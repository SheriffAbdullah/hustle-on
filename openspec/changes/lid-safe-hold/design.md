# Design

## Context

Verified current behavior: `enforce_power_settings()` snapshots once if `defaults_backup.json` is absent (`hustleon_core.py:93-98`), applies lid/sleep/hibernate/display = 0, and never reverts. The tray never enforces on mode actions; only About -> Fix lid does, via `ShellExecuteW runas` (`hustleon_tray.py:416-428`). Execution state is set from three threads (menu callbacks `act_*`, heartbeat `engine.tick`, main `resume_last_mode` -> `engine.reassert` at `hustleon_tray.py:146`), but `SetThreadExecutionState` is per-thread, so a hold set on one thread can be cleared or lost when that thread's state is overwritten.

## Goals / Non-Goals

Goals: power settings changed only while a hold is live; always restored; crash-safe; no admin for the common case; fix the audited bugs; add autostart, first-run setup, logging; testable core.
Non-goals: service/driver, per-scheme management, non-Windows.

## Decisions

1. **PowerController (new, in core)**. One daemon thread owns a command queue (`hold(flags)`, `release()`, `reassert()`, `stop()`) and is the only caller of `set_execution_state`. `Engine` posts commands and reads `api_ok` from a result field. Alternative (lock around calls) rejected: the lock does not fix per-thread semantics. The CLI path uses the same controller.
2. **Apply/restore lifecycle (`PowerProfile`)**. `begin_hold()`: if an `applied` marker already exists (crash leftover) restore first; then snapshot via `_query_index`; refuse to snapshot values equal to the enforced values when a marker says we wrote them (treat as stale, keep the older marker snapshot); write snapshot+`applied=true` atomically; then apply. `end_hold(reason)`: restore snapshot, clear marker. Called on Off, expiry, guard trip, Quit, CLI Ctrl+C. Snapshot is always retaken at the next hold start, so a user changing their plan between holds is respected.
3. **Crash/power-loss recovery**. The marker file `applied.json` (in `%APPDATA%\hustle-on`) holds the snapshot and scheme GUID. On launch, before resume logic, a present marker means the previous run died mid-hold: restore, clear, then let resume decide whether to begin a new hold (which re-snapshots).
4. **Sleep after guard trip**. Guard trip -> `end_hold("battery")` restores lid action. If the lid is closed (detected via `GetSystemPowerStatus` is not enough; use the lid-switch power notification `GUID_LIDSWITCH_STATE_CHANGE` or, simpler, record whether a lid-close event was seen while held) the app requests sleep with `SetSuspendState(hibernate=True)` falling back to sleep, once, so the PC returns to normal rather than running on. If lid state is unknown, do not force sleep; normal timeouts apply.
5. **Optional admin**. Apply tries unelevated first. Only if the lid setting is hidden/rejected does the app offer the one-time elevated step (`--enforce-only` renamed semantics: unhide registry only, `Attributes=2`); the choice is remembered (`unhide_done`). After unhide, all later applies are unelevated.
6. **Tri-state lid**. `protected` (read-back Do Nothing AC+DC while held, or applied marker with verified read-back), `unprotected` (read-back shows Sleep/Hibernate/Shutdown during a hold), `unknown` (setting hidden or query failed). `unknown` shows a menu item "Lid status unknown - open Windows power settings" launching `ms-settings:powersleep`; no launch-time warning. Only `unprotected` while a hold is live raises an alert.
7. **Thermal (optional)**. Setting `thermal_guard` (default off). While a hold is live and the lid is closed, if an available thermal source (ACPI thermal zone via WMI `MSAcpi_ThermalZoneTemperature`, queried through `powershell`/`wmic`-free ctypes is not available) exceeds a threshold, alert and end the hold like the battery guard. If no sensor is readable the feature reports "unavailable" and does nothing.
8. **Engine thread safety**: `threading.RLock` around mode/deadline/paused-snapshot mutation in `activate`, `deactivate`, `tick`, `resume_snapshot`, `reassert`; tray `persist()` reads under the lock.
9. **Resume fixes**: `resume_snapshot` re-arms timer/until only for the remaining time of a future deadline (`deadline - now`, not full `timer_minutes`); an expired snapshot results in `off`, never `on` (`hustleon_core.py:376-384`). `resume_last_mode` reads a separate `last_mode` so Quit (which deactivates) still resumes the user's last mode while Off remains Off.
10. **Quit semantics**: Quit does `end_hold("quit")` but persists `last_mode`/deadline as resumable; explicit Off clears `last_mode`.
11. **Storage**: `settings.json`, `applied.json`, `log.txt` move to `%APPDATA%\hustle-on`. Writes use temp file + `os.replace`. An unparseable `settings.json` is renamed `settings.json.corrupt-<ts>` and defaults used. One-time migration copies an existing next-to-exe `settings.json`.
12. **Process/robustness**: tray `main()` parses `--enforce-only` before creating the mutex (frozen exe has no script arg). Mutex name `Local\HustleOnSingleInstance`, `WinDLL(..., use_last_error=True)` and `ctypes.get_last_error()`. Non-frozen elevation uses `os.path.abspath(core.__file__)`. `BatteryLifePercent` becomes `c_ubyte`; unknown stays 255. Dead block at `hustleon_core.py:463-468` and `--interval` removed (loop sleeps 30s). pystray pinned (`pystray==<current tested>` in `requirements.txt`); `TrayIcon._on_notify` override only installed when `hasattr(pystray.Icon, "_on_notify")` and backend `_win32` imports succeed, else default right-click menu.
13. **Tk on one thread**: a `UiThread` runs the sole `tk.Tk()` hidden root; dialogs (custom timer/until, About, first-run) are `root.after` calls fed by a queue, replacing per-call `tk.Tk()` (`hustleon_tray.py:334-339,459-460`). The "one dialog" guard stays.
14. **Start with Windows**: menu toggle writes/deletes `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\HustleOn` with the quoted exe path (frozen) or `pythonw.exe "<abs script>"`. Checked state is read from the registry at menu open.
15. **First-run setup**: shown when `settings.json` has no `first_run_done`. A Tk checklist: lid status (with link to `ms-settings:powersleep`), battery guard on, Start with Windows toggle, one-time admin unhide offer when needed. Completion sets `first_run_done`.
16. **Logging**: stdlib `logging` rotating file `%APPDATA%\hustle-on\log.txt` (256 KB x 2), logging hold start/end, apply/restore results, guard trips, recovery, errors. Notifications remain alerts-only.

## Risks / Trade-offs

- Restoring on every end means a failed restore leaves the machine non-default: retry once, keep marker so next launch retries, alert on persistent failure.
- Forcing sleep after a battery trip is intrusive: only when lid known closed and the hold just ended due to guard.
- Moving settings to APPDATA drops "portable" next-to-exe settings; migration covers existing users.
- Thermal sensor availability varies; feature is opt-in and degrades to "unavailable".

## Migration

On first launch of the new version: copy any next-to-exe `settings.json` to `%APPDATA%\hustle-on`. A legacy `defaults_backup.json` is treated as untrusted (it may hold already-enforced values) and is not auto-applied; the first-run dialog offers "Restore my previous sleep settings" from it when its values are not all the enforced ones, then deletes it.

## Open Questions

- Thermal sensor source (WMI thermal zones are absent on many laptops); acceptable to ship as best-effort.
