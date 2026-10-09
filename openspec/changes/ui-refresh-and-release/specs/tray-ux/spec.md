## MODIFIED Requirements

### Requirement: State icons
The tray icon SHALL be generated at runtime (no binary assets) and SHALL NOT rely on colour alone. Off SHALL be a gray power glyph. Live states (indefinite, timer, until) SHALL be a green disc with the glyph and a white outer ring. Battery-paused SHALL be an amber disc with dark pause bars. Separate hand-tuned drawings SHALL exist for 16, 20, 24 and 32px, rendered supersampled with LANCZOS, and SHALL be legible on light (#f3f3f3) and dark taskbars. No red dot SHALL be drawn.

#### Scenario: Paused
- **WHEN** low-battery protection has paused keep-awake
- **THEN** the icon shows an amber disc with dark pause bars

#### Scenario: Live distinguishable without colour
- **WHEN** keep-awake is active
- **THEN** the icon has a white outer ring that the off icon lacks

#### Scenario: Gallery check
- **WHEN** `icons/render_gallery.py` runs
- **THEN** all sizes render on both light and dark mock taskbars

### Requirement: Menu contents
The menu SHALL contain, in order: lid warning action and paused line with Resume (when applicable), `Keep awake`, `Keep awake for...` (30 minutes, 1 hour, 2 hours, 8 hours, Custom...), `Keep awake until...` (Lunch 13:00, EOD 18:00, Morning 08:00, Custom...), `Off`, `Keep screen on`, `Pause on low battery` (Enabled, `Pause below N%` thresholds, status), `About HustleOn...`, `Quit`. The active mode SHALL be checked and remaining time or deadline appended to parent labels. When the lid will still sleep the PC, the first item SHALL be an enabled clickable action `⚠ Lid close will still sleep this PC — fix…` that starts the lid fix. When paused, a line `Paused: battery 28%. Plug in to resume.` SHALL appear with a `Resume` item.

#### Scenario: Past until preset
- **WHEN** a preset time has already passed today
- **THEN** its label ends with `(tomorrow)`

#### Scenario: Lid warning clickable
- **WHEN** the lid is not protected and the user clicks the warning item
- **THEN** the lid fix flow starts

#### Scenario: Paused line
- **WHEN** paused at 28% battery
- **THEN** the menu shows `Paused: battery 28%. Plug in to resume.` and an enabled Resume

### Requirement: Tooltip
The tooltip SHALL read `HustleOn: <state> · <power>` with state `Awake indefinitely`, `Awake for 1h20m`, `Awake until <ddd HH:MM>`, `Paused` or `Off (normal sleep)`, and power such as `On battery 64%` or `Plugged in`, followed by a lid indicator `Lid OK` or `Lid will sleep`.

#### Scenario: Timer on battery
- **WHEN** a timer has 1h20m left on 64% battery
- **THEN** the tooltip is `HustleOn: Awake for 1h20m · On battery 64%` plus the lid indicator

#### Scenario: Off on AC
- **WHEN** mode is off and plugged in
- **THEN** the tooltip reads `HustleOn: Off (normal sleep) · Plugged in` plus the lid indicator

### Requirement: Alerts only
Notifications SHALL be raised only for failures: battery auto-pause, Windows refusing keep-awake, bad `until` input, missing tkinter, repeated internal errors, and lid-not-protected at launch. Titles and bodies SHALL use plain language and SHALL NOT use the word "hold". Mode changes, timer expiry and toggles SHALL be silent.

#### Scenario: Timer expiry
- **WHEN** a timer expires
- **THEN** no notification is shown and the icon shows Off

#### Scenario: Wording
- **WHEN** any alert is shown
- **THEN** its text does not contain "hold"

### Requirement: About dialog
`About HustleOn...` SHALL be a ttk dialog using the vista theme, laid out as a key/value grid showing version, status, display setting, low-battery pause, and sleep/display/lid summary, with equal-width buttons `Fix lid close…`, `Reset sleep settings`, `Close` (Return activates Close). It SHALL follow the system dark/light app theme (`AppsUseLightTheme`, title bar via `DwmSetWindowAttribute` attribute 20) and scale with DPI. The tray context menu SHALL also follow dark mode via uxtheme ordinals 135/136, falling back to light if unavailable. Only one dialog SHALL be open at a time.

#### Scenario: Second open
- **WHEN** About is already open
- **THEN** choosing it again does nothing

#### Scenario: Dark mode
- **WHEN** Windows apps use dark theme
- **THEN** the About dialog and context menu render dark

#### Scenario: Default button
- **WHEN** the user presses Return in About
- **THEN** the dialog closes

## ADDED Requirements

### Requirement: Custom time prompts
Custom timer and until entries SHALL use a dialog with inline validation instead of popup errors. The until prompt SHALL state 24-hour format with an example (e.g. 17:30). OK SHALL stay disabled or an inline error SHALL show until input is valid.

#### Scenario: Invalid until
- **WHEN** the user types `25:99`
- **THEN** an inline message explains the 24-hour HH:MM format and the dialog stays open
