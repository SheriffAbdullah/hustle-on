"""Capture real HustleOn dialogs (ImageGrab) and render a menu mock into docs/.

Run from the repo root:  python docs/make_screenshots.py
Safe: the engine is never activated (no powercfg writes), nothing is persisted and the
registry is only read. Dark/light is forced by patching the theme probe, not the registry.
The native tray popup cannot be grabbed unattended, so the menu image is drawn with Pillow
from the real build_menu() items.
"""
import datetime
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PIL import Image, ImageDraw, ImageFont, ImageGrab  # noqa: E402

import hustleon_tray as t  # noqa: E402
import hustleon_win as hw  # noqa: E402

OUT = os.path.join(ROOT, "docs")


def grab_window(win):
    import ctypes
    import ctypes.wintypes as wt
    win.update()
    hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
    rc = wt.RECT()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rc), ctypes.sizeof(rc))
    return ImageGrab.grab(bbox=(rc.left, rc.top, rc.right, rc.bottom), all_screens=True)


def on_ui(fn, timeout=15):
    box, done = {}, threading.Event()

    def run():
        try:
            box["v"] = fn()
        except Exception as e:  # noqa: BLE001
            box["e"] = e
        done.set()
    assert t.ui.call(run)
    done.wait(timeout)
    if "e" in box:
        raise box["e"]
    return box.get("v")


def shoot(build, name, dark, setup=None):
    for attempt in range(4):
        try:
            return _shoot(build, name, dark, setup)
        except Exception as e:  # noqa: BLE001  (window vanished: retry)
            print('retry', name, e)
    raise SystemExit('could not capture ' + name)


def _shoot(build, name, dark, setup=None):
    hw.dark_mode = lambda: dark
    t.hw.dark_mode = lambda: dark
    result = {}

    def go():
        t._open_dialog[0] = None
        build()
        win = t._open_dialog[0]
        if setup:
            setup(win)
        win.update()
        win.after(700, lambda: result.setdefault("go", True))
        return win

    win = on_ui(go)
    time.sleep(1.2)

    def snap():
        result["img"] = grab_window(win)
        t._open_dialog[0] = None
        win.destroy()
    on_ui(snap)
    path = os.path.join(OUT, f"{name}-{'dark' if dark else 'light'}.png")
    result["img"].convert("RGB").save(path, optimize=True)
    print("wrote", path, result["img"].size)


def prompt_with_error(win):
    for w in win.winfo_children():
        pass
    entry = [c for c in _walk(win) if c.winfo_class() == "TEntry"][0]
    entry.insert(0, "25:99")


def _walk(w):
    for c in w.winfo_children():
        yield c
        yield from _walk(c)


def menu_mock(dark):
    """Pillow rendering of the real menu items in a Windows 11 style flyout (2x)."""
    t.lid_state = "protected"
    t.engine.mode = "timer"
    t.engine.deadline = datetime.datetime.now() + datetime.timedelta(hours=1, minutes=20, seconds=30)
    t.engine.timer_minutes = 120
    items = t.build_menu().items
    z = 2
    bg, fg, sub, hov, line = (("#2c2c2c", "#ffffff", "#9d9d9d", "#3a3a3a", "#424242") if dark
                              else ("#f9f9f9", "#1a1a1a", "#6b6b6b", "#eaeaea", "#e0e0e0"))
    try:
        f = ImageFont.truetype("segoeui.ttf", 14 * z)
        fi = ImageFont.truetype("seguisym.ttf", 14 * z)
    except OSError:
        f = fi = ImageFont.load_default()
    rows = []
    for it in items:
        txt = str(it.text)
        rows.append(("sep", "") if txt.startswith("-") else ("item", txt, it))
    w, ih, sh_, pad = 330 * z, 32 * z, 9 * z, 4 * z
    h = pad * 2 + sum(sh_ if r[0] == "sep" else ih for r in rows)
    img = Image.new("RGB", (w + 16 * z, h + 16 * z), "#1d1d1d" if dark else "#d9d9d9")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8 * z, 8 * z, 8 * z + w, 8 * z + h], radius=8 * z, fill=bg, outline=line)
    y = 8 * z + pad
    for r in rows:
        if r[0] == "sep":
            d.line([(8 * z + 12 * z, y + sh_ // 2), (8 * z + w - 12 * z, y + sh_ // 2)], fill=line, width=z)
            y += sh_
            continue
        txt, it = r[1], r[2]
        if getattr(it, "default", False) and False:
            pass
        checked = False
        try:
            checked = bool(it.checked)
        except Exception:
            pass
        if txt == "Keep awake for…" or txt.startswith("Keep awake for"):
            d.rounded_rectangle([8 * z + 5 * z, y, 8 * z + w - 5 * z, y + ih - z], radius=4 * z, fill=hov)
        if checked:
            d.text((8 * z + 18 * z, y + 5 * z), "✓", font=fi, fill=fg)
        d.text((8 * z + 40 * z, y + 5 * z), txt, font=f, fill=fg)
        if it.submenu is not None:
            d.text((8 * z + w - 30 * z, y + 5 * z), "›", font=fi, fill=sub)
        y += ih
    path = os.path.join(OUT, f"menu-{'dark' if dark else 'light'}.png")
    img.save(path, optimize=True)
    print("wrote", path)
    t.engine.mode, t.engine.deadline = "off", None


def main():
    os.makedirs(OUT, exist_ok=True)
    # a believable live state without touching powercfg or persisting anything
    t.engine.mode = "timer"
    t.engine.timer_minutes = 120
    t.engine.deadline = datetime.datetime.now() + datetime.timedelta(hours=1, minutes=20, seconds=30)
    t.engine.last_reassert = datetime.datetime.now()
    t.lid_state = "protected"
    for dark in (False, True):
        shoot(t._build_about, "about", dark)
    for dark in (False, True):
        shoot(lambda: t._build_prompt(
            "Keep awake until…", "Until what time?",
            "Use 24-hour time as HH:MM, for example 17:30. A time that already passed means tomorrow.",
            "e.g. 17:30", t.validate_hhmm, lambda v: None), "prompt-until", dark, prompt_with_error)
    for dark in (False, True):
        shoot(t._build_first_run, "first-run", dark)
    for dark in (False, True):
        menu_mock(dark)
    t.engine.mode, t.engine.deadline = "off", None
    t.ui.stop()
    os._exit(0)


if __name__ == "__main__":
    main()
