# Tasks

## 1. Test harness first

- [x] 1.1 Add `tests/` with pytest config and `tests/conftest.py` fixtures mocking `get_power_status`, `set_execution_state`, `run_powercfg`, `_query_index`, and a temp `%APPDATA%`
- [x] 1.2 Add `requirements-dev.txt` (pytest) and pin pystray in `requirements.txt`
- [x] 1.3 Add characterization tests for current Engine tick/expiry/guard behavior

## 2. Core robustness fixes

- [x] 2.1 Read `BatteryLifePercent` as `c_ubyte`; test 255 and 101 map to unknown
- [x] 2.2 Add `threading.RLock` to `Engine`; test concurrent activate/tick
- [x] 2.3 Fix `resume_snapshot`: expired -> off, timer/until resume with remaining time; tests
- [x] 2.4 Remove dead no-op block and `--interval` from `main()`; loop sleeps 30s; test argparse rejects `--interval`
- [x] 2.5 Move settings to `%APPDATA%\hustle-on` with atomic write, corrupt-file backup, one-time migration; tests
- [x] 2.6 Add rotating logger to `%APPDATA%\hustle-on\log.txt`

## 3. Power thread

- [x] 3.1 Add `PowerController` thread owning all `set_execution_state` calls (hold/release/reassert/stop)
- [x] 3.2 Route `Engine.activate/deactivate/reassert` and `resume_last_mode` through it; test that only the power thread calls the mock

## 4. Apply-while-live and restore

- [x] 4.1 Implement `begin_hold` (fresh snapshot, never snapshot enforced values, write `applied.json` marker, apply)
- [x] 4.2 Implement `end_hold(reason)` (restore, retry once, clear marker)
- [x] 4.3 Wire into activate/deactivate/expiry/guard trip/Quit/CLI Ctrl+C
- [x] 4.4 Crash recovery: restore marker on launch before resume; tests for leftover marker and stale enforced values
- [x] 4.5 Unelevated-first apply; limit elevation to one-time registry unhide with remembered choice; tests with mocked powercfg failures
- [x] 4.6 Tri-state lid status (protected/unprotected/unknown) from read-back; tests
- [x] 4.7 Guard trip with lid closed: restore then request sleep/hibernate; tests (mock lid state and suspend call)
- [x] 4.8 Optional thermal guard with "unavailable" fallback; tests

## 5. Tray fixes and features

- [x] 5.1 Handle `--enforce-only` before the mutex in tray `main()`; use `Local\` mutex with `use_last_error`
- [x] 5.2 Use `core.__file__` for the script path in the elevation command
- [x] 5.3 Dedicated Tk UI thread for custom timer/until, About, and first-run dialogs
- [x] 5.4 Guard `_on_notify` override with `hasattr`/import fallback
- [x] 5.5 Quit preserves resumable `last_mode`; explicit Off clears it; tests
- [x] 5.6 Lid-status menu item with `ms-settings:powersleep` link; drop launch-time warning; About button changed to one-time unlock
- [x] 5.7 `Start with Windows` toggle (HKCU Run); tests with mocked winreg
- [x] 5.8 First-run setup dialog/checklist and `first_run_done`

## 6. CI and docs

- [x] 6.1 Add `.github/workflows/ci.yml` on `windows-latest` running `pytest` and a PyInstaller build smoke test
- [x] 6.2 Update `README.md` and `openspec.md` for apply-while-live behavior
- [x] 6.3 Update `openspec/config.yaml` context (revert behavior, autostart now in scope, APPDATA storage)
- [ ] 6.4 Manual verification on a laptop: lid close during hold, timer expiry restore, kill process then relaunch
