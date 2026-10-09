"""Render hustle-on icon candidates (64px) for visual comparison."""
import math
from PIL import Image, ImageDraw

OUT = "icons/candidates"

GREEN = (46, 204, 113, 255)
GRAY = (128, 128, 128, 255)
WHITE = (255, 255, 255, 255)


def base(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=color)
    return img, d


def ring():
    img, d = base(GREEN)
    d.ellipse([20, 20, 44, 44], fill=(0, 0, 0, 0))
    d.ellipse([22, 22, 42, 42], fill=WHITE)  # current design
    return img


def power():
    img, d = base(GREEN)
    d.arc([18, 18, 46, 46], start=300, end=240, fill=WHITE, width=5)
    d.line([32, 14, 32, 34], fill=WHITE, width=5)  # power symbol
    return img


def cup():
    img, d = base(GREEN)
    d.rounded_rectangle([20, 26, 40, 46], radius=4, fill=WHITE)  # mug
    d.arc([38, 28, 48, 40], start=270, end=90, fill=WHITE, width=4)  # handle
    for x in (26, 32):  # steam
        d.line([x, 14, x, 22], fill=WHITE, width=3)
    return img


def eye():
    img, d = base(GREEN)
    d.ellipse([14, 24, 50, 42], fill=WHITE)  # open eye = awake
    d.ellipse([26, 26, 38, 38], fill=GREEN)
    return img


def zzz():
    img, d = base(GRAY)
    d.text((20, 16), "Z", fill=WHITE)  # off-state style reference
    d.line([16, 46, 48, 46], fill=(231, 76, 60, 255), width=5)  # slash = no sleep
    return img


if __name__ == "__main__":
    import os
    os.makedirs(OUT, exist_ok=True)
    for name, fn in [("A-ring", ring), ("B-power", power), ("C-cup", cup),
                     ("D-eye", eye), ("E-zzz-off", zzz)]:
        fn().save(f"{OUT}/{name}.png")
        print("wrote", name)
