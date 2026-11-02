"""Draw the app icon (two overlapping pages, one ticked) as PNG and ICO.

  py packaging/make_icon.py        (needs Pillow; only run when the icon changes)
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..", "dupefinder", "app")


def draw(size=256):
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return [round(v * s) for v in (x0, y0, x1, y1)]
    # back page (the extra copy), grey
    d.rounded_rectangle(box(28, 20, 168, 196), radius=round(18 * s), fill=(176, 186, 197, 255))
    # front page (the kept copy), blue
    d.rounded_rectangle(box(84, 60, 228, 236), radius=round(18 * s), fill=(38, 120, 214, 255))
    # tick
    d.line([tuple(round(v * s) for v in p) for p in ((118, 150), (146, 180), (196, 112))],
           fill=(255, 255, 255, 255), width=max(2, round(18 * s)), joint="curve")
    return img


if __name__ == "__main__":
    big = draw(256)
    big.save(os.path.join(APP, "icon.png"))
    big.save(os.path.join(HERE, "dupefinder.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                                           (64, 64), (128, 128), (256, 256)])
    print("icon written")
