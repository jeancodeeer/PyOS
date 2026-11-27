"""Turn TrueType fonts into small glyph atlases that PyKernel can draw.

    python tools/mkfont.py            # writes pyos/share/fonts/*.pkf

This runs on the host (it needs Pillow): PyKernel has no TrueType rasteriser,
so each font is drawn once here, at a few sizes, into an 8-bit alpha image.
On the machine, pygame.font reads the .pkf file and copies glyphs from it.

File format (.pkf):
    b"PKF2"  + 4-byte length + JSON header  + the alpha atlas, zero runs packed
    header: {"size", "ascent", "height", "w", "h",
             "glyphs": {"<codepoint>": [x, y, w, h, left, top, advance]}}
"""
import json
import shutil
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pyos" / "share" / "fonts"            # the fonts belong to SnakeyOS
DEJAVU = Path("/usr/share/fonts/truetype/dejavu")

FONTS = {                              # name -> TrueType file
    "sans": "DejaVuSans.ttf",
    "sans-bold": "DejaVuSans-Bold.ttf",
    "mono": "DejaVuSansMono.ttf",
    "mono-bold": "DejaVuSansMono-Bold.ttf",
}
SIZES = {"sans": (11, 13, 15, 18, 24, 32, 44), "sans-bold": (11, 13, 15, 18, 24, 32, 44),
         "mono": (13, 15), "mono-bold": (13, 15)}
CHARS = [chr(c) for c in range(32, 127)] + [chr(c) for c in range(160, 256)] + list(
    "•–—‘’“”…€←↑→↓✓✕★●"
    "▶◀▲▼™−·─│┌┐└┘█░▒▓↻⌂☆☰♠♥♦♣♪♫☀☁✎✂⌨⌕↔≡")


def zero_rle(data):
    """Runs of zero bytes become (0, length); everything else is copied.
    Simple enough to decode in a few lines on the machine."""
    out, i, n = bytearray(), 0, len(data)
    while i < n:
        if data[i] == 0:
            j = i
            while j < n and data[j] == 0 and j - i < 255:
                j += 1
            out += bytes((0, j - i))
            i = j
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


def build(name, path, size):
    font = ImageFont.truetype(str(path), size)
    ascent, descent = font.getmetrics()
    height = ascent + descent
    glyphs, images = {}, []
    for ch in CHARS:
        left, top, right, bottom = font.getbbox(ch)
        w, h = max(0, right - left), max(0, bottom - top)
        img = Image.new("L", (max(1, w), max(1, h)))
        ImageDraw.Draw(img).text((-left, -top), ch, font=font, fill=255)
        advance = round(font.getlength(ch))
        images.append((ch, img, w, h, left, top, advance))
    # pack glyphs in rows
    atlas_w = 512
    x = y = row_h = 0
    for ch, img, w, h, left, top, adv in images:
        if x + w + 1 > atlas_w:
            x, y, row_h = 0, y + row_h + 1, 0
        glyphs[str(ord(ch))] = [x, y, w, h, left, top, adv]
        x += w + 1
        row_h = max(row_h, h)
    atlas_h = y + row_h + 1
    atlas = Image.new("L", (atlas_w, atlas_h))
    for ch, img, w, h, left, top, adv in images:
        gx, gy = glyphs[str(ord(ch))][:2]
        if w and h:
            atlas.paste(img, (gx, gy))
    header = json.dumps({"size": size, "ascent": ascent, "height": height, "w": atlas_w, "h": atlas_h,
                         "glyphs": glyphs}, separators=(",", ":")).encode()
    data = b"PKF2" + struct.pack("<I", len(header)) + header + zero_rle(atlas.tobytes())
    (OUT / ("%s-%d.pkf" % (name, size))).write_bytes(data)
    return len(data)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, file in FONTS.items():
        for size in SIZES[name]:
            total += build(name, DEJAVU / file, size)
    licence = Path("/usr/share/doc/fonts-dejavu-core/copyright")
    if licence.is_file():
        shutil.copy(licence, ROOT / "pyfs" / "licenses" / "DejaVu.txt")
    print("fonts: %d bytes in %s" % (total, OUT))


if __name__ == "__main__":
    main()
