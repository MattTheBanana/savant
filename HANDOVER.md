# Savant — Development Handover

**Updated:** 2026-10-23  
**Repository:** [MattTheBanana/savant](https://github.com/MattTheBanana/savant)  
**Branch:** `main`  
**Latest implementation commit:** [`b7a7fae3d405390c3c6d738530fcc961a4d3cac6`](https://github.com/MattTheBanana/savant/commit/b7a7fae3d405390c3c6d738530fcc961a4d3cac6)

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

## Other current UI state

The following are present in `webui/index.html`; GUI verification remains outstanding:

- Browser tab title follows the active section.
- Preferences uses vertical tabs: Visuals, UI, Utility, Generator Defaults.
- Generator's “Use Audio Directory” / “Use Lyrics Directory” controls sit beside Browse.
- Path suggestion rows omit the right-side Folder/File label; new-directory paths use orange/missing-path styling.
- Context-menu shortcut hints use the same font size as action labels.
- Persistent audio player dock remains a key regression target.

## Validation status

Static checks against the latest UI source:

- Inline JavaScript parses.
- No duplicate HTML IDs.
- Legacy toolbar-hiding selector is absent.
- Zoom controls are scoped to TTML; zoom lower bound equals Fit Lines; button-state refresh runs after zoom application.
- Generator drop-path resolver passed focused Windows/POSIX path and filename-match checks.
- Shared line timestamp helper passed focused tests for first, middle, last, empty, descending-neighbor, and equal-neighbor cases.
- Context-menu markup now has disabled-state logic for Copy/Cut/Paste and uses the new Add word label.

Not yet run:

- Python project tests.
- Interactive browser checks of toolbar responsiveness, preference persistence, zoom appearance, line insertion, context menu behavior, and external clipboard interactions.
- Real drag/drop tests across the user's browser/OS configuration.

## Working expectations

Read current implementation before editing it. Make targeted changes and preserve unrelated functionality. Ask a concise clarifying question when intent or implementation choice is genuinely ambiguous. Implement clear requirements completely; distinguish static checks from interactive validation. Commit changes on `main` and link commits in implementation reports.
