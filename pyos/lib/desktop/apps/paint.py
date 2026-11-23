# Paint: brush, line, rectangle, circle, fill colour; saves BMP files.
import pygame
from desktop import theme as T, ui
from desktop.wm import App

PALETTE = [(0, 0, 0), (255, 255, 255), (200, 40, 40), (240, 140, 30), (240, 220, 40), (60, 170, 70),
           (40, 120, 220), (120, 60, 200), (140, 90, 50), (128, 128, 128)]
TOOLS = ["pincel", "linea", "rect", "circulo", "borrar"]


class Paint(App):
    title = "Dibujo"
    size = (700, 480)

    def __init__(self, win, path=None):
        App.__init__(self, win)
        self.canvas = pygame.Surface((560, 400))
        self.canvas.fill((255, 255, 255))
        self.color = (0, 0, 0)
        self.tool = "pincel"
        self.size = 3
        self.start = None
        self.last = None
        self.path = ui.Field((80, 440, 300, 24), path or "/disk/dibujo.bmp")
        self.form = ui.Form()
        self.form.add(self.path)
        self.form.add(ui.Button((390, 440, 80, 24), "Guardar", self.save))
        self.form.add(ui.Button((476, 440, 80, 24), "Abrir", self.load))
        self.form.add(ui.Button((562, 440, 80, 24), "Limpiar", lambda: self.canvas.fill((255, 255, 255))))
        for i, t in enumerate(TOOLS):
            self.form.add(ui.Button((4, 8 + 30 * i, 66, 26), t, lambda t=t: self.set_tool(t)))
        self.form.add(ui.Button((4, 170, 30, 24), "-", lambda: self.set_size(-1)))
        self.form.add(ui.Button((40, 170, 30, 24), "+", lambda: self.set_size(1)))
        self.msg = ""
        if path:
            self.load()

    def set_tool(self, t):
        self.tool = t

    def set_size(self, d):
        self.size = max(1, min(30, self.size + d))

    def origin(self):
        return (80, 8)

    def to_canvas(self, pos):
        ox, oy = self.origin()
        return pos[0] - ox, pos[1] - oy

    def save(self):
        try:
            pygame.image.save(self.canvas, self.path.text)
            self.msg = "guardado " + self.path.text
        except Exception as e:
            self.msg = "error: %s" % e

    def load(self):
        try:
            img = pygame.image.load(self.path.text)
            self.canvas.fill((255, 255, 255))
            self.canvas.blit(img, (0, 0))
            self.msg = "abierto " + self.path.text
        except Exception as e:
            self.msg = "error: %s" % e

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        ox, oy = self.origin()
        surf.blit(self.canvas, (ox, oy))
        pygame.draw.rect(surf, T.FIELD_BORDER, (ox - 1, oy - 1, 562, 402), 1)
        for i, c in enumerate(PALETTE):
            r = (4 + (i % 2) * 34, 210 + (i // 2) * 30, 30, 26)
            pygame.draw.rect(surf, c, r)
            if c == self.color:
                pygame.draw.rect(surf, T.ACCENT, r, 2)
        for b in self.form.widgets[4:9]:
            b.primary = b.label == self.tool
        self.form.draw(surf)
        ui.text(surf, "tam %d" % self.size, 8, 196, T.MUTED)
        ui.text(surf, self.msg, 80, 418, T.MUTED)
        if self.start and self.last and self.tool in ("linea", "rect", "circulo"):
            self._shape(surf, self.start, self.last, (ox, oy))

    def _shape(self, surf, a, b, off=(0, 0)):
        a = (a[0] + off[0], a[1] + off[1])
        b = (b[0] + off[0], b[1] + off[1])
        if self.tool == "linea":
            pygame.draw.line(surf, self.color, a, b, self.size)
        elif self.tool == "rect":
            r = pygame.Rect(min(a[0], b[0]), min(a[1], b[1]), abs(a[0] - b[0]), abs(a[1] - b[1]))
            pygame.draw.rect(surf, self.color, r, self.size)
        elif self.tool == "circulo":
            rad = int(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5)
            pygame.draw.circle(surf, self.color, a, max(1, rad), self.size)

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for i, c in enumerate(PALETTE):
                if ui.inside((4 + (i % 2) * 34, 210 + (i // 2) * 30, 30, 26), pos):
                    self.color = c
                    return True
            p = self.to_canvas(pos)
            if 0 <= p[0] < 560 and 0 <= p[1] < 400:
                self.start = self.last = p
                if self.tool in ("pincel", "borrar"):
                    self._brush(p, p)
                return True
        if ev.type == pygame.MOUSEMOTION and self.start:
            p = self.to_canvas(pos)
            if self.tool in ("pincel", "borrar"):
                self._brush(self.last, p)
            self.last = p
            return True
        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and self.start:
            p = self.to_canvas(pos)
            if self.tool in ("linea", "rect", "circulo"):
                self._shape(self.canvas, self.start, p)
            self.start = self.last = None
            return True
        return self.form.event(ev, pos)

    def _brush(self, a, b):
        color = (255, 255, 255) if self.tool == "borrar" else self.color
        size = self.size * (3 if self.tool == "borrar" else 1)
        pygame.draw.line(self.canvas, color, a, b, size)
        pygame.draw.circle(self.canvas, color, b, max(1, size // 2))
