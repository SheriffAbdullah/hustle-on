# hustle-on — openspec (v1: tray app)

## 1. Goal
Caffeine-style Windows tray app that keeps the machine running with the lid closed,
"as if open". Replaces `hustleon.py` console loop with a tray-resident app.
Stack: Python + pystray + Pillow. Packaged as PyInstaller one-file exe.
Autostart is explicitly out of scope for v1 (deferred).

## 2. Modes (exactly one active)
| Mode | Meaning | Expiry |
|---|---|---|
| `off` | Passive. Execution-state hold released. | — |
| `on` | Indefinite hold. | Manual / quit / battery auto-off |
| `timer` | Hold for N minutes from activation. | Auto → `off` + notification |
| `until` | Hold until wall-clock datetime (today, or tomorrow if time passed). | Auto → `off` + notification |

Hold = `SetThreadExecutionState(ES_CONTINUOUS \| ES_SYSTEM_REQUIRED \| ES_AWAYMODE_REQUIRED [+ ES_DISPLAY_REQUIRED])`,
re-asserted every 60s (heartbeat). Only the API hold is session state; powercfg
lid/sleep enforcement is machine config and is NOT reverted on expiry/off/quit.

## 3. Battery awareness (on by default)
- Poll `GetSystemPowerStatus` (ctypes, no new dep) every 60s (same heartbeat).
- Rule: if on DC (unplugged) AND battery % ≤ threshold (default 30%) AND mode != `off`
  → auto-switch to `off` + notification "Battery low — hustle-on paused".
- Manual re-enable while below threshold is allowed but re-triggers the rule on next
  poll (i.e. user can override for one poll cycle; menu shows warning state).
- Configurable: enabled bool + threshold int (10–50). Shown in menu as
  `Battery guard: on (30%)` info/disabled item + toggles in a `Settings` submenu.
- Tooltip always shows `AC` or `Batt NN%` when knowable.

## 4. Resume last mode on launch
- Persist on every change: `{mode, timer_minutes, until_iso, screen_on, battery_guard, battery_threshold}` → `settings.json` next to exe (fallback `%APPDATA%/hustle-on/` if dir not writable).
- On launch: `on` → resume `on`. `timer`/`until` with deadline still in future → resume
  with remaining time. Expired deadline or `off` → start `off`.
- Corrupt/missing settings → defaults (`off`, screen on, guard on/30%).

## 5. Tray UX (industry-standard best practices)
- **Icon states** (Pillow-generated, no binary assets): gray = off, green = on,
  blue = timer/until. Optional red dot overlay when battery guard tripped/paused.
- **Left-click**: Windows opens the menu on single-click by OS design, so the
  `Turn on/off` item is the *default* item — **double-click toggles**. Same convention as Caffeine.
- **Right-click menu**:
  - `Turn on` / `Turn off` (label flips with state; checked state on `On` item)
  - `Timer ▸` → 30m / 1h / 2h / 8h / Custom… (checked = active preset w/ remaining)
  - `Until ▸` → presets (Lunch 13:00 / EOD 18:00 / Morning 08:00) / Custom… (HH:MM dialog)
  - separator
  - ☑ `Keep screen on` (default on)
  - `Battery guard ▸` → ☑ Enabled / Threshold ▸ 10/15/20/30% / status line (disabled info item)
  - separator
  - `Enforce lid settings (admin)…` → relaunches elevate path, reports OK/Needs Admin
  - `Check settings` → balloon/dialog summary (sleep/lid/display, Modern Standby note)
  - `Quit`
- **Disabled items with reasons**: e.g. `Until 08:00 (passed)` disabled; battery status line disabled info.
- **Tooltip**: `hustle-on: On — 1h12m left — AC` / `Off — Batt 64%`.
- **Notifications** (pystray balloon): mode change, expiry, battery auto-off, lid-enforce result. Rate-limited (no heartbeat spam).
- **Single instance**: named mutex/lockfile; second launch notifies existing instance (or just exits with balloon "already running").
- **Quit**: releases API hold (`ES_CONTINUOUS`), saves settings, removes icon cleanly.
- **No main window in v1**: Custom timer/until via simple dialog (`tkinter.simpledialog`, stdlib, hidden root). No console window in exe build (`--noconsole`).

## 6. CLI parity (same exe/script)
`--on/--off/--timer MIN/--until HH:MM/--screen-on/--screen-off/--check/--no-enforce`
so scheduled tasks and scripts can drive it. CLI invocation of a running instance:
v1 = applies to new process only (documented); single-instance handoff is future work.

## 7. Edge cases
- **Modern Standby (HP Optimized etc.) hides LIDACTION**: enforce tries alias path,
  then registry unhide (`Attributes=2`, needs Admin) + retry; if still absent, menu
  item reports "not exposed — set in Settings > Power & battery > Lid controls".
- **Admin**: tray runs as standard user. Lid enforce elevates on demand (UAC) via
  `ShellExecuteW ... runas` of the exe with `--enforce-only`; result relayed via exit code.
- **Lock screen**: API hold persists (process lives in user session); verify note in README.
  No service in v1.
- **Sleep/hibernate.api**: heartbeat 60s also re-polls battery + deadline checks.
- **Time**: `until` uses local time; DST/zone change mid-hold = deadline stays absolute ISO.

## 8. Build & repo layout
```
hustle-on/
  hustleon.py        # core engine (API hold + powercfg enforce + check) — kept, CLI-usable
  hustleon_tray.py   # tray app (imports core, adds modes/menu/icons/persistence)
  icons/             # generated at runtime (no binaries) — or checked-in PNGs if we freeze them
  openspec.md        # this file
  README.md
  Start-HustleOn.bat
  requirements.txt   # pystray, pillow, pyinstaller (build-only)
  hustle-on.spec     # pyinstaller spec (one-file, noconsole, icon)
```
Build: `pyinstaller --noconsole --onefile --name hustle-on hustleon_tray.py`.

## 9. Out of scope (v1)
Autostart-at-logon, Windows service (pre-logon/lock-screen-proof), global hotkeys,
multi-instance handoff, auto-update, Microsoft Store packaging.

## 10. Decisions locked
- Stack: Python + pystray → PyInstaller exe. No .NET SDK on this machine.
- Battery guard: yes, default on/30%. Resume last mode: yes.
- UX: best-practice tray conventions above.
