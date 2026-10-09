"""hustle-on core engine: execution-state hold, powercfg apply/restore, battery, modes, settings.

Shared by the CLI (hustleon.py) and the tray app (hustleon_tray.py).
No third-party dependencies - stdlib + ctypes only.

Power settings (lid / sleep / hibernate / display) are changed ONLY while a
hold is live and are restored whenever the hold ends (see begin_hold/end_hold).
"""

__version__ = "1.1.0"
import argparse
import ctypes
import datetime
import json
import logging
import logging.handlers
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_AWAYMODE_REQUIRED = 0x00000040

SUB_BUTTONS = "SUB_BUTTONS"
LIDACTION = "LIDACTION"
SUB_SLEEP = "SUB_SLEEP"
STANDBYIDLE = "STANDBYIDLE"
HIBERNATEIDLE = "HIBERNATEIDLE"
SUB_VIDEO = "SUB_VIDEO"
VIDEOIDLE = "VIDEOIDLE"
LIDACTION_GUID = "5ca83367-6e45-459f-a27b-476b1d01c936"
SUB_BUTTONS_GUID = "4f971e89-eebd-4455-a8de-9e59040e7347"

MODE_OFF, MODE_ON, MODE_TIMER, MODE_UNTIL = "off", "on", "timer", "until"
HEARTBEAT_SECONDS = 30
ENFORCED_VALUE = "0x00000000"

# (key, subgroup alias, setting alias): everything a hold changes.
POWER_SETTINGS = (("lid", SUB_BUTTONS, LIDACTION),
                  ("sleep", SUB_SLEEP, STANDBYIDLE),
                  ("hibernate", SUB_SLEEP, HIBERNATEIDLE),
                  ("display", SUB_VIDEO, VIDEOIDLE))

DEFAULTS = {
    "mode": MODE_OFF,
    "timer_minutes": 60,
    "until_iso": None,          # absolute local-time deadline
    "screen_on": True,
    "battery_guard": True,
    "battery_threshold": 30,
    "start_with_windows": False,
    "thermal_guard": False,     # opt-in, best effort
    "thermal_threshold": 90,    # deg C
    "first_run_done": False,
    "unhide_done": False,
}


# ---------- storage + logging ----------

def data_dir():
    """%APPDATA%\\hustle-on (created on demand)."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "hustle-on")
    os.makedirs(d, exist_ok=True)
    return d


def _legacy_dir():
    """Where pre-1.1 builds kept settings.json (next to the exe/script)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def atomic_write_json(path, obj):
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


_log_state = {"dir": None}


def get_logger():
    """Rotating file log in %APPDATA%\\hustle-on\\log.txt (256 KB x 2)."""
    lg = logging.getLogger("hustleon")
    try:
        d = data_dir()
        if _log_state["dir"] != d:
            for h in list(lg.handlers):
                lg.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass
            h = logging.handlers.RotatingFileHandler(
                os.path.join(d, "log.txt"), maxBytes=256 * 1024, backupCount=2,
                encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            lg.addHandler(h)
            lg.setLevel(logging.INFO)
            lg.propagate = False
            _log_state["dir"] = d
    except Exception:
        if not lg.handlers:
            lg.addHandler(logging.NullHandler())
    return lg


def log(msg, level=logging.INFO):
    try:
        get_logger().log(level, msg)
    except Exception:
        pass


# ---------- low-level ----------

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def set_execution_state(flags):
    """Returns (ret, ok). A 0 return with error 0 is SUCCESS (previous state
    was 0) - the classic Win32 pitfall is testing `ret != 0` alone."""
    try:
        ctypes.set_last_error(0)
        ret = _kernel32.SetThreadExecutionState(flags)
        return ret, (ret != 0 or ctypes.get_last_error() == 0)
    except Exception:
        return 0, False


def hold_flags(screen_on):
    f = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
    if screen_on:
        f |= ES_DISPLAY_REQUIRED
    return f


class PowerController:
    """Single daemon thread that owns every SetThreadExecutionState call.

    The Win32 state is per-thread, so a hold set on a menu thread can be lost
    or overwritten from the heartbeat thread. All callers post commands here.
    """

    def __init__(self):
        self._q = queue.Queue()
        self._thread = None
        self._guard = threading.Lock()
        self._flags = None

    def _ensure(self):
        with self._guard:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="hustleon-power",
                                                daemon=True)
                self._thread.start()

    def _run(self):
        while True:
            cmd, flags, box, ev = self._q.get()
            try:
                if cmd == "stop":
                    box.append(True)
                    ev.set()
                    return
                if cmd == "release":
                    ok = set_execution_state(ES_CONTINUOUS)[1]
                else:
                    ok = set_execution_state(flags)[1]
                box.append(ok)
            except Exception:
                box.append(False)
            ev.set()

    def _submit(self, cmd, flags=None, timeout=10):
        self._ensure()
        box, ev = [], threading.Event()
        self._q.put((cmd, flags, box, ev))
        if not ev.wait(timeout):
            return False
        return bool(box and box[0])

    def hold(self, flags):
        self._flags = flags
        return self._submit("hold", flags)

    def reassert(self, flags=None):
        if flags is not None:
            self._flags = flags
        if self._flags is None:
            return False
        return self._submit("reassert", self._flags)

    def release(self):
        self._flags = None
        return self._submit("release")

    def stop(self):
        if self._thread is not None and self._thread.is_alive():
            self._submit("stop", timeout=2)


_controller = None


def get_controller():
    global _controller
    if _controller is None:
        _controller = PowerController()
    return _controller


def run_powercfg(args):
    try:
        r = subprocess.run(["powercfg"] + args, capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def unhide_lid_setting():
    """One-time Modern Standby fix: makes the lid setting visible to powercfg.
    Needs Administrator (HKLM write)."""
    import winreg
    key = rf"SYSTEM\CurrentControlSet\Control\Power\PowerSettings\{SUB_BUTTONS_GUID}\{LIDACTION_GUID}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "Attributes", 0, winreg.REG_DWORD, 2)
            return True, "lid unhidden via registry"
    except PermissionError:
        return False, "registry needs Administrator"
    except FileNotFoundError:
        return False, "lid GUID not present in registry"
    except Exception as e:
        return False, str(e)


def _query_index(sub, setting):
    """Current AC/DC power-setting index via aliases; None when hidden/unknown."""
    try:
        r = subprocess.run(["powercfg", "/query", "SCHEME_CURRENT", sub, setting],
                           capture_output=True, text=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ac = dc = None
        for line in (r.stdout or "").splitlines():
            s = line.strip()
            if s.startswith("Current AC Power Setting Index:"):
                ac = s.split(":")[1].strip()
            elif s.startswith("Current DC Power Setting Index:"):
                dc = s.split(":")[1].strip()
        if ac is None and dc is None:
            return None
        return ac, dc
    except Exception:
        return None


def _fmt_secs(idx):
    if idx is None:
        return "?"
    try:
        v = int(idx, 16)
    except ValueError:
        return idx
    if v == 0:
        return "Never"
    m, s = divmod(v, 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m" if h else (f"{m}m" if m else f"{s}s")


def _fmt_action(idx):
    return {"0x00000000": "Do nothing", "0x00000001": "Sleep",
            "0x00000002": "Hibernate", "0x00000003": "Shut down"}.get(
                (idx or "").lower(), idx if idx else "?")


def _snapshot_current():
    return {key: _query_index(sub, setting) for key, sub, setting in POWER_SETTINGS}


def _active_scheme():
    ok, out = run_powercfg(["/getactivescheme"])
    m = re.search(r"([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})", out or "") if ok else None
    return m.group(1).lower() if m else None


def lid_status():
    """'protected' | 'unprotected' | 'unknown' from a power-setting read-back."""
    v = _query_index(SUB_BUTTONS, LIDACTION)
    if v is None or v[0] is None or v[1] is None:
        return "unknown"
    if all(x.lower() == ENFORCED_VALUE for x in v):
        return "protected"
    return "unprotected"


# ---------- apply-while-live / restore ----------

def applied_path():
    return os.path.join(data_dir(), "applied.json")


def load_marker():
    try:
        with open(applied_path(), encoding="utf-8") as f:
            m = json.load(f)
        if isinstance(m, dict) and isinstance(m.get("snapshot"), dict):
            return m
    except Exception:
        pass
    return None


def _clear_marker():
    try:
        os.remove(applied_path())
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"could not remove applied marker: {e}", logging.WARNING)


def _restore_snapshot(snap, scheme):
    """Write snapshot values back. Missing/unreadable values are skipped (ok).
    Returns [(desc, ok, detail)]."""
    results = []
    target = scheme or "SCHEME_CURRENT"
    for key, sub, setting in POWER_SETTINGS:
        vals = snap.get(key) if isinstance(snap, dict) else None
        if not vals or vals[0] is None or vals[1] is None:
            results.append((f"{key}: no snapshot value, skipped", True, "unknown"))
            continue
        try:
            ac, dc = str(int(vals[0], 16)), str(int(vals[1], 16))
        except (ValueError, TypeError):
            results.append((f"{key}: snapshot unreadable, skipped", True, str(vals)))
            continue
        ok1, d1 = run_powercfg(["/setacvalueindex", target, sub, setting, ac])
        ok2, d2 = run_powercfg(["/setdcvalueindex", target, sub, setting, dc])
        results.append((f"{key} restored to {ac}/{dc} (AC/DC)", ok1 and ok2, (d1 + d2)[:200]))
    # Re-activate only if that scheme is still the active one; never switch
    # the user's plan back behind their back.
    if scheme is None or _active_scheme() == scheme:
        ok, d = run_powercfg(["/setactive", target])
        results.append(("scheme re-activated", ok, d))
    return results


def begin_hold():
    """Snapshot the user's values, persist the applied marker, then apply
    lid=Do Nothing / sleep, hibernate, display=Never. Returns [(desc, ok, detail)]."""
    results = []
    snap = scheme = None
    marker = load_marker()
    if marker:
        # A previous hold never ended (crash / power loss). Our own enforced
        # values must never be recorded as the user's defaults.
        log("stale applied marker found at hold start; restoring first", logging.WARNING)
        r = _restore_snapshot(marker["snapshot"], marker.get("scheme"))
        results += [("stale: " + d, ok, x) for d, ok, x in r]
        if all(ok for _, ok, _ in r):
            _clear_marker()
        else:
            snap, scheme = marker["snapshot"], marker.get("scheme")
    if snap is None:
        snap, scheme = _snapshot_current(), _active_scheme()
    try:
        atomic_write_json(applied_path(), {"applied": True, "scheme": scheme, "snapshot": snap,
                                           "ts": datetime.datetime.now().isoformat()})
    except Exception as e:
        results.append(("write applied marker", False, str(e)))
    target = scheme or "SCHEME_CURRENT"
    for key, sub, setting in POWER_SETTINGS:
        label = {"lid": "lid = Do Nothing", "sleep": "sleep = Never",
                 "hibernate": "hibernate = Never", "display": "display = Never"}[key]
        for scope, flag in (("AC", "/setacvalueindex"), ("DC", "/setdcvalueindex")):
            ok, d = run_powercfg([flag, target, sub, setting, "0"])
            results.append((f"{scope} {label}", ok, d))
    ok, d = run_powercfg(["/setactive", target])
    results.append(("scheme re-activated", ok, d))
    st = lid_status()
    results.append((f"lid status after apply: {st}", st != "unprotected", ""))
    log(f"hold applied (lid {st}); failures: "
        f"{[x for x in results if not x[1]] or 'none'}")
    return results


def end_hold(reason="off"):
    """Restore the snapshot and clear the marker. Retries once.
    Returns (results, ok). No marker -> ([], True)."""
    marker = load_marker()
    if not marker:
        return [], True
    snap, scheme = marker["snapshot"], marker.get("scheme")
    results = _restore_snapshot(snap, scheme)
    if not all(ok for _, ok, _ in results):
        log(f"restore ({reason}) failed once, retrying: {results}", logging.WARNING)
        results = _restore_snapshot(snap, scheme)
    ok = all(ok for _, ok, _ in results)
    if ok:
        _clear_marker()
        log(f"hold ended ({reason}); power settings restored")
    else:
        log(f"hold ended ({reason}); RESTORE FAILED, marker kept for next launch: {results}",
            logging.ERROR)
    return results, ok


def recover_applied():
    """Launch-time crash recovery: restore a leftover marker. Returns (results, ok)."""
    if load_marker():
        log("crash recovery: leftover applied marker", logging.WARNING)
    return end_hold("recovery")


def restore_power_defaults():
    """Manual 'Restore sleep defaults'. Uses the applied marker's snapshot."""
    if not load_marker():
        return [("no saved snapshot - nothing to restore (no hold applied settings)", False, "")]
    results, _ = end_hold("manual")
    return results


def legacy_restore_candidate():
    """Pre-1.1 builds left defaults_backup.json (untrusted: may hold already
    enforced values). Returns the snapshot only if not all values are enforced."""
    try:
        with open(os.path.join(data_dir(), "defaults_backup.json"), encoding="utf-8") as f:
            snap = json.load(f)
    except Exception:
        return None
    vals = [v for v in snap.values() if isinstance(v, list) and len(v) == 2 and None not in v] \
        if isinstance(snap, dict) else []
    if not vals or all(all(str(x).lower() == ENFORCED_VALUE for x in v) for v in vals):
        return None
    return snap


def restore_legacy_backup():
    snap = legacy_restore_candidate()
    if snap is None:
        return [("no usable legacy backup", False, "")]
    results = _restore_snapshot(snap, None)
    if all(ok for _, ok, _ in results):
        try:
            os.remove(os.path.join(data_dir(), "defaults_backup.json"))
        except Exception:
            pass
    return results


def enforce_unhide_only():
    """--enforce-only: one-time registry unhide. Returns [(desc, ok, detail)]."""
    ok, d = unhide_lid_setting()
    return [("unhide lid setting (Modern Standby fix)", ok, d)]


def power_summary():
    """Short human summary for the About dialog. Never raises."""
    try:
        sleep = _query_index(SUB_SLEEP, STANDBYIDLE)
        hib = _query_index(SUB_SLEEP, HIBERNATEIDLE)
        disp = _query_index(SUB_VIDEO, VIDEOIDLE)
        lid = _query_index(SUB_BUTTONS, LIDACTION)
        return {
            "sleep": f"{_fmt_secs(sleep[0] if sleep else None)} / {_fmt_secs(sleep[1] if sleep else None)} (AC/DC)" if sleep else "?",
            "hibernate": f"{_fmt_secs(hib[0] if hib else None)} / {_fmt_secs(hib[1] if hib else None)} (AC/DC)" if hib else "?",
            "display": f"{_fmt_secs(disp[0] if disp else None)} / {_fmt_secs(disp[1] if disp else None)} (AC/DC)" if disp else "?",
            "lid": f"{_fmt_action(lid[0] if lid else None)} / {_fmt_action(lid[1] if lid else None)} (AC/DC)" if lid else "hidden (Modern Standby - set in Windows Settings)",
        }
    except Exception:
        return {k: "?" for k in ("sleep", "hibernate", "display", "lid")}


def check_settings_text():
    lines = []
    try:
        r = subprocess.run(["powercfg", "/query", "SCHEME_CURRENT"],
                           capture_output=True, text=True, timeout=15)
        out = r.stdout or ""
        for line in out.splitlines():
            s = line.strip()
            if s.startswith("Power Scheme GUID"):
                lines.append(s)
        buf = []
        for line in out.splitlines():
            if "Subgroup GUID" in line or "Power Setting GUID" in line or "Friendly Name" in line \
               or "Current AC" in line or "Current DC" in line or "Alias" in line:
                buf.append(line.rstrip())
                if "Current DC" in line:
                    block = "\n".join(buf)
                    if any(k in block for k in ("Sleep", "Hibernate", "SUB_SLEEP", "SUB_BUTTONS",
                                                "SUB_VIDEO", "STANDBY", "HIBER", "VIDEO", "BUTTON")):
                        lines.append(block)
                    buf = []
        if "LIDACTION" not in out:
            lines.append("NOTE: no lid action in this scheme (Modern Standby). "
                         "Set Settings > System > Power & battery > Lid controls > Do Nothing.")
    except Exception as e:
        lines.append(f"query failed: {e}")
    return "\n---\n".join(lines)


# ---------- lid switch + suspend + thermal (best effort) ----------

_lid = {"closed": None}   # None = unknown
GUID_LIDSWITCH_STATE_CHANGE = "ba3e0f4d-b817-4094-a2d1-d56379e6a0f3"


def get_lid_state():
    """True = closed, False = open, None = unknown (watcher not running/unsupported)."""
    return _lid["closed"]


def start_lid_watcher():
    """Message-only window listening for GUID_LIDSWITCH_STATE_CHANGE. Best effort:
    on any failure the lid state simply stays unknown."""
    t = threading.Thread(target=_lid_watcher, name="hustleon-lid", daemon=True)
    t.start()
    return t


def _lid_watcher():
    try:
        import ctypes.wintypes as wt
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class GUID(ctypes.Structure):
            _fields_ = [("D1", ctypes.c_uint32), ("D2", ctypes.c_uint16),
                        ("D3", ctypes.c_uint16), ("D4", ctypes.c_ubyte * 8)]

        def mkguid(s):
            import uuid
            u = uuid.UUID(s)
            g = GUID()
            g.D1, g.D2, g.D3 = u.time_low, u.time_mid, u.time_hi_version
            for i, b in enumerate(u.bytes[8:]):
                g.D4[i] = b
            return g

        class PBS(ctypes.Structure):
            _fields_ = [("PowerSetting", GUID), ("DataLength", wt.DWORD),
                        ("Data", ctypes.c_ubyte * 1)]

        lid_guid = mkguid(GUID_LIDSWITCH_STATE_CHANGE)
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
        user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.DefWindowProcW.restype = LRESULT

        def proc(hwnd, msg, wparam, lparam):
            if msg == 0x218 and wparam == 0x8013:  # WM_POWERBROADCAST / PBT_POWERSETTINGCHANGE
                ps = ctypes.cast(lparam, ctypes.POINTER(PBS)).contents
                if ps.PowerSetting.D1 == lid_guid.D1 and bytes(ps.PowerSetting.D4) == bytes(lid_guid.D4) \
                        and ps.DataLength >= 1:
                    _lid["closed"] = (ps.Data[0] == 0)
                    log(f"lid {'closed' if _lid['closed'] else 'opened'}")
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        cb = WNDPROC(proc)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE),
                        ("hIcon", wt.HANDLE), ("hCursor", wt.HANDLE), ("hbrBackground", wt.HANDLE),
                        ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]

        k32.GetModuleHandleW.restype = wt.HINSTANCE
        hinst = k32.GetModuleHandleW(None)
        wc = WNDCLASS()
        wc.lpfnWndProc = cb
        wc.hInstance = hinst
        wc.lpszClassName = "HustleOnLidWatcher"
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
        user32.RegisterClassW(ctypes.byref(wc))
        user32.CreateWindowExW.restype = wt.HWND
        user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND,
                                           wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        hwnd = user32.CreateWindowExW(0, "HustleOnLidWatcher", "HustleOnLidWatcher", 0, 0, 0, 0, 0,
                                      wt.HWND(-3), None, hinst, None)  # HWND_MESSAGE
        if not hwnd:
            return
        user32.RegisterPowerSettingNotification.argtypes = [wt.HANDLE, ctypes.POINTER(GUID), wt.DWORD]
        user32.RegisterPowerSettingNotification.restype = wt.HANDLE
        if not user32.RegisterPowerSettingNotification(hwnd, ctypes.byref(lid_guid), 0):
            return
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    except Exception as e:
        log(f"lid watcher unavailable: {e}", logging.WARNING)


def request_suspend():
    """Hibernate, falling back to sleep. Returns True if a request was accepted."""
    try:
        pp = ctypes.WinDLL("powrprof")
        for hib in (True, False):
            if pp.SetSuspendState(hib, False, False):
                return True
    except Exception as e:
        log(f"suspend request failed: {e}", logging.WARNING)
    return False


def read_temperature_c():
    """Hottest ACPI thermal zone in deg C, or None when no sensor is readable."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
             "| ForEach-Object { $_.CurrentTemperature }"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        vals = [float(x) / 10.0 - 273.15 for x in (r.stdout or "").split() if x.strip().isdigit()]
        return max(vals) if vals else None
    except Exception:
        return None


# ---------- autostart (HKCU Run) ----------

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "HustleOn"


def autostart_command():
    if getattr(sys, "frozen", False):
        return f'"{os.path.abspath(sys.executable)}"'
    pyw = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = os.path.abspath(sys.executable)
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hustleon_tray.py")
    return f'"{pyw}" "{script}"'


def autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except Exception:
        return False


def set_autostart(enable):
    """Returns (ok, detail)."""
    try:
        import winreg
        if enable:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass
        log(f"start with Windows {'enabled' if enable else 'disabled'}")
        return True, ""
    except Exception as e:
        log(f"autostart change failed: {e}", logging.WARNING)
        return False, str(e)


# ---------- battery (ctypes, no deps) ----------

class _SPS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte),
                ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong)]


def get_power_status():
    """Returns (on_ac: bool|None, percent: int|None). None = unknown."""
    try:
        s = _SPS()
        if not _kernel32.GetSystemPowerStatus(ctypes.byref(s)):
            return None, None
        ac = {0: False, 1: True}.get(int(s.ACLineStatus), None)
        pct = int(s.BatteryLifePercent)
        pct = None if pct > 100 else pct
        return ac, pct
    except Exception:
        return None, None


# ---------- settings persistence ----------

def settings_path():
    return os.path.join(data_dir(), "settings.json")


def load_settings():
    s = dict(DEFAULTS)
    path = settings_path()
    if not os.path.exists(path):
        legacy = os.path.join(_legacy_dir(), "settings.json")
        if os.path.isfile(legacy):  # one-time migration of a next-to-exe file
            try:
                shutil.copy2(legacy, path)
                log(f"migrated settings from {legacy}")
            except Exception as e:
                log(f"settings migration failed: {e}", logging.WARNING)
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError("settings root is not an object")
        s.update(loaded)
    except FileNotFoundError:
        pass
    except Exception as e:
        try:
            bak = f"{path}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
            os.replace(path, bak)
            log(f"settings unreadable ({e}); moved to {bak}", logging.WARNING)
        except Exception:
            pass
    if s.get("mode") not in (MODE_OFF, MODE_ON, MODE_TIMER, MODE_UNTIL):
        s["mode"] = MODE_OFF
    return s


def resume_plan(saved):
    """Resumable mode dict from settings: `last_mode`, else (pre-1.1 files) the
    saved live `mode`. Explicit Off / expiry leave neither -> None."""
    last = saved.get("last_mode")
    if isinstance(last, dict) and last.get("mode") in (MODE_ON, MODE_TIMER, MODE_UNTIL):
        return last
    if "last_mode" not in saved and saved.get("mode") in (MODE_ON, MODE_TIMER, MODE_UNTIL):
        return {"mode": saved["mode"], "until_iso": saved.get("until_iso"),
                "timer_minutes": saved.get("timer_minutes")}
    return None


def save_settings(s):
    try:
        atomic_write_json(settings_path(), s)
        return True
    except Exception as e:
        log(f"settings save failed: {e}", logging.WARNING)
        return False


# ---------- mode engine ----------

class Engine:
    def __init__(self, screen_on=True, guard=True, guard_threshold=30, enforce=True,
                 thermal_guard=False, thermal_threshold=90, controller=None,
                 lid_state_fn=None, suspend_fn=None, thermal_fn=None):
        self._lock = threading.RLock()
        self.screen_on = screen_on
        self.guard = guard
        self.guard_threshold = guard_threshold
        self.enforce = enforce
        self.thermal_guard = thermal_guard
        self.thermal_threshold = thermal_threshold
        self.thermal_available = None   # None = not tried yet
        self._controller = controller
        self._lid_state_fn = lid_state_fn
        self._suspend_fn = suspend_fn
        self._thermal_fn = thermal_fn
        self.mode = MODE_OFF
        self.timer_minutes = 60
        self.deadline = None  # datetime for timer/until
        self.battery_paused = False
        self.paused_snapshot = None  # (mode, deadline, timer_minutes) saved at auto-pause
        self.api_ok = True  # False when Windows refused the last hold request
        self.last_reassert = None  # datetime of last successful hold assertion
        self.applied = False       # power settings currently applied by us
        self.restore_ok = True     # False when the last restore failed
        self.lid_status = "unknown"
        self.apply_results = []

    # -- helpers
    def _ctl(self):
        return self._controller or get_controller()

    def _lid_closed(self):
        return (self._lid_state_fn or get_lid_state)()

    def _suspend(self):
        return (self._suspend_fn or request_suspend)()

    def _assert(self, first=False):
        flags = hold_flags(self.screen_on)
        ctl = self._ctl()
        ok = ctl.hold(flags) if first else ctl.reassert(flags)
        self.api_ok = ok
        if ok:
            self.last_reassert = datetime.datetime.now()

    def _begin(self, mode, deadline):
        self.mode = mode
        self.deadline = deadline
        self.battery_paused = False
        if mode == MODE_OFF:
            return
        self._assert(first=True)
        if self.enforce and not self.applied:
            self.apply_results = begin_hold()
            self.applied = True
            self.lid_status = lid_status()
            self.restore_ok = True

    def _finish(self, reason):
        """Release the hold and restore power settings (idempotent)."""
        self.mode = MODE_OFF
        self.deadline = None
        self._ctl().release()
        if self.applied:
            _, ok = end_hold(reason)
            self.restore_ok = ok
            self.applied = False

    # -- public API
    def activate(self, mode, minutes=None, until=None):
        with self._lock:
            now = datetime.datetime.now()
            if mode == MODE_TIMER:
                self.timer_minutes = minutes or 60
                deadline = now + datetime.timedelta(minutes=self.timer_minutes)
            elif mode == MODE_UNTIL:
                deadline = until
            else:
                deadline = None
            if mode == MODE_OFF:
                self._finish("off")
                self.battery_paused = False
                return
            self._begin(mode, deadline)

    def deactivate(self, reason="off"):
        with self._lock:
            self._finish(reason)

    def reassert(self):
        with self._lock:
            if self.mode != MODE_OFF:
                self._assert()

    def snapshot_mode(self):
        """Resumable description of the live mode, or None when off."""
        with self._lock:
            if self.mode == MODE_OFF:
                return None
            return {"mode": self.mode,
                    "until_iso": self.deadline.isoformat() if self.deadline else None,
                    "timer_minutes": self.timer_minutes}

    def resume_from_last(self, last):
        """Re-arm a persisted {"mode","until_iso","timer_minutes"}. Returns True if live."""
        if not isinstance(last, dict):
            return False
        mode = last.get("mode")
        with self._lock:
            if mode == MODE_ON:
                self.activate(MODE_ON)
                return True
            if mode in (MODE_TIMER, MODE_UNTIL):
                try:
                    dl = datetime.datetime.fromisoformat(last["until_iso"])
                except Exception:
                    return False
                if dl > datetime.datetime.now():
                    self.timer_minutes = last.get("timer_minutes") or 60
                    self._begin(mode, dl)
                    return True
        return False

    def resume_snapshot(self):
        """Re-arm whatever was live at auto-pause. Expired -> stays off."""
        with self._lock:
            snap = self.paused_snapshot
            self.paused_snapshot = None
            self.battery_paused = False
            if not snap:
                return
            mode, deadline, minutes = snap
            if mode == MODE_ON:
                self.activate(MODE_ON)
            elif mode in (MODE_TIMER, MODE_UNTIL) and deadline \
                    and deadline > datetime.datetime.now():
                self.timer_minutes = minutes or self.timer_minutes
                self._begin(mode, deadline)  # remaining time, not a fresh N minutes

    def remaining(self, now=None):
        with self._lock:
            if self.mode in (MODE_TIMER, MODE_UNTIL) and self.deadline:
                return self.deadline - (now or datetime.datetime.now())
        return None

    def tick(self):
        """Returns list of events: 'expired', 'battery_pause', 'thermal',
        'sleeping'. Call ~every 30s."""
        events = []
        with self._lock:
            now = datetime.datetime.now()
            if self.mode in (MODE_TIMER, MODE_UNTIL) and self.deadline and now >= self.deadline:
                self._finish("expired")
                return ["expired"]
            if self.guard and self.mode != MODE_OFF:
                ac, pct = get_power_status()
                if ac is False and pct is not None and pct <= self.guard_threshold:
                    self.paused_snapshot = (self.mode, self.deadline, self.timer_minutes)
                    lid_closed = self._lid_closed() is True
                    self._finish("battery")
                    self.battery_paused = True
                    events.append("battery_pause")
                    if lid_closed and self._suspend():
                        events.append("sleeping")
                    return events
            if self.thermal_guard and self.mode != MODE_OFF and self._lid_closed() is True:
                temp = (self._thermal_fn or read_temperature_c)()
                self.thermal_available = temp is not None
                if temp is not None and temp >= self.thermal_threshold:
                    log(f"thermal guard tripped at {temp:.0f}C", logging.WARNING)
                    self._finish("thermal")
                    events.append("thermal")
                    if self._suspend():
                        events.append("sleeping")
                    return events
            self.reassert()
        return events


# ---------- CLI ----------

def _parse_until(s):
    """'HH:MM' today, or tomorrow if passed. Returns datetime."""
    h, m = s.split(":")
    now = datetime.datetime.now()
    dt = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    if dt <= now:
        dt += datetime.timedelta(days=1)
    return dt


def main(argv=None):
    ap = argparse.ArgumentParser(description="hustle-on: keep Windows awake with lid closed.")
    ap.add_argument("--screen-off", action="store_true")
    ap.add_argument("--screen-on", action="store_true")
    ap.add_argument("--no-enforce", action="store_true",
                    help="hold awake without touching lid/sleep power settings")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--enforce-only", action="store_true",
                    help="one-time elevated Modern Standby lid unhide, then exit")
    ap.add_argument("--on", action="store_true")
    ap.add_argument("--off", action="store_true")
    ap.add_argument("--timer", type=int, metavar="MINUTES")
    ap.add_argument("--until", metavar="HH:MM")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)

    # Validate BEFORE touching any machine config.
    if args.timer is not None and args.timer <= 0:
        print("--timer needs a positive number of minutes.", file=sys.stderr)
        return 2
    until_dt = None
    if args.until:
        try:
            until_dt = _parse_until(args.until)
        except Exception:
            print("--until needs HH:MM (24h).", file=sys.stderr)
            return 2

    if args.check:
        print(check_settings_text())
        return 0
    if sys.platform != "win32":
        print("Windows only.", file=sys.stderr)
        return 1

    if args.enforce_only:
        for desc, ok, d in enforce_unhide_only():
            print(f"[{'OK' if ok else 'FAIL'}] {desc}" + ("" if ok else f" :: {d[:200]}"))
        return 0

    if args.off:
        set_execution_state(ES_CONTINUOUS)
        print("Hold released (off).")
        return 0

    screen_on = not args.screen_off if (args.screen_off or args.screen_on) else True
    enforce = not args.no_enforce
    if enforce:
        # A previous run that died mid-hold left settings applied: undo that first.
        _, rec_ok = recover_applied()
        if not rec_ok:
            print("  [FAIL] could not restore earlier power settings", file=sys.stderr)
    start_lid_watcher()
    eng = Engine(screen_on=screen_on, enforce=enforce)
    try:
        if args.timer:
            eng.activate(MODE_TIMER, minutes=args.timer)
            print(f"Holding for {args.timer} min (until {eng.deadline:%H:%M}). Ctrl+C to stop.")
        elif args.until:
            eng.activate(MODE_UNTIL, until=until_dt)
            print(f"Holding until {eng.deadline:%Y-%m-%d %H:%M}. Ctrl+C to stop.")
        else:
            eng.activate(MODE_ON)
            print(f"Holding indefinitely (0x{hold_flags(screen_on):08X}). Ctrl+C to stop.")
        for desc, ok, d in eng.apply_results:
            print(f"  [{'OK' if ok else 'FAIL'}] {desc}" + ("" if ok else f" :: {d[:160]}"))
        while True:
            time.sleep(HEARTBEAT_SECONDS)
            ev = eng.tick()
            if "expired" in ev:
                print("Deadline reached - hold released, power settings restored.")
                return 0
            if "battery_pause" in ev:
                print("Battery low - hold released, power settings restored.")
                return 0
            if "thermal" in ev:
                print("Too hot - hold released, power settings restored.")
                return 0
            rem = eng.remaining()
            extra = f" ({rem} left)" if rem else ""
            print(f"  heartbeat: {eng.mode}{extra} {time.strftime('%H:%M:%S')}", flush=True)
    except KeyboardInterrupt:
        print("\nRestored normal sleep.")
        return 0
    finally:
        eng.deactivate("cli-exit")   # idempotent: releases hold + restores settings


if __name__ == "__main__":
    raise SystemExit(main())
