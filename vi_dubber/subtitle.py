"""Parse YouTube WebVTT (karaoke-tagged) subtitles into timed sentences."""

from __future__ import annotations

import re
from pathlib import Path

TS_LINE = re.compile(
    r"^\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[.,]\d{3})"
)
KARAOKE = re.compile(r"<(\d{2}:\d{2}:\d{2})[.,](\d{3})><c>(.*?)</c>", re.DOTALL)
PUNCT_END = re.compile(r"[.!?。…]+\s*")
SPEAKER_LABEL = re.compile(r"^(?:-\s*)?\[[^\]]*\]\s*")
PAREN_NOTE = re.compile(r"\([^)]*\)")


# ── helpers ──────────────────────────────────────────────────────────────────

def _ts(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _clean(s: str) -> str:
    """Remove speaker labels, parenthetical notes, and excess punctuation."""
    s = SPEAKER_LABEL.sub("", s)
    s = PAREN_NOTE.sub("", s)
    s = re.sub(r"[,;:\s]+$", "", s)
    s = re.sub(r"^[,;:\s]+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _is_boundary(text: str, pos: int) -> bool:
    """Return True if the character at *pos* ends a sentence.

    A literal ``.`` does NOT end a sentence when surrounded by digits
    (``10.000``, ``3.14``) or two letters (``U.S.A``).
    """
    if text[pos] != ".":
        return True
    prev = text[pos - 1] if pos > 0 else ""
    nxt = text[pos + 1] if pos + 1 < len(text) else ""
    if prev.isdigit() and nxt.isdigit():
        return False
    if prev.isalpha() and nxt.isalpha():
        return False
    return True


# ── raw cue iterator ──────────────────────────────────────────────────────────

def _iter_cues(path: Path):
    """Yield ``(t0, t1, payload_lines)`` for every VTT cue."""
    lines = (
        path.read_text(encoding="utf-8", errors="replace")
        .replace("\r\n", "\n")
        .split("\n")
    )
    i, n = 0, len(lines)
    while i < n:
        m = TS_LINE.match(lines[i])
        if not m:
            i += 1
            continue
        t0, t1 = _ts(m.group(1)), _ts(m.group(2))
        i += 1
        while i < n and not lines[i].strip():
            i += 1
        payload: list[str] = []
        while i < n and lines[i].strip() and not TS_LINE.match(lines[i]):
            if lines[i].strip().upper().startswith("NOTE"):
                break
            payload.append(lines[i].strip())
            i += 1
        while i < n and not lines[i].strip():
            i += 1
        yield t0, t1, payload


# ── karaoke → timed fragments ─────────────────────────────────────────────────

def _karaoke_blob(payload: list[str]) -> str:
    cleaned = [_clean(ln) for ln in payload]
    tagged = [ln for ln in cleaned if re.search(r"<\d{2}:\d{2}:\d{2}", ln)]
    return " ".join(tagged) if tagged else " ".join(cleaned)


def _karaoke_time(m: re.Match) -> float:
    return _ts(f"{m.group(1)}.{m.group(2)}")


def _fragments(t0: float, t1: float, blob: str) -> list[tuple[float, float, str]]:
    matches = list(KARAOKE.finditer(blob))
    if not matches:
        t = re.sub(r"<[^>]+>", "", blob)
        t = re.sub(r"\s+", " ", t).strip()
        return [(t0, t1, t)] if t else []

    out: list[tuple[float, float, str]] = []
    pre = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", blob[: matches[0].start()])).strip()
    if pre:
        out.append((t0, _karaoke_time(matches[0]), pre))
    for j, m in enumerate(matches):
        ts = _karaoke_time(m)
        te = _karaoke_time(matches[j + 1]) if j + 1 < len(matches) else t1
        out.append((ts, te, m.group(3).replace("\n", " ")))
    post = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", blob[matches[-1].end() :])).strip()
    if post:
        out.append((_karaoke_time(matches[-1]), t1, post))
    return out


# ── timed character stream ────────────────────────────────────────────────────

def build_timed_text_stream(path: Path) -> tuple[str, list[float]]:
    """Return ``(full_text, times)`` where ``times[i]`` is the timestamp of
    ``full_text[i]``.  Parenthetical notes spanning multiple cues are removed
    in a second pass that keeps the ``times`` array in sync.
    """
    frags: list[tuple[float, float, str]] = []
    for t0, t1, payload in _iter_cues(path):
        if t1 - t0 < 0.05:
            continue
        frags.extend(_fragments(t0, t1, _karaoke_blob(payload)))

    chars: list[str] = []
    times: list[float] = []
    for ts, te, raw in frags:
        piece = raw.strip()
        if not piece:
            continue
        if chars:
            chars.append(" ")
            times.append(ts)
        n = len(piece)
        for k in range(n):
            t = (ts + te) / 2 if n == 1 else ts + (te - ts) * (k / (n - 1))
            times.append(t)
        chars.extend(piece)

    # Remove parenthetical notes that span multiple fragments
    clean_c: list[str] = []
    clean_t: list[float] = []
    depth = 0
    for ch, t in zip(chars, times):
        if ch == "(":
            depth += 1
        if depth == 0:
            clean_c.append(ch)
            clean_t.append(t)
        if ch == ")" and depth > 0:
            depth -= 1

    joined = re.sub(r" {2,}", " ", "".join(clean_c)).strip()
    final_t: list[float] = []
    j = 0
    for ch in joined:
        while j < len(clean_c) and clean_c[j] != ch:
            j += 1
        final_t.append(clean_t[j] if j < len(clean_t) else (clean_t[-1] if clean_t else 0.0))
        j += 1
    return joined, final_t


# ── sentence splitting ────────────────────────────────────────────────────────

def split_sentences(text: str) -> list[tuple[int, int, str]]:
    """Return ``[(start, end, sentence), …]`` splitting on sentence-ending
    punctuation while ignoring ``.`` inside numbers or abbreviations.
    """
    spans: list[tuple[int, int, str]] = []
    start = 0
    for m in PUNCT_END.finditer(text):
        if not _is_boundary(text, m.start()):
            continue
        sent = text[start : m.end()].strip()
        if sent:
            spans.append((start, m.end(), sent))
        start = m.end()
    if start < len(text):
        tail = text[start:].strip()
        if tail:
            spans.append((start, len(text), tail))
    return spans


# ── public API ────────────────────────────────────────────────────────────────

def sentences_with_timing(path: Path) -> list[tuple[float, float, str]]:
    """Parse a YouTube ``.vi.vtt`` file and return timed sentences.

    Returns a list of ``(t0, t1, sentence_text)`` tuples.
    """
    text, times = build_timed_text_stream(path)
    if not text or len(times) != len(text):
        raise RuntimeError(f"timed-text length mismatch for {path.name}")
    out: list[tuple[float, float, str]] = []
    for s0, s1, sent in split_sentences(text):
        lo = min(s0, len(text) - 1)
        hi = min(s1 - 1, len(text) - 1)
        if hi < lo:
            continue
        t0, t1 = times[lo], times[hi]
        if t1 < t0:
            t0, t1 = t1, t0
        t1 = max(t1, t0 + 0.02)
        out.append((t0, t1, sent))
    return out


def fmt_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    s, ms = divmod(ms, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def write_normalized_vtt(src: Path, cues: list[tuple[float, float, str]]) -> Path:
    """Write a clean sentence-per-cue WebVTT file next to *src*."""
    out = src.with_name(f"{src.stem}_normalized.vtt")
    lines = [
        "WEBVTT",
        "Language: vi",
        "",
        "NOTE",
        "Normalized: sentence-split via karaoke timestamps.",
        "",
    ]
    for t0, t1, text in cues:
        lines += [f"{fmt_ts(t0)} --> {fmt_ts(t1)}", text, ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
