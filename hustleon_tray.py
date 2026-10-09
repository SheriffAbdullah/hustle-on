"""hustle-on tray app - caffeine-style system-tray keep-awake.

Run:  python hustleon_tray.py        (double-click the built exe in v1 packaging)
"""
import ctypes
import ctypes.wintypes
import datetime
import os
import queue
import sys
import threading

import hustleon_core as core

# The elevated one-time unlock must run BEFORE heavy imports and before the
# single-instance check: a frozen exe has no script arg, and the tray is
# usually already running when the elevated copy starts.
if __name__ == "__main__" and "--enforce-only" in sys.argv[1:]:
    raise SystemExit(core.main(["--enforce-only"]))

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

APP = "HustleOn"
TICK_SECONDS = core.HEARTBEAT_SECONDS
POWER_SETTINGS_URI = "ms-settings:powersleep"

C_OFF = (128, 128, 128, 255)
C_ON = (46, 204, 113, 255)      # green: indefinitely on
C_TIMED = (46, 204, 113, 255)   # green: timer
C_UNTIL = (46, 204, 113, 255)   # green: until date/time
C_PAUSED = (231, 76, 60, 255)   # red live-dot (live states only)

TIMER_PRESETS = [30, 60, 120, 480]
UNTIL_PRESETS = [("Lunch 13:00", "13:00"), ("EOD 18:00", "18:00"), ("Morning 08:00", "08:00")]


# ---------- single instance ----------

def ensure_single_instance():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    ctypes.set_last_error(0)
    m = k32.CreateMutexW(None, False, "Local\\HustleOnSingleInstance")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(None, "hustle-on is already running (check the tray).",
                                        APP, 0x40)
        raise SystemExit(0)
    return m


def elevation_command():
    """(exe, params) for the one-time elevated lid unlock."""
    if getattr(sys, "frozen", False):
        return sys.executable, "--enforce-only"
    return sys.executable, f'"{os.path.abspath(core.__file__)}" --enforce-only'


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
                     guard_threshold=saved.get("battery_threshold", 30),
                     thermal_guard=saved.get("thermal_guard", False),
                     thermal_threshold=saved.get("thermal_threshold", 90))
icon = None  # pystray Icon, set in main
_mutex = None  # single-instance handle, module-held so lifetime is explicit
_heartbeat_wake = threading.Event()
_last_menu_key = [None]
lid_state = "unknown"   # 'protected' | 'unprotected' | 'unknown' (read-back)
_quitting = [False]
_alerted = {"unprotected": False, "restore": False}


def persist():
    if _quitting[0]:
        return
    saved.update({"mode": engine.mode,
                  "timer_minutes": engine.timer_minutes,
                  "until_iso": engine.deadline.isoformat() if engine.deadline else None,
                  "last_mode": engine.snapshot_mode(),   # None on explicit Off / expiry
                  "screen_on": engine.screen_on,
                  "battery_guard": engine.guard,
                  "battery_threshold": engine.guard_threshold,
                  "thermal_guard": engine.thermal_guard,
                  "thermal_threshold": engine.thermal_threshold})
    core.save_settings(saved)


def resume_last_mode():
    engine.resume_from_last(core.resume_plan(saved))
    persist()


def refresh_lid_status():
    """Cache the tri-state lid status (read-back, never the powercfg rc)."""
    global lid_state
    try:
        lid_state = core.lid_status()
    except Exception:
        lid_state = "unknown"


def open_power_settings(ic=None, it=None):
    try:
        os.startfile(POWER_SETTINGS_URI)
    except Exception:
        msgbox("Open Windows Settings > System > Power & battery and set the lid to Do Nothing.")


def check_alerts():
    """Failure-only alerts, once per occurrence."""
    if engine.mode == "off":
        _alerted["unprotected"] = False
    elif lid_state == "unprotected" and not _alerted["unprotected"]:
        _alerted["unprotected"] = True
        notify(APP, "The lid will still put this PC to sleep. Open Windows power settings.")
    if engine.restore_ok:
        _alerted["restore"] = False
    elif not _alerted["restore"]:
        _alerted["restore"] = True
        notify(APP, "Couldn't restore your sleep settings. Use About > Restore sleep defaults.")


def after_change():
    persist()
    refresh_lid_status()
    check_alerts()
    refresh()


# ---------- click behavior ----------
# Upstream pystray shows the menu on RIGHT-click only; LEFT-click fires the
# default item (a surprise toggle + balloon). Caffeine-style = left-click menu.

class TrayIcon(pystray.Icon):
    pass


def _left_click_on_notify(self, wparam, lparam):
    from pystray import _win32 as _backend
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


def _can_override_notify():
    """Only replace pystray's click handling if its private hooks exist."""
    try:
        from pystray import _win32 as _backend
        return (hasattr(pystray.Icon, "_on_notify")
                and all(hasattr(_backend.win32, n) for n in
                        ("WM_LBUTTONUP", "WM_RBUTTONUP", "SetForegroundWindow", "GetCursorPos",
                         "TrackPopupMenuEx", "TPM_RIGHTALIGN", "TPM_BOTTOMALIGN", "TPM_RETURNCMD"))
                and hasattr(_backend, "wintypes"))
    except Exception:
        return False


if _can_override_notify():
    TrayIcon._on_notify = _left_click_on_notify
# else: pystray's default right-click menu is used


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
            engine.screen_on, engine.guard, engine.guard_threshold, engine.thermal_guard,
            engine.battery_paused, engine.api_ok, lid_state, engine.timer_minutes,
            core.autostart_enabled())


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


# ---------- Tk UI thread: the ONE tk.Tk() in the process ----------

class UiThread:
    """Owns the sole (hidden) Tk root. Dialogs are Toplevels built on this
    thread; other threads post callables with call()."""

    def __init__(self):
        self._q = queue.Queue()
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self.root = None
        self.failed = False

    def _start(self):
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="hustleon-ui", daemon=True)
                self._thread.start()
        self._ready.wait(10)

    def _run(self):
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()  # hidden for life; dialogs are Toplevels
            try:
                from PIL import ImageTk
                root._icon_ref = ImageTk.PhotoImage(_current_icon_image().resize((32, 32)))
                root.iconphoto(True, root._icon_ref)
            except Exception:
                pass
            self.root = root
            self._ready.set()
            self._pump()
            root.mainloop()
        except Exception:
            self.failed = True
            self._ready.set()

    def _pump(self):
        try:
            while True:
                fn = self._q.get_nowait()
                try:
                    fn()
                except Exception as e:
                    core.log(f"ui callback failed: {e}")
        except queue.Empty:
            pass
        if self.root is not None:
            self.root.after(100, self._pump)

    def call(self, fn):
        """Run fn on the UI thread. False when Tk is unavailable."""
        self._start()
        if self.failed or self.root is None:
            return False
        self._q.put(fn)
        return True

    def stop(self):
        if self.root is not None:
            try:
                self.root.after(0, self.root.quit)
            except Exception:
                pass


ui = UiThread()


# ---------- actions (menu callbacks take icon, item) ----------

def act_on(ic=None, it=None):
    engine.battery_paused = False
    engine.activate("on")
    after_change()


def act_off(ic=None, it=None):
    engine.deactivate("off")
    engine.battery_paused = False
    after_change()


def act_timer(minutes):
    def _run(ic=None, it=None):
        engine.battery_paused = False
        engine.activate("timer", minutes=minutes)
        after_change()
    return _run


def act_resume(ic=None, it=None):
    if engine.guard:
        ac, pct = core.get_power_status()
        if ac is False and pct is not None and pct <= engine.guard_threshold:
            notify(APP, f"Still on battery at {pct}% (guard {engine.guard_threshold}%) — plug in to resume.")
            return
    engine.resume_snapshot()
    after_change()


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


def _in_worker(fn):
    threading.Thread(target=fn, name="hustleon-action", daemon=True).start()


def act_timer_custom(ic=None, it=None):
    def _dialog():
        from tkinter import simpledialog
        root = ui.root
        root.attributes("-topmost", True)
        v = simpledialog.askinteger(APP, "Hold for how many minutes?", parent=root,
                                    minvalue=1, maxvalue=1440)
        if v:
            _in_worker(act_timer(v))
    if not ui.call(_dialog):
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
        after_change()
    return _run


def act_until_custom(ic=None, it=None):
    def _dialog():
        from tkinter import simpledialog
        root = ui.root
        root.attributes("-topmost", True)
        v = simpledialog.askstring(APP, "Hold until what time? (HH:MM)", parent=root)
        if v:
            _in_worker(act_until(v))
    if not ui.call(_dialog):
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


def act_thermal_toggle(ic=None, it=None):
    engine.thermal_guard = not engine.thermal_guard
    persist()
    refresh()


def act_autostart_toggle(ic=None, it=None):
    want = not core.autostart_enabled()
    ok, detail = core.set_autostart(want)
    if not ok:
        notify(APP, f"Couldn't change Start with Windows: {detail[:80]}")
    saved["start_with_windows"] = core.autostart_enabled()
    persist()
    refresh()


def act_unlock_lid(ic=None, it=None):
    """One-time elevated unhide of the lid setting (Modern Standby). Only shown
    when the lid setting is hidden; day-to-day applies need no admin."""
    exe, params = elevation_command()
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        if int(rc) <= 32:
            msgbox("Elevation failed or was cancelled.", APP)
        else:
            saved["unhide_done"] = True   # remember the choice; first-run won't ask again
            persist()
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


def _about_rows():
    """Key/value rows for the About grid (same data as _about_body)."""
    return [ln.split(": ", 1) if ": " in ln else ("", ln)
            for ln in _about_body().split("\n")]


def _dark_mode():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        return False


def _current_icon_image():
    if engine.battery_paused:
        return ICONS["paused"]
    return ICONS.get({"timer": "timed"}.get(engine.mode, engine.mode), ICONS["off"])


def _set_window_icon(win):
    """Use the app's own PIL icon (never the Tk feather). Reference kept on win."""
    try:
        from PIL import ImageTk
        win._icon_ref = [ImageTk.PhotoImage(_current_icon_image().resize((32, 32)))]
        win.iconphoto(True, *win._icon_ref)
    except Exception:
        pass


def _style_for(win):
    """Shared dark/light ttk styling. Returns (bg, fg, sub, dark)."""
    from tkinter import ttk
    dark = _dark_mode()
    bg, fg, sub = ("#202020", "#ffffff", "#9a9a9a") if dark else ("#f3f3f3", "#1a1a1a", "#6b6b6b")
    win.configure(bg=bg)
    st = ttk.Style(win)
    if dark:
        st.theme_use("clam")
        st.configure("TButton", background="#333333", foreground=fg, bordercolor="#444444",
                     focuscolor="#333333", padding=(10, 5))
        st.map("TButton", background=[("active", "#444444")])
    st.configure("A.TFrame", background=bg)
    st.configure("K.TLabel", background=bg, foreground=sub, font=("Segoe UI", 10))
    st.configure("V.TLabel", background=bg, foreground=fg, font=("Segoe UI", 10))
    st.configure("T.TLabel", background=bg, foreground=fg, font=("Segoe UI", 16, "bold"))
    st.configure("S.TLabel", background=bg, foreground=sub, font=("Segoe UI", 9))
    st.configure("A.TCheckbutton", background=bg, foreground=fg, font=("Segoe UI", 10))
    return bg, fg, sub, dark


def _show_window(win, dark):
    """Dark title bar, centre on the primary work area, then reveal."""
    win.update_idletasks()
    if dark:
        try:
            hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
        except Exception:
            pass
    try:
        rc = ctypes.wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rc), 0)
        ax, ay, aw, ah = rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top
    except Exception:
        ax, ay, aw, ah = 0, 0, win.winfo_screenwidth(), win.winfo_screenheight()
    ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
    win.geometry(f"+{ax + (aw - ww) // 2}+{ay + (ah - wh) // 2}")
    win.attributes("-topmost", True)
    win.deiconify()
    win.lift()
    win.focus_force()


_about_win = [None]   # touched only on the UI thread: at most one About dialog


def _build_about():
    import tkinter as tk
    from tkinter import ttk
    if _about_win[0] is not None:   # already open: raise and focus it
        w = _about_win[0]
        try:
            w.deiconify()
            w.lift()
            w.focus_force()
        except Exception:
            _about_win[0] = None
        else:
            return
    win = tk.Toplevel(ui.root)
    _about_win[0] = win
    win.withdraw()  # stay hidden until fully laid out and positioned
    win.title("About HustleOn")
    win.resizable(False, False)
    bg, fg, sub, dark = _style_for(win)
    _set_window_icon(win)

    outer = ttk.Frame(win, style="A.TFrame", padding=20)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="HustleOn", style="T.TLabel").pack(anchor="w")
    ttk.Label(outer, text=f"Version {core.__version__}", style="S.TLabel").pack(anchor="w", pady=(0, 12))
    grid = ttk.Frame(outer, style="A.TFrame")
    grid.pack(fill="x")
    grid.columnconfigure(1, weight=1)
    btns = ttk.Frame(outer, style="A.TFrame")
    btns.pack(fill="x", pady=(16, 0))

    def _close(_e=None):
        _about_win[0] = None
        try:
            win.destroy()
        except Exception:
            pass

    def _restore():
        if engine.applied:
            msgbox("A hold is live. Turn it Off and HustleOn restores your sleep settings "
                   "automatically.", APP)
            return
        res = core.restore_power_defaults()
        refresh_lid_status()
        _fill()
        if not all(ok for _, ok, _ in res):
            msgbox("Nothing to restore, or some values could not be restored.", APP)

    def _unlock():
        act_unlock_lid()
        _fill()

    def _fill():
        for c in grid.winfo_children():
            c.destroy()
        rows = _about_rows()
        for i, (k, v) in enumerate(rows):
            ttk.Label(grid, text=k, style="K.TLabel").grid(row=i, column=0, sticky="nw",
                                                           padx=(0, 16), pady=2)
            ttk.Label(grid, text=v, style="V.TLabel", wraplength=300,
                      justify="left").grid(row=i, column=1, sticky="nw", pady=2)
        hidden = any(k.startswith("Lid close") and v.startswith("hidden") for k, v in rows)
        for c in btns.winfo_children():
            c.destroy()
        specs = []
        if hidden:   # one-time unlock, only while the lid setting is hidden
            specs.append(("Unlock lid setting (admin)…", _unlock))
        specs += [("Restore sleep defaults", _restore), ("Close", _close)]
        for n, (txt, cmd) in enumerate(specs):
            b = ttk.Button(btns, text=txt, command=cmd, width=22)
            b.grid(row=0, column=n, padx=(0 if n == 0 else 8, 0), sticky="ew")
            btns.columnconfigure(n, weight=1, uniform="b")
            if txt == "Close":
                b.focus_set()

    _fill()
    win.bind("<Return>", _close)
    win.bind("<Escape>", _close)
    win.protocol("WM_DELETE_WINDOW", _close)
    _show_window(win, dark)


def act_about(ic=None, it=None):
    if not ui.call(_build_about):
        msgbox(f"HustleOn {core.__version__}\n\n{_about_body()}", "About HustleOn")


# ---------- first-run setup ----------

_first_run_win = [None]


def _build_first_run():
    import tkinter as tk
    from tkinter import ttk
    if _first_run_win[0] is not None:
        return
    win = tk.Toplevel(ui.root)
    _first_run_win[0] = win
    win.withdraw()
    win.title("Welcome to HustleOn")
    win.resizable(False, False)
    bg, fg, sub, dark = _style_for(win)
    _set_window_icon(win)
    outer = ttk.Frame(win, style="A.TFrame", padding=20)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="Quick setup", style="T.TLabel").pack(anchor="w")
    ttk.Label(outer, text="HustleOn changes your lid/sleep settings only while a hold is on, "
                          "and puts them back when it ends.", style="S.TLabel",
              wraplength=380, justify="left").pack(anchor="w", pady=(0, 12))

    lid_text = {"protected": "Lid close: Do Nothing (ready)",
                "unprotected": "Lid close: will be set to Do Nothing during a hold",
                "unknown": "Lid close: hidden by Windows (Modern Standby)"}
    st = core.lid_status()
    ttk.Label(outer, text=lid_text[st], style="V.TLabel").pack(anchor="w")
    ttk.Button(outer, text="Open Windows power settings",
               command=open_power_settings).pack(anchor="w", pady=(4, 8))
    if st == "unknown" and not saved.get("unhide_done"):
        ttk.Button(outer, text="Unlock lid setting (admin, one time)…",
                   command=act_unlock_lid).pack(anchor="w", pady=(0, 8))

    guard_var = tk.BooleanVar(value=engine.guard)
    auto_var = tk.BooleanVar(value=core.autostart_enabled())

    def _guard():
        engine.guard = guard_var.get()
        persist()
        refresh()

    def _auto():
        ok, detail = core.set_autostart(auto_var.get())
        if not ok:
            auto_var.set(core.autostart_enabled())
            msgbox(f"Couldn't change Start with Windows: {detail[:100]}", APP)
        saved["start_with_windows"] = core.autostart_enabled()
        persist()
        refresh()

    ttk.Checkbutton(outer, text="Battery guard (pause the hold on low battery)",
                    variable=guard_var, command=_guard, style="A.TCheckbutton").pack(anchor="w", pady=2)
    ttk.Checkbutton(outer, text="Start with Windows", variable=auto_var, command=_auto,
                    style="A.TCheckbutton").pack(anchor="w", pady=2)

    if core.legacy_restore_candidate() is not None:
        def _legacy():
            res = core.restore_legacy_backup()
            msgbox("Previous sleep settings restored." if all(ok for _, ok, _ in res)
                   else "Couldn't restore all previous settings.", APP)
        ttk.Button(outer, text="Restore my previous sleep settings",
                   command=_legacy).pack(anchor="w", pady=(8, 0))

    def _done(_e=None):
        saved["first_run_done"] = True
        persist()
        _first_run_win[0] = None
        try:
            win.destroy()
        except Exception:
            pass

    done = ttk.Button(outer, text="Done", command=_done, width=14)
    done.pack(anchor="e", pady=(16, 0))
    done.focus_set()
    win.bind("<Return>", _done)
    win.protocol("WM_DELETE_WINDOW", _done)
    _show_window(win, dark)


def act_quit(ic=None, it=None):
    persist()                  # captures last_mode while the hold is still live
    _quitting[0] = True        # nothing may overwrite it with "off" afterwards
    engine.deactivate("quit")  # releases the hold and restores power settings
    if not engine.restore_ok:
        msgbox("HustleOn couldn't restore your sleep settings. They will be restored "
               "next time it starts.", APP)
    ui.stop()
    if icon:
        icon.stop()


# ---------- menu ----------

def build_menu():
    # Caffeine-style labels: modes read as sentences, active mode checked.
    # Parents carry checks so custom values still show state.
    items = []
    if lid_state == "unknown":
        items.append(pystray.MenuItem("Lid status unknown — open Windows power settings",
                                      open_power_settings))
    elif lid_state == "unprotected" and engine.mode != "off":
        items.append(pystray.MenuItem("⚠ Lid will still sleep — open Windows power settings",
                                      open_power_settings))
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
                               and engine.timer_minutes == m)
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
            pystray.MenuItem("Also stop when hot (lid closed, best effort)", act_thermal_toggle,
                             checked=lambda it: engine.thermal_guard),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda it: f"Status: {power_brief()}"
                             + (" — tripped" if engine.battery_paused else ""),
                             None, enabled=False))),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start with Windows", act_autostart_toggle,
                         checked=lambda it: core.autostart_enabled()),
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
            elif "thermal" in events:
                notify(APP, "This PC is running hot with the lid closed — hold ended.")
                persist()
            if engine.mode != "off" or events:
                refresh_lid_status()
            check_alerts()
            if engine.mode != "off" and not engine.api_ok and api_was_ok:
                notify(APP, "Windows refused the stay-awake request — hold may be inactive.")
            api_was_ok = engine.api_ok if engine.mode != "off" else True
            refresh()
        except Exception as e:
            # Never skip the hold silently: retry it, escalate on repetition.
            fail_streak += 1
            core.log(f"heartbeat error: {e}")
            try:
                engine.reassert()
            except Exception:
                pass
            if fail_streak == 3:
                notify(APP, "HustleOn hit a repeated internal error — hold may be stale. Restart the app.")


def main():
    global icon, _mutex
    # Defensive: normally handled at import time for the frozen exe, before the mutex.
    if "--enforce-only" in sys.argv[1:]:
        raise SystemExit(core.main(["--enforce-only"]))
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
    core.log(f"HustleOn {core.__version__} starting")
    core.start_lid_watcher()
    # Crash/power-loss recovery BEFORE any resume logic.
    _, rec_ok = core.recover_applied()
    resume_last_mode()
    refresh_lid_status()
    icon = TrayIcon(APP, ICONS["off"], tooltip(), build_menu())
    threading.Thread(target=heartbeat, daemon=True).start()
    refresh()

    def _setup(ic):
        try:
            ic.visible = True
        except Exception:
            pass
        if not rec_ok:
            notify(APP, "Couldn't restore earlier sleep settings. Open About > Restore sleep defaults.")
        check_alerts()
        if not saved.get("first_run_done"):
            ui.call(_build_first_run)

    icon.run(setup=_setup)


if __name__ == "__main__":
    main()
