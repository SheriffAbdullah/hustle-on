# battery-guard Specification

## Purpose
Automatically pauses a live hold on low battery to avoid draining an unplugged laptop.

Known drift: the original openspec.md said manual re-enable below the threshold is allowed and re-triggers on the next poll. Actual: "Keep awake" menu items are still allowed (and re-trip on the next tick), but `Resume hold` is refused with a notification while on battery at or below the threshold.

## Requirements

### Requirement: Power status polling
The system SHALL read AC/battery state via `GetSystemPowerStatus` (ctypes). Unknown values SHALL be reported as unknown (None), never guessed; battery percent above 100 SHALL be treated as unknown.

#### Scenario: Unknown status
- **WHEN** the API call fails or percent is 255
- **THEN** the guard does not trigger

### Requirement: Auto-pause rule
When the guard is enabled, the mode is not `off`, the machine is definitely on battery, and percent is at or below the threshold, the system SHALL snapshot the current mode and deadline, switch to `off`, set `battery_paused`, and raise a battery-low notification.

#### Scenario: Trip
- **WHEN** a tick sees unplugged at 25% with threshold 30%
- **THEN** mode becomes `off`, `battery_paused` is true, and a `battery_pause` event is emitted

#### Scenario: On AC
- **WHEN** the machine is plugged in at 5%
- **THEN** the guard does not trigger

### Requirement: Configuration
The guard SHALL default to enabled with a 30% threshold; the tray offers thresholds 10, 15, 20, 30, 40 and 50. Disabling the guard SHALL clear the paused latch.

#### Scenario: Disable while paused
- **WHEN** the user disables the guard while paused
- **THEN** `battery_paused` becomes false

### Requirement: Resume after pause
`Resume hold` SHALL re-arm the paused mode (timer/until only if the deadline is still in the future, otherwise `on`). It SHALL be refused with a notification while still on battery at or below the threshold.

#### Scenario: Resume refused
- **WHEN** the user clicks Resume at 20% on battery with threshold 30%
- **THEN** a notification explains to plug in and nothing resumes

### Requirement: Live status display
The tooltip SHALL show `AC` or `Batt NN%` when known, and the tray SHALL poll live power status when the menu opens.

#### Scenario: Tooltip
- **WHEN** unplugged at 64%
- **THEN** the tooltip ends with `Batt 64%`
