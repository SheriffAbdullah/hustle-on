"""Windows shell helpers: DPI awareness, tray icon size, dark mode, fonts.

Every call is best-effort: on failure the app falls back to the light theme /
96 DPI rather than crashing. Nothing here writes to the registry.
"""
import ctypes
import ctypes.wintypes

SM_CXSMICON = 49
USER_DEFAULT_DPI = 96
_dpi_done = [False]


def set_dpi_awareness():
    """Per-Monitor V2 where available. Must run before any Tk/pystray window."""
    if _dpi_done[0]:
        return
    _dpi_done[0] = True
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return
    except Exception:
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def system_dpi():
    try:
        d = int(ctypes.windll.user32.GetDpiForSystem())
        if d > 0:
            return d
    except Exception:
        pass
    return USER_DEFAULT_DPI


def primary_monitor_dpi():
    """Effective DPI of the primary monitor (where dialogs are centred)."""
    try:
        pt = ctypes.wintypes.POINT(0, 0)
        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        user32.MonitorFromPoint.argtypes = [ctypes.wintypes.POINT, ctypes.c_uint32]
        hmon = user32.MonitorFromPoint(pt, 1)   # MONITOR_DEFAULTTOPRIMARY
        dx, dy = ctypes.c_uint(), ctypes.c_uint()
        ctypes.windll.shcore.GetDpiForMonitor(ctypes.c_void_p(hmon), 0, ctypes.byref(dx),
                                              ctypes.byref(dy))   # MDT_EFFECTIVE_DPI
        if dx.value:
            return int(dx.value)
    except Exception:
        pass
    return system_dpi()


def tray_icon_px(dpi=None):
    """Pixel size Windows will use for a notification-area icon (SM_CXSMICON)."""
    dpi = dpi or system_dpi()
    try:
        fn = ctypes.windll.user32.GetSystemMetricsForDpi
        px = int(fn(SM_CXSMICON, int(dpi)))
        if px > 0:
            return max(16, min(64, px))
    except Exception:
        pass
    try:
        px = int(ctypes.windll.user32.GetSystemMetrics(SM_CXSMICON))
        if px > 0:
            return max(16, min(64, px))
    except Exception:
        pass
    return max(16, min(64, round(16 * dpi / USER_DEFAULT_DPI)))


def tk_scaling(dpi):
    """Tk 'scaling' value (pixels per point) for a DPI: dpi / 72."""
    return dpi / 72.0


def scale_px(n, dpi):
    return int(round(n * dpi / USER_DEFAULT_DPI))


def dark_mode():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        return False


def dark_title_bar(hwnd, dark=True):
    """DwmSetWindowAttribute(DWMWA_USE_IMMERSIVE_DARK_MODE=20)."""
    try:
        v = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(v), 4)
        return True
    except Exception:
        return False


def apply_menu_theme(dark=None):
    """Make native popup menus follow the app theme (uxtheme ordinals 135 =
    SetPreferredAppMode, 136 = FlushMenuThemes). Undocumented; any failure
    leaves the default light menu."""
    try:
        dark = dark_mode() if dark is None else dark
        ux = ctypes.WinDLL("uxtheme")
        set_mode = ux[135]
        flush = ux[136]
        set_mode.argtypes = [ctypes.c_int]
        set_mode.restype = ctypes.c_int
        set_mode(2 if dark else 3)    # ForceDark / ForceLight
        flush()
        return True
    except Exception:
        return False


def pick_font(root=None):
    """Segoe UI Variable Text on Windows 11, else Segoe UI, else TkDefault."""
    try:
        import tkinter.font as tkfont
        fams = set(tkfont.families(root))
        for name in ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI"):
            if name in fams:
                return name
    except Exception:
        pass
    return "Segoe UI"
