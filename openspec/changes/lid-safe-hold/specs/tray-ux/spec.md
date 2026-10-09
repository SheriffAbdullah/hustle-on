# Spec Delta

## MODIFIED Requirements

### Requirement: Menu contents
The menu SHALL contain, in order: optional lid-status item and paused/Resume items, `Keep awake indefinitely`, `Keep awake on interval` (30 minutes, 1 hour, 2 hours, 8 hours, Custom...), `Keep awake until expiration date and time` (Lunch 13:00, EOD 18:00, Morning 08:00, Custom...), `Off (keep using the selected power plan)`, `Keep screen on`, `Battery guard` (Enabled, thresholds, status), `Start with Windows`, `About HustleOn...`, `Quit`. The active mode SHALL be checked and remaining time or deadline appended to parent labels. The lid-status item SHALL appear only when status is `unprotected` during a hold (warning) or `unknown` (link to `ms-settings:powersleep`).

#### Scenario: Past until preset
- **WHEN** a preset time has already passed today
- **THEN** its label ends with `(tomorrow)`

#### Scenario: Unknown lid status
- **WHEN** the lid status is unknown
- **THEN** the menu shows an item that opens `ms-settings:powersleep` and no warning alert is raised at launch

### Requirement: Alerts only
Notifications SHALL be raised only for failures: battery auto-pause, Windows refusing the hold, bad `until` input, missing tkinter, repeated internal errors, failed restore of power settings, and lid `unprotected` while a hold is live. Mode changes, timer expiry and guard toggles SHALL be silent.

#### Scenario: Timer expiry
- **WHEN** a timer expires
- **THEN** no notification is shown and the icon shows Off

### Requirement: About dialog
`About HustleOn...` SHALL show version, status, hold state, display setting, battery guard, sleep/display/lid summary, and buttons `Restore sleep defaults`, `OK`, plus a one-time `Unlock lid setting (admin)...` button only when the lid setting is hidden. Dialogs SHALL run on one dedicated UI thread and only one About dialog SHALL be open at a time.

#### Scenario: Second open
- **WHEN** About is already open
- **THEN** choosing it again does nothing

### Requirement: Single instance
Launching a second instance SHALL show a message box "already running" and exit, using a named `Local\` mutex whose error state is read with last-error tracking. An `--enforce-only` launch SHALL be handled before this check.

#### Scenario: Second launch
- **WHEN** the app is already running
- **THEN** the new process shows a notice and exits with code 0

### Requirement: Quit
Quit SHALL release the hold, restore power settings, persist settings with the resumable mode preserved, and remove the tray icon.

#### Scenario: Quit while on
- **WHEN** the user clicks Quit
- **THEN** the hold is released, settings are restored, the icon stops, and the next launch resumes `on`

## ADDED Requirements

### Requirement: Start with Windows
The menu SHALL offer a checked toggle `Start with Windows` that adds or removes a per-user (HKCU Run) startup entry for the app. The checked state SHALL reflect the registry when the menu opens.

#### Scenario: Enable autostart
- **WHEN** the user turns on `Start with Windows`
- **THEN** the HKCU Run entry points at the current exe or script and the item is checked

### Requirement: First-run setup
On first launch (`first_run_done` false) the app SHALL show a one-time setup dialog with a checklist: lid status with a link to `ms-settings:powersleep`, battery guard on, Start with Windows, and an optional admin unlock only if needed. Completing or dismissing it SHALL set `first_run_done`.

#### Scenario: First launch
- **WHEN** the app starts with no saved settings
- **THEN** the setup dialog appears once and not on the next launch

### Requirement: Diagnostic log
The app SHALL write a rotating log to `%APPDATA%\hustle-on\log.txt` recording hold start/end, apply/restore results, guard trips, crash recovery and errors, without raising notifications.

#### Scenario: Hold lifecycle logged
- **WHEN** a hold starts and ends
- **THEN** log.txt contains both events with timestamps

### Requirement: Compatible click handling
The left-click-opens-menu behavior SHALL be installed only if the pystray internals it depends on are present; otherwise the app SHALL fall back to the library default menu behavior.

#### Scenario: Pystray internals missing
- **WHEN** the installed pystray lacks the expected internals
- **THEN** the app starts and the menu opens via the default right-click
