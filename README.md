# Savant (Windows CLI)

A separate CLI program that takes an audio file and a supplied lyrics text file, uses a **local forced-alignment model**, and writes a standard line-timed `.lrc` file. It does not use LRCLIB, Lidarr, an online inference API, or the `synclyr2metadata` program.

## How it works

The default engine uses [WhisperX](https://github.com/m-bain/whisperX)'s forced-alignment API. It does **not** transcribe the song to invent lyrics: it aligns the lyrics you provide to the recording. On the first run, WhisperX downloads the relevant language alignment model into its local cache; inference then runs on your PC.

For singing, there is now an optional **TIFA singing-aware backend**. TIFA is a separate forced-alignment model trained and evaluated on singing as well as speech; it is designed to handle accompaniment/noise and provides its own alignment diagnostics. With `--aligner tifa`, WhisperX is retained only for rough line/chunk anchors and an independent timing comparison; TIFA supplies final word intervals. The program segments longer songs into chunks under a minute and prefers low-energy pauses near lyric-line boundaries, reducing the chance that a long sung word is split across a too-short alignment window. TIFA's own diagnostics are written to `Song.tifa-diagnosis.json` by default. See the TIFA setup and usage section below. The first integration supports English lyrics only. TIFA model weights are licensed CC BY-NC-SA 4.0, which restricts use of those weights to compliant non-commercial use; review the [upstream model license](https://github.com/openvpi/TIFA/releases/tag/v1.0.0) before using them commercially or redistributing them.

Other options are available:

- **Vocal isolation:** `--separate-vocals` uses [demucs-infer](https://github.com/openmirlab/demucs-infer) to create a local vocal stem, so the aligner hears less of the instrumental mix. This is an optional install and does not alter the source file.
- **WhisperX second-pass refinement:** `--refine` re-aligns each line in a narrow local time window. It can help some tracks but runs the same model again, so it may reproduce systematic timing errors; it is not used for the TIFA backend.
- **Instrumental cues:** `--instrumental-cues` adds timestamped `♪` lines for long intros, gaps between lyric lines, and outros where no lyric timing was detected. The default minimum gap is 6 seconds.

Vocal isolation can help when instruments mask consonants, but dense compression, backing vocals, long melisma, live recordings, incorrect lyrics, or stylized pronunciation can still confuse an aligner. Review generated lyrics before copying them to your TrueNAS music library.

## Windows prerequisites

- Windows 10/11
- A supported Python installation: **3.10, 3.11, or 3.12** (64-bit). Use the included installer to create a project-local `.venv`. This project intentionally doesn't try to use Python 3.15 because Torch/WhisperX wheel support can lag behind new Python releases.
- FFmpeg installed and available as `ffmpeg.exe` on `PATH`.
- Internet access for initial package/model downloads. After the model has been downloaded, the alignment inference itself is local.
- Several GB of free disk space for PyTorch, dependencies, and cached models. CPU works; a supported NVIDIA CUDA setup can be faster.

### Install FFmpeg

If FFmpeg is not already on your PATH, one option on Windows is:

```cmd
winget install --id Gyan.FFmpeg.Shared --exact
```

Open a new Command Prompt after installation and verify:

```cmd
ffmpeg -version
```

### Install the program

1. Extract this folder somewhere local, for example `D:\Programs\lyrics-audio-aligner`.
2. Run `install.bat` from File Explorer or CMD. It checks for a compatible installed Python in common install locations and creates `.venv` inside this project. It does not need the `py` launcher or modify PATH.
3. Check the environment:

```cmd
lyrics-aligner.bat --doctor
lyrics-aligner.bat --help
```

The installer looks for Python 3.11, 3.10, then 3.12 in standard per-user/system locations. If none is found, install Python 3.11 x64 (e.g. `winget install --id Python.Python.3.11 --exact`) and run `install.bat` again. Existing Python 3.15 remains untouched.

### Optional: install vocal isolation

After the base aligner is installed, run `install-vocal-separation.bat`. This installs the inference-focused `demucs-infer` package into this project's `.venv`, using modern PyTorch 2.x-compatible packaging rather than the older upstream Demucs package. On the first use, its pretrained source-separation model is downloaded to a local cache. The installer does not intentionally replace your global Python or modify PATH.

Use `lyrics-aligner.bat --doctor` to check whether vocal separation is available. You can skip this optional installation and use the normal aligner any time.

### Optional: install the singing-aware TIFA backend

After the base `.venv` is installed, run `install-tifa.bat`. It downloads the pinned TIFA v1.0.0 source and the `TIFA-1.0-ST` checkpoint, then creates a **separate** `.tifa-venv`. This prevents TIFA's dependencies from replacing or downgrading the working WhisperX/Demucs environment. The installer downloads the CUDA-enabled PyTorch 2.8.0 wheels for CUDA 12.8; it checks whether that separate environment can see your NVIDIA GPU at the end.

The model checkpoint is approximately 144 MB, in addition to TIFA's Python dependencies and PyTorch. TIFA uses a model context of about one minute; this CLI targets 42-second chunks by default and selects chunk boundaries near low-energy pauses when possible. The TIFA model weights are under [CC BY-NC-SA 4.0](https://github.com/openvpi/TIFA/releases/tag/v1.0.0); the model license is separate from the source repository's code license.

Verify the installation with:

```cmd
lyrics-aligner.bat --doctor
```

Look for `TIFA source/environment: available`, `TIFA pretrained model: available`, and `TIFA CUDA available: True`. If you only see the regular WhisperX checks, run the TIFA installer again and review its error output.

## Usage

Suppose the audio file is `D:\Music\Artist\Album\Song.flac` and the correct unsynchronized lyrics are in `D:\Lyrics\Song.txt`:

```cmd
lyrics-aligner.bat --audio "D:\Music\Artist\Album\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en
```

By default the output is next to the audio file as `Song.lrc`. Existing output files are **not overwritten** unless `--overwrite` is supplied.

Use a custom path:

```cmd
lyrics-aligner.bat --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --output "D:\Lyrics\Song.synced.lrc" --language en
```

Preview inputs without loading a model or writing files:

```cmd
lyrics-aligner.bat --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --dry-run
```

Use CPU explicitly:

```cmd
lyrics-aligner.bat --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --device cpu
```

Apply a global timing correction. Negative values move all lyric lines earlier; positive values move them later. If the whole result feels late, start with a small correction like `-0.15` seconds and listen again:

```cmd
lyrics-aligner.bat --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en --offset -0.15 --overwrite
```

If only a few lines need correction, use a JSON file with per-line offsets instead of shifting the entire song. Line numbers are 1-based after blank lines and LRC metadata have been removed. Negative values move those lines earlier; positive values move them later. For example, save this as `D:\Lyrics\Song-offsets.json`:

```json
{
  "3": -0.15,
  "7": -0.08,
  "12": 0.05
}
```

Then rerun alignment with the correction file:

```cmd
lyrics-aligner.bat --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en --line-offsets "D:\Lyrics\Song-offsets.json" --overwrite
```

Global `--offset` and per-line corrections can be combined. Corrections applied during alignment do not require retraining or downloading another model. Existing output is still protected unless `--overwrite` is supplied.

### Refine an LRC you already generated (no model rerun)

For a quick experiment, shift an existing LRC 150 milliseconds earlier. This creates `Song.adjusted.lrc` and leaves the original untouched:

```cmd
lyrics-aligner.bat --adjust-lrc "D:\Music\Song.lrc" --offset -0.15
```

For lines that need individual corrections, pass the same JSON format with `--line-offsets`:

```cmd
lyrics-aligner.bat --adjust-lrc "D:\Music\Song.lrc" --line-offsets "D:\Lyrics\Song-offsets.json"
```

You can preview an adjustment with `--dry-run`. To modify the existing LRC in place, specify `--output` with the original path and add `--overwrite`; the default is deliberately to create a separate file.

Supply a language code (default `en`). The language must have a WhisperX alignment model available. For example, `fr`, `de`, `es`, `it`, `ja`, `zh`, `pt`, `ru`, `nl`, `ko`, and others may be available depending on the installed WhisperX version. Check the WhisperX documentation for the current model list. If needed, a custom Hugging Face wav2vec2 alignment model can be supplied with `--align-model MODEL_NAME`.

### Recommended quality pass for dense/compressed singing

If WhisperX's timestamps are inconsistent or the next line appears before the previous sung word finishes, try the singing-aware TIFA backend rather than repeatedly running the same speech-trained model:

```cmd
lyrics-aligner.bat --audio "D:\Music\Artist\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en --device cuda --separate-vocals --aligner tifa --word-level --offset -0.15 --instrumental-cues --review-report "D:\Lyrics\Song.review.txt"
```

This first runs WhisperX to get rough line locations, then uses those only to plan longer TIFA chunks around lyric-line boundaries and detected low-energy pauses. TIFA supplies the final word times. A second comparison between WhisperX and TIFA flags line starts/ends that disagree substantially; TIFA also writes its model-native diagnosis metrics. This uses two different aligners plus TIFA's built-in self-check, rather than adding a third model that would increase runtime and VRAM demand without a demonstrated benefit. `--refine` is unnecessary for this mode and is intentionally skipped; `--offset -0.15` still shifts the final output 150 ms earlier.

**Short-word context repair is enabled by default with `--aligner tifa`.** It targets a common singing failure: a quiet word such as “I”, “a”, or “of” is missed or placed almost on top of the following word, so the next lyric line appears late. For this small set of common function words, the tool compares TIFA's timing with WhisperX's independent estimate and checks both against the previous and next timed words. It restores a missing interval from WhisperX when that interval fits the sequence; if both models miss the word, it only estimates a brief interval when there is a real, bounded gap between neighboring words. Content words are not shifted by this pass. Every repair is recorded in the review report and `Song.tifa-diagnosis.json`. This is a conservative heuristic—not ground-truth detection—so review the repairs before processing a large library. Add `--no-context-repair` to disable it.

`--tifa-chunk-seconds 42` is the default target. Try `--tifa-chunk-seconds 35` for tracks where words or phrases straddle chunk boundaries; chunk cuts prefer low-energy pauses close to line breaks. The program does not split a word's transcript across chunks deliberately. If no pause is detected, it falls back to a lyric-line boundary and reports that in the review notes. `--separate-vocals` makes pause detection and TIFA inference work against an isolated vocal stem, but Demucs separation may itself create artifacts. Use `--demucs-segment 4` if the GTX 1650 runs out of GPU memory.

The review report contains line spans, unit coverage, model-disagreement notes, context repairs and chunk warnings. The sibling `Song.tifa-diagnosis.json` contains TIFA's `agreement`, `confidence`, `determinacy`, and `monotonicity` self-consistency metrics plus any context repairs. Those scores help prioritize listening review, but they are not calibrated probabilities that a timestamp is correct. Add `--overwrite` if you intentionally want to replace already generated LRC, TTML, review, or TIFA diagnostic files.

#### Supplying pronunciation hints to TIFA

TIFA is a forced aligner, not a chat model: adding instructions such as “listen harder to this line” to the lyric text will be treated as transcript text, not as a prompt. Its inference format supports `.pfml` transcripts for explicit pronunciation candidates, fixed word boundaries, and language scopes; ordinary `.txt`/`.lab` input stays plain transcript text. This CLI currently writes plain-text chunk transcripts, so it does not yet accept per-word PFML pronunciation overrides. Such hints are a promising targeted feature for proper names, contractions, and unusual sung pronunciations, but they should be explicit pronunciation candidates—not prose instructions. See the [TIFA PFML documentation](https://github.com/openvpi/TIFA) before crafting candidate phonemes.

If every chunk reports a missing TextGrid despite TIFA returning exit code 0, treat that as an inference/output failure, not as bad alignment confidence. Keep `--tifa-debug-dir` enabled and inspect `tifa-run.stdout.log`, `tifa-run.stderr.log`, `chunk-plan.json`, `output_artifacts_found`, and the per-chunk `relevant_log_lines`. Current diagnostics now retain command details and log tails even when the TextGrid is missing; the complete log files are retained when a debug directory is specified.

### Browser-based lyric editor (new)

Launch the local editing UI from Command Prompt in this folder:

```cmd
lyrics-editor.bat
```

It opens `http://127.0.0.1:8765` in your browser. If port 8765 is already in use, run `lyrics-editor.bat --port 8766` and open the printed local address. Stop the server with Ctrl+C in the terminal. The HTTP server binds only to `127.0.0.1`; it does not provide upload endpoints. Audio and lyrics are opened by the browser's local file picker or by dropping files anywhere into the page; they are not uploaded.

### Editing workflow

- Choose a local audio file and an LRC, TTML, or TXT lyric file, or **drag and drop audio + lyrics together anywhere into the page**. You can also drop just one file at a time. Supported audio includes FLAC, MP3, WAV, M4A, OGG/Opus and other browser-supported audio formats; lyric imports include LRC, TTML/XML, and TXT. If several of one type are dropped at once, the first supported one is loaded.
- The LRC / Lines view remains a simple line-number, timestamp, and lyric grid. For higher-fidelity editing, switch to **TTML words**: a DAW-inspired timeline shows the audio waveform on top and keeps each lyric line in its own row underneath, with word clips positioned on a shared time axis. The active line and word follow playback.
- Edit timestamps and lyric text directly in the grid. The lyric cell is editable text; changing its text clears that line's old word cues so stale timing isn't accidentally exported. Use the LRC/TTML preview tabs, then Download LRC or Download TTML to save results.
- In the LRC / Lines view, select a row and press Left/Right to nudge its timestamp. Shift+Left/Right uses a larger step; Up/Down selects rows. Press Enter to edit the selected lyric, then use Escape to leave text editing. In TTML words view, Up/Down selects words and Left/Right nudges the selected word. The word timeline supports zoom in/out and Fit Song; clicking the ruler or waveform seeks playback.
- In either view, drag a word clip body to move its start/end together, or drag its left/right edge to adjust only that word boundary. The selected-word inspector allows precise start/end entry and edits to word text, singer/agent, style reference, font style, font weight, and color. The waveform is decoded locally by the browser when supported; very large files or unsupported codecs may show a timeline without a waveform. Space starts/stops playback when focus is outside a lyric/text field; when a text field is focused, Space is a normal typeable space. Ctrl+S exports LRC in Lines view and TTML in TTML words view. The lead-in, nudge increment, Shift multiplier, text-file placeholder spacing, and export language are configurable on the Settings screen.
- Both views operate on the same underlying timings: editing a line timestamp in Lines view shifts all of that line's TTML word cues by the same amount; editing the first word's start in TTML view updates the LRC line timestamp. Other word-level adjustments stay in TTML and do not flatten the simpler LRC timestamps. If you change the lyric text so its word count no longer matches existing cues, those stale word cues are cleared for that line. When the source is LRC/TXT, TTML export remains line-timed; the editor cannot invent accurate word cues that aren't present.

The editor is intended for fast review of generated output without another model run. It is local-only and dependency-free beyond Python already installed for the CLI.

## Diagnose a repeatable late line (recommended before batch processing)

If the same line is late in multiple runs, do not keep swapping separators or applying manual offsets yet. Preserve TIFA's actual alignment evidence so you can tell whether its phoneme/word boundaries are late or if the error appears when we map those boundaries into LRC/TTML. TIFA writes `texts`, `words`, and `phones` tiers to each TextGrid; debug mode retains those files instead of deleting them with temporary files. It also adds TIFA similarity plots and a CSV comparing raw TIFA times, WhisperX coarse times, the final times, and the phonemes assigned to each lyric word.

```cmd
lyrics-aligner.bat --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en --device cuda --separate-vocals --aligner tifa --word-level --offset -0.15 --instrumental-cues --review-report "D:\Lyrics\Song.review.txt" --tifa-debug-dir "D:\Lyrics\Song.tifa-debug" --overwrite
```

After the run, open the newest `run_...` folder under `D:\Lyrics\Song.tifa-debug`. Start with `word-timing-comparison.csv`; filter to the problematic line(s) and compare `tifa_start_s`/`tifa_end_s` with `whisperx_start_s`/`whisperx_end_s`. The `tifa_phones` column and `output` TextGrids/plots show what TIFA predicted at phoneme level. CSV times are raw model-relative timestamps before applying your global `--offset`.

The debug folder also preserves `tifa-run.stdout.log`, `tifa-run.stderr.log`, and `chunk-plan.json`. If the review says `TIFA OUTPUT MISSING`, the chunk's final timings came from WhisperX, not TIFA. Check `output_artifacts_found` and `alignment_source_summary` in the JSON diagnosis alongside those log files. Current TIFA documentation says successful samples write `texts`, `words`, and `phones` TextGrid tiers; if all chunks are missing, treat that run as an unsuccessful TIFA alignment and do not batch-apply its fallback LRCs without review. The CLI now records missing/invalid chunks explicitly instead of silently omitting them from the per-chunk report.

- If TIFA and WhisperX both place the first word late, inspect its `phones` and similarity plot; the issue likely comes from the audio evidence, transcript pronunciation, or both models agreeing on the same wrong boundary.
- If raw TIFA times look right but `final_start_s` differs, the weak-word/context-repair or fallback mapping changed it.
- If the CSV looks right but Navidrome still changes lines late, compare the generated `.ttml` cue times and the player's renderer; the alignment model may not be the cause.

Debug mode writes chunk WAVs and image plots, so it uses extra disk space. Use a local SSD folder for the debug directory rather than a network share. Each run is stored in a new timestamped subfolder and older debug runs are not deleted automatically.

For your GPU, the first run downloads the TIFA model and may take longer while it initializes. The models then run locally; no audio is sent to a remote inference service.


### Optional manual corrections (fallback only)

Manual offsets remain available as a last resort, not the recommended way to fix systematic alignment errors. First try `--aligner tifa` and inspect the independent-model comparison and TIFA diagnosis. `--refine` runs the same WhisperX model again in a local window and may reproduce its timing error.

Create `D:\Lyrics\phrase-offsets.json`:

```json
{
  "Talkin' Talking Heads and space": -0.20
}
```

The key must match the **entire cleaned lyric line** (case and repeated whitespace are ignored; punctuation and words should match). The correction is applied to every occurrence of that exact line. If only one of several identical lines needs correction, use `--line-offsets` with that line's 1-based cleaned lyric line number instead. If your command already uses `--offset -0.15`, adding `-0.20` here moves this specific line 200 ms further earlier, for a total correction of `-0.35` seconds.

Add `--phrase-offsets` to your usual alignment command. For example:

```cmd
lyrics-aligner.bat --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en --device cuda --separate-vocals --word-level --offset -0.15 --phrase-offsets "D:\Lyrics\phrase-offsets.json" --refine --instrumental-cues --overwrite
```

This correction is applied to both `.lrc` line timestamps and every word timestamp for that line in `.ttml`. Use a small adjustment such as `-0.10` or `-0.20` to start, compare playback, then tune it. Run without `--dry-run` to generate the corrected files. During a dry run, the CLI reports how many phrase-specific corrections matched.

### Add musical-note markers for instrumental sections

```cmd
lyrics-aligner.bat --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en --instrumental-cues
```

By default, `♪` is inserted for detected lyric-free openings, between-line gaps, or endings lasting at least 6 seconds. Change the cutoff, for example to 4 seconds, with `--instrumental-threshold 4`. Cues are inferred from the timestamps of detected words; they indicate likely instrumental passages, not a music-genre or solo-instrument classifier. Review them for songs with long rests or drawn-out vocal notes.

## Lyrics file format

A plain `.txt` file is fine: put one lyric line on each line, with accurate words and punctuation. The CLI also accepts an existing LRC and strips leading line timestamps/standard metadata before realigning it. Blank lines and standard LRC metadata lines such as `[ar:...]` / `[ti:...]` are ignored.

The output is standard line-level LRC, e.g.:

```text
[00:12.34]First lyric line
[00:16.82]Second lyric line
```

This is line-level timing (one timestamp per lyric line). The alignment model produces word/character timestamps internally, but ordinary LRC only stores line starts. Lines the model cannot timestamp are omitted and reported as warnings; the command exits with a nonzero status if some lines were omitted. Token-to-timestamp mapping checks actual normalized text matches rather than assuming equal token counts mean every position matches, which reduces the chance of a mismatched token offsetting later line timings.

## Word-by-word karaoke timing for Navidrome

Use `--word-level` to write a Navidrome-compatible TTML sidecar with the aligned word/character timings, while keeping the `.lrc` output for simpler players:

```cmd
lyrics-aligner.bat --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en --word-level --offset -0.15 --refine
```

This writes `Song.lrc` and `Song.ttml` beside the audio. The TTML contains `<span begin="..." end="...">word</span>` cues, so compatible clients can highlight the current word rather than only scrolling the current line. With the default backend, timestamps come from WhisperX. With `--aligner tifa`, the final word timestamps come from TIFA, with WhisperX used only as a coarse anchor and independent comparison. Review singing, fast delivery, backing vocals, and heavily compressed mixes.

TTML is the recommended Navidrome output when you want word timing now and named singer/agent layers later. Navidrome 0.63 and newer parse TTML sidecars and expose word-timed cues through the OpenSubsonic v2 enhanced-lyrics API. A client must actually request and render the enhanced/structured cues for word-by-word highlighting to appear; writing TTML alone does not add a karaoke renderer to every player's UI. Navidrome's default `LyricsPriority` prioritizes `.ttml`; if you customized it, include `.ttml` before `.lrc`.

Use `--ttml-output "D:\Lyrics\Song.ttml"` if you want to set the TTML output location yourself. `--ttml-output` also enables word-timed TTML without `--word-level`; the dedicated flag is a convenient switch when you want the generated TTML saved next to the audio automatically.

## Multi-singer lyrics and Navidrome

The aligner can keep normal `.lrc` output for broad player compatibility and create a named-agent TTML sidecar for Navidrome. TTML supports word timing plus multi-voice agent layers, so it is the preferred output when singer assignment is involved. Navidrome 0.63 and newer can parse `.ttml` sidecars and expose multi-voice/word-timed cues through OpenSubsonic's enhanced lyrics endpoint. The default Navidrome `LyricsPriority` already prioritizes `.ttml`; if you customized it, include `.ttml` before `.lrc`.

### 1. Put singer definitions at the top of the lyrics file

The first non-empty line of the `.txt` file can define the singer roles in square brackets. Use a plain name for the default singer, `*name*` for a featured/italic singer, and `**name & name**` for a duet/group whose words are bold. These markers now work as **spans anywhere in the lyrics**: they can start or end mid-line, appear multiple times on one line, or continue across line breaks. The aligner removes the markers before aligning lyrics and assigns each aligned word/character to the role active at its start.

For example, `D:\Lyrics\Song.txt`:

```text
[Forrest Nolan, *love interest*, **Forrest Nolan & love interest**]
Hi
*Hello*
**We are both speaking**
Now we're back to the lead singer
And you said, *"So is love"*
*And you said,* "So is love"
Yes its true *she came on
kinda strong* she kinda turns me on, etc.
**and us
forever** yes
```

In this example, plain text belongs to Forrest Nolan, text within `*...*` belongs to love interest, and text within `**...**` belongs to the duet. After a marker closes, assignment returns to the default singer. The markup can continue across a newline, so `*Hi\nits me* and me` assigns both `Hi` and `its me` to the featured singer and `and me` to the default singer. A line can therefore contain words assigned to different people; the `.ttml` output stores the agent on each timed word rather than guessing one speaker for the whole line.

The role markers in the opening definition must be unique: one plain/default singer, one italic singer, and one bold/group singer at most. A bold group can list its members with either `&` or commas, so both `**Forrest Nolan & love interest**` and `**Forrest Nolan, love interest**` are valid. A group color can be mixed from the colors of its members. Markers cannot be nested inside each other; close one style before opening another. Put style changes between words rather than inside a word, because the aligner timestamps word units. To include a literal asterisk in the lyrics, escape it with a backslash (`\*`).

Commas outside quotes separate roles in the opening definition. If a singer's actual name contains a comma, wrap that name in double quotes. For example:

```text
["Tyler, the Creator", *love interest*, **"Tyler, the Creator" & love interest**]
```

Quotes keep `Tyler, the Creator` as one name, while the `&` separates the two members of the bold group. In a bold group, commas between unquoted members work as an alternative to `&`; quote any member whose name itself contains a comma.

### 2. Optional: configure singer colors

The bracketed definition provides names and presentation roles without requiring JSON. To customize singer colors, copy `examples\duet-singers.json` and edit the color values. Singer names are matched against the names in the opening bracketed line; a group can use `"color": "mix"` with `members` listing the singer names.

For example, the JSON color configuration can contain:

```json
{
  "mix_group_colors": true,
  "singers": [
    {"name": "Forrest Nolan", "color": "#4fc3f7"},
    {"name": "love interest", "color": "#ba68c8"},
    {"name": "Forrest Nolan & love interest", "type": "group", "members": ["Forrest Nolan", "love interest"], "color": "mix"}
  ]
}
```

### 3. Align and create both files

For the example above, no `--singer-config` is needed to assign singers:

```cmd
lyrics-aligner.bat --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en --word-level --offset -0.15 --refine --instrumental-cues
```

To apply the custom colors from a JSON file, add `--singer-config "D:\Lyrics\duet-singers.json"`:

```cmd
lyrics-aligner.bat --audio "D:\Music\Song.flac" --lyrics "D:\Lyrics\Song.txt" --language en --singer-config "D:\Lyrics\duet-singers.json" --word-level --offset -0.15 --refine
```

This creates:

- `D:\Music\Song.lrc` — ordinary timestamped lyric lines for clients that only understand LRC. Singer definitions and markup are removed.
- `D:\Music\Song.ttml` — word-timed TTML with named singer/agent assignments, timing, and style/color metadata.

The `.ttml` output is created automatically when inline singer definitions, `--singer-config`, or `--word-level` is used. Existing output files are protected unless you pass `--overwrite`; use `--dry-run` to validate paths and lyric parsing first.

### 3. Display this in Navidrome

Use Navidrome 0.63 or newer and make sure the `.ttml` file is visible to the Navidrome process beside the matching audio file. If you customized `LyricsPriority`, set it to include `.ttml`, for example:

```toml
LyricsPriority = ".ttml,.yaml,.yml,.elrc,.lrc,.srt,.txt,embedded"
```

The stock Navidrome server can expose the parsed multi-voice data to compatible OpenSubsonic clients through `getLyricsBySongId` with `enhanced=true`. That is the server/data integration. It is distinct from the web UI presentation: standard Markdown characters in an `.lrc` file are not automatically rendered as bold/italic, and Navidrome's structured lyrics API does not carry custom color styles as a general Markdown document would.

For custom Navidrome Web UI rendering, `navidrome-ui/` contains a React renderer and CSS that consume the enhanced OpenSubsonic `structuredLyrics` result and the same singer JSON. It applies italic styling to featured singers, bold styling to group/duet agents, optional mixed colors for concurrent layers, and word-level highlighting using cue times. This is a frontend integration component for a custom Navidrome UI build, not an installable server plugin or an automatic patch to the stock Web UI. The current stock UI needs to be wired to request `enhanced=true`, pass the current playback position in milliseconds, and mount this component in its lyrics view; see `navidrome-ui/README.md`.

Group colors can be set to `"mix"` and `members` can list the singer names/IDs. The generated TTML uses the blended color in its style definition; `navidrome-ui/MultiVoiceLyrics.tsx` also blends member colors in the UI. `mix_concurrent_lines` controls the UI behavior when two or more voices overlap at the same lyric line index. Color is presentation metadata and may not be shown by third-party clients; named singer/agent layers and timing are the interoperable part.

## Troubleshooting

- **`FFmpeg was not found on PATH`**: install FFmpeg, ensure the folder containing `ffmpeg.exe` is in PATH, then open a new CMD window.
- **Python version not supported**: the installer uses a separate Python 3.10–3.12 environment. Don't use `py`; it is not required.
- **CUDA error**: retry with `--device cpu`.
- **No default alignment model for language**: check WhisperX's supported language/model list or provide `--align-model`.
- **Short words such as “I”, “a”, or “of” appear late / the previous line remains on screen**: use `--aligner tifa` (the TIFA mode now enables short-word context repair by default). Inspect the review report for `Context repair:` entries and the `context_repairs` array in `Song.tifa-diagnosis.json`. The repair only changes selected weak-word intervals where the second model or a real neighboring-word gap provides supporting evidence. It will leave ambiguous cases untouched rather than guessing. Vocal separation can help with masking instruments but may introduce artifacts of its own. Strong compression, backing vocals, pronunciation changes, rapid delivery, and repeated choruses can still confuse forced aligners.
- **Vocal separation fails or runs out of GPU memory**: make sure `install-vocal-separation.bat` completed and `lyrics-aligner.bat --doctor` lists vocal separation as available. Try `--demucs-segment 4` or `--device cpu` if the GTX GPU runs out of memory.
- **Instrumental notes aren't quite right**: change `--instrumental-threshold` (e.g. `4` to insert more cues) or omit `--instrumental-cues`. The feature detects long gaps between detected lyric events; it does not identify which instrument is playing.
- **Model download failure**: the first run needs internet access to download the alignment model. Retry after checking network access and the Hugging Face model availability. Once cached, inference can run offline.

## Dependencies and attribution

This CLI uses WhisperX and PyTorch; the optional vocal-separation feature uses demucs-infer. See upstream documentation and license terms:

- WhisperX: https://github.com/m-bain/whisperX
- PyTorch: https://pytorch.org/
- demucs-infer (optional): https://github.com/openmirlab/demucs-infer

Only local audio/lyrics paths are passed to the local library. This program does not make calls to LRCLIB or Lidarr.

## Latest TTML timeline controls

The TTML word editor now supports persistent playhead display (including gaps between words), a configurable timestamp label size, waveform click-and-drag seeking, and middle-button drag panning. `Ctrl` + mouse wheel zooms around the pointer position on the row beneath the cursor. Shift + left-drag from an empty waveform or track area box-selects word clips. Dragging a selected clip normally shifts the whole selection; `Ctrl` + dragging one selected clip moves only that clip. When dragging near/beyond a lane's left or right edge, the view scrolls automatically; configure its px/second speed in Settings.

When no word clip is selected, left/right arrows seek the playhead by the fine-nudge increment, and `Shift` + left/right jumps to the current/adjacent word boundary. With a word selected, the arrows continue to nudge the selected word timing. In the line text editor, `Ctrl+A` selects the full lyric line; clicking empty track space clears word selection. Waveform peaks are stored at 1 kHz and rendered by aggregating bins per display pixel, improving detail when zoomed in while preserving amplitude peaks when zoomed out.
