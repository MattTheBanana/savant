# Troubleshooting

[Back to the README](../README.md) · [Installation](installation.md) · [CLI reference](cli-reference.md) · [TIFA guide](tifa.md)

Start with a diagnostic run:

```bash
python lyrics_align.py --doctor
```

If you are using Generate in the browser app, select **Run System Diagnostics** and read the Logs tab. The browser's setup panel may also show an installation action or setup instructions.

## FFmpeg is missing

Install FFmpeg, confirm that `ffmpeg -version` works in a new terminal, then restart Savant. Installing FFmpeg without making it available on `PATH` will not resolve the error.

## WhisperX or PyTorch is unavailable

Activate the same Python environment used to launch Savant, then check:

```bash
python -c "import torch; print(torch.__version__)"
python -c "import whisperx; print('WhisperX import OK')"
```

If the import fails, install the dependencies into that environment. For CUDA-specific PyTorch versions, follow the current [WhisperX setup guidance](https://github.com/m-bain/whisperX). You can try `--device cpu` while diagnosing GPU-specific problems.

## CUDA out-of-memory

- Try `--device cpu` to determine whether the problem is GPU memory.
- If vocal separation is enabled, try a shorter `--demucs-segment` (valid values are 2–7 seconds).
- Avoid running several GPU-heavy applications alongside Savant.

CPU mode may be slower but can help verify that the files and lyrics are otherwise valid.

## Output already exists

By default Savant does not replace existing output. Choose a new `--output` path or enable `--overwrite` only when replacement is intentional. `--adjust-lrc` creates a separate adjusted file by default; use the original path plus `--overwrite` only if you deliberately want to modify it in place.

## Alignment is poor or a line starts late

- Confirm the lyric text matches the sung words, including repeated lines and contractions.
- Try a small global `--offset` if the whole result is consistently early or late.
- Use `--line-offsets` when only a few lines need changes.
- Try `--refine` with WhisperX, or the optional singing-aware `--aligner tifa` for supported English material.
- Consider `--separate-vocals` if accompaniment masks consonants, but listen for artifacts introduced by separation.
- Review the generated LRC in a player; no aligner can guarantee perfect timing.

## TIFA setup or diagnosis problems

TIFA is optional and needs its own source checkout, isolated Python environment, and model checkpoint. Run `--doctor` and check the paths given to `--tifa-root`, `--tifa-python`, and `--tifa-model`. The integrated TIFA backend supports English lyrics only.

Use the browser Generate panel's Logs and Raw JSON tabs, or inspect the diagnosis and review-report files directly. A missing or poorly matched chunk can come from incorrect transcript text, pronunciation differences, or inference/output issues. The metrics are diagnostic clues, not certainty scores.

## Browser app does not start

- Make sure the editor is using the intended Python environment.
- If port 8765 is busy, run `python lyrics_editor.py --port 8766`.
- Use `python lyrics_editor.py --no-browser` to print the URL without opening a browser.
- Open the local URL printed by the terminal and keep the Python server running while using Generate.

## Generate says a file is missing

Use the file pickers or drag each input into its corresponding drop zone. Alignment requires both audio and lyrics; LRC adjustment requires an existing `.lrc`. The input names are shown below each drop zone after selection.

For general flags and sample commands, see the [CLI reference](cli-reference.md).
