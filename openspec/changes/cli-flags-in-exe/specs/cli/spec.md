## ADDED Requirements

### Requirement: CLI flags in the windowed exe
When the packaged `hustle-on.exe` is started with any command-line argument (for example `--version`, `--check`, `--enforce-only`), it SHALL run the core CLI and exit with its code, before taking the single-instance mutex and before creating any Tk or tray object. It SHALL attach to the parent console so output is visible, and SHALL continue silently if no parent console exists.

#### Scenario: Version from a console
- **WHEN** `hustle-on.exe --version` is run from a terminal
- **THEN** the version is printed there and no tray icon is created

#### Scenario: No parent console
- **WHEN** the exe is started with `--check` and no console is attached
- **THEN** it exits normally without error and without starting the tray
