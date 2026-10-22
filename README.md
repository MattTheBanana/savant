# Savant

**Savant aligns supplied lyrics to audio and helps you refine the timing.** It includes a command-line aligner and a browser-based editor for reviewing line-by-line LRC and word-by-word TTML lyrics.

Savant is a *forced aligner*, not a speech-to-text tool: you provide the correct lyrics, and it estimates when those words are sung. Model inference runs locally; the first run may download Python packages and model weights.

## What you can do

- **Align lyrics:** generate standard `.lrc` timestamps from an audio file and a plain-text or existing LRC lyric file.
- **Create karaoke timing:** write a word-timed `.ttml` sidecar for compatible players, including Navidrome.
- **Review and correct:** open the local editor to adjust timestamps, inspect a waveform, edit word cues, and export LRC or TTML.
- **Handle tricky recordings:** optionally try TIFA, a singing-aware aligner, vocal isolation, timing offsets, and review reports.

## Quick start

### Requirements

- Python 3.10–3.12 (64-bit is a practical choice for the current PyTorch/WhisperX stack).
- FFmpeg available on your `PATH`.
- Internet access for initial dependency and model downloads. A supported NVIDIA GPU can speed up inference; CPU is also available.

On Windows, FFmpeg can be installed with:

```powershell
winget install --id Gyan.FFmpeg.Shared --exact
```

Create a virtual environment and install WhisperX. PyTorch/CUDA installation can vary by machine; use the [WhisperX installation notes](https://github.com/m-bain/whisperX) if you need a specific GPU build.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install whisperx
ffmpeg -version
python lyrics_align.py --doctor
```

On macOS/Linux, activate with `source .venv/bin/activate` instead. The optional vocal-separation and TIFA backends need their own dependencies and model files; see their options below and check `--doctor`.

### Align a song

Place the correct lyrics in a plain text file with one lyric line per line, or provide an existing LRC to realign.

```powershell
python lyrics_align.py --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en
```

By default, Savant writes `Song.lrc` beside the audio. Existing files are not overwritten unless you pass `--overwrite`.

To write word-level TTML as well:

```powershell
python lyrics_align.py --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en --word-level
```

To test the paths and lyric parsing without loading an alignment model:

```powershell
python lyrics_align.py --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --dry-run
```

For a basic timing adjustment, negative offsets move timings earlier and positive offsets move them later:

```powershell
python lyrics_align.py --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --offset -0.15 --overwrite
```

### Open the browser editor

```powershell
python lyrics_editor.py
```

This opens Savant at [http://127.0.0.1:8765](http://127.0.0.1:8765). Choose audio and lyrics in the browser, or drag and drop them into the page. The editor uses Python's standard-library web server and binds only to `127.0.0.1`; your audio and lyrics are opened locally by the browser and are not uploaded. Press **Ctrl+C** in the terminal to stop the server.

If the port is busy, use `python lyrics_editor.py --port 8766`. To print the address without opening the browser automatically, add `--no-browser`.

## Command-line reference

Run `python lyrics_align.py --help` for the live help text and `python lyrics_align.py --doctor` to check your environment.

### Inputs and outputs

| Option | Purpose |
| --- | --- |
| `--audio PATH` | Source audio file (for example FLAC, MP3, WAV, or M4A). |
| `--lyrics PATH` | Correct lyrics in TXT or LRC format. Required for alignment. |
| `--adjust-lrc PATH` | Adjust an existing LRC without running the model. |
| `--output PATH` | Set the LRC output path. By default, output is based on the audio filename. |
| `--word-level` | Also create a word-timed TTML sidecar. LRC is still written as a compatibility fallback. |
| `--ttml-output PATH` | Choose a TTML sidecar path; also enables TTML output. |
| `--singer-config PATH` | JSON configuration for named singers, TTML styles, and colors. |

### Alignment and timing

| Option | Purpose |
| --- | --- |
| `--language CODE` | Alignment language (default: `en`). Availability depends on the aligner/model. |
| `--aligner whisperx|tifa` | Choose the alignment backend (default: `whisperx`). TIFA is singing-aware and currently supports English in this integration. |
| `--align-model NAME` | Custom Hugging Face/wav2vec2 model for the WhisperX backend. |
| `--device auto|cpu|cuda` | Select the inference device (default: `auto`). |
| `--offset SECONDS` | Shift all output timings. Negative is earlier; positive is later. |
| `--line-offsets PATH` | JSON mapping 1-based cleaned lyric line numbers to timing offsets in seconds. |
| `--phrase-offsets PATH` | JSON mapping exact cleaned lyric-line text to additional offsets. All matching repeated lines receive the correction. |
| `--refine` | Run a narrow second alignment pass with WhisperX; ignored by TIFA. |
| `--refine-window SECONDS` | Refinement window on either side of the first-pass line bounds (default: `0.80`). |

Example `line-offsets.json`:

```json
{
  "3": -0.15,
  "7": -0.08,
  "12": 0.05
}
```

Use it with `--line-offsets "D:\Lyrics\line-offsets.json"`. The numbers refer to lyric lines after blank lines and standard LRC metadata have been removed.

### TIFA options

These options apply when TIFA is installed and you use `--aligner tifa`.

| Option | Purpose |
| --- | --- |
| `--tifa-root PATH` | TIFA source checkout directory. |
| `--tifa-python PATH` | Python executable for the separate TIFA environment. |
| `--tifa-model PATH` | TIFA checkpoint or model folder. |
| `--tifa-chunk-seconds N` | Target chunk length in seconds (default: `42`). |
| `--tifa-context SECONDS` | Audio context around the first/last lyric in a chunk (default: `1.8`). |
| `--tifa-diagnostics PATH` | Choose the TIFA JSON diagnostics file. |
| `--no-context-repair` | Disable the default short-word timing repair used with TIFA. |

TIFA's model weights use the [CC BY-NC-SA 4.0 license](https://github.com/openvpi/TIFA/releases/tag/v1.0.0). Review that license before using the model commercially or redistributing its weights.

### Optional audio processing and reports

| Option | Purpose |
| --- | --- |
| `--separate-vocals` | Run optional local Demucs vocal isolation before alignment. Requires `demucs-infer`. |
| `--demucs-model NAME` | Demucs model to use (default: `htdemucs`). |
| `--demucs-segment SECONDS` | Demucs segment length (default: `6`); shorter segments may reduce GPU memory use. |
| `--vocal-output PATH` | Keep the separated vocal stem at this WAV path. |
| `--instrumental-cues` | Add timestamped `♪` cues for long lyric-free openings, gaps, or endings. |
| `--instrumental-threshold SECONDS` | Minimum gap length for an instrumental cue (default: `6`). |
| `--review-report PATH` | Write a line-by-line timing review report. |

### General options

| Option | Purpose |
| --- | --- |
| `--dry-run` | Validate inputs and show planned outputs without loading a model or writing alignment output. |
| `--overwrite` | Allow existing output files to be replaced. |
| `--doctor` | Check the Python, WhisperX, PyTorch, CUDA, and FFmpeg setup. |

The browser editor has a separate, small set of options:

| Option | Purpose |
| --- | --- |
| `python lyrics_editor.py --port PORT` | Use a different local port (default: `8765`). |
| `python lyrics_editor.py --no-browser` | Print the URL without opening it automatically. |

## Common workflows

### Adjust an LRC without rerunning alignment

This creates a separate adjusted file by default and leaves the original untouched:

```powershell
python lyrics_align.py --adjust-lrc "D:\Music\Song.lrc" --offset -0.15
```

Use `--output` with the original path and `--overwrite` only when you intentionally want to replace it. You can combine `--adjust-lrc` with `--line-offsets` for line-specific changes.

### Try the singing-aware backend

With TIFA and the optional vocal-separation dependencies installed:

```powershell
python lyrics_align.py --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en --aligner tifa --device cuda --separate-vocals --word-level --review-report "D:\Lyrics\Song.review.txt"
```

TIFA's singing-trained model supplies final word timings; WhisperX helps plan chunks and provides a timing comparison. Review the output report and listen to the result—no aligner can guarantee perfect timing on every vocal performance.

### Multi-singer styling in TTML

A lyric file can start with a role definition, followed by lyrics. Plain text is the default singer, `*...` marks a featured/italic singer, and `**...**` marks a duet/group:

```text
[Lead Singer, *Featured Singer*, **Both Singers**]
First line
*Featured line*
**Duet line**
```

For custom singer IDs or colors, use `--singer-config PATH`. TTML output preserves word timing and styling metadata for compatible clients; LRC itself stores line timestamps only.

## Output formats and limitations

- **LRC** stores a timestamp per lyric line and works with many music players.
- **TTML** can store word timings and singer/style metadata. Word-by-word highlighting depends on the player supporting and rendering TTML/enhanced lyrics.
- Lyrics must be supplied by you. Savant aligns the text to the audio; it does not transcribe a song to produce the lyrics.
- Incorrect lyrics, backing vocals, heavy compression, live recordings, long melisma, and unusual pronunciation can all affect alignment. Review output before using it in a music library.

## Troubleshooting

- **`ffmpeg` not found:** install FFmpeg, make sure it is on `PATH`, and open a new terminal.
- **Model or package download fails:** verify internet access and retry; first use downloads model weights.
- **CUDA or GPU memory error:** try `--device cpu`; when using Demucs, try a shorter `--demucs-segment`.
- **Language/model unavailable:** try a WhisperX-supported language or provide `--align-model`.
- **A line is consistently late:** try a small `--offset`; if only a few lines are wrong, use `--line-offsets` or `--phrase-offsets`.

## Acknowledgements

Savant builds on [WhisperX](https://github.com/m-bain/whisperX), [PyTorch](https://pytorch.org/), and optionally [demucs-infer](https://github.com/openmirlab/demucs-infer) and [TIFA](https://github.com/openvpi/TIFA). Please review the respective upstream documentation and licenses for the dependencies and model weights you choose to use.
