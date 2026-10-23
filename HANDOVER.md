# Savant GUI / Editor Handover

**Prepared:** 2026-10-22  
**Repository:** [MattTheBanana/savant](https://github.com/MattTheBanana/savant)  
**Working branch:** `gui-progress-import-confirm`  
**Branch HEAD when prepared:** `7f1d40f43f9a46f419bc217573371f135917d8b4` — “Center LRC auto-follow within the lyric panel”  
**Status:** In progress; changes have not yet been fully validated. No PR has been opened for this branch.

## Repository and pull-request status

- **PR #8** — “Add GUI CLI generator and improve editor workflow” — merged into `main`.
- **PR #9** — “Shorten README, split docs into guides, and title-case menus” — open from `docs/short-readme-guides` into `main`. Keep this documentation work separate from the editor feature branch.
- **`gui-progress-import-confirm`** — contains the ongoing UI/editor and Generate workflow work. Continue here; do not push this work directly to `main`.
- Main files involved: `webui/index.html` and `lyrics_editor.py`.

## Overall goal

Finish the editor and Generate workflow requests collected in the conversation, test them, then open a pull request against `main`. Do not describe the features as complete until they have been validated in the actual GUI and the code checks pass.

## Requested behavior

### LRC / TTML editing and playback

- LRC and TTML must follow the same active lyric line during playback and use the same underlying timing state.
- Auto-follow should center the active line within its own scrollable editor panel when practical. At the beginning/end, clamp scrolling so the first/last line remains visible; do not scroll the whole page.
- Apply the same behavior to both LRC and TTML panels.
- Deleting a word at the start or end of a line must not recenter or unexpectedly change the timeline's visible time range.
- Deleting a TTML line must be available from a toolbar control and the right-click/context menu, and must not switch the editor out of word-timing mode.
- In the TTML inspector, show the line number and seconds on one row, with seconds right-aligned; put the line preview underneath, centered with horizontal margins and wrapping.
- Remove the redundant “Waveform ready · shown per lyric line” status text.
- Remove the “Lyric timing grid / Edit line starts and lyrics. When word timing exists, changes to a line’s word count create starter cues for further editing.” heading/instruction from above the LRC grid.
- Keep editor height within the viewport. Scrolling should happen inside the LRC/TTML panels, not the whole page.
- In the preview tab, make the rounded corners match the vertically rotated layout: curves at the top-right and bottom-right.

### Editor action bar and layout preferences

- Put the LRC/TTML switcher at the top-left of the editor area.
- Remove Import Audio and Import Lyrics from the top of the editor and put them on the action bar before the export/action buttons.
- Arrange the action bar from left to right: +, −, Fit Lines at the far left; LRC/TTML toggles; Import Audio and Import Lyrics; then the remaining action buttons, grouped with sensible gaps/dividers; LRC Controls dropdown at the far right.
- Add a saved preference to bias the action bar alignment left, center, or right.
- Default the word editor/inspector to the right of the TTML editor, with a saved preference for a bottom/stacked layout.

### Generate workflow

- Provide basic output location choices: lyrics directory, audio directory, or default run folder. Output filename defaults to the input TXT stem, with editable output folder/name controls.
- When enabled, automatically import generated audio and TTML into Edit after generation. When disabled, show an “Import Output to Edit” button next to Run; keep it disabled until output is ready.
- Display progress as segmented steps: total percentage on the left and the current step label above the active segment. The active step/segment should visibly move as progress advances.
- After a successful run, prevent rerunning until the configuration changes; show and clear finished feedback appropriately.
- If overwrite confirmation is enabled, ask before overwriting existing output.
- Remove the redundant second WhisperX refinement toggle and its `genRefine` / `genRefineWindow` UI/config. A disabled checkbox must not continue to appear checked.

## Changes that have been attempted

Prior work on this branch has attempted changes in `webui/index.html` and `lyrics_editor.py`, including:
- segmented generation progress UI and step labeling;
- output directory/name fields and a local folder chooser endpoint;
- automatic import preference plus a manual “Import Output to Edit” action;
- overwrite confirmation and run-success button state;
- artifact loading for generated audio/TTML;
- removal of the second refinement toggle/config;
- TTML line deletion controls and context-menu action;
- preview-tab corner styling;
- editor/action-bar and settings/layout changes;
- a latest commit specifically targeting centered LRC auto-follow.

**These are implementation attempts, not a verified feature list.** Re-read the current branch files and inspect the latest diff before extending or relying on any of this work.

## Known risks to inspect before calling this done

1. **Auto-follow consistency:** `updateLiveHighlight` is the known entry point in `webui/index.html`. Inspect it and the render functions for both LRC and TTML. Avoid `scrollIntoView()` if it moves the page; calculate scroll position relative to the panel and clamp to valid bounds.
2. **Timeline viewport preservation:** inspect `deleteWordCues`, `rerenderWordTimelinePreservingView`, and the relevant time-window helpers. Capture/restore the visible range when deleting the first/last word cue.
3. **HTML/JS integrity:** the HTML file is large and was edited repeatedly. Check for duplicate IDs, stale element references after removing controls, event handlers attached to missing elements, inconsistent saved-preference key names, and JS syntax errors.
4. **Python/API integrity:** inspect imports and helpers in `lyrics_editor.py` before trusting new routes. In particular verify whether `mimetypes` is imported and whether any referenced name such as `_safe_name` actually exists.
5. **Artifact contract:** ensure the run snapshot/artifact metadata uses the keys expected by the import function; confirm the local artifact endpoint URL and route registration match. Verify `input-audio` is available when appropriate.
6. **Folder picker:** the proposed picker uses Tkinter; verify it works in the app’s supported launch environment and fails gracefully if there is no desktop display.
7. **Output naming:** test extensions, paths containing spaces/unicode, empty values, and overwrite-confirmation logic. Ensure output selection does not accidentally change the source file.
8. **TTML deletion:** confirm deletion mutates the intended line, refreshes both views correctly, and preserves word-timing mode.

## Suggested next steps

1. Re-fetch current `webui/index.html` and `lyrics_editor.py` from `gui-progress-import-confirm`; inspect the latest commit and diff against `main`.
2. Finish LRC/TTML synchronized active-line highlighting and panel-local center-follow, including first/last line cases and playback seeking.
3. Fix timeline-view preservation for deleting first/last word cues.
4. Review the action-bar layout and both saved layout preferences at narrow and wide viewport sizes.
5. Trace Generate end-to-end: choose output destination/name → run → segmented progress → ready state → auto-import or manual import → overwrite confirmation.
6. Validate removal of the second refinement toggle in both UI and run/config payloads.
7. Run a JS syntax parse on every inline script and check IDs/selectors. Run Python syntax compilation and the project’s available tests. Then perform manual GUI smoke tests with an audio file, LRC, TTML, and a generated output.
8. Fix any failures and re-run the checks. Only then open a PR from `gui-progress-import-confirm` to `main`, summarizing behavior and test results.

## Minimum manual test checklist

- [ ] Play audio and seek across several lines: LRC and TTML highlight the same active line.
- [ ] Active line centers in both panels; first/last line behavior is clamped; page does not scroll.
- [ ] Delete first and last word cues; visible timeline range stays put.
- [ ] Delete a TTML line from the toolbar and context menu while in word mode.
- [ ] Confirm editor height fits the viewport and each lyric panel scrolls independently.
- [ ] Verify action-bar order, alignment preference, and right/stacked inspector preference survive reload.
- [ ] Generate with each output-folder choice and with default/custom names.
- [ ] Verify progress segment/label advances and total percentage is shown.
- [ ] Confirm auto-import and manual-import flows work; manual import stays disabled until ready.
- [ ] Confirm overwrite prompt and successful-run lockout/config-change reset.
- [ ] Confirm the removed refinement toggle no longer appears or leaks into config.
- [ ] Run code checks and inspect console/server logs for errors.

## Handover principle

Treat anything not covered by a passing check as unfinished. Keep the README/docs PR independent, and do not merge this feature branch until the editor synchronization, Generate workflow, and regression checks are complete.
