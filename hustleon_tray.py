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

APP = "HustleOn"
TICK_SECONDS = 30

C_OFF = (128, 128, 128, 255)
C_ON = (46, 204, 113, 255)      # green: indefinitely on
C_TIMED = (46, 204, 113, 255)   # green: timer
C_UNTIL = (46, 204, 113, 255)   # green: until date/time
C_PAUSED = (231, 76, 60, 255)   # red live-dot (live states only)

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


# ---------- icons: user-specced set (basic circle; red dot = LIVE only) ----------
# off: gray power · on: green infinity · timer: green hourglass ·
# until: green wall clock · paused: gray pause-bars (mirrors icons/render_gallery.py)

def _disc(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=color)
    d.ellipse([4, 4, 60, 60], outline=(0, 0, 0, 100), width=2)  # rim: legible on light taskbars
    return img, d


def _live_dot(img):
    ImageDraw.Draw(img).ellipse([40, 40, 60, 60], fill=C_PAUSED)
    return img


def _icon_off():
    img, d = _disc(C_OFF)
    d.arc([19, 19, 45, 45], start=300, end=240, fill=(255, 255, 255, 255), width=6)
    d.line([32, 13, 32, 33], fill=(255, 255, 255, 255), width=6)
    return img


def _icon_on():
    img, d = _disc(C_ON)
    d.ellipse([15, 23, 33, 41], outline=(255, 255, 255, 255), width=6)
    d.ellipse([31, 23, 49, 41], outline=(255, 255, 255, 255), width=6)
    return _live_dot(img)


def _icon_timer():
    img, d = _disc(C_TIMED)
    d.polygon([(23, 14), (41, 14), (32, 31)], fill=(255, 255, 255, 255))
    d.polygon([(32, 33), (23, 50), (41, 50)], fill=(255, 255, 255, 255))
    d.line([21, 12, 43, 12], fill=(255, 255, 255, 255), width=4)
    d.line([21, 52, 43, 52], fill=(255, 255, 255, 255), width=4)
    return _live_dot(img)


def _icon_until():
    img, d = _disc(C_UNTIL)
    d.ellipse([19, 19, 45, 45], fill=(255, 255, 255, 255))
    d.line([32, 32, 32, 22], fill=C_UNTIL, width=5)
    d.line([32, 32, 39, 36], fill=C_UNTIL, width=5)
    d.ellipse([29, 29, 35, 35], fill=C_UNTIL)
    return _live_dot(img)


def _icon_paused():
    img, d = _disc(C_OFF)
    d.rounded_rectangle([24, 20, 30, 44], radius=2, fill=(255, 255, 255, 255))
    d.rounded_rectangle([34, 20, 40, 44], radius=2, fill=(255, 255, 255, 255))
    return img


ICONS = {"off": _icon_off(), "on": _icon_on(), "timed": _icon_timer(),
         "until": _icon_until(), "paused": _icon_paused()}


# ---------- state ----------

saved = core.load_settings()
engine = core.Engine(screen_on=saved.get("screen_on", True),
                     guard=saved.get("battery_guard", True),
                     guard_threshold=saved.get("battery_threshold", 30))
icon = None  # pystray Icon, set in main
_mutex = None  # single-instance handle, module-held so lifetime is explicit
_heartbeat_wake = threading.Event()
_last_menu_key = [None]
lid_protected = None  # True/False once checked; None = unknown
_about_open = [False]


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
            engine.timer_minutes = saved.get("timer_minutes", 60)
            engine.reassert()
        # else: expired while away -> stay off
    persist()


def refresh_lid_status():
    """Cache whether lid-close is truly Do Nothing (read-back, not rc)."""
    global lid_protected
    try:
        s = core.power_summary()["lid"]
        parts = [p.strip().lower() for p in s.split("/")]
        lid_protected = len(parts) == 2 and all("do nothing" in p for p in parts)
    except Exception:
        lid_protected = None


# ---------- click behavior ----------
# Upstream pystray shows the menu on RIGHT-click only; LEFT-click fires the
# default item (a surprise toggle + balloon). Caffeine-style = left-click menu.

class TrayIcon(pystray.Icon):
    def _on_notify(self, wparam, lparam):
        from pystray import _win32 as _backend
        import ctypes
        win32, wintypes = _backend.win32, _backend.wintypes
        if self._menu_handle and lparam in (win32.WM_LBUTTONUP, win32.WM_RBUTTONUP):
            try:
                refresh()  # live battery/mode data: menu never shows a stale snapshot
            except Exception:
                pass
            # TrackPopupMenuEx misbehaves unless our window is foreground
            win32.SetForegroundWindow(self._hwnd)
            point = wintypes.POINT()
            win32.GetCursorPos(ctypes.byref(point))
            hmenu, descriptors = self._menu_handle
            index = win32.TrackPopupMenuEx(
                hmenu,
                win32.TPM_RIGHTALIGN | win32.TPM_BOTTOMALIGN
                | win32.TPM_RETURNCMD,
                point.x,
                point.y,
                self._menu_hwnd,
                None)
            if index > 0:
                descriptors[index - 1](self)
        # (no CS_DBLCLKS in backend: double-clicks arrive as plain LBUTTONUPs,
        # so every click opens the menu; toggling happens only via menu items)


def notify(title, msg):
    """Alerts ONLY: battery auto-off, API failures, bad input. Success is silent."""
    try:
        if icon:
            icon.notify(msg, title)
    except Exception:
        pass


def msgbox(text, title=APP):
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)


def _menu_key():
    return (engine.mode, engine.deadline.isoformat() if engine.deadline else None,
            engine.screen_on, engine.guard, engine.guard_threshold,
            engine.battery_paused, engine.api_ok, lid_protected,
            getattr(engine, "timer_minutes", None))


def refresh():
    """Icon art + tooltip always; menu rebuilt only on state change (avoids
    mid-navigation rebuilds). Wakes the heartbeat for an immediate tick."""
    global icon
    _heartbeat_wake.set()
    if not icon:
        return
    if engine.battery_paused:
        icon.icon = ICONS["paused"]
    elif engine.mode == "off":
        icon.icon = ICONS["off"]
    elif engine.mode == "on":
        icon.icon = ICONS["on"]
    elif engine.mode == "until":
        icon.icon = ICONS["until"]
    else:
        icon.icon = ICONS["timed"]
    icon.title = tooltip()
    key = _menu_key()
    if key != _last_menu_key[0]:
        _last_menu_key[0] = key
        try:
            icon.menu = build_menu()
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
        state = "Paused"
    elif engine.mode == "off":
        state = "Off"
    elif engine.mode == "on":
        state = "Awake indefinitely"
    elif engine.mode == "timer":
        state = f"{fmt_remaining()} left" if fmt_remaining() else "Timer"
    else:
        state = f"Until {engine.deadline:%a %H:%M}" if engine.deadline else "Until…"
    return f"{APP} · {state} · {power_brief()}"


# ---------- actions (menu callbacks take icon, item) ----------

def act_on(ic=None, it=None):
    engine.battery_paused = False
    engine.activate("on")
    persist()
    refresh()


def act_off(ic=None, it=None):
    engine.deactivate()
    engine.battery_paused = False
    persist()
    refresh()


def act_timer(minutes):
    def _run(ic=None, it=None):
        engine.battery_paused = False
        engine.activate("timer", minutes=minutes)
        persist()
        refresh()
    return _run


def act_resume(ic=None, it=None):
    if engine.guard:
        ac, pct = core.get_power_status()
        if ac is False and pct is not None and pct <= engine.guard_threshold:
            notify(APP, f"Still on battery at {pct}% (guard {engine.guard_threshold}%) — plug in to resume.")
            return
    engine.resume_snapshot()
    persist()
    refresh()


def _timer_label(m):
    if m == 60:
        return "1 hour"
    if m % 60 == 0:
        return f"{m // 60} hours"
    return f"{m} minutes"


def _until_suffix(hhmm):
    """' (tomorrow)' when the wall-clock time already passed today."""
    try:
        h, mi = hhmm.split(":")
        now = datetime.datetime.now()
        if now.replace(hour=int(h), minute=int(mi), second=0, microsecond=0) <= now:
            return " (tomorrow)"
    except Exception:
        pass
    return ""


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
    persist()
    refresh()


def act_guard_toggle(ic=None, it=None):
    engine.guard = not engine.guard
    if not engine.guard:
        engine.battery_paused = False  # explicit user action clears the latch
    persist()
    refresh()


def act_guard_threshold(pct):
    def _run(ic=None, it=None):
        engine.guard_threshold = pct
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
        # success is silent; verify in About HustleOn
    except Exception as e:
        msgbox(f"Elevation failed: {e}", APP)


def _about_body():
    status = {
        "off": "Off — using system power plan",
        "on": "Awake indefinitely",
        "timer": f"Awake — {fmt_remaining()} left" if fmt_remaining() else "Awake on timer",
        "until": f"Awake until {engine.deadline:%a %H:%M}" if engine.deadline else "Awake until…",
    }[engine.mode]
    if engine.battery_paused:
        status += " (paused: battery low)"
    ps = core.power_summary()
    if engine.mode != "off" and engine.last_reassert:
        hold = f"live (re-asserted {engine.last_reassert:%H:%M:%S})"
    else:
        hold = engine.mode
    return (f"Status: {status}\n"
            f"Hold: {hold}\n"
            f"Display: {'kept on' if engine.screen_on else 'may sleep (CPU stays awake)'}\n"
            f"Battery guard: {'on (' + str(engine.guard_threshold) + '%)' if engine.guard else 'off'} · {power_brief()}\n"
            f"Sleep after: {ps['sleep']}\n"
            f"Display off after: {ps['display']}\n"
            f"Lid close: {ps['lid']}")


def act_about(ic=None, it=None):
    if _about_open[0]:
        return
    _about_open[0] = True
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        w = tk.Toplevel(root)
        w.title("About HustleOn")
        w.attributes("-topmost", True)
        w.resizable(False, False)
        tk.Label(w, text="HustleOn", font=("Segoe UI", 16, "bold")).pack(pady=(14, 0))
        tk.Label(w, text=f"Version {core.__version__}", font=("Segoe UI", 9),
                 fg="gray").pack()
        body = tk.Label(w, text=_about_body(), font=("Segoe UI", 10), justify="left")
        body.pack(padx=20, pady=12, anchor="w")

        def _fix_lid():
            act_enforce()
            body.config(text=_about_body())

        def _close():
            _about_open[0] = False
            for _w in (w, root):
                try:
                    _w.destroy()
                except Exception:
                    pass

        def _restore():
            res = core.restore_power_defaults()
            refresh_lid_status()
            body.config(text=_about_body())
            if not all(ok for _, ok, _ in res):
                msgbox("Some values could not be restored (Administrator may be required).",
                       APP)

        btns = tk.Frame(w)
        btns.pack(pady=(0, 14))
        tk.Button(btns, text="Fix lid settings (admin)…", width=22,
                  command=_fix_lid).pack(side="left", padx=4)
        tk.Button(btns, text="Restore sleep defaults", width=20,
                  command=_restore).pack(side="left", padx=4)
        tk.Button(btns, text="OK", width=8,
                  command=_close).pack(side="left", padx=4)
        w.bind("<Escape>", lambda e: _close())
        w.protocol("WM_DELETE_WINDOW", _close)
        w.update_idletasks()
        x = w.winfo_pointerx() - w.winfo_reqwidth() // 2
        y = w.winfo_pointery() - w.winfo_reqheight() // 2
        w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        root.mainloop()
    except Exception:
        _about_open[0] = False
        msgbox(f"HustleOn {core.__version__}\n\n{_about_body()}", "About HustleOn")


def act_quit(ic=None, it=None):
    engine.deactivate()
    persist()
    if icon:
        icon.stop()


# ---------- menu ----------

def build_menu():
    # Caffeine-style labels: modes read as sentences, active mode checked.
    # Parents carry checks so custom values still show state.
    items = []
    if lid_protected is False:
        items.append(pystray.MenuItem("⚠ Lid will still sleep — fix in About HustleOn",
                                      act_about, enabled=False))
    if engine.battery_paused:
        ac, pct = core.get_power_status()
        items.append(pystray.MenuItem(
            f"Paused — battery {pct if pct is not None else '?'}%. Plug in, then resume.",
            None, enabled=False))
        items.append(pystray.MenuItem("Resume hold", act_resume))
        items.append(pystray.Menu.SEPARATOR)
    interval_label = "Keep awake on interval"
    if engine.mode == "timer" and fmt_remaining():
        interval_label += f" ({fmt_remaining()} left)"
    until_label = "Keep awake until expiration date and time"
    if engine.mode == "until" and engine.deadline:
        until_label += f" (until {engine.deadline:%a %H:%M})"
    items += [
        pystray.MenuItem("Keep awake indefinitely", act_on,
                         checked=lambda it: engine.mode == "on",
                         default=(engine.mode == "off")),
        pystray.MenuItem(interval_label, pystray.Menu(
            *[pystray.MenuItem(_timer_label(m), act_timer(m),
                               checked=lambda it, m=m: engine.mode == "timer"
                               and getattr(engine, "timer_minutes", None) == m)
              for m in TIMER_PRESETS],
            pystray.MenuItem("Custom…", act_timer_custom)),
            checked=lambda it: engine.mode == "timer"),
        pystray.MenuItem(until_label, pystray.Menu(
            *[pystray.MenuItem(f"{label}{_until_suffix(hhmm)}", act_until(hhmm))
              for label, hhmm in UNTIL_PRESETS],
            pystray.MenuItem("Custom…", act_until_custom)),
            checked=lambda it: engine.mode == "until"),
        pystray.MenuItem("Off (keep using the selected power plan)", act_off,
                         checked=lambda it: engine.mode == "off",
                         default=(engine.mode != "off")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Keep screen on", act_toggle_screen,
                         checked=lambda it: engine.screen_on),
        pystray.MenuItem("Battery guard", pystray.Menu(
            pystray.MenuItem("Enabled", act_guard_toggle,
                             checked=lambda it: engine.guard),
            pystray.Menu.SEPARATOR,
            *[pystray.MenuItem(f"{p}%", act_guard_threshold(p),
                               checked=lambda it, p=p: engine.guard_threshold == p)
              for p in (10, 15, 20, 30, 40, 50)],
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda it: f"Status: {power_brief()}"
                             + (" — tripped" if engine.battery_paused else ""),
                             None, enabled=False))),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("About HustleOn…", act_about),
        pystray.MenuItem("Quit", act_quit),
    ]
    return pystray.Menu(*items)


# ---------- heartbeat ----------

def heartbeat():
    api_was_ok = True
    fail_streak = 0
    while True:
        _heartbeat_wake.wait(TICK_SECONDS)
        _heartbeat_wake.clear()
        try:
            events = engine.tick()
            fail_streak = 0
            if "expired" in events:
                persist()  # completed as asked: silent
            elif "battery_pause" in events:
                notify(APP, f"Battery low ({power_brief()}) — hold paused. Plug in, then Resume hold.")
                persist()
                refresh_lid_status()
            if engine.mode != "off" and not engine.api_ok and api_was_ok:
                notify(APP, "Windows refused the stay-awake request — hold may be inactive.")
            api_was_ok = engine.api_ok if engine.mode != "off" else True
            refresh()
        except Exception:
            # Never skip the hold silently: retry it, escalate on repetition.
            fail_streak += 1
            try:
                engine.reassert()
            except Exception:
                pass
            if fail_streak == 3:
                notify(APP, "HustleOn hit a repeated internal error — hold may be stale. Restart the app.")


def main():
    global icon, _mutex
    # Crisp menus/icons on high-DPI: declare Per-Monitor V2 before any window
    # exists (manifest covers the exe; this covers running from source).
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    _mutex = ensure_single_instance()
    resume_last_mode()
    refresh_lid_status()
    warn_lid = (lid_protected is False)
    icon = TrayIcon(APP, ICONS["off"], tooltip(), build_menu())
    threading.Thread(target=heartbeat, daemon=True).start()
    refresh()

    def _setup(ic):
        try:
            ic.visible = True
        except Exception:
            pass
        if warn_lid:
            notify(APP, "HustleOn can't hold the lid yet — open About HustleOn → Fix lid settings.")

    icon.run(setup=_setup)


if __name__ == "__main__":
    main()
