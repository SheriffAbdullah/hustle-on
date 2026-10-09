"""Tasks 3.x: only the power thread calls SetThreadExecutionState."""
import threading

import hustleon_core as core


def test_only_power_thread_calls_api(power, execstate, controller):
    e = core.Engine(enforce=False, controller=controller)
    e.activate(core.MODE_ON)

    def other_thread():
        e.reassert()
        e.tick()
        e.activate(core.MODE_TIMER, minutes=5)
        e.deactivate()

    t = threading.Thread(target=other_thread, name="menu-thread")
    t.start()
    t.join()
    e.reassert()
    names = {n for n, _ in execstate.calls}
    assert names == {"hustleon-power"}
    assert execstate.calls[-1][1] == core.ES_CONTINUOUS


def test_controller_commands(power, execstate, controller):
    assert controller.hold(core.hold_flags(True))
    assert controller.reassert()
    assert controller.release()
    flags = [f for _, f in execstate.calls]
    assert flags == [core.hold_flags(True), core.hold_flags(True), core.ES_CONTINUOUS]
    assert controller.reassert() is False  # nothing held -> nothing to reassert


def test_reassert_after_menu_change_keeps_hold(power, execstate, controller):
    e = core.Engine(enforce=False, controller=controller)
    e.activate(core.MODE_ON)
    e.screen_on = False
    e.reassert()
    assert not (execstate.calls[-1][1] & core.ES_DISPLAY_REQUIRED)
    assert execstate.calls[-1][1] & core.ES_SYSTEM_REQUIRED


def test_resume_goes_through_controller(power, execstate, controller):
    e = core.Engine(enforce=False, controller=controller)
    assert e.resume_from_last({"mode": "on"})
    assert {n for n, _ in execstate.calls} == {"hustleon-power"}
