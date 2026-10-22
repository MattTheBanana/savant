# TIFA singing-aware alignment

[Back to the README](../README.md) · [Installation](installation.md) · [CLI reference](cli-reference.md) · [Troubleshooting](troubleshooting.md)

TIFA is an optional singing-trained forced aligner that can help with sung vocals where a speech-oriented aligner struggles. It is not required for normal Savant use.

## When to try TIFA

Try it when WhisperX timing is unreliable on a singing-heavy track. The current Savant integration supports **English lyrics only**. It uses WhisperX for rough timing and chunk planning, then TIFA supplies the final word intervals and Savant compares results for review.

## Setup and model files

TIFA requires three components: its source checkout, an isolated Python environment, and a model checkpoint. The default paths expected by the current CLI are:

- Source checkout: `vendor/TIFA/` (must contain `infer.py`)
- Python environment: `.tifa-venv/Scripts/python.exe` on the default Windows configuration
- Model folder: `models/TIFA-1.0-ST/`

The CLI accepts `--tifa-root`, `--tifa-python`, and `--tifa-model` to point at custom locations. The source checkout, Python environment, and checkpoint are optional extras and are not part of the basic WhisperX setup. Follow the [upstream TIFA project](https://github.com/openvpi/TIFA) for source, environment, checkpoint, and compatibility requirements; make sure your local setup matches the paths or explicitly specify them.

The TIFA model weights are licensed **CC BY-NC-SA 4.0**. This is separate from the code license. Review the [upstream model release license](https://github.com/openvpi/TIFA/releases/tag/v1.0.0) before commercial use or redistributing weights.

## Run TIFA

With the source, environment, and model installed:

```powershell
python lyrics_align.py --audio "D:/Music/Song.flac" --lyrics "D:/Lyrics/Song.txt" --language en --aligner tifa --word-level --review-report "D:/Lyrics/Song.review.txt"
```

Add `--separate-vocals` if you have installed the optional `demucs-infer` dependency and want to align against an isolated vocal stem. It may help when instruments mask consonants, but source separation can also introduce artifacts.

## Chunking and context repair

The default target is `--tifa-chunk-seconds 42`, within TIFA's roughly one-minute context limit. Savant tries to place boundaries near low-energy pauses and lyric-line breaks. You can tune:

- `--tifa-chunk-seconds` (20–55 seconds; default `42`)
- `--tifa-context` (0.5–5 seconds; default `1.8`)
- `--no-context-repair` to disable the conservative short-function-word timing repair, which is enabled by default with TIFA.

Context repair looks for common weak words that are missing or implausibly timed. It compares TIFA and WhisperX intervals and checks neighboring words before applying a correction. It is a heuristic, not ground truth. Any changes should be reviewed.

## Diagnosis and review

A TIFA run writes a JSON diagnosis file by default beside the audio, unless `--tifa-diagnostics PATH` is supplied. `--review-report PATH` writes a human-readable review report. In the browser **Generate → Advanced options**, use the Clean diagnosis tab for an overview and Raw JSON to inspect the complete diagnosis payload.

The diagnosis includes metrics such as agreement, confidence, determinacy, and monotonicity, as well as chunk matching and notes. These are model self-consistency indicators, **not calibrated probabilities** that a timestamp is correct.

If a chunk is poorly matched, check that the supplied lyrics and pronunciation match the recording, listen around the reported interval, and review whether a long word crosses a chunk boundary. For setup or inference errors, run `python lyrics_align.py --doctor` and follow [Troubleshooting](troubleshooting.md).
