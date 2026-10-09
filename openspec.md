# hustle-on specs moved

The specification now lives in `openspec/` (OpenSpec, spec-driven development):

- Current behavior: `openspec/specs/<capability>/spec.md`
  (awake-modes, battery-guard, tray-ux, power-enforcement, persistence-resume, cli)
- Project context and conventions: `openspec/config.yaml`
- Proposed changes: `openspec/changes/`

Change the product by proposing a change (`/opsx:propose <idea>` in Claude Code), not by editing this file.

Power-settings behavior (apply while a hold is live, restore on every end, crash recovery) is specified by
the change `openspec/changes/lid-safe-hold/` and described for users in `README.md`.

UI and release behavior (shape-coded DPI-crisp icons, menu/tooltip/alert wording, themed dialogs, validated prompts,
LICENSE, CHANGELOG, `pyproject.toml` version source, CI/release workflow) is specified by
`openspec/changes/ui-refresh-and-release/`. "Start with Windows" is an optional, off-by-default menu toggle.
