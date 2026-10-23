# Installation and setup

[Back to the README](../README.md)

This guide sets up Savant in a local Python environment. Use the same environment to run the aligner and the browser editor.

## Requirements

- **Python 3.10–3.12, 64-bit** is a practical choice for the current PyTorch / WhisperX dependencies.
- **FFmpeg** must be installed and available on your `PATH`.
- An internet connection is needed for initial package and model downloads.
- Several gigabytes of free disk space are recommended. A supported NVIDIA GPU can speed up processing; CPU mode is also available.

## 1. Install FFmpeg

On Windows, one option is:

```powershell
winget install --id Gyan.FFmpeg.Shared --exact
```

On macOS with Homebrew:

```bash
brew install ffmpeg
```

On Debian or Ubuntu Linux:

```bash
sudo apt update
sudo apt install ffmpeg
```

Open a new terminal after installing, then verify:

```bash
ffmpeg -version
```

## 2. Create a Python environment

Open a terminal in the Savant project folder and create a virtual environment:

```bash
python -m venv .venv
```

Activate it.

**Windows PowerShell:**

```powershell
./.venv/Scripts/Activate.ps1
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

Install the base aligner:

```bash
python -m pip install --upgrade pip
python -m pip install whisperx
```

PyTorch installation differs between CPU and CUDA setups. If you need a particular GPU build, follow the current [WhisperX installation instructions](https://github.com/m-bain/whisperX) before installing or changing PyTorch packages.

## 3. Check the setup

Run:

```bash
python lyrics_align.py --doctor
```

The report lists Python, FFmpeg, PyTorch, CUDA, WhisperX, and any detected optional components. Resolve missing FFmpeg or dependency errors before running alignment.

## 4. Try a first alignment

Prepare a plain-text file with the **correct lyrics**, usually one lyric line per line. Then run:

```powershell
python lyrics_align.py --audio "D:/Music/Song.flac" --lyrics "D:/Lyrics/Song.txt" --language en
```

Savant estimates the timing of the lyrics you supply; it does not transcribe the song. By default, the LRC output is written beside the audio file. Use `--dry-run` to validate inputs and planned outputs before loading a model.

See the [CLI reference](cli-reference.md) for more examples and options.

## 5. Open the browser app

With the environment activated:

```bash
python lyrics_editor.py
```

Open the local URL shown in the terminal, normally `http://127.0.0.1:8765`. The **Edit** screen is for reviewing existing LRC/TTML files; **Generate** runs the CLI through the local Python server. See the [browser editor guide](editor.md) for details.

## Optional features

- **Vocal separation:** install `demucs-infer` in the same Python environment if you want to use `--separate-vocals`:
  ```bash
  python -m pip install demucs-infer
  ```
  Its first use may download a model.
- **TIFA singing-aware alignment:** TIFA requires its own source checkout, isolated Python environment, and model checkpoint. Follow the [TIFA guide](tifa.md); it is not needed for standard WhisperX alignment.

## Keep the environment consistent

Run `python lyrics_align.py` and `python lyrics_editor.py` from the same activated environment. The editor launches the CLI with the Python interpreter running the editor, so installing dependencies into a different environment will not make them available to Generate.
