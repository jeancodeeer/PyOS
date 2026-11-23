# PyWin on the PyOS desktop: a Windows program's console and windows
# become desktop windows.
#
#   from pywin import host
#   host.start("/disk/Descargas/juego.exe")
#
# The program runs in its own thread. Everything that touches the desktop
# is handed to the desktop's loop with wm.later(), and the program waits
# for the answer when it needs one (a line of input, a message box button).
import _thread
import time
import pygame
from desktop import theme as T, ui
from desktop.wm import App
from pywin import gui
from pywin.process import Process

# pygame keys -> Windows virtual-key codes
VK = {pygame.K_BACKSPACE: 8, pygame.K_TAB: 9, pygame.K_RETURN: 13, pygame.K_ESCAPE: 27, pygame.K_SPACE: 32,
      pygame.K_PAGEUP: 33, pygame.K_PAGEDOWN: 34, pygame.K_END: 35, pygame.K_HOME: 36, pygame.K_LEFT: 37,
      pygame.K_UP: 38, pygame.K_RIGHT: 39, pygame.K_DOWN: 40, pygame.K_INSERT: 45, pygame.K_DELETE: 46,
      pygame.K_LSHIFT: 16, pygame.K_RSHIFT: 16, pygame.K_LCTRL: 17, pygame.K_RCTRL: 17}
for _k in range(12):
    VK[getattr(pygame, "K_F%d" % (_k + 1))] = 0x70 + _k

# MessageBox: which buttons, and what each returns (IDOK=1, IDCANCEL=2, IDYES=6, IDNO=7...)
BOXES = {0: (("Aceptar", 1),), 1: (("Cancelar", 2), ("Aceptar", 1)),
         2: (("Anular", 3), ("Reintentar", 4), ("Omitir", 5)), 3: (("Cancelar", 2), ("No", 7), ("Si", 6)),
         4: (("No", 7), ("Si", 6)), 5: (("Cancelar", 2), ("Reintentar", 4))}


def _wm():
    from desktop import wm
    return wm.wm


def menu_h(wnd):
    """Height of the menu bar a window has above its client area (0 if none)."""
    return gui.MENU_H if getattr(wnd, "menu", None) is not None else 0


def menu_entries(menu, on_pick, prefix=""):
    """A Win32 menu as the desktop's right-click menu items: (label, fn) or None.
    Sub-menus are flattened as "Sub > item"."""
    out = []
    for it in menu.items:
        if it.flags & gui.MF_SEPARATOR:
            if out and out[-1] is not None:
                out.append(None)
        elif it.popup is not None:
            out.extend(menu_entries(it.popup, on_pick, prefix + it.label + " > "))
        else:
            mark = "\u2713 " if it.flags & gui.MF_CHECKED else "   "
            if it.flags & (gui.MF_GRAYED | gui.MF_DISABLED):
                out.append(("   (" + prefix + it.label + ")", lambda: None))
            else:
                out.append((mark + prefix + it.label, (lambda n=it.id: on_pick(n))))
    while out and out[-1] is None:
        out.pop()
    return out or [("(vacio)", lambda: None)]


def vk_of(key):
    if key in VK:
        return VK[key]
    if 97 <= key <= 122:
        return key - 32                     # letters: 'A'..'Z'
    if 48 <= key <= 57:
        return key
    return key & 0xFF


class Host:
    """The `ui` of a Process running on the desktop."""

    def __init__(self, name):
        self.name = name
        self.p = None
        self.console = None
        self.answer = None
        self.keys_down = set()
        self.screen_size = T.SCREEN
        self.running = True

    # ---- the console (made the first time it is needed) ----
    def open_console(self):
        if self.console is None:
            self.console = "opening"
            _wm().later(self._open_console)

    def _open_console(self):
        win = _wm().open(ConsoleApp, self, name="pywin")
        win.set_title(self.name)

    def _wait_console(self):
        self.open_console()
        while not isinstance(self.console, ConsoleApp):
            time.sleep_ms(10)
        return self.console

    def write(self, text):
        self._wait_console().out(text)

    def read_line(self):
        c = self._wait_console()
        c.waiting = True
        c.redraw()
        while c.waiting:
            if self.p.killed:
                return ""
            time.sleep_ms(20)
        return c.line

    def title(self, text):
        if isinstance(self.console, ConsoleApp):
            self.console.win.set_title(text)

    def color(self, attr):
        self._wait_console().color(attr)

    def clear(self):
        self._wait_console().clear()

    def ask_path(self, title, default, save):
        """The Open / Save as dialog: a path, or None if cancelled."""
        box = {"done": False, "path": None}

        def answer(path):
            box["path"], box["done"] = path, True

        def show():
            w = _wm()
            w.ask(title, "Ruta del archivo:", default, answer)
            if w.dialog is not None:                    # Cancel / Esc also ends the wait
                done = w.dialog.done
                w.dialog.done = lambda v: (done(v), box.__setitem__("done", True))
        _wm().later(show)
        while not box["done"]:
            if self.p.killed:
                return None
            time.sleep_ms(20)
        return box["path"]

    def open_url(self, url):
        _wm().later(lambda: _wm().launch("browser", url))

    def open_path(self, path):
        from desktop import places
        _wm().later(lambda: places.open_path(path))

    def message_box(self, text, caption, flags):
        from desktop.dialog import Dialog
        buttons = BOXES.get(flags & 0xF, BOXES[0])
        box = {"result": None}

        def show():
            w = _wm()
            values = tuple((label, n) for label, n in buttons)
            d = Dialog(w, caption, text.replace("\r", "").replace("\n", "  "), None, values,
                       lambda v: box.__setitem__("result", v if v is not False else buttons[0][1]))
            w.dialog = d
            try:
                from kernel import sound
                if sound.card:
                    sound.play_wav("/share/sounds/aviso.wav")
            except Exception:
                pass
        _wm().later(show)
        while box["result"] is None:
            if self.p.killed:
                return 2
            time.sleep_ms(20)
        return box["result"]

    # ---- windows ----
    def open_window(self, wnd):
        wnd.host = "opening"
        _wm().later(lambda: self._open_window(wnd))

    def _open_window(self, wnd):
        if getattr(wnd, "destroyed", False):
            return
        win = _wm().open(Win32App, self, wnd, name="pywin")
        win.resize(wnd.w, wnd.h + menu_h(wnd))
        win.set_title(wnd.title or self.name)
        wnd.host = win

    def close_window(self, wnd):
        def close():
            win = wnd.host
            if isinstance(win, object) and hasattr(win, "app") and win.app is not None:
                win.app.forced = True
                _wm().close(win)
            wnd.host = None
        _wm().later(close)

    def resize_window(self, wnd):
        def resize():
            if hasattr(wnd.host, "resize"):
                wnd.host.resize(wnd.w, wnd.h + menu_h(wnd))
        _wm().later(resize)

    def title_window(self, wnd):
        def title():
            if hasattr(wnd.host, "set_title"):
                wnd.host.set_title(wnd.title)
        _wm().later(title)

    def client_origin(self, wnd):
        top = wnd
        while top.parent is not None and top.style & gui.WS_CHILD:
            top = top.parent
        if not hasattr(top.host, "client_origin"):
            return 0, 0
        x, y = top.host.client_origin()
        ox, oy = wnd.offset_in_top()
        return x + ox, y + oy + menu_h(top)

    def popup_menu(self, menu, pos):
        """TrackPopupMenu: show the menu at pos and wait. The chosen command, or 0."""
        box = {"choice": None, "shown": False}

        def show():
            w = _wm()
            w.context_menu(pos, menu_entries(menu, lambda n: box.__setitem__("choice", n)))
            box["shown"] = True
        _wm().later(show)
        while box["choice"] is None:
            if self.p.killed or (box["shown"] and _wm().menu is None):
                break
            time.sleep_ms(20)
        return box["choice"] or 0

    def mouse(self):
        return pygame.mouse.get_pos()

    def wait(self, ms):
        time.sleep_ms(ms or 1)              # gives the desktop its turn

    # ---- running ----
    def run(self):
        code = self.p.run()
        self.running = False
        self.code = code

        def finished():
            from pywin.dlls import user32
            for wnd in list(user32.state(self.p).windows.values()) if "user32" in self.p.state else ():
                if hasattr(wnd.host, "app") and wnd.host.app is not None:
                    wnd.host.app.forced = True
                    _wm().close(wnd.host)
            if isinstance(self.console, ConsoleApp):
                self.console.out("\n[el programa ha terminado con el codigo %d]\n" % (code if code < 0x80000000 else code - (1 << 32)))
            elif code not in (0,):
                _wm().toast("%s ha terminado con el codigo %#x" % (self.name, code))
        _wm().later(finished)


def start(path, args=()):
    """Run a Windows program on the desktop. Returns the Host, or None."""
    name = path.rsplit("/", 1)[-1]
    host = Host(name)
    try:
        host.p = Process(path, args, ui=host)
    except Exception as e:
        _wm().toast("PyWin: no se puede abrir %s: %s" % (name, e))
        return None
    if host.p.image.console:
        host.open_console()
    try:
        _thread.stack_size(64 * 1024)
    except Exception:
        pass
    _thread.start_new_thread(host.run, ())
    return host


# ---- the console window ----

# the 16 console colours (Windows Terminal's "Campbell" scheme)
PALETTE = [(12, 12, 12), (0, 55, 218), (19, 161, 14), (58, 150, 221), (197, 15, 31), (136, 23, 152),
           (193, 156, 0), (204, 204, 204), (118, 118, 118), (59, 120, 255), (22, 198, 12), (97, 214, 214),
           (231, 72, 86), (180, 0, 158), (249, 241, 165), (242, 242, 242)]
# ANSI colour numbers (30-37) -> console colour numbers
ANSI = [0, 4, 2, 6, 1, 5, 3, 7]


class ConsoleApp(App):
    """A Windows console: lines of coloured pieces of text, and a line to type."""
    title = "Consola"
    size = (680, 400)

    def __init__(self, win, host):
        App.__init__(self, win)
        self.host = host
        self.lines = [[]]               # each line: [(text, colour number, background number)]
        self.attr = 7                   # light grey on black
        self.escape = None              # an ANSI sequence being read
        self.waiting = False
        self.typed = ""
        self.line = ""
        host.console = self

    def color(self, attr):
        self.attr = attr & 0xFF

    def _put(self, text):
        fg, bg = self.attr & 15, (self.attr >> 4) & 15
        line = self.lines[-1]
        if line and line[-1][1] == fg and line[-1][2] == bg:
            line[-1] = (line[-1][0] + text, fg, bg)
        else:
            line.append((text, fg, bg))

    def _ansi(self, code):
        """ESC [ ... m (colours), ESC [ 2 J (clear), ESC [ H (home)."""
        kind, params = code[-1], code[:-1]
        if kind == "m":
            for n in [int(x) if x.isdigit() else 0 for x in (params.split(";") if params else ["0"])]:
                if n == 0:
                    self.attr = 7
                elif n == 1:
                    self.attr |= 8
                elif 30 <= n <= 37:
                    self.attr = (self.attr & 0xF8) | ANSI[n - 30]
                elif 90 <= n <= 97:
                    self.attr = (self.attr & 0xF0) | ANSI[n - 90] | 8
                elif 40 <= n <= 47:
                    self.attr = (self.attr & 0x0F) | ANSI[n - 40] << 4
                elif n == 39:
                    self.attr = (self.attr & 0xF0) | 7
                elif n == 49:
                    self.attr &= 0x0F
        elif kind == "J" and params in ("2", "3"):
            self.lines = [[]]

    def out(self, text):
        piece = ""
        for ch in text:
            if self.escape is not None:
                self.escape += ch
                if ch.isalpha():
                    if self.escape.startswith("["):
                        self._put(piece)
                        piece = ""
                        self._ansi(self.escape[1:])
                    self.escape = None
                continue
            if ch == "\x1b":
                self._put(piece)
                piece = ""
                self.escape = ""
            elif ch == "\n":
                self._put(piece)
                piece = ""
                self.lines.append([])
            elif ch == "\b":
                self._put(piece)
                piece = ""
                line = self.lines[-1]
                if line:
                    text0, fg, bg = line[-1]
                    line[-1] = (text0[:-1], fg, bg)
            elif ch == "\t":
                piece += "    "
            elif ch != "\r":
                piece += ch
        self._put(piece)
        if len(self.lines) > 1000:
            self.lines = self.lines[-800:]
        self.redraw()

    def clear(self):
        self.lines = [[]]
        self.redraw()

    def draw(self, surf):
        surf.fill(PALETTE[0])
        f = ui.MONO()
        lh = f.get_height() + 1
        cw = f.size("M")[0]
        cols = max(10, (self.win.w - 16) // cw)
        rows = []                                    # screen rows: [(text, fg, bg)]
        shown = self.lines[-200:]
        for k, line in enumerate(shown):
            pieces = list(line)
            if self.waiting and k == len(shown) - 1:
                pieces.append((self.typed + "_", 15, 0))  # what is being typed, after the prompt
            row, used = [], 0
            for text, fg, bg in pieces:
                while text:
                    take = text[:cols - used]
                    row.append((take, fg, bg))
                    used += len(take)
                    text = text[len(take):]
                    if used >= cols:
                        rows.append(row)
                        row, used = [], 0
            rows.append(row)
        visible = max(1, (self.win.h - 8) // lh)
        y = 6
        for row in rows[-visible:]:
            x = 8
            for text, fg, bg in row:
                if bg:
                    pygame.draw.rect(surf, PALETTE[bg], (x, y, cw * len(text), lh))
                ui.text(surf, text, x, y, PALETTE[fg], f)
                x += cw * len(text)
            y += lh

    def event(self, ev, pos):
        if ev.type != pygame.KEYDOWN:
            return False
        if ui.ctrl(ev) and ev.key == pygame.K_c:
            if self.host.running:
                self.host.p.killed = True
                self.out("^C\n")
            return True
        if not self.waiting:
            return False
        if ev.key == pygame.K_RETURN:
            self.out(self.typed + "\n")
            self.line, self.typed = self.typed + "\n", ""
            self.waiting = False
        elif ev.key == pygame.K_BACKSPACE:
            self.typed = self.typed[:-1]
        elif ui.ctrl(ev) and ev.key == pygame.K_v:
            from desktop import clipboard
            self.typed += (clipboard.get() or "").split("\n")[0]
        elif ui.is_text_key(ev):
            self.typed += ev.unicode
        else:
            return False
        self.redraw()
        return True

    def close(self):
        if self.host.running:
            self.host.p.killed = True       # closing the console ends the program, as on Windows
        return True


# ---- a Win32 window ----

class Win32App(App):
    title = "Ventana"
    size = (400, 300)

    def __init__(self, win, host, wnd):
        App.__init__(self, win)
        self.host, self.wnd = host, wnd
        self.forced = False
        self.down = None                    # the window that got the button press

    def state(self):
        from pywin.dlls import user32
        return user32.state(self.host.p)

    def draw(self, surf):
        mh = menu_h(self.wnd)
        if mh:
            self.draw_menu_bar(surf)
        self.wnd.compose(surf, 0, mh)

    def draw_menu_bar(self, surf):
        """The window's menu (Archivo, Editar...) as a bar of words."""
        f = ui.font(13)
        pygame.draw.rect(surf, (249, 249, 249), (0, 0, self.win.w, gui.MENU_H))
        pygame.draw.line(surf, (220, 220, 220), (0, gui.MENU_H - 1), (self.win.w, gui.MENU_H - 1))
        self.bar = []
        x = 4
        for it in self.wnd.menu.items:
            if it.flags & gui.MF_SEPARATOR:
                continue
            w = f.size(it.label)[0] + 16
            grey = it.flags & (gui.MF_GRAYED | gui.MF_DISABLED)
            ui.text(surf, it.label, x + 8, (gui.MENU_H - f.get_height()) // 2,
                    (150, 150, 150) if grey else (20, 20, 20), f)
            self.bar.append((pygame.Rect(x, 0, w, gui.MENU_H), it))
            x += w

    def menu_click(self, pos):
        for rect, it in getattr(self, "bar", []):
            if rect.collidepoint(pos) and not it.flags & (gui.MF_GRAYED | gui.MF_DISABLED):
                handle = self.wnd.handle
                post = lambda n: self.state().post(handle, gui.WM_COMMAND, n, 0)   # noqa: E731
                if it.popup is None:                       # a word on the bar that is a command
                    post(it.id)
                    return
                ox, oy = self.win.client_origin()
                _wm().context_menu((ox + rect.x, oy + gui.MENU_H), menu_entries(it.popup, post))
                return

    def tick(self, now):
        if self.wnd.changed:
            self.wnd.changed = False
            return True
        return False

    def resized(self, w, h):
        h -= menu_h(self.wnd)
        if (w, h) != (self.wnd.w, self.wnd.h):
            self.wnd.resize(w, h)
            self.state().post(self.wnd.handle, gui.WM_SIZE, 0, (h << 16) | w)

    def _post(self, target, msg, wparam, x, y):
        self.state().post(target.handle, msg, wparam, ((y & 0xFFFF) << 16) | (x & 0xFFFF))

    def event(self, ev, pos):
        s = self.state()
        mh = menu_h(self.wnd)
        if pos and mh:
            if pos[1] < mh:                                # on the menu bar
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    self.menu_click(pos)
                return ev.type != pygame.MOUSEMOTION
            pos = (pos[0], pos[1] - mh)
        if ev.type == pygame.MOUSEBUTTONDOWN and pos:
            target, (x, y) = self.wnd.child_at(pos)
            if ev.button in (4, 5):
                delta = 120 if ev.button == 4 else -120
                s.post(target.handle, gui.WM_MOUSEWHEEL, (delta & 0xFFFF) << 16, 0)
                return True
            self.down = target
            msg = gui.WM_LBUTTONDOWN if ev.button == 1 else gui.WM_RBUTTONDOWN
            self._post(target, msg, 1 if ev.button == 1 else 2, x, y)
            return True
        if ev.type == pygame.MOUSEBUTTONUP and pos and ev.button in (1, 3):
            target = self.down or self.wnd.child_at(pos)[0]
            ox, oy = target.offset_in_top()
            self._post(target, gui.WM_LBUTTONUP if ev.button == 1 else gui.WM_RBUTTONUP, 0,
                       pos[0] - ox, pos[1] - oy)
            self.down = None
            return True
        if ev.type == pygame.MOUSEMOTION and pos:
            target, (x, y) = self.wnd.child_at(pos)
            if s.queue and s.queue[-1][1] == gui.WM_MOUSEMOVE:
                s.queue.pop()               # only the latest position matters
            self._post(target, gui.WM_MOUSEMOVE, 1 if ev.buttons[0] else 0, x, y)
            return False
        if ev.type == pygame.KEYDOWN:
            vk = vk_of(ev.key)
            self.host.keys_down.add(vk)
            focus = s.windows.get(s.focus) or self.wnd
            s.post(focus.handle, gui.WM_KEYDOWN, vk, 1)
            if ev.unicode and (ev.unicode >= " " or ev.key in (pygame.K_RETURN, pygame.K_BACKSPACE, pygame.K_TAB)):
                s.post(focus.handle, gui.WM_CHAR, ord(ev.unicode[0]), 1)
            return True
        if ev.type == pygame.KEYUP:
            vk = vk_of(ev.key)
            self.host.keys_down.discard(vk)
            focus = s.windows.get(s.focus) or self.wnd
            s.post(focus.handle, gui.WM_KEYUP, vk, 0xC0000001)
            return True
        return False

    def close(self):
        if self.forced or not self.host.running:
            return True
        self.state().post(self.wnd.handle, gui.WM_CLOSE)     # the program decides
        return False
