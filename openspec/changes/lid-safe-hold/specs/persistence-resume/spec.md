# Spec Delta

## MODIFIED Requirements

### Requirement: Settings location
Settings SHALL be stored in `%APPDATA%\hustle-on\settings.json`, written atomically (temp file then replace). An existing next-to-exe `settings.json` SHALL be migrated once. A settings file that cannot be parsed SHALL be renamed to a timestamped `.corrupt` backup and defaults used.

#### Scenario: Read-only install dir
- **WHEN** the app directory is not writable
- **THEN** settings are still stored under `%APPDATA%\hustle-on`

#### Scenario: Atomic write
- **WHEN** settings are saved
- **THEN** a crash during the write leaves either the old or the new complete file

#### Scenario: Corrupt file
- **WHEN** settings.json is invalid JSON
- **THEN** it is renamed to a `.corrupt` backup and defaults are used

### Requirement: Persisted fields
Every mode or option change SHALL persist `mode`, `timer_minutes`, `until_iso`, `screen_on`, `battery_guard`, `battery_threshold`, `last_mode`, `start_with_windows`, `thermal_guard` and `first_run_done`. The applied marker (snapshot of user power values) SHALL be persisted separately while a hold's settings are applied.

#### Scenario: Change threshold
- **WHEN** the user picks 20%
- **THEN** `battery_threshold` is saved as 20

### Requirement: Defaults on bad data
Missing or corrupt settings SHALL yield defaults: mode `off`, screen on, guard on, threshold 30, timer 60, `first_run_done` false. An unknown mode value SHALL become `off`.

#### Scenario: Corrupt file
- **WHEN** settings.json is invalid JSON
- **THEN** defaults are used

#### Scenario: Missing file
- **WHEN** settings.json does not exist
- **THEN** defaults are used and `first_run_done` is false

### Requirement: Resume on launch
On launch, any applied marker SHALL be restored first. Then the last mode SHALL be resumed: saved `on` resumes `on`; `timer`/`until` with a future deadline resume with the remaining time; an expired deadline or `off` starts `off`. Quit SHALL preserve the resumable mode; an explicit Off SHALL clear it.

#### Scenario: Future deadline
- **WHEN** saved mode is timer with a deadline 20 minutes ahead
- **THEN** the hold resumes and expires at that deadline

#### Scenario: Expired while away
- **WHEN** the saved deadline is in the past
- **THEN** the app starts off

#### Scenario: Quit then relaunch
- **WHEN** the user quits while mode is `on` and relaunches
- **THEN** the mode resumes as `on`

#### Scenario: Explicit Off then relaunch
- **WHEN** the user chose Off before quitting
- **THEN** the app starts off
