"""Task 1.3: behavior that must survive the refactor."""
import datetime

import hustleon_core as core


def test_activate_on_holds(power, execstate):
    e = core.Engine(screen_on=True)
    e.activate(core.MODE_ON)
    assert e.mode == "on" and e.api_ok
    assert execstate.calls[-1][1] == core.hold_flags(True)
    assert core.ES_DISPLAY_REQUIRED & execstate.calls[-1][1]


def test_screen_off_omits_display_flag(power, execstate):
    e = core.Engine(screen_on=False)
    e.activate(core.MODE_ON)
    assert not (core.ES_DISPLAY_REQUIRED & execstate.calls[-1][1])


def test_deactivate_releases(power, execstate):
    e = core.Engine()
    e.activate(core.MODE_ON)
    e.deactivate()
    assert e.mode == "off" and e.deadline is None
    assert execstate.calls[-1][1] == core.ES_CONTINUOUS


def test_timer_expiry(power):
    e = core.Engine()
    e.activate(core.MODE_TIMER, minutes=5)
    e.deadline = datetime.datetime.now() - datetime.timedelta(seconds=1)
    assert e.tick() == ["expired"]
    assert e.mode == "off"


def test_tick_reasserts(power, execstate):
    e = core.Engine()
    e.activate(core.MODE_ON)
    n = len(execstate.calls)
    assert e.tick() == []
    assert len(execstate.calls) == n + 1


def test_guard_trips_on_battery(power, monkeypatch):
    monkeypatch.setattr(core, "get_power_status", lambda: (False, 25))
    e = core.Engine(guard_threshold=30)
    e.activate(core.MODE_ON)
    assert e.tick() == ["battery_pause"]
    assert e.mode == "off" and e.battery_paused


def test_guard_ignores_ac_and_unknown(power, monkeypatch):
    e = core.Engine(guard_threshold=30)
    e.activate(core.MODE_ON)
    monkeypatch.setattr(core, "get_power_status", lambda: (True, 5))
    assert e.tick() == []
    monkeypatch.setattr(core, "get_power_status", lambda: (False, None))
    assert e.tick() == []
    monkeypatch.setattr(core, "get_power_status", lambda: (None, None))
    assert e.tick() == []


def test_guard_disabled(power, monkeypatch):
    monkeypatch.setattr(core, "get_power_status", lambda: (False, 1))
    e = core.Engine(guard=False)
    e.activate(core.MODE_ON)
    assert e.tick() == []


def test_api_refusal_sets_api_ok_false(power, monkeypatch):
    monkeypatch.setattr(core, "set_execution_state", lambda f: (0, False))
    e = core.Engine()
    e.activate(core.MODE_ON)
    assert e.api_ok is False
