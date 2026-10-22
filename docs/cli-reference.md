# Command-line reference

[Back to the README](../README.md) · [Installation](installation.md) · [TIFA guide](tifa.md)

Run `python lyrics_align.py --help` for the argument parser's current help. The browser app's **Generate → Advanced Options** exposes these options in a form.

## Typical commands

Align plain-text lyrics and write an LRC:

```powershell
python lyrics_align.py --audio "D:/Music/Song.flac" --lyrics "D:/Lyrics/Song.txt" --language en
```

Also write word-timed TTML:

```powershell
python lyrics_align.py --audio "D:/Music/Song.flac" --lyrics "D:/Lyrics/Song.txt" --word-level
```

Validate paths and show the planned output without loading an alignment model:

```powershell
python lyrics_align.py --audio "D:/Music/Song.flac" --lyrics "D:/Lyrics/Song.txt" --dry-run
```

Adjust an existing LRC without rerunning the model:

```powershell
python lyrics_align.py --adjust-lrc "D:/Music/Song.lrc" --offset -0.15
```

## Inputs and outputs

| Option | Description |
| --- | --- |
| `--audio PATH` | Audio file to align (FLAC, MP3, WAV, M4A, and other FFmpeg-supported formats). |
| `--lyrics PATH` | Correct lyrics in plain text or LRC format. Required for alignment. |
| `--adjust-lrc PATH` | Adjust timestamps in an existing LRC without running an alignment model. |
| `--output PATH` | Output LRC path. Alignment defaults to the audio filename with `.lrc`; adjustment defaults to a separate `.adjusted.lrc` file. |
| `--word-level` | Also write a word-timed TTML sidecar. The LRC is still written for compatibility. |
| `--ttml-output PATH` | Set the TTML output path; also enables TTML output. |
| `--singer-config PATH` | JSON settings for named singers and their TTML metadata. |

## Alignment and timing

| Option | Description |
| --- | --- |
| `--language CODE` | Alignment language code (default: `en`). Model support varies by backend. |
| `--aligner whisperx` or `--aligner tifa` | Select the backend. WhisperX is the default; TIFA is the optional singing-aware backend and currently supports English in this integration. |
| `--align-model NAME` | Optional custom Hugging Face / wav2vec2 alignment model for WhisperX. |
| `--device auto|cpu|cuda` | Inference device (default: `auto`). |
| `--offset SECONDS` | Apply a global timing correction. Negative values move timings earlier; positive values move them later. |
| `--line-offsets PATH` | JSON object mapping 1-based lyric line numbers to timing corrections in seconds. Blank lines and standard LRC metadata are removed before counting. |
| `--phrase-offsets PATH` | JSON object mapping exact cleaned lyric-line text to extra timing corrections. Repeated matching lines all receive the correction. |
| `--refine` | Run a second, narrow timing pass with WhisperX. Ignored by TIFA. |
| `--refine-window SECONDS` | Refinement window around a line's first-pass bounds (default: `0.80`; valid range: `0.1`–`5`). |

Example `line-offsets.json`:

```json
{
  "3": -0.15,
  "7": -0.08,
  "12": 0.05
}
```

Pass it with `--line-offsets "D:/Lyrics/line-offsets.json"`. Global and per-line corrections can be combined.

## TIFA options

These options apply to TIFA runs. Read the [TIFA guide](tifa.md) before using them.

| Option | Description |
| --- | --- |
| `--tifa-root PATH` | TIFA source checkout directory. |
| `--tifa-python PATH` | Python executable for TIFA's separate environment. |
| `--tifa-model PATH` | Model checkpoint or folder. |
| `--tifa-chunk-seconds N` | Target chunk duration in seconds (default: `42`; valid range: `20`–`55`). |
| `--tifa-context SECONDS` | Audio context around chunk lyric boundaries (default: `1.8`; valid range: `0.5`–`5`). |
| `--tifa-diagnostics PATH` | Custom path for the TIFA JSON diagnostics report. |
| `--no-context-repair` | Disable the default conservative short-word timing repair used with TIFA. |

## Optional audio processing and reports

| Option | Description |
| --- | --- |
| `--separate-vocals` | Use optional local vocal isolation before alignment. Requires `demucs-infer`. |
| `--demucs-model NAME` | Vocal-separation model (default: `htdemucs`). |
| `--demucs-segment SECONDS` | Demucs segment length (default: `6`; valid values: `2`–`7`). Shorter segments may reduce GPU memory use. |
| `--vocal-output PATH` | Keep the separated vocal stem at this WAV path. Requires `--separate-vocals`. |
| `--instrumental-cues` | Add timestamped `♪` markers for long lyric-free gaps and intros/outros. |
| `--instrumental-threshold SECONDS` | Minimum gap for an instrumental marker (default: `6`; must be greater than zero and at most `120`). |
| `--review-report PATH` | Write a text report of timing warnings, repairs, and other review notes. |

## General options

| Option | Description |
| --- | --- |
| `--overwrite` | Allow existing output files to be replaced. Without it, existing outputs are protected. |
| `--dry-run` | Validate the input and show planned output without loading the alignment model or writing alignment results. |
| `--doctor` | Check Python, FFmpeg, PyTorch, CUDA, WhisperX, and optional components. |

## Browser editor options

The editor is launched separately:

| Option | Description |
| --- | --- |
| `--port PORT` | Use a different local port (default: `8765`). |
| `--no-browser` | Print the local URL without opening a browser automatically. |

```powershell
python lyrics_editor.py --port 8766 --no-browser
```

## Safety notes

- Use `--overwrite` only when you intend to replace an existing output. Adjustment defaults to a separate file to help preserve the original.
- `--adjust-lrc` is for timestamp correction, not audio alignment. It does not need `--audio` or `--lyrics`.
- `--doctor` is a setup check; it does not validate the timing quality of a song.
