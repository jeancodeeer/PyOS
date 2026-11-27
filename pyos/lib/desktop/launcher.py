# The launcher: every app in a grid, a search box, and power buttons.
# Opens with the PyKernel button, the Windows key or Ctrl+Space.
import pygame
from pygame.constants import SRCALPHA
from desktop import theme as T, ui, icons

CATEGORIES = (
    ("Sistema", ("files", "terminal", "settings", "clock", "sysmon", "disks", "store", "updates", "about")),
    ("Creatividad", ("editor", "images", "paint", "music", "videos", "jeancode")),
    ("Utilidades", ("calc", "browser", "pywin", "bloc", "escritor", "hoja", "presentaciones", "calendario",
                    "notas", "tareas", "recortes", "caracteres", "lupa", "teclado")),
    ("Juegos", ("snake", "blocks", "mines", "solitario", "espacio", "pelota", "cubo")),
)


def apps_icon(name):
    if name.startswith("win:"):
        return "exe"
    from desktop import apps
    return apps.icon_name(name)


class Launcher:
    """Every app in glass panels by kind (Sistema, Creatividad, Utilidades, Juegos), a search box
    on top and the power buttons at the bottom. Typing filters into one flat list."""

    def __init__(self, wm):
        from desktop import apps
        self.wm = wm
        apps.scan()                                  # apps installed since last time show up too
        self.all = [(name, apps.label(name)) for name in apps.names()]
        self.query = ""
        sw, sh = T.SCREEN
        self.rect = pygame.Rect(40, T.TOP_H + 16, sw - 80, sh - T.TOP_H - 32)
        self._layout = None
        # the biggest icons with which every section fits on the screen
        for icon, cell in ((64, (112, 104)), (56, (100, 92)), (48, (92, 80)), (40, (84, 70)), (32, (76, 58))):
            self.icon, self.cell = icon, cell
            self._layout = None
            panels, _ = self.layout()
            if not panels or panels[-1][1].bottom <= self.rect.bottom - 40:
                break
        self.power = [("Bloquear", self.lock), ("Cerrar sesion", self.log_out), ("Consola", self.leave),
                      ("Reiniciar", self.reboot), ("Apagar", self.poweroff)]

    def items(self):
        q = self.query.lower()
        out = [(n, l) for n, l in self.all if q in l.lower() or q in n]
        out += [("win:%d" % i, s["name"]) for i, s in enumerate(self.windows_apps()) if q in s["name"].lower()]
        return out

    def sections(self):
        """[(title, [(name, label)])]: the kinds, with the apps that exist (others go to Utilidades)."""
        if self.query:
            return [("Resultados", self.items())]
        labels = dict(self.all)
        placed = set()
        out = []
        for title, names in CATEGORIES:
            row = [(n, labels[n]) for n in names if n in labels]
            placed.update(n for n, _ in row)
            out.append([title, row])
        extra = [(n, l) for n, l in self.all if n not in placed]
        out[2][1].extend(extra)
        out.append(["Windows", [("win:%d" % i, s["name"]) for i, s in enumerate(self.windows_apps())]])
        return [(t, r) for t, r in out if r]

    def windows_apps(self):
        """Programs installed with PyWin (their Start menu shortcuts)."""
        if not hasattr(self, "_win_apps"):
            try:
                from pywin import install
                self._win_apps = install.shortcuts()
            except Exception:
                self._win_apps = []
        return self._win_apps

    def open(self, name):
        self.wm.launcher = None
        if name.startswith("win:"):
            try:
                from pywin import install
                install.launch(self.windows_apps()[int(name[4:])])
            except Exception as e:
                self.wm.error(e)
            return
        self.wm.launch(name)

    def layout(self):
        """(panels, cells): panels = [(title, rect)], cells = [(name, label, rect)]."""
        key = (self.query,)
        if self._layout and self._layout[0] == key:
            return self._layout[1]
        r = self.rect
        cw, ch = self.cell
        cols = max(1, (r.w - 40) // cw)
        y = r.y + 64
        panels, cells = [], []
        for title, items in self.sections():
            rows = (len(items) + cols - 1) // cols
            h = 40 + rows * ch + 8
            panels.append((title, pygame.Rect(r.x, y, r.w, h)))
            for k, (name, label) in enumerate(items):
                cells.append((name, label, pygame.Rect(r.x + 20 + (k % cols) * cw, y + 36 + (k // cols) * ch, cw, ch)))
            y += h + 14
        self._layout = (key, (panels, cells))
        return panels, cells

    def cells(self):
        return self.layout()[1]

    def power_rects(self):
        out, x = [], self.rect.right
        f = ui.font(13)
        for label, fn in reversed(self.power):
            w = ui.width(label, f) + 24
            x -= w
            out.append((label, fn, pygame.Rect(x, self.rect.bottom - 30, w, 28)))
            x -= 8
        return out

    def draw(self, scr):
        from desktop import wm as W
        r = self.rect
        search = pygame.Rect(r.centerx - 220, r.y, 440, 38)
        scr.blit(W._glass(search.w, search.h, 19, 170), search.topleft)
        f = ui.font(15)
        ui.text(scr, self.query or "Buscar aplicaciones...", search.x + 18, search.y + 10,
                T.PANEL_TEXT if self.query else (90, 100, 120), f)
        mouse = self.wm.mouse
        white = (255, 255, 255)
        panels, cells = self.layout()
        for title, pr in panels:
            if pr.bottom > r.bottom - 36:
                pr = pygame.Rect(pr.x, pr.y, pr.w, max(40, r.bottom - 36 - pr.y))
            scr.blit(W._glass(pr.w, pr.h, 24, 70), pr.topleft)
            ui.text(scr, title, pr.x + 20, pr.y + 10, white, ui.font(18))
        lf = ui.font(13)
        for name, label, cell in cells:
            if cell.bottom > r.bottom - 36:
                continue
            if cell.collidepoint(mouse):
                scr.blit(W._glass(cell.w - 8, cell.h - 4, 16, 90), (cell.x + 4, cell.y + 2))
            scr.blit(icons.icon(apps_icon(name), self.icon, label), (cell.centerx - self.icon // 2, cell.y + 6))
            ui.text(scr, label, cell.centerx, cell.y + self.icon + 12, white, lf, cell.w - 6, center=True)
        for label, fn, pr in self.power_rects():
            scr.blit(W._glass(pr.w, pr.h, 10, 200 if pr.collidepoint(mouse) else 150), pr.topleft)
            ui.text(scr, label, pr.centerx, pr.y + 6, T.PANEL_TEXT, ui.font(13), center=True)

    def event(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.wm.launcher = None
            elif ev.key == pygame.K_RETURN:
                found = self.items()
                if found:
                    self.open(found[0][0])
            elif ev.key == pygame.K_BACKSPACE:
                self.query = self.query[:-1]
                self._layout = None
            elif ui.is_text_key(ev):
                self.query += ev.unicode
                self._layout = None
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            panels, _ = self.layout()
            on_panel = any(pr.collidepoint(ev.pos) for _, pr in panels)
            on_power = any(pr.collidepoint(ev.pos) for _, _, pr in self.power_rects())
            if not on_panel and not on_power and ev.pos[1] > self.rect.y + 40:
                self.wm.launcher = None                  # a click on the wallpaper closes it
                return
            for name, label, cell in self.cells():
                if cell.collidepoint(ev.pos):
                    self.open(name)
                    return
            for label, fn, pr in self.power_rects():
                if pr.collidepoint(ev.pos):
                    fn()

    def lock(self):
        from desktop import splash
        self.wm.launcher = None
        splash.lock_screen(self.wm)

    def log_out(self):
        from desktop import splash
        self.wm.launcher = None
        self.wm.later(lambda: splash.log_out(self.wm))   # after this click is handled

    def poweroff(self):
        from kernel import acpi
        acpi.poweroff()

    def reboot(self):
        from kernel import acpi
        acpi.reset()

    def leave(self):
        self.wm.launcher = None
        self.wm.running = False
