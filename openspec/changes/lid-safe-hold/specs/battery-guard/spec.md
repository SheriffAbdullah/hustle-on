# Spec Delta

## MODIFIED Requirements

### Requirement: Power status polling
The system SHALL read AC/battery state via `GetSystemPowerStatus` (ctypes) with the battery percent read as an unsigned byte. Unknown values SHALL be reported as unknown (None), never guessed; battery percent above 100 SHALL be treated as unknown.

#### Scenario: Unknown status
- **WHEN** the API call fails or percent is 255
- **THEN** the guard does not trigger

#### Scenario: Percent 255 is unsigned
- **WHEN** the API reports 255
- **THEN** the percent is unknown rather than negative

### Requirement: Auto-pause rule
When the guard is enabled, the mode is not `off`, the machine is definitely on battery, and percent is at or below the threshold, the system SHALL snapshot the current mode and deadline, switch to `off`, restore the lid and sleep settings, set `battery_paused`, and raise a battery-low notification.

#### Scenario: Trip
- **WHEN** a tick sees unplugged at 25% with threshold 30%
- **THEN** mode becomes `off`, settings are restored, `battery_paused` is true, and a `battery_pause` event is emitted

#### Scenario: On AC
- **WHEN** the machine is plugged in at 5%
- **THEN** the guard does not trigger

### Requirement: Resume after pause
`Resume hold` SHALL re-arm the paused mode: `on` re-arms `on`; timer/until re-arm for the remaining time only if the deadline is still in the future, otherwise the mode stays `off`. It SHALL re-snapshot and re-apply power settings, and SHALL be refused with a notification while still on battery at or below the threshold.

#### Scenario: Resume refused
- **WHEN** the user clicks Resume at 20% on battery with threshold 30%
- **THEN** a notification explains to plug in and nothing resumes

#### Scenario: Timer resumes with remaining time
- **WHEN** a 60-minute timer is paused with 20 minutes left and resumed
- **THEN** the hold expires after the remaining 20 minutes

#### Scenario: Expired pause
- **WHEN** the paused deadline has passed before Resume
- **THEN** the mode stays off and does not become indefinite
