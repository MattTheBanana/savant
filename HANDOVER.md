# Savant — Development Handover

**Updated:** 2026-10-23  
**Repository:** [MattTheBanana/savant](https://github.com/MattTheBanana/savant)  
**Branch:** `main`  
**Latest UI implementation commit:** [`92672bf4a0a02b11a2f48b09aafd5bcff8ffa8a6`](https://github.com/MattTheBanana/savant/commit/92672bf4a0a02b11a2f48b09aafd5bcff8ffa8a6)

Primary UI file: `webui/index.html`  
Backend and local filesystem APIs: `lyrics_editor.py`

The latest changes are committed to `main`. The editor toolbar, shortcut-hints preference, TTML zoom behavior, and generator drop-path feedback have been updated. JavaScript parse/static checks passed, but no interactive browser/native-picker smoke test has been run. Do not claim interaction behavior has been verified without testing it.

## Current editor implementation

### Toolbar and keyboard shortcut hints

- The LRC/TTML switcher is in `#editorModeSwitchRow` and must remain visible.
- The functional editor toolbar is `#editorActionBar`; its import, editing, Controls dropdown, and relevant mode-switching behavior must never be controlled by the optional hints preference.
- The preference is `showEditorShortcutHints`, stored in `lyrics-aligner-ui-settings`, and is applied by `applyEditorPreferences()`.
- `#editorHotkeyBar` is the distinct bottom keyboard-hints bar. Its contents use LRC/TTML-specific classes and `updateTimelineControlsContext()` toggles the active mode's hints.
- The top bar now uses flex rather than the previous inconsistent grid track/column assignments. It stays on one row at typical desktop widths and wraps below 1180px; narrow layouts also wrap editing actions.
- The zoom group (`#editorZoomControls`) and its adjacent separators are hidden in LRC mode using the `word-mode` class on `#editorActionBar`. They are TTML timeline controls, not LRC controls.

### TTML zoom model and expected behavior

Relevant functions include `computeFitZoom()`, `laneContextBounds()`, `laneVisibleSpan()`, `setTimelineGeometry()`, `minimumTimelineZoom()`, `applyTimelineZoom()`, and `syncEditorActionBar()`.

- Fit scale is based on the largest *effective* per-line context after clamping to the media/lyrics duration. Calculating fit from an unclamped phrase-plus-context span made the requested scale disagree with what a lane could actually display, especially at the start/end of audio.
- The Fit Lines scale is the lower zoom bound. The minus button and Fit Lines are disabled when already at that scale; plus is disabled at the upper scale limit. The button state is refreshed after a zoom.
- Keep this consistent: a minus click must never reduce zoom below Fit Lines; Fit Lines should be disabled when it would not change the view; and the first plus click above Fit Lines should visibly increase timeline detail.
- TTML zoom buttons are intentionally unavailable when there are no word-timed cues. Do not remove the mode/cue restrictions without confirming intent.
- Verify zoom behavior with actual audio and TTML word cues. Current evidence is a JavaScript parse/static check only, not a real GUI test.

### Add Line

Current markup uses `#addLine` in both modes. Its click handler dispatches to `addLine()` in LRC mode and `addTtmlLine()` in TTML mode; the latter calls `insertTtmlLineAt()`. The current code does not have a separate `#addLineTtml` element.

Expected behavior to verify interactively:

- LRC inserts a new empty lyric line immediately after the selected line, or at the end if nothing is selected, and updates selection, grid, preview, status, and undo history.
- TTML inserts a new TTML lyric line, stays in word-timing mode, selects/scrolls to it, and updates preview, status, and undo history.
- Check insertion at the first position and at the end, as well as with an empty editor where applicable.

### Generator: dropped lyrics and output folder

The user confirmed that **Choose lyrics** (native picker) correctly fills `#genOutputDirectory`, but drag-and-drop does not. The user does **not** want an automatic native file-picker prompt after dropping a file.

The drop handler now:

- Tries to recover an absolute path from `File.path`, a `file://` URI, or an absolute path in the drag data, validating that the basename matches the dropped file.
- Uses that path to set the directory when the OS/browser actually exposes it.
- Otherwise keeps the dropped `File` selected and shows feedback that this browser did not expose the source folder. Do not automatically open a picker as a fallback.
- Preserves an explicitly selected/configured custom output folder; automatic lyrics-directory behavior should not overwrite a user's explicit folder choice.

The underlying browser limitation remains: many browsers do not expose an absolute parent directory for a dropped local file. Do not infer a path from the filename or the working directory. If the user requests another approach, explain the trade-off before making a behavior-changing choice.

## Other current UI state

The following are present in `webui/index.html`; real GUI verification is still outstanding:

- Browser tab title follows the active section (for example, `savant • Edit`, `savant • Generate`, `savant • Preferences`).
- Preferences uses vertical tabs in this order: Visuals, UI, Utility, Generator Defaults.
- Generator's “Use Audio Directory” and “Use Lyrics Directory” actions sit beside Browse and have no trailing ellipses.
- Path suggestion rows omit the right-side Folder/File label; paths for new directories use orange/missing-path styling.
- Context-menu keyboard shortcut hints use the same font size as action labels.
- The bottom persistent audio player dock must remain usable and unobscured.

## Validation status

Static checks run against the latest `webui/index.html`:

- Inline JavaScript parsed successfully using a JavaScript function-constructor syntax check.
- No duplicate HTML IDs were found.
- Confirmed the old toolbar-hiding rule is absent.
- Confirmed LRC mode hides the TTML zoom group, zoom lower bound equals the Fit Lines scale, zoom boundary state is updated after applying zoom, and the drag-path feedback remains without automatic picker invocation.

Not yet run:

- Python project tests.
- Browser smoke tests of hints persistence/toggling, toolbar layout, zoom, and Add Line.
- Drag/drop tests across the browser/OS combinations the user uses.

## Working expectations

Read the current implementation before editing it. Make targeted changes and preserve unrelated functionality. Ask a concise clarifying question when user intent or an implementation choice is genuinely ambiguous. Implement all clear requirements, and distinguish static checks from actual behavioral verification. Commit changes on `main` and link commits when reporting the result.
