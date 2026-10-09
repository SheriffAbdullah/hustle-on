# Spec Delta

## MODIFIED Requirements

### Requirement: Flags
The CLI SHALL accept `--on`, `--off`, `--timer MINUTES`, `--until HH:MM`, `--screen-on`, `--screen-off`, `--check`, `--no-enforce`, `--enforce-only` and `--version`. The `--interval` flag SHALL NOT exist.

#### Scenario: Version
- **WHEN** run with `--version`
- **THEN** it prints the program name and version

#### Scenario: Removed flag
- **WHEN** run with `--interval 30`
- **THEN** it exits 2 with an unrecognized-argument error

### Requirement: Hold loop
Without `--off`, `--check` or `--enforce-only`, the CLI SHALL snapshot and apply power settings (unless `--no-enforce`), hold the requested mode (indefinite by default), and print a heartbeat every 30 seconds until it expires, the battery guard trips, or Ctrl+C. On every exit path, including Ctrl+C, it SHALL release the hold and restore the power settings.

#### Scenario: Timer completes
- **WHEN** run with `--timer 1` and one minute elapses
- **THEN** it prints "Deadline reached", restores power settings and exits 0

#### Scenario: Ctrl+C restores
- **WHEN** the user presses Ctrl+C during a hold
- **THEN** the hold is released and the original power settings are restored

### Requirement: Enforce-only
`--enforce-only` SHALL perform the elevated one-time Modern Standby unhide, print `[OK]`/`[FAIL]` lines, and exit 0 (used for elevation). In the frozen exe it SHALL run before the single-instance check.

#### Scenario: Failure reporting
- **WHEN** a powercfg or registry call fails
- **THEN** a `[FAIL]` line with detail is printed and exit code is still 0
