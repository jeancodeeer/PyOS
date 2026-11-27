# The SnakeyOS logo: a blue and yellow snake shaped as an S (pictures in /share/pyos/logo-N.png;
# draw() is the drawn fallback).
#
#   logo.draw(surface, x, y, size)      draw it in a size x size square
#   logo.surface(size)                  a transparent Surface with it
# The same drawing, as SVG, is /share/pyos/logo.svg.
import pygame
from pygame.constants import SRCALPHA

BLUE = (55, 118, 171)          # the two colours of Python
YELLOW = (255, 212, 59)
SNAKE = (28, 44, 74)
BELLY = (90, 140, 210)

# the window: four panes on a 100 x 100 grid
PANES = ((16, 16, BLUE), (52, 16, YELLOW), (16, 52, YELLOW), (52, 52, BLUE))
PANE = 32
# the snake's path: in through the middle from the left, round the top-right
# pane, then down through the middle, head at the bottom
PATH = [(4, 50), (84, 50), (89.5, 44.5), (89.5, 16.5), (84, 11), (56, 11), (50, 17), (50, 88)]
BODY = 8                       # thickness of the snake, grid units


def _points(path, step=1.0):
    """Points every `step` units along the path."""
    out = []
    for (x0, y0), (x1, y1) in zip(path, path[1:]):
        n = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) / step))
        for i in range(n):
            out.append((x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n))
    out.append(path[-1])
    return out


def draw(surf, x, y, size):
    u = size / 100.0

    def P(px, py):
        return (int(x + px * u), int(y + py * u))

    radius = max(2, int(6 * u))
    for px, py, color in PANES:
        pygame.draw.rect(surf, color, (int(x + px * u), int(y + py * u), int(PANE * u), int(PANE * u)), 0, radius)
    pts = _points(PATH, 0.8)
    r = max(2, int(BODY * u / 2))
    for i, (px, py) in enumerate(pts):                    # the body: a chain of discs, tail thinner
        t = min(1.0, i / 25.0)
        pygame.draw.circle(surf, SNAKE, P(px, py), max(1, int(r * (0.45 + 0.55 * t))))
    for i, (px, py) in enumerate(pts):                    # a lighter stripe along the back
        if i % 6 < 3 and i > 10:
            pygame.draw.circle(surf, BELLY, P(px, py), max(1, r // 3))
    hx, hy = PATH[-1]
    pygame.draw.ellipse(surf, SNAKE, (int(x + (hx - 7) * u), int(y + (hy - 5) * u), int(14 * u), int(13 * u)))
    for ex in (-3, 3):                                    # eyes
        pygame.draw.circle(surf, (255, 255, 255), P(hx + ex, hy + 1), max(1, int(2 * u)))
        pygame.draw.circle(surf, (10, 10, 10), P(hx + ex, hy + 1.6), max(1, int(1 * u)))
    red = (230, 60, 60)                                   # forked tongue
    pygame.draw.line(surf, red, P(hx, hy + 7), P(hx, hy + 11), max(1, int(1.2 * u)))
    pygame.draw.line(surf, red, P(hx, hy + 11), P(hx - 2, hy + 13), max(1, int(1.2 * u)))
    pygame.draw.line(surf, red, P(hx, hy + 11), P(hx + 2, hy + 13), max(1, int(1.2 * u)))


_cache = {}
SIZES = (20, 24, 32, 48, 64, 96, 128, 256)     # /share/pyos/logo-N.png: the SnakeyOS logo, drawn


def _picture(size):
    """The logo picture for `size`: the stored one of that size, or the next bigger one scaled."""
    best = next((n for n in SIZES if n >= size), SIZES[-1])
    for root in ("/disk/system/share", "/share"):
        try:
            img = pygame.image.load("%s/pyos/logo-%d.png" % (root, best))
            if best != size:
                img = pygame.transform.scale(img, (size, size))
            return img
        except Exception:
            pass
    return None


def surface(size):
    s = _cache.get(size)
    if s is None:
        s = _picture(size)
        if s is None:                      # no picture (a bare system): draw it
            s = pygame.Surface((size, size), SRCALPHA)
            s.fill((0, 0, 0, 0))
            draw(s, 0, 0, size)
        _cache[size] = s
    return s
