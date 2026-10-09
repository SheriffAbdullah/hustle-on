"""ui-refresh-and-release: icons, DPI helpers, wording, menu, prompts, release files.
Registry, powercfg and uxtheme are faked; nothing here touches the real system."""
import ctypes
import datetime
import importlib
import os
import re
import sys
import types

import pytest

pystray = pytest.importorskip("pystray")
pytest.importorskip("PIL")

import hustleon_core as core  # noqa: E402
import hustleon_icons as hi  # noqa: E402
import hustleon_win as hw  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def tray(power, monkeypatch):
    sys.modules.pop("hustleon_tray", None)
    t = importlib.import_module("hustleon_tray")
    monkeypatch.setattr(t, "icon", None)
    monkeypatch.setattr(t, "msgbox", lambda *a, **k: None)
    monkeypatch.setattr(core, "autostart_enabled", lambda: False)
    yield t
    t.engine.deactivate()
    sys.modules.pop("hustleon_tray", None)


# ---- icons ----
@pytest.mark.parametrize("size", [16, 20, 24, 32, 48, 64])
@pytest.mark.parametrize("state", ["off", "live", "paused"])
def test_icon_sizes_and_alpha(state, size):
    img = hi.render(state, size)
    assert img.size == (size, size) and img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] == 0               # transparent corners
    assert img.getpixel((size // 2, size // 2))[3] == 255


def test_icon_sizes_hand_tuned_and_interpolated():
    assert set(hi.TUNED_SIZES) >= {16, 20, 24, 32}
    assert hi.tuned(30)["ring"] < hi.tuned(32)["ring"] < hi.tuned(48)["ring"]
    assert hi.render("live", 40).size == (40, 40)     # non-tuned size still renders


def _white_ring(img, size):
    return any(all(c > 235 for c in img.getpixel((x, size // 2))[:3])
               and img.getpixel((x, size // 2))[3] == 255 for x in range(2, 14))


def test_live_has_white_ring_off_does_not_and_no_red():
    size = 64
    live, off, paused = (hi.render(s, size) for s in ("live", "off", "paused"))
    assert _white_ring(live, size) and not _white_ring(off, size)
    for img in (live, off, paused):                   # no red dot anywhere
        for r, g, b, a in img.getdata():
            assert not (a > 200 and r > 200 and g < 100 and b < 100)


def test_paused_is_amber_with_dark_bars():
    img = hi.render("paused", 64)
    r, g, b, _ = img.getpixel((8, 32))
    assert r > 230 and 140 < g < 200 and b < 60       # amber
    assert min(sum(img.getpixel((x, 32))[:3]) for x in range(20, 44)) < 150


def test_icon_cache_returns_same_object():
    assert hi.get("live", 24) is hi.get("live", 24)


def test_tray_icon_image_follows_state_and_size(tray, monkeypatch):
    monkeypatch.setattr(hw, "tray_icon_px", lambda dpi=None: 24)
    assert tray.icon_state() == "off" and tray.icon_image().size == (24, 24)
    tray.engine.mode = "timer"
    assert tray.icon_state() == "live"                # timer and until share live
    tray.engine.mode = "until"
    assert tray.icon_state() == "live"
    tray.engine.battery_paused = True
    assert tray.icon_state() == "paused"
    tray.engine.battery_paused = False
    tray.engine.mode = "off"


# ---- DPI / theme helpers ----
def test_tray_icon_px_from_system_metrics(monkeypatch):
    fake = types.SimpleNamespace(user32=types.SimpleNamespace(
        GetDpiForSystem=lambda: 192,
        GetSystemMetricsForDpi=lambda idx, dpi: 32 if (idx, dpi) == (49, 192) else 0))
    monkeypatch.setattr(hw.ctypes, "windll", fake)
    assert hw.system_dpi() == 192 and hw.tray_icon_px() == 32


def test_tray_icon_px_fallbacks(monkeypatch):
    monkeypatch.setattr(hw.ctypes, "windll", types.SimpleNamespace())   # every call raises
    assert hw.system_dpi() == 96
    assert hw.tray_icon_px() == 16
    assert hw.tray_icon_px(dpi=288) == 48


def test_tk_scaling_and_scale_px():
    assert hw.tk_scaling(96) == pytest.approx(96 / 72)
    assert hw.tk_scaling(288) == pytest.approx(4.0)
    assert hw.scale_px(24, 192) == 48 and hw.scale_px(10, 144) == 15


def test_dpi_awareness_prefers_per_monitor_v2(monkeypatch):
    calls = []

    class Fn:
        argtypes = None

        def __call__(self, ctx):
            calls.append(ctx.value)
            return 1

    monkeypatch.setattr(hw.ctypes, "windll", types.SimpleNamespace(
        user32=types.SimpleNamespace(SetProcessDpiAwarenessContext=Fn())))
    monkeypatch.setattr(hw, "_dpi_done", [False])
    hw.set_dpi_awareness()
    hw.set_dpi_awareness()                           # idempotent
    assert calls == [ctypes.c_void_p(-4).value]


def test_menu_theme_uses_uxtheme_ordinals_and_falls_back(monkeypatch):
    seen = []

    class UX:
        def __getitem__(self, ordinal):
            def fn(*a):
                seen.append((ordinal, a))
                return 0
            return fn

    monkeypatch.setattr(hw.ctypes, "WinDLL", lambda name: UX())
    assert hw.apply_menu_theme(dark=True) is True
    assert seen[0] == (135, (2,)) and seen[1][0] == 136
    seen.clear()
    hw.apply_menu_theme(dark=False)
    assert seen[0] == (135, (3,))

    def boom(name):
        raise OSError("no uxtheme")
    monkeypatch.setattr(hw.ctypes, "WinDLL", boom)
    assert hw.apply_menu_theme(dark=True) is False   # safe fallback


def test_dark_mode_reads_value_and_fails_to_light(monkeypatch):
    fake = types.SimpleNamespace(HKEY_CURRENT_USER=1, OpenKey=lambda *a: object(),
                                 QueryValueEx=lambda k, n: (0, 4))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert hw.dark_mode() is True
    fake.QueryValueEx = lambda k, n: (1, 4)
    assert hw.dark_mode() is False
    monkeypatch.setitem(sys.modules, "winreg", types.SimpleNamespace())
    assert hw.dark_mode() is False                   # failure -> light


def test_dark_title_bar_uses_attribute_20(monkeypatch):
    got = []
    dwm = types.SimpleNamespace(DwmSetWindowAttribute=lambda h, a, v, n: got.append((h, a, n)))
    monkeypatch.setattr(hw.ctypes, "windll", types.SimpleNamespace(dwmapi=dwm))
    assert hw.dark_title_bar(7) and got == [(7, 20, 4)]


# ---- wording, tooltip, menu ----
def test_tooltip_formats(tray, monkeypatch):
    monkeypatch.setattr(core, "get_power_status", lambda: (True, 100))
    tray.lid_state = "protected"
    assert tray.tooltip() == "HustleOn: Off (normal sleep) · Plugged in · Lid OK"
    monkeypatch.setattr(core, "get_power_status", lambda: (False, 64))
    tray.engine.mode = "on"
    tray.lid_state = "unprotected"
    assert tray.tooltip() == "HustleOn: Awake indefinitely · On battery 64% · Lid will sleep"
    tray.engine.mode = "timer"
    monkeypatch.setattr(tray, "fmt_remaining", lambda: "1h20m")
    assert tray.tooltip().startswith("HustleOn: Awake for 1h20m · On battery 64%")
    tray.engine.battery_paused = True
    assert "Paused" in tray.tooltip()
    tray.engine.battery_paused = False
    tray.engine.mode = "off"


def test_menu_order_and_labels(tray):
    tray.lid_state = "protected"
    texts = [str(i.text) for i in tray.build_menu().items if not str(i.text).startswith("-")]
    assert texts == ["Keep awake", "Keep awake for…", "Keep awake until…", "Off",
                     "Keep screen on", "Pause on low battery", "Start with Windows",
                     "About HustleOn…", "Quit"]
    items = tray.build_menu().items
    sub = items[1].submenu
    assert [str(i.text) for i in sub.items] == ["30 minutes", "1 hour", "2 hours", "8 hours",
                                                 "Custom…"]
    guard = [str(i.text) for i in next(x for x in items if str(x.text) == "Pause on low battery").submenu.items]
    assert guard[0] == "Enabled" and "Pause below 30%" in guard


def test_lid_warning_is_enabled_action_that_fixes(tray, monkeypatch):
    tray.lid_state = "unprotected"
    tray.engine.mode = "on"
    first = tray.build_menu().items[0]
    assert str(first.text) == "⚠ Lid close will still sleep this PC — fix…"
    assert first.enabled
    seen = []
    monkeypatch.setattr(tray, "open_power_settings", lambda *a: seen.append("settings"))
    monkeypatch.setattr(tray, "refresh_lid_status", lambda: None)
    first(None)
    assert seen == ["settings"]     # still unprotected after a re-apply: open Windows settings
    tray.engine.mode = "off"


def test_fix_lid_hidden_setting_requests_unlock(tray, monkeypatch):
    seen = []
    monkeypatch.setattr(tray, "act_unlock_lid", lambda *a: seen.append("unlock"))
    monkeypatch.setattr(tray, "refresh_lid_status", lambda: None)
    tray.lid_state = "unknown"
    tray.act_fix_lid()
    assert seen == ["unlock"]


def test_paused_line_and_resume(tray, monkeypatch):
    monkeypatch.setattr(core, "get_power_status", lambda: (False, 28))
    tray.engine.battery_paused = True
    tray.lid_state = "protected"
    items = tray.build_menu().items
    assert str(items[0].text) == "Paused: battery 28%. Plug in to resume."
    assert not items[0].enabled
    assert str(items[1].text) == "Resume" and items[1].enabled
    tray.engine.battery_paused = False


def test_deadline_appended_to_parent_label(tray):
    tray.lid_state = "protected"
    tray.engine.mode = "until"
    tray.engine.deadline = datetime.datetime(2030, 1, 4, 18, 0)
    texts = [str(i.text) for i in tray.build_menu().items if str(i.text)]
    assert "Keep awake until… (Fri 18:00)" in texts
    tray.engine.mode, tray.engine.deadline = "off", None


def test_alert_texts_avoid_the_word_hold(tray, monkeypatch):
    sent = []
    monkeypatch.setattr(tray, "notify", lambda t, m: sent.append((t, m)))
    tray.lid_state = "unprotected"
    tray.engine.mode = "on"
    tray.check_alerts()
    tray.engine.restore_ok = False
    tray.check_alerts()
    tray.engine.restore_ok, tray.engine.mode = True, "off"
    assert len(sent) == 2
    for t, m in sent:
        assert not re.search(r"\bhold\b", t + m, re.I)
    src = open(os.path.join(ROOT, "hustleon_tray.py"), encoding="utf-8").read()
    for call in re.findall(r"notify\((.*?)\)\n", src, re.S):
        assert not re.search(r"\bhold\b", call, re.I), call


# ---- validated prompts ----
@pytest.mark.parametrize("text,ok", [("90", True), ("1", True), ("1440", True), (" 30 ", True),
                                     ("0", False), ("1441", False), ("abc", False),
                                     ("1.5", False), ("-5", False)])
def test_validate_minutes(tray, text, ok):
    v, msg = tray.validate_minutes(text)
    assert (v is not None) is ok
    assert ok or msg


def test_validate_empty_has_no_message(tray):
    assert tray.validate_minutes("") == (None, "")
    assert tray.validate_hhmm("  ") == (None, "")


@pytest.mark.parametrize("text,out", [("17:30", "17:30"), ("7:05", "07:05"), (" 00:00 ", "00:00"),
                                      ("23:59", "23:59")])
def test_validate_hhmm_valid(tray, text, out):
    assert tray.validate_hhmm(text) == (out, None)


@pytest.mark.parametrize("text", ["25:99", "24:00", "12:60", "1730", "5pm", "12:5", "::"])
def test_validate_hhmm_invalid_explains_format(tray, text):
    v, msg = tray.validate_hhmm(text)
    assert v is None and "24-hour" in msg and "17:30" in msg


def test_bad_preset_notifies_in_plain_words(tray, monkeypatch):
    sent = []
    monkeypatch.setattr(tray, "notify", lambda t, m: sent.append((t, m)))
    tray.act_until("99:99")()
    assert sent and "17:30" in sent[0][1]


def test_custom_prompts_use_ui_thread(tray, monkeypatch):
    calls = []
    monkeypatch.setattr(tray.ui, "call", lambda fn: calls.append(fn) or True)
    tray.act_timer_custom()
    tray.act_until_custom()
    assert len(calls) == 2
    monkeypatch.setattr(tray.ui, "call", lambda fn: False)
    sent = []
    monkeypatch.setattr(tray, "notify", lambda t, m: sent.append(m))
    tray.act_timer_custom()
    assert sent


def test_about_rows_keys(tray):
    rows = tray._about_rows()
    assert [k for k, _ in rows] == ["Version", "Status", "Display", "Low-battery pause",
                                    "Sleep after", "Display off after", "Lid close"]
    assert dict(rows)["Version"] == core.__version__


# ---- release files ----
def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_version_single_source_pyproject():
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', _read("pyproject.toml"))
    assert m and core.__version__ == m.group(1)
    assert not re.search(r'(?m)^__version__\s*=\s*"\d', _read("hustleon_core.py"))


def test_license_is_mit_with_holder():
    t = _read("LICENSE")
    assert t.startswith("MIT License") and "Sheriff Abdullah" in t and "sheriffabdullah" in t


def test_changelog_keep_a_changelog():
    t = _read("CHANGELOG.md")
    assert "Keep a Changelog" in t and "## [Unreleased]" in t and core.__version__ in t


def test_readme_content_and_no_drift():
    t = _read("README.md")
    assert "Close the lid. Keep working. Auto-stops before your battery pays for it." in t
    assert t.count("img.shields.io") >= 5
    for name in ("PowerToys Awake", "Lidless", "ClosedAwake", "Modern Standby"):
        assert name in t
    assert "Tap" not in t and "dist/hustle-on.exe" not in t
    assert re.search(r"\bClick\b", t)
    for rel in re.findall(r"\]\((docs/[^)]+)\)", t) + re.findall(r'src="(docs/[^"]+)"', t):
        assert os.path.exists(os.path.join(ROOT, rel)), rel


def test_release_workflow_checks_tag_and_publishes():
    t = _read(".github/workflows/release.yml")
    assert "windows-latest" in t and "pytest" in t and "PyInstaller" in t
    assert "v*" in t and "pyproject.toml" in t and "upload-artifact" in t
    assert "hustle-on.exe" in t


def test_gallery_renders_every_size_on_light_and_dark():
    sys.path.insert(0, os.path.join(ROOT, "icons"))
    import render_gallery as rg
    g = rg.gallery()
    assert g.width > 800 and g.height > 600
    for theme in (rg.LIGHT, rg.DARK):
        assert rg.panel(theme).size[0] > 0
    assert rg.tray_states().size[0] > 0
    assert rg.LIGHT["bg"][:3] == (243, 243, 243)
