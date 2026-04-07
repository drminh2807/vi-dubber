"""Download YouTube video + Vietnamese subtitles via yt-dlp."""

from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console
from yt_dlp import YoutubeDL

console = Console()


def _verbose() -> bool:
    return bool(os.environ.get("VI_DUBBER_VERBOSE"))


def _extract_video_id(url: str) -> str | None:
    """Return the YouTube video ID from a URL, or None if it cannot be determined."""
    quiet = not _verbose()
    with YoutubeDL({"quiet": quiet, "no_warnings": quiet, "ignoreerrors": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        if info:
            return info.get("id")
    return None


def _vtt_exists_for_id(output_dir: Path, video_id: str) -> bool:
    """Return True if a *.vi.vtt whose filename contains *video_id* already exists."""
    return any(True for _ in output_dir.glob(f"*{video_id}*.vi.vtt"))


def download_with_subs(urls: list[str], output_dir: Path) -> list[Path]:
    """Download video + Vietnamese subtitles for each URL.

    Downloads both manual and auto-generated subtitles for language ``vi``.
    Skips a URL if a ``*.vi.vtt`` file whose name contains that video's ID
    already exists in *output_dir*.

    Returns the list of ``.vi.vtt`` paths that correspond to the requested
    URLs (already-existing files are included).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Resolve video IDs once so we don't repeat the network call.
    url_ids: dict[str, str | None] = {u: _extract_video_id(u) for u in urls}

    pending: list[str] = []
    for url, vid_id in url_ids.items():
        if vid_id and _vtt_exists_for_id(output_dir, vid_id):
            existing = next(output_dir.glob(f"*{vid_id}*.vi.vtt"))
            console.print(f"[dim][download] Skip (exists): {existing.name}[/dim]")
        else:
            pending.append(url)

    if pending:
        urls_still_needed = [
            u for u in pending
            if not (vid_id := url_ids.get(u)) or not _vtt_exists_for_id(output_dir, vid_id)
        ]
        if urls_still_needed:
            quiet = not _verbose()
            opts: dict = {
                "paths": {"home": str(output_dir)},
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["vi"],
                "skip_download": False,
                "ignoreerrors": True,
                "quiet": quiet,
                "no_warnings": quiet,
                "sleep_interval_subtitles": 1,
                "retries": 5,
                "fragment_retries": 5,
            }
            console.print(f"[cyan][download][/cyan] Trying subtitle lang [vi] for {len(urls_still_needed)} URL(s) …")
            with YoutubeDL(opts) as ydl:
                ydl.download(urls_still_needed)

    # Collect only the .vi.vtt files that belong to the requested URLs.
    result: list[Path] = []
    for vid_id in url_ids.values():
        if vid_id:
            matches = sorted(output_dir.glob(f"*{vid_id}*.vi.vtt"))
            result.extend(matches)

    console.print(f"[green]✓[/green] {len(result)} .vi.vtt file(s) ready.")
    return result
