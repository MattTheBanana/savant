# Savant — Development Guide

This guide provides durable project context for future contributors and AI coding assistants. For the latest file-specific state, known implementation details, and work in progress, read [HANDOVER.md](HANDOVER.md) as well.

## What Savant is

Savant is a local lyric-alignment tool with two connected parts:

- A command-line forced aligner that estimates when supplied lyrics are sung in an audio file. It is not a lyric transcription service; users provide the lyrics to align.
- A browser-based editor for reviewing and manually correcting line-level LRC timing and word-level TTML timing.

Audio processing and editing are intended to remain local to the user's machine. Initial setup or optional alignment backends may download dependencies or model weights. Existing local weights, user-generated outputs, custom configuration, and untracked files must be treated as user data.

## Project map

| Path | Role |
| --- | --- |
| `lyrics_align.py` | CLI alignment entry point and alignment arguments/processing. |
| `lyrics_editor.py` | Local web-server entry point, browser UI hosting, file APIs, generation orchestration, capabilities, and installation settings API. |
| `webui/index.html` | Main browser UI. It contains the editor layout, CSS, HTML, and most client-side JavaScript in one file. |
| `savant-settings.txt` | Installation-local user preferences written/read through the local settings API; preserve existing user values. |
| `docs/` | User-facing installation, editor, CLI, output-format, optional backend, and troubleshooting guides. |
| `HANDOVER.md` | Current implementation handover: important selectors/functions, recently changed behavior, static checks, and remaining GUI verification. |

Read a file's current contents and surrounding call sites before editing it. In particular, many editor behaviors live in the large inline script inside `webui/index.html`; do not assume a separate JavaScript module exists.

## Editor concepts

### LRC and TTML

- **LRC / lines mode** edits one timestamp and one text field per lyric line.
- **TTML / words mode** edits word-level cues on per-line timeline lanes, with waveform context, a playhead, timing handles, and a word inspector. A TTML source can carry word cues and style/singer metadata that must survive edits/export.
- The same underlying line data feeds both views. Changing modes should not accidentally discard word cues, singer/agent attributes, styling, metadata, or TTML header information.
- LRC cannot encode word-level timing. Exporting LRC is therefore a line-level representation; word-level data is preserved in TTML.

### Main UI architecture

The interface uses ordinary HTML, CSS, and JavaScript rather than a front-end framework. Important responsibilities in `webui/index.html` include:

- `renderGrid()`, `renderLineGrid()`, and `renderWordGrid()`: switch/render line and word modes.
- `selectLineSelection()`, `selectWord()`, and related selection helpers: line and word selection state, anchors, visual feedback, and selection operations.
- `scrollElementToCenter()`, `scrollElementToNearest()`, and timeline view helpers: selection visibility, eased centering, and preserving the timeline view during rerendering.
- `addLine()`, `addTtmlLine()`, `insertTtmlLineAt()`, and `lineStartAtInsertion()`: mode-aware line insertion and sensible timestamp placement.
- `lrcOutput()` and `ttmlOutput()`: serialization/export.
- `updateCustomPlayerControls()`, `updateTimeReadout()`, `playPause()`, and `blockPause()`: custom player interface and playback actions.
- `showEditorContextMenu()` and the timeline Controls menu markup: right-click actions and user-facing keyboard/mouse reference.

Function names and exact line numbers can change. Search the latest source instead of relying on a stale line number.

## Preferences and persistence

There are two synchronized preference representations:

1. Browser-side settings in `localStorage` under `lyrics-aligner-ui-settings`.
2. Installation-level preferences in `savant-settings.txt`, read and written through `/api/settings` in `lyrics_editor.py`.

The UI normalizes preferences against `DEFAULT_UI_SETTINGS`, populates the Preferences form, saves changes locally, and schedules writes to the installation file. Preserve this synchronization path when adding or changing a preference; consider behavior when an older settings file does not contain a newly introduced key.

**User shorthand:** “Add a preference for that” means add a real, named option to the Preferences UI with a sensible default, persistence, and behavior wired into the feature. Do not satisfy this shorthand by only changing the default, adding a temporary button, or hard-coding a behavior that the user asked to configure.

When modifying settings, check all relevant places: defaults, normalization/migration, form markup, `saveSettings()`, `syncSettingsForm()`, change listeners, reset defaults, and installation settings synchronization. Existing settings must not disappear when an older settings file is loaded.

## Current and recent work

The editor has accumulated a number of behavior details that should be preserved while adding features. See `HANDOVER.md` for the latest state. Recent areas of focus include:

- Keyboard/mouse selection in the LRC and TTML editors: Ctrl/Cmd toggles individual lines or word cues; Shift extends ranges; line-range drag behavior; keyboard range selection; multiple-selection-aware delete actions.
- A Preferences option controlling eased centering for selected lines and clicked TTML words. With centering off, do not snap the reader's viewport to the center; scroll only as much as necessary to keep a selected line visible.
- TTML timeline zoom bounds, Fit Lines behavior, per-line waveform context, seek/playhead interactions, drag-to-retime and snap behavior.
- Editor action bar and shortcut hints, mode-specific Controls menu instructions, right-click context actions, saved agent presets, TTML style/singer formatting, and consistent singular/plural actions.
- A custom fixed audio-player dock with a seek bar, circular play/pause button, Block Pause, SVG volume/mute icons, volume slider, time shown to hundredths, centered audio filename, and right-aligned file size.
- Configurable Preferences and Generator defaults, including optional TIFA configuration, and output-path handling.

Don't silently change established shortcuts or gesture meanings while polishing the UI. If a control's current implementation does not match its description, inspect the code and either fix the behavior or correct the label so they agree.

## Development workflow

### Before editing

1. Re-fetch the latest branch/file versions and read the relevant HTML, JavaScript, Python API, and settings code.
2. Understand the full interaction: markup, styles, handlers, state, persistence, keyboard events, context menus, and rerender/focus/scroll consequences may be in different sections of the same file.
3. Check the requested change against related features. Examples: a new selection gesture must not break dragging or inline text editing; a new playback button should reuse the underlying audio logic; a new preference should work after reload and installation-settings synchronization.
4. If there is an important unresolved ambiguity that would materially affect the result, ask one concise question. Otherwise make a clear, reasonable implementation choice and state any material assumption in the handover.

### Validation

Static validation is useful but is not an interactive UI test. For UI edits, at minimum:

- Parse the entire inline JavaScript block after editing.
- Check for duplicate static HTML IDs.
- Check that expected controls, handlers, preference wiring, and keyboard labels are all present.
- Inspect responsive CSS and media queries when layout changes are involved.
- Verify that new or renamed DOM IDs agree with every reference in JavaScript.
- Use focused tests for pure helper logic when practical.
- Do not claim the browser, real audio playback, waveform behavior, drag behavior, or responsive layout was manually tested unless it actually was.

For manual verification when a runnable environment is available, test both LRC and word-timed TTML with audio loaded. Exercise the normal click, modified click, drag, keyboard, context-menu, playback, settings-save/reload, and narrow-window cases relevant to the change. Confirm export and undo/redo remain correct.

Useful Windows CMD checks from the repository root:

```cmd
python lyrics_align.py --doctor
python -m py_compile lyrics_editor.py lyrics_align.py
git status --short
```

Start the local browser editor with:

```cmd
python lyrics_editor.py
```

Use the project's installation guide for dependency setup and backend-specific steps. The `--doctor` command is a diagnostic; it does not prove that the browser UI behavior has been manually tested.

## Git and user-environment safety

The user commonly works on Windows at `D:\\Programs\\savant` and uses **CMD**. Prefer CMD-compatible instructions such as `ren`, `del`, and `fc` over PowerShell-only commands unless asked otherwise.

- Implement changes on the requested branch (normally `main`) and provide a link to the resulting commit.
- Re-fetch the target file and use its current blob SHA before updating it; avoid overwriting concurrent changes.
- Update `HANDOVER.md` when a feature or important behavior changes. Keep this development guide focused on durable project architecture and collaboration expectations.
- Do not use `git reset --hard`, `git clean -fd`, or broad deletion commands as casual troubleshooting. Do not discard untracked files without explicit approval.
- If Git reports an untracked file would be overwritten (for example, a local `.gitignore`), preserve/rename it, pull safely, compare it against the repository version, and merge any custom rules before removing the backup.
- Never ask the user to remove model weights or generated outputs merely to make a pull or test pass. Preserve them unless the task specifically requires safely managing those assets.

## Collaboration expectations

The user values **thoroughness, accuracy, and questions when they are actually needed**.

- Treat each request as a complete set of requirements. Check every requested detail, including copy, spacing, responsive behavior, control labels, default behavior, and persistence.
- Inspect the existing implementation first; prefer targeted changes over broad rewrites, and preserve unrelated features.
- Ask rather than guess when an important product decision is genuinely ambiguous. Don't ask the user to repeat information already in the conversation, and don't delay clear work with unnecessary confirmation questions.
- For larger tasks, provide a concise plan, then do the implementation and validation in the current response rather than promising future/background work.
- Be explicit about what was changed and what was actually tested. Never imply that syntax checks are GUI validation.
- Update project documentation after meaningful work so the next contributor/model has reliable continuity. Include current commit links, implementation facts, and limitations, not unverified claims.
- Keep responses direct and practical. When the user uses a shorthand they have defined, apply it consistently; document durable meanings in this guide.

This guide is intended as durable project context; the details of the latest implementation should be taken from the current source and `HANDOVER.md`.
