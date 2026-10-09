# hustle-on

Keep Windows running with the lid closed, as if open. Caffeine-style tray app.
No key-jiggling — uses `SetThreadExecutionState` + `powercfg` enforcement.

## Use (recommended)
Run **`dist/hustle-on.exe`** (or the installed copy) - it lives in the tray (up-arrow area):
1. **Tap the icon** -> menu opens. Pick `Keep awake indefinitely`, a Timer, or an Until time.
2. **First run:** a short setup window shows your lid status, battery guard and `Start with Windows`.
   No admin is needed day to day. If Windows hides the lid setting (Modern Standby), the menu shows
   `Lid status unknown` (opens Windows power settings) and `About HustleOn...` has a one-time
   `Unlock lid setting (admin)...` button. Alternatively set
   `Settings > System > Power & battery > Lid controls > Do Nothing` yourself.
3. Close the lid. Everything keeps running. Hover the icon for live status.

- **Settings are changed only while a hold is live.** When a hold starts HustleOn snapshots your
  lid / sleep / hibernate / display settings, sets them to Do Nothing / Never, and **restores them
  whenever the hold ends** (Off, timer or until expiry, low-battery pause, Quit). If the app or PC dies
  mid-hold, the next launch restores them (`%APPDATA%\hustle-on\applied.json`).
- If the battery guard trips while the lid is closed, your settings are restored and the PC goes to
  sleep/hibernate instead of running on in a bag.
- Optional `Also stop when hot` (Battery guard submenu): best effort, only works when Windows exposes an
  ACPI thermal sensor; otherwise it does nothing.
- Timers: 30 minutes / 1 / 2 / 8 hours / custom. Until: Lunch 13:00 / EOD 18:00 / Morning 08:00 / custom HH:MM (past times mean tomorrow, and say so).
- `Keep screen on` toggle, `Battery guard` (auto-pauses on low battery, default 30%; `Resume hold` in the menu when plugged back in).
- `Start with Windows` toggle (per-user Run key). Resumes the last mode on launch (also after `Quit`; an explicit `Off` stays off). Single instance.
- Settings, the applied marker and `log.txt` live in `%APPDATA%\hustle-on`.
- `About HustleOn...` -> `Restore sleep defaults` is a manual recovery button (only if a restore ever failed).

## CLI / source
```
python hustleon.py --check        # show lid/sleep/display settings
python hustleon.py                # hold indefinitely (console; Ctrl+C restores settings)
python hustleon.py --timer 60     # hold 60 min
python hustleon.py --until 18:00  # hold until 18:00
python hustleon_tray.py           # tray app from source (needs: pip install -r requirements.txt)
```
Rebuild exe: `python -m PyInstaller --noconsole --onefile --manifest app.manifest --name hustle-on hustleon_tray.py`

## Why Caffeine fails here
Caffeine fakes F15 keypresses (idle-sleep only). Lid-close is a power-button
action - it bypasses it. While a hold is live hustle-on sets lid to Do Nothing + holds the
execution state, so close the lid and everything keeps running. Keep plugged
in and watch heat with the lid closed.

## Development
```
pip install -r requirements-dev.txt
python -m pytest        # all tests mock powercfg, SetThreadExecutionState, the registry and the battery
```

See `openspec.md` for the full v1 spec.
