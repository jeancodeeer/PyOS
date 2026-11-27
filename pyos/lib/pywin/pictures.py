# Pictures inside Windows programs: bitmaps (BMP) and icons (ICO), as
# pygame Surfaces.
#
# A bitmap resource is a BMP file without its first 14 bytes: a header
# (BITMAPINFOHEADER), maybe a palette, then the pixels, bottom row first.
# An icon is a "group" (a list of sizes) pointing at one picture per size;
# each picture is either a PNG file or a bitmap twice as tall as the icon
# (the colours, then a 1-bit "mask" saying which pixels are transparent).
import struct
import pygame

KEY = (255, 0, 254)                  # the colour that means "transparent" in our Surfaces
MAX_SIDE = 4096                       # refuse absurd sizes (a damaged or hostile file)


def _palette(data, at, count):
    return [(data[at + 4 * k + 2], data[at + 4 * k + 1], data[at + 4 * k]) for k in range(count)]


def dib(data, icon=False):
    """A Surface from a DIB (BITMAPINFOHEADER + palette + pixels). For an icon
    the height counts the mask too, and masked pixels become transparent."""
    size, w, h, planes, bpp, compression = struct.unpack_from("<IiiHHI", data, 0)
    if size < 40 or compression not in (0, 3):           # BI_RGB or BI_BITFIELDS
        raise ValueError("unsupported bitmap (compression %d)" % compression)
    top_down = h < 0
    h = abs(h) // 2 if icon else abs(h)
    if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE) or bpp not in (1, 4, 8, 16, 24, 32):
        raise ValueError("bitmap size out of range")
    colors = struct.unpack_from("<I", data, 32)[0] or (1 << bpp if bpp <= 8 else 0)
    at = size + (12 if compression == 3 else 0)
    pal = _palette(data, at, min(colors, 256)) if bpp <= 8 else None
    at += 4 * colors if bpp <= 8 else 0
    stride = ((w * bpp + 31) // 32) * 4
    mask_stride = ((w + 31) // 32) * 4
    mask_at = at + stride * h
    if mask_at > len(data) or (icon and bpp != 32 and mask_at + mask_stride * h > len(data)):
        raise ValueError("bitmap data cut short")
    if bpp == 32 and (icon or compression == 0):
        return _dib32(data, at, w, h, stride, top_down, icon)
    surf = pygame.Surface((w, h))
    alpha_seen = False
    for y in range(h):
        row = at + (y if top_down else h - 1 - y) * stride
        for x in range(w):
            if bpp == 32:
                b, g, r, a = data[row + 4 * x:row + 4 * x + 4]
                color = (r, g, b)
                if icon and a < 128:
                    color = KEY
                alpha_seen = alpha_seen or a
            elif bpp == 24:
                b, g, r = data[row + 3 * x:row + 3 * x + 3]
                color = (r, g, b)
            elif bpp == 16:
                v = data[row + 2 * x] | data[row + 2 * x + 1] << 8
                color = ((v >> 10 & 31) << 3, (v >> 5 & 31) << 3, (v & 31) << 3)
            else:
                per = 8 // bpp
                byte = data[row + x // per]
                index = (byte >> (8 - bpp * (x % per + 1))) & ((1 << bpp) - 1)
                color = pal[index] if index < len(pal) else (0, 0, 0)
            if icon and bpp != 32:
                m = mask_at + (y if top_down else h - 1 - y) * mask_stride
                if data[m + x // 8] & (0x80 >> (x % 8)):
                    color = KEY
            surf.set_at((x, y), color)
    if icon:
        surf.set_colorkey(KEY)
    return surf


def _dib32(data, at, w, h, stride, top_down, icon):
    """32-bit pixels are stored B, G, R, A, like our Surfaces: copy whole rows.
    An icon keeps its alpha (soft edges); a bitmap is made opaque."""
    from pygame.constants import SRCALPHA
    surf = pygame.Surface((w, h), SRCALPHA if icon else 0)
    buf, row = surf._buf, 4 * w
    for y in range(h):
        src = at + (y if top_down else h - 1 - y) * stride
        buf[y * row:(y + 1) * row] = data[src:src + row]
    if icon and not any(data[k] for k in range(at + 3, at + stride * h, 4)):   # an old icon without alpha: use its mask
        surf = pygame.Surface((w, h))
        surf.set_colorkey(KEY)
        return _masked(data, at, w, h, stride, top_down, surf, buf)
    if not icon:
        surf.set_alpha(None)
    return surf


def _masked(data, at, w, h, stride, top_down, surf, pixels):
    surf._buf[:] = pixels
    mask_at = at + stride * h
    mask_stride = ((w + 31) // 32) * 4
    for y in range(h):
        m = mask_at + (y if top_down else h - 1 - y) * mask_stride
        for x in range(w):
            if data[m + x // 8] & (0x80 >> (x % 8)):
                surf.set_at((x, y), KEY)
    return surf


def png(data):
    import io
    surf = pygame.image.load(io.BytesIO(data), "icon.png")
    return surf


def bmp_file(data):
    """A Surface from the bytes of a .bmp file."""
    if data[:2] != b"BM":
        raise ValueError("not a BMP file")
    return dib(data[14:])


def best_icon(entries, want):
    """From a group's [(width, height, bits, id)], the one closest to `want` pixels (most colours)."""
    def score(e):
        w = e[0] or 256
        return (abs(w - want), -e[2])
    return min(entries, key=score)


def group_entries(data, file=False):
    """The pictures listed by an icon group (resource) or an .ico file: [(w, h, bits, id or offset, size)]."""
    _, kind, count = struct.unpack_from("<HHH", data, 0)
    out = []
    for k in range(min(count, 64)):
        if file:
            w, h, _, _, _, bits, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * k)
            out.append((w, h, bits, offset, size))
        else:
            w, h, _, _, _, bits, size, ident = struct.unpack_from("<BBBBHHIH", data, 6 + 14 * k)
            out.append((w, h, bits, ident, size))
    return out


def icon_image(data):
    """One icon picture (PNG or DIB with a mask) as a Surface."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return png(data)
    return dib(data, icon=True)


def ico_file(data, want=32):
    """A Surface from the bytes of an .ico file, the size nearest `want`."""
    entries = group_entries(data, file=True)
    if not entries:
        raise ValueError("empty icon file")
    w, h, bits, offset, size = best_icon(entries, want)
    if offset + size > len(data):
        raise ValueError("icon file cut short")
    return icon_image(data[offset:offset + size])


def fit(surf, w, h):
    """The picture at w x h (if asked for a size)."""
    if w and h and surf.get_size() != (w, h):
        key = surf.get_colorkey()
        surf = pygame.transform.scale(surf, (w, h))
        if key is not None:
            surf.set_colorkey(key)
    return surf
