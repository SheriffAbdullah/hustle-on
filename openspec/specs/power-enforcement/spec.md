# power-enforcement Specification

## Purpose
Machine-level powercfg changes (lid, sleep, hibernate, display) so a held machine survives lid close, plus snapshot/restore and read-back.

Known drift: the CLI `--on`, `--timer`, `--until` and bare run enforce unless `--no-enforce`, while `--off`, `--check`, and the tray's mode actions do NOT enforce; the tray enforces only via the About dialog button. A dead no-op branch exists in `main()` around enforcement selection (no behavioral effect).

## Requirements

### Requirement: Enforced settings
Enforcement SHALL set, on the current scheme for both AC and DC: lid close action to Do Nothing, sleep timeout to Never, hibernate timeout to Never, display timeout to Never, then re-activate the scheme.

#### Scenario: Enforce run
- **WHEN** enforcement runs successfully
- **THEN** each setting reports `= Do Nothing` or `= Never` and the scheme is re-activated

### Requirement: Snapshot before first change
On the first enforcement the system SHALL save the current sleep, hibernate, display and lid values to `defaults_backup.json` next to settings. An existing snapshot SHALL NOT be overwritten.

#### Scenario: Second enforcement
- **WHEN** a snapshot already exists
- **THEN** it is left unchanged

### Requirement: Restore defaults
`restore_power_defaults` SHALL write the snapshot values back for each setting, skip values that are missing or unreadable, and report per-setting results. With no snapshot it SHALL report failure and change nothing.

#### Scenario: No snapshot
- **WHEN** restore runs and no snapshot exists
- **THEN** it reports nothing to restore

### Requirement: Modern Standby lid handling
If the lid setting is rejected, the system SHALL attempt to unhide it by setting registry `Attributes=2` (needs Administrator) and retry. After enforcement it SHALL read back the lid value and report verified, not verifiable (hidden), or mismatch.

#### Scenario: Hidden lid setting
- **WHEN** the lid value cannot be queried
- **THEN** the result says it is not verifiable and the About dialog says to set it in Windows Settings

### Requirement: Elevation on demand
The tray SHALL run as a standard user and elevate via `ShellExecuteW runas` with `--enforce-only` when the user clicks `Fix lid settings (admin)...`. Cancelled or failed elevation SHALL show a message box.

#### Scenario: UAC cancelled
- **WHEN** the user cancels UAC
- **THEN** "Elevation failed or was cancelled." is shown

### Requirement: No automatic revert
Expiry, going off, and quit SHALL NOT revert powercfg changes; only the Restore action does.

#### Scenario: Quit after enforce
- **WHEN** the app quits
- **THEN** lid/sleep/display settings remain as enforced
