"""Tray icon rendering for HustleOn (Pillow only, no binary assets).

State cues never rely on colour alone:
  off     gray disc, white power glyph
  live    green disc, white OUTER RING + infinity glyph (timer/until share it)
  paused  amber disc, dark pause bars

Every icon is drawn at SUPERSAMPLE x the target size and reduced with LANCZOS,
so it stays crisp at 100-300% display scaling. Sizes 16/20/24/32 have
hand-tuned stroke widths; other sizes (48/64 or odd DPI values) interpolate.
"""
from PIL import Image, ImageDraw

SUPERSAMPLE = 8
TUNED_SIZES = (16, 20, 24, 32, 48, 64)

GRAY = (120, 120, 120, 255)
GREEN = (30, 170, 90, 255)
AMBER = (255, 176, 0, 255)
WHITE = (255, 255, 255, 255)
DARK = (32, 32, 32, 255)

# Hand-tuned stroke widths in OUTPUT pixels:
#   rim    green/gray/amber edge outside the white ring (live only)
#   ring   white outer ring width (live only)
#   glyph  stroke width of the infinity loops / power glyph
#   bar    pause-bar width
_TUNE = {
    16: dict(rim=0.8, ring=1.2, glyph=1.55, bar=2.6),
    20: dict(rim=1.0, ring=1.4, glyph=1.9, bar=3.2),
    24: dict(rim=1.1, ring=1.7, glyph=2.3, bar=3.8),
    32: dict(rim=1.5, ring=2.2, glyph=3.0, bar=5.0),
    48: dict(rim=2.2, ring=3.2, glyph=4.5, bar=7.5),
    64: dict(rim=3.0, ring=4.2, glyph=6.0, bar=10.0),
}


def tuned(size):
    """Stroke widths for `size`: exact table row, else linear interpolation."""
    if size in _TUNE:
        return dict(_TUNE[size])
    keys = sorted(_TUNE)
    if size <= keys[0]:
        k = _TUNE[keys[0]]
        return {n: v * size / keys[0] for n, v in k.items()}
    if size >= keys[-1]:
        k = _TUNE[keys[-1]]
        return {n: v * size / keys[-1] for n, v in k.items()}
    lo = max(k for k in keys if k < size)
    hi = min(k for k in keys if k > size)
    t = (size - lo) / (hi - lo)
    return {n: _TUNE[lo][n] + (_TUNE[hi][n] - _TUNE[lo][n]) * t for n in _TUNE[lo]}


def _line(d, p0, p1, w, fill):
    """Round-capped thick line."""
    d.line([p0, p1], fill=fill, width=int(round(w)))
    r = w / 2
    for x, y in (p0, p1):
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def _disc(size, color):
    S = size * SUPERSAMPLE
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 0.5 * SUPERSAMPLE
    d.ellipse([pad, pad, S - pad, S - pad], fill=color)
    # faint dark hairline keeps the disc edge visible on light taskbars
    rim_a = 70
    d.ellipse([pad, pad, S - pad, S - pad], outline=(0, 0, 0, rim_a),
              width=max(1, int(round(0.5 * SUPERSAMPLE))))
    return img, d, S


def _power_glyph(d, S, w):
    c, R = S / 2, S / 2
    r = R * 0.47
    arc_w = int(round(w))
    d.arc([c - r, c - r + R * 0.04, c + r, c + r + R * 0.04], start=300, end=240,
          fill=WHITE, width=arc_w)  # gap at the top
    _line(d, (c, c - R * 0.60), (c, c - R * 0.05), w, WHITE)


def _infinity(d, S, w):
    c, R = S / 2, S / 2
    rl = R * 0.33           # loop outer radius
    off = R * 0.31         # loop centre offset
    for sx in (-1, 1):
        cx = c + sx * off
        d.ellipse([cx - rl, c - rl, cx + rl, c + rl], outline=WHITE, width=int(round(w)))


def render(state, size):
    """Return an RGBA PIL image `size` x `size` for state off|live|paused."""
    size = max(8, int(size))
    t = tuned(size)
    ss = SUPERSAMPLE
    if state == "paused":
        img, d, S = _disc(size, AMBER)
        bw = t["bar"] * ss
        bh = S * 0.50
        gap = S * 0.14
        for sx in (-1, 1):
            x = S / 2 + sx * (gap / 2 + bw / 2)
            _line(d, (x, S / 2 - bh / 2 + bw / 2), (x, S / 2 + bh / 2 - bw / 2), bw, DARK)
    elif state == "live":
        img, d, S = _disc(size, GREEN)
        rim = t["rim"] * ss
        rw = t["ring"] * ss
        o = 0.5 * ss + rim
        d.ellipse([o, o, S - o, S - o], outline=WHITE, width=int(round(rw)))
        _infinity(d, S, t["glyph"] * ss)
    else:
        img, d, S = _disc(size, GRAY)
        _power_glyph(d, S, t["glyph"] * ss * 1.1)
    return img.resize((size, size), Image.LANCZOS)


_cache = {}


def get(state, size):
    key = (state, int(size))
    if key not in _cache:
        _cache[key] = render(state, size)
    return _cache[key]
