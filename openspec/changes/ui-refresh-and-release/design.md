## Context
Tray icons are generated at runtime by Pillow; the menu is rebuilt live at open. `lid-safe-hold` changes core lid/pause semantics concurrently; this change only consumes its state (lid ok / will sleep, paused) and does not alter engine behavior.

## Goals / Non-Goals
- Goals: colour-independent state cues, legible 16px icon, plain-language wording, accessible themed dialogs, reproducible tagged releases.
- Non-Goals: engine changes, autostart, installer/winget/scoop, code signing.

## Decisions
- **Icon cue by shape**: live = green disc + white outer ring; paused = amber disc + dark bars; off = gray power glyph. Separate hand-tuned drawings at 16/20/24/32, rendered at 4x and downsampled with LANCZOS. The ring survives deuteranopia and leaves the glyph unobstructed. Timer and until share the live icon; remaining time lives in tooltip/menu (progress cue deferred).
- **Verification**: `icons/render_gallery.py` gains a light (#f3f3f3) mock beside dark; screenshots committed under `docs/`.
- **Dark mode**: read `AppsUseLightTheme` from HKCU; call `DwmSetWindowAttribute(hwnd, 20, ...)` for title bars; context menu via uxtheme ordinals 135 (SetPreferredAppMode) and 136 (FlushMenuThemes), in try/except so failure falls back to light.
- **DPI**: per-monitor awareness via manifest or `SetProcessDpiAwareness`; Tk scaling from `GetDpiForWindow`.
- **Prompts**: custom Toplevel with inline validation message; until accepts 24-hour `HH:MM` (e.g. 17:30).
- **Version**: `pyproject.toml` is the single source; app reads it via `importlib.metadata` or a build-generated `_version.py`; CI checks tag equals version.
- **CI**: one workflow on windows-latest: install, pytest, PyInstaller one-file, upload-artifact; on `v*` tag create a release attaching the exe.
- **Honesty table**: PowerToys Awake (no lid-close, fails on Modern Standby), ClosedAwake (Store-only), Lidless (closest).

## Risks / Trade-offs
- Undocumented uxtheme ordinals may change: guarded, cosmetic only.
- Wording churn overlaps with `lid-safe-hold` strings: land that change first or rebase.
- No test suite exists yet: add minimal pytest smoke tests so CI is meaningful.
