# pyos-app
# name: Mapa de caracteres
# icon: caracteres
# mode: window
#
# Every character the system font can draw. Click one to add it to the text
# box; "Copiar" puts the text on the clipboard for any other app (Ctrl+V).
import pygame
from desktop import theme as T, ui, clipboard
from desktop.wm import App as Base

CELL = 34
COLS = 16


class App(Base):
    title = "Mapa de caracteres"
    size = (16 * CELL + 200, 470)
    resizable = False

    def __init__(self, win):
        Base.__init__(self, win)
        atlas = ui.font(15)._a()
        self.chars = [chr(c) for c in sorted(atlas.glyphs) if c > 32] if atlas else [chr(c) for c in range(33, 127)]
        self.top = 0
        self.selected = 0
        self.form = ui.Form()
        x = 16 + COLS * CELL + 16
        self.field = self.form.add(ui.Field((x, 300, 164, 32), ""))
        self.form.add(ui.Button((x, 340, 164, 30), "Copiar", self.copy, primary=True))
        self.form.add(ui.Button((x, 376, 164, 30), "Borrar", lambda: self.field.set("")))

    def rows(self):
        return (self.win.h - 32) // CELL

    def copy(self):
        clipboard.set(self.field.text)
        ui.toast("copiado: " + self.field.text)

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        f = ui.font(18)
        for k in range(self.rows() * COLS):
            i = self.top * COLS + k
            if i >= len(self.chars):
                break
            r = pygame.Rect(16 + (k % COLS) * CELL, 16 + (k // COLS) * CELL, CELL - 2, CELL - 2)
            pygame.draw.rect(surf, T.ACCENT if i == self.selected else T.FIELD, r, 0, 5)
            ui.text(surf, self.chars[i], r.centerx, r.y + 6, T.ACCENT_TEXT if i == self.selected else T.TEXT, f,
                    center=True)
        x = 16 + COLS * CELL + 16
        ch = self.chars[self.selected]
        box = pygame.Rect(x, 16, 164, 164)
        pygame.draw.rect(surf, T.FIELD, box, 0, 12)
        ui.text(surf, ch, box.centerx, box.y + 52, T.TEXT, ui.font(44, bold=True), center=True)
        ui.text(surf, "U+%04X" % ord(ch), x, 196, T.TEXT, ui.font(15, bold=True))
        ui.text(surf, "decimal %d" % ord(ch), x, 220, T.MUTED)
        ui.text(surf, "Texto para copiar:", x, 278, T.MUTED)
        self.form.draw(surf)

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and pos and pos[0] < 16 + COLS * CELL:
            if ev.button in (4, 5):
                last = max(0, (len(self.chars) + COLS - 1) // COLS - self.rows())
                self.top = max(0, min(last, self.top + (-1 if ev.button == 4 else 1)))
                return True
            if ev.button == 1 and pos[0] >= 16 and pos[1] >= 16:
                i = (self.top + (pos[1] - 16) // CELL) * COLS + (pos[0] - 16) // CELL
                if i < len(self.chars):
                    self.selected = i
                    self.field.insert(self.chars[i])
                return True
        return self.form.event(ev, pos)
