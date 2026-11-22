"""
Build the app icon and logo: a white serif V (Fraunces 600) on a red rounded square.

Writes:
  assets/logo.png    512x512, the bare mark (browser tab icon, README)
  assets/icon.png    1024x1024 on Apple's icon grid with a soft shadow (also the Dock icon, set by desktop.py)
  assets/Venato.icns all sizes, for Venato.app/Contents/Resources (macOS)
  assets/icon.ico    all sizes, for the Windows shortcuts made by setup.ps1

The loading screen (assets/splash.html) draws the same mark in CSS, so keep the colour and proportions in step.

Needs fontTools and brotli to read the bundled .woff2 font (build-time only):
    .venv/bin/pip install fonttools brotli
Run with:   .venv/bin/python scripts/make_icon.py
"""

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASSETS = Path(__file__).resolve().parents[1] / "assets"
FONT = ASSETS / "fonts" / "Fraunces-600.woff2"
LOGO = ASSETS / "logo.png"
PNG = ASSETS / "icon.png"
ICNS = ASSETS / "Venato.icns"
ICO = ASSETS / "icon.ico"

RED = "#C62828"          # the app's light-mode accent (venato/ui/appearance.py)
SIZE = 1024
INSET = 100              # Apple's icon grid: the shape is 824 px inside a 1024 canvas
RADIUS_RATIO = 34 / 148  # corner radius / side, as on the loading screen
GLYPH_RATIO = 104 / 148  # V font size / side, as on the loading screen
SCALE = 4                # draw this much bigger, then shrink, for smooth edges


def font(px):
    """Fraunces at px size. Pillow can't read .woff2, so it is converted to TrueType in memory."""
    tt = TTFont(FONT)
    tt.flavor = None
    buf = io.BytesIO()
    tt.save(buf)
    buf.seek(0)
    return ImageFont.truetype(buf, px)


def mark(side):
    """The logo, side x side: red rounded square, white V centred on its ink."""
    big = side * SCALE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, big - 1, big - 1), round(big * RADIUS_RATIO), fill=RED)
    f = font(round(big * GLYPH_RATIO))
    left, top, right, bottom = draw.textbbox((0, 0), "V", font=f)
    draw.text(((big - (right - left)) / 2 - left, (big - (bottom - top)) / 2 - top), "V", font=f, fill="white")
    return img.resize((side, side), Image.LANCZOS)


def build_logo():
    mark(512).save(LOGO)


def build_png():
    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    side = SIZE - 2 * INSET

    # Soft drop shadow under the shape.
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((INSET, INSET + 12, SIZE - INSET, SIZE - INSET + 12),
                                             round(side * RADIUS_RATIO), fill=(0, 0, 0, 70))
    icon.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    icon.alpha_composite(mark(side), (INSET, INSET))

    icon.save(PNG)
    return icon


def build_icns(icon):
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "Venato.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            icon.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            icon.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS)], check=True)


def build_icns_pillow(icon):
    """Without macOS's iconutil: Pillow writes every .icns size from the 1024 px icon."""
    icon.save(ICNS, format="ICNS")


def build_ico():
    """Windows shows the icon small and square, so it gets the mark edge to edge (no Apple-grid margin)."""
    mark(256).save(ICO, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])


if __name__ == "__main__":
    build_logo()
    icon = build_png()
    build_ico()
    if shutil.which("iconutil"):            # macOS
        build_icns(icon)
    else:
        build_icns_pillow(icon)
    print(f"Wrote {LOGO.name}, {PNG.name}, {ICO.name} and {ICNS.name}")
