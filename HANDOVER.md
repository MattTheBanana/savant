# Savant — Development Handover

**Updated:** 2026-10-23  
**Repository:** [MattTheBanana/savant](https://github.com/MattTheBanana/savant)  
**Branch:** `main`  
**Latest implementation commit:** [`7f56150d9522cc09103d332e1ace057bf6ca22a8`](https://github.com/MattTheBanana/savant/commit/7f56150d9522cc09103d332e1ace057bf6ca22a8)

Primary UI file: `webui/index.html`  
Backend and local filesystem APIs: `lyrics_editor.py`

General project architecture, development workflow, validation guidance, and collaboration expectations: [`DEVELOPMENT.md`](DEVELOPMENT.md).

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

### Custom player bar, TTML agent presets, and configurable Shift shortcut

- Replaced the browser-native `<audio controls>` UI with Savant-styled Play/Pause, seek, mute, and volume controls. The audio element remains only as the playback engine; the player dock has one separate current/duration readout, and obsolete native-control CSS selectors were removed.
- Edit-screen buttons, editor context-menu actions, saved agent-preset actions, color picker controls, and player buttons render in consistent title case.
- Importing TTML collects declared `ttm:agent` IDs as well as agent values attached to lines and word cues. Unique file-derived presets use the agent ID as the agent value and inherit the first available line/word style properties. On the next lyric import, prior file-derived presets are replaced while user-saved presets are preserved.
- The TTML context-menu action now says **Delete Words** for a multi-word selection and **Delete Word** for one word. The top-bar action is plural only when more than one word is selected.
- Added a **Double-Shift interval (milliseconds)** preference (150–1000 ms, default 450 ms). It is saved by the existing browser/installation settings synchronization and is used by the Shift × 2 jump shortcut.
- Static checks on the latest UI source passed: inline JavaScript parses; there are no duplicate IDs; native audio controls and their old CSS-hiding rules are absent; the custom player controls and all expected media event updates exist; only one time-readout element exists; Shift timing is connected to settings; and both automatic agent presets and singular/plural delete labels are present.
- Actual browser/GUI playback, agent-preset application against real TTML files, and changing/reloading the Shift preference have not yet been interactively tested.

### Modifier-based line and word selection

- The LRC line grid supports plain click to select one line, Shift-click and Shift-drag to select an inclusive line range, Ctrl/Cmd-click to toggle individual lines, and Shift+Up/Down keyboard range selection. Modifier gestures intercept native text selection so selecting multiple lines does not highlight lyric text. The lyric editor is slightly inset from the right edge, leaving a strip for line selection.
- In TTML mode, Shift-click / Ctrl-Cmd-click and Shift-drag line selection begin in the left line-label gutter; the entire selected lane is highlighted and selected lanes can take keyboard focus. Shift+Up/Down also extends line ranges. The waveform/word-track area keeps its existing word marquee and drag-to-retime gestures, and waveform clicks remain dedicated to seeking/scrubbing.
- TTML word blocks support Shift-click range selection across sequential word cues and Ctrl/Cmd-click to add/remove individual words. Existing marquee selection and drag-to-retime gestures remain separate from line-label range selection.
- The Preferences setting `centerModifierSelection` defaults to off. Modifier-based line selection keeps the current scroll position unless the selected line needs to be revealed; when enabled, it smoothly centers the selection. The setting is synchronized through local storage and `savant-settings.txt`.
- The top-bar line delete action and TTML Delete Line action delete all selected lines and update their labels to **Delete Lines** when appropriate. Single-line deletion remains singular. Context-menu targeted line deletion stays scoped to the clicked line.
- Line and word selection anchors are included in undo/redo snapshots. Importing new lyrics resets the selection to the first line.
- Latest static verification: the inline JavaScript parses; there are no duplicate HTML IDs; the LRC gutter, modifier clicks/drags, keyboard range selection, optional eased centering preference, TTML gutter selection, word-range selection, and multi-line deletion paths are present. Interactive browser testing has not been run, so pointer behavior and visual feedback still need GUI verification.

### Controls menus, playback shortcuts, and selection scrolling

- The editor Controls menu lists shortcuts as consistent visible gestures, including `Left Click + Drag`, `Middle Click + Drag`, `Shift + Left Click + Drag`, and `Ctrl + Scroll Wheel`. The former TTML footnote is now a normal row. Both LRC and TTML menus have separate Space and Ctrl + Space playback entries; Ctrl + Z / Ctrl + Y remain in the right-click menu, not the Controls menu.
- `Shift + F` inserts a line via the same mode-aware behavior as the Add Line button: LRC line in LRC mode and a blank TTML line in TTML mode. The TTML right-click menu includes Select All Words in Line (`Ctrl + A`) and Select All Words in All Lines (`Ctrl + Shift + A`), backed by the same selection helper as the keyboard shortcuts.
- The UI preference `centerModifierSelection` now covers clicking/keyboard-selecting lines and selecting TTML words. When off, the editor avoids centering and only scrolls lines into view as needed; when on, it uses eased centering for selected lines and clicked words.
- TTML style-reference information is shown in a viewport-clamped popover anchored to the info button, rather than a toast pinned to the bottom edge. The LRC Jump to Current Line button uses standard small-button styling.
- Actual browser/GUI verification has not been run. Static verification on the latest UI source passed: inline JavaScript parses; no duplicate HTML IDs; the info popover, select-all context actions, Shift + F handler, updated Controls rows, and shared centering preference are present.

### Custom audio player dock and branding

- The fixed dock has a full-width seek/progress bar, a controls row (circular play/pause, Block Pause, mute/unmute SVG icons, volume slider, and current/duration time to hundredths), and a separate metadata row. The audio filename is centered beneath the controls, and file size is right-aligned on that row.
- The top-left wordmark is the text “Savant” in medium-weight italics, without a music-symbol mark.
- Block Pause reuses `blockPause()`: when audio is playing, it pauses and seeks back to `playbackStartPosition`, the start of the current playback segment. Pressing the action while paused follows the existing keyboard behavior and starts playback.
- The mute and playback controls use inline SVG artwork, not emoji glyphs. The volume control remains visible on narrow screens with a reduced width. The time display uses `fmtTime(..., 2)`.
- Latest static verification: inline JavaScript parses; no duplicate HTML IDs; full-width seek bar, metadata row, filename/file-size layout, branding styles, and player control IDs are present. Actual responsive browser testing has not yet been run.

## Working expectations

Read current implementation before editing it. Make targeted changes and preserve unrelated functionality. Ask a concise clarifying question when a material ambiguity blocks a correct implementation; don't repeatedly ask questions already answered in the conversation. Be thorough about implementing each requested detail and checking for adjacent regressions. Distinguish static checks from interactive validation. Commit changes on `main`, update this handover and the general `DEVELOPMENT.md` when appropriate, and link commits in implementation reports.

User-specific collaboration guidance:
- “Add a preference for that” means implement a real option in the Preferences UI, with a sensible default and persistence through the existing local/browser plus `savant-settings.txt` synchronization path. It does not mean only changing the default or adding a temporary toggle.
- The user primarily uses Windows CMD, so default shell instructions to CMD syntax unless they ask for PowerShell or another shell.
- Preserve local model weights, outputs, and untracked custom files. Never recommend destructive cleanup or force-reset operations as a casual troubleshooting step; back up and compare conflicting files first.
- Thoroughness and accuracy matter: inspect relevant code, implement the whole request, validate syntax and static invariants, and say explicitly when real GUI/browser testing was not performed.

## Latest follow-up: player dock, jump visibility, and editor switching

- The fixed player dock now places the filename in regular weight on the same controls row as Play/Pause, Block Pause, volume, and time. The seek bar remains above; row spacing was increased, including responsive rules for narrow windows.
- The LRC and TTML “Jump to current line” buttons now treat the viewport edges as visible (with a one-pixel tolerance) rather than requiring an extra pixel of margin.
- Added the UI preference **Follow selected LRC line when switching to TTML**, default On. A new explicit LRC line selection can be brought into view in TTML and clears the prior word selection. Turn it Off to keep the existing TTML word selection/view when changing modes.
- The LRC and TTML editor scroll positions are captured and restored on mode switches, preventing playback-time switching from resetting the TTML viewport to the top.
- LRC lyric text is inset less from the time column and its right-side blank strip is wider for line selection.
- Static verification after the change: inline JavaScript compiles; no duplicate static HTML IDs; the preference is wired through defaults, form synchronization, reset defaults, and save listeners; both jump-button visibility checks, two-row player layout, lyric gutter, and mode scroll restoration are present.
- Not yet verified interactively in a browser. In particular, test mode switching during playback, switching after selecting an LRC line, the preference On/Off across reload and installation settings sync, viewport-edge jump visibility, and player layout at desktop/mobile widths.

## Player dock typography and controls follow-up

- The playback timer now sits immediately after the volume slider, before the filename metadata group.
- File-size text matches the timer size at the breakpoints where the size is shown; the narrow-screen size follows the narrow-screen timer size.
- Enlarged the Block Pause and mute/volume icons on desktop, with a proportional adjustment on compact screens. The play glyph is nudged left to optically center it, and the pause-bars geometry is centered separately.
- Added more line-height and vertical padding to the filename to prevent descenders such as y and g from being clipped.
- Static checks passed: inline JavaScript compiles, no duplicate HTML IDs, and the timer markup sits after the volume slider and before the filename group. Browser visual confirmation has not been run.

## Editor sync centering and playback scroll stability

- Increased the player filename from 12px to 13px on desktop and from 11px to 12px on narrow screens.
- The play/pause control no longer has a filled circle by default; the shared button hover background/border still appears on hover.
- Expanded the centered workspace max-width to 1780px so the editor panel can align closer to the left edge of the Edit navigation while extending farther to the right.
- Switching from LRC to TTML with **Follow selected LRC line when switching to TTML** enabled now centers the selected line in the timeline. Switching from TTML to LRC centers the corresponding selected line in the line grid.
- Mode changes cancel pending smooth-scroll animations and temporarily suppress playback-driven auto-pan while the view and selection are restored. This avoids the playback-follow handler fighting the mode-switch scroll restoration and should preserve the TTML viewport anchor while toggling modes during playback.
- Static validation passed: inline JavaScript compiles; there are no duplicate static IDs; both direction-specific centering paths, preference guard, playback auto-pan suppression, scroll-animation cancellation, filename sizing, play-button default background, and workspace width are present. Interactive browser testing remains outstanding.

## Matching LRC and TTML count footer spacing

- Removed the TTML-only reduced vertical padding from the shared line/word-count footer. LRC and TTML now both use the common `.grid-footer` padding (`10px 12px`), with no mode-specific padding difference.
- Static checks passed after this follow-up: inline JavaScript compiles; no duplicate static HTML IDs; the TTML-only override is absent and the shared footer padding remains defined. Interactive appearance still needs browser confirmation.

## Separate LRC Shift-arrow control description

- Split the LRC Controls menu's left/right-arrow row into two controls: `← / →` nudges the selected line or seeks during playback; `Shift + ← / →` applies the configured multiplier to the nudge/seek step. Use the actual arrow symbols in the shortcut label.
- Static checks passed: inline JavaScript compiles, there are no duplicate static HTML IDs, and the old combined description is removed.

## Consolidated TTML seek gesture help

- Combined the separate `Left Click + Drag Playhead` and `Left Click + Drag Waveform` help rows into one `Left Click + Drag` row: “Seek the audio by dragging the playhead or waveform.”
- Static validation passed: inline JavaScript compiles, there are no duplicate static HTML IDs, and the two old rows are replaced by the combined description.

## TTML Ctrl-drag for moving one word from a multi-selection

- Split the TTML word-drag help into two rows: `Left Click + Drag on Word` moves the selected word(s); `Ctrl + Left Click + Drag on Word` moves only the clicked word from a multi-selection.
- Fixed the underlying gesture: when Ctrl/Cmd is held on an already-selected word in a multi-selection, pointer-down now arms a pending single-word drag instead of immediately toggling the word out of the selection. Crossing the pointer movement threshold begins moving only that word. Releasing without moving still performs the normal Ctrl/Cmd-click selection toggle.
- Ctrl-drag is limited to word bodies, not resize handles. Ordinary group drags and Shift-drag snap behavior remain on their existing paths.
- Static validation passed: inline JavaScript compiles; no duplicate static HTML IDs; separate help rows and the Ctrl-drag pending/movement/toggle paths are present. Interactive pointer testing remains outstanding.

## Clarified TTML Shift-drag snapping label

- Updated the TTML Controls wording to `Shift + Left Click + Drag on Selection` — “Snaps the selection to the time grid or playhead when close.”
- Static validation passed: inline JavaScript parses, no duplicate static HTML IDs, and the previous label/description are removed.

## Deselect TTML line selection with Escape

- Pressing Escape in the TTML editor clears the selected line selection, resets the active selected-line index, and refreshes timeline selection styling, word inspector state, and action controls.
- Existing Escape behavior for open context menus, preset menus, timeline controls, preview drawer, color picker, and word-style help retains priority. Word-cue selection is also cleared as part of clearing a TTML line selection.
- Static validation passed: inline JavaScript compiles and there are no duplicate static HTML IDs. Interactive browser testing remains outstanding.

## TTML Shift+Arrow nudge versus playback seek

- In TTML word-editing mode, Left/Right nudges the selected word or word group by the normal step; Shift+Left/Right now applies the configured nudge multiplier instead of seeking to a word boundary.
- When no word cue is selected, the arrow keys remain playback controls: Left/Right seeks by the configured step and Shift+Left/Right seeks to the nearest word boundary.
- Split the former combined arrow-help description into separate word-editing and playback-control rows under the TTML Controls menu. Playback seeking rows are now listed under the `Playback controls` heading.
- Static validation passed: inline JavaScript compiles, no duplicate static HTML IDs, and the old combined help row is removed. Interactive browser testing remains outstanding.

## Remove periods from editor control descriptions

- Removed terminal periods from all 26 one-sentence control descriptions in the LRC and TTML Controls menu, including the separate word-editing and playback-control rows.
- Static validation passed: inline JavaScript compiles, no duplicate static HTML IDs, and no control description in the menu ends with a period.

## Player pause and volume icon refinement

- Applied a small leftward optical correction to the playback pause icon and slightly increased the visible height of its bars.
- Replaced the outlined volume glyph with a filled, fuller-proportioned speaker and sound-wave icon. The muted state uses the same filled speaker body with a stroked mute mark; both the initial markup and runtime icon strings are updated.
- Static validation passed: inline JavaScript compiles and no duplicate static HTML IDs were found. Visual confirmation in a browser remains outstanding.

## Escape deselects TTML word selections

- Expanded Escape handling in TTML mode so it clears selection when a line, a single word cue, or a multi-word selection is active. Selection styling, active indices, and inspector state are refreshed.
- Existing Escape priority for open menus and popovers remains unchanged.
- Static validation passed: inline JavaScript compiles and no duplicate static HTML IDs were found. Interactive browser testing remains outstanding.

## Player icon alignment and volume slider fill

- Shifted the playback pause glyph very slightly down and right for optical alignment.
- Enlarged and strengthened the block-pause glyph on desktop, with a proportionate size for the compact layout, so its visible weight better matches the other controls.
- Added a live filled/unfilled gradient to the volume slider, driven by the current volume value and refreshed with player controls.
- Static validation passed: inline JavaScript compiles, no duplicate static HTML IDs, and the volume fill is updated from the current slider value. Browser visual confirmation remains outstanding.

## Align editor workspace and center filename in player bar

- Added resize-aware alignment for the edit screen: its left edge is shifted to line up with the left edge of the top-bar Edit button, while its right edge remains in place so the usable panel width is reduced accordingly. The shift is bounded to avoid moving the screen outside the shell on very wide layouts.
- Centered the loaded filename against the full player dock rather than the remaining flex space beside the controls. The title width is dynamically limited to the space that clears the left-side controls; the compact mobile layout retains its flow-based title placement.
- Standardized visible word wording to `word or words`, including the TTML drag/nudge help and natural singular/plural wording in selection and preset-paste notifications.
- Static validation passed: inline JavaScript compiles, no duplicate static HTML IDs, old `word(s)`/`word group` phrasing is removed from the relevant UI strings, and the alignment/centering calculations are connected to initialization and resize handling. Interactive/browser visual testing remains outstanding.

## Preserve preset casing and position dropdown at its trigger

- Removed automatic CSS capitalization from saved preset names in the agent preset dropdown so their displayed case matches the name as saved.
- Fixed the preset dropdown appearing at the top-left corner by positioning it from the trigger's viewport rectangle when opened. It aligns to the trigger's left edge, flips above when there is insufficient space below, and is repositioned on window resize. The shared positioning helper also keeps the timeline controls menu anchored to its trigger.
- Static validation passed: inline JavaScript compiles, no duplicate static HTML IDs, preset labels are not transformed to title case, and the floating menus use trigger-based positioning. Interactive browser testing remains outstanding.

## Stop control icon and wording

- Replaced the unclear circular-arrow/pause-bars glyph with a simple filled square stop icon. Renamed its visible and accessible label to `Stop`; its tooltip and the Ctrl+Space help description now say “Stop playback and return to the start of the current playback segment.”
- Nudged the square down by 1px for optical alignment in both desktop and compact layouts.
- Static validation passed: inline JavaScript compiles, no duplicate static HTML IDs, and the old SVG is replaced by a centered square path. Browser visual testing remains outstanding.

## Match Generate and Preferences views to the editor width

- Applied the same resize-aware horizontal offset and width reduction to the Generate and Preferences screen containers as the Edit screen, so their left edges align with the top-bar Edit button and their right edges remain aligned with the existing shell content edge.
- The alignment helper now propagates its computed offset to all three main screens and continues to recalculate on window resize.
- Static validation passed: inline JavaScript compiles, no duplicate static HTML IDs, and all three screens share the same alignment rule. Browser layout verification remains outstanding.
