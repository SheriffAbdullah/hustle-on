## 1. Icons
- [ ] 1.1 Redraw state icons: live = green disc + white ring, paused = amber disc + dark bars, remove red dot
- [ ] 1.2 Hand-tune 16/20/24/32px variants; supersample with LANCZOS
- [ ] 1.3 Extend `icons/render_gallery.py` with light (#f3f3f3) mock; review all sizes on both

## 2. Menu, tooltip, alerts
- [ ] 2.1 Rename menu items and battery labels per spec
- [ ] 2.2 Make lid warning an enabled action; add paused line and Resume
- [ ] 2.3 New tooltip format with Lid OK / Lid will sleep
- [ ] 2.4 Reword notifications (no "hold"); drop timer-vs-until glyph distinction

## 3. Dialogs and theming
- [ ] 3.1 Dark-mode helper (AppsUseLightTheme, DwmSetWindowAttribute 20, DPI scaling)
- [ ] 3.2 Rebuild About as ttk/vista key-value grid with equal-width buttons, Return default
  - Note: partially implemented early: flash/icon/close fixes
- [ ] 3.3 Dark context menu via uxtheme 135/136 with safe fallback
- [ ] 3.4 Custom timer/until prompt with inline validation (24-hour, e.g. 17:30)

## 4. Release and docs
- [ ] 4.1 Add MIT `LICENSE`
- [ ] 4.2 Add `pyproject.toml` as single version source; wire app and About to it
- [ ] 4.3 Add `CHANGELOG.md`
- [ ] 4.4 Generate/capture screenshots into `docs/`
- [ ] 4.5 Rewrite README (badges, tagline, table, safety, Modern Standby, install); fix drift, "Click"
- [ ] 4.6 Add minimal pytest smoke tests
- [ ] 4.7 Add `.github/workflows/release.yml` (pytest, PyInstaller, artifact, tag release, version check)
- [ ] 4.8 Update `openspec.md` drift; verify on Windows 11 light and dark
