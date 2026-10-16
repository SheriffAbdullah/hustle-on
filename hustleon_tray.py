"""hustle-on tray app - caffeine-style system-tray keep-awake.

Run:  python hustleon_tray.py        (double-click the built exe in v1 packaging)
"""
import ctypes
import ctypes.wintypes
import datetime
import os
import queue
import re
import sys
import threading

import hustleon_core as core
import hustleon_icons as hicons
import hustleon_win as hw

def _attach_parent_console():
    """A --noconsole exe has no stdout; attach to the launching console if any.

    Returns True when sys.stdout/sys.stderr now point at a console, False when
    there is no parent console (output is then discarded)."""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if not k32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            return False
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        return True
    except Exception:
        return False


def run_cli_if_requested(argv=None):
    """If any command-line args were given, run the core CLI and return its exit code.

    Returns None when there are no args (normal tray launch). Must run before the
    single-instance mutex and before any Tk/pystray object exists."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return None
    if getattr(sys, "frozen", False) or sys.stdout is None or sys.stderr is None:
        if not _attach_parent_console():
            if sys.stdout is None:
                sys.stdout = open(os.devnull, "w")
            if sys.stderr is None:
                sys.stderr = open(os.devnull, "w")
    try:
        return core.main(args)
    except SystemExit as e:  # argparse --version/--help/errors
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


# CLI flags (--version, --check, --enforce-only, ...) must run BEFORE heavy imports
# and before the single-instance check: a frozen exe has no script arg, and the tray
# is usually already running when the elevated copy starts.
if __name__ == "__main__":
    _rc = run_cli_if_requested()
    if _rc is not None:
        raise SystemExit(_rc)

try:
    from PIL import Image  # noqa: F401  (also checks Pillow is installed)
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


# ---------- icons (see hustleon_icons.py: supersampled, size-tuned, shape cues) ----------

def icon_state():
    """off | live | paused. Timer/until share the live icon; time is in the tooltip."""
    if engine.battery_paused:
        return "paused"
    return "off" if engine.mode == "off" else "live"


def icon_image(state=None, size=None):
    """PIL icon for the real notification-area size (SM_CXSMICON at the system DPI)."""
    return hicons.get(state or icon_state(), size or hw.tray_icon_px())


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


def act_fix_lid(ic=None, it=None):
    """Lid warning / 'Fix lid close...' action. Hidden setting (Modern Standby):
    one-time admin unlock. Otherwise retry applying it, then fall back to the
    Windows power settings page."""
    refresh_lid_status()
    if lid_state == "unknown":
        act_unlock_lid()
    elif lid_state == "unprotected":
        if engine.mode != "off":
            try:
                engine.reassert()
            except Exception:
                pass
            refresh_lid_status()
        if lid_state != "protected":
            open_power_settings()
    refresh()


def check_alerts():
    """Failure-only alerts, once per occurrence."""
    if engine.mode == "off":
        _alerted["unprotected"] = False
    elif lid_state == "unprotected" and not _alerted["unprotected"]:
        _alerted["unprotected"] = True
        notify("Lid close will still sleep this PC",
               "Click the HustleOn tray icon, then the warning at the top of the menu, to fix it.")
    if engine.restore_ok:
        _alerted["restore"] = False
    elif not _alerted["restore"]:
        _alerted["restore"] = True
        notify("Couldn't put your sleep settings back",
               "Open About HustleOn and choose Reset sleep settings.")


def after_change():
    persist()
    refresh_lid_status()
    check_alerts()
    refresh()


# ---------- click behavior ----------
# Upstream pystray shows the menu on RIGHT-click only; LEFT-click fires the
# default item (a surprise toggle + balloon). Caffeine-style = left-click menu.

class TrayIcon(pystray.Icon):
    def _assert_icon_handle(self):
        """Load the HICON at exactly the notification-area size. pystray's own
        loader asks for the big-icon size (SM_CXICON) and lets Windows rescale,
        which blurs the tray icon on high-DPI displays."""
        if self._icon_handle:
            return
        try:
            import tempfile
            from pystray import _win32 as backend
            px = self.icon.size[0]
            fd, path = tempfile.mkstemp(suffix=".ico")
            os.close(fd)
            try:
                self.icon.convert("RGBA").save(path, format="ICO", sizes=[(px, px)])
                handle = backend.win32.LoadImage(
                    None, path, backend.win32.IMAGE_ICON, px, px,
                    backend.win32.LR_LOADFROMFILE)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
            if not handle:
                raise OSError("LoadImage failed")
            self._icon_handle = handle
        except Exception:
            super()._assert_icon_handle()   # pystray default (still works, less crisp)


def _left_click_on_notify(self, wparam, lparam):
    from pystray import _win32 as _backend
    win32, wintypes = _backend.win32, _backend.wintypes
    if self._menu_handle and lparam in (win32.WM_LBUTTONUP, win32.WM_RBUTTONUP):
        try:
            refresh()  # live battery/mode data: menu never shows a stale snapshot
        except Exception:
            pass
        hw.apply_menu_theme()   # dark/light menu follows Windows (guarded, cosmetic)
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
    """Failures only (battery pause, Windows refusing keep-awake, bad input,
    lid not protected). Mode changes and timer expiry are silent."""
    try:
        if icon:
            icon.notify(msg, title)
    except Exception:
        pass


def msgbox(text, title=APP):
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)


def _paused_pct():
    if not engine.battery_paused:
        return None
    try:
        return core.get_power_status()[1]
    except Exception:
        return None


def _menu_key():
    return (engine.mode, engine.deadline.isoformat() if engine.deadline else None,
            engine.screen_on, engine.guard, engine.guard_threshold, engine.thermal_guard,
            engine.battery_paused, _paused_pct(), engine.api_ok, lid_state,
            engine.timer_minutes, core.autostart_enabled())


_last_icon_key = [None]


def refresh():
    """Icon art + tooltip always; menu rebuilt only on state change (avoids
    mid-navigation rebuilds). Wakes the heartbeat for an immediate tick."""
    global icon
    _heartbeat_wake.set()
    if not icon:
        return
    state, px = icon_state(), hw.tray_icon_px()
    if (state, px) != _last_icon_key[0]:      # re-render if the DPI/tray size changed
        _last_icon_key[0] = (state, px)
        icon.icon = icon_image(state, px)
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
        return "Power unknown"
    if ac:
        return "Plugged in"
    return f"On battery {pct if pct is not None else '?'}%"


def lid_brief():
    return {"protected": "Lid OK", "unprotected": "Lid will sleep"}.get(lid_state, "Lid unknown")


def tooltip():
    if engine.battery_paused:
        state = "Paused"
    elif engine.mode == "off":
        state = "Off (normal sleep)"
    elif engine.mode == "on":
        state = "Awake indefinitely"
    elif engine.mode == "timer":
        state = f"Awake for {fmt_remaining()}" if fmt_remaining() else "Awake on a timer"
    else:
        state = f"Awake until {engine.deadline:%a %H:%M}" if engine.deadline else "Awake until…"
    return f"{APP}: {state} · {power_brief()} · {lid_brief()}"


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
            hw.set_dpi_awareness()   # Per-Monitor V2 BEFORE the first Tk window exists
            root = tk.Tk()
            root.withdraw()  # hidden for life; dialogs are Toplevels
            try:
                root.tk.call("tk", "scaling", hw.tk_scaling(hw.primary_monitor_dpi()))
            except Exception:
                pass
            try:
                from PIL import ImageTk
                root._icon_ref = ImageTk.PhotoImage(_current_icon_image(48))
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
            notify("Still on low battery",
                   f"Battery is at {pct}%. Plug in to resume keep-awake.")
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


# ---------- custom time prompts: inline validation, no popup errors ----------

HHMM_HELP = "Use 24-hour time as HH:MM, for example 17:30 (hours 00-23, minutes 00-59)."
MINUTES_HELP = "Enter whole minutes from 1 to 1440 (24 hours), for example 90."


def validate_minutes(text):
    """-> (minutes, None) when valid, else (None, message). Empty input: (None, '')."""
    t = text.strip()
    if not t:
        return None, ""
    if not t.isdigit() or not 1 <= int(t) <= 1440:
        return None, MINUTES_HELP
    return int(t), None


def validate_hhmm(text):
    """-> ('HH:MM', None) when valid 24-hour time, else (None, message)."""
    t = text.strip()
    if not t:
        return None, ""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None, HHMM_HELP
    return f"{int(m.group(1)):02d}:{m.group(2)}", None


def act_timer_custom(ic=None, it=None):
    if not ui.call(lambda: _build_prompt(
            "Keep awake for…", "How many minutes?", MINUTES_HELP, "e.g. 90",
            validate_minutes, lambda v: _in_worker(act_timer(v)))):
        notify("Custom time unavailable", "This copy of HustleOn can't show windows (Tk is missing).")


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
            notify("Couldn't read that time", f"'{hhmm}' isn't valid. {HHMM_HELP}")
            return
        engine.battery_paused = False
        engine.activate("until", until=dt)
        after_change()
    return _run


def act_until_custom(ic=None, it=None):
    if not ui.call(lambda: _build_prompt(
            "Keep awake until…", "Until what time?",
            "Use 24-hour time as HH:MM, for example 17:30. A time that already passed means tomorrow.",
            "e.g. 17:30", validate_hhmm, lambda v: _in_worker(act_until(v)))):
        notify("Custom time unavailable", "This copy of HustleOn can't show windows (Tk is missing).")


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
        notify("Couldn't change Start with Windows", detail[:80])
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


def _about_rows():
    """Key/value rows for the About grid."""
    status = {
        "off": "Off (normal sleep)",
        "on": "Awake indefinitely",
        "timer": f"Awake for {fmt_remaining()}" if fmt_remaining() else "Awake on a timer",
        "until": f"Awake until {engine.deadline:%a %H:%M}" if engine.deadline else "Awake until…",
    }[engine.mode]
    if engine.battery_paused:
        status = "Paused (battery low)"
    ps = core.power_summary()
    return [
        ("Version", core.__version__),
        ("Status", status),
        ("Display", "Kept on" if engine.screen_on else "May turn off (PC stays awake)"),
        ("Low-battery pause",
         f"On, below {engine.guard_threshold}% · {power_brief()}" if engine.guard
         else f"Off · {power_brief()}"),
        ("Sleep after", ps["sleep"]),
        ("Display off after", ps["display"]),
        ("Lid close", ps["lid"]),
    ]


def _about_body():
    return "\n".join(f"{k}: {v}" for k, v in _about_rows())


def _current_icon_image(size=48):
    return icon_image(icon_state(), size)


# ---------- dialog shell: Windows 11 look, DPI + dark-mode aware ----------

class _Shell:
    """Window + styling shared by About, first-run and the time prompts."""


_open_dialog = [None]   # touched only on the UI thread: at most ONE dialog at a time


def _raise_existing():
    w = _open_dialog[0]
    if w is None:
        return False
    try:
        w.deiconify()
        w.lift()
        w.focus_force()
        return True
    except Exception:
        _open_dialog[0] = None
        return False


def _new_dialog(title):
    """Create a hidden, themed Toplevel with body + footer frames."""
    import tkinter as tk
    from tkinter import ttk
    sh = _Shell()
    win = tk.Toplevel(ui.root)
    _open_dialog[0] = win
    win.withdraw()                      # stay hidden until laid out and positioned
    win.title(title)
    win.resizable(False, False)
    dpi = hw.primary_monitor_dpi()
    try:
        win.tk.call("tk", "scaling", hw.tk_scaling(dpi))   # sharp, not tiny, not blurry
    except Exception:
        pass
    px = lambda n: hw.scale_px(n, dpi)  # noqa: E731
    fam = hw.pick_font(win)
    dark = hw.dark_mode()
    if dark:
        bg, fg, sub, foot, field, line = "#202020", "#ffffff", "#a0a0a0", "#2b2b2b", "#2d2d2d", "#454545"
    else:
        bg, fg, sub, foot, field, line = "#ffffff", "#1a1a1a", "#5f5f5f", "#f3f3f3", "#ffffff", "#d0d0d0"
    try:
        import tkinter.font as tkfont
        for n in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkCaptionFont"):
            tkfont.nametofont(n).configure(family=fam, size=10)
    except Exception:
        pass
    win.configure(bg=bg)
    st = ttk.Style(win)
    try:
        st.theme_use("clam" if dark else "vista")
    except Exception:
        pass
    pad = (px(14), px(6))
    if dark:
        st.configure("TButton", background="#333333", foreground=fg, bordercolor=line,
                     lightcolor="#333333", darkcolor="#333333", focuscolor="#333333", padding=pad)
        st.map("TButton", background=[("active", "#3d3d3d"), ("pressed", "#2a2a2a")])
        st.configure("TEntry", fieldbackground=field, foreground=fg, insertcolor=fg,
                     bordercolor=line, lightcolor=line, darkcolor=line, padding=px(5))
    else:
        st.configure("TButton", padding=pad)
        st.configure("TEntry", padding=px(4))
    st.configure("A.TFrame", background=bg)
    st.configure("F.TFrame", background=foot)
    st.configure("T.TLabel", background=bg, foreground=fg, font=(fam, 18, "bold"))
    st.configure("K.TLabel", background=bg, foreground=sub, font=(fam, 10))
    st.configure("V.TLabel", background=bg, foreground=fg, font=(fam, 10))
    st.configure("S.TLabel", background=bg, foreground=sub, font=(fam, 10))
    st.configure("H.TLabel", background=bg, foreground=fg, font=(fam, 12, "bold"))
    st.configure("E.TLabel", background=bg, foreground="#e5484d" if dark else "#c42b1c",
                 font=(fam, 9))
    st.configure("A.TCheckbutton", background=bg, foreground=fg, font=(fam, 10))
    st.map("A.TCheckbutton", background=[("active", bg)])
    body = ttk.Frame(win, style="A.TFrame", padding=(px(28), px(24), px(28), px(20)))
    footer = ttk.Frame(win, style="F.TFrame", padding=(px(28), px(14), px(28), px(14)))
    footer.pack(side="bottom", fill="x")
    body.pack(side="top", fill="both", expand=True)
    sh.win, sh.body, sh.footer, sh.dark, sh.px, sh.fam = win, body, footer, dark, px, fam
    sh.dpi = dpi
    try:
        from PIL import ImageTk
        win._icon_ref = [ImageTk.PhotoImage(_current_icon_image(32))]
        win.iconphoto(False, *win._icon_ref)
    except Exception:
        pass

    def close(_e=None):
        _open_dialog[0] = None
        try:
            win.destroy()
        except Exception:
            pass
    sh.close = close
    win.protocol("WM_DELETE_WINDOW", close)
    win.bind("<Escape>", close)
    return sh


def _button_row(sh, specs, default=None):
    """Equal-width buttons, right-aligned in the footer. specs: [(text, cmd)]."""
    from tkinter import ttk
    row = ttk.Frame(sh.footer, style="F.TFrame")
    row.pack(side="right")
    btns = {}
    for n, (txt, cmd) in enumerate(specs):
        b = ttk.Button(row, text=txt, command=cmd, takefocus=True)
        b.grid(row=0, column=n, padx=(0 if n == 0 else sh.px(8), 0), sticky="ew")
        row.columnconfigure(n, uniform="btn")
        if txt == default:
            try:
                b.configure(default="active")
            except Exception:
                pass
            b.focus_set()
        btns[txt] = b
    return btns


def _header(sh, title, subtitle=None):
    from tkinter import ttk
    head = ttk.Frame(sh.body, style="A.TFrame")
    head.pack(fill="x", pady=(0, sh.px(16)))
    try:
        from PIL import ImageTk
        sh.win._hdr_ref = ImageTk.PhotoImage(_current_icon_image(sh.px(40)))
        ttk.Label(head, image=sh.win._hdr_ref, style="K.TLabel").pack(
            side="left", padx=(0, sh.px(14)))
    except Exception:
        pass
    col = ttk.Frame(head, style="A.TFrame")
    col.pack(side="left", fill="x")
    ttk.Label(col, text=title, style="T.TLabel").pack(anchor="w")
    if subtitle:
        ttk.Label(col, text=subtitle, style="S.TLabel").pack(anchor="w")


def _show_window(win, dark):
    """Dark title bar, centre on the primary work area, then reveal."""
    win.update_idletasks()
    if dark:
        try:
            hw.dark_title_bar(ctypes.windll.user32.GetParent(win.winfo_id()), True)
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


def _build_about():
    from tkinter import ttk
    if _raise_existing():
        return
    sh = _new_dialog("About HustleOn")
    px = sh.px
    _header(sh, "HustleOn", "Close the lid. Keep working.")
    grid = ttk.Frame(sh.body, style="A.TFrame")
    grid.pack(fill="x")
    grid.columnconfigure(1, weight=1)

    def _fill():
        for c in grid.winfo_children():
            c.destroy()
        for i, (k, v) in enumerate(_about_rows()):
            ttk.Label(grid, text=k, style="K.TLabel").grid(
                row=i, column=0, sticky="nw", padx=(0, px(24)), pady=px(3))
            ttk.Label(grid, text=v, style="V.TLabel", wraplength=px(300), justify="left").grid(
                row=i, column=1, sticky="nw", pady=px(3))

    def _fix():
        act_fix_lid()
        _fill()

    def _reset():
        if engine.applied:
            msgbox("Keep awake is on. Turn it Off and HustleOn puts your sleep settings back "
                   "automatically.", APP)
            return
        res = core.restore_power_defaults()
        refresh_lid_status()
        _fill()
        if not all(ok for _, ok, _ in res):
            msgbox("Nothing to reset, or some settings could not be put back.", APP)

    _fill()
    _button_row(sh, [("Fix lid close…", _fix), ("Reset sleep settings", _reset),
                     ("Close", sh.close)], default="Close")
    sh.win.bind("<Return>", sh.close)
    _show_window(sh.win, sh.dark)


def act_about(ic=None, it=None):
    if not ui.call(_build_about):
        msgbox(f"HustleOn {core.__version__}\n\n{_about_body()}", "About HustleOn")


def _build_prompt(title, heading, hint, example, validate, on_ok):
    """Small dialog with inline validation (no popup errors)."""
    import tkinter as tk
    from tkinter import ttk
    if _raise_existing():
        return
    sh = _new_dialog(title)
    px = sh.px
    ttk.Label(sh.body, text=heading, style="H.TLabel").pack(anchor="w")
    ttk.Label(sh.body, text=hint, style="S.TLabel", wraplength=px(340),
              justify="left").pack(anchor="w", pady=(px(4), px(12)))
    var = tk.StringVar()
    entry = ttk.Entry(sh.body, textvariable=var, width=18)
    entry.pack(anchor="w")
    err = ttk.Label(sh.body, text="", style="E.TLabel", wraplength=px(340), justify="left")
    err.pack(anchor="w", pady=(px(6), 0))
    ttk.Label(sh.body, text=example, style="S.TLabel").pack(anchor="w", pady=(px(2), 0))
    btns = _button_row(sh, [("OK", None), ("Cancel", sh.close)], default="OK")
    ok = btns["OK"]

    def _check(*_):
        val, msg = validate(var.get())
        err.configure(text=msg or "")
        ok.state(["!disabled"] if val is not None else ["disabled"])
        return val

    def _accept(_e=None):
        val = _check()
        if val is None:
            return "break"
        sh.close()
        on_ok(val)
        return "break"

    ok.configure(command=_accept)
    var.trace_add("write", _check)
    _check()
    sh.win.bind("<Return>", _accept)
    _show_window(sh.win, sh.dark)
    entry.focus_set()


# ---------- first-run setup ----------

def _build_first_run():
    import tkinter as tk
    from tkinter import ttk
    if _raise_existing():
        return
    sh = _new_dialog("Welcome to HustleOn")
    px = sh.px
    _header(sh, "Welcome to HustleOn", "Quick setup")
    ttk.Label(sh.body, text="HustleOn changes your lid and sleep settings only while keep-awake "
                            "is on, and puts them back when it ends.", style="S.TLabel",
              wraplength=px(400), justify="left").pack(anchor="w", pady=(0, px(12)))

    lid_text = {"protected": "Lid close: Do Nothing (ready)",
                "unprotected": "Lid close: will be set to Do Nothing while keep-awake is on",
                "unknown": "Lid close: hidden by Windows (Modern Standby)"}
    st = core.lid_status()
    ttk.Label(sh.body, text=lid_text[st], style="V.TLabel").pack(anchor="w")
    ttk.Button(sh.body, text="Open Windows power settings",
               command=open_power_settings).pack(anchor="w", pady=(px(6), px(8)))
    if st == "unknown" and not saved.get("unhide_done"):
        ttk.Button(sh.body, text="Unlock lid setting (admin, one time)…",
                   command=act_unlock_lid).pack(anchor="w", pady=(0, px(8)))

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

    ttk.Checkbutton(sh.body, text="Pause keep-awake on low battery", variable=guard_var,
                    command=_guard, style="A.TCheckbutton").pack(anchor="w", pady=px(3))
    ttk.Checkbutton(sh.body, text="Start with Windows", variable=auto_var, command=_auto,
                    style="A.TCheckbutton").pack(anchor="w", pady=px(3))

    if core.legacy_restore_candidate() is not None:
        def _legacy():
            res = core.restore_legacy_backup()
            msgbox("Previous sleep settings restored." if all(ok for _, ok, _ in res)
                   else "Couldn't restore all previous settings.", APP)
        ttk.Button(sh.body, text="Restore my previous sleep settings",
                   command=_legacy).pack(anchor="w", pady=(px(8), 0))

    def _done(_e=None):
        saved["first_run_done"] = True
        persist()
        sh.close()

    _button_row(sh, [("Done", _done)], default="Done")
    sh.win.bind("<Return>", _done)
    sh.win.protocol("WM_DELETE_WINDOW", _done)
    _show_window(sh.win, sh.dark)


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
    # Plain-language labels; the active mode is checked and parents carry the
    # remaining time / deadline so custom values still show state.
    items = []
    if lid_state == "unknown":
        items.append(pystray.MenuItem("Lid status unknown — check Windows power settings",
                                      open_power_settings))
    elif lid_state == "unprotected" and engine.mode != "off":
        items.append(pystray.MenuItem("⚠ Lid close will still sleep this PC — fix…", act_fix_lid))
    if engine.battery_paused:
        pct = _paused_pct()
        items.append(pystray.MenuItem(
            f"Paused: battery {pct if pct is not None else '?'}%. Plug in to resume.",
            None, enabled=False))
        items.append(pystray.MenuItem("Resume", act_resume))
    if items:
        items.append(pystray.Menu.SEPARATOR)
    for_label = "Keep awake for…"
    if engine.mode == "timer" and fmt_remaining():
        for_label += f" ({fmt_remaining()} left)"
    until_label = "Keep awake until…"
    if engine.mode == "until" and engine.deadline:
        until_label += f" ({engine.deadline:%a %H:%M})"
    items += [
        pystray.MenuItem("Keep awake", act_on,
                         checked=lambda it: engine.mode == "on",
                         default=(engine.mode == "off")),
        pystray.MenuItem(for_label, pystray.Menu(
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
        pystray.MenuItem("Off", act_off,
                         checked=lambda it: engine.mode == "off",
                         default=(engine.mode != "off")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Keep screen on", act_toggle_screen,
                         checked=lambda it: engine.screen_on),
        pystray.MenuItem("Pause on low battery", pystray.Menu(
            pystray.MenuItem("Enabled", act_guard_toggle,
                             checked=lambda it: engine.guard),
            pystray.Menu.SEPARATOR,
            *[pystray.MenuItem(f"Pause below {p}%", act_guard_threshold(p),
                               checked=lambda it, p=p: engine.guard_threshold == p)
              for p in (10, 15, 20, 30, 40, 50)],
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Also stop when hot (lid closed, best effort)", act_thermal_toggle,
                             checked=lambda it: engine.thermal_guard),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda it: f"Status: {power_brief()}"
                             + (" — paused" if engine.battery_paused else ""),
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
                notify("Keep-awake paused",
                       f"{power_brief()}. Plug in to resume, or click Resume in the menu.")
                persist()
            elif "thermal" in events:
                notify("PC running hot", "HustleOn turned keep-awake off because this PC is hot with the lid closed.")
                persist()
            if engine.mode != "off" or events:
                refresh_lid_status()
            check_alerts()
            if engine.mode != "off" and not engine.api_ok and api_was_ok:
                notify("Windows blocked keep-awake", "Windows refused the stay-awake request, so this PC may sleep.")
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
                notify("HustleOn needs a restart", "It hit repeated errors and may not be keeping this PC awake.")


def main():
    global icon, _mutex
    # Defensive: normally handled at import time for the frozen exe, before the mutex.
    rc = run_cli_if_requested()
    if rc is not None:
        raise SystemExit(rc)
    # Crisp menus/icons/dialogs on high-DPI: declare Per-Monitor V2 before any
    # window exists (the manifest covers the exe; this covers running from source).
    hw.set_dpi_awareness()
    hw.apply_menu_theme()
    _mutex = ensure_single_instance()
    core.log(f"HustleOn {core.__version__} starting")
    core.start_lid_watcher()
    # Crash/power-loss recovery BEFORE any resume logic.
    _, rec_ok = core.recover_applied()
    resume_last_mode()
    refresh_lid_status()
    icon = TrayIcon(APP, icon_image("off"), tooltip(), build_menu())
    threading.Thread(target=heartbeat, daemon=True).start()
    refresh()

    def _setup(ic):
        try:
            ic.visible = True
        except Exception:
            pass
        if not rec_ok:
            notify("Couldn't put your sleep settings back",
                   "Open About HustleOn and choose Reset sleep settings.")
        check_alerts()
        if not saved.get("first_run_done"):
            ui.call(_build_first_run)

    icon.run(setup=_setup)


if __name__ == "__main__":
    main()
