# Savant — Development Handover

**Updated:** 2026-10-23  
**Repository:** [MattTheBanana/savant](https://github.com/MattTheBanana/savant)  
**Branch:** `main`  
**Latest implementation commit:** [`dd7c6ac443926c43bc3489dbf6a4d264f4ac1929`](https://github.com/MattTheBanana/savant/commit/dd7c6ac443926c43bc3489dbf6a4d264f4ac1929)

Primary UI file: `webui/index.html`  
Backend and local filesystem APIs: `lyrics_editor.py`

The recent changes are committed to `main`. JavaScript parse and static checks have passed, but no interactive GUI smoke test has been run. Distinguish static checks from actual user-facing verification.

## Current editor implementation

### Toolbar and keyboard shortcut hints

- The LRC/TTML switcher is `#editorModeSwitchRow` and must remain visible.
- The functional toolbar is `#editorActionBar`. Import, editing, and Controls dropdown visibility must never depend on the optional keyboard-hints preference.
- The preference `showEditorShortcutHints` is stored in `lyrics-aligner-ui-settings`; `applyEditorPreferences()` only toggles the dedicated `#editorHotkeyBar`.
- The top toolbar uses flex layout. It stays on one row at typical desktop widths and wraps below 1180px / on narrow viewports.
- The TTML timeline zoom controls (`#editorZoomControls`) and their separators are hidden in LRC mode via the `word-mode` class on `#editorActionBar`.

### TTML zoom model

Relevant functions include `computeFitZoom()`, `laneContextBounds()`, `laneVisibleSpan()`, `setTimelineGeometry()`, `minimumTimelineZoom()`, `applyTimelineZoom()`, and `syncEditorActionBar()`.

- Fit scale is based on the largest effective per-line context after accounting for media/lyrics boundaries.
- Fit Lines is the lower zoom bound. Minus and Fit Lines are disabled at the fit scale; plus is disabled at the upper limit. The buttons update state after zooming.
- TTML zoom is unavailable without word-timed cues. Do not remove the mode/cue restrictions without clarifying intent.
- Validate with actual TTML word cues and audio. Static checks are not proof that visible scale behavior is correct.

### Add Line and timestamp rules

The top `#addLine` control dispatches to `addLine()` in LRC mode and `addTtmlLine()` in TTML mode. TTML insertion calls `insertTtmlLineAt()`. The context-menu Insert above/below actions use `insertLineAt()`.

These insertion paths now share `lineStartAtInsertion(index)`:

- Before the first line: use a nonnegative time before its timestamp, subject to the zero-second boundary.
- After the last line: use the last timestamp plus configured `txtSpacing`.
- Between two lines with distinct timestamps: use their midpoint, so the new timestamp is numerically between the surrounding timestamps even if imported data is out of chronological order.
- If the two neighboring timestamps are equal, no strictly intermediate time exists; fall back to the configured spacing after the upper line.
- LRC Add Line inserts after the selected line, or at the end when there is no valid selection. TTML Add Line also inserts after the selected line, or at the end with no valid selection.

Still verify interactively that the selected line, timeline/grid, preview, status, and undo history all update. Include insertions before the first line, between lines, and after the last line. The shared timestamp helper passed focused JavaScript tests for empty input, first/middle/last insertion, descending neighboring values, and equal-time fallback.

### Right-click context menu

- `showEditorContextMenu()` disables Copy/Cut when the target does not contain a selected text range, valid selected word, or valid row target.
- Paste is disabled while Savant's internal `editorClipboard` is empty. After an in-app copy/cut, it is enabled.
- The TTML action label is **Add word** (not “Make new word”).
- Keep the distinctions among text selection, whole-line targets, word targets, and style presets in future changes.

Note: system clipboard text may be readable through `pasteContextTarget()` where browser permissions allow it. The context menu's Paste disabled state currently tracks Savant's internal clipboard; verify external/system clipboard expectations before changing this policy.

### Generator: dropped lyrics and output folder

The user confirmed that **Choose lyrics** (native picker) correctly fills `#genOutputDirectory`, but drag-and-drop does not. The user does **not** want Savant to automatically open a native picker after dropping a file.

The drop handler tries to recover an absolute path from `File.path`, a `file://` URI, or an absolute path in drag data, validating that the basename matches the dropped filename. If the OS/browser exposes it, Savant uses the source directory. Otherwise, it keeps the dropped file selected and displays feedback. Do not infer a folder from the filename or working directory and do not automatically open a picker as fallback. Preserve explicitly selected/configured custom folders.

Many browsers deliberately omit the parent directory from local dropped files, so recovering it is not always technically possible from browser data alone.

### Generator overwrite confirmation and failure state

- Before launching an alignment or adjustment subprocess, `/api/generate` checks resolved artifact paths for existing LRC, TTML, vocal, diagnosis, and report outputs. Dry runs skip this check.
- If outputs already exist, the server returns an overwrite-required response without starting a worker and removes that attempt's temporary run directory. The UI lists existing paths in a built-in confirmation. Declining cancels the attempt; confirming retries with overwrite enabled for that run.
- The prior generic confirmation tied only to the checkbox has been removed; no prompt is shown when no relevant output file exists.
- A failed generation paints the entire segmented progress track red. Errors returned before a run is created also show the failed/red state. Verify with both a deliberately invalid run and a successful run that targets an existing output file.

### Mode toggle, timeline zoom feedback, and CLI errors

- LRC / TTML are presented as a pill-style segmented toggle with an accessible `aria-pressed` state. Import Audio and Import Lyrics sit on the same row to the right.
- At the minimum timeline zoom, Minus and Fit Lines use the same lower-bound test as zoom application, are disabled, and have high-contrast disabled styling. The state refreshes after timeline re-render/resize; the click handlers also guard against no-op zoom-out or fitting.
- Failed generator runs show the footer error text centered and red. The local worker extracts the CLI's actual error output, names common causes (for example output exists, invalid lyrics, missing FFmpeg/model/dependency, invalid JSON/settings, or audio processing), and keeps the useful detail instead of displaying an opaque numeric exit code.
- Static verification passed: inline JavaScript parses, there are no duplicate HTML IDs, disabled zoom guards are present, and sample error text was checked against the named error categories. A GUI smoke test with a real TTML track and deliberately failed CLI runs is still required.

### Installation-local Preferences and settings synchronization

- Preferences, including Generator Defaults, are stored in `savant-settings.txt` in the installation directory. It contains pretty-printed UTF-8 JSON, intentionally using a plain-text extension for easy editing.
- The file is generated on first launch from existing browser preferences when no installation file exists. When the file exists, its settings become authoritative and are applied to both Preferences and the generator form.
- `/api/settings` reads the current file and returns a SHA-256 revision. The UI polls every 1.2 seconds so external file edits synchronize back into the running UI; Preferences edits are debounced and written atomically back to the file. Conflicting concurrent file changes are detected rather than silently overwritten.
- `.gitignore` excludes the runtime `savant-settings.txt` and its temporary atomic-write file so normal Git updates preserve each installation's settings.
- If the app reports invalid JSON in the settings file, fix the syntax in a text editor and save valid JSON; the UI continues checking for file changes.

### Controls-menu and LRC Delete shortcut

- `LRC Controls` / `TTML Controls` and the saved-agent-preset menu use the shared `toggleFloatingMenu()`. It had been missing, so clicks raised a runtime ReferenceError. The helper now opens/closes the menus, maintains `aria-expanded`, closes the other floating menu, and positions the fixed controls menu next to the toolbar button.
- The LRC context menu's Delete Line item now advertises the `Delete` key and tooltip. The existing keyboard handler deletes the selected line in LRC mode when keyboard focus is not inside an editable text/input control.

### TTML toolbar, spacing, style help, and jump-to-current-line shortcut

- In TTML mode, Add/Delete Line/Word actions are shown before the timeline zoom buttons, matching the LRC action-first toolbar arrangement.
- The TTML editor's bottom padding and the adjacent line/word-count footer padding are reduced to tighten the gap above the filename/count row.
- The TTML style-reference info icon is now a real button in the label row. Clicking it explains that the value is a TTML style ID, separate from Singer/agent metadata, and may have no visible effect without a matching defined style. The global toast-dismiss handler deliberately leaves this help toast visible.
- Double-tapping Shift within 450 ms jumps the current/selected line into view in either editor mode. The shortcut is shown in the LRC and TTML Controls menus and the optional shortcut-hints bar.
- In LRC mode, the Lyric column header has a compact **Jump to current line** button that appears when the currently edited/selected line is not fully visible. The click listener is delegated from `#gridHead` because `renderGrid()` rebuilds that header dynamically. Visibility updates on LRC grid render, line selection/focus, scroll, and resize.
- Static verification: JavaScript parsing passed, the runtime header contains a single jump button, and the dynamic event delegation and both jump paths are present. GUI testing remains necessary to tune the visibility threshold and the double-Shift timing on the user's actual browser.

## Other current UI state

The following are present in `webui/index.html`; GUI verification remains outstanding:

- Browser tab title follows the active section.
- Preferences uses vertical tabs: Visuals, UI, Utility, Generator Defaults.
- Generator's “Use Audio Directory” / “Use Lyrics Directory” controls sit beside Browse.
- Path suggestion rows omit the right-side Folder/File label; new-directory paths use orange/missing-path styling.
- Context-menu shortcut hints use the same font size as action labels.
- Persistent audio player dock remains a key regression target.

## Validation status

Latest static checks for the settings/controls work:
- JavaScript parses and no duplicate HTML IDs were found.
- Confirmed `toggleFloatingMenu()` now has a definition, both menu triggers call it, and the Delete context action includes the `Delete` shortcut.
- Confirmed GET/POST `/api/settings` routes, file revision checks, atomic text-file writes, and `.gitignore` protection are present.
- Actual GUI testing, Python test-suite execution, and live external-edit synchronization testing are still outstanding.


Static checks against the latest UI source:

- Inline JavaScript parses.
- No duplicate HTML IDs.
- Legacy toolbar-hiding selector is absent.
- Zoom controls are scoped to TTML; zoom lower bound equals Fit Lines; button-state refresh runs after zoom application.
- Generator drop-path resolver passed focused Windows/POSIX path and filename-match checks.
- Shared line timestamp helper passed focused tests for first, middle, last, empty, descending-neighbor, and equal-neighbor cases.
- Context-menu markup now has disabled-state logic for Copy/Cut/Paste and uses the new Add word label.
- Generator JavaScript parses; output existence checks are placed before the worker thread starts. Confirmation retries reuse the selected uploads, and failed/start-error states apply red progress styling.

Not yet run:

- Python project tests.
- Interactive browser checks of toolbar responsiveness, preference persistence, zoom appearance, line insertion, context menu behavior, and external clipboard interactions.
- Real drag/drop tests across the user's browser/OS configuration.

## Working expectations

Read current implementation before editing it. Make targeted changes and preserve unrelated functionality. Ask a concise clarifying question when intent or implementation choice is genuinely ambiguous. Implement clear requirements completely; distinguish static checks from interactive validation. Commit changes on `main` and link commits in implementation reports.
