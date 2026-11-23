# The window manager: windows, the top bar, the dock and the launcher.
#
# Each window belongs to an app object (see App below and desktop/apps).
# The window gives the app a Surface for its client area; the app draws into
# it when asked and gets the events meant for it, with positions relative to
# that area. Everything is redrawn into one screen Surface, then flipped.
import time
import pygame
from pygame.constants import SRCALPHA
from desktop import theme as T, ui, icons

wm = None
START = []          # [(app name, arg...)] opened when the desktop starts
SCRIPT = []         # [(ms after start, fn)]: scripted actions (demos, tests)


class App:
    """Base class for desktop apps. Override what you need."""
    title = "App"
    size = (480, 320)
    resizable = True

    def __init__(self, win, *args):
        self.win = win

    def draw(self, surf):
        surf.fill(T.WIN_BG)

    def event(self, ev, pos):
        return False

    def tick(self, now_ms):
        """Called every frame; return True to be redrawn."""
        return False

    def resized(self, w, h):
        pass

    def close(self):
        return True                    # False keeps the window open

    def redraw(self):
        self.win.dirty = True


class Window:
    def __init__(self, app_class, args, name):
        sw, sh = T.SCREEN
        w, h = app_class.size
        w = min(w, sw - 20)
        h = min(h, sh - T.TOP_H - T.DOCK_H - T.TITLE_H - 20)
        n = len(wm.windows)
        self.x = max(0, min((sw - w) // 2 - 120 + 30 * (n % 8), sw - w - 2))
        self.y = max(T.TOP_H + 6, min(T.TOP_H + 30 + 26 * (n % 8), sh - T.DOCK_H - T.TITLE_H - h - 6))
        self.w, self.h = w, h                         # client size
        self.surf = pygame.Surface((w, h))
        self.name = name
        self.minimized = False
        self.maximized = None                         # saved geometry while maximized
        self.dirty = True
        self.shadow = None
        self.app = app_class(self, *args)
        self.title = getattr(self.app, "title", app_class.title)

    def frame_rect(self):
        return pygame.Rect(self.x, self.y, self.w, self.h + T.TITLE_H)

    def client_origin(self):
        return self.x, self.y + T.TITLE_H

    def buttons(self):
        """(close, minimize, maximize) circles on the left of the title bar."""
        cy = self.y + T.TITLE_H // 2
        return [pygame.Rect(self.x + 12 + 20 * i, cy - 6, 12, 12) for i in range(3)]

    def resize(self, w, h):
        w, h = max(200, w), max(100, h)
        if (w, h) == (self.w, self.h):
            return
        self.w, self.h = w, h
        self.surf = pygame.Surface((w, h))
        self.shadow = None
        self.app.resized(w, h)
        self.dirty = True

    def toggle_maximize(self):
        if self.maximized:
            self.x, self.y, w, h = self.maximized
            self.maximized = None
        else:
            self.maximized = (self.x, self.y, self.w, self.h)
            self.x, self.y = 0, T.TOP_H
            w, h = T.SCREEN[0], T.SCREEN[1] - T.TOP_H - T.DOCK_H - T.TITLE_H
        self.resize(w, h)

    def set_title(self, s):
        self.title = s
        if wm:
            wm.dirty = True


def _shadow(w, h):
    """A soft dark halo around a w x h window (built once per size)."""
    pad = 14
    s = pygame.Surface((w + 2 * pad, h + 2 * pad), SRCALPHA)
    s.fill((0, 0, 0, 0))
    for i in range(pad, 0, -2):
        a = int(70 * (1 - i / pad) ** 2) + 4
        pygame.draw.rect(s, (0, 0, 0, a), (pad - i, pad - i + 4, w + 2 * i, h + 2 * i), 0, T.RADIUS + i)
    return s


class WindowManager:
    def __init__(self):
        global wm
        wm = self
        self.screen = pygame.display.set_mode(T.SCREEN)
        pygame.display.set_caption("PyKernel")
        try:
            pygame.key.set_repeat(350, 40)
        except Exception:
            pass
        self.windows = []                  # bottom to top
        self.drag = None                   # (window, dx, dy, mode)
        self.launcher = None               # the open launcher, or None
        self.dirty = True
        self.running = True
        self.after = None
        self.clock = pygame.time.Clock()
        self.notice = ("", 0)
        self.caption = ("", 0)             # a subtitle (guided tour, videos)
        self.mouse = (0, 0)
        self.last_title_click = (0, None)
        self.desktop_focus = False
        self.shadow, self.shadow_key = None, None
        from pyos import config
        self.wall_index = config.get("wallpaper", 0)
        cached = globals().get("_cached_wallpaper")
        self.wallpaper = cached if cached is not None and self.wall_index == 0 else wallpaper(self.wall_index)
        self.dialog = None                 # a modal Dialog on top of everything
        self.menu = None                   # an open right-click Menu
        self.calls = []                    # later(fn): run by the desktop's own loop
        from desktop.deskicons import DesktopIcons
        self.icons = DesktopIcons(self)

    # ---- windows ----
    def open(self, app_class, *args, name=None):
        win = Window(app_class, args, name or "about")
        self.windows.append(win)
        self.launcher = None
        self.dirty = True
        return win

    def close(self, win):
        try:
            ok = win.app.close()
        except Exception as e:
            self.error(e)
            ok = True
        if ok is False:
            return
        if win in self.windows:
            self.windows.remove(win)
        win.app = win.surf = win.shadow = None
        import gc
        gc.collect()                       # a window is a big pixel buffer: give it back now
        self.dirty = True

    def focus(self, win):
        if win in self.windows:
            self.windows.remove(win)
            self.windows.append(win)
        win.minimized = False
        self.dirty = True

    def top(self):
        for w in reversed(self.windows):
            if not w.minimized:
                return w
        return None

    def window_at(self, pos):
        for w in reversed(self.windows):
            if not w.minimized and w.frame_rect().collidepoint(pos):
                return w
        return None

    def launch(self, target, *args):
        from desktop import apps
        try:
            if callable(target) and not isinstance(target, type):
                return target()
            if isinstance(target, str) and apps.info(target).get("mode") == "fullscreen":
                return self.run_fullscreen(apps.info(target)["path"])
            cls = apps.load(target) if isinstance(target, str) else target
            if cls is None:
                return None
            return self.open(cls, *args, name=target if isinstance(target, str) else None)
        except Exception as e:
            self.error(e)

    def run_fullscreen(self, path):
        """Give the whole screen to a plain pygame program until it quits."""
        import sys
        display = pygame.display
        saved = (display.quit, pygame.quit, display.set_mode)
        display.quit = pygame.quit = lambda: None          # it must not switch back to text mode
        self.fullscreen = path
        try:
            ns = {"__name__": "__main__", "__file__": path}
            with open(path) as f:
                exec(compile(f.read(), path, "exec"), ns)
        except SystemExit:
            pass
        except Exception as e:
            self.error(e)
        finally:
            self.fullscreen = None
            display.quit, pygame.quit, display.set_mode = saved
            try:                                        # an OpenGL program leaves big buffers behind
                from OpenGL import context
                context.current = None
            except ImportError:
                pass
            import gc
            gc.collect()
            self.screen = display.set_mode(T.SCREEN)
            pygame.event.get()                              # drop what the program left behind
            for w in self.windows:
                w.dirty = True
            self.dirty = True

    def later(self, fn):
        """Run fn in the desktop's loop. Safe to call from another thread
        (PyWin programs run in their own thread)."""
        self.calls.append(fn)

    # ---- dialogs, menus, wallpaper ----
    def ask(self, title, message, text, on_done):
        from desktop.dialog import Dialog
        self.dialog = Dialog(self, title, message, text, (("Cancelar", False), ("Aceptar", True)), on_done)
        self.dirty = True

    def confirm(self, title, message, on_done):
        from desktop.dialog import Dialog
        self.dialog = Dialog(self, title, message, None, (("Cancelar", False), ("Aceptar", True)), on_done)
        self.dirty = True

    def context_menu(self, pos, items):
        from desktop.dialog import Menu
        self.menu = Menu(self, pos, items)
        self.dirty = True

    def next_wallpaper(self):
        from pyos import config
        self.wall_index = (self.wall_index + 1) % len(WALLPAPERS)
        config.set("wallpaper", self.wall_index)
        self.wallpaper = wallpaper(self.wall_index)
        self.dirty = True

    def toast(self, s):
        self.notice = (s, time.ticks_ms() + 3500)
        self.dirty = True

    def error(self, e):
        import io
        import sys
        buf = io.StringIO()
        sys.print_exception(e, buf)
        try:
            from kernel import log
            import _kernel
            log.error("desktop: " + buf.getvalue().strip().replace("\n", " | "))
            _kernel.serial_write(buf.getvalue().encode())
        except Exception:
            pass
        self.toast("error: %r" % e)

    # ---- drawing ----
    def draw(self):
        scr = self.screen
        scr.blit(self.wallpaper, (0, 0))
        self.icons.draw(scr)
        top = self.top()
        for win in self.windows:
            if win.minimized:
                continue
            if win.dirty:
                try:
                    win.app.draw(win.surf)
                except Exception as e:
                    win.surf.fill(T.WIN_BG)
                    ui.text(win.surf, "draw failed: %r" % e, 10, 10, T.RED)
                win.dirty = False
            self.draw_frame(scr, win, win is top)
            scr.blit(win.surf, win.client_origin())
        self.draw_top_bar(scr, top)
        self.draw_dock(scr)
        if self.launcher:
            self.launcher.draw(scr)
        if self.menu:
            self.menu.draw(scr)
        if self.dialog:
            self.dialog.draw(scr)
        self.draw_toast(scr)
        self.draw_subtitle(scr)
        pygame.display.flip()
        self.dirty = False

    def draw_frame(self, scr, win, active):
        if active:                                   # one soft shadow, for the window in front
            key = (win.w, win.h)
            if self.shadow_key != key:
                self.shadow_key, self.shadow = key, _shadow(win.w, win.h + T.TITLE_H)
            scr.blit(self.shadow, (win.x - 14, win.y - 14))
        else:                                        # the others: a cheap dark edge
            pygame.draw.rect(scr, (30, 30, 40), win.frame_rect().move(2, 3), 0, T.RADIUS)
        fr = win.frame_rect()
        pygame.draw.rect(scr, T.WIN_BORDER, fr.inflate(2, 2), 0, T.RADIUS + 1)
        pygame.draw.rect(scr, T.TITLE_BG if active else T.TITLE_BG_OFF, fr, 0, T.RADIUS)
        f = ui.font(13, bold=True)
        title_w = win.w - 90
        ui.text(scr, win.title, win.x + 70 + title_w // 2, win.y + (T.TITLE_H - f.get_height()) // 2,
                T.TITLE_TEXT if active else T.TITLE_TEXT_OFF, f, title_w, center=True)
        colors = (T.RED, T.YELLOW, T.GREEN) if active else ((200, 202, 208),) * 3
        for rect, c in zip(win.buttons(), colors):
            pygame.draw.circle(scr, c, rect.center, 6)
        if not win.maximized and getattr(win.app, "resizable", True):
            gx, gy = win.x + win.w - 12, win.y + T.TITLE_H + win.h - 12
            for i in (4, 8):
                pygame.draw.line(scr, (170, 174, 184), (gx + i, gy + 10), (gx + 10, gy + i))

    def draw_top_bar(self, scr, top):
        sw = T.SCREEN[0]
        scr.blit(_panel(sw, T.TOP_H, 0), (0, 0))
        f, fb = ui.font(13), ui.font(13, bold=True)
        y = (T.TOP_H - f.get_height()) // 2
        from pyos import logo
        scr.blit(logo.surface(20), (8, (T.TOP_H - 20) // 2))
        ui.text(scr, "PyOS", 34, y, T.PANEL_TEXT, fb)
        if top is not None:
            ui.text(scr, top.title, 90, y, (200, 204, 214), f, 300)
        t = time.localtime()
        days = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")
        ui.text(scr, "%s %d  %02d:%02d" % (days[t[6]], t[2], t[3], t[4]), sw // 2, y, T.PANEL_TEXT, fb, center=True)
        import gc
        x = sw - 12
        for label in (_net_label(), "%d MB libres" % (gc.mem_free() >> 20), _sound_label()):
            if label:
                x -= ui.width(label, f)
                ui.text(scr, label, x, y, (210, 214, 224), f)
                x -= 18

    def dock_items(self):
        from desktop import apps
        names = list(apps.DOCK)
        for w in self.windows:
            if w.name not in names:
                names.append(w.name)
        return names

    def dock_rects(self):
        names = self.dock_items()
        size, gap = 44, 10
        total = len(names) * (size + gap) - gap + 24
        x0 = (T.SCREEN[0] - total) // 2
        y = T.SCREEN[1] - T.DOCK_H + (T.DOCK_H - size) // 2 - 2
        panel = pygame.Rect(x0, y - 8, total, size + 16)
        return panel, [(n, pygame.Rect(x0 + 12 + i * (size + gap), y, size, size)) for i, n in enumerate(names)]

    def draw_dock(self, scr):
        panel, items = self.dock_rects()
        scr.blit(_panel(panel.w, panel.h, 16), panel.topleft)
        from desktop import apps
        running = {w.name for w in self.windows}
        hovered = None
        for name, r in items:
            if r.collidepoint(self.mouse):
                hovered = (name, r)
                scr.blit(icons.icon(apps.icon_name(name), 52, apps.label(name)), (r.x - 4, r.y - 8))   # grows under the mouse
            else:
                scr.blit(icons.icon(apps.icon_name(name), 44, apps.label(name)), r.topleft)
            if name in running:
                pygame.draw.circle(scr, (240, 242, 248), (r.centerx, r.bottom + 6), 2)
        if hovered:
            label = apps.label(hovered[0])
            f = ui.font(13)
            w = ui.width(label, f) + 20
            y = panel.y - 34
            scr.blit(_panel(w, 26, 8), (hovered[1].centerx - w // 2, y))
            ui.text(scr, label, hovered[1].centerx, y + 5, T.PANEL_TEXT, f, center=True)

    def subtitle(self, text, ms=3500):
        """A line of text at the bottom of the screen, above the dock, for a while."""
        self.caption = (text, time.ticks_ms() + ms)
        self.dirty = True

    def draw_subtitle(self, scr):
        s, until = self.caption
        if not s or time.ticks_ms() > until:
            return
        f = ui.font(18, bold=True)
        w = min(T.SCREEN[0] - 80, ui.width(s, f) + 48)
        x, y = (T.SCREEN[0] - w) // 2, T.SCREEN[1] - T.DOCK_H - 64
        scr.blit(_panel(w, 46, 14), (x, y))
        ui.text(scr, s, T.SCREEN[0] // 2, y + 13, (255, 255, 255), f, w - 30, center=True)

    def draw_toast(self, scr):
        s, until = self.notice
        if not s or time.ticks_ms() > until:
            return
        f = ui.font(13)
        w = min(460, ui.width(s, f) + 32)
        x, y = T.SCREEN[0] - w - 14, T.TOP_H + 12
        scr.blit(_panel(w, 40, 10), (x, y))
        ui.text(scr, s, x + 16, y + 11, T.PANEL_TEXT, f, w - 30)

    # ---- events ----
    def handle(self, ev):
        if ev.type == pygame.QUIT:
            self.running = False
            return
        if hasattr(ev, "pos"):
            near_dock = T.SCREEN[1] - T.DOCK_H - 40
            if ev.type == pygame.MOUSEMOTION and (ev.pos[1] > near_dock or self.mouse[1] > near_dock):
                self.dirty = True                      # the dock reacts to the mouse
            self.mouse = ev.pos
        if self.dialog:
            self.dialog.event(ev)
            self.dirty = True
            return
        if self.menu:
            if ev.type == pygame.MOUSEMOTION:
                self.dirty = True
            else:
                self.menu.event(ev)
            return
        if self.launcher:
            self.launcher.event(ev)
            self.dirty = True
            return
        if ev.type == pygame.MOUSEMOTION and self.icons.mouse_move(ev):
            self.dirty = True
            return
        if ev.type == pygame.MOUSEBUTTONUP and self.icons.mouse_up(ev):
            self.dirty = True
            return
        if ev.type == pygame.KEYDOWN:
            alt = ev.mod & pygame.KMOD_ALT
            if (ev.key == pygame.K_TAB and alt) or ev.key == pygame.K_F6:
                if self.windows:
                    self.focus(self.windows[0])
                return
            if ev.key in (pygame.K_LGUI, getattr(pygame, "K_RGUI", -1)) or (ev.key == pygame.K_SPACE and ui.ctrl(ev)):
                self.open_launcher()
                return
            if ev.key == pygame.K_F4 and alt:
                if self.top():
                    self.close(self.top())
                return
        if ev.type == pygame.MOUSEBUTTONDOWN:
            self.mouse_down(ev)
            return
        if ev.type == pygame.MOUSEMOTION and self.drag:
            win, dx, dy, mode = self.drag
            if mode == "move":
                win.x = max(-win.w + 80, min(T.SCREEN[0] - 80, ev.pos[0] - dx))
                win.y = max(T.TOP_H, min(T.SCREEN[1] - T.DOCK_H - T.TITLE_H, ev.pos[1] - dy))
            else:
                win.resize(ev.pos[0] - win.x + dx, ev.pos[1] - win.y - T.TITLE_H + dy)
            self.dirty = True
            return
        if ev.type == pygame.MOUSEBUTTONUP and self.drag:
            self.drag = None
            return
        win = self.top()
        if win is None or (ev.type == pygame.KEYDOWN and self.icons.selected is not None and self.desktop_focus):
            if ev.type == pygame.KEYDOWN and self.icons.key(ev):
                self.dirty = True
            return
        if ev.type == pygame.MOUSEMOTION and self.window_at(ev.pos) is not win and not any(getattr(ev, "buttons", (0,))):
            return
        self.send(win, ev)

    def send(self, win, ev):
        pos = None
        if hasattr(ev, "pos"):
            ox, oy = win.client_origin()
            pos = (ev.pos[0] - ox, ev.pos[1] - oy)
        try:
            if win.app.event(ev, pos):
                win.dirty = True
                self.dirty = True
        except Exception as e:
            self.error(e)

    def mouse_down(self, ev):
        pos = ev.pos
        if pos[1] < T.TOP_H:
            if pos[0] < 100:
                self.open_launcher()
            return
        panel, items = self.dock_rects()
        if panel.collidepoint(pos):
            for name, r in items:
                if r.collidepoint(pos) and ev.button == 1:
                    self.dock_click(name)
            return
        win = self.window_at(pos)
        if win is None:                                 # the desktop itself: its icons
            self.desktop_focus = True
            self.icons.mouse_down(ev)
            self.dirty = True
            return
        self.desktop_focus = False
        self.icons.selected = None
        if win is not self.top():
            self.focus(win)
        if ev.button == 1 and pos[1] < win.y + T.TITLE_H:
            close, mini, maxi = win.buttons()
            if close.inflate(6, 6).collidepoint(pos):
                self.close(win)
            elif mini.inflate(6, 6).collidepoint(pos):
                win.minimized = True
                self.dirty = True
            elif maxi.inflate(6, 6).collidepoint(pos):
                win.toggle_maximize()
                self.dirty = True
            else:
                now = time.ticks_ms()
                if self.last_title_click[1] is win and now - self.last_title_click[0] < 400:
                    win.toggle_maximize()               # double click on the title bar
                    self.dirty = True
                    return
                self.last_title_click = (now, win)
                self.drag = (win, pos[0] - win.x, pos[1] - win.y, "move")
            return
        if (ev.button == 1 and not win.maximized and getattr(win.app, "resizable", True) and
                pos[0] > win.x + win.w - 14 and pos[1] > win.y + T.TITLE_H + win.h - 14):
            self.drag = (win, win.x + win.w - pos[0], win.y + T.TITLE_H + win.h - pos[1], "resize")
            return
        self.send(win, ev)

    def dock_click(self, name):
        mine = [w for w in self.windows if w.name == name]
        if not mine:
            self.launch(name)
        elif mine[-1] is self.top():
            mine[-1].minimized = True
        else:
            self.focus(mine[-1])
        self.dirty = True

    def open_launcher(self):
        from desktop.launcher import Launcher
        self.launcher = Launcher(self)
        self.dirty = True

    # ---- the loop ----
    def run(self):
        for item in START:
            self.launch(item[0], *item[1:])
        START.clear()
        script = sorted(SCRIPT, key=lambda a: a[0])
        SCRIPT.clear()
        t0 = time.ticks_ms()
        last_minute = None
        last_gc = t0
        while self.running:
            for ev in pygame.event.get():
                self.handle(ev)
            while self.calls:
                try:
                    self.calls.pop(0)()
                except Exception as e:
                    self.error(e)
                self.dirty = True
            now = time.ticks_ms()
            while script and now - t0 >= script[0][0]:
                try:
                    script.pop(0)[1]()
                except Exception as e:
                    self.error(e)
                self.dirty = True
            for win in list(self.windows):
                try:
                    if win.app and win.app.tick(now):
                        win.dirty = True
                except Exception as e:
                    self.error(e)
                if win.dirty:
                    self.dirty = True
            if now - last_gc > 5000:                    # tidy the heap now and then, while idle
                import gc
                gc.collect()
                last_gc = now
            minute = time.localtime()[4]
            if minute != last_minute:
                last_minute = minute
                self.dirty = True
            if self.caption[0] and now > self.caption[1]:
                self.caption = ("", 0)
                self.dirty = True
            if self.notice[0] and now > self.notice[1]:
                self.notice = ("", 0)
                self.dirty = True
            if self.dirty:
                try:
                    self.draw()
                except MemoryError:                     # tidy up, ask the kernel for room, draw next time
                    import desktop
                    for w in self.windows:
                        w.shadow = None
                    self.shadow = None
                    desktop.more_memory(32 << 20)
            self.clock.tick(30)
        for win in list(self.windows):
            try:
                win.app.close()
            except Exception:
                pass
        pygame.display.quit()


# ---- pieces of the look ----

_panels = {}


def _panel(w, h, radius):
    """A translucent dark rounded rectangle (cached by size)."""
    key = (w, h, radius)
    p = _panels.get(key)
    if p is None:
        if len(_panels) > 40:
            _panels.clear()
        p = pygame.Surface((w, h), SRCALPHA)
        p.fill((0, 0, 0, 0))
        pygame.draw.rect(p, T.PANEL, (0, 0, w, h), 0, radius)
        _panels[key] = p
    return p


WALLPAPERS = [                     # (top colour, bottom colour, glow colours)
    ((36, 58, 120), (120, 52, 120), ((120, 180, 255), (255, 120, 200), (140, 255, 220))),
    ((14, 60, 70), (20, 120, 110), ((90, 255, 200), (40, 160, 255), (220, 255, 140))),
    ((70, 30, 20), (190, 90, 40), ((255, 190, 90), (255, 110, 80), (255, 230, 150))),
    ((18, 20, 30), (40, 44, 64), ((90, 120, 255), (160, 90, 255), (60, 200, 255))),
    ((40, 90, 160), (150, 200, 240), ((255, 255, 255), (200, 230, 255), (255, 240, 200))),
]


def wallpaper(index=0):
    """A gradient with soft glowing circles and the PyOS logo, or a picture
    from /disk/Imagenes for the indexes after the built-in ones."""
    w, h = T.SCREEN
    s = pygame.Surface((w, h))
    top, bottom, glows = WALLPAPERS[index % len(WALLPAPERS)]
    (r1, g1, b1), (r2, g2, b2) = top, bottom
    for y in range(0, h, 2):
        t = y / h
        s.fill((int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t), int(b1 + (b2 - b1) * t)), (0, y, w, 2))
    glow = pygame.Surface((w, h), SRCALPHA)
    for (cx, cy, rad), col in zip(((760, 200, 260), (220, 560, 300), (520, 420, 180)), glows):
        glow.fill((0, 0, 0, 0))
        for k in range(10, 0, -1):                       # discs, brighter towards the centre
            pygame.draw.circle(glow, col + (int(44 * (1 - k / 10)) + 4,), (cx, cy), rad * k // 10)
        s.blit(glow, (0, 0))
    from pyos import logo
    s.blit(logo.surface(96), (w - 40 - 96, h - T.DOCK_H - 220))
    ui.text(s, "PyOS", w - 40 - ui.width("PyOS", ui.font(32, True)), h - T.DOCK_H - 100, (234, 238, 250),
            ui.font(32, bold=True))
    note = "sobre PyKernel: Python es el sistema"
    ui.text(s, note, w - 40 - ui.width(note, ui.font(13)), h - T.DOCK_H - 58, (214, 218, 240), ui.font(13))
    return s


def _net_label():
    try:
        from kernel import net
        return ("red " + net.ntoa(net.ip)) if net.nic is not None and net.ip else "sin red"
    except Exception:
        return ""


def _sound_label():
    try:
        from kernel import sound
        return "sonido" if sound.card else ""
    except Exception:
        return ""


def run():
    pygame.init()
    WindowManager().run()
