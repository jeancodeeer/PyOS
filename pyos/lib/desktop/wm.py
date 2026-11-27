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
        self.maximized = False                        # filling the whole work area
        self.saved = None                             # (x, y, w, h) to go back to after a snap or maximize
        self.dirty = True
        self.shadow = None
        self.app = app_class(self, *args)
        self.title = getattr(self.app, "title", app_class.title)

    def frame_rect(self):
        return pygame.Rect(self.x, self.y, self.w, self.h + T.TITLE_H)

    def client_origin(self):
        return self.x, self.y + T.TITLE_H

    def buttons(self):
        """(close, minimize, maximize) on the right of the title bar, as in Windows:
        on screen they read  —  ☐  ✕  from left to right."""
        r = self.x + self.w
        close = pygame.Rect(r - BTN_W, self.y, BTN_W, T.TITLE_H)
        maxi = close.move(-BTN_W, 0)
        mini = maxi.move(-BTN_W, 0)
        return [close, mini, maxi]

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
            self.restore()
        else:
            self.snap(work_area())
            self.maximized = True

    def snap(self, frame):
        """Fill `frame` (a Rect on the screen, title bar included): a half, a
        quarter, the whole screen. The old place is kept for restore()."""
        if self.saved is None:
            self.saved = (self.x, self.y, self.w, self.h)
        self.maximized = False
        self.x, self.y = frame.x, frame.y
        self.resize(frame.w, frame.h - T.TITLE_H)

    def restore(self):
        if self.saved:
            self.x, self.y, w, h = self.saved
            self.saved = None
            self.resize(w, h)
        self.maximized = False

    def snapped(self):
        return self.saved is not None

    def set_title(self, s):
        self.title = s
        if wm:
            wm.dirty = True


BTN_W = 46                       # the width of each title bar button

# Snap layouts (the hub over the maximize button): each zone is (x, y, w, h)
# in fractions of the work area.
LAYOUTS = [
    [(0, 0, .5, 1), (.5, 0, .5, 1)],
    [(0, 0, 2 / 3, 1), (2 / 3, 0, 1 / 3, 1)],
    [(0, 0, 1 / 3, 1), (1 / 3, 0, 1 / 3, 1), (2 / 3, 0, 1 / 3, 1)],
    [(0, 0, .5, .5), (.5, 0, .5, .5), (0, .5, .5, .5), (.5, .5, .5, .5)],
]


def work_area():
    """The screen without the top bar and the dock."""
    sw, sh = T.SCREEN
    return pygame.Rect(0, T.TOP_H, sw, sh - T.TOP_H - T.DOCK_H)


def zone_rect(zone):
    a = work_area()
    x, y, w, h = zone
    return pygame.Rect(a.x + int(a.w * x), a.y + int(a.h * y), int(a.w * w), int(a.h * h))


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
        try:                                   # theme, resolution, mouse, time zone... before drawing
            from pyos import settings
            settings.apply_all()
        except Exception as e:
            print("settings:", repr(e))
        wm = self
        self.screen = T.open_screen()
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
        self.update_checked = False        # the daily look for SnakeyOS updates (GitHub) was done
        self.hub = None                    # the snap layouts panel: (window, panel rect, [(zone rect, frame)])
        self.hover_key = None              # the title bar button under the mouse, and since when
        self.hover_since = 0
        self.snap_preview = None           # where a window dragged to an edge would go (Rect or "max")
        self.desktop_focus = False
        self.shadow, self.shadow_key = None, None
        from pyos import config
        self.wall_index = config.get("wallpaper", 0)
        cached = globals().get("_cached_wallpaper")
        self.wallpaper = cached if cached is not None and self.wall_index == 0 else wallpaper(self.wall_index)
        self.dialog = None                 # a modal Dialog on top of everything
        self.last_input = time.ticks_ms()  # for turning the screen off when nobody uses it
        self.screen_off = False
        self.menu = None                   # an open right-click Menu
        self.calls = []                    # later(fn): run by the desktop's own loop
        from desktop.deskicons import DesktopIcons
        self.icons = DesktopIcons(self)

    # ---- windows ----
    def open(self, app_class, *args, name=None):
        win = Window(app_class, args, name or "about")
        self.launcher = None
        self.zoom_in(win)
        self.windows.append(win)
        self.dirty = True
        return win

    def zoom_in(self, win, frames=6):
        """The window grows out of the middle of where it will be (a short, Mac-like opening)."""
        if _setting("animaciones") is False or getattr(self, "screen", None) is None:
            return
        try:
            self.draw()                               # the desktop as it is, without the new window
            behind = self.screen.copy()
            fr = win.frame_rect()
            for k in range(1, frames + 1):
                t = k / frames
                t = 1 - (1 - t) * (1 - t)             # ease out
                w, h = int(fr.w * (0.82 + 0.18 * t)), int(fr.h * (0.82 + 0.18 * t))
                r = pygame.Rect(0, 0, w, h)
                r.center = fr.center
                self.screen.blit(behind, (0, 0))
                pygame.draw.rect(self.screen, T.WIN_BORDER, r.inflate(2, 2), 0, T.RADIUS + 1)
                pygame.draw.rect(self.screen, T.WIN_BG, r, 0, T.RADIUS)
                pygame.draw.rect(self.screen, T.TITLE_BG, (r.x, r.y, r.w, T.TITLE_H), 0, T.RADIUS)
                pygame.display.update(r.inflate(30, 30))
                time.sleep_ms(12)
        except Exception:
            pass

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
            self.screen = T.open_screen()
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
        self.wall_index = (self.wall_index + 1) % wallpaper_count()
        config.set("wallpaper", self.wall_index)
        self.wallpaper = wallpaper(self.wall_index)
        self.dirty = True

    def toast(self, s):
        if _setting("notificaciones") is False and not s.startswith("error"):
            return                                  # Settings > Notificaciones: off (errors still show)
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
        if _setting("iconos_escritorio"):
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
        self.draw_hub(scr)
        if self.launcher:
            self.launcher.draw(scr)
        if self.menu:
            self.menu.draw(scr)
        if self.dialog:
            self.dialog.draw(scr)
        self.draw_toast(scr)
        self.draw_subtitle(scr)
        self.draw_night_light(scr)
        pygame.display.flip()
        self.dirty = False

    def draw_windows(self, wins):
        """Only some windows changed (a game's frame, a video): if nothing covers them, copy
        just those windows to the screen instead of drawing everything again. False: do a full draw."""
        if self.launcher or self.menu or self.dialog or self.hub or self.drag or self.notice[0] or \
                self.caption[0] or _setting("luz_nocturna"):
            return False
        order = [w for w in self.windows if not w.minimized]
        for win in wins:
            r = win.frame_rect()
            for above in order[order.index(win) + 1:]:
                if above.frame_rect().colliderect(r):
                    return False                       # partly covered: the full draw gets it right
        scr = self.screen
        for win in wins:
            try:
                win.app.draw(win.surf)
            except Exception as e:
                win.surf.fill(T.WIN_BG)
                ui.text(win.surf, "draw failed: %r" % e, 10, 10, T.RED)
            win.dirty = False
            ox, oy = win.client_origin()
            scr.blit(win.surf, (ox, oy))
            pygame.display.update((ox, oy, win.w, win.h))
        return True

    # ---- settings that change the whole screen ----
    def draw_night_light(self, scr):
        """Luz nocturna: a warm, see-through layer over everything (less blue light)."""
        strength = _setting("luz_nocturna") or 0
        if not strength:
            return
        key = (T.SCREEN, strength)
        if getattr(self, "_night", (None,))[0] != key:
            layer = pygame.Surface(T.SCREEN)
            layer.fill((255, 140, 40))
            layer.set_alpha(int(strength) * 90 // 100)
            self._night = (key, layer)
        scr.blit(self._night[1], (0, 0))

    def restyle(self):
        """The theme, the text size or the dock changed: draw everything again."""
        self.wallpaper = wallpaper(self.wall_index)
        self.shadow, self.shadow_key = None, None
        for w in self.windows:
            w.shadow = None
            w.dirty = True
        try:
            _panels.clear()
        except NameError:
            pass
        self.dirty = True

    def set_resolution(self, width, height):
        """Change the screen mode and fit the windows into the new size."""
        old = T.SCREEN
        try:
            self.screen = pygame.display.set_mode((width, height))
            T.SCREEN = (width, height)
        except (ValueError, OSError):
            self.screen = T.open_screen(old)          # the screen stays as it was
            raise
        width, height = T.SCREEN
        for w in self.windows:
            w.x = max(0, min(w.x, width - 120))
            w.y = max(T.TOP_H, min(w.y, height - T.DOCK_H - T.TITLE_H - 40))
        self.restyle()

    def check_idle(self, now):
        minutes = _setting("apagar_pantalla_min") or 0
        if minutes and not self.screen_off and time.ticks_diff(now, self.last_input) > minutes * 60000:
            self.screen_off = True
            self.screen.fill((0, 0, 0))
            pygame.display.flip()

    def wake(self):
        self.screen_off = False
        self.dirty = True
        if _setting("bloquear_al_volver"):
            try:
                from desktop import splash
                if hasattr(splash, "lock_screen"):
                    splash.lock_screen(self)
            except Exception as e:
                self.error(e)

    def draw_frame(self, scr, win, active):
        if active:                                   # one soft shadow, for the window in front
            key = (win.w, win.h)
            if self.shadow_key != key:
                self.shadow_key, self.shadow = key, _shadow(win.w, win.h + T.TITLE_H)
            scr.blit(self.shadow, (win.x - 14, win.y - 14))
        else:                                        # the others: a cheap dark edge
            pygame.draw.rect(scr, (120, 128, 144), win.frame_rect().move(1, 2), 0, T.RADIUS)
        fr = win.frame_rect()
        pygame.draw.rect(scr, T.WIN_BORDER, fr.inflate(2, 2), 0, T.RADIUS + 1)
        pygame.draw.rect(scr, T.TITLE_BG if active else T.TITLE_BG_OFF, fr, 0, T.RADIUS)
        f = ui.font(13, bold=True)
        ty = win.y + (T.TITLE_H - f.get_height()) // 2
        try:                                          # the app's icon, then its title, on the left
            scr.blit(icons.icon(win.name, 18), (win.x + 10, win.y + (T.TITLE_H - 18) // 2))
        except Exception:
            pass
        ui.text(scr, win.title, win.x + 36, ty, T.TITLE_TEXT if active else T.TITLE_TEXT_OFF, f,
                max(20, win.w - 36 - 3 * BTN_W - 8))
        close, mini, maxi = win.buttons()
        ink = T.TITLE_TEXT if active else T.TITLE_TEXT_OFF
        for kind, rect in (("min", mini), ("max", maxi), ("close", close)):
            hot = rect.collidepoint(self.mouse) and self.window_at(self.mouse) is win
            if hot:
                fill = (196, 43, 28) if kind == "close" else T.BUTTON_HI
                if kind == "close" and rect.right >= fr.right - 1:      # the top right corner is rounded
                    pygame.draw.rect(scr, fill, rect, 0, T.RADIUS)
                    pygame.draw.rect(scr, fill, (rect.x, rect.y, rect.w - T.RADIUS, rect.h))
                    pygame.draw.rect(scr, fill, (rect.x, rect.y + T.RADIUS, rect.w, rect.h - T.RADIUS))
                else:
                    pygame.draw.rect(scr, fill, rect)
            color = (255, 255, 255) if hot and kind == "close" else ink
            cx, cy = rect.center
            if kind == "min":
                pygame.draw.line(scr, color, (cx - 5, cy), (cx + 5, cy))
            elif kind == "max":
                if win.maximized or win.snapped():         # "restore": two squares, one behind the other
                    pygame.draw.rect(scr, color, (cx - 3, cy - 6, 9, 9), 1)
                    pygame.draw.rect(scr, T.TITLE_BG if active else T.TITLE_BG_OFF, (cx - 6, cy - 3, 9, 9))
                    pygame.draw.rect(scr, color, (cx - 6, cy - 3, 9, 9), 1)
                else:
                    pygame.draw.rect(scr, color, (cx - 5, cy - 5, 10, 10), 1)
            else:
                pygame.draw.line(scr, color, (cx - 5, cy - 5), (cx + 5, cy + 5))
                pygame.draw.line(scr, color, (cx - 5, cy + 5), (cx + 5, cy - 5))
        if not win.maximized and not win.snapped() and getattr(win.app, "resizable", True):
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
        ui.text(scr, "SnakeyOS", 34, y, T.PANEL_TEXT, fb)
        if top is not None:
            ui.text(scr, top.title, 34 + ui.width("SnakeyOS", fb) + 16, y, (70, 86, 112), f, 300)
        t = time.localtime()
        days = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")
        if _setting("reloj_24h") is False:
            clock = "%d:%02d %s" % ((t[3] % 12) or 12, t[4], "p. m." if t[3] >= 12 else "a. m.")
        else:
            clock = "%02d:%02d" % (t[3], t[4])
        ui.text(scr, "%s %d  %s" % (days[t[6]], t[2], clock), sw // 2, y, T.PANEL_TEXT, fb, center=True)
        x = sw - 12
        for label in (_net_label(), _ram_label(), _sound_label()):
            if label:
                x -= ui.width(label, f)
                ui.text(scr, label, x, y, (52, 68, 96), f)
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
                pygame.draw.circle(scr, T.ACCENT, (r.centerx, r.bottom + 6), 2)
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
        ui.text(scr, s, T.SCREEN[0] // 2, y + 13, T.PANEL_TEXT, f, w - 30, center=True)

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
        if ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION):
            self.last_input = time.ticks_ms()
            if self.screen_off:                    # any key or movement wakes the screen up
                self.wake()
                return
        if hasattr(ev, "pos"):
            near_dock = T.SCREEN[1] - T.DOCK_H - 40
            if ev.type == pygame.MOUSEMOTION and (ev.pos[1] > near_dock or self.mouse[1] > near_dock):
                self.dirty = True                      # the dock reacts to the mouse
            self.mouse = ev.pos
        if self.hub_event(ev):
            return
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
            if mode == "move" and win.snapped():         # pulling a snapped window: back to its own size
                share = dx / float(max(1, win.w))
                win.restore()
                dx = int(win.w * share)
                self.drag = (win, dx, dy, mode)
            if mode == "move":
                self.snap_preview = self.edge_zone(ev.pos)
                win.x = max(-win.w + 80, min(T.SCREEN[0] - 80, ev.pos[0] - dx))
                win.y = max(T.TOP_H, min(T.SCREEN[1] - T.DOCK_H - T.TITLE_H, ev.pos[1] - dy))
            else:
                win.resize(ev.pos[0] - win.x + dx, ev.pos[1] - win.y - T.TITLE_H + dy)
            self.dirty = True
            return
        if ev.type == pygame.MOUSEBUTTONUP and self.drag:
            win, _, _, mode = self.drag
            self.drag = None
            zone = self.snap_preview
            self.snap_preview = None
            if mode == "move" and zone is not None:     # let go at an edge: snap there
                if zone == "max":
                    win.toggle_maximize()
                else:
                    win.snap(zone)
            self.dirty = True
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
            if close.collidepoint(pos):
                self.close(win)
            elif mini.collidepoint(pos):
                win.minimized = True
                self.dirty = True
            elif maxi.collidepoint(pos):
                self.hub = None
                if win.snapped() and not win.maximized:
                    win.restore()
                else:
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
        if (ev.button == 1 and not win.maximized and not win.snapped() and getattr(win.app, "resizable", True) and
                pos[0] > win.x + win.w - 14 and pos[1] > win.y + T.TITLE_H + win.h - 14):
            self.drag = (win, win.x + win.w - pos[0], win.y + T.TITLE_H + win.h - pos[1], "resize")
            return
        self.send(win, ev)

    # ---- updates (SnakeyOS Update: GitHub releases) ----
    def background_update_check(self):
        """Once a day, quietly: is there a newer SnakeyOS on GitHub? Then say so (or install it)."""
        try:
            from pyos import update
            c = update.config()
            if not c.get("auto_check") or update.restart_pending():
                return
            import time as _t
            if _t.time() - (c.get("last_check") or 0) < 24 * 3600:
                return
        except Exception:
            return
        import _thread

        def work():
            try:
                info = update.check()
                if info is None:
                    return
                if update.config().get("auto_install"):
                    m, package = update.download(info)
                    update.install(m, package)
                    self.later(lambda: self.toast("SnakeyOS %s instalado: reinicia para terminar" % m["version"]))
                else:
                    self.later(lambda: self.toast("Hay una actualizacion: SnakeyOS %s (abre Actualizaciones)" % info["version"]))
            except Exception:
                pass                                 # no network, GitHub busy...: next time
        _thread.start_new_thread(work, ())

    # ---- snapping (as in Windows) ----
    def edge_zone(self, pos):
        """Dragging a window to the screen's edge: left/right half, the top: maximize."""
        sw, _ = T.SCREEN
        x, y = pos
        if y <= T.TOP_H + 2:
            return "max"
        if x <= 2:
            return zone_rect(LAYOUTS[0][0])
        if x >= sw - 3:
            return zone_rect(LAYOUTS[0][1])
        return None

    def hub_event(self, ev):
        """The hover over a maximize button opens the snap layouts; a click on a zone snaps."""
        if ev.type == pygame.MOUSEMOTION and not self.drag:
            key = None
            win = self.window_at(ev.pos)
            if win is not None and ev.pos[1] < win.y + T.TITLE_H:
                for kind, r in zip(("close", "min", "max"), win.buttons()):
                    if r.collidepoint(ev.pos):
                        key = (win, kind)
            if key != self.hover_key:
                self.hover_key, self.hover_since = key, time.ticks_ms()
                self.dirty = True
            if self.hub and not (self.hub[1].inflate(10, 10).collidepoint(ev.pos) or
                                 (key and key[1] == "max" and key[0] is self.hub[0])):
                self.hub = None
                self.dirty = True
            elif self.hub:
                self.dirty = True                       # the zone under the mouse lights up
            return False
        if self.hub and ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            win, panel, zones = self.hub
            if panel.collidepoint(ev.pos):
                for r, frame in zones:
                    if r.collidepoint(ev.pos):
                        win.snap(frame)
                        self.focus(win)
                self.hub = None
                self.dirty = True
                return True
            self.hub = None
            self.dirty = True
        return False

    def check_hub(self, now):
        """Open the snap layouts after the mouse rests half a second on a maximize button."""
        key = self.hover_key
        if key and key[1] == "max" and self.hub is None and time.ticks_diff(now, self.hover_since) > 500:
            win = key[0]
            if win in self.windows and not win.minimized:
                self.hub = self.make_hub(win)
                self.dirty = True

    def make_hub(self, win):
        maxi = win.buttons()[2]
        cell_w, cell_h, pad = 86, 54, 10
        panel = pygame.Rect(0, 0, pad + 2 * (cell_w + pad), pad + 2 * (cell_h + pad))
        panel.midtop = (maxi.centerx, maxi.bottom + 4)
        sw, _ = T.SCREEN
        panel.x = max(4, min(panel.x, sw - panel.w - 4))
        zones = []
        for i, layout in enumerate(LAYOUTS):
            cell = pygame.Rect(panel.x + pad + (i % 2) * (cell_w + pad), panel.y + pad + (i // 2) * (cell_h + pad),
                               cell_w, cell_h)
            for z in layout:
                r = pygame.Rect(cell.x + int(cell.w * z[0]) + 1, cell.y + int(cell.h * z[1]) + 1,
                                max(4, int(cell.w * z[2]) - 2), max(4, int(cell.h * z[3]) - 2))
                zones.append((r, zone_rect(z)))
        return (win, panel, zones)

    def draw_hub(self, scr):
        if self.snap_preview is not None:                # where the dragged window will go
            r = work_area() if self.snap_preview == "max" else self.snap_preview
            glass = pygame.Surface(r.size, SRCALPHA)
            glass.fill((0, 0, 0, 0))
            pygame.draw.rect(glass, T.ACCENT + (70,), (0, 0, r.w, r.h), 0, T.RADIUS)
            pygame.draw.rect(glass, T.ACCENT + (200,), (0, 0, r.w, r.h), 2, T.RADIUS)
            scr.blit(glass, r.topleft)
        if not self.hub:
            return
        win, panel, zones = self.hub
        pygame.draw.rect(scr, (0, 0, 0), panel.move(0, 3), 0, 10)
        pygame.draw.rect(scr, T.WIN_BG, panel, 0, 10)
        pygame.draw.rect(scr, T.WIN_BORDER, panel, 1, 10)
        for r, frame in zones:
            hot = r.collidepoint(self.mouse)
            pygame.draw.rect(scr, T.ACCENT if hot else T.BUTTON_HI, r, 0, 4)

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
        self.cpu_load = 0.0                             # share of the time spent working (0..1), for the monitor
        drew_at = t0
        while self.running:
            frame_start = time.ticks_ms()
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
            self.check_idle(now)
            self.check_hub(now)
            if not self.update_checked and time.ticks_diff(now, t0) > 90000:
                self.update_checked = True
                self.background_update_check()
            changed = [w for w in self.windows if w.dirty and not w.minimized]
            if (self.dirty or changed) and not self.screen_off:
                drew_at = now
                try:
                    if self.dirty or not self.draw_windows(changed):
                        self.draw()
                except MemoryError:                     # tidy up, ask the kernel for room, draw next time
                    import desktop
                    for w in self.windows:
                        w.shadow = None
                    self.shadow, self.shadow_key = None, None
                    desktop.more_memory(32 << 20)
            busy = time.ticks_diff(time.ticks_ms(), frame_start) / 33.0
            self.cpu_load = self.cpu_load * 0.9 + min(1.0, busy) * 0.1
            # 60 frames a second while something moves (games, videos, dragging); 30 when still
            self.clock.tick(60 if time.ticks_diff(now, drew_at) < 500 or self.drag else 30)
        for win in list(self.windows):
            try:
                win.app.close()
            except Exception:
                pass
        pygame.display.quit()


# ---- pieces of the look ----

_panels = {}


def _panel(w, h, radius):
    """A frosted, light rounded rectangle with a hairline edge, as on a Mac (cached by size)."""
    key = (w, h, radius)
    p = _panels.get(key)
    if p is None:
        if len(_panels) > 40:
            _panels.clear()
        p = pygame.Surface((w, h), SRCALPHA)
        p.fill((0, 0, 0, 0))
        pygame.draw.rect(p, T.PANEL, (0, 0, w, h), 0, radius)
        if radius:
            pygame.draw.rect(p, (255, 255, 255, 230), (0, 0, w, h), 1, radius)          # light rim
        else:
            pygame.draw.line(p, (30, 79, 140, 40), (0, h - 1), (w, h - 1))            # the top bar's hairline
        _panels[key] = p
    return p


WALLPAPERS = [                     # (top colour, bottom colour, glow colours)
    ((24, 62, 118), (250, 214, 110), ((255, 232, 140), (70, 130, 210), (255, 244, 200))),   # SnakeyOS: Python blue and yellow
    ((236, 240, 246), (255, 240, 196), ((255, 222, 115), (120, 170, 230), (255, 255, 255))),   # light, minimal
    ((36, 58, 120), (120, 52, 120), ((120, 180, 255), (255, 120, 200), (140, 255, 220))),
    ((14, 60, 70), (20, 120, 110), ((90, 255, 200), (40, 160, 255), (220, 255, 140))),
    ((70, 30, 20), (190, 90, 40), ((255, 190, 90), (255, 110, 80), (255, 230, 150))),
    ((18, 20, 30), (40, 44, 64), ((90, 120, 255), (160, 90, 255), (60, 200, 255))),
    ((40, 90, 160), (150, 200, 240), ((255, 255, 255), (200, 230, 255), (255, 240, 200))),
]


def _wallpaper_pictures():
    """Pictures the user can choose as wallpaper: the ones in /disk/Imagenes."""
    import os
    out = []
    try:
        for name in sorted(os.listdir("/disk/Imagenes")):
            if name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                out.append("/disk/Imagenes/" + name)
    except OSError:
        pass
    return out


def wallpaper_count():
    return len(WALLPAPERS) + len(_wallpaper_pictures())


def wallpaper(index=0):
    """A gradient with soft glowing circles and the SnakeyOS logo, or a picture
    from /disk/Imagenes for the indexes after the built-in ones."""
    w, h = T.SCREEN
    pictures = _wallpaper_pictures()
    index %= len(WALLPAPERS) + len(pictures)
    if index >= len(WALLPAPERS):
        try:
            from imaging import load
            with open(pictures[index - len(WALLPAPERS)], "rb") as f:
                img = load(f.read())
            return pygame.transform.scale(img, (w, h))
        except Exception:
            index = 0
    s = pygame.Surface((w, h))
    top, bottom, glows = WALLPAPERS[index % len(WALLPAPERS)]
    (r1, g1, b1), (r2, g2, b2) = top, bottom
    for y in range(0, h, 2):
        t = y / h
        s.fill((int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t), int(b1 + (b2 - b1) * t)), (0, y, w, 2))
    glow = pygame.Surface((w, h), SRCALPHA)
    for (cx, cy, rad), col in zip(((w * 760 // 1024, h * 200 // 768, 260), (w * 220 // 1024, h * 560 // 768, 300),
                                   (w * 520 // 1024, h * 420 // 768, 180)), glows):
        glow.fill((0, 0, 0, 0))
        for k in range(10, 0, -1):                       # discs, brighter towards the centre
            pygame.draw.circle(glow, col + (int(44 * (1 - k / 10)) + 4,), (cx, cy), rad * k // 10)
        s.blit(glow, (0, 0))
    from pyos import logo
    s.blit(logo.surface(96), (w - 40 - 96, h - T.DOCK_H - 220))
    ink = (24, 52, 96) if sum(bottom) > 500 else (234, 238, 250)       # dark letters on a light bottom
    ui.text(s, "SnakeyOS", w - 40 - ui.width("SnakeyOS", ui.font(32, True)), h - T.DOCK_H - 100, ink,
            ui.font(32, bold=True))
    note = "sobre PyKernel: Python es el sistema"
    ui.text(s, note, w - 40 - ui.width(note, ui.font(13)), h - T.DOCK_H - 58, ink, ui.font(13))
    return s


_ram = {"at": 0, "text": ""}


def _ram_label():
    """'RAM 1,2/2,0 GB': the machine's memory in use / total (worked out once a second)."""
    now = time.ticks_ms()
    if not _ram["text"] or time.ticks_diff(now, _ram["at"]) > 1000:
        try:
            from kernel import mm
            st = mm.stats()
            used, total = st["total"] - st["free"], st["total"]
            _ram["text"] = "RAM %.1f/%.1f GB" % (used / 2 ** 30, total / 2 ** 30) if total >= 2 ** 30 else \
                "RAM %d/%d MB" % (used >> 20, total >> 20)
        except Exception:
            import gc
            _ram["text"] = "%d MB libres" % (gc.mem_free() >> 20)
        _ram["at"] = now
    return _ram["text"]


def _net_label():
    try:
        from kernel import net
        return ("red " + net.ntoa(net.ip)) if net.nic is not None and net.ip else "sin red"
    except Exception:
        return ""


def _setting(key):
    try:
        from pyos import settings
        return settings.get(key)
    except Exception:
        return None


def _sound_label():
    try:
        from kernel import sound
        return "sonido" if sound.card else ""
    except Exception:
        return ""


def run():
    pygame.init()
    WindowManager().run()
