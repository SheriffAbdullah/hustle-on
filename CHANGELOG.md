# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- The windowed `hustle-on.exe` now honours `--version`, `--check`, `--enforce-only` and every other
  CLI flag instead of launching the tray; output is attached to the parent console.

### Added
- Windows VERSIONINFO resource (FileVersion, ProductName, Copyright) generated from `pyproject.toml`.

## [1.2.0]

### Added
- Shape-coded tray icons (green disc + white ring = awake, amber + bars = paused, gray power = off),
  supersampled and hand-tuned at 16/20/24/32 (+48/64), chosen from the real tray icon size.
- Per-Monitor V2 DPI awareness and Tk scaling from the actual DPI; Windows 11 style dialogs in
  Segoe UI Variable, dark mode for dialogs, title bars and the tray menu.
- Clickable lid warning, paused line with Resume, tooltip with Lid OK / Lid will sleep.
- Custom timer and until prompts with inline validation (24-hour HH:MM).
- MIT `LICENSE`, `pyproject.toml` as the single version source, release workflow, README rewrite,
  screenshots under `docs/`.
- Apply-while-live: power settings change only while keep-awake is on and are restored on every end.

### Changed
- Plainer menu and notification wording ("Keep awake", "Pause on low battery"); no "hold" jargon.
- The red live dot is gone.

## [1.1.0]
- Earlier releases (tray app, battery guard, timers).
