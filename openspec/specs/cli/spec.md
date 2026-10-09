# cli Specification

## Purpose
Command-line interface (`hustleon.py` wrapper over `hustleon_core.main`) for scripts and scheduled tasks.

Known drift: a CLI invocation never talks to a running tray instance; it is its own foreground process. The original spec omitted `--interval`, `--enforce-only`, and `--version`.

## Requirements

### Requirement: Flags
The CLI SHALL accept `--on`, `--off`, `--timer MINUTES`, `--until HH:MM`, `--screen-on`, `--screen-off`, `--check`, `--no-enforce`, `--enforce-only`, `--interval SECONDS` (default 60, capped at 60) and `--version`.

#### Scenario: Version
- **WHEN** run with `--version`
- **THEN** it prints the program name and version

### Requirement: Input validation before side effects
The CLI SHALL validate `--timer` (positive) and `--until` (`HH:MM`) before changing any machine config, exiting with code 2 and a message on error.

#### Scenario: Bad timer
- **WHEN** run with `--timer 0`
- **THEN** it exits 2 without running powercfg

### Requirement: Hold loop
Without `--off`, `--check` or `--enforce-only`, the CLI SHALL enforce power settings (unless `--no-enforce`), hold the requested mode (indefinite by default), and print a heartbeat until it expires, the battery guard trips, or Ctrl+C. Ctrl+C SHALL release the hold.

#### Scenario: Timer completes
- **WHEN** run with `--timer 1` and one minute elapses
- **THEN** it prints "Deadline reached" and exits 0

### Requirement: Off and check
`--off` SHALL release the hold and exit 0. `--check` SHALL print relevant power settings and exit 0 without modifying anything.

#### Scenario: Check
- **WHEN** run with `--check`
- **THEN** current sleep/lid/display values are printed

### Requirement: Enforce-only
`--enforce-only` SHALL run enforcement, print `[OK]`/`[FAIL]` lines, and exit 0 (used for elevation).

#### Scenario: Failure reporting
- **WHEN** a powercfg call fails
- **THEN** a `[FAIL]` line with detail is printed and exit code is still 0

### Requirement: Windows only
Outside Windows the CLI SHALL print "Windows only." and exit 1 (after `--check` handling).

#### Scenario: Non-Windows
- **WHEN** run on Linux without `--check`
- **THEN** exit code 1
