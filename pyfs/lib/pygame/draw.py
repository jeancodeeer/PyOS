# pygame.draw: shapes on a Surface. Each returns the Rect it touched.
import math
import _gfx
from pygame.rect import Rect
from pygame.color import pixel


def _p(surface, color):
    p = pixel(color)
    return p if surface._flags else p | 0xFF000000


def _bounds(points, width=0):
    xs = [int(p[0]) for p in points]
    ys = [int(p[1]) for p in points]
    pad = max(0, width // 2)
    return Rect(min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 1 + 2 * pad,
                max(ys) - min(ys) + 1 + 2 * pad)


def rect(surface, color, rect, width=0, border_radius=0, border_top_left_radius=-1,
         border_top_right_radius=-1, border_bottom_left_radius=-1, border_bottom_right_radius=-1):
    r = Rect(rect)
    r.normalize()
    c = _p(surface, color)
    b, w, h = surface._buf, surface._w, surface._h
    if border_radius > 0:
        rad = min(border_radius, r.w // 2, r.h // 2)
        if width <= 0:
            _gfx.fill(b, w, h, r.x + rad, r.y, r.w - 2 * rad, r.h, c)
            _gfx.fill(b, w, h, r.x, r.y + rad, r.w, r.h - 2 * rad, c)
            for cx, cy in ((r.x, r.y), (r.right - 2 * rad, r.y), (r.x, r.bottom - 2 * rad),
                           (r.right - 2 * rad, r.bottom - 2 * rad)):
                _gfx.ellipse(b, w, h, cx, cy, 2 * rad, 2 * rad, c, 0)
            return r.clip(surface.get_rect())
        # an outline with round corners: four straight edges and four corner rings
        _gfx.fill(b, w, h, r.x + rad, r.y, r.w - 2 * rad, width, c)
        _gfx.fill(b, w, h, r.x + rad, r.bottom - width, r.w - 2 * rad, width, c)
        _gfx.fill(b, w, h, r.x, r.y + rad, width, r.h - 2 * rad, c)
        _gfx.fill(b, w, h, r.right - width, r.y + rad, width, r.h - 2 * rad, c)
        corners = ((r.x, r.y, 0, 0), (r.right - rad, r.y, rad, 0),
                   (r.x, r.bottom - rad, 0, rad), (r.right - rad, r.bottom - rad, rad, rad))
        from pygame.surface import Surface
        from pygame.constants import SRCALPHA
        ring = Surface((2 * rad, 2 * rad), SRCALPHA)
        ring.fill((0, 0, 0, 0))
        _gfx.ellipse(ring._buf, 2 * rad, 2 * rad, 0, 0, 2 * rad, 2 * rad, c, width)
        for x, y, sx, sy in corners:                 # copy one quarter of the ring to each corner
            _gfx.blit(b, w, h, x, y, ring._buf, 2 * rad, 2 * rad, sx, sy, rad, rad, 2, 0, 255)
        return r.clip(surface.get_rect())
    if width <= 0:
        _gfx.fill(b, w, h, r.x, r.y, r.w, r.h, c)
    else:
        _gfx.fill(b, w, h, r.x, r.y, r.w, width, c)
        _gfx.fill(b, w, h, r.x, r.bottom - width, r.w, width, c)
        _gfx.fill(b, w, h, r.x, r.y, width, r.h, c)
        _gfx.fill(b, w, h, r.right - width, r.y, width, r.h, c)
    return r.clip(surface.get_rect())


def line(surface, color, start_pos, end_pos, width=1):
    if width < 1:
        return Rect(int(start_pos[0]), int(start_pos[1]), 0, 0)
    _gfx.line(surface._buf, surface._w, surface._h, int(start_pos[0]), int(start_pos[1]),
              int(end_pos[0]), int(end_pos[1]), _p(surface, color), width)
    return _bounds((start_pos, end_pos), width).clip(surface.get_rect())


aaline = line


def lines(surface, color, closed, points, width=1):
    pts = list(points)
    for a, b in zip(pts, pts[1:]):
        line(surface, color, a, b, width)
    if closed and len(pts) > 2:
        line(surface, color, pts[-1], pts[0], width)
    return _bounds(pts, width).clip(surface.get_rect())


def aalines(surface, color, closed, points, blend=1):
    return lines(surface, color, closed, points)


def polygon(surface, color, points, width=0):
    pts = [(int(p[0]), int(p[1])) for p in points]
    if width > 0:
        return lines(surface, color, True, pts, width)
    _gfx.polygon(surface._buf, surface._w, surface._h, pts, _p(surface, color))
    lines(surface, color, True, pts, 1)            # include the edges, as pygame does
    return _bounds(pts).clip(surface.get_rect())


def circle(surface, color, center, radius, width=0, draw_top_right=None,
           draw_top_left=None, draw_bottom_left=None, draw_bottom_right=None):
    cx, cy, r = int(center[0]), int(center[1]), int(radius)
    if r < 1:
        return Rect(cx, cy, 0, 0)
    box = Rect(cx - r, cy - r, 2 * r, 2 * r)
    _gfx.ellipse(surface._buf, surface._w, surface._h, box.x, box.y, box.w, box.h,
                 _p(surface, color), max(0, width))
    return box.clip(surface.get_rect())


def ellipse(surface, color, rect, width=0):
    r = Rect(rect)
    _gfx.ellipse(surface._buf, surface._w, surface._h, r.x, r.y, r.w, r.h,
                 _p(surface, color), max(0, width))
    return r.clip(surface.get_rect())


def arc(surface, color, rect, start_angle, stop_angle, width=1):
    r = Rect(rect)
    if stop_angle < start_angle:
        stop_angle += 2 * math.pi
    steps = max(8, int((stop_angle - start_angle) * max(r.w, r.h) / 4))
    pts = []
    for i in range(steps + 1):
        a = start_angle + (stop_angle - start_angle) * i / steps
        pts.append((r.centerx + math.cos(a) * r.w / 2, r.centery - math.sin(a) * r.h / 2))
    return lines(surface, color, False, pts, width)
