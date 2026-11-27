# pygame.display: the screen. set_mode() switches the video card to a
# graphics mode (kernel/video.py); flip() / update() copy the display
# Surface to the framebuffer. quit() goes back to the text console.
import _gfx
from pygame.constants import OPENGL
from kernel import video, keyboard, mouse as _kmouse
from pygame.surface import Surface, error
from pygame.rect import Rect

_surface = None
_fb = None
_caption = ("pygame window", "pygame window")
_icon = None
DEFAULT = (640, 480)


class _Info:
    def __init__(self):
        size = _surface.get_size() if _surface else DEFAULT
        self.hw, self.wm, self.video_mem = 0, 0, 16
        self.bitsize, self.bytesize = 32, 4
        self.current_w, self.current_h = size
        self.blit_hw = self.blit_hw_CC = self.blit_hw_A = 0
        self.blit_sw = self.blit_sw_CC = self.blit_sw_A = 0
        self.masks = (0xFF0000, 0xFF00, 0xFF, 0)
        self.shifts = (16, 8, 0, 0)
        self.losses = (0, 0, 0, 8)

    def __repr__(self):
        return "<VideoInfo(%dx%d, 32 bpp)>" % (self.current_w, self.current_h)


def init():
    from pygame import event
    event._attach()


def quit():
    """Close the display: back to the text console."""
    global _surface, _fb, _cursor_at
    from pygame import event
    event._detach()
    _cursor_at = None
    if _fb is not None:
        video.text_mode()
    _surface = _fb = None


def get_init():
    return True


def set_mode(size=(0, 0), flags=0, depth=0, display=0, vsync=0):
    global _surface, _fb, _cursor_at
    from pygame import event, mouse
    w, h = int(size[0]) or DEFAULT[0], int(size[1]) or DEFAULT[1]
    _cursor_at = None
    _fb = video.set_mode(w, h)
    if _fb.width < w or _fb.height < h:          # ARM64: the screen UEFI chose is smaller
        w, h = min(w, _fb.width), min(h, _fb.height)
    _surface = Surface((w, h))
    _kmouse.bounds = (w, h)
    mouse._clamp()
    event._attach()
    if flags & OPENGL:
        _opengl(_surface)
    flip()
    return _surface


def _opengl(surface):
    """OPENGL: OpenGL draws into the screen (the OpenGL package is SnakeyOS's)."""
    try:
        from OpenGL import context
    except ImportError:
        raise error("OpenGL is not installed (it comes with SnakeyOS)")
    context.attach(surface)


def get_surface():
    return _surface


def get_active():
    return _surface is not None


_cursor_at = None           # where the mouse pointer was last drawn on the screen
_presenting = False


def _present(x, y, w, h):
    global _cursor_at, _presenting
    if _surface is None or _fb is None:
        raise error("video system not initialized")
    _presenting = True
    try:
        _gfx.present(_fb.buf, _fb.pitch, _surface._buf, _surface._w, _surface._h, x, y, w, h)
        from pygame import mouse
        if _cursor_at is not None and (x, y, w, h) != (0, 0, _surface._w, _surface._h):
            _restore(*_cursor_at)               # a partial update: rub out the pointer where it was
        mouse._draw_cursor(_fb)
        _cursor_at = mouse.get_pos()
    finally:
        _presenting = False


def _restore(cx, cy):
    """Put the screen's own pixels back where the pointer was drawn."""
    from pygame import mouse
    cw, ch = mouse._cursor_size()
    sw, sh = _surface._w, _surface._h
    w, h = min(cw, sw - cx), min(ch, sh - cy)
    if w > 0 and h > 0:
        _gfx.present(_fb.buf, _fb.pitch, _surface._buf, sw, sh, cx, cy, w, h)


def _move_cursor():
    """The mouse moved: draw the pointer at its new place at once, without waiting for
    the program to draw a frame (only the two small squares change)."""
    global _cursor_at
    if _surface is None or _fb is None or _presenting:
        return
    from pygame import mouse
    if _cursor_at is not None:
        _restore(*_cursor_at)
    mouse._draw_cursor(_fb)
    _cursor_at = mouse.get_pos()


def flip():
    if _surface is not None:
        _present(0, 0, _surface._w, _surface._h)


def update(rects=None):
    if _surface is None:
        return
    if rects is None:
        return flip()
    if isinstance(rects, Rect) or (len(rects) == 4 and isinstance(rects[0], int)):
        rects = [rects]
    for r in rects:
        if r:
            r = Rect(r)
            _present(r.x, r.y, r.w, r.h)


def set_caption(title, icontitle=None):
    global _caption
    _caption = (title, icontitle or title)


def get_caption():
    return _caption


def set_icon(surface):
    global _icon
    _icon = surface


def Info():
    return _Info()


def list_modes(depth=0, flags=0, display=0):
    return [(1024, 768), (800, 600), (640, 480), (320, 240)]


def mode_ok(size, flags=0, depth=0, display=0):
    return 32 if 0 < size[0] <= 1600 and 0 < size[1] <= 1200 else 0


def get_desktop_sizes():
    return [DEFAULT]


def get_num_displays():
    return 1


def get_driver():
    return "bga"


def get_wm_info():
    return {}


def iconify():
    return False


def toggle_fullscreen():
    return 1


def set_gamma(*args):
    return False
