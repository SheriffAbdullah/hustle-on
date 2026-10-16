"""Tasks 5.x: tray behavior. Tk, the registry, powercfg and the tray icon are all faked."""
import ctypes
import importlib
import os
import runpy
import sys
import threading
import time
import types

import pytest

pystray = pytest.importorskip("pystray")
pytest.importorskip("PIL")

import hustleon_core as core  # noqa: E402

_real_autostart_enabled = core.autostart_enabled
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def tray(power, monkeypatch):
    sys.modules.pop("hustleon_tray", None)
    t = importlib.import_module("hustleon_tray")
    monkeypatch.setattr(t, "icon", None)
    monkeypatch.setattr(t.ui, "stop", lambda: None)
    monkeypatch.setattr(t, "msgbox", lambda *a, **k: None)
    monkeypatch.setattr(core, "autostart_enabled", lambda: False)
    yield t
    t.engine.deactivate()
    sys.modules.pop("hustleon_tray", None)


# 5.1 --enforce-only handled before the mutex
def test_enforce_only_runs_before_mutex(monkeypatch):
    seen = []
    monkeypatch.setattr(core, "unhide_lid_setting", lambda: seen.append("unhide") or (True, "x"))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("mutex/kernel32 touched before --enforce-only")))
    monkeypatch.setattr(sys, "argv", ["hustleon_tray.py", "--enforce-only"])
    with pytest.raises(SystemExit) as ei:
        runpy.run_path(os.path.join(ROOT, "hustleon_tray.py"), run_name="__main__")
    assert ei.value.code == 0 and seen == ["unhide"]


def test_single_instance_uses_local_mutex_and_last_error(tray, monkeypatch):
    names = []

    class K32:
        def __init__(self):
            def create(sec, owner, name):
                names.append(name)
                ctypes.set_last_error(183)
                return 1
            self.CreateMutexW = create

    boxes = []
    monkeypatch.setattr(tray.ctypes, "WinDLL", lambda *a, **k: K32())
    monkeypatch.setattr(tray.ctypes, "windll", types.SimpleNamespace(
        user32=types.SimpleNamespace(MessageBoxW=lambda *a: boxes.append(a))))
    with pytest.raises(SystemExit) as ei:
        tray.ensure_single_instance()
    assert ei.value.code == 0 and boxes
    assert names == ["Local\\HustleOnSingleInstance"]


# 5.2 script path independent of cwd
def test_elevation_command_uses_module_file(tray, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exe, params = tray.elevation_command()
    assert os.path.abspath(core.__file__) in params and params.endswith("--enforce-only")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert tray.elevation_command() == (sys.executable, "--enforce-only")


# 5.3 one Tk root, dialogs on one UI thread
def _fake_tk(created, threads):
    class Root:
        def __init__(self):
            created.append(1)
            threads.append(threading.current_thread().name)
            self._cb = None
            self._quit = False

        def withdraw(self):
            pass

        def iconphoto(self, *a):
            pass

        def after(self, ms, fn):
            self._cb = fn

        def mainloop(self):
            for _ in range(300):
                if self._quit:
                    return
                time.sleep(0.01)
                if self._cb:
                    cb, self._cb = self._cb, None
                    cb()

        def quit(self):
            self._quit = True

    return types.SimpleNamespace(Tk=Root)


def test_ui_thread_single_root_and_thread(tray, monkeypatch):
    created, threads, ran = [], [], []
    monkeypatch.setitem(sys.modules, "tkinter", _fake_tk(created, threads))
    ui = tray.UiThread()
    done = threading.Event()
    assert ui.call(lambda: ran.append(threading.current_thread().name))
    assert ui.call(lambda: (ran.append(threading.current_thread().name), done.set()))
    assert done.wait(3)
    ui.stop()
    assert len(created) == 1                      # exactly one Tk()
    assert set(ran) == {"hustleon-ui"} == set(threads)


def test_ui_thread_reports_missing_tkinter(tray, monkeypatch):
    monkeypatch.setitem(sys.modules, "tkinter", None)   # import raises
    ui = tray.UiThread()
    assert ui.call(lambda: None) is False


# 5.4 notify override guarded
def test_notify_override_installed_when_hooks_exist(tray):
    assert tray._can_override_notify() is True
    assert tray.TrayIcon._on_notify is tray._left_click_on_notify


def test_notify_override_skipped_without_hook(tray, monkeypatch):
    monkeypatch.delattr(pystray.Icon, "_on_notify")
    assert tray._can_override_notify() is False


# 5.5 Quit keeps resumable mode, Off clears it
def test_quit_preserves_last_mode_and_off_clears(tray, power):
    tray.act_on()
    assert tray.saved["last_mode"]["mode"] == "on"
    tray.act_quit()
    s = core.load_settings()
    assert s["last_mode"]["mode"] == "on"
    assert tray.engine.mode == "off" and power.values[("SUB_SLEEP", "STANDBYIDLE")][0] == "0x00000384"
    tray._quitting[0] = False
    # next launch resumes
    plan = core.resume_plan(s)
    e = core.Engine(enforce=False)
    assert e.resume_from_last(plan) and e.mode == "on"
    # explicit Off clears
    tray.act_on()
    tray.act_off()
    assert core.load_settings()["last_mode"] is None
    assert core.resume_plan(core.load_settings()) is None


def test_resume_plan_legacy_and_expired(tray):
    assert core.resume_plan({"mode": "on"}) == {"mode": "on", "until_iso": None,
                                                 "timer_minutes": None}
    assert core.resume_plan({"mode": "off"}) is None
    assert core.resume_plan({"mode": "on", "last_mode": None}) is None
    assert core.resume_plan({"last_mode": {"mode": "bogus"}}) is None


# 5.6 lid menu item
def _texts(menu):
    return [str(i.text) for i in menu.items if not getattr(i, "_text", None) == ""]


def test_menu_lid_item_by_status(tray):
    tray.lid_state = "unknown"
    assert any("Lid status unknown" in t for t in _texts(tray.build_menu()))
    tray.lid_state = "protected"
    assert not any("Lid" in t for t in _texts(tray.build_menu()))
    tray.lid_state = "unprotected"      # engine off: user's own setting, no warning
    assert not any("Lid" in t for t in _texts(tray.build_menu()))
    tray.engine.mode = "on"
    assert any("Lid close will still sleep this PC" in t for t in _texts(tray.build_menu()))
    tray.engine.mode = "off"


def test_open_power_settings_uri(tray, monkeypatch):
    opened = []
    monkeypatch.setattr(tray.os, "startfile", lambda u: opened.append(u), raising=False)
    tray.open_power_settings()
    assert opened == ["ms-settings:powersleep"]


def test_no_launch_time_lid_warning(tray):
    src = open(os.path.join(ROOT, "hustleon_tray.py"), encoding="utf-8").read()
    assert "warn_lid" not in src and "can't hold the lid yet" not in src


def test_unprotected_alert_only_while_live(tray, monkeypatch):
    sent = []
    monkeypatch.setattr(tray, "notify", lambda t, m: sent.append(m))
    tray.lid_state = "unprotected"
    tray.engine.mode = "off"
    tray.check_alerts()
    assert sent == []
    tray.engine.mode = "on"
    tray.check_alerts()
    tray.check_alerts()                 # once only
    assert len(sent) == 1
    tray.engine.mode = "off"


def test_unlock_remembers_choice_and_uses_runas(tray, monkeypatch):
    calls = []
    monkeypatch.setattr(tray.ctypes, "windll", types.SimpleNamespace(
        shell32=types.SimpleNamespace(
            ShellExecuteW=lambda *a: calls.append(a) or 42),
        user32=types.SimpleNamespace(MessageBoxW=lambda *a: 0)))
    tray.act_unlock_lid()
    assert calls[0][1] == "runas" and "--enforce-only" in calls[0][3]
    assert core.load_settings()["unhide_done"] is True


# 5.7 start with windows
def test_autostart_toggle_writes_hkcu_run(tray, monkeypatch):
    store = {}

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def create(hive, path, *a):
        assert hive == "HKCU" and path.endswith(r"CurrentVersion\Run")
        return Key()

    def opened(hive, path, *a):
        assert hive == "HKCU"
        return Key()

    def query(k, name):
        if name not in store:
            raise FileNotFoundError
        return store[name], 1

    def delete(k, name):
        if name not in store:
            raise FileNotFoundError
        del store[name]

    fake = types.SimpleNamespace(
        HKEY_CURRENT_USER="HKCU", HKEY_LOCAL_MACHINE="HKLM", KEY_SET_VALUE=2, KEY_READ=1,
        REG_SZ=1, CreateKeyEx=create, OpenKey=opened,
        SetValueEx=lambda k, n, r, t, v: store.__setitem__(n, v),
        QueryValueEx=query, DeleteValue=delete)
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(core, "autostart_enabled", _real_autostart_enabled)
    assert core.set_autostart(True) == (True, "")
    assert store["HustleOn"] == core.autostart_command()
    assert core.autostart_enabled() is True
    tray.act_autostart_toggle()            # on -> off
    assert "HustleOn" not in store
    assert core.set_autostart(False) == (True, "")   # idempotent when absent



def test_autostart_command_quotes_paths(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\HustleOn\hustle-on.exe")
    assert core.autostart_command() == '"C:\\Program Files\\HustleOn\\hustle-on.exe"'
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    cmd = core.autostart_command()
    assert cmd.startswith('"') and cmd.rstrip().endswith('hustleon_tray.py"')


def test_autostart_failure_reported(monkeypatch):
    # winreg stub from conftest has no attributes -> failure path, no real registry
    ok, detail = core.set_autostart(True)
    assert ok is False and detail


# 5.8 first run
def test_first_run_flag_default_and_persist(tray):
    assert core.load_settings()["first_run_done"] is False
    tray.saved["first_run_done"] = True
    tray.persist()
    assert core.load_settings()["first_run_done"] is True


# cli-flags-in-exe: dispatch before mutex / Tk
def test_cli_dispatch_none_without_args(tray):
    assert tray.run_cli_if_requested([]) is None


@pytest.mark.parametrize("flag", ["--version", "--check", "--enforce-only"])
def test_cli_dispatch_delegates_to_core(tray, monkeypatch, flag):
    calls = []
    monkeypatch.setattr(core, "main", lambda argv=None: calls.append(argv) or 0)
    monkeypatch.setattr(tray, "_attach_parent_console", lambda: True)
    monkeypatch.setattr(tray, "ensure_single_instance",
                        lambda: (_ for _ in ()).throw(AssertionError("mutex taken")))
    assert tray.run_cli_if_requested([flag]) == 0
    assert calls == [[flag]]


def test_main_exits_via_cli_before_mutex(tray, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["hustle-on.exe", "--version"])
    monkeypatch.setattr(core, "main", lambda argv=None: 0)
    monkeypatch.setattr(tray, "_attach_parent_console", lambda: True)
    monkeypatch.setattr(tray, "ensure_single_instance",
                        lambda: (_ for _ in ()).throw(AssertionError("mutex taken")))
    with pytest.raises(SystemExit) as ei:
        tray.main()
    assert ei.value.code == 0


def test_cli_dispatch_survives_no_console_and_systemexit(tray, monkeypatch):
    monkeypatch.setattr(tray, "_attach_parent_console", lambda: False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(core, "main", lambda argv=None: (_ for _ in ()).throw(SystemExit(2)))
    assert tray.run_cli_if_requested(["--bogus"]) == 2


def test_attach_console_falls_back_when_no_parent(tray, monkeypatch):
    class K32:
        def AttachConsole(self, pid):
            return 0
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: K32())
    assert tray._attach_parent_console() is False


def test_version_info_generation():
    import make_version_info as m
    out = m.version_info_text("1.2.0")
    assert "filevers=(1, 2, 0, 0)" in out and "StringStruct('FileVersion', '1.2.0')" in out
    assert "StringStruct('ProductName', 'HustleOn')" in out
