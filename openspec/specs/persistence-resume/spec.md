# persistence-resume Specification

## Purpose
Persisting settings to `settings.json` and resuming on launch.

Known drift: the original spec said resume restores `on`/`timer`/`until` after restart. Actual: Quit and battery auto-pause call `persist()` after deactivating, so they save mode `off`. Resume therefore only restores a live mode after an unclean exit (crash, logoff, power loss).

## Requirements

### Requirement: Settings location
Settings SHALL be stored in `settings.json` next to the exe (frozen) or the script, falling back to `%APPDATA%\hustle-on\` when that directory is not writable.

#### Scenario: Read-only install dir
- **WHEN** the app directory is not writable
- **THEN** settings are stored under `%APPDATA%\hustle-on`

### Requirement: Persisted fields
Every mode or option change SHALL persist `mode`, `timer_minutes`, `until_iso`, `screen_on`, `battery_guard` and `battery_threshold`.

#### Scenario: Change threshold
- **WHEN** the user picks 20%
- **THEN** `battery_threshold` is saved as 20

### Requirement: Defaults on bad data
Missing or corrupt settings SHALL yield defaults: mode `off`, screen on, guard on, threshold 30, timer 60. An unknown mode value SHALL become `off`.

#### Scenario: Corrupt file
- **WHEN** settings.json is invalid JSON
- **THEN** defaults are used

### Requirement: Resume on launch
On launch, saved `on` SHALL resume `on`. Saved `timer`/`until` with a future deadline SHALL resume with the remaining time; an expired deadline or `off` SHALL start `off`.

#### Scenario: Future deadline
- **WHEN** saved mode is timer with a deadline 20 minutes ahead
- **THEN** the hold resumes and expires at that deadline

#### Scenario: Expired while away
- **WHEN** the saved deadline is in the past
- **THEN** the app starts off

### Requirement: Time semantics
Deadlines SHALL be naive local-time ISO strings; a timezone change across a restart reinterprets a resumed deadline.

#### Scenario: Zone change
- **WHEN** the system timezone changes before relaunch
- **THEN** the stored wall-clock deadline is used as-is
