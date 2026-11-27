# pygame.mouse: the PS/2 mouse (kernel/mouse.py) and an on-screen pointer.
import _gfx
from kernel import mouse as _m
from pygame import constants as C

_visible = True
_rel = [0, 0]
_last_buttons = 0
_cursor = None

# an arrow pointer: X = black edge, . = white, space = transparent
_ARROW = (
    "X          ",
    "XX         ",
    "X.X        ",
    "X..X       ",
    "X...X      ",
    "X....X     ",
    "X.....X    ",
    "X......X   ",
    "X.......X  ",
    "X........X ",
    "X.....XXXXX",
    "X..X..X    ",
    "X.X X..X   ",
    "XX  X..X   ",
    "X    X..X  ",
    "     XXXX  ",
)


def _cursor_pixels():
    global _cursor
    if _cursor is None:
        w, h = len(_ARROW[0]), len(_ARROW)
        buf = bytearray(w * h * 4)
        for y, row in enumerate(_ARROW):
            for x, ch in enumerate(row):
                p = {"X": 0xFF000000, ".": 0xFFFFFFFF}.get(ch, 0x00FF00FF)
                _gfx.set_at(buf, w, h, x, y, p)
        _cursor = (buf, w, h)
    return _cursor


def _cursor_size():
    buf, w, h = _cursor_pixels()
    return w, h


def _draw_cursor(fb):
    if not (_visible and _m.present):
        return
    buf, w, h = _cursor_pixels()
    # straight onto the framebuffer: the next flip() rubs it out again
    _gfx.blit(fb.buf, fb.width, fb.height, _m.x, _m.y, buf, w, h, 0, 0, w, h, 1, 0xFF00FF, 255)


def _clamp():
    _m.x = max(0, min(_m.bounds[0] - 1, _m.x))
    _m.y = max(0, min(_m.bounds[1] - 1, _m.y))


def _buttons_tuple(bits):
    return (bool(bits & 1), bool(bits & 4), bool(bits & 2))      # left, middle, right


def _moved(dx, dy, bits, add, Event):
    global _last_buttons
    _rel[0] += dx
    _rel[1] += dy
    pos = (_m.x, _m.y)
    if dx or dy:
        add(Event(C.MOUSEMOTION, pos=pos, rel=(dx, dy), buttons=_buttons_tuple(bits), touch=False))
        if _visible:
            try:
                from pygame import display
                display._move_cursor()            # the pointer follows the hand, frame or no frame
            except Exception:
                pass
    changed = bits ^ _last_buttons
    for bit, button in ((1, C.BUTTON_LEFT), (4, C.BUTTON_MIDDLE), (2, C.BUTTON_RIGHT)):
        if changed & bit:
            kind = C.MOUSEBUTTONDOWN if bits & bit else C.MOUSEBUTTONUP
            add(Event(kind, pos=pos, button=button, touch=False))
    _last_buttons = bits


def get_pos():
    return (_m.x, _m.y)


def get_rel():
    r = (_rel[0], _rel[1])
    _rel[0] = _rel[1] = 0
    return r


def get_pressed(num_buttons=3):
    t = _buttons_tuple(_m.buttons)
    return t if num_buttons == 3 else t + (False, False)


def set_pos(*pos):
    x, y = pos if len(pos) == 2 else pos[0]
    _m.x, _m.y = int(x), int(y)
    _clamp()


def set_visible(on):
    global _visible
    was, _visible = _visible, bool(on)
    return was


def get_visible():
    return _visible


def get_focused():
    return True


def set_cursor(*args):
    pass


def get_cursor():
    return None
