# pygame.font: smooth proportional text from glyph atlases (.pkf files in
# /share/fonts, made from DejaVu by tools/mkfont.py), drawn by Python.
#
#   f = pygame.font.Font(None, 18)          # DejaVu Sans, 18 px
#   f = pygame.font.SysFont("mono", 15)     # DejaVu Sans Mono
#   surf = f.render("hola", True, (255, 255, 255))
#
# A glyph is an 8-bit coverage image; render() copies each one into a new
# transparent Surface in the requested colour. If the atlases are missing,
# the video card's 8x16 font is used instead.
import json
from kernel import arch as _arch   # ARM64: C versions of the viper functions
import struct
import micropython
import _gfx
from pygame.surface import Surface
from pygame.constants import SRCALPHA
from pygame.color import pixel

FONT_DIR = "/share/fonts"
SIZES = {"sans": (11, 13, 15, 18, 24, 32, 44), "mono": (13, 15)}
_init = False
_atlases = {}         # (family, bold, size) -> Atlas


def init():
    global _init
    try:
        from kernel import video
        video.font()          # keep the VGA font at hand (read while in text mode)
    except Exception:
        pass
    _init = True


def quit():
    global _init
    _init = False


def get_init():
    return _init


def get_default_font():
    return "sans"


def get_fonts():
    return ["sans", "mono", "dejavusans", "dejavusansmono"]


def match_font(name, bold=False, italic=False):
    return _family(name)


def _family(name):
    n = (name or "").lower() if isinstance(name, str) else ""
    return "mono" if any(k in n for k in ("mono", "courier", "consol", "menlo", "code", "fixed")) else "sans"


@micropython.viper
def _put(dst: ptr8, dw: int, dh: int, dx: int, dy: int, src: ptr8, sw: int, sx: int, sy: int,
         w: int, h: int, b: int, g: int, r: int):
    """Copy a w x h coverage rectangle from the atlas into BGRA pixels."""
    for row in range(h):
        y = dy + row
        if y < 0 or y >= dh:
            continue
        s = (sy + row) * sw + sx
        for col in range(w):
            x = dx + col
            if x < 0 or x >= dw:
                continue
            a = int(src[s + col])
            if a:
                o = (y * dw + x) * 4
                if a > int(dst[o + 3]):
                    dst[o] = b
                    dst[o + 1] = g
                    dst[o + 2] = r
                    dst[o + 3] = a
_put = _arch.fast(_put, 'font_put')


@micropython.viper
def _unrle(src: ptr8, i: int, end: int, dst: ptr8):
    """Undo tools/mkfont.py's packing: (0, n) is n zero bytes, others are copied."""
    o = 0
    while i < end:
        b = src[i]
        if b == 0:
            o += src[i + 1]                    # dst is already zeros: just skip
            i += 2
        else:
            dst[o] = b
            o += 1
            i += 1
_unrle = _arch.fast(_unrle, 'font_unrle')


class Atlas:
    def __init__(self, path):
        with open(path, "rb") as f:
            data = f.read()
        if data[:4] != b"PKF2":
            raise OSError("not a PKF2 font")
        n = struct.unpack_from("<I", data, 4)[0]
        head = json.loads(data[8:8 + n])
        self.pixels = bytearray(head["w"] * head["h"])
        _unrle(data, 8 + n, len(data), self.pixels)
        self.size, self.ascent, self.height = head["size"], head["ascent"], head["height"]
        self.w = head["w"]
        self.glyphs = {int(k): v for k, v in head["glyphs"].items()}
        self.fallback = self.glyphs.get(63)               # '?'

    def glyph(self, ch):
        return self.glyphs.get(ord(ch)) or self.glyphs.get(_LOOKALIKE.get(ch, 63)) or self.fallback

    def width(self, text):
        g = self.glyphs
        total = 0
        for ch in text:
            v = g.get(ord(ch)) or self.glyph(ch)
            total += v[6]
        return total


_LOOKALIKE = {"„": 34, "′": 39, "″": 34, " ": 32, " ": 32, "​": 32, "■": 0x2588}


def _atlas(family, bold, size):
    sizes = SIZES[family]
    best = min(sizes, key=lambda s: abs(s - size))
    key = (family, bold, best)
    a = _atlases.get(key)
    if a is None:
        name = "%s%s-%d.pkf" % (family, "-bold" if bold else "", best)
        try:
            a = Atlas(FONT_DIR + "/" + name)
        except OSError:
            a = False                                    # no atlas: VGA font
        _atlases[key] = a
    return a


class Font:
    def __init__(self, file=None, size=24, _family_name=None):
        self.point_size = max(1, int(size))
        self.family = _family_name or (_family(file) if isinstance(file, str) else "sans")
        self.bold = self.italic = self.underline = self.strikethrough = False
        self._px = self._pixel_size(self.point_size)

    @staticmethod
    def _pixel_size(size):
        # pygame's Font(None, 24) draws about 17-pixel text; keep that feel
        return max(11, int(size * 0.72 + 0.5)) if size > 15 else size

    def _a(self):
        return _atlas(self.family, self.bold, self._px)

    def size(self, text):
        a = self._a()
        if not a:
            return len(text) * 8, 16
        return a.width(str(text)), a.height

    def get_height(self):
        a = self._a()
        return a.height if a else 16

    get_linesize = get_height

    def get_ascent(self):
        a = self._a()
        return a.ascent if a else 12

    def get_descent(self):
        a = self._a()
        return (a.ascent - a.height) if a else -4

    def set_bold(self, on):
        self.bold = bool(on)

    def get_bold(self):
        return self.bold

    def set_italic(self, on):
        self.italic = bool(on)

    def get_italic(self):
        return self.italic

    def set_underline(self, on):
        self.underline = bool(on)

    def get_underline(self):
        return self.underline

    def set_strikethrough(self, on):
        self.strikethrough = bool(on)

    def render(self, text, antialias=True, color=(255, 255, 255), background=None, wraplength=0):
        text = str(text).replace("\n", " ").replace("\t", "    ")
        a = self._a()
        if not a:
            return _vga_render(text, color, background)
        w, h = max(1, a.width(text)), a.height
        surf = Surface((w, h), SRCALPHA)
        surf.fill((0, 0, 0, 0))
        c = pixel(color)
        r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
        x = 0
        buf, pix, aw, asc = surf._buf, a.pixels, a.w, a.ascent
        for ch in text:
            gx, gy, gw, gh, left, top, adv = a.glyph(ch)
            if gw:
                _put(buf, w, h, x + left, top, pix, aw, gx, gy, gw, gh, b, g, r)
            x += adv
        if self.underline:
            surf.fill(color, (0, asc + 1, w, 1))
        if self.strikethrough:
            surf.fill(color, (0, h // 2, w, 1))
        if background is not None:
            out = Surface((w, h))
            out.fill(background)
            out.blit(surf, (0, 0))
            return out
        return surf

    def metrics(self, text):
        a = self._a()
        out = []
        for ch in text:
            if a:
                gx, gy, gw, gh, left, top, adv = a.glyph(ch)
                out.append((left, left + gw, a.ascent - top - gh, a.ascent - top, adv))
            else:
                out.append((0, 8, 0, 16, 8))
        return out


def SysFont(name=None, size=24, bold=False, italic=False):
    f = Font(None, size, _family(name))
    f.bold, f.italic = bool(bold), italic
    return f


# ---- the VGA font, when no atlas is available ----

def _vga_render(text, color, background):
    from kernel import video
    from kernel.console import CP437
    chars = bytes(o if o < 0x80 else CP437.get(o, 0x3F) for o in (ord(ch) for ch in text))
    surf = Surface((max(1, len(chars) * 8), 16), 0 if background is not None else SRCALPHA)
    surf.fill(background if background is not None else (0, 0, 0, 0))
    _gfx.text(surf._buf, surf._w, surf._h, 0, 0, video.font(), chars, pixel(color) | 0xFF000000, 1, 1, -1)
    return surf
