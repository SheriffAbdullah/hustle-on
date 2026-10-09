# awake-modes Specification

## Purpose
Defines the four mutually exclusive awake modes and the execution-state hold they drive (`hustleon_core.Engine`).

Known drift: none for this capability.

## Requirements

### Requirement: Exactly one mode is active
The engine SHALL be in exactly one of `off`, `on`, `timer`, or `until` at any time, defaulting to `off`.

#### Scenario: Default state
- **WHEN** the engine is created
- **THEN** the mode is `off` and no deadline is set

### Requirement: Execution-state hold
While the mode is not `off`, the system SHALL call `SetThreadExecutionState` with `ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED`, adding `ES_DISPLAY_REQUIRED` when "keep screen on" is enabled. Going `off` SHALL release the hold with `ES_CONTINUOUS` only.

#### Scenario: Screen kept on
- **WHEN** a mode is activated with screen_on true
- **THEN** the hold includes `ES_DISPLAY_REQUIRED`

#### Scenario: Screen may sleep
- **WHEN** a mode is activated with screen_on false
- **THEN** the hold omits `ES_DISPLAY_REQUIRED`

#### Scenario: Release
- **WHEN** the engine deactivates
- **THEN** the hold is cleared and the mode is `off`

### Requirement: Heartbeat re-assertion
The hold SHALL be re-asserted on every engine tick (the tray ticks every 30 seconds, and mode actions wake the heartbeat immediately). The system SHALL track whether Windows accepted the request (`api_ok`); a return of 0 with last-error 0 SHALL count as success.

#### Scenario: Windows refuses the request
- **WHEN** the hold call fails while a mode is live
- **THEN** `api_ok` is false and the tray alerts once per hold

### Requirement: Timer mode
In `timer` mode the system SHALL hold for N minutes from activation (default 60) and then automatically switch to `off` without a notification.

#### Scenario: Timer expires
- **WHEN** a tick occurs at or after the deadline
- **THEN** the hold is released, mode becomes `off`, and an `expired` event is returned

### Requirement: Until mode
In `until` mode the system SHALL hold until an absolute local-time deadline. An `HH:MM` that has already passed today SHALL be interpreted as tomorrow. At the deadline the system SHALL switch to `off` silently.

#### Scenario: Time already passed
- **WHEN** the user selects 13:00 at 14:30
- **THEN** the deadline is 13:00 the next day

### Requirement: Indefinite mode
In `on` mode the system SHALL hold until the user turns it off, quits, or the battery guard pauses it.

#### Scenario: No expiry
- **WHEN** mode is `on`
- **THEN** no deadline is set and ticks never expire it
