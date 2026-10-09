"""hustle-on core engine: execution-state hold, powercfg enforce, battery, modes, settings.

Shared by the CLI (hustleon.py) and the tray app (hustleon_tray.py).
No third-party dependencies — stdlib + ctypes only.
"""
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

def set_execution_state(flags):
    try:
        return ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        return 0


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
    results = []
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
    return results


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
    def __init__(self, screen_on=True, guard=True, guard_threshold=20):
        self.screen_on = screen_on
        self.guard = guard
        self.guard_threshold = guard_threshold
        self.mode = MODE_OFF
        self.deadline = None  # datetime for timer/until
        self.battery_paused = False

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
            set_execution_state(hold_flags(self.screen_on))

    def deactivate(self):
        self.mode = MODE_OFF
        self.deadline = None
        set_execution_state(ES_CONTINUOUS)

    def reassert(self):
        if self.mode != MODE_OFF:
            set_execution_state(hold_flags(self.screen_on))

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
    args = ap.parse_args(argv)

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
        eng.activate(MODE_UNTIL, until=_parse_until(args.until))
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
