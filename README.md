# vi-dubber

Automatically dub YouTube videos with synchronized Vietnamese TTS.

https://github.com/user-attachments/assets/demo.webm

**Pipeline:**

```
YouTube URL
    │
    ▼  Step 1 — download
    │  yt-dlp downloads video + Vietnamese subtitles (.vi.vtt)
    │  Falls back to auto-translated vi-en if vi is unavailable
    │
    ▼  Step 2 — normalize
    │  Parses YouTube karaoke-tagged VTT → sentence-level timing
    │  Removes speaker labels [Name], sound effects (description)
    │  Handles numbers (10.000) and abbreviations (U.S.A) correctly
    │
    ▼  Step 3 — tts
    │  Vieneu TTS synthesizes each sentence
    │  Compresses audio to fit timeline window (pitch-preserving)
    │  Outputs single *_vi_timeline.wav
    │
    ▼  Step 4 — merge (requires ffmpeg)
       ffmpeg mixes original audio (20% volume) + TTS audio
       Outputs *_vi.webm / *_vi.mp4 in the same container format
```

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) on `$PATH` (`brew install ffmpeg` on macOS)
- Apple Silicon Mac recommended for Vieneu Metal acceleration

## Installation

### 1. Clone

```bash
git clone https://github.com/drminh2807/vi-dubber.git
cd vi-dubber
```

### 2. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install yt-dlp (always use latest)

```bash
pip install --upgrade "yt-dlp[default,curl-cffi]"
```

### 4. Install Vieneu (macOS Apple Silicon — Metal)

```bash
pip install vieneu --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/metal/
```

For other platforms, omit the `--extra-index-url` flag.

### 5. Install remaining dependencies

```bash
pip install -r requirements.txt
```

That's it — no extra install step required. You can run the tool directly with `python -m vi_dubber` (see Usage below).

> **Optional:** `pip install -e .` installs the `vi-dubber` console command globally in the venv so you can type `vi-dubber` instead of `python -m vi_dubber`.

## Usage

### Full pipeline

```bash
python -m vi_dubber https://youtu.be/XXXXXXXXXXX
```

Multiple URLs at once:

```bash
python -m vi_dubber https://youtu.be/AAA https://youtu.be/BBB
```

Options:

| Flag                          | Default   | Description                                |
| ----------------------------- | --------- | ------------------------------------------ |
| `-o DIR` / `--output-dir DIR` | `Output/` | Directory for all output files             |
| `--orig-volume VOL`           | `0.20`    | Original audio volume (0–1) in final video |
| `-v` / `--verbose`            | off       | Show detailed logs and library output      |

### Run individual steps

```bash
# Step 1: download video + subtitles
python -m vi_dubber download https://youtu.be/...

# Step 2: normalize subtitles (sentence splitting + timing)
python -m vi_dubber normalize

# Step 3: TTS synthesis
python -m vi_dubber tts

# Step 4: merge into video
python -m vi_dubber merge --orig-volume 0.15
```

Each step skips files that already exist, so you can re-run safely.

### Use as a library

```python
from pathlib import Path
from vi_dubber.download import download_with_subs
from vi_dubber.subtitle import sentences_with_timing, write_normalized_vtt
from vi_dubber.tts import synthesize_timeline
from vi_dubber.merge import merge_audio

output = Path("Output")
download_with_subs(["https://youtu.be/..."], output)

for vtt in sorted(output.glob("*.vi.vtt")):
    cues = sentences_with_timing(vtt)
    norm = write_normalized_vtt(vtt, cues)
    synthesize_timeline(norm, output)

merge_audio(output, orig_volume=0.20)
```

## Output files

| File                               | Description                                  |
| ---------------------------------- | -------------------------------------------- |
| `Output/<title>.vi.vtt`            | Original Vietnamese subtitles                |
| `Output/<title>.vi_normalized.vtt` | Sentence-split subtitles with karaoke timing |
| `Output/<title>_vi_timeline.wav`   | TTS audio aligned to video timeline          |
| `Output/<title>_vi.webm`           | Final dubbed video                           |

## Notes on yt-dlp

yt-dlp releases frequently to keep up with YouTube changes. Always upgrade
before a new download session:

```bash
pip install --upgrade "yt-dlp[default,curl-cffi]"
```

## Acknowledgements

Vietnamese TTS powered by [vieneu](https://github.com/pnnbao97/VieNeu-TTS) — a beautiful open-source Vietnamese TTS engine. Thank you for making high-quality Vietnamese speech synthesis accessible to everyone.

## License

MIT — see [LICENSE](LICENSE).
