"""Render FINAL hustle-on icon set (user spec) + gallery.html preview."""
import os
from PIL import Image, ImageDraw

D = "icons/gallery"
W = (255, 255, 255, 255)
RED = (231, 76, 60, 255)
GRAY = (128, 128, 128, 255)
GREEN = (46, 204, 113, 255)
ORANGE = GREEN
BLUE = GREEN
PURPLE = GREEN


def disc(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=color)
    d.ellipse([4, 4, 60, 60], outline=(0, 0, 0, 100), width=2)  # rim: legible on light taskbars
    return img, d


def live_dot(img):
    ImageDraw.Draw(img).ellipse([40, 40, 60, 60], fill=RED)
    return img


def off():
    img, d = disc(GRAY)  # power button, no dot
    d.arc([19, 19, 45, 45], start=300, end=240, fill=W, width=6)
    d.line([32, 13, 32, 33], fill=W, width=6)
    return img


def on():
    img, d = disc(ORANGE)  # infinity, live
    d.ellipse([15, 23, 33, 41], outline=W, width=6)
    d.ellipse([31, 23, 49, 41], outline=W, width=6)
    return live_dot(img)


def timer():
    img, d = disc(BLUE)  # sand clock, live
    d.polygon([(23, 14), (41, 14), (32, 31)], fill=W)
    d.polygon([(32, 33), (23, 50), (41, 50)], fill=W)
    d.line([21, 12, 43, 12], fill=W, width=4)
    d.line([21, 52, 43, 52], fill=W, width=4)
    return live_dot(img)


def until():
    img, d = disc(PURPLE)  # wall clock, live
    d.ellipse([19, 19, 45, 45], fill=W)
    d.line([32, 32, 32, 22], fill=PURPLE, width=5)
    d.line([32, 32, 39, 36], fill=PURPLE, width=5)
    d.ellipse([29, 29, 35, 35], fill=PURPLE)
    return live_dot(img)


def paused():
    img, d = disc(GRAY)  # pause bars (YouTube-style), no dot: not live
    d.rounded_rectangle([24, 20, 30, 44], radius=2, fill=W)
    d.rounded_rectangle([34, 20, 40, 44], radius=2, fill=W)
    return img


FINAL = [("off", "Off", off), ("on", "On indefinitely", on), ("timer", "Timer", timer),
         ("until", "Until date/time", until), ("paused", "Paused (battery)", paused)]

os.makedirs(D, exist_ok=True)
cells = ""
for key, label, fn in FINAL:
    img = fn()
    p64, p16 = f"{D}/final-{key}-64.png", f"{D}/final-{key}-16.png"
    img.save(p64)
    img.resize((16, 16), Image.LANCZOS).save(p16)
    cells += (f"<td><img src='gallery/final-{key}-64.png' width=96><br>"
              f"<span class='traymock'><img src='gallery/final-{key}-16.png' width=16></span>"
              f"<br><small>{label}</small></td>")

html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>hustle-on FINAL icon set</title>
<style>body{{font-family:Segoe UI,Arial;margin:24px;background:#111;color:#eee}}
table{{border-collapse:collapse}}td{{border:1px solid #444;padding:14px;text-align:center}}
.traymock{{display:inline-block;background:#1f1f1f;padding:8px 14px;border-radius:6px;margin-top:8px}}
small{{color:#aaa}}h1{{font-size:22px}}p{{color:#bbb}}</style></head><body>
<h1>hustle-on FINAL icon set</h1>
<p>Your spec: gray power = off · green &infin; = on indefinitely · green hourglass = timer ·
green clock = until · gray pause-bars = battery-paused. Red dot = LIVE (only on the three live states).
Big = artwork, on-dark-bar = actual 16px tray size.</p>
<table><tr>{cells}</tr></table></body></html>"""
open("icons/icon-gallery.html", "w").write(html)
print("ok")
