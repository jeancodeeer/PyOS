"""The 8x16 text console font for machines without VGA (ARM64): code page 437,
like a PC's text mode, drawn from DejaVu Sans Mono (Bitstream Vera licence).

    python tools/mkconsolefont.py   # -> pyfs/share/console8x16.bin (4096 bytes)
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
TTF = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
BOX = "─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬"


def glyph(ch, font, bold):
    img = Image.new("L", (8, 16), 0)
    if ch.isprintable() and ch != " ":
        d = ImageDraw.Draw(img)
        if ch in BOX or ord(ch) in range(0x2500, 0x25A0):   # box drawing: edge to edge
            big = ImageFont.truetype(TTF, 16)
            d.text((0, -3), ch, fill=255, font=big)
        else:
            d.text((0, 0), ch, fill=255, font=font)
            if bold:
                d.text((1, 0), ch, fill=255, font=font)
    rows = bytearray(16)
    for y in range(16):
        b = 0
        for x in range(8):
            if img.getpixel((x, y)) > 110:
                b |= 0x80 >> x
        rows[y] = b
    return rows


def main():
    font = ImageFont.truetype(TTF, 13)
    out = bytearray()
    for i in range(256):
        ch = bytes([i]).decode("cp437") if i >= 0x20 else " "
        out += glyph(ch, font, False)
    dest = ROOT / "pyfs" / "share" / "console8x16.bin"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(out)
    print(dest, len(out))


if __name__ == "__main__":
    main()
