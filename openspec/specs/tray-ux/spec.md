# tray-ux Specification

## Purpose
System-tray presentation: icons, click behavior, menu, tooltip, notifications, About dialog, single instance (`hustleon_tray.py`).

Known drift: the original spec described `Settings` and a `Check settings` dialog; actual UI has a `Battery guard` submenu and an `About HustleOn...` dialog (which also has `Restore sleep defaults`, absent from the original spec).

## Requirements

### Requirement: State icons
The tray icon SHALL be generated at runtime (no binary assets): gray power glyph for off, green infinity for on, green hourglass for timer, green clock for until, gray pause bars for battery-paused. A red dot SHALL appear on the three live states only.

#### Scenario: Paused
- **WHEN** the battery guard has paused the hold
- **THEN** the icon shows gray pause bars

### Requirement: Click opens menu
Every left or right click on the icon SHALL open the popup menu; there SHALL be no double-click action. The menu, tooltip and icon SHALL be refreshed at the moment of opening.

#### Scenario: Left click
- **WHEN** the user left-clicks the icon
- **THEN** the menu opens and no mode toggles

### Requirement: Menu contents
The menu SHALL contain, in order: optional lid warning and paused/Resume items, `Keep awake indefinitely`, `Keep awake on interval` (30 minutes, 1 hour, 2 hours, 8 hours, Custom...), `Keep awake until expiration date and time` (Lunch 13:00, EOD 18:00, Morning 08:00, Custom...), `Off (keep using the selected power plan)`, `Keep screen on`, `Battery guard` (Enabled, thresholds, status), `About HustleOn...`, `Quit`. The active mode SHALL be checked and remaining time or deadline appended to parent labels.

#### Scenario: Past until preset
- **WHEN** a preset time has already passed today
- **THEN** its label ends with `(tomorrow)`

### Requirement: Tooltip
The tooltip SHALL read `HustleOn · <state> · <power>` where state is Off, Awake indefinitely, `<time> left`, `Until <ddd HH:MM>`, or Paused.

#### Scenario: Off on AC
- **WHEN** mode is off and plugged in
- **THEN** tooltip is `HustleOn · Off · AC` (with percent when known)

### Requirement: Alerts only
Notifications SHALL be raised only for failures: battery auto-pause, Windows refusing the hold, bad `until` input, missing tkinter, repeated internal errors, and lid-not-protected at launch. Mode changes, timer expiry and guard toggles SHALL be silent.

#### Scenario: Timer expiry
- **WHEN** a timer expires
- **THEN** no notification is shown and the icon shows Off

### Requirement: About dialog
`About HustleOn...` SHALL show version, status, hold state, display setting, battery guard, sleep/display/lid summary, and buttons `Fix lid settings (admin)...`, `Restore sleep defaults`, `OK`. Only one dialog SHALL be open at a time.

#### Scenario: Second open
- **WHEN** About is already open
- **THEN** choosing it again does nothing

### Requirement: Single instance
Launching a second instance SHALL show a message box "already running" and exit, using a named global mutex.

#### Scenario: Second launch
- **WHEN** the app is already running
- **THEN** the new process shows a notice and exits with code 0

### Requirement: Quit
Quit SHALL release the hold, persist settings, and remove the tray icon.

#### Scenario: Quit while on
- **WHEN** the user clicks Quit
- **THEN** the hold is released and the icon stops
