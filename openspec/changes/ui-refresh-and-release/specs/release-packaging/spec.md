## ADDED Requirements

### Requirement: License
The repository SHALL contain an MIT `LICENSE` with holder `Sheriff Abdullah` (GitHub sheriffabdullah).

#### Scenario: License present
- **WHEN** the repo root is listed
- **THEN** `LICENSE` exists with the MIT text and that holder

### Requirement: README content
`README.md` SHALL be concise and contain: shields.io badges (license, platform Windows, Python version, latest release, CI), the tagline `Close the lid. Keep working. Auto-stops before your battery pays for it.`, tray-state screenshots or GIF stored under `docs/` (generated from `icons/render_gallery.py` or captured), a comparison table versus PowerToys Awake, Lidless and ClosedAwake, safety notes (heat, bags), a Modern Standby caveat, and install instructions via GitHub Releases (winget/scoop labelled as future). It SHALL say "Click", not "Tap", and SHALL NOT claim autostart or that `dist/` is in the repo.

#### Scenario: Honest comparison
- **WHEN** a reader views the comparison table
- **THEN** it states PowerToys Awake lacks lid-close and fails on Modern Standby, ClosedAwake is Store-only, and Lidless is closest

#### Scenario: No drift
- **WHEN** README is compared to behavior
- **THEN** no autostart claim and no reference to a committed `dist/` remains

### Requirement: Changelog and version
`CHANGELOG.md` SHALL follow Keep a Changelog. The version SHALL be defined once in `pyproject.toml` and consumed by the app, About dialog and release tag.

#### Scenario: Tag mismatch
- **WHEN** a `v*` tag differs from the pyproject version
- **THEN** CI fails before publishing

### Requirement: CI and release
A GitHub Actions workflow on `windows-latest` SHALL run pytest, build the PyInstaller one-file exe, upload it as an artifact, and on a `v*` tag publish a GitHub Release with the exe attached.

#### Scenario: Tagged release
- **WHEN** tag `v1.2.0` is pushed and tests pass
- **THEN** a release is created with `hustle-on.exe`
