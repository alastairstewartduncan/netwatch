"""Generates NetWatch's brand artwork: app icon (.ico/.png), installer sidebar & header bitmaps.

Run once after changing the design:  python tools/make_art.py
Outputs go to assets/. The build uses the committed files, so fonts are only needed when regenerating.
"""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nw.version import APP_NAME, VERSION  # noqa: E402

ASSETS = ROOT / "assets"
CYAN, INDIGO = (34, 211, 238), (99, 102, 241)
NAVY, NAVY2 = (7, 11, 24), (18, 26, 51)


def font(weight="Bold", size=20):
    for p in (f"/usr/share/fonts/opentype/inter/Inter-{weight}.otf", f"C:/Windows/Fonts/segoeui{'b' if weight == 'Bold' else ''}.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def diagonal_gradient(size, c1, c2):
    w, h = size
    g = Image.new("RGB", (w, h))
    px = g.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = lerp(c1, c2, (x / w * 0.55 + y / h * 0.45))
    return g


def logo_mark(size, dot=(255, 255, 255)):
    """White signal arcs + dot, transparent background."""
    s = size / 100
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = 50 * s, 70 * s
    w = 8.5
    for r, a0, a1 in ((42, 225, 315), (28.5, 228, 312), (15, 233, 307)):
        # centre-line radius r; PIL draws width inward from the bounding circle, so offset by w/2
        R = (r + w / 2) * s
        d.arc([cx - R, cy - R, cx + R, cy + R], start=a0, end=a1, fill=(255, 255, 255, 255), width=int(w * s))
        for ang in (a0, a1):  # round caps on the centre line
            a = math.radians(ang)
            x, y = cx + r * s * math.cos(a), cy + r * s * math.sin(a)
            d.ellipse([x - w / 2 * s, y - w / 2 * s, x + w / 2 * s, y + w / 2 * s], fill=(255, 255, 255, 255))
    d.ellipse([cx - 6.5 * s, cy - 6.5 * s, cx + 6.5 * s, cy + 6.5 * s], fill=dot + (255,))
    return img


def app_icon(size=1024):
    ss = size
    base = diagonal_gradient((ss, ss), CYAN, INDIGO).convert("RGBA")
    mask = Image.new("L", (ss, ss), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, ss - 1, ss - 1], radius=int(ss * 0.23), fill=255)
    # soft top highlight
    hl = Image.new("RGBA", (ss, ss), (255, 255, 255, 0))
    ImageDraw.Draw(hl).ellipse([-ss * 0.3, -ss * 0.85, ss * 1.3, ss * 0.45], fill=(255, 255, 255, 38))
    base = Image.alpha_composite(base, hl.filter(ImageFilter.GaussianBlur(ss * 0.04)))
    mark = logo_mark(int(ss * 0.78))
    shadow = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    off = int(ss * 0.11)
    sh = Image.new("RGBA", mark.size, (12, 20, 60, 0))
    sh.putalpha(mark.getchannel("A").point(lambda a: int(a * 0.35)))
    shadow.paste(sh, (off, off + int(ss * 0.03)), sh)
    base = Image.alpha_composite(base, shadow.filter(ImageFilter.GaussianBlur(ss * 0.025)))
    base.alpha_composite(mark, (off, off))
    base.putalpha(mask)
    return base


def installer_sidebar(path):
    """164x314 welcome/finish page bitmap (rendered at 3x then reduced for crispness)."""
    k = 3
    W, H = 164 * k, 314 * k
    img = Image.new("RGB", (W, H), NAVY)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-W * 0.6, -H * 0.25, W * 1.1, H * 0.55], fill=INDIGO + (110,))
    gd.ellipse([-W * 0.2, H * 0.55, W * 1.4, H * 1.35], fill=CYAN + (70,))
    img = Image.alpha_composite(img.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(70 * k)))
    # faint grid of dots
    d = ImageDraw.Draw(img)
    for y in range(12 * k, H, 14 * k):
        if 150 * k < y < 215 * k or y > 280 * k:
            continue  # keep the text areas clean
        for x in range(10 * k, W, 14 * k):
            d.ellipse([x, y, x + k, y + k], fill=(148, 163, 184, 40))
    ic = app_icon(84 * k)
    img.alpha_composite(ic, ((W - ic.width) // 2, 64 * k))
    f1, f2, f3 = font("Bold", 22 * k), font("Medium", 9 * k), font("Regular", 8 * k)

    def ctext(y, text, f, fill):
        w = d.textlength(text, font=f)
        d.text(((W - w) / 2, y), text, font=f, fill=fill)
    ctext(166 * k, APP_NAME, f1, (240, 244, 252))
    ctext(196 * k, "Network monitor for Windows", f2, (180, 191, 214))
    ctext(290 * k, f"Version {VERSION}", f3, (125, 138, 166))
    img.convert("RGB").resize((164, 314), Image.LANCZOS).save(path, "BMP")


def installer_header(path):
    """150x57 header bitmap shown at the top-right of inner pages."""
    k = 3
    W, H = 150 * k, 57 * k
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    ic = app_icon(38 * k)
    img.alpha_composite(ic, (W - ic.width - 10 * k, (H - ic.height) // 2))
    img.convert("RGB").resize((150, 57), Image.LANCZOS).save(path, "BMP")


def main():
    ASSETS.mkdir(exist_ok=True)
    big = app_icon(1024)
    big.resize((256, 256), Image.LANCZOS).save(ASSETS / "netwatch.png")
    big.save(ASSETS / "netwatch-1024.png")
    sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    frames = [big.resize((s, s), Image.LANCZOS) for s in sizes]
    frames[-1].save(ASSETS / "netwatch.ico", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    installer_sidebar(ASSETS / "installer-sidebar.bmp")
    installer_header(ASSETS / "installer-header.bmp")
    # web favicon / in-app logo
    big.resize((192, 192), Image.LANCZOS).save(ROOT / "ui" / "icon.png")
    print("Artwork written to", ASSETS)


if __name__ == "__main__":
    main()
