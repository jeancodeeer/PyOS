# The Windows GUI model shared by user32 (windows and messages), gdi32
# (drawing) and the SnakeyOS desktop (pywin/host.py).
#
# Every window (HWND) has a pygame Surface the size of its client area.
# The program draws into it through a DC (device context); the desktop
# shows it in a SnakeyOS window and turns the mouse and keyboard into messages.
import pygame

# messages
WM_CREATE, WM_DESTROY, WM_MOVE, WM_SIZE, WM_ACTIVATE = 0x01, 0x02, 0x03, 0x05, 0x06
WM_SETFOCUS, WM_KILLFOCUS, WM_ENABLE = 0x07, 0x08, 0x0A
WM_SETTEXT, WM_GETTEXT, WM_GETTEXTLENGTH, WM_PAINT, WM_CLOSE, WM_QUIT = 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x12
WM_ERASEBKGND, WM_SHOWWINDOW, WM_SETFONT, WM_GETMINMAXINFO = 0x14, 0x18, 0x30, 0x24
WM_NCCREATE, WM_NCDESTROY = 0x81, 0x82
WM_KEYDOWN, WM_KEYUP, WM_CHAR, WM_COMMAND, WM_TIMER = 0x100, 0x101, 0x102, 0x111, 0x113
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x200, 0x201, 0x202, 0x203
WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MOUSEWHEEL = 0x204, 0x205, 0x20A
WM_CTLCOLORSTATIC, WM_CTLCOLOREDIT, WM_CTLCOLORBTN = 0x138, 0x133, 0x135
WM_USER = 0x400
BM_GETCHECK, BM_SETCHECK, BN_CLICKED = 0xF0, 0xF1, 0
EN_CHANGE = 0x300

# window styles
WS_CHILD, WS_VISIBLE, WS_DISABLED, WS_BORDER, WS_CAPTION = 0x40000000, 0x10000000, 0x08000000, 0x00800000, 0x00C00000
BS_CHECKBOX, BS_AUTOCHECKBOX, BS_RADIOBUTTON, BS_AUTORADIOBUTTON, BS_GROUPBOX = 2, 3, 4, 9, 7
ES_MULTILINE, ES_PASSWORD, ES_READONLY = 0x4, 0x20, 0x800
SS_CENTER, SS_RIGHT = 1, 2

FRAME_W, FRAME_H = 16, 39        # what Windows 10 adds around a client area

# system colours (COLOR_WINDOW + 1 and so on, as brushes)
SYS_COLORS = {0: (200, 200, 200), 1: (0, 80, 160), 4: (240, 240, 240), 5: (255, 255, 255),
              6: (100, 100, 100), 8: (0, 0, 0), 15: (240, 240, 240), 16: (160, 160, 160),
              18: (0, 0, 0), 20: (255, 255, 255)}


def rgb(colorref):
    """A COLORREF (0x00BBGGRR) as (r, g, b)."""
    return (colorref & 255, (colorref >> 8) & 255, (colorref >> 16) & 255)


class Wnd:
    def __init__(self, handle, cls, title, x, y, w, h, style, parent, menu_id, param):
        self.handle, self.cls, self.title = handle, cls, title
        self.x, self.y, self.w, self.h = x, y, max(1, w), max(1, h)
        self.style, self.parent, self.id, self.param = style, parent, menu_id, param
        self.children = []
        self.proc = cls.proc if cls else None    # guest address, or a Python function
        self.visible = bool(style & WS_VISIBLE)
        self.enabled = not style & WS_DISABLED
        self.invalid = True                       # needs a WM_PAINT
        self.erase = True
        self._surface = None                      # made when first drawn on (see `surface`)
        self.user_data = 0
        self.extra = {}
        self.font = None
        self.checked = 0
        self.pressed = False
        self.changed = True                       # the desktop should show it again
        self.host = None                          # the desktop window showing it

    @property
    def surface(self):
        """The window's pixels. Made the first time something draws: programs
        create many windows that are never shown (tooltips, hidden dialogs,
        message windows), and each picture can take a megabyte or more."""
        if self._surface is None:
            try:
                self._surface = pygame.Surface((self.w, self.h))
            except MemoryError:                   # ask SnakeyOS for more room, once
                from pywin.process import heap_area_for
                heap_area_for(4 * self.w * self.h)
                self._surface = pygame.Surface((self.w, self.h))
            self._surface.fill(self.cls.background if self.cls else (240, 240, 240))
        return self._surface

    @surface.setter
    def surface(self, value):
        self._surface = value

    def forget_pixels(self):
        """Give the picture's memory back (for a hidden window); it is redrawn when needed."""
        self._surface = None
        self.invalid = self.erase = True

    @property
    def top_level(self):
        return self.parent is None or not self.style & WS_CHILD

    def resize(self, w, h):
        w, h = max(1, w), max(1, h)
        if (w, h) != (self.w, self.h):
            self.w, self.h = w, h
            old = self._surface
            self._surface = None
            if old is not None:                       # keep what was drawn
                self.surface.blit(old, (0, 0))
            self.invalid = self.erase = True

    def offset_in_top(self):
        """Where this window's client area is inside its top-level window."""
        x = y = 0
        w = self
        while w.parent is not None and w.style & WS_CHILD:
            x += w.x
            y += w.y
            w = w.parent
        return x, y

    # The children are kept as Windows keeps them: the first one is on top
    # ("Z order"), and a new child goes to the bottom. A group box (the frame
    # around radio buttons) is see-through: drawn first, never clicked.

    def is_group_box(self):
        return self.cls is not None and self.cls.name.lower() == "button" and self.style & 0xF == 7

    def child_at(self, pos):
        """The deepest visible child window under pos (client coordinates): the top one."""
        for c in self.children:
            if c.visible and not c.is_group_box() and c.x <= pos[0] < c.x + c.w and c.y <= pos[1] < c.y + c.h:
                return c.child_at((pos[0] - c.x, pos[1] - c.y))
        return self, pos

    def compose(self, target, x=0, y=0):
        """Draw this window and its children onto target: bottom child first."""
        target.blit(self.surface, (x, y))
        order = list(reversed(self.children))
        order = [c for c in order if c.is_group_box()] + [c for c in order if not c.is_group_box()]
        for c in order:
            if c.visible:
                if c.cls and c.cls.render:
                    c.cls.render(c)               # a built-in control draws itself
                c.compose(target, x + c.x, y + c.y)


class WndClass:
    def __init__(self, name, proc, background=(240, 240, 240), style=0, extra=0, render=None):
        self.name, self.proc, self.background, self.style = name, proc, background, style
        self.extra = extra
        self.render = render                      # for built-in controls


# ---- GDI objects ----

class Pen:
    def __init__(self, color=(0, 0, 0), width=1, null=False):
        self.color, self.width, self.null = color, max(1, width), null


class Brush:
    def __init__(self, color=(255, 255, 255), null=False):
        self.color, self.null = color, null


class Font:
    def __init__(self, height=16, bold=False, face="sans"):
        self.height, self.bold, self.face = height, bold, face
        self._font = None

    def pygame_font(self):
        if self._font is None:
            px = abs(self.height) or 16
            size = int(px / 0.72 + 0.5) if px > 15 else px          # see pygame/font.py
            self._font = pygame.font.SysFont(self.face, size, bold=self.bold)
        return self._font


class Bitmap:
    def __init__(self, w, h):
        self.surface = pygame.Surface((max(1, w), max(1, h)))
        self.surface.fill((0, 0, 0))


class DC:
    """Where drawing goes: a window, or a bitmap in memory."""

    def __init__(self, wnd=None, surface=None):
        self.wnd = wnd
        self.surface = surface if surface is not None else wnd.surface
        self.pen = Pen()
        self.brush = Brush()
        self.font = Font(16)
        self.bitmap = None
        self.text_color = (0, 0, 0)
        self.bk_color = (255, 255, 255)
        self.transparent = False
        self.pos = (0, 0)
        self.align = 0

    def changed(self):
        if self.wnd is not None:
            top = self.wnd
            while top.parent is not None and top.style & WS_CHILD:
                top = top.parent
            top.changed = True


# ---- menus ----
MF_GRAYED, MF_DISABLED, MF_CHECKED, MF_POPUP, MF_SEPARATOR, MF_BYPOSITION = 1, 2, 8, 0x10, 0x800, 0x400
MENU_H = 24                     # the menu bar's height, above the client area


class MenuItem:
    def __init__(self, text, ident=0, popup=None, flags=0):
        self.text, self.id, self.popup, self.flags = text, ident, popup, flags

    @property
    def label(self):
        """The text without the '&' that marks the shortcut letter, and without '\\t keys'."""
        return self.text.split("\t")[0].replace("&&", "\0").replace("&", "").replace("\0", "&")


class Menu:
    def __init__(self):
        self.items = []
