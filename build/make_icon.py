# -*- coding: utf-8 -*-
"""生成应用图标（无外部素材依赖）。"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent.parent / "assets" / "app.ico"


def main():
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([14, 14, 242, 242], radius=52,
                        fill=(28, 62, 45, 255), outline=(198, 168, 106, 255), width=12)
    d.rounded_rectangle([44, 78, 212, 178], radius=18,
                        fill=(240, 232, 210, 255))
    for i, x in enumerate(range(58, 200, 26)):
        d.rectangle([x, 94, x + 12, 162], fill=(28, 62, 45, 180))
    d.polygon([(150, 100), (150, 156), (200, 128)], fill=(180, 40, 40, 255))
    d.rectangle([44, 190, 212, 202], fill=(198, 168, 106, 255))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                         (64, 64), (128, 128), (256, 256)])
    print("icon ->", OUT)


if __name__ == "__main__":
    main()
