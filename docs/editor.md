# Browser editor and Generate panel

[Back to the README](../README.md) · [Installation](installation.md) · [CLI reference](cli-reference.md)

Savant's browser app has two main workflows: **Edit** for fine-tuning existing lyrics, and **Generate** for running the command-line aligner without building a command by hand.

## Launch the app

From the project folder, with your Python environment activated:

```bash
python lyrics_editor.py
```

Open the local URL shown in the terminal (normally `http://127.0.0.1:8765`). If the port is busy, try `--port 8766`. Use `--no-browser` to print the address without opening a browser.

## Generate

Select **Generate** in the top navigation.

1. Open **Configuration** and drop audio and lyric files into their areas, or use the file pickers. The main choices are task, alignment backend, language, compute device, timing offset, word-timed output, vocal separation, second-pass refinement, and instrumental cues.
2. Choose **Advanced Options** for custom output paths, overwrite / dry-run, review reports, custom models, TIFA settings, Demucs settings, singer configuration, and timing-correction JSON files.
3. Press **Run Generator**. The panel shows the current step, overall progress, step progress, and live CLI output.
4. When the run finishes, open **Output Files** to locate generated LRC/TTML, reports, logs, or diagnosis files.

The **Run System Diagnostics** action invokes the CLI's `--doctor` check. If a required dependency is missing, the panel displays setup guidance or an available installer action. Installer actions ask for confirmation before they run.

## Logs and diagnoses

The results area includes:

- **Logs:** the CLI and setup output for the current task.
- **Clean Diagnosis:** a summary of TIFA's diagnosis metrics, chunk coverage, and notes.
- **Raw JSON:** the original structured TIFA diagnosis file, where one was produced.
- **Output Files:** available generated files with buttons to open the file or reveal it in the system file manager.

Diagnosis details are only available for TIFA runs that produce a diagnosis JSON file. The metrics are useful for reviewing suspicious chunks, but they are not calibrated probabilities that every timestamp is correct. See the [TIFA guide](tifa.md).

## Return to Edit automatically

Open **Preferences** and find **After generation finishes**. Choose whether to stay in Generate to inspect the result or return to Edit after a successful run.

## What stays local?

The browser UI is served by Python on `127.0.0.1`, which is the local machine. The regular Edit screen reads files in the browser. When you use Generate, the selected inputs are posted to the local Python server and stored in the run folder in your home directory:

- Windows: `%USERPROFILE%/.savant/runs/`
- macOS / Linux: `~/.savant/runs/`

The CLI and alignment models run on your computer; this workflow does not send audio or lyrics to a remote Savant service. Dependencies and model weights may be downloaded during setup or first use. Run folders can contain copies of the selected inputs, generated files, and logs; remove a run folder yourself when you no longer need it.

## Edit existing LRC or TTML

Choose **Edit** to import an audio file and a lyric file. Use LRC view for line-level timing and TTML view for word-by-word cues and styling where present. Review the waveform and playback, make corrections, and export the format supported by your player.

For file formats and singer metadata, see [Output formats and singer styling](output-formats.md).
