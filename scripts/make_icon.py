from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def make_icon(path: Path, png_path: Path | None = None) -> None:
    size = 1024
    img = Image.new("RGBA", (size, size), (18, 20, 24, 255))
    d = ImageDraw.Draw(img)

    # Rounded archive body
    d.rounded_rectangle((170, 145, 854, 879), radius=120, fill=(31, 35, 42, 255), outline=(73, 220, 205, 255), width=30)
    # Vertical zipper
    x = 512
    d.rounded_rectangle((464, 190, 560, 756), radius=32, fill=(73, 220, 205, 255))
    for y in range(225, 700, 95):
        d.rounded_rectangle((405, y, 474, y + 42), radius=12, fill=(214, 255, 249, 255))
        d.rounded_rectangle((550, y + 44, 619, y + 86), radius=12, fill=(214, 255, 249, 255))
    # Compression arrows
    d.polygon([(300, 490), (410, 420), (410, 465), (455, 465), (455, 515), (410, 515), (410, 560)], fill=(255, 255, 255, 235))
    d.polygon([(724, 490), (614, 420), (614, 465), (569, 465), (569, 515), (614, 515), (614, 560)], fill=(255, 255, 255, 235))
    # Bottom badge line
    d.rounded_rectangle((290, 770, 734, 810), radius=20, fill=(73, 220, 205, 255))

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    if png_path:
        img.resize((512, 512), Image.Resampling.LANCZOS).save(png_path, format="PNG")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="assets/RayPack.ico")
    parser.add_argument("--png", default="assets/RayPack.png")
    args = parser.parse_args()
    make_icon(Path(args.out), Path(args.png) if args.png else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
