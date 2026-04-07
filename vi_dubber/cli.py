"""Command-line entry point for vi-dubber."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

console = Console()


def _set_verbose(v: bool) -> None:
    os.environ["VI_DUBBER_VERBOSE"] = "1" if v else ""


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vi-dubber",
        description=(
            "Dub YouTube videos with Vietnamese TTS.\n\n"
            "Usage:\n"
            "  vi-dubber <URL> [URL …]          — run the full pipeline\n"
            "  vi-dubber <step> [options]        — run one step\n\n"
            "Pipeline steps:\n"
            "  1. download  — fetch video + vi subtitles via yt-dlp\n"
            "  2. normalize — parse karaoke VTT → sentence-level timing\n"
            "  3. tts       — synthesize speech, compress to timeline\n"
            "  4. merge     — mix TTS + original audio into new video"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=Path("Output"),
        metavar="DIR",
        help="Directory for all output files (default: Output/)",
    )
    p.add_argument(
        "--orig-volume",
        type=float,
        default=0.20,
        metavar="VOL",
        help="Original audio volume fraction in output video (default: 0.20)",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed progress output",
    )
    sub = p.add_subparsers(dest="command")

    # ── download ─────────────────────────────────────────────────────────────
    dl = sub.add_parser("download", help="Step 1: download video + subtitles.")
    dl.add_argument("urls", nargs="+", metavar="URL")

    # ── normalize ────────────────────────────────────────────────────────────
    sub.add_parser("normalize", help="Step 2: normalize *.vi.vtt → *_normalized.vtt.")

    # ── tts ──────────────────────────────────────────────────────────────────
    sub.add_parser("tts", help="Step 3: synthesize TTS timeline WAV.")

    # ── merge ─────────────────────────────────────────────────────────────────
    sub.add_parser("merge", help="Step 4: merge TTS audio into video.")

    return p


def _step_header(n: int, label: str, detail: str = "") -> None:
    suffix = f"  [dim]{detail}[/dim]" if detail else ""
    console.print(f"\n[bold cyan]Step {n}/4 — {label}[/bold cyan]{suffix}")


def _run_normalize(output_dir: Path, vtts: list[Path] | None = None) -> None:
    from vi_dubber.subtitle import sentences_with_timing, write_normalized_vtt

    if vtts is None:
        vtts = sorted(output_dir.glob("*.vi.vtt"))
    if not vtts:
        console.print("[yellow][normalize] No *.vi.vtt found — run 'download' first.[/yellow]")
        return
    for vtt in vtts:
        out = vtt.with_name(f"{vtt.stem}_normalized.vtt")
        if out.exists():
            console.print(f"[dim][normalize] Skip (exists): {out.name}[/dim]")
            continue
        try:
            cues = sentences_with_timing(vtt)
        except Exception as exc:
            console.print(f"[red][normalize] Error for {vtt.name}: {exc}[/red]")
            continue
        if not cues:
            console.print(f"[yellow][normalize] Skip (no cues): {vtt.name}[/yellow]")
            continue
        write_normalized_vtt(vtt, cues)
        console.print(f"[green]✓[/green] {out.name} ({len(cues)} sentences)")


def _run_tts(output_dir: Path) -> None:
    from vi_dubber.tts import synthesize_timeline
    from vieneu import Vieneu

    norms = sorted(output_dir.glob("*_normalized.vtt"))
    if not norms:
        console.print("[yellow][tts] No *_normalized.vtt found — run 'normalize' first.[/yellow]")
        return
    tts = Vieneu()
    for norm in norms:
        synthesize_timeline(norm, output_dir, tts=tts)


def _run_pipeline(urls: list[str], output_dir: Path, orig_volume: float) -> None:
    from vi_dubber.download import download_with_subs
    from vi_dubber.merge import merge_audio

    console.print(Panel(
        f"[bold]vi-dubber[/bold] — Vietnamese TTS dubbing pipeline\n"
        f"[dim]{len(urls)} URL(s) → {output_dir}/[/dim]",
        border_style="cyan",
    ))

    _step_header(1, "Download", "video + subtitles via yt-dlp")
    vtts = download_with_subs(urls, output_dir)

    _step_header(2, "Normalize", "karaoke VTT → sentence-level timing")
    _run_normalize(output_dir, vtts)

    _step_header(3, "TTS", "Vietnamese speech synthesis")
    _run_tts(output_dir)

    _step_header(4, "Merge", f"original audio at {orig_volume:.0%} + TTS → video")
    merge_audio(output_dir, orig_volume=orig_volume)

    console.print("\n[bold green]✓ Pipeline complete.[/bold green]")


def main(argv: list[str] | None = None) -> int:
    _SUBCOMMANDS = {"download", "normalize", "tts", "merge"}
    raw = argv if argv is not None else sys.argv[1:]

    # Parse verbose flag early so we can suppress library noise before imports.
    verbose = "-v" in raw or "--verbose" in raw
    _set_verbose(verbose)
    if not verbose:
        # Suppress yt-dlp / torch / transformers noise
        os.environ.setdefault("PYTHONWARNINGS", "ignore")
        # Redirect stderr for noisy libraries via log level
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        os.environ.setdefault("DATASETS_VERBOSITY", "error")

    positionals = [a for a in raw if not a.startswith("-")]
    if positionals and positionals[0] not in _SUBCOMMANDS:
        flags = [a for a in raw if a.startswith("-")]
        p = _build_parser()
        args = p.parse_args(flags)
        output_dir: Path = args.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        urls = [a for a in raw if not a.startswith("-")]
        _run_pipeline(urls, output_dir, args.orig_volume)
        return 0

    args = _build_parser().parse_args(raw)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    from vi_dubber.download import download_with_subs
    from vi_dubber.merge import merge_audio

    if args.command is None:
        _build_parser().print_help()
        return 0

    elif args.command == "download":
        download_with_subs(args.urls, output_dir)

    elif args.command == "normalize":
        _run_normalize(output_dir)

    elif args.command == "tts":
        _run_tts(output_dir)

    elif args.command == "merge":
        merge_audio(output_dir, orig_volume=args.orig_volume)

    return 0


if __name__ == "__main__":
    sys.exit(main())
