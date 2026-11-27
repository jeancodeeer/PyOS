# Widgets for desktop apps, drawn with pygame.
#
#   ui.text(surf, "hola", x, y)                  draw text (cached)
#   ui.Button((10, 10, 90, 28), "OK", on_click)
#   ui.Field((10, 50, 200, 28)).text             one line of input
#   ui.ListBox((10, 90, 200, 200), items, on_pick, on_open)
#   ui.TextView(rect, lines)                     scrolling text
#   form = ui.Form(); form.add(widget)           draws them, routes events, Tab
# Every widget has draw(surf) and event(ev, pos) -> True if it used the event.
import time
import pygame
from desktop import theme as T

_fonts = {}
_cache = {}
SCALE = 1.0                      # Settings > Pantalla > tamano del texto


def set_scale(scale):
    global SCALE
    SCALE = scale
    _fonts.clear()
    _cache.clear()


def font(size=13, bold=False, mono=False):
    size = int(round(size * SCALE))
    key = (size, bold, mono)
    f = _fonts.get(key)
    if f is None:
        pygame.font.init()
        f = pygame.font.SysFont("mono" if mono else "sans", size, bold)
        f._px = size                               # sizes here are pixels
        _fonts[key] = f
    return f


def FONT():
    return font(13)


def MONO():
    return font(13, mono=True)


def render(s, color=None, f=None):
    f = f or FONT()
    color = T.TEXT if color is None else color
    key = (s, color, id(f))
    surf = _cache.get(key)
    if surf is None:
        if len(_cache) > 500:
            _cache.clear()
        surf = f.render(s, True, color)
        _cache[key] = surf
    return surf


def width(s, f=None):
    return (f or FONT()).size(s)[0]


def fit(s, max_w, f=None):
    """Shorten s with '…' until it fits in max_w pixels."""
    f = f or FONT()
    if f.size(s)[0] <= max_w:
        return s
    while s and f.size(s + "…")[0] > max_w:
        s = s[:-1]
    return s + "…" if s else ""


def text(surf, s, x, y, color=None, f=None, max_w=None, center=False):
    if not s:
        return 0
    color = T.TEXT if color is None else color
    f = f or FONT()
    if max_w is not None:
        s = fit(s, max_w, f)
    img = render(s, color, f)
    if center:
        x -= img.get_width() // 2
    surf.blit(img, (x, y))
    return img.get_width()


def wrap(s, max_w, f=None):
    """Break text into lines no wider than max_w pixels, at spaces."""
    f = f or FONT()
    out = []
    for para in s.split("\n"):
        line = ""
        for word in para.split(" "):
            test = word if not line else line + " " + word
            if f.size(test)[0] <= max_w or not line:
                line = test
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


def box(surf, rect, fill, border=None, radius=6):
    pygame.draw.rect(surf, fill, rect, 0, radius)
    if border:
        pygame.draw.rect(surf, border, rect, 1, radius)


def frame(surf, rect, fill=None, border=None):
    fill = T.FIELD if fill is None else fill
    border = T.FIELD_BORDER if border is None else border
    box(surf, rect, fill, border, 6)


def inside(rect, pos):
    x, y, w, h = rect
    return pos is not None and x <= pos[0] < x + w and y <= pos[1] < y + h


def ctrl(ev):
    return bool(getattr(ev, "mod", 0) & pygame.KMOD_CTRL)


def shift(ev):
    return bool(getattr(ev, "mod", 0) & pygame.KMOD_SHIFT)


def is_text_key(ev):
    return ev.unicode and ord(ev.unicode[0]) >= 32 and not ctrl(ev)


class Widget:
    def __init__(self, rect):
        self.rect = pygame.Rect(rect)
        self.focus = False
        self.visible = True

    def draw(self, surf):
        pass

    def event(self, ev, pos):
        return False


class Label(Widget):
    def __init__(self, rect, s, color=None, f=None):
        Widget.__init__(self, rect)
        self.s, self.color, self.f = s, color, f

    def draw(self, surf):
        f = self.f or FONT()
        text(surf, self.s, self.rect.x, self.rect.y + (self.rect.h - f.get_height()) // 2, self.color or T.TEXT, f,
             self.rect.w)


class Button(Widget):
    def __init__(self, rect, label, on_click=None, primary=False):
        Widget.__init__(self, rect)
        self.label, self.on_click, self.primary = label, on_click, primary
        self.down = False

    def draw(self, surf):
        if self.primary:
            fill, border, color = T.ACCENT, None, T.ACCENT_TEXT
        else:
            fill, border, color = (T.BUTTON_HI if self.down else T.BUTTON), T.FIELD_BORDER, T.TEXT
        box(surf, self.rect, fill, border, 6)
        f = FONT()
        text(surf, self.label, self.rect.centerx, self.rect.y + (self.rect.h - f.get_height()) // 2, color, f,
             self.rect.w - 8, center=True)

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and inside(self.rect, pos):
            self.down = True
            return True
        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and self.down:
            self.down = False
            if inside(self.rect, pos) and self.on_click:
                self.on_click()
            return True
        return False


class Field(Widget):
    """One line of editable text."""

    def __init__(self, rect, text="", on_enter=None, password=False, placeholder=""):
        Widget.__init__(self, rect)
        self.text, self.cursor, self.on_enter, self.password = text, len(text), on_enter, password
        self.placeholder = placeholder

    def set(self, s):
        self.text, self.cursor = s, len(s)

    def draw(self, surf):
        box(surf, self.rect, T.FIELD, T.ACCENT if self.focus else T.FIELD_BORDER, 6)
        f = FONT()
        shown = ("•" * len(self.text)) if self.password else self.text
        y = self.rect.y + (self.rect.h - f.get_height()) // 2
        inner = self.rect.w - 14
        before = shown[:self.cursor]
        shift_x = max(0, f.size(before)[0] - inner)        # keep the cursor visible
        clip = surf.get_clip() if hasattr(surf, "get_clip") else None
        if not shown and self.placeholder and not self.focus:
            text(surf, self.placeholder, self.rect.x + 7, y, T.MUTED, f, inner)
        else:
            img = render(shown, T.TEXT, f) if shown else None
            if img:
                surf.blit(img, (self.rect.x + 7, y), (shift_x, 0, inner, img.get_height()))
        if self.focus:
            cx = self.rect.x + 7 + f.size(before)[0] - shift_x
            pygame.draw.line(surf, T.ACCENT, (cx, y + 1), (cx, y + f.get_height() - 2), 2)

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self.focus = inside(self.rect, pos)
            if self.focus:
                f, x, i = FONT(), pos[0] - self.rect.x - 7, 0
                while i < len(self.text) and f.size(self.text[:i + 1])[0] < x:
                    i += 1
                self.cursor = i
            return self.focus
        if not self.focus or ev.type != pygame.KEYDOWN:
            return False
        k = ev.key
        if k == pygame.K_RETURN:
            if self.on_enter:
                self.on_enter(self.text)
        elif k == pygame.K_BACKSPACE:
            if self.cursor:
                self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
                self.cursor -= 1
        elif k == pygame.K_DELETE:
            self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]
        elif k == pygame.K_LEFT:
            self.cursor = max(0, self.cursor - 1)
        elif k == pygame.K_RIGHT:
            self.cursor = min(len(self.text), self.cursor + 1)
        elif k == pygame.K_HOME:
            self.cursor = 0
        elif k == pygame.K_END:
            self.cursor = len(self.text)
        elif ctrl(ev) and k == pygame.K_v:
            from desktop import clipboard
            self.insert(clipboard.get().split("\n")[0])
        elif is_text_key(ev):
            self.insert(ev.unicode)
        else:
            return False
        return True

    def insert(self, s):
        self.text = self.text[:self.cursor] + s + self.text[self.cursor:]
        self.cursor += len(s)


class ListBox(Widget):
    def __init__(self, rect, items=(), on_pick=None, on_open=None, row_h=24):
        Widget.__init__(self, rect)
        self.items = list(items)
        self.selected = 0 if self.items else -1
        self.top = 0
        self.on_pick, self.on_open = on_pick, on_open
        self.row_h = row_h
        self._last = (0, -1)

    def set_items(self, items):
        self.items = list(items)
        self.selected = 0 if self.items else -1
        self.top = 0

    def rows(self):
        return max(1, (self.rect.h - 4) // self.row_h)

    def label(self, item):
        return item if isinstance(item, str) else str(item[0])

    def draw(self, surf):
        box(surf, self.rect, T.FIELD, T.FIELD_BORDER, 6)
        n, f = self.rows(), FONT()
        if self.selected >= 0:
            self.top = min(self.top, self.selected)
            self.top = max(self.top, self.selected - n + 1)
        for i in range(n):
            j = self.top + i
            if j >= len(self.items):
                break
            y = self.rect.y + 2 + i * self.row_h
            chosen = j == self.selected
            if chosen:
                box(surf, (self.rect.x + 3, y, self.rect.w - 6, self.row_h), T.ACCENT if self.focus else T.SELECT, None, 5)
            item = self.items[j]
            ty = y + (self.row_h - f.get_height()) // 2
            right = item[2] if isinstance(item, tuple) and len(item) > 2 else ""     # (label, data, right text)
            rw = width(right, f) + 14 if right else 0
            text(surf, self.label(item), self.rect.x + 10, ty, T.ACCENT_TEXT if chosen and self.focus else T.TEXT, f,
                 self.rect.w - 22 - rw)
            if right:
                text(surf, right, self.rect.right - rw - 4, ty, T.ACCENT_TEXT if chosen and self.focus else T.MUTED, f)
        if len(self.items) > n:                                      # scroll bar
            h = max(16, self.rect.h * n // len(self.items))
            y = self.rect.y + (self.rect.h - h) * self.top // max(1, len(self.items) - n)
            box(surf, (self.rect.right - 7, y, 4, h), (190, 194, 204), None, 2)

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and inside(self.rect, pos):
            self.focus = True
            if ev.button in (4, 5):
                step = -3 if ev.button == 4 else 3
                self.top = max(0, min(len(self.items) - self.rows(), self.top + step))
                return True
            j = self.top + (pos[1] - self.rect.y - 2) // self.row_h
            if 0 <= j < len(self.items):
                now = time.ticks_ms()
                double = self._last[1] == j and now - self._last[0] < 450
                self._last = (now, j)
                self.selected = j
                if self.on_pick:
                    self.on_pick(self.items[j])
                if double and self.on_open:
                    self.on_open(self.items[j])
            return True
        if ev.type == pygame.MOUSEBUTTONDOWN:
            self.focus = False
            return False
        if self.focus and ev.type == pygame.KEYDOWN and self.items:
            moves = {pygame.K_UP: -1, pygame.K_DOWN: 1, pygame.K_PAGEUP: -self.rows(), pygame.K_PAGEDOWN: self.rows()}
            if ev.key in moves:
                self.selected = max(0, min(len(self.items) - 1, self.selected + moves[ev.key]))
                if self.on_pick:
                    self.on_pick(self.items[self.selected])
                return True
            if ev.key == pygame.K_RETURN and self.on_open:
                self.on_open(self.items[self.selected])
                return True
        return False


class TextView(Widget):
    """Scrolling read-only text (logs, output). mono=True for columns."""

    def __init__(self, rect, lines=(), fg=None, bg=None, mono=False):
        Widget.__init__(self, rect)
        self.lines = list(lines)
        self.top = 0
        self.fg, self.bg, self.mono = fg, bg, mono
        self.follow = True

    def f(self):
        return MONO() if self.mono else FONT()

    def line_h(self):
        return self.f().get_height() + 2

    def rows(self):
        return max(1, (self.rect.h - 8) // self.line_h())

    def set_text(self, s):
        self.lines = wrap(s, self.rect.w - 16, self.f())
        self.top = 0

    def append(self, s):
        self.lines.extend(wrap(s, self.rect.w - 16, self.f()))
        if len(self.lines) > 2000:
            self.lines = self.lines[-1500:]
        if self.follow:
            self.top = max(0, len(self.lines) - self.rows())

    def draw(self, surf):
        bg = self.bg or T.FIELD
        box(surf, self.rect, bg, T.FIELD_BORDER if self.bg is None else None, 6)
        f, lh = self.f(), self.line_h()
        for i in range(self.rows()):
            j = self.top + i
            if j >= len(self.lines):
                break
            text(surf, self.lines[j], self.rect.x + 8, self.rect.y + 4 + i * lh, self.fg or T.TEXT, f, self.rect.w - 16)

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and inside(self.rect, pos) and ev.button in (4, 5):
            step = -3 if ev.button == 4 else 3
            self.top = max(0, min(max(0, len(self.lines) - self.rows()), self.top + step))
            self.follow = self.top >= len(self.lines) - self.rows()
            return True
        return False


class Form:
    """Holds widgets: draws them, routes events, moves focus with Tab."""

    def __init__(self):
        self.widgets = []

    def add(self, w):
        self.widgets.append(w)
        return w

    def draw(self, surf):
        for w in self.widgets:
            if w.visible:
                w.draw(surf)

    def event(self, ev, pos):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_TAB:
            focusable = [w for w in self.widgets if isinstance(w, (Field, ListBox)) and w.visible]
            if focusable:
                cur = next((i for i, w in enumerate(focusable) if w.focus), -1)
                for w in focusable:
                    w.focus = False
                focusable[(cur + (-1 if shift(ev) else 1)) % len(focusable)].focus = True
                return True
        used = False
        for w in self.widgets:
            if w.visible and w.event(ev, pos):
                used = True
                if ev.type != pygame.MOUSEBUTTONDOWN:
                    break
        return used


class MenuBar(Widget):
    """A menu bar at the top of a window: menus = [(title, [(label, fn) or None, ...])].
    Clicking a title opens its menu (the desktop's right-click menu)."""

    def __init__(self, width, menus, height=28):
        Widget.__init__(self, (0, 0, width, height))
        self.menus = menus

    def spots(self):
        x, f = 8, FONT()
        for title, items in self.menus:
            w = width(title, f) + 20
            yield title, items, pygame.Rect(x, 2, w, self.rect.h - 4)
            x += w

    def draw(self, surf):
        pygame.draw.rect(surf, (240, 242, 246), self.rect)
        pygame.draw.line(surf, (222, 225, 232), (0, self.rect.h - 1), (self.rect.w, self.rect.h - 1))
        f = FONT()
        for title, items, r in self.spots():
            text(surf, title, r.centerx, r.y + (r.h - f.get_height()) // 2, T.TEXT, f, center=True)

    def event(self, ev, pos):
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1 or pos is None or pos[1] >= self.rect.h:
            return False
        for title, items, r in self.spots():
            if r.collidepoint(pos):
                from desktop import wm
                mx, my = wm.wm.mouse                              # where on the screen the click was
                wm.wm.context_menu((mx - (pos[0] - r.x), my - pos[1] + self.rect.h), items)
                return True
        return False


def ask(title, message, default, on_done):
    """A dialog asking for one line of text (a file name, say)."""
    from desktop import wm
    wm.wm.ask(title, message, default, on_done)


def confirm(title, message, on_done):
    from desktop import wm
    wm.wm.confirm(title, message, on_done)


def toast(s):
    from desktop import wm
    wm.wm.toast(s)
