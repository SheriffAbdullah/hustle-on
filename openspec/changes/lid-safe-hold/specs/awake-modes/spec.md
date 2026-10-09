# Spec Delta

## MODIFIED Requirements

### Requirement: Execution-state hold
While the mode is not `off`, the system SHALL call `SetThreadExecutionState` with `ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED`, adding `ES_DISPLAY_REQUIRED` when "keep screen on" is enabled. All such calls SHALL be made from a single dedicated power thread. Going `off` SHALL release the hold with `ES_CONTINUOUS` only, from that same thread.

#### Scenario: Screen kept on
- **WHEN** a mode is activated with screen_on true
- **THEN** the hold includes `ES_DISPLAY_REQUIRED`

#### Scenario: Screen may sleep
- **WHEN** a mode is activated with screen_on false
- **THEN** the hold omits `ES_DISPLAY_REQUIRED`

#### Scenario: Release
- **WHEN** the engine deactivates
- **THEN** the hold is cleared and the mode is `off`

#### Scenario: Menu action does not drop the hold
- **WHEN** a mode is activated from a menu callback and a heartbeat tick follows
- **THEN** the hold stays asserted because both go through the one power thread

### Requirement: Heartbeat re-assertion
The hold SHALL be re-asserted on every engine tick (the tray ticks every 30 seconds, and mode actions wake the heartbeat immediately). The system SHALL track whether Windows accepted the request (`api_ok`); a return of 0 with last-error 0 SHALL count as success. Engine state changes SHALL be serialized so concurrent menu, heartbeat and startup callers cannot corrupt mode or deadline.

#### Scenario: Windows refuses the request
- **WHEN** the hold call fails while a mode is live
- **THEN** `api_ok` is false and the tray alerts once per hold

### Requirement: Timer mode
In `timer` mode the system SHALL hold for N minutes from activation (default 60) and then automatically switch to `off`, restoring power settings, without a notification. A timer resumed after a pause or restart SHALL run for its remaining time, not the full N minutes.

#### Scenario: Timer expires
- **WHEN** a tick occurs at or after the deadline
- **THEN** the hold is released, power settings are restored, mode becomes `off`, and an `expired` event is returned

#### Scenario: Resume keeps the deadline
- **WHEN** a timer with 20 minutes left is resumed
- **THEN** it expires 20 minutes later
