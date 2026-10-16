## Why

The PyInstaller `--noconsole` exe ignored `--version` and `--check` and launched the tray, and had no stdout to print to. It also lacked a VERSIONINFO resource.

## What Changes

- `hustleon_tray.main` and the module entry delegate any command-line args to `core.main` before the single-instance mutex and any Tk/pystray object; the exe attaches to the parent console for output.
- The build generates `version_info.txt` from `pyproject.toml` and embeds it.

## Impact

- Affected specs: cli, release-packaging
