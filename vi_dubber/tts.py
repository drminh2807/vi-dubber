"""Vietnamese TTS synthesis + timeline-aligned audio mixing."""

from __future__ import annotations

import os
import re
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from vieneu import Vieneu

_TS_LINE = re.compile(
    r"^\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[.,]\d{3})"
)

RATE_MAX = 2.8      # maximum time-compression ratio (avoids severe artifacts)
STRETCH_N_FFT = 512  # small FFT window → less reverb on speech
STRETCH_HOP = STRETCH_N_FFT // 4

console = Console()


def _verbose() -> bool:
    return bool(os.environ.get("VI_DUBBER_VERBOSE"))


def _ts(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_normalized_cues(path: Path) -> list[tuple[float, float, str]]:
    """Parse a ``*_normalized.vtt`` file produced by :mod:`vi_dubber.subtitle`.

    Returns ``[(t0, t1, text), …]``.  NOTE blocks spanning multiple lines are
    skipped correctly.
    """
    lines = (
        path.read_text(encoding="utf-8", errors="replace")
        .replace("\r\n", "\n")
        .split("\n")
    )
    i, n = 0, len(lines)
    out: list[tuple[float, float, str]] = []
    while i < n:
        m = _TS_LINE.match(lines[i])
        if not m:
            i += 1
            continue
        t0, t1 = _ts(m.group(1)), _ts(m.group(2))
        i += 1
        while i < n and not lines[i].strip():
            i += 1
        if i >= n or _TS_LINE.match(lines[i]):
            continue
        text_lines: list[str] = []
        while i < n and lines[i].strip() and not _TS_LINE.match(lines[i]):
            ls = lines[i].strip()
            if ls.upper().startswith("NOTE"):
                i += 1
                while i < n and lines[i].strip():
                    i += 1
                while i < n and not lines[i].strip():
                    i += 1
                continue
            text_lines.append(ls)
            i += 1
        text = " ".join(text_lines).strip()
        while i < n and not lines[i].strip():
            i += 1
        if text:
            out.append((t0, t1, text))
    return out


def _mono_f32(y: np.ndarray) -> np.ndarray:
    y = np.asarray(y, dtype=np.float32)
    return y.mean(axis=1).astype(np.float32) if y.ndim > 1 else y


def compress_to_duration(y: np.ndarray, sr: int, dur_target: float) -> np.ndarray:
    """Time-compress *y* to fit *dur_target* seconds (pitch-preserving).

    If *y* is already shorter than the target window it is returned as-is
    (no stretching, no padding) to avoid phase-vocoder artifacts.
    Peak level is restored after compression.
    """
    dur_target = max(dur_target, 0.02)
    dur_actual = len(y) / sr
    if dur_actual < 1e-6:
        return np.zeros(0, dtype=np.float32)
    rate = dur_actual / dur_target
    if rate <= 1.0:
        return np.asarray(y, dtype=np.float32)  # already fits — no-op
    rate = float(np.clip(rate, 1.0, RATE_MAX))
    n_target = int(round(dur_target * sr))
    y_st = librosa.effects.time_stretch(
        np.asarray(y, dtype=np.float32),
        rate=rate,
        n_fft=STRETCH_N_FFT,
        hop_length=STRETCH_HOP,
    )
    in_peak = float(np.max(np.abs(y)))
    out_peak = float(np.max(np.abs(y_st)))
    if out_peak > 1e-8 and in_peak > 1e-8:
        y_st = y_st * (in_peak / out_peak)
    if len(y_st) > n_target:
        y_st = y_st[:n_target]
    elif len(y_st) < n_target:
        y_st = np.pad(y_st, (0, n_target - len(y_st)))
    return np.clip(y_st, -1.0, 1.0).astype(np.float32)


def synthesize_timeline(
    norm_vtt: Path,
    output_dir: Path,
    *,
    tts: Vieneu | None = None,
) -> Path | None:
    """Synthesize Vietnamese TTS for every sentence in *norm_vtt* and mix
    them onto a single timeline WAV.

    Returns the path to the written WAV, or ``None`` if there were no cues.
    Skips synthesis if the output file already exists.
    """
    cues = parse_normalized_cues(norm_vtt)
    if not cues:
        console.print(f"[yellow][tts] Skip (no cues): {norm_vtt.name}[/yellow]")
        return None

    base = norm_vtt.stem.removesuffix("_normalized")
    root = base.removesuffix(".vi") if base.endswith(".vi") else base
    out_wav = output_dir / f"{root}_vi_timeline.wav"

    if out_wav.exists():
        console.print(f"[dim][tts] Skip (exists): {out_wav.name}[/dim]")
        return out_wav

    _tts = tts or Vieneu()
    sr = int(_tts.sample_rate)

    total_end = max(t1 for _, t1, _ in cues) + 0.5
    mix = np.zeros(int(round(total_end * sr)), dtype=np.float32)

    progress_cols = [
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    ]
    with Progress(*progress_cols, console=console, transient=not _verbose()) as prog:
        task = prog.add_task(f"[cyan]{out_wav.name}[/cyan]", total=len(cues))
        for t0, t1, text in cues:
            if text.strip():
                raw = _mono_f32(_tts.infer(text=text))
                seg = compress_to_duration(raw, sr, max(t1 - t0, 0.02))
                start = int(round(t0 * sr))
                end = start + len(seg)
                if end > len(mix):
                    mix = np.pad(mix, (0, end - len(mix)))
                mix[start:end] += seg
            prog.advance(task)

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 1.0:
        mix = np.clip(mix * (0.98 / peak), -1.0, 1.0)

    sf.write(str(out_wav), mix, sr, subtype="PCM_16")
    console.print(f"[green]✓[/green] {out_wav.name} ({mix.shape[0] / sr:.1f}s, sr={sr})")
    return out_wav
