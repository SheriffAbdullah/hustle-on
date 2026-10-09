# Spec Delta

## MODIFIED Requirements

### Requirement: Enforced settings
While a hold is live, the system SHALL set, on the current scheme for both AC and DC: lid close action to Do Nothing, sleep timeout to Never, hibernate timeout to Never, display timeout to Never, then re-activate the scheme. These changes SHALL be applied on every hold start (tray modes and CLI) and SHALL NOT be applied while no hold is live.

#### Scenario: Enforce run
- **WHEN** a hold starts and enforcement runs successfully
- **THEN** each setting reports `= Do Nothing` or `= Never` and the scheme is re-activated

#### Scenario: No hold, no change
- **WHEN** the mode is off
- **THEN** the lid, sleep, hibernate and display settings equal the user's own values

### Requirement: Snapshot before first change
At every hold start the system SHALL re-snapshot the current sleep, hibernate, display and lid values before changing them. It SHALL NOT keep a snapshot from an earlier hold, and SHALL NOT snapshot values it itself enforced (a leftover applied marker is restored first, or its older snapshot kept).

#### Scenario: Second enforcement
- **WHEN** a snapshot from an earlier hold exists
- **THEN** it is discarded and a fresh snapshot is taken

#### Scenario: Second hold
- **WHEN** the user changes their sleep timeout between two holds
- **THEN** the second hold snapshots and later restores the new value

#### Scenario: Stale enforced values
- **WHEN** a hold starts and the current values already equal the enforced values because of a previous crash
- **THEN** the earlier recorded snapshot is kept and the enforced values are not recorded as defaults

### Requirement: Restore defaults
The system SHALL restore the snapshot values for each setting whenever a hold ends (Off, timer or until expiry, battery-guard trip, Quit) and via the explicit `Restore sleep defaults` button. It SHALL skip values that are missing or unreadable, report per-setting results, clear the applied marker on success, and retry once on failure. With no snapshot it SHALL report failure and change nothing.

#### Scenario: Timer expires
- **WHEN** a timer hold expires
- **THEN** lid, sleep, hibernate and display values are restored to the snapshot

#### Scenario: No snapshot
- **WHEN** restore runs and no snapshot exists
- **THEN** it reports nothing to restore

### Requirement: Modern Standby lid handling
If the lid setting is rejected, the system SHALL attempt to unhide it by setting registry `Attributes=2` (needs Administrator) and retry. Powercfg lid changes on the current scheme SHALL be attempted unelevated first; elevation SHALL be requested only for the unhide step, at most once, and only with the user's consent. After enforcement it SHALL read back the lid value and report one of protected, unprotected, or unknown.

#### Scenario: Hidden lid setting
- **WHEN** the lid value cannot be queried
- **THEN** the lid status is `unknown` and the menu offers a link to `ms-settings:powersleep`

#### Scenario: Works without admin
- **WHEN** the lid change succeeds unelevated and reads back Do Nothing
- **THEN** no UAC prompt is shown and the status is `protected`

### Requirement: Elevation on demand
The tray SHALL run as a standard user and elevate via `ShellExecuteW runas` with `--enforce-only` only for the one-time Modern Standby unhide, when the user accepts the offer. A frozen exe SHALL handle `--enforce-only` before the single-instance check. Cancelled or failed elevation SHALL show a message box.

#### Scenario: UAC cancelled
- **WHEN** the user cancels UAC
- **THEN** "Elevation failed or was cancelled." is shown

#### Scenario: Frozen exe elevated launch
- **WHEN** the elevated frozen exe starts with `--enforce-only` while the tray is running
- **THEN** it performs the unhide and exits without the "already running" box

## ADDED Requirements

### Requirement: Crash recovery
While a hold's settings are applied, the system SHALL persist an applied marker with the snapshot. On the next launch, a present marker SHALL cause the snapshot to be restored before any resume logic runs.

#### Scenario: Power loss mid-hold
- **WHEN** the app is killed during a hold and launched again
- **THEN** the original lid/sleep values are restored on startup and the marker is cleared

### Requirement: Lid closed after guard trip
If a hold ends because of a battery-guard trip while the lid is closed, the system SHALL restore the settings and then let the PC sleep or hibernate normally rather than keep running.

#### Scenario: Trip with lid closed
- **WHEN** the guard trips and the lid is closed
- **THEN** settings are restored and the PC enters sleep or hibernate

### Requirement: Thermal protection
When the thermal guard is enabled, the lid is closed, a hold is live and a readable temperature exceeds the threshold, the system SHALL alert and end the hold. If no temperature source is available it SHALL report the feature as unavailable and do nothing.

#### Scenario: Over temperature
- **WHEN** the temperature exceeds the threshold with the lid closed
- **THEN** the hold ends, settings are restored and an alert is shown

## REMOVED Requirements

### Requirement: No automatic revert
**Reason**: Superseded by apply-while-live and restore-on-every-end; leaving the lid on Do Nothing after a hold lets a bagged laptop overheat.
**Migration**: Settings are restored automatically at every hold end; `Restore sleep defaults` remains for manual recovery.
