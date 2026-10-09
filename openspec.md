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
- **Icon states** (basic circle + white glyph, no binary assets): gray power = off,
  green infinity = on indefinitely, green hourglass = timer, green wall clock = until date/time,
  gray pause-bars = battery-paused. Red dot = LIVE, on the three live states only.
  (Candidates explored in `icons/candidates/`; final set previewed in `icons/icon-gallery.html`.)
- **Click behavior** (Caffeine-style, via `TrayIcon` subclass — upstream pystray maps
  left-click to default-item activation, which caused surprise toggles): EVERY click
  (left or right) opens the popup menu. No double-click action (backend delivers no
  DBLCLK without CS_DBLCLKS). Toggling happens only via menu items. `default=` flags
  remain as bold highlight on the recommended item.
- **Right-click menu** (Caffeine-style labels):
  - `Keep awake indefinitely` (checked when on; double-click default when off)
  - `Keep awake on interval ▸` → 30 minutes / 1 hour / 2 hours / 8 hours / Custom…
    (active preset checked, remaining time appended to the label)
  - `Keep awake until expiration date and time ▸` → Lunch 13:00 / EOD 18:00 /
    Morning 08:00 / Custom… (deadline appended to the label)
  - `Off (keep using the selected power plan)` (checked when off; double-click default when on)
  - separator
  - ☑ `Keep screen on` (default on)
  - `Battery guard ▸` → ☑ Enabled / Threshold ▸ 10/15/20/30% / status line (disabled info item)
  - separator
  - `Enforce lid settings (admin)…` → relaunches elevate path, reports OK/Needs Admin
  - `About HustleOn…` → dialog with version, live status and short power summary
    (sleep/display/lid, Modern Standby note)
  - `Quit`
- **Disabled items with reasons**: e.g. `Until 08:00 (passed)` disabled; battery status line disabled info.
- **Tooltip** (short, branded): `HustleOn · Awake indefinitely · AC 100%` / `HustleOn · 1h12m left · Batt 64%` / `HustleOn · Off · AC` / `HustleOn · Paused · Batt 15%`.
- **Notifications — alerts only, success is silent**: battery auto-off, Windows refusing
  the stay-awake request (`api_ok` tracked in engine, alerted once per hold), bad `until`
  input, elevation failure. Mode changes, timer expiry (completed as asked), guard toggles,
  enforce launch: silent. Explicit dialogs (`Check settings`, single-instance notice) stay.
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
