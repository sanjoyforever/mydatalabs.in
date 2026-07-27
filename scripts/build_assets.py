#!/usr/bin/env python
"""Generate the derived image assets from app/static/img/logo.png.

The source logo is 1024x1024 / ~234 KB. It was being served as the 32px header
icon, the 26px footer icon, the apple-touch-icon and the OpenGraph image — about
ten times the page's own HTML weight for an icon, and the wrong aspect ratio for
a social card.

Outputs:
    logo-64.png          64x64   header / footer icon
    apple-touch-icon.png 180x180 iOS home screen
    favicon.png          64x64   browser tab (regenerated for consistency)
    og-card.png          1200x630 OpenGraph / Twitter social card

Run after changing the logo:  python scripts/build_assets.py
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "static", "img")
SOURCE = os.path.join(IMG_DIR, "logo.png")

# Hero photograph. The source is a 4503x3000 / ~11 MB JPEG — roughly 600x the
# page's own HTML weight, so it is never served directly. These derivatives
# feed a srcset in home.html; browsers pick one and the rest cost nothing.
HERO_SOURCE = os.path.join(IMG_DIR, "image1.jpg")
HERO_WIDTHS = (640, 960, 1400)
HERO_ASPECT = 12 / 5  # the hero is a full-bleed band, not a 4:3 block
# Vertical crop bias: 0.5 centres, higher keeps more of the lower frame. The
# vessel sits below centre, so a centred band crops it out.
HERO_VCROP = 0.60
# Fraction of the source width kept before the aspect crop (trimmed from the
# right), which slides the vessel out from under the gradient.
HERO_HKEEP = 0.76

# Matches --page-bg / --surface-card / --accent-blue / --text-main in style.css.
BG = (8, 11, 17)
CARD = (17, 23, 38)
ACCENT = (56, 189, 248)
TEXT = (248, 250, 252)
SUB = (148, 163, 184)


def _font(size: int, bold: bool = False):
    """Best available system font, falling back to Pillow's default."""
    candidates = [
        "seguisb.ttf" if bold else "segoeui.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_icons(src: Image.Image) -> None:
    for name, size in (("logo-64.png", 64), ("favicon.png", 64), ("apple-touch-icon.png", 180)):
        out = src.resize((size, size), Image.LANCZOS)
        out.save(os.path.join(IMG_DIR, name), "PNG", optimize=True)
        print(f"  {name}: {size}x{size}, {os.path.getsize(os.path.join(IMG_DIR, name)) // 1024} KB")


def build_og_card(src: Image.Image) -> None:
    """1200x630 social card. Square logos crop badly in a 1.91:1 slot, so the
    card is composed rather than cropped."""
    W, H = 1200, 630
    card = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(card)

    # Panel + accent rule
    draw.rectangle([56, 56, W - 56, H - 56], fill=CARD)
    draw.rectangle([56, 56, W - 56, 62], fill=ACCENT)

    logo = src.resize((104, 104), Image.LANCZOS)
    card.paste(logo, (104, 112), logo if logo.mode == "RGBA" else None)

    draw.text((232, 128), "MyDataLabs", font=_font(52, bold=True), fill=TEXT)
    draw.text((232, 190), "QUANTITATIVE INTELLIGENCE", font=_font(22), fill=ACCENT)

    draw.text((104, 300), "Hormuz Crisis Index", font=_font(72, bold=True), fill=TEXT)
    draw.text(
        (104, 396),
        "Weekly composite tracking geopolitical stress,\nshipping disruption and energy dislocation.",
        font=_font(30),
        fill=SUB,
        spacing=12,
    )
    draw.text((104, H - 128), "mydatalabs.in  ·  open methodology  ·  free JSON & CSV", font=_font(24), fill=SUB)

    path = os.path.join(IMG_DIR, "og-card.png")
    card.save(path, "PNG", optimize=True)
    print(f"  og-card.png: {W}x{H}, {os.path.getsize(path) // 1024} KB")


def build_hero() -> None:
    """Responsive WebP + JPEG derivatives of the hero photograph."""
    if not os.path.exists(HERO_SOURCE):
        print("  image1.jpg not present — skipping hero derivatives")
        return

    src = Image.open(HERO_SOURCE).convert("RGB")
    print(f"hero source: {src.width}x{src.height}, {os.path.getsize(HERO_SOURCE) // 1024} KB")

    # The left of the hero card is covered by the gradient that hands the photo
    # back to the card surface, so the subject has to sit right of centre.
    # Trimming the right edge first pushes it there; the aspect crop follows.
    usable_w = int(src.width * HERO_HKEEP)
    frame = src.crop((0, 0, usable_w, src.height))

    # Crop to HERO_ASPECT before scaling so every derivative shares one ratio
    # and the CSS can reserve space without layout shift.
    target_h = min(frame.height, int(frame.width / HERO_ASPECT))
    target_w = int(target_h * HERO_ASPECT)
    left = (frame.width - target_w) // 2
    top = int((frame.height - target_h) * HERO_VCROP)
    cropped = frame.crop((left, top, left + target_w, top + target_h))

    for width in HERO_WIDTHS:
        height = int(width / HERO_ASPECT)
        out = cropped.resize((width, height), Image.LANCZOS)
        for ext, kwargs in (("webp", {"quality": 82, "method": 6}),
                            ("jpg", {"quality": 82, "optimize": True, "progressive": True})):
            path = os.path.join(IMG_DIR, f"hero-{width}.{ext}")
            out.save(path, **kwargs)
            print(f"  hero-{width}.{ext}: {width}x{height}, {os.path.getsize(path) // 1024} KB")


def main() -> None:
    if not os.path.exists(SOURCE):
        raise SystemExit(f"source logo not found: {SOURCE}")
    src = Image.open(SOURCE).convert("RGBA")
    print(f"source: {src.width}x{src.height}, {os.path.getsize(SOURCE) // 1024} KB")
    build_icons(src)
    build_og_card(src)
    build_hero()


if __name__ == "__main__":
    main()
