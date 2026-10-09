## Why

UI/UX and release audits found: the red live-dot is colour-only (fails deuteranopia) and hides the infinity glyph at 16px; menu wording is jargon-heavy ("hold", "Battery guard"); the lid warning is a dead line; the About dialog is unthemed and not dark-mode or DPI aware; and the repo has no LICENSE, CHANGELOG, CI, badges or screenshots. README and spec also drift from reality (autostart claim, `dist/` not in the repo, "Tap" wording).

## What Changes

- Icons: shape cue instead of red dot (white outer ring on green disc = live; amber disc with dark bars = paused), hand-tuned 16/20/24/32px, supersampled LANCZOS, verified on light (#f3f3f3) and dark taskbars via `icons/render_gallery.py`.
- Menu/tooltip/notification wording rewrite ("Keep awake", "Keep awake for...", "Keep awake until...", "Off", "Pause on low battery"); clickable lid-fix action; clearer paused line with Resume; Lid OK / Lid will sleep indicator.
- About dialog: ttk vista theme, key/value grid, equal-width buttons, dark-mode and DPI aware; dark-mode context menu; custom timer/until prompts with inline validation.
- Release: MIT LICENSE, concise README with badges/tagline/screenshots/honesty table/safety notes, CHANGELOG, single-source version in pyproject, GitHub Actions on windows-latest (pytest, PyInstaller, artifact, release on tag).
- Fix README/spec drift. Docs say "Click" not "Tap".

## Capabilities

### New Capabilities
- `release-packaging`: license, README/docs content, versioning, changelog, CI build and release.

### Modified Capabilities
- `tray-ux`: state icons, menu contents, tooltip, alerts wording, About dialog.

## Impact

`hustleon_tray.py`, `icons/render_gallery.py`, `README.md`, new `LICENSE`, `CHANGELOG.md`, `pyproject.toml`, `.github/workflows/`, `docs/`. Core/power logic is out of scope (separate change `lid-safe-hold`); coordinate on menu strings for lid/pause state. No autostart or service added. Out of scope: winget/scoop publishing (documented as future).
