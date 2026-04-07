"""Merge original video (at reduced volume) with Vietnamese TTS audio via ffmpeg."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from rich.console import Console

console = Console()

# Audio codec + bitrate + required sample-rate per container
_CONTAINER_AUDIO: dict[str, tuple[str, str, str | None]] = {
    ".mp4":  ("aac",     "192k", None),
    ".webm": ("libopus", "128k", "48000"),
    ".mkv":  ("aac",     "192k", None),
}


def _verbose() -> bool:
    return bool(os.environ.get("VI_DUBBER_VERBOSE"))


def _probe_has_audio(path: Path) -> bool:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name",
            "-of", "default=nw=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return bool(r.stdout.strip())


def find_bundles(output_dir: Path) -> list[tuple[Path, Path, Path]]:
    """Return ``[(video_src, wav_vi, video_out), …]`` not yet processed."""
    bundles: list[tuple[Path, Path, Path]] = []
    for norm in sorted(output_dir.glob("*_normalized.vtt")):
        base = norm.stem.removesuffix("_normalized")
        root = base.removesuffix(".vi") if base.endswith(".vi") else base
        wav = output_dir / f"{root}_vi_timeline.wav"
        if not wav.exists():
            wav = output_dir / f"{base}_vi_timeline.wav"
        if not wav.exists():
            continue
        for ext in (".mp4", ".webm", ".mkv"):
            vid = output_dir / f"{root}{ext}"
            if vid.exists():
                bundles.append((vid, wav, output_dir / f"{root}_vi{ext}"))
                break
    return bundles


def merge_audio(
    output_dir: Path,
    *,
    orig_volume: float = 0.20,
) -> None:
    """Mix TTS audio into every video found in *output_dir*.

    The original audio track is attenuated to *orig_volume* (0–1).
    Output files are named ``<stem>_vi<ext>`` and use the same container as
    the source.  Already-processed files are skipped.

    Requires ``ffmpeg`` on ``$PATH``  (``brew install ffmpeg`` on macOS).
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg not found. Install it with:  brew install ffmpeg"
        )
    bundles = find_bundles(output_dir)
    if not bundles:
        console.print(
            "[yellow][merge] No bundles found: need video (.mp4/.webm/.mkv) + "
            "*_vi_timeline.wav in the output directory.[/yellow]"
        )
        return

    for vid, wav, out in bundles:
        if out.exists():
            console.print(f"[dim][merge] Skip (exists): {out.name}[/dim]")
            continue

        ext = vid.suffix.lower()
        acodec, abitrate, asr = _CONTAINER_AUDIO.get(ext, ("aac", "192k", None))
        has_orig = _probe_has_audio(vid)

        console.print(f"[cyan][merge][/cyan] {vid.name}")
        if _verbose():
            console.print(f"        + {wav.name}")
            console.print(f"        → {out.name}  ({acodec} {abitrate}, orig={orig_volume:.0%})")

        resample = f":out_sample_rate={asr}" if asr else ""
        tts_filt = f"[1:a]aresample=async=1{resample}[a_tts]"

        if has_orig:
            fc = (
                f"[0:a]volume={orig_volume}[a_orig];"
                f"{tts_filt};"
                "[a_orig][a_tts]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a_out]"
            )
        else:
            fc = tts_filt.replace("[a_tts]", "[a_out]")

        cmd = [
            "ffmpeg", "-y",
            "-i", str(vid),
            "-i", str(wav),
            "-filter_complex", fc,
            "-map", "0:v",
            "-map", "[a_out]",
            "-c:v", "copy",
            "-c:a", acodec,
            "-b:a", abitrate,
            str(out),
        ]
        result = subprocess.run(
            cmd,
            capture_output=not _verbose(),
            text=True,
        )
        if result.returncode == 0:
            size_mb = out.stat().st_size / 1024 / 1024
            console.print(f"[green]✓[/green] {out.name} ({size_mb:.1f} MB)")
        else:
            err = result.stderr[-1200:] if result.stderr else "(no stderr)"
            console.print(f"[red][merge] ffmpeg error:[/red]\n{err}")
