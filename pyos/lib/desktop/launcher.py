# The launcher: every app in a grid, a search box, and power buttons.
# Opens with the PyKernel button, the Windows key or Ctrl+Space.
import pygame
from pygame.constants import SRCALPHA
from desktop import theme as T, ui, icons

COLS, CELL_W, CELL_H = 6, 112, 100


def apps_icon(name):
    from desktop import apps
    return apps.icon_name(name)


class Launcher:
    def __init__(self, wm):
        from desktop import apps
        self.wm = wm
        apps.scan()                                  # apps installed since last time show up too
        self.all = [(name, apps.label(name)) for name in apps.names()]
        self.query = ""
        self.hover = None
        w = COLS * CELL_W + 40
        rows = (len(self.all) + COLS - 1) // COLS
        h = rows * CELL_H + 130
        self.rect = pygame.Rect((T.SCREEN[0] - w) // 2, (T.SCREEN[1] - h) // 2 - 10, w, h)
        self.bg = None
        self.power = [("Apagar", self.poweroff), ("Reiniciar", self.reboot), ("Salir a la consola", self.leave)]

    def items(self):
        q = self.query.lower()
        return [(n, l) for n, l in self.all if q in l.lower() or q in n]

    def cells(self):
        out = []
        for i, (name, label) in enumerate(self.items()):
            x = self.rect.x + 20 + (i % COLS) * CELL_W
            y = self.rect.y + 70 + (i // COLS) * CELL_H
            out.append((name, label, pygame.Rect(x, y, CELL_W, CELL_H)))
        return out

    def power_rects(self):
        out, x = [], self.rect.right - 20
        f = ui.font(13)
        for label, fn in reversed(self.power):
            w = ui.width(label, f) + 24
            x -= w
            out.append((label, fn, pygame.Rect(x, self.rect.bottom - 44, w, 28)))
            x -= 8
        return out

    def background(self):
        """The dimmed screen and the panel, made once per launcher."""
        if self.bg is None:
            r = self.rect
            self.bg = pygame.Surface((r.w, r.h), SRCALPHA)
            self.bg.fill((0, 0, 0, 0))
            pygame.draw.rect(self.bg, (24, 26, 36, 235), (0, 0, r.w, r.h), 0, 18)
        return self.bg

    def draw(self, scr):
        r = self.rect
        scr.blit(self.background(), r.topleft)
        search = pygame.Rect(r.x + 20, r.y + 20, r.w - 40, 34)
        pygame.draw.rect(scr, (46, 50, 64), search, 0, 10)
        f = ui.font(15)
        ui.text(scr, self.query or "Buscar aplicaciones...", search.x + 14, search.y + 8,
                T.PANEL_TEXT if self.query else (140, 146, 160), f)
        mouse = self.wm.mouse
        for name, label, cell in self.cells():
            if cell.collidepoint(mouse):
                pygame.draw.rect(scr, (60, 66, 86), cell.inflate(-6, -6), 0, 12)
            scr.blit(icons.icon(apps_icon(name), 52, label), (cell.centerx - 26, cell.y + 10))
            ui.text(scr, label, cell.centerx, cell.y + 70, T.PANEL_TEXT, ui.font(13), CELL_W - 8, center=True)
        for label, fn, pr in self.power_rects():
            pygame.draw.rect(scr, (70, 76, 96) if pr.collidepoint(mouse) else (46, 50, 64), pr, 0, 8)
            ui.text(scr, label, pr.centerx, pr.y + 6, T.PANEL_TEXT, ui.font(13), center=True)

    def event(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.wm.launcher = None
            elif ev.key == pygame.K_RETURN:
                found = self.items()
                if found:
                    self.wm.launcher = None
                    self.wm.launch(found[0][0])
            elif ev.key == pygame.K_BACKSPACE:
                self.query = self.query[:-1]
            elif ui.is_text_key(ev):
                self.query += ev.unicode
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if not self.rect.collidepoint(ev.pos):
                self.wm.launcher = None
                return
            for name, label, cell in self.cells():
                if cell.collidepoint(ev.pos):
                    self.wm.launcher = None
                    self.wm.launch(name)
                    return
            for label, fn, pr in self.power_rects():
                if pr.collidepoint(ev.pos):
                    fn()

    def poweroff(self):
        from kernel import acpi
        acpi.poweroff()

    def reboot(self):
        from kernel import acpi
        acpi.reset()

    def leave(self):
        self.wm.launcher = None
        self.wm.running = False
