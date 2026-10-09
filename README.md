# hustle-on

Keep Windows running with the lid closed, as if open. Caffeine-style tray app.
No key-jiggling — uses `SetThreadExecutionState` + `powercfg` enforcement.

## Use (recommended)
Double-click **`dist/hustle-on.exe`** — lives in the tray (up-arrow area):
- Double-click icon = on/off toggle. Right-click = full menu.
- Timer (30m/1h/2h/8h/custom), Until (13:00/18:00/08:00/custom HH:MM).
- `Keep screen on` toggle, `Battery guard` (auto-pause on low battery, default 30%).
- `Enforce lid settings (admin)…` for one-time UAC lid fix, `Check settings` to verify.
- Resumes last mode on launch. Single instance. `Quit` restores normal sleep.

First run: right-click → `Enforce lid settings (admin)…`, or
`Settings > System > Power & battery > Lid controls > Do Nothing`
(required on HP Modern Standby schemes that hide the lid action).

## CLI / source
```
python hustleon.py --check        # show lid/sleep/display settings
python hustleon.py                # hold indefinitely (console)
python hustleon.py --timer 60     # hold 60 min
python hustleon.py --until 18:00  # hold until 18:00
python hustleon_tray.py           # tray app from source (needs: pip install -r requirements.txt)
```
Rebuild exe: `python -m PyInstaller --noconsole --onefile --name hustle-on hustleon_tray.py`

## Why Caffeine fails here
Caffeine fakes F15 keypresses (idle-sleep only). Lid-close is a power-button
action — it bypasses it. hustle-on sets lid to Do Nothing + holds the
execution state, so close the lid and everything keeps running. Keep plugged
in and watch heat with the lid closed.

See `openspec.md` for the full v1 spec.
