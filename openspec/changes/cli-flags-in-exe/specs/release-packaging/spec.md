## ADDED Requirements

### Requirement: Executable version resource
The build SHALL generate a Windows VERSIONINFO resource from the `pyproject.toml` version (FileVersion, ProductVersion, ProductName, CompanyName, LegalCopyright) and embed it in `hustle-on.exe`.

#### Scenario: File properties
- **WHEN** the built exe's file properties are read
- **THEN** FileVersion equals the pyproject version and ProductName is HustleOn
