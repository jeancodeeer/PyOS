# Small modal windows: ask for a name, confirm something, show a message.
# Opened with wm.wm.ask(...), wm.wm.confirm(...); drawn above everything.
import pygame
from pygame.constants import SRCALPHA
from desktop import theme as T, ui


class Dialog:
    def __init__(self, wm, title, message, text=None, buttons=(("Aceptar", True),), on_done=None):
        self.wm, self.title, self.message, self.on_done = wm, title, message, on_done
        self.rect = pygame.Rect((T.SCREEN[0] - 420) // 2, (T.SCREEN[1] - 180) // 2 - 40, 420, 180 if text is not None else 150)
        self.form = ui.Form()
        self.field = None
        if text is not None:
            self.field = self.form.add(ui.Field((20, 70, 380, 32), text, lambda s: self.done(True)))
            self.field.focus = True
            dot = text.rfind(".")
            self.field.cursor = dot if dot > 0 else len(text)          # cursor before the extension
        x = self.rect.w - 20
        for label, value in reversed(buttons):
            w = max(96, ui.width(label) + 30)
            x -= w
            self.form.add(ui.Button((x, self.rect.h - 48, w, 32), label, lambda v=value: self.done(v), primary=value is True))
            x -= 10

    def done(self, value):
        self.wm.dialog = None
        self.wm.dirty = True
        if self.on_done:
            try:
                if self.field is not None:
                    if value is True:
                        self.on_done(self.field.text)
                else:
                    self.on_done(value)
            except Exception as e:
                self.wm.error(e)

    def draw(self, scr):
        from desktop.wm import _shadow
        r = self.rect
        scr.blit(_shadow(r.w, r.h), (r.x - 14, r.y - 14))
        panel = pygame.Surface(r.size, SRCALPHA)           # transparent corners, rounded panel
        panel.fill((0, 0, 0, 0))
        pygame.draw.rect(panel, T.WIN_BG + (255,), (0, 0, r.w, r.h), 0, 14)
        ui.text(panel, self.title, 20, 18, T.TEXT, ui.font(15, bold=True), r.w - 40)
        ui.text(panel, self.message, 20, 44, T.MUTED, ui.font(13), r.w - 40)
        self.form.draw(panel)
        scr.blit(panel, r.topleft)

    def event(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.done(False)
            return
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_RETURN and self.field is None:
            self.done(True)
            return
        pos = (ev.pos[0] - self.rect.x, ev.pos[1] - self.rect.y) if hasattr(ev, "pos") else None
        self.form.event(ev, pos)


class Menu:
    """A right-click menu: items are (label, fn) or None for a separator."""

    def __init__(self, wm, pos, items):
        self.wm, self.items = wm, items
        w = max(ui.width(i[0]) for i in items if i) + 40
        h = sum(26 if i else 9 for i in items) + 10
        x = min(pos[0], T.SCREEN[0] - w - 4)
        y = min(pos[1], T.SCREEN[1] - h - 4)
        self.rect = pygame.Rect(x, y, w, h)

    def rows(self):
        y = self.rect.y + 5
        for item in self.items:
            h = 26 if item else 9
            yield item, pygame.Rect(self.rect.x + 4, y, self.rect.w - 8, h)
            y += h

    def draw(self, scr):
        panel = pygame.Surface(self.rect.size, SRCALPHA)
        panel.fill((0, 0, 0, 0))
        pygame.draw.rect(panel, (250, 250, 252, 248), (0, 0, self.rect.w, self.rect.h), 0, 10)
        scr.blit(panel, self.rect.topleft)
        pygame.draw.rect(scr, (200, 204, 212), self.rect, 1, 10)
        for item, r in self.rows():
            if item is None:
                pygame.draw.line(scr, (226, 228, 234), (r.x + 8, r.centery), (r.right - 8, r.centery))
                continue
            if r.collidepoint(self.wm.mouse):
                pygame.draw.rect(scr, T.ACCENT, r, 0, 6)
            ui.text(scr, item[0], r.x + 12, r.y + 5, T.ACCENT_TEXT if r.collidepoint(self.wm.mouse) else T.TEXT)

    def event(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.wm.menu = None
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            self.wm.menu = None
            if self.rect.collidepoint(ev.pos):
                for item, r in self.rows():
                    if item and r.collidepoint(ev.pos):
                        try:
                            item[1]()
                        except Exception as e:
                            self.wm.error(e)
        self.wm.dirty = True
