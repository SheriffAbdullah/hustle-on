"""hustle-on core engine: execution-state hold, powercfg enforce, battery, modes, settings.

Shared by the CLI (hustleon.py) and the tray app (hustleon_tray.py).
No third-party dependencies — stdlib + ctypes only.
"""

__version__ = "1.0.0"
import argparse
import ctypes
import datetime
import json
import os
import subprocess
import sys
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

DEFAULTS = {
    "mode": MODE_OFF,
    "timer_minutes": 60,
    "until_iso": None,          # absolute local-time deadline
    "screen_on": True,
    "battery_guard": True,
    "battery_threshold": 30,
}


# ---------- low-level ----------

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def set_execution_state(flags):
    """Returns (ret, ok). A 0 return with error 0 is SUCCESS (previous state
    was 0) — the classic Win32 pitfall is testing `ret != 0` alone."""
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


def run_powercfg(args):
    try:
        r = subprocess.run(["powercfg"] + args, capture_output=True, text=True, timeout=15)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def unhide_lid_setting():
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


def enforce_power_settings():
    # First run snapshots current values so restore_power_defaults() can undo us.
    results = []
    try:
        bp = _backup_path()
        if not os.path.exists(bp):
            with open(bp, "w") as f:
                json.dump(_snapshot_current(), f, indent=2)
            results.append(("saved current settings snapshot (for Restore)", True, bp))
    except Exception as e:
        results.append(("saved current settings snapshot (for Restore)", False, str(e)))
    lid_ok = True
    for scope, flag in (("AC lid", "/setacvalueindex"), ("DC lid", "/setdcvalueindex")):
        ok, detail = run_powercfg([flag, "SCHEME_CURRENT", SUB_BUTTONS, LIDACTION, "0"])
        if not ok and ("Invalid Parameters" in detail or "not supported" in detail.lower()):
            lid_ok = False
        results.append((scope + " = Do Nothing", ok, detail))
    if not lid_ok:
        ok, detail = unhide_lid_setting()
        results.append(("unhide lid setting (Modern Standby fix)", ok, detail))
        if ok:
            for scope, flag in (("AC lid retry", "/setacvalueindex"), ("DC lid retry", "/setdcvalueindex")):
                ok2, d2 = run_powercfg([flag, "SCHEME_CURRENT", SUB_BUTTONS, LIDACTION, "0"])
                results.append((scope + " = Do Nothing", ok2, d2))
    for scope, flag in (("AC sleep", "/setacvalueindex"), ("DC sleep", "/setdcvalueindex")):
        ok, d = run_powercfg([flag, "SCHEME_CURRENT", SUB_SLEEP, STANDBYIDLE, "0"])
        results.append((scope + " = Never", ok, d))
    for scope, flag in (("AC hibernate", "/setacvalueindex"), ("DC hibernate", "/setdcvalueindex")):
        ok, d = run_powercfg([flag, "SCHEME_CURRENT", SUB_SLEEP, HIBERNATEIDLE, "0"])
        results.append((scope + " = Never", ok, d))
    for scope, flag in (("AC display", "/setacvalueindex"), ("DC display", "/setdcvalueindex")):
        ok, d = run_powercfg([flag, "SCHEME_CURRENT", SUB_VIDEO, VIDEOIDLE, "0"])
        results.append((scope + " = Never", ok, d))
    ok, d = run_powercfg(["/setactive", "SCHEME_CURRENT"])
    results.append(("scheme re-activated", ok, d))
    # Read-back: "OK" from powercfg can be a silent no-op on schemes that hide
    # the setting (Modern Standby). Verify the load-bearing lid value.
    v = _query_index(SUB_BUTTONS, LIDACTION)
    if v and all((x or "").lower() == "0x00000000" for x in v):
        results.append(("lid verified: Do Nothing on AC+DC (read-back OK)", True, ""))
    elif v is None:
        results.append(("lid NOT verifiable on this scheme — see About HustleOn", True,
                        "setting hidden; confirm in Windows Settings"))
    else:
        results.append((f"lid read-back mismatch {v} — see About HustleOn", False,
                        "verify failed"))
    return results


def _query_index(sub, setting):
    """Current AC/DC power-setting index via aliases; None when hidden/unknown."""
    try:
        r = subprocess.run(["powercfg", "/query", "SCHEME_CURRENT", sub, setting],
                           capture_output=True, text=True, timeout=10)
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


def _backup_path():
    return os.path.join(os.path.dirname(settings_path()), "defaults_backup.json")


def _snapshot_current():
    return {"sleep": _query_index(SUB_SLEEP, STANDBYIDLE),
            "hibernate": _query_index(SUB_SLEEP, HIBERNATEIDLE),
            "display": _query_index(SUB_VIDEO, VIDEOIDLE),
            "lid": _query_index(SUB_BUTTONS, LIDACTION)}


def restore_power_defaults():
    """Restore the pre-enforce snapshot. Returns [(desc, ok, detail)]."""
    results = []
    try:
        with open(_backup_path()) as f:
            snap = json.load(f)
    except Exception:
        return [("no saved snapshot — nothing to restore (enforce never ran)", False, "")]
    mapping = {"sleep": (SUB_SLEEP, STANDBYIDLE), "hibernate": (SUB_SLEEP, HIBERNATEIDLE),
               "display": (SUB_VIDEO, VIDEOIDLE), "lid": (SUB_BUTTONS, LIDACTION)}
    for key, (sub, setting) in mapping.items():
        vals = snap.get(key) if isinstance(snap, dict) else None
        if not vals or vals[0] is None or vals[1] is None:
            results.append((f"{key}: no snapshot value, skipped", False, "unknown"))
            continue
        try:
            ac, dc = str(int(vals[0], 16)), str(int(vals[1], 16))
        except (ValueError, TypeError):
            results.append((f"{key}: snapshot unreadable, skipped", False, str(vals)))
            continue
        ok1, d1 = run_powercfg(["/setacvalueindex", "SCHEME_CURRENT", sub, setting, ac])
        ok2, d2 = run_powercfg(["/setdcvalueindex", "SCHEME_CURRENT", sub, setting, dc])
        results.append((f"{key} restored to {ac}/{dc} (AC/DC)", ok1 and ok2, (d1 + d2)[:200]))
    ok, d = run_powercfg(["/setactive", "SCHEME_CURRENT"])
    results.append(("scheme re-activated", ok, d))
    return results


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
            "lid": f"{_fmt_action(lid[0] if lid else None)} / {_fmt_action(lid[1] if lid else None)} (AC/DC)" if lid else "hidden (Modern Standby — set in Windows Settings)",
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


# ---------- battery (ctypes, no deps) ----------

class _SPS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_byte),
                ("BatteryFlag", ctypes.c_byte),
                ("BatteryLifePercent", ctypes.c_byte),
                ("SystemStatusFlag", ctypes.c_byte),
                ("BatteryLifeTime", ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong)]


def get_power_status():
    """Returns (on_ac: bool|None, percent: int|None). None = unknown."""
    try:
        s = _SPS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
            return None, None
        ac = {0: False, 1: True}.get(int(s.ACLineStatus), None)
        pct = int(s.BatteryLifePercent)
        pct = None if pct > 100 else pct
        return ac, pct
    except Exception:
        return None, None


# ---------- settings persistence ----------

def settings_path():
    if getattr(sys, "frozen", False):
        # PyInstaller onefile: __file__ points into the ephemeral _MEI temp dir,
        # so persist next to the exe instead (resume-last-mode survives restarts).
        here = os.path.dirname(os.path.abspath(sys.executable))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
    try:
        probe = os.path.join(here, ".writetest")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return os.path.join(here, "settings.json")
    except Exception:
        d = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "hustle-on")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "settings.json")


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(settings_path()) as f:
            s.update(json.load(f))
    except Exception:
        pass
    if s.get("mode") not in (MODE_OFF, MODE_ON, MODE_TIMER, MODE_UNTIL):
        s["mode"] = MODE_OFF
    return s


def save_settings(s):
    try:
        with open(settings_path(), "w") as f:
            json.dump(s, f, indent=2)
        return True
    except Exception:
        return False


# ---------- mode engine ----------

class Engine:
    def __init__(self, screen_on=True, guard=True, guard_threshold=30):
        self.screen_on = screen_on
        self.guard = guard
        self.guard_threshold = guard_threshold
        self.mode = MODE_OFF
        self.deadline = None  # datetime for timer/until
        self.battery_paused = False
        self.paused_snapshot = None  # (mode, deadline, timer_minutes) saved at auto-pause
        self.api_ok = True  # False when Windows refused the last hold request
        self.last_reassert = None  # datetime of last successful hold assertion

    def activate(self, mode, minutes=None, until=None):
        now = datetime.datetime.now()
        if mode == MODE_TIMER:
            self.deadline = now + datetime.timedelta(minutes=minutes or 60)
            self.timer_minutes = minutes or 60
        elif mode == MODE_UNTIL:
            self.deadline = until
        else:
            self.deadline = None
        self.mode = mode
        self.battery_paused = False
        if mode != MODE_OFF:
            _, self.api_ok = set_execution_state(hold_flags(self.screen_on))
            if self.api_ok:
                self.last_reassert = datetime.datetime.now()

    def deactivate(self):
        self.mode = MODE_OFF
        self.deadline = None
        set_execution_state(ES_CONTINUOUS)

    def reassert(self):
        if self.mode != MODE_OFF:
            _, self.api_ok = set_execution_state(hold_flags(self.screen_on))
            if self.api_ok:
                self.last_reassert = datetime.datetime.now()

    def resume_snapshot(self):
        """Re-arm whatever was live at auto-pause (or plain on)."""
        snap = self.paused_snapshot
        self.paused_snapshot = None
        self.battery_paused = False
        if snap and snap[0] in (MODE_TIMER, MODE_UNTIL) and snap[1] \
                and snap[1] > datetime.datetime.now():
            if snap[0] == MODE_TIMER:
                self.timer_minutes = snap[2] or 60
                self.activate(MODE_TIMER, minutes=self.timer_minutes)
            else:
                self.activate(MODE_UNTIL, until=snap[1])
        else:
            self.activate(MODE_ON)

    def remaining(self, now=None):
        if self.mode in (MODE_TIMER, MODE_UNTIL) and self.deadline:
            return self.deadline - (now or datetime.datetime.now())
        return None

    def tick(self):
        """Returns list of events: 'expired', 'battery_pause'. Call ~every 30-60s."""
        events = []
        now = datetime.datetime.now()
        if self.mode in (MODE_TIMER, MODE_UNTIL) and self.deadline and now >= self.deadline:
            self.deactivate()
            events.append("expired")
            return events
        if self.guard and self.mode != MODE_OFF:
            ac, pct = get_power_status()
            if ac is False and pct is not None and pct <= self.guard_threshold:
                self.paused_snapshot = (self.mode, self.deadline,
                                        getattr(self, "timer_minutes", None))
                self.deactivate()
                self.battery_paused = True
                events.append("battery_pause")
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
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--no-enforce", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--enforce-only", action="store_true", help="enforce powercfg and exit (admin path)")
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
        for desc, ok, d in enforce_power_settings():
            print(f"[{'OK' if ok else 'FAIL'}] {desc}" + ("" if ok else f" :: {d[:200]}"))
        return 0

    if not args.no_enforce and (args.on or args.timer or args.until or
                                (not args.off and args.timer is None and args.until is None
                                 and "--off" not in (argv or []))):
        # default legacy run also enforces (preserves old hustleon.py behavior)
        if not (args.on or args.timer or args.until or args.off):
            pass  # legacy path below enforces too
    if args.off:
        set_execution_state(ES_CONTINUOUS)
        print("Hold released (off).")
        return 0

    screen_on = not args.screen_off if (args.screen_off or args.screen_on) else True
    if not args.no_enforce:
        print("[1/2] Enforcing: lid=Do Nothing, sleep/hibernate/display=Never ...")
        for desc, ok, d in enforce_power_settings():
            print(f"  [{'OK' if ok else 'FAIL'}] {desc}" + ("" if ok else f" :: {d[:160]}"))
        print("  (FAIL usually means: re-run as Administrator)")

    eng = Engine(screen_on=screen_on)
    if args.timer:
        eng.activate(MODE_TIMER, minutes=args.timer)
        print(f"Holding for {args.timer} min (until {eng.deadline:%H:%M}). Ctrl+C to stop.")
    elif args.until:
        eng.activate(MODE_UNTIL, until=until_dt)
        print(f"Holding until {eng.deadline:%Y-%m-%d %H:%M}. Ctrl+C to stop.")
    else:
        eng.activate(MODE_ON)
        print(f"Holding indefinitely (0x{hold_flags(screen_on):08X}). Ctrl+C to stop.")
    try:
        while True:
            time.sleep(min(args.interval, 60))
            ev = eng.tick()
            if "expired" in ev:
                print("Deadline reached — hold released.")
                return 0
            if "battery_pause" in ev:
                print("Battery low — hold released.")
                return 0
            rem = eng.remaining()
            extra = f" ({rem} left)" if rem else ""
            print(f"  heartbeat: {eng.mode}{extra} {time.strftime('%H:%M:%S')}", flush=True)
    except KeyboardInterrupt:
        eng.deactivate()
        print("\nRestored normal sleep.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
