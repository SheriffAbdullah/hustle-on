"""Safety net: no test may touch real powercfg, SetThreadExecutionState,
the registry, the battery, or the user's real %APPDATA%."""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hustleon_core as core  # noqa: E402

REAL_GET_POWER_STATUS = core.get_power_status


class FakePower:
    """In-memory powercfg: scheme values for AC/DC, with a call log."""

    def __init__(self):
        self.values = {
            ("SUB_BUTTONS", "LIDACTION"): ["0x00000001", "0x00000001"],
            ("SUB_SLEEP", "STANDBYIDLE"): ["0x00000384", "0x00000258"],
            ("SUB_SLEEP", "HIBERNATEIDLE"): ["0x00000e10", "0x00000708"],
            ("SUB_VIDEO", "VIDEOIDLE"): ["0x000002d0", "0x00000168"],
        }
        self.calls = []
        self.fail_set = False          # make every /set* fail
        self.fail_once = 0             # fail next N /set* calls
        self.hidden_lid = False        # lid setting hidden (Modern Standby)
        self.scheme = "381b4222-f694-41f0-9685-ff5bb260df2e"

    def run_powercfg(self, args):
        self.calls.append(list(args))
        op = args[0]
        if op == "/getactivescheme":
            return True, f"Power Scheme GUID: {self.scheme}  (Balanced)"
        if op == "/setactive":
            return True, ""
        if op in ("/setacvalueindex", "/setdcvalueindex"):
            sub, setting, val = args[2], args[3], args[4]
            if self.hidden_lid and setting == "LIDACTION":
                return False, "Invalid Parameters -- the setting is not supported"
            if self.fail_set:
                return False, "boom"
            if self.fail_once > 0:
                self.fail_once -= 1
                return False, "transient"
            idx = 0 if op == "/setacvalueindex" else 1
            self.values[(sub, setting)][idx] = "0x%08x" % int(val)
            return True, ""
        return False, "unexpected"

    def query_index(self, sub, setting):
        if self.hidden_lid and setting == "LIDACTION":
            return None
        v = self.values[(sub, setting)]
        return v[0], v[1]

    def sets(self):
        return [c for c in self.calls if c[0] in ("/setacvalueindex", "/setdcvalueindex")]


class FakeExec:
    def __init__(self):
        self.calls = []        # (thread_name, flags)

    def __call__(self, flags):
        import threading
        self.calls.append((threading.current_thread().name, flags))
        return 0x80000000, True


@pytest.fixture(autouse=True)
def appdata(tmp_path, monkeypatch):
    d = tmp_path / "appdata"
    d.mkdir()
    monkeypatch.setenv("APPDATA", str(d))
    monkeypatch.setattr(core, "_legacy_dir", lambda: str(tmp_path / "nolegacy"))
    return d


@pytest.fixture(autouse=True)
def no_real_system(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("test attempted a real subprocess/system call")
    monkeypatch.setattr(core.subprocess, "run", _blocked)
    # any real registry use fails (no attributes); tests install their own fake
    monkeypatch.setitem(sys.modules, "winreg", types.SimpleNamespace())
    monkeypatch.setattr(core, "set_execution_state", FakeExec())
    monkeypatch.setattr(core, "_controller", None)
    monkeypatch.setattr(core, "get_power_status", lambda: (True, 100))


@pytest.fixture
def power(monkeypatch):
    p = FakePower()
    monkeypatch.setattr(core, "run_powercfg", p.run_powercfg)
    monkeypatch.setattr(core, "_query_index", p.query_index)
    return p


@pytest.fixture
def execstate():
    return core.set_execution_state


@pytest.fixture
def controller(monkeypatch):
    c = core.PowerController()
    monkeypatch.setattr(core, "_controller", c)
    yield c
    c.stop()
