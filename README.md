# Savant - Local lyric alignment generator and editor

**Savant lines up lyrics with a song, then helps you fine-tune the timing.** It includes a command-line aligner and a browser-based editor with a **Generate** panel.

Savant is a *forced aligner*, not a lyric transcription tool: provide the correct lyrics, and it estimates when they are sung. Processing runs locally; first-time setup may download packages and model weights.

## Get started

1. Install Python 3.10–3.12 (64-bit) and [FFmpeg](https://ffmpeg.org/).
2. In this project folder, create and activate a virtual environment, then install WhisperX:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install whisperx
   ```
   On macOS/Linux, activate with `source .venv/bin/activate`.
3. Check your setup:
   ```bash
   python lyrics_align.py --doctor
   ```
4. Align a song:
   ```powershell
   python lyrics_align.py --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en
   ```
5. Or open the browser app with `python lyrics_editor.py` and use **Generate** to run the CLI or **Edit** to fine-tune existing LRC/TTML files.

By default, alignment writes an LRC beside the audio. Existing outputs are protected unless you explicitly enable overwriting.

## Choose a guide

- [Installation and setup](docs/installation.md) — requirements, virtual environments, and dependency checks.
- [Browser editor and Generate panel](docs/editor.md) — drag-and-drop, CLI options, progress, logs, and outputs.
- [Command-line reference](docs/cli-reference.md) — every aligner flag with examples.
- [Output formats and singer styling](docs/output-formats.md) — LRC, word-timed TTML, and multi-singer metadata.
- [TIFA singing-aware alignment](docs/tifa.md) — optional setup, settings, diagnostics, and limitations.
- [Troubleshooting](docs/troubleshooting.md) — common setup and alignment problems.
- [Development guide](DEVELOPMENT.md) — project architecture, validation workflow, user-data safety, and contributor/AI collaboration expectations.

**New to Savant?** Start with [Installation and setup](docs/installation.md), then try the basic alignment command above. Optional TIFA and vocal-separation features can be added later.
