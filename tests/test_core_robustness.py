"""Tasks 2.x: core robustness fixes."""
import ctypes
import datetime
import json
import os
import threading

import pytest

import hustleon_core as core
from conftest import REAL_GET_POWER_STATUS


# 2.1 BatteryLifePercent unsigned
class _FakeK32:
    def __init__(self, ac, pct):
        self.ac, self.pct = ac, pct

    def GetSystemPowerStatus(self, ref):
        s = ref._obj
        s.ACLineStatus, s.BatteryLifePercent = self.ac, self.pct
        return 1


@pytest.mark.parametrize("pct,expected", [(255, None), (101, None), (100, 100), (0, 0), (30, 30)])
def test_battery_percent_unsigned(monkeypatch, pct, expected):
    monkeypatch.setattr(core, "_kernel32", _FakeK32(0, pct))
    ac, got = REAL_GET_POWER_STATUS()
    assert ac is False and got == expected


def test_battery_ac_unknown_255(monkeypatch):
    monkeypatch.setattr(core, "_kernel32", _FakeK32(255, 50))
    assert REAL_GET_POWER_STATUS() == (None, 50)


def test_struct_fields_are_unsigned():
    assert core._SPS.BatteryLifePercent.size == 1
    s = core._SPS()
    s.BatteryLifePercent = 255
    assert s.BatteryLifePercent == 255


# 2.2 thread safety
def test_concurrent_activate_tick(power):
    e = core.Engine(enforce=False)
    errors = []

    def worker(i):
        try:
            for _ in range(30):
                e.activate(core.MODE_TIMER, minutes=5 + i)
                e.tick()
                e.snapshot_mode()
                e.deactivate()
        except Exception as ex:  # pragma: no cover
            errors.append(ex)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    assert e.mode == "off" and e.deadline is None


def test_engine_has_rlock():
    assert isinstance(core.Engine()._lock, type(threading.RLock()))


# 2.3 resume_snapshot
def test_resume_expired_goes_off_not_on(power):
    e = core.Engine(enforce=False)
    e.paused_snapshot = (core.MODE_TIMER, datetime.datetime.now() - datetime.timedelta(minutes=1), 60)
    e.battery_paused = True
    e.resume_snapshot()
    assert e.mode == "off" and not e.battery_paused


def test_resume_timer_uses_remaining_time(power):
    e = core.Engine(enforce=False)
    dl = datetime.datetime.now() + datetime.timedelta(minutes=20)
    e.paused_snapshot = (core.MODE_TIMER, dl, 60)
    e.resume_snapshot()
    assert e.mode == "timer" and e.deadline == dl
    assert e.timer_minutes == 60


def test_resume_until_and_on(power):
    e = core.Engine(enforce=False)
    dl = datetime.datetime.now() + datetime.timedelta(hours=1)
    e.paused_snapshot = (core.MODE_UNTIL, dl, None)
    e.resume_snapshot()
    assert e.mode == "until" and e.deadline == dl
    e.deactivate()
    e.paused_snapshot = (core.MODE_ON, None, None)
    e.resume_snapshot()
    assert e.mode == "on"


def test_resume_from_last_remaining_and_expired(power):
    e = core.Engine(enforce=False)
    dl = datetime.datetime.now() + datetime.timedelta(minutes=20)
    assert e.resume_from_last({"mode": "timer", "until_iso": dl.isoformat(), "timer_minutes": 60})
    assert e.deadline == dl
    e.deactivate()
    past = (datetime.datetime.now() - datetime.timedelta(minutes=1)).isoformat()
    assert not e.resume_from_last({"mode": "timer", "until_iso": past})
    assert e.mode == "off"
    assert not e.resume_from_last(None)
    assert e.resume_from_last({"mode": "on"}) and e.mode == "on"


# 2.4 CLI
def test_interval_flag_removed(capsys):
    with pytest.raises(SystemExit) as ei:
        core.main(["--interval", "30"])
    assert ei.value.code == 2


def test_cli_loop_sleeps_30s(power, monkeypatch):
    sleeps = []

    def fake_sleep(n):
        sleeps.append(n)
        raise KeyboardInterrupt

    monkeypatch.setattr(core.time, "sleep", fake_sleep)
    monkeypatch.setattr(core, "start_lid_watcher", lambda: None)
    assert core.main(["--on"]) == 0
    assert sleeps == [30]


# 2.5 settings
def test_settings_in_appdata_roundtrip(appdata):
    s = core.load_settings()
    s["battery_threshold"] = 20
    assert core.save_settings(s)
    assert os.path.dirname(core.settings_path()) == str(appdata / "hustle-on")
    assert core.load_settings()["battery_threshold"] == 20
    assert not [f for f in os.listdir(appdata / "hustle-on") if ".tmp" in f]


def test_atomic_write_failure_keeps_old_file(appdata, monkeypatch):
    core.save_settings({"mode": "on"})
    real = os.replace
    monkeypatch.setattr(core.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("x")))
    assert core.save_settings({"mode": "off"}) is False
    monkeypatch.setattr(core.os, "replace", real)
    assert json.load(open(core.settings_path()))["mode"] == "on"


def test_corrupt_settings_backed_up(appdata):
    d = appdata / "hustle-on"
    d.mkdir()
    (d / "settings.json").write_text("{not json")
    s = core.load_settings()
    assert s["mode"] == "off" and s["first_run_done"] is False
    names = os.listdir(d)
    assert any(n.startswith("settings.json.corrupt-") for n in names)
    assert "settings.json" not in names


def test_unknown_mode_becomes_off(appdata):
    core.save_settings({"mode": "bogus"})
    assert core.load_settings()["mode"] == "off"


def test_legacy_settings_migrated_once(appdata, tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "settings.json").write_text(json.dumps({"battery_threshold": 15}))
    monkeypatch.setattr(core, "_legacy_dir", lambda: str(legacy))
    assert core.load_settings()["battery_threshold"] == 15
    core.save_settings({"battery_threshold": 40})
    (legacy / "settings.json").write_text(json.dumps({"battery_threshold": 99}))
    assert core.load_settings()["battery_threshold"] == 40  # not re-migrated


# 2.6 logging
def test_log_written_to_appdata(appdata):
    core.log("hello-test")
    for h in core.get_logger().handlers:
        h.flush()
    assert "hello-test" in open(appdata / "hustle-on" / "log.txt", encoding="utf-8").read()
    h = core.get_logger().handlers[0]
    assert h.maxBytes == 256 * 1024 and h.backupCount == 2
