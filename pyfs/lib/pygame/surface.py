# pygame.Surface: an image in memory, 32-bit pixels, drawn by the _gfx C
# module. The display is a Surface too (see display.py).
import _gfx
from pygame.constants import SRCALPHA
from pygame.rect import Rect
from pygame.color import pixel, from_pixel

_KEY, _SRCA, _SURFA = 1, 2, 4


class error(RuntimeError):
    pass


class Surface:
    def __init__(self, size, flags=0, depth=32, masks=None, _buf=None):
        w, h = int(size[0]), int(size[1])
        if w < 0 or h < 0:
            raise ValueError("Invalid resolution for Surface")
        self._w, self._h = w, h
        self._flags = flags & SRCALPHA
        self._buf = _buf if _buf is not None else bytearray(w * h * 4)
        self._key = None
        self._alpha = None
        if _buf is None and not self._flags:
            _gfx.fill(self._buf, w, h, 0, 0, w, h, 0xFF000000)

    def __repr__(self):
        return "<Surface(%dx%dx32%s)>" % (self._w, self._h, " SRCALPHA" if self._flags else "")

    # -- size --
    def get_width(self):
        return self._w

    def get_height(self):
        return self._h

    def get_size(self):
        return (self._w, self._h)

    def get_rect(self, **kw):
        r = Rect(0, 0, self._w, self._h)
        for k, v in kw.items():
            setattr(r, k, v)
        return r

    def get_flags(self):
        return self._flags

    def get_bitsize(self):
        return 32

    def get_bytesize(self):
        return 4

    def get_pitch(self):
        return self._w * 4

    def get_buffer(self):
        return memoryview(self._buf)

    def get_view(self, kind="2"):
        return memoryview(self._buf)

    # -- formats (all surfaces share one format here) --
    def convert(self, *args):
        s = self.copy()
        s._flags = 0
        return s

    def convert_alpha(self, *args):
        s = self.copy()
        s._flags = SRCALPHA
        return s

    def copy(self):
        s = Surface((self._w, self._h), self._flags, _buf=bytearray(self._buf))
        s._key, s._alpha = self._key, self._alpha
        return s

    # -- transparency --
    def set_colorkey(self, color=None, flags=0):
        self._key = None if color is None else pixel(color) & 0xFFFFFF

    def get_colorkey(self):
        return None if self._key is None else tuple(from_pixel(self._key | 0xFF000000))

    def set_alpha(self, value=None, flags=0):
        self._alpha = None if value is None else max(0, min(255, int(value)))

    def get_alpha(self):
        return self._alpha if self._alpha is not None else (255 if self._flags else None)

    def lock(self):
        pass

    def unlock(self):
        pass

    def mustlock(self):
        return False

    def get_locked(self):
        return False

    # -- drawing --
    def _clip(self, rect):
        if rect is None:
            return Rect(0, 0, self._w, self._h)
        return Rect(rect).clip(Rect(0, 0, self._w, self._h))

    def fill(self, color, rect=None, special_flags=0):
        r = self._clip(rect)
        p = pixel(color)
        if not self._flags:
            p |= 0xFF000000
        _gfx.fill(self._buf, self._w, self._h, r.x, r.y, r.w, r.h, p)
        return r

    def blit(self, source, dest=(0, 0), area=None, special_flags=0):
        if len(dest) == 4 or isinstance(dest, Rect):
            dx, dy = dest[0], dest[1]
        else:
            dx, dy = dest
        dx, dy = int(dx), int(dy)
        if area is None:
            sx, sy, cw, ch = 0, 0, source._w, source._h
        else:
            sx, sy, cw, ch = Rect(area)
        flags = 0
        if source._key is not None:
            flags |= _KEY
        if source._flags:
            flags |= _SRCA
        if source._alpha is not None and source._alpha < 255:
            flags |= _SURFA
        _gfx.blit(self._buf, self._w, self._h, dx, dy, source._buf, source._w, source._h,
                  sx, sy, cw, ch, flags, source._key or 0, source._alpha or 255)
        return Rect(dx, dy, cw, ch).clip(Rect(0, 0, self._w, self._h))

    def blits(self, blit_sequence, doreturn=1):
        out = [self.blit(*item) for item in blit_sequence]
        return out if doreturn else None

    def fblits(self, blit_sequence, special_flags=0):
        for item in blit_sequence:
            self.blit(*item)

    def get_at(self, pos):
        return from_pixel(_gfx.get_at(self._buf, self._w, self._h, int(pos[0]), int(pos[1])))

    def get_at_mapped(self, pos):
        return _gfx.get_at(self._buf, self._w, self._h, int(pos[0]), int(pos[1]))

    def set_at(self, pos, color):
        _gfx.set_at(self._buf, self._w, self._h, int(pos[0]), int(pos[1]), pixel(color))

    def map_rgb(self, color):
        return pixel(color)

    def unmap_rgb(self, value):
        return from_pixel(value)

    def subsurface(self, rect):
        """A copy of part of this surface (here it does not share pixels)."""
        r = Rect(rect)
        s = Surface((r.w, r.h), self._flags)
        s.blit(self, (0, 0), r) if not self._flags else _gfx.blit(
            s._buf, r.w, r.h, 0, 0, self._buf, self._w, self._h, r.x, r.y, r.w, r.h, 0, 0, 255)
        s._key = self._key
        return s

    def scroll(self, dx=0, dy=0):
        tmp = self.copy()
        tmp._key = None
        tmp._flags = 0
        _gfx.blit(self._buf, self._w, self._h, dx, dy, tmp._buf, self._w, self._h,
                  0, 0, self._w, self._h, 0, 0, 255)

    def get_bounding_rect(self, min_alpha=1):
        return self.get_rect()
