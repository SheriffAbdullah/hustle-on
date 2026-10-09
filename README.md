# hustle-on

Keep Windows running with the lid closed, as if open. Caffeine-style tray app.
No key-jiggling — uses `SetThreadExecutionState` + `powercfg` enforcement.

## Use (recommended)
Run **`dist/hustle-on.exe`** (or the installed copy) — it lives in the tray (up-arrow area):
1. **Tap the icon** → menu opens. Pick `Keep awake indefinitely`, a Timer, or an Until time.
2. **First run:** tap → `About HustleOn…` → `Fix lid settings (admin)…`, approve the UAC
   prompt. Until the lid reads "Do Nothing", closing it can still sleep the PC —
   the menu shows a ⚠ warning line while that's true. (On HP Modern Standby schemes
   the lid slot is hidden; alternatively set `Settings > System > Power & battery > Lid controls > Do Nothing`.)
3. Close the lid. Everything keeps running. Hover the icon for live status.

- Timers: 30 minutes / 1 / 2 / 8 hours / custom. Until: Lunch 13:00 / EOD 18:00 / Morning 08:00 / custom HH:MM (past times mean tomorrow, and say so).
- `Keep screen on` toggle, `Battery guard` (auto-pauses on low battery, default 30%; `Resume hold` in the menu when plugged back in).
- Resumes last mode on launch (autostart via the Startup shortcut). Single instance.
- `Quit` releases the stay-awake hold but **leaves your power settings as they are**.
  To undo them: `About HustleOn…` → `Restore sleep defaults`.

## CLI / source
```
python hustleon.py --check        # show lid/sleep/display settings
python hustleon.py                # hold indefinitely (console)
python hustleon.py --timer 60     # hold 60 min
python hustleon.py --until 18:00  # hold until 18:00
python hustleon_tray.py           # tray app from source (needs: pip install -r requirements.txt)
```
Rebuild exe: `python -m PyInstaller --noconsole --onefile --manifest app.manifest --name hustle-on hustleon_tray.py`

## Why Caffeine fails here
Caffeine fakes F15 keypresses (idle-sleep only). Lid-close is a power-button
action — it bypasses it. hustle-on sets lid to Do Nothing + holds the
execution state, so close the lid and everything keeps running. Keep plugged
in and watch heat with the lid closed.

See `openspec.md` for the full v1 spec.
