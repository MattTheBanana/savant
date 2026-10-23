# Savant — Development Handover

**Updated:** 2026-10-23  
**Repository:** [MattTheBanana/savant](https://github.com/MattTheBanana/savant)  
**Branch:** `main`  
**Latest code commit before this handover update:** [`10d13225bf8b9b2d27b1777bf6962df62a479777`](https://github.com/MattTheBanana/savant/commit/10d13225bf8b9b2d27b1777bf6962df62a479777)

Primary UI file: `webui/index.html`  
Backend and local filesystem APIs: `lyrics_editor.py`

This document supersedes the older handover notes that describe a separate feature branch and PR status. The current work is on `main`. The latest Preferences/generator UI changes have static checks, but the current editor-controls regression has **not** been fixed yet.

## Immediate priority — Repair the editor controls

An earlier interpretation mixed up the user's request. The desired optional bar is the **bottom keyboard-shortcut / hotkey indicators bar**, not the functional toolbar at the top of the editor.

### 1. Keep the top editor toolbar visible

The top toolbar must remain visible regardless of the bottom hints preference. It contains:

- Import Audio and Import Lyrics.
- Zoom out (`−`), Zoom in (`+`), and Fit Lines.
- Add Line; Add Word when the editor is in TTML word mode; Delete Line / Delete Word(s) as appropriate.
- The LRC/TTML-specific Controls dropdown.

The LRC/TTML mode switcher is its own row and must remain visible.

Relevant markup and functions in `webui/index.html`:

- `#editorModeSwitchRow`
- `#editorActionBar`
- `#editorImportGroup`
- `#editorZoomControls`
- `#editorActionButtons`
- `#timelineControlsTrigger`
- `syncEditorActionBar()`
- `setGridMode()`

### 2. Make the preference control only the bottom hints bar

The existing preference is named `showEditorControlsBar`, is saved in `lyrics-aligner-ui-settings`, and is applied by `applyEditorPreferences()`.

The current problematic code is:

```javascript
document.body.classList.toggle(
  'show-editor-controls-bar',
  Boolean(settings.showEditorControlsBar)
);
```

paired with CSS that hides the actual functional toolbar and TTML timeline toolbar:

```css
body:not(.show-editor-controls-bar) #editorActionBar,
body:not(.show-editor-controls-bar) .timeline-toolbar {
  display: none !important;
}
```

This behavior is incorrect.

Rename the preference to something unambiguous, such as **Keyboard shortcut hints bar**, with Hide / Show choices, and wire it exclusively to a dedicated bottom bar. Ensure existing saved settings migrate gracefully (for example, map the old `showEditorControlsBar` key to the new preference or safely default the new preference to false). Do not tie this setting to `#editorActionBar` or any functional toolbar.

### 3. Add a dedicated bottom keyboard-hints bar

The current `#timelineControlsMenu` contains LRC/TTML keyboard and interaction hints, but it is a popup triggered by `#timelineControlsTrigger`. The current `#gridStatus` footer only shows editor status and the lyrics filename; it is not the requested keyboard-hints bar.

Inspect the shortcut text already in `#timelineControlsMenu` and reuse appropriate hints to create a distinct, compact bar at the bottom of the editor. It must:

- Be independently showable/hideable via Preferences.
- Reflect the active mode where that matters (LRC vs TTML).
- Avoid unnecessarily duplicating identical shortcut text.
- Remain separate from the Controls dropdown, which should continue to work.
- Not obscure the persistent audio player dock or make the lyric editor unusably short.

### 4. Repair the top toolbar layout

The toolbar is not reliably appearing on one line. Current CSS gives `.editor-action-bar` a grid layout with six defined tracks, but some children are assigned up to grid column eight. At widths below roughly 1180px, other CSS switches the toolbar to flex with wrapping.

Fix the layout intentionally:

- Keep the top controls on one line at typical desktop widths.
- Group imports, zoom actions, editing actions and the Controls dropdown logically.
- Do not assign children to nonexistent grid tracks.
- Do not hide controls to force one-line layout.
- On narrow screens, permit a deliberate compact/responsive layout instead of overlap or clipping.

### 5. Verify zoom buttons

The zoom event handlers are present:

```javascript
$('zoomIn').addEventListener(
  'click',
  () => applyTimelineZoom(timelineZoom * 1.25)
);
$('zoomOut').addEventListener(
  'click',
  () => applyTimelineZoom(timelineZoom / 1.25)
);
$('zoomFit').addEventListener(
  'click',
  () => applyTimelineZoom(computeFitZoom(), true)
);
```

The controls are disabled when `gridMode !== 'words'` by `syncEditorActionBar()`. This may be intentional because the timeline zoom applies to TTML word timing, but the buttons must work in TTML mode.

Trace initialization of `timelineZoom`, timeline geometry, and `applyTimelineZoom()` rendering. Check for a zero or invalid initial zoom, uninitialized geometry, missing redraw, or stale UI state. Don't remove the LRC/TTML restriction without confirming the intended behavior.

Expected:
- `+` increases visible timeline detail.
- `−` decreases visible timeline detail.
- Fit Lines restores the fitted view.
- Buttons have a clear and intentional disabled state when unavailable.

### 6. Verify Add Line in both modes

Existing controls and handlers include:

- `#addLine`, wired to `addLine()` in LRC mode.
- `#addLineTtml`, wired to `addTtmlLine()` in TTML mode.
- `insertTtmlLineAt()` handles TTML line insertion.

`syncEditorActionBar()` hides the top Add Line button in word mode, where the TTML-specific button is used. Verify the complete mode-transition flow.

Expected:
- **LRC:** the top Add Line button inserts an empty lyric line below the selected line, or at the end if none is selected.
- **TTML:** the TTML Add Line button inserts a new TTML line and preserves word-timing mode.
- Selection, rendered grid/timeline, preview, status, and undo history all update correctly.

Do not treat the existence of a button or event-handler registration as proof it works.

## Secondary outstanding issue — Generator lyrics path

The generator output folder has reportedly still failed to populate automatically when lyrics are imported.

In `genSetFile(key, file)`, selecting lyrics uses `genSourceDirectory(file)` and `outputDirectory.dataset.outputDirectoryMode` to decide whether to set `#genOutputDirectory`. The last code change attempts to refresh automatic locations while preserving an explicitly browsed/configured custom folder.

The user has not yet said whether the failure occurs when using **Choose lyrics** or when dragging/dropping a file. The native picker returns an absolute local path, whereas browser drag-and-drop may hide the original absolute path. Ask which workflow fails before selecting a fix. Preserve custom output-folder choices.

Do not let this separate generator issue block repair of the editor controls.

## Other current UI state

The following are present in the latest code and passed static checks in the last review, but still need real GUI verification:

- Browser tab title follows the active section (for example, `savant • Edit`, `savant • Generate`, `savant • Preferences`).
- Preferences uses vertical tabs in this order: Visuals, UI, Utility, Generator Defaults.
- Generator's “Use Audio Directory” and “Use Lyrics Directory” actions sit beside Browse and have no trailing ellipses.
- Path suggestion rows no longer show the right-side Folder/File label; paths for new directories use orange/missing-path styling.
- Context-menu keyboard shortcut hints use the same font size as action labels.

The latest code commit above changed `webui/index.html`. No interactive browser/native picker smoke test was completed in that environment.

## Validation checklist before marking controls fixed

1. Confirm the top toolbar remains visible when the keyboard-hints preference is Off.
2. Turn the hints preference On and Off; verify only the bottom hints bar changes.
3. Verify hints update sensibly when switching LRC/TTML modes.
4. Test zoom in, zoom out and Fit Lines in TTML mode with an audio file and word cues loaded.
5. Test Add Line in LRC mode and TTML mode, including first-line/end-of-list insertion.
6. Confirm the LRC/TTML mode switcher, Controls dropdown and persistent audio player still work.
7. Test at desktop and narrow window widths for clipping, overflow and overlapping buttons.
8. Reload and confirm the hints preference persists.
9. Parse all inline JavaScript; check duplicate IDs, stale DOM selectors, and HTML structure.
10. Run Python syntax checks and available project tests. Perform an interactive GUI smoke test if the environment allows it.
11. Commit the repair on `main`, then link the commit and clearly distinguish static checks from interactive tests.

## Working expectations

Read the current implementation before editing it. Make targeted changes and preserve unrelated functionality. Ask a concise clarifying question when user intent or an implementation choice is genuinely ambiguous. Do not claim behavior is fixed based on static checks alone.
