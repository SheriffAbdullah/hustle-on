"""hustle-on tray app — caffeine-style system-tray keep-awake.

Run:  python hustleon_tray.py        (double-click the built exe in v1 packaging)
"""
import ctypes
import datetime
import os
import sys
import threading

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow required: pip install pillow", file=sys.stderr)
    raise SystemExit(1)

try:
    import pystray
except ImportError:
    print("pystray required: pip install pystray", file=sys.stderr)
    raise SystemExit(1)

import hustleon_core as core

APP = "hustle-on"
TICK_SECONDS = 30

C_OFF = (128, 128, 128, 255)
C_ON = (46, 204, 113, 255)
C_TIMED = (52, 152, 219, 255)
C_PAUSED = (231, 76, 60, 255)

TIMER_PRESETS = [30, 60, 120, 480]
UNTIL_PRESETS = [("Lunch 13:00", "13:00"), ("EOD 18:00", "18:00"), ("Morning 08:00", "08:00")]


# ---------- single instance ----------

def ensure_single_instance():
    m = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\HustleOnSingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(None, "hustle-on is already running (check the tray).",
                                        APP, 0x40)
        raise SystemExit(0)
    return m


# ---------- icons: white power glyph on solid disc (legible at 16px) ----------

def make_icon(color, paused=False):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=color)
    d.arc([19, 19, 45, 45], start=300, end=240, fill=(255, 255, 255, 255), width=6)
    d.line([32, 13, 32, 33], fill=(255, 255, 255, 255), width=6)
    if paused:
        d.ellipse([40, 40, 60, 60], fill=C_PAUSED)
    return img


ICONS = {"off": make_icon(C_OFF), "on": make_icon(C_ON),
         "timed": make_icon(C_TIMED), "paused": make_icon(C_OFF, paused=True)}


# ---------- state ----------

saved = core.load_settings()
engine = core.Engine(screen_on=saved.get("screen_on", True),
                     guard=saved.get("battery_guard", True),
                     guard_threshold=saved.get("battery_threshold", 30))
icon = None  # pystray Icon, set in main


def persist():
    saved.update({"mode": engine.mode,
                  "timer_minutes": getattr(engine, "timer_minutes", saved.get("timer_minutes", 60)),
                  "until_iso": engine.deadline.isoformat() if engine.deadline else None,
                  "screen_on": engine.screen_on,
                  "battery_guard": engine.guard,
                  "battery_threshold": engine.guard_threshold})
    core.save_settings(saved)


def resume_last_mode():
    mode = saved.get("mode", "off")
    if mode == "on":
        engine.activate("on")
    elif mode in ("timer", "until"):
        try:
            dl = datetime.datetime.fromisoformat(saved["until_iso"]) if saved.get("until_iso") else None
        except Exception:
            dl = None
        if dl and dl > datetime.datetime.now():
            engine.mode = mode
            engine.deadline = dl
            engine.reassert()
        # else: expired while away -> stay off
    persist()


def notify(title, msg):
    try:
        if icon:
            icon.notify(msg, title)
    except Exception:
        pass


def msgbox(text, title=APP):
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)


def refresh():
    """Refresh icon art + tooltip + menu. Safe from any thread."""
    global icon
    if not icon:
        return
    if engine.battery_paused:
        icon.icon = ICONS["paused"]
    elif engine.mode == "off":
        icon.icon = ICONS["off"]
    elif engine.mode == "on":
        icon.icon = ICONS["on"]
    else:
        icon.icon = ICONS["timed"]
    icon.title = tooltip()
    try:
        icon.menu = build_menu()
    except Exception:
        pass
    try:
        icon.update_menu()
    except Exception:
        pass


def fmt_remaining():
    rem = engine.remaining()
    if rem is None:
        return ""
    s = int(rem.total_seconds())
    if s < 0:
        return ""
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def power_brief():
    ac, pct = core.get_power_status()
    if ac is None and pct is None:
        return "power: ?"
    if ac:
        return "AC" + (f" {pct}%" if pct is not None else "")
    return f"Batt {pct if pct is not None else '?'}%"


def tooltip():
    if engine.battery_paused:
        state = "Paused (battery low)"
    elif engine.mode == "off":
        state = "Off (using system power plan)"
    elif engine.mode == "on":
        state = "Awake indefinitely"
    elif engine.mode == "timer":
        state = f"Awake — {fmt_remaining()} left" if fmt_remaining() else "Awake on timer"
    else:
        state = f"Awake until {engine.deadline:%a %H:%M}" if engine.deadline else "Awake until…"
    return f"{APP} — {state} · {power_brief()}"


# ---------- actions (menu callbacks take icon, item) ----------

def act_on(ic=None, it=None):
    engine.battery_paused = False
    engine.activate("on")
    notify(APP, "On — holding awake indefinitely.")
    persist()
    refresh()


def act_off(ic=None, it=None):
    engine.deactivate()
    engine.battery_paused = False
    notify(APP, "Off — normal sleep restored.")
    persist()
    refresh()


def act_timer(minutes):
    def _run(ic=None, it=None):
        engine.battery_paused = False
        engine.activate("timer", minutes=minutes)
        notify(APP, f"Timer — holding for {minutes} min (until {engine.deadline:%H:%M}).")
        persist()
        refresh()
    return _run


def _tk_root():
    import tkinter as tk
    r = tk.Tk()
    r.withdraw()
    r.attributes("-topmost", True)
    return r


def act_timer_custom(ic=None, it=None):
    try:
        from tkinter import simpledialog
        r = _tk_root()
        try:
            v = simpledialog.askinteger(APP, "Hold for how many minutes?", minvalue=1, maxvalue=1440)
        finally:
            r.destroy()
        if v:
            act_timer(v)()
    except Exception:
        notify(APP, "Custom timer unavailable (tkinter missing).")


def _parse_hhmm(s):
    h, m = s.strip().split(":")
    now = datetime.datetime.now()
    dt = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    if dt <= now:
        dt += datetime.timedelta(days=1)
    return dt


def act_until(hhmm):
    def _run(ic=None, it=None):
        try:
            dt = _parse_hhmm(hhmm)
        except Exception:
            notify(APP, f"Bad time '{hhmm}' — use HH:MM.")
            return
        engine.battery_paused = False
        engine.activate("until", until=dt)
        notify(APP, f"Holding until {dt:%a %H:%M}.")
        persist()
        refresh()
    return _run


def act_until_custom(ic=None, it=None):
    try:
        from tkinter import simpledialog
        r = _tk_root()
        try:
            v = simpledialog.askstring(APP, "Hold until what time? (HH:MM)")
        finally:
            r.destroy()
        if v:
            act_until(v)()
    except Exception:
        notify(APP, "Custom 'until' unavailable (tkinter missing).")


def act_toggle_screen(ic=None, it=None):
    engine.screen_on = not engine.screen_on
    engine.reassert()
    notify(APP, "Keep screen on." if engine.screen_on else "Screen may sleep (CPU stays awake).")
    persist()
    refresh()


def act_guard_toggle(ic=None, it=None):
    engine.guard = not engine.guard
    notify(APP, f"Battery guard {'on' if engine.guard else 'off'}.")
    persist()
    refresh()


def act_guard_threshold(pct):
    def _run(ic=None, it=None):
        engine.guard_threshold = pct
        notify(APP, f"Battery guard threshold: {pct}%.")
        persist()
        refresh()
    return _run


def act_enforce(ic=None, it=None):
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, "--enforce-only"
    else:
        exe = sys.executable
        params = f'"{os.path.abspath("hustleon_core.py")}" --enforce-only'
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        if int(rc) <= 32:
            msgbox("Elevation failed or was cancelled.", APP)
        else:
            notify(APP, "Lid enforcement launched (UAC) — use Check settings to verify.")
    except Exception as e:
        msgbox(f"Elevation failed: {e}", APP)


def act_check(ic=None, it=None):
    msgbox(core.check_settings_text()[:1500], f"{APP} — settings")


def act_quit(ic=None, it=None):
    engine.deactivate()
    persist()
    if icon:
        icon.stop()


# ---------- menu ----------

def build_menu():
    # Caffeine-style labels: modes read as sentences, active mode checked,
    # double-click (default item) flips on/off.
    interval_label = "Keep awake on interval"
    if engine.mode == "timer" and fmt_remaining():
        interval_label += f" ({fmt_remaining()} left)"
    until_label = "Keep awake until expiration date and time"
    if engine.mode == "until" and engine.deadline:
        until_label += f" (until {engine.deadline:%a %H:%M})"
    return pystray.Menu(
        pystray.MenuItem("Keep awake indefinitely", act_on,
                         checked=lambda it: engine.mode == "on",
                         default=(engine.mode == "off")),
        pystray.MenuItem(interval_label, pystray.Menu(
            *[pystray.MenuItem(f"{m // 60} hour(s)" if m % 60 == 0 else f"{m} minutes",
                               act_timer(m),
                               checked=lambda it, m=m: engine.mode == "timer"
                               and getattr(engine, "timer_minutes", None) == m)
              for m in TIMER_PRESETS],
            pystray.MenuItem("Custom…", act_timer_custom))),
        pystray.MenuItem(until_label, pystray.Menu(
            *[pystray.MenuItem(label, act_until(hhmm)) for label, hhmm in UNTIL_PRESETS],
            pystray.MenuItem("Custom…", act_until_custom))),
        pystray.MenuItem("Off (keep using the selected power plan)", act_off,
                         checked=lambda it: engine.mode == "off",
                         default=(engine.mode != "off")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Keep screen on", act_toggle_screen,
                         checked=lambda it: engine.screen_on),
        pystray.MenuItem("Battery guard", pystray.Menu(
            pystray.MenuItem("Enabled", act_guard_toggle,
                             checked=lambda it: engine.guard),
            pystray.MenuItem("Threshold", pystray.Menu(
                *[pystray.MenuItem(f"{p}%", act_guard_threshold(p),
                                   checked=lambda it, p=p: engine.guard_threshold == p)
                  for p in (10, 15, 20, 30)])),
            pystray.MenuItem(lambda it: f"Status: {power_brief()}"
                             + (" — tripped" if engine.battery_paused else ""),
                             None, enabled=False))),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Enforce lid settings (admin)…", act_enforce),
        pystray.MenuItem("Check settings", act_check),
        pystray.MenuItem("Quit", act_quit),
    )


# ---------- heartbeat ----------

def heartbeat():
    while True:
        threading.Event().wait(TICK_SECONDS)
        try:
            events = engine.tick()
            if "expired" in events:
                notify(APP, "Time's up — hold released.")
                persist()
            elif "battery_pause" in events:
                notify(APP, f"Battery low ({power_brief()}) — hold paused. Plug in to resume.")
                persist()
            refresh()
        except Exception:
            pass


def main():
    global icon
    ensure_single_instance()
    resume_last_mode()
    icon = pystray.Icon(APP, ICONS["off"], tooltip(), build_menu())
    threading.Thread(target=heartbeat, daemon=True).start()
    refresh()
    icon.run()


if __name__ == "__main__":
    main()
