# App icons, drawn with pygame shapes (no image files). icon(name, size)
# returns a transparent Surface; results are cached.
import math
import pygame
from pygame.constants import SRCALPHA

_cache = {}

COLORS = {
    "terminal": ((40, 44, 52), (90, 96, 110)), "files": ((66, 140, 255), (40, 100, 220)),
    "browser": ((40, 170, 255), (20, 110, 210)), "editor": ((255, 170, 50), (230, 120, 30)),
    "sysmon": ((80, 200, 120), (40, 150, 90)), "settings": ((140, 146, 160), (90, 96, 110)),
    "calc": ((255, 120, 70), (220, 80, 50)), "paint": ((240, 90, 160), (190, 60, 130)),
    "images": ((120, 110, 240), (80, 70, 200)), "clock": ((250, 210, 60), (220, 160, 30)),
    "store": ((60, 200, 200), (30, 150, 160)), "disks": ((100, 110, 130), (60, 66, 80)),
    "snake": ((80, 200, 80), (40, 140, 50)), "blocks": ((170, 90, 230), (120, 60, 190)),
    "mines": ((130, 140, 160), (80, 90, 110)), "about": ((64, 120, 242), (40, 80, 200)),
    "music": ((255, 80, 110), (200, 40, 80)), "jeancode": ((20, 20, 20), (60, 60, 60)),
    "folder": ((120, 170, 255), (70, 120, 230)), "notes": ((250, 210, 70), (230, 170, 40)),
    "sheet": ((70, 190, 110), (40, 140, 80)), "trash": ((140, 146, 160), (100, 106, 120)),
    "bloc": ((120, 180, 255), (70, 130, 230)), "escritor": ((60, 110, 230), (30, 70, 190)),
    "presentaciones": ((245, 120, 60), (210, 80, 30)), "solitario": ((50, 150, 90), (30, 110, 60)),
    "calendario": ((255, 255, 255), (230, 232, 238)), "recortes": ((230, 70, 130), (180, 40, 100)),
    "caracteres": ((150, 120, 240), (110, 80, 200)), "teclado": ((110, 120, 140), (70, 78, 96)),
    "lupa": ((40, 170, 200), (20, 120, 160)), "tareas": ((90, 200, 140), (50, 160, 100)),
    "pywin": ((30, 60, 120), (20, 36, 80)), "exe": ((90, 130, 200), (50, 90, 170)),
    "cubo": ((30, 30, 50), (10, 10, 20)),
}


def _tile(s, size, top, bottom):
    r = size // 5
    for y in range(size):                        # vertical gradient, row by row
        t = y / size
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        inset = 0
        if y < r:
            inset = r - int(math.sqrt(max(0, r * r - (r - y) ** 2)))
        elif y >= size - r:
            inset = r - int(math.sqrt(max(0, r * r - (y - (size - r - 1)) ** 2)))
        s.fill(c + (255,), (inset, y, size - 2 * inset, 1))


def icon(name, size=48, label=None):
    """The icon called `name`; unknown names get a tile with the label's first letter."""
    key = (name, size, label)
    if key in _cache:
        return _cache[key]
    s = pygame.Surface((size, size), SRCALPHA)
    s.fill((0, 0, 0, 0))
    top, bottom = COLORS.get(name, ((120, 120, 140), (80, 80, 100)))
    _tile(s, size, top, bottom)
    u = size / 48.0                              # draw on a 48-unit grid
    W = (255, 255, 255)

    def P(x, y):
        return (int(x * u), int(y * u))

    def R(x, y, w, h):
        return (int(x * u), int(y * u), max(1, int(w * u)), max(1, int(h * u)))

    d = pygame.draw
    if name == "terminal":
        d.lines(s, (120, 255, 140), False, [P(12, 16), P(20, 24), P(12, 32)], max(2, int(3 * u)))
        d.rect(s, W, R(23, 30, 13, 3))
    elif name == "files":
        d.rect(s, (255, 214, 102), R(9, 15, 14, 6))
        d.rect(s, (255, 200, 60), R(9, 19, 30, 18))
    elif name == "browser":
        c = P(24, 24)
        d.circle(s, W, c, int(15 * u), max(1, int(2 * u)))
        d.ellipse(s, W, R(17, 9, 14, 30), max(1, int(2 * u)))
        d.line(s, W, P(9, 24), P(39, 24), max(1, int(2 * u)))
        d.line(s, W, P(12, 16), P(36, 16), max(1, int(u)))
        d.line(s, W, P(12, 32), P(36, 32), max(1, int(u)))
    elif name == "editor":
        d.rect(s, W, R(13, 9, 22, 30))
        for i in range(5):
            d.rect(s, (230, 140, 40), R(16, 14 + i * 5, 16 if i % 2 else 12, 2))
    elif name == "sysmon":
        pts = [P(9, 32), P(16, 26), P(22, 30), P(29, 17), P(35, 22), P(40, 12)]
        d.lines(s, W, False, pts, max(2, int(3 * u)))
        d.rect(s, (255, 255, 255, 120), R(9, 36, 30, 2))
    elif name == "settings":
        c = P(24, 24)
        for k in range(8):
            a = k * math.pi / 4
            d.line(s, W, c, (c[0] + int(math.cos(a) * 14 * u), c[1] + int(math.sin(a) * 14 * u)), max(3, int(5 * u)))
        d.circle(s, W, c, int(10 * u))
        d.circle(s, top, c, int(4 * u))
    elif name == "calc":
        d.rect(s, W, R(13, 9, 22, 30))
        d.rect(s, (60, 60, 70), R(16, 12, 16, 7))
        for i in range(3):
            for j in range(3):
                d.rect(s, (220, 90, 60), R(16 + j * 6, 22 + i * 5, 4, 3))
    elif name == "paint":
        d.circle(s, W, P(24, 25), int(15 * u))
        for (x, y), c in zip(((18, 18), (27, 16), (33, 23), (17, 28)), ((240, 60, 60), (60, 160, 240), (60, 200, 90), (250, 200, 40))):
            d.circle(s, c, P(x, y), int(3.5 * u))
    elif name == "images":
        d.rect(s, W, R(9, 12, 30, 24))
        d.polygon(s, (90, 200, 120), [P(11, 34), P(20, 22), P(27, 30), P(31, 26), P(37, 34)])
        d.circle(s, (255, 210, 70), P(31, 18), int(3 * u))
    elif name == "clock":
        c = P(24, 24)
        d.circle(s, W, c, int(15 * u))
        d.line(s, (60, 60, 70), c, P(24, 14), max(2, int(2 * u)))
        d.line(s, (60, 60, 70), c, P(31, 27), max(2, int(2 * u)))
    elif name == "store":
        d.rect(s, W, R(12, 18, 24, 20))
        d.ellipse(s, W, R(18, 10, 12, 14), max(2, int(2 * u)))
    elif name == "disks":
        d.rect(s, (220, 224, 232), R(10, 14, 28, 20))
        d.circle(s, (80, 220, 120), P(33, 29), int(2 * u))
        d.rect(s, (150, 156, 168), R(13, 18, 16, 3))
    elif name == "snake":
        d.lines(s, W, False, [P(12, 34), P(12, 22), P(24, 22), P(24, 14), P(36, 14)], max(4, int(6 * u)))
        d.circle(s, (255, 90, 90), P(36, 33), int(3 * u))
    elif name == "blocks":
        for (x, y) in ((12, 26), (19, 26), (26, 26), (19, 19)):
            d.rect(s, W, R(x, y, 6, 6))
        d.rect(s, (255, 220, 90), R(26, 12, 6, 6))
    elif name == "mines":
        d.circle(s, (30, 30, 36), P(24, 26), int(10 * u))
        for k in range(4):
            a = k * math.pi / 4
            d.line(s, (30, 30, 36), (int((24 - math.cos(a) * 14) * u), int((26 - math.sin(a) * 14) * u)),
                   (int((24 + math.cos(a) * 14) * u), int((26 + math.sin(a) * 14) * u)), max(1, int(2 * u)))
        d.circle(s, W, P(20, 22), int(2 * u))
    elif name == "jeancode":
        d.rect(s, W, R(10, 13, 28, 18), 0, max(2, int(4 * u)))
        d.polygon(s, W, [P(16, 30), P(16, 37), P(23, 30)])
        for i in range(3):
            d.circle(s, top, P(17 + 7 * i, 22), max(1, int(2 * u)))
    elif name == "music":
        d.rect(s, W, R(20, 12, 3, 20))
        d.rect(s, W, R(20, 12, 13, 3))
        d.rect(s, W, R(30, 12, 3, 16))
        d.circle(s, W, P(18, 33), int(4 * u))
        d.circle(s, W, P(28, 29), int(4 * u))
    elif name == "about":                        # an "i"
        d.circle(s, W, P(24, 15), int(3 * u))
        d.rect(s, W, R(21, 21, 6, 15))
    elif name == "folder":
        d.rect(s, (255, 214, 102), R(8, 13, 15, 7), 0, max(1, int(2 * u)))
        d.rect(s, (255, 196, 50), R(8, 18, 32, 20), 0, max(1, int(3 * u)))
    elif name == "notes":
        d.rect(s, (255, 244, 170), R(11, 9, 26, 30), 0, max(1, int(3 * u)))
        for i in range(4):
            d.rect(s, (200, 170, 60), R(15, 16 + i * 5, 18, 2))
    elif name == "sheet":
        d.rect(s, W, R(10, 10, 28, 28))
        for i in range(1, 4):
            d.line(s, (60, 160, 90), P(10, 10 + i * 7), P(38, 10 + i * 7), max(1, int(u)))
            d.line(s, (60, 160, 90), P(10 + i * 7, 10), P(10 + i * 7, 38), max(1, int(u)))
    elif name == "trash":
        d.rect(s, W, R(14, 16, 20, 23), 0, max(1, int(3 * u)))
        d.rect(s, W, R(11, 12, 26, 3))
        d.rect(s, W, R(20, 9, 8, 3))
    elif name == "bloc":
        d.rect(s, W, R(12, 9, 24, 30), 0, max(1, int(3 * u)))
        for i in range(5):
            d.rect(s, (120, 160, 220), R(16, 15 + i * 4.5, 16 if i % 2 == 0 else 12, 2))
    elif name == "escritor":
        d.rect(s, W, R(12, 9, 24, 30), 0, max(1, int(3 * u)))
        from desktop import ui as _ui
        img = _ui.font(24 if size >= 40 else 13, True).render("W", True, (40, 80, 200))
        s.blit(img, ((size - img.get_width()) // 2, int(14 * u)))
    elif name == "presentaciones":
        d.rect(s, W, R(9, 12, 30, 20), 0, max(1, int(2 * u)))
        d.rect(s, (245, 120, 60), R(13, 16, 12, 2))
        d.rect(s, (200, 200, 210), R(13, 21, 18, 2))
        d.rect(s, (200, 200, 210), R(13, 25, 14, 2))
        d.line(s, W, P(24, 32), P(24, 38), max(1, int(2 * u)))
        d.line(s, W, P(18, 39), P(30, 39), max(1, int(2 * u)))
    elif name == "solitario":
        d.rect(s, (240, 240, 240), R(10, 12, 18, 25), 0, max(1, int(3 * u)))
        d.rect(s, W, R(20, 10, 18, 25), 0, max(1, int(3 * u)))
        from desktop import ui as _ui
        img = _ui.font(24 if size >= 40 else 13, True).render("♥", True, (210, 40, 50))
        s.blit(img, (int(29 * u) - img.get_width() // 2, int(14 * u)))
    elif name == "calendario":
        d.rect(s, (236, 84, 76), R(8, 8, 32, 10), 0, max(1, int(3 * u)))
        from desktop import ui as _ui
        import time as _t
        img = _ui.font(24 if size >= 40 else 13, True).render(str(_t.localtime()[2]), True, (40, 44, 52))
        s.blit(img, ((size - img.get_width()) // 2, int(18 * u)))
    elif name == "recortes":
        d.circle(s, W, P(16, 32), int(5 * u), max(1, int(2 * u)))
        d.circle(s, W, P(32, 32), int(5 * u), max(1, int(2 * u)))
        d.line(s, W, P(19, 28), P(34, 10), max(2, int(2.5 * u)))
        d.line(s, W, P(29, 28), P(14, 10), max(2, int(2.5 * u)))
    elif name == "caracteres":
        from desktop import ui as _ui
        img = _ui.font(32 if size >= 40 else 15, True).render("A\u00f1", True, (255, 255, 255))
        s.blit(img, ((size - img.get_width()) // 2, (size - img.get_height()) // 2))
    elif name == "teclado":
        d.rect(s, W, R(7, 15, 34, 19), 0, max(1, int(3 * u)))
        for row in range(3):
            for col in range(6 - (row == 2) * 2):
                d.rect(s, (110, 120, 140), R(10 + col * 5 + row * 2, 18 + row * 5, 3, 3))
    elif name == "lupa":
        d.circle(s, W, P(21, 21), int(10 * u), max(2, int(3 * u)))
        d.line(s, W, P(28, 28), P(38, 38), max(3, int(5 * u)))
    elif name == "tareas":
        for i in range(3):
            d.rect(s, W, R(12, 12 + i * 9, 6, 6), 0, max(1, int(u)))
            d.rect(s, W, R(22, 14 + i * 9, 14, 2))
        d.lines(s, (40, 120, 70), False, [P(13, 15), P(15, 17), P(18, 12)], max(1, int(1.5 * u)))
    elif name == "pywin":                        # four window panes with a snake across
        for i, c in enumerate(((242, 80, 34), (127, 186, 0), (0, 164, 239), (255, 185, 0))):
            d.rect(s, c, R(11 + (i % 2) * 14, 11 + (i // 2) * 14, 12, 12), 0, max(1, int(u)))
        d.lines(s, (255, 222, 87), False, [P(7, 32), P(16, 26), P(24, 30), P(32, 22), P(41, 16)], max(2, int(3 * u)))
        d.circle(s, (255, 222, 87), P(41, 16), int(3 * u))
    elif name == "exe":                          # a window with its title bar
        d.rect(s, W, R(8, 11, 32, 26), 0, max(1, int(2 * u)))
        d.rect(s, (40, 80, 160), R(8, 11, 32, 6), 0, max(1, int(2 * u)))
        d.rect(s, (230, 80, 70), R(34, 12, 4, 4))
        d.rect(s, (180, 190, 210), R(12, 21, 16, 2))
        d.rect(s, (180, 190, 210), R(12, 26, 22, 2))
    elif name == "cubo":                         # a lit cube, for OpenGL
        d.polygon(s, (90, 160, 255), [P(24, 8), P(39, 16), P(24, 24), P(9, 16)])
        d.polygon(s, (40, 90, 200), [P(9, 16), P(24, 24), P(24, 41), P(9, 32)])
        d.polygon(s, (60, 120, 230), [P(39, 16), P(24, 24), P(24, 41), P(39, 32)])
    else:                                        # anything else: the first letter
        from desktop import ui
        letter = (label or name or "?")[:1].upper()
        f = ui.font(32 if size >= 40 else 24, bold=True)
        img = f.render(letter, True, (255, 255, 255))
        s.blit(img, ((size - img.get_width()) // 2, (size - img.get_height()) // 2))
    _cache[key] = s
    return s
