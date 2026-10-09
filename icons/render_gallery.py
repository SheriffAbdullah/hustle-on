"""Render the HustleOn icon gallery from the REAL tray icon code (hustleon_icons.py).

Writes (run from the repo root:  python icons/render_gallery.py):
  docs/icon-gallery.png   every state at 16/20/24/32/48/64 on light (#f3f3f3) and dark (#202020)
  docs/tray-states.png    realistic light + dark taskbar mocks at 100% / 150% / 200% / 300%

The sizes are exactly the ones the tray picks from GetSystemMetrics(SM_CXSMICON), so
what you see here is what ships. Light is the hard case: it checks that the
disc edge and the white ring stay legible on a pale taskbar.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import hustleon_icons as hi  # noqa: E402

DOCS = os.path.join(ROOT, "docs")
SIZES = (16, 20, 24, 32, 48, 64)
STATES = (("off", "Off"), ("live", "Awake (indefinite, timer, until)"), ("paused", "Paused (low battery)"))
TRAY_PX = {100: 16, 150: 24, 200: 32, 300: 48}
LIGHT = dict(bg=(243, 243, 243, 255), fg=(26, 26, 26, 255), sub=(96, 96, 96, 255), name="Light")
DARK = dict(bg=(32, 32, 32, 255), fg=(255, 255, 255, 255), sub=(160, 160, 160, 255), name="Dark")


def font(size, bold=False):
    for f in (("segoeuib.ttf" if bold else "segoeui.ttf"), "arial.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


ZOOM = {16: 5, 20: 4, 24: 4, 32: 3, 48: 2, 64: 1}


def panel(theme):
    """One theme panel: label + big artwork + each tray size (nearest-zoomed for inspection)."""
    pad, row_h = 24, 120
    label_w, art_w = 250, 120
    cell = [s * ZOOM[s] + 24 for s in SIZES]
    w = pad * 2 + label_w + art_w + sum(cell)
    h = pad * 2 + 36 + row_h * len(STATES)
    img = Image.new("RGBA", (w, h), theme["bg"])
    d = ImageDraw.Draw(img)
    d.text((pad, pad - 6), f"{theme['name']} taskbar", font=font(18, True), fill=theme["fg"])
    x0 = pad + label_w + art_w
    for i, s in enumerate(SIZES):
        d.text((x0 + sum(cell[:i]) + 6, pad + 22), f"{s}px", font=font(12), fill=theme["sub"])
    for r, (key, label) in enumerate(STATES):
        y = pad + 40 + r * row_h
        d.text((pad, y + row_h // 2 - 18), label, font=font(14), fill=theme["fg"])
        art = hi.render(key, 96)
        img.alpha_composite(art, (pad + label_w, y + (row_h - 96) // 2 - 6))
        for i, s in enumerate(SIZES):
            ic = hi.render(key, s)
            zoom = ZOOM[s]
            big = ic.resize((s * zoom, s * zoom), Image.NEAREST)
            img.alpha_composite(big, (x0 + sum(cell[:i]) + 6, y + (row_h - s * zoom) // 2 - 6))
    return img


def gallery():
    a, b = panel(LIGHT), panel(DARK)
    out = Image.new("RGBA", (max(a.width, b.width), a.height + b.height), (0, 0, 0, 255))
    out.paste(a, (0, 0))
    out.paste(b, (0, a.height))
    return out


def taskbar_mock(theme, scale):
    """A Windows 11-style taskbar corner at `scale`% showing the three tray states."""
    px = hi_size = TRAY_PX[scale]
    gap = round(px * 0.9)
    bar_h = round(48 * scale / 100)
    w = round(380 * scale / 100)
    taskbar = (252, 252, 252, 255) if theme is LIGHT else (28, 28, 28, 255)
    img = Image.new("RGBA", (w, bar_h), taskbar)
    d = ImageDraw.Draw(img)
    x = round(14 * scale / 100)
    y = (bar_h - px) // 2
    for key, _ in STATES:
        img.alpha_composite(hi.render(key, hi_size), (x, y))
        x += px + gap
    clock = font(round(12 * scale / 100))
    d.text((w - round(86 * scale / 100), bar_h // 2 - round(15 * scale / 100)), "9:41 AM",
           font=clock, fill=theme["fg"])
    d.text((w - round(86 * scale / 100), bar_h // 2 + round(1 * scale / 100)), "10/9/2026",
           font=clock, fill=theme["sub"])
    return img


def tray_states():
    scales = (100, 150, 200, 300)
    mocks = [(t, s, taskbar_mock(t, s)) for t in (LIGHT, DARK) for s in scales]
    pad = 20
    w = max(m.width for _, _, m in mocks) * 2 + pad * 3 + 80
    h = sum(max(mocks[i][2].height, mocks[i + 4][2].height) + 26 for i in range(4)) + pad * 2
    out = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    d = ImageDraw.Draw(out)
    y = pad
    colw = max(m.width for _, _, m in mocks)
    for i, s in enumerate(scales):
        d.text((pad, y), f"{s}% scaling: {TRAY_PX[s]}px tray icon",
               font=font(13), fill=(70, 70, 70, 255))
        y += 22
        for j in range(2):
            m = mocks[j * 4 + i][2]
            out.paste(m, (pad + j * (colw + pad + 40), y))
        y += max(mocks[i][2].height, mocks[i + 4][2].height) + 4
    return out.crop((0, 0, w, y + pad // 2))


def main():
    os.makedirs(DOCS, exist_ok=True)
    gallery().convert("RGB").save(os.path.join(DOCS, "icon-gallery.png"), optimize=True)
    tray_states().convert("RGB").save(os.path.join(DOCS, "tray-states.png"), optimize=True)
    print("wrote docs/icon-gallery.png and docs/tray-states.png")


if __name__ == "__main__":
    main()
