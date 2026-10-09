# Proposal

## Why

Today HustleOn rewrites the machine's powercfg (lid = Do Nothing, sleep/hibernate/display = Never) once and leaves it that way forever (`hustleon_core.py:90-136`, spec "No automatic revert"). After a timer expires, the battery guard trips, or the app quits, a closed lid keeps the laptop running in a bag. The one-time snapshot (`hustleon_core.py:93-98`) is also never refreshed and can capture already-enforced values, making Restore a no-op. Several concurrency and robustness bugs compound this (see design).

Decision made by the user: lid/sleep powercfg settings are applied ONLY while a hold is live, and the original values are restored whenever the hold ends (Off, timer/until expiry, battery-guard trip, Quit, crash recovery on next launch).

## What Changes

- **Apply-while-live / restore-on-end**: every hold start snapshots the current values (never stale, never already-enforced values) and applies the lid/sleep settings; every hold end restores them. A persisted "applied" marker lets the next launch restore after a crash or power loss.
- **Battery trip with lid closed**: after restore, the PC returns to normal sleep/hibernate behavior instead of running on.
- **Admin is optional**: powercfg on the current scheme normally works unelevated (`hustleon_core.py:102-106`); only the Modern Standby registry unhide (`hustleon_core.py:75-87`) needs elevation, and it is offered once, optionally.
- **Tri-state lid status** (protected / unprotected / unknown) replacing the boolean (`hustleon_tray.py:119,151-159`); `unknown` shows a link to `ms-settings:powersleep` rather than a permanent warning (`hustleon_tray.py:526`).
- **Optional thermal warning/pause** while the lid is closed and a hold is live.
- **Bug fixes**: single dedicated power thread owning `SetThreadExecutionState` (today called from the menu thread, heartbeat thread and main thread: `hustleon_core.py:356,363,367`, `hustleon_tray.py:146`); frozen exe handles `--enforce-only` before the mutex (`hustleon_tray.py:624`, tray ignores argv); script path from `__file__` not cwd (`hustleon_tray.py:421`); `Engine` RLock; `Local\` mutex with `use_last_error` (`hustleon_tray.py:41-42`); `BatteryLifePercent` as `c_ubyte` (`hustleon_core.py:268`); settings under `%APPDATA%\hustle-on` with atomic write and corrupt-file backup (`hustleon_core.py:290-327`); remove dead no-op block and undocumented `--interval` (`hustleon_core.py:428,463-468`); `resume_snapshot` must not turn an expired hold into indefinite and timers resume with remaining time (`hustleon_core.py:371-384`); Tk dialogs on one dedicated thread (`hustleon_tray.py:334-339,459-460`); pin pystray and guard the `_on_notify` override with `hasattr` fallback (`hustleon_tray.py:166-168`, `requirements.txt`); Quit preserves resumable mode (`hustleon_tray.py:512-516` saves `off`).
- **Features**: "Start with Windows" menu toggle (HKCU Run), first-run setup dialog/checklist, logging to `%APPDATA%\hustle-on\log.txt`.
- **Tests and CI**: pytest suite mocking `get_power_status` / `set_execution_state` / powercfg, plus a Windows CI workflow.

## Capabilities

### New Capabilities

None. All behavior lands in existing capabilities.

### Modified Capabilities

- `power-enforcement`: apply-while-live, restore on every end, per-hold snapshot, crash-recovery marker, optional admin, tri-state lid status, thermal pause (REMOVES "No automatic revert").
- `battery-guard`: trip restores power settings and lets the PC sleep with lid closed; BatteryLifePercent unsigned.
- `persistence-resume`: settings in `%APPDATA%\hustle-on`, atomic write, corrupt backup, applied marker, Quit keeps resumable mode, remaining-time resume.
- `awake-modes`: single power thread owns execution state; engine is thread-safe; timer/until resume semantics.
- `tray-ux`: tri-state lid item, Start with Windows, first-run setup, dedicated Tk thread, Local mutex, `--enforce-only` before mutex, Quit semantics, logging.
- `cli`: remove `--interval`, `--enforce-only` and CLI hold use apply/restore lifecycle, script path robustness.

## Impact

- Code: `hustleon_core.py`, `hustleon_tray.py`, `hustleon.py`, `requirements.txt`, `hustle-on.spec`, new `tests/`, new `.github/workflows/ci.yml`.
- Behavior change: users who relied on the permanent enforce now get settings only during a hold (intentional).
- `openspec/config.yaml` context lines "never auto-reverted" and "no autostart" become stale; updated in the tasks.
- Out of scope: Windows service, multi-scheme handling beyond `SCHEME_CURRENT`, non-Windows support.
