# pygame.transform: scale, flip, rotate (nearest neighbour, in C).
import math
import _gfx
from pygame.surface import Surface


def _like(src, w, h):
    s = Surface((max(0, int(w)), max(0, int(h))), src._flags)
    s._key, s._alpha = src._key, src._alpha
    return s


def scale(surface, size, dest_surface=None):
    w, h = int(size[0]), int(size[1])
    out = dest_surface or _like(surface, w, h)
    _gfx.scale(surface._buf, surface._w, surface._h, out._buf, w, h)
    return out


smoothscale = scale


def scale_by(surface, factor):
    fx, fy = (factor, factor) if not hasattr(factor, "__len__") else factor
    return scale(surface, (surface._w * fx, surface._h * fy))


smoothscale_by = scale_by


def scale2x(surface, dest_surface=None):
    return scale(surface, (surface._w * 2, surface._h * 2), dest_surface)


def flip(surface, flip_x, flip_y):
    out = _like(surface, surface._w, surface._h)
    _gfx.flip(surface._buf, surface._w, surface._h, out._buf, flip_x, flip_y)
    return out


def rotate(surface, angle):
    """Counter-clockwise by `angle` degrees; the result grows to fit."""
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    w, h = surface._w, surface._h
    nw = int(abs(w * c) + abs(h * s) + 0.5)
    nh = int(abs(w * s) + abs(h * c) + 0.5)
    out = _like(surface, nw, nh)
    if surface._flags:
        fill = 0
    elif surface._key is not None:
        fill = surface._key | 0xFF000000
    else:
        fill = _gfx.get_at(surface._buf, w, h, 0, 0) if w and h else 0
    # inverse mapping: destination pixel -> source pixel (y grows downwards)
    _gfx.rotate(surface._buf, w, h, out._buf, nw, nh, int(c * 65536), int(s * 65536), fill)
    return out


def rotozoom(surface, angle, scale_factor):
    r = rotate(surface, angle)
    if scale_factor == 1:
        return r
    return scale(r, (r._w * scale_factor, r._h * scale_factor))


def chop(surface, rect):
    return surface.copy()


def laplacian(surface, dest_surface=None):
    return surface.copy()


def average_color(surface, rect=None, consider_alpha=False):
    w, h = surface._w, surface._h
    tot = [0, 0, 0, 0]
    n = 0
    step = max(1, (w * h) // 4096)
    for i in range(0, w * h, step):
        p = _gfx.get_at(surface._buf, w, h, i % w, i // w)
        tot[0] += (p >> 16) & 255
        tot[1] += (p >> 8) & 255
        tot[2] += p & 255
        tot[3] += p >> 24
        n += 1
    return tuple(v // max(1, n) for v in tot)
