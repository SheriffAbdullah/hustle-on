"""Tasks 4.x: apply-while-live, restore, crash recovery, lid status, guard, thermal."""
import datetime
import json
import sys
import types

import hustleon_core as core

ORIG = {("SUB_BUTTONS", "LIDACTION"): ["0x00000001", "0x00000001"],
        ("SUB_SLEEP", "STANDBYIDLE"): ["0x00000384", "0x00000258"],
        ("SUB_SLEEP", "HIBERNATEIDLE"): ["0x00000e10", "0x00000708"],
        ("SUB_VIDEO", "VIDEOIDLE"): ["0x000002d0", "0x00000168"]}


def values(power):
    return {k: list(v) for k, v in power.values.items()}


def test_nothing_changes_while_off(power):
    core.Engine()
    assert power.sets() == []
    assert values(power) == ORIG


def test_apply_on_start_restore_on_off(power):
    e = core.Engine()
    e.activate(core.MODE_ON)
    assert all(v == ["0x00000000"] * 2 for v in power.values.values())
    assert core.load_marker() is not None
    assert e.lid_status == "protected"
    e.deactivate()
    assert values(power) == ORIG
    assert core.load_marker() is None


def test_changing_mode_while_live_does_not_resnapshot(power):
    e = core.Engine()
    e.activate(core.MODE_ON)
    e.activate(core.MODE_TIMER, minutes=10)
    e.deactivate()
    assert values(power) == ORIG   # never recorded enforced values


def test_fresh_snapshot_each_hold(power):
    e = core.Engine()
    e.activate(core.MODE_ON)
    e.deactivate()
    power.values[("SUB_SLEEP", "STANDBYIDLE")] = ["0x00000064", "0x00000032"]  # user edits plan
    e.activate(core.MODE_ON)
    e.deactivate()
    assert power.values[("SUB_SLEEP", "STANDBYIDLE")] == ["0x00000064", "0x00000032"]


def test_restore_on_expiry(power):
    e = core.Engine()
    e.activate(core.MODE_TIMER, minutes=1)
    e.deadline = datetime.datetime.now() - datetime.timedelta(seconds=1)
    assert e.tick() == ["expired"]
    assert values(power) == ORIG and e.mode == "off"


def test_restore_on_guard_trip(power, monkeypatch):
    e = core.Engine(guard_threshold=30)
    e.activate(core.MODE_ON)
    monkeypatch.setattr(core, "get_power_status", lambda: (False, 10))
    assert e.tick() == ["battery_pause"]
    assert values(power) == ORIG


def test_restore_on_quit(power):
    e = core.Engine()
    e.activate(core.MODE_ON)
    e.deactivate("quit")
    assert values(power) == ORIG


def test_restore_retries_once_then_succeeds(power):
    e = core.Engine()
    e.activate(core.MODE_ON)
    power.fail_once = 1
    e.deactivate()
    assert e.restore_ok and values(power) == ORIG and core.load_marker() is None


def test_restore_persistent_failure_keeps_marker(power):
    e = core.Engine()
    e.activate(core.MODE_ON)
    power.fail_set = True
    e.deactivate()
    assert e.restore_ok is False
    assert core.load_marker() is not None   # next launch retries
    power.fail_set = False
    core.recover_applied()
    assert values(power) == ORIG and core.load_marker() is None


def test_crash_recovery_restores_on_launch(power):
    e = core.Engine()
    e.activate(core.MODE_ON)           # "process dies" here: no deactivate
    results, ok = core.recover_applied()
    assert ok and values(power) == ORIG and core.load_marker() is None


def test_recover_without_marker_is_noop(power):
    assert core.recover_applied() == ([], True)
    assert power.sets() == []


def test_stale_enforced_values_not_snapshotted(power):
    e = core.Engine()
    e.activate(core.MODE_ON)           # crash leaves enforced values + marker
    e2 = core.Engine()                 # new run begins a hold WITHOUT recovery first
    e2.activate(core.MODE_ON)
    e2.deactivate()
    assert values(power) == ORIG


def test_stale_marker_restore_failure_keeps_older_snapshot(power):
    e = core.Engine()
    e.activate(core.MODE_ON)
    power.fail_once = 100              # stale restore fails
    e2 = core.Engine()
    e2.activate(core.MODE_ON)
    power.fail_once = 0
    snap = core.load_marker()["snapshot"]
    assert snap["sleep"] == ["0x00000384", "0x00000258"]   # original, not zeros
    e2.deactivate()
    assert values(power) == ORIG


def test_no_snapshot_manual_restore_reports(power):
    res = core.restore_power_defaults()
    assert res[0][1] is False and power.sets() == []


def test_manual_restore_with_marker(power):
    e = core.Engine()
    e.activate(core.MODE_ON)
    assert all(ok for _, ok, _ in core.restore_power_defaults())
    assert values(power) == ORIG


def test_missing_values_skipped(power):
    power.hidden_lid = True
    e = core.Engine()
    e.activate(core.MODE_ON)
    assert e.lid_status == "unknown"
    e.deactivate()
    assert e.restore_ok
    assert power.values[("SUB_SLEEP", "STANDBYIDLE")] == ORIG[("SUB_SLEEP", "STANDBYIDLE")]


def test_unelevated_only_no_registry(power, monkeypatch):
    called = []
    monkeypatch.setattr(core, "unhide_lid_setting", lambda: called.append(1) or (False, ""))
    power.hidden_lid = True
    e = core.Engine()
    e.activate(core.MODE_ON)
    e.deactivate()
    assert called == []                 # apply/restore never elevate or touch HKLM


def test_apply_failures_reported_without_crash(power):
    power.fail_set = True
    e = core.Engine()
    e.activate(core.MODE_ON)
    assert any(not ok for _, ok, _ in e.apply_results)
    assert e.mode == "on"


def test_scheme_not_switched_back_if_user_changed_plan(power):
    e = core.Engine()
    e.activate(core.MODE_ON)
    power.scheme = "11111111-2222-3333-4444-555555555555"
    power.calls.clear()
    e.deactivate()
    assert not any(c[0] == "/setactive" for c in power.calls)


def test_no_enforce_leaves_power_alone(power):
    e = core.Engine(enforce=False)
    e.activate(core.MODE_ON)
    e.deactivate()
    assert power.sets() == [] and core.load_marker() is None


def test_enforce_only_unhide_uses_mock(monkeypatch):
    monkeypatch.setattr(core, "unhide_lid_setting", lambda: (True, "ok"))
    assert core.enforce_unhide_only()[0][1] is True


def test_unhide_registry_calls_mocked_winreg(monkeypatch):
    written = []

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=1, KEY_SET_VALUE=2, REG_DWORD=4,
        OpenKey=lambda *a: Key(),
        SetValueEx=lambda k, name, r, t, v: written.append((name, v)))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert core.unhide_lid_setting()[0] is True
    assert written == [("Attributes", 2)]


# 4.6 tri-state
def test_lid_status_tristate(power):
    assert core.lid_status() == "unprotected"      # user value = Sleep
    power.values[("SUB_BUTTONS", "LIDACTION")] = ["0x00000000", "0x00000000"]
    assert core.lid_status() == "protected"
    power.values[("SUB_BUTTONS", "LIDACTION")] = ["0x00000000", "0x00000001"]
    assert core.lid_status() == "unprotected"
    power.hidden_lid = True
    assert core.lid_status() == "unknown"


# 4.7 guard trip + lid closed
def test_guard_trip_lid_closed_restores_then_sleeps(power, monkeypatch):
    order = []
    monkeypatch.setattr(core, "get_power_status", lambda: (False, 10))
    e = core.Engine(lid_state_fn=lambda: True,
                    suspend_fn=lambda: order.append(("suspend", values(power) == ORIG)) or True)
    e.activate(core.MODE_ON)
    assert e.tick() == ["battery_pause", "sleeping"]
    assert order == [("suspend", True)]            # restored BEFORE suspending


def test_guard_trip_lid_open_or_unknown_does_not_sleep(power, monkeypatch):
    monkeypatch.setattr(core, "get_power_status", lambda: (False, 10))
    for state in (False, None):
        calls = []
        e = core.Engine(lid_state_fn=lambda s=state: s, suspend_fn=lambda: calls.append(1))
        e.activate(core.MODE_ON)
        assert e.tick() == ["battery_pause"]
        assert calls == []


def test_suspend_falls_back_to_sleep(monkeypatch):
    calls = []

    class PP:
        def SetSuspendState(self, hib, f, w):
            calls.append(hib)
            return 0 if hib else 1

    monkeypatch.setattr(core.ctypes, "WinDLL", lambda name: PP())
    assert core.request_suspend() is True
    assert calls == [True, False]


# 4.8 thermal
def test_thermal_trip_when_lid_closed(power):
    sus = []
    e = core.Engine(thermal_guard=True, thermal_threshold=90, lid_state_fn=lambda: True,
                    thermal_fn=lambda: 95.0, suspend_fn=lambda: sus.append(1) or True)
    e.activate(core.MODE_ON)
    assert e.tick() == ["thermal", "sleeping"]
    assert e.mode == "off" and values(power) == ORIG and sus == [1]


def test_thermal_ignored_when_lid_open_or_disabled(power):
    for kw in ({"thermal_guard": True, "lid_state_fn": lambda: False},
               {"thermal_guard": False, "lid_state_fn": lambda: True}):
        e = core.Engine(thermal_threshold=90, thermal_fn=lambda: 99.0, **kw)
        e.activate(core.MODE_ON)
        assert e.tick() == []
        e.deactivate()


def test_thermal_unavailable_does_nothing(power):
    e = core.Engine(thermal_guard=True, lid_state_fn=lambda: True, thermal_fn=lambda: None)
    e.activate(core.MODE_ON)
    assert e.tick() == [] and e.thermal_available is False and e.mode == "on"


def test_read_temperature_parses_wmi(monkeypatch):
    monkeypatch.setattr(core.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout="3232\n3000\n"))
    assert abs(core.read_temperature_c() - (3232 / 10 - 273.15)) < 0.01
    monkeypatch.setattr(core.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=""))
    assert core.read_temperature_c() is None


# CLI lifecycle
def _interrupt(n):
    raise KeyboardInterrupt


def test_cli_ctrl_c_restores(power, monkeypatch):
    monkeypatch.setattr(core, "start_lid_watcher", lambda: None)
    monkeypatch.setattr(core.time, "sleep", _interrupt)
    assert core.main(["--timer", "5"]) == 0
    assert values(power) == ORIG and core.load_marker() is None


def test_cli_recovers_leftover_marker(power, monkeypatch):
    core.Engine().activate(core.MODE_ON)      # leaves enforced + marker
    monkeypatch.setattr(core, "start_lid_watcher", lambda: None)
    monkeypatch.setattr(core.time, "sleep", _interrupt)
    core.main(["--on"])
    assert values(power) == ORIG


def test_legacy_backup_untrusted(power, appdata):
    d = appdata / "hustle-on"
    d.mkdir(exist_ok=True)
    zeros = {k: ["0x00000000", "0x00000000"] for k in ("sleep", "hibernate", "display", "lid")}
    (d / "defaults_backup.json").write_text(json.dumps(zeros))
    assert core.legacy_restore_candidate() is None
    good = dict(zeros, sleep=["0x00000384", "0x00000258"])
    (d / "defaults_backup.json").write_text(json.dumps(good))
    assert core.legacy_restore_candidate() is not None
    assert all(ok for _, ok, _ in core.restore_legacy_backup())
    assert not (d / "defaults_backup.json").exists()
