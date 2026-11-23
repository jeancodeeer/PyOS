# Clock and calendar: an analog clock, the date, this month, a stopwatch.
import math
import time
import pygame
from desktop import theme as T, ui
from desktop.wm import App

MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]
DAYS = ["lu", "ma", "mi", "ju", "vi", "sa", "do"]


class Clock(App):
    title = "Reloj y calendario"
    size = (520, 300)
    resizable = False

    def __init__(self, win):
        App.__init__(self, win)
        self.last = None
        self.sw_start = None
        self.sw_total = 0
        self.form = ui.Form()
        self.form.add(ui.Button((20, 250, 90, 26), "Iniciar", self.toggle))
        self.form.add(ui.Button((116, 250, 90, 26), "Reiniciar", self.reset))

    def toggle(self):
        if self.sw_start is None:
            self.sw_start = time.ticks_ms()
        else:
            self.sw_total += time.ticks_ms() - self.sw_start
            self.sw_start = None

    def reset(self):
        self.sw_start, self.sw_total = None, 0

    def tick(self, now):
        t = time.localtime()[:6]
        if t != self.last or self.sw_start is not None:
            self.last = t
            return True
        return False

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        y, mo, d, hh, mm, ss = time.localtime()[:6]
        cx, cy, r = 110, 110, 90
        pygame.draw.circle(surf, T.FIELD, (cx, cy), r)
        pygame.draw.circle(surf, T.TEXT, (cx, cy), r, 2)
        for i in range(12):
            a = math.pi * 2 * i / 12
            pygame.draw.line(surf, T.TEXT, (cx + int(math.sin(a) * (r - 10)), cy - int(math.cos(a) * (r - 10))),
                             (cx + int(math.sin(a) * (r - 2)), cy - int(math.cos(a) * (r - 2))), 2)
        for value, length, width, color in ((((hh % 12) + mm / 60) / 12, 50, 4, T.TEXT),
                                            ((mm + ss / 60) / 60, 72, 3, T.TEXT), (ss / 60, 80, 1, T.RED)):
            a = math.pi * 2 * value
            pygame.draw.line(surf, color, (cx, cy), (cx + int(math.sin(a) * length), cy - int(math.cos(a) * length)), width)
        ui.text(surf, "%02d:%02d:%02d" % (hh, mm, ss), 76, 208, T.TEXT)
        ui.text(surf, "%d de %s de %d" % (d, MONTHS[mo - 1], y), 250, 14, T.TEXT)
        first = time.mktime((y, mo, 1, 0, 0, 0, 0, 0))
        wd = time.gmtime(first)[6]
        days = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1]
        for i, name in enumerate(DAYS):
            ui.text(surf, name, 250 + i * 36, 44, T.MUTED)
        for day in range(1, days + 1):
            pos = wd + day - 1
            x, yy = 250 + (pos % 7) * 36, 66 + (pos // 7) * 24
            if day == d:
                pygame.draw.rect(surf, T.ACCENT, (x - 4, yy - 2, 28, 20))
            ui.text(surf, "%2d" % day, x, yy, T.ACCENT_TEXT if day == d else T.TEXT)
        total = self.sw_total + (time.ticks_ms() - self.sw_start if self.sw_start is not None else 0)
        ui.text(surf, "cronometro  %02d:%02d.%d" % (total // 60000, total // 1000 % 60, total // 100 % 10), 250, 254, T.TEXT)
        self.form.widgets[0].label = "Parar" if self.sw_start is not None else "Iniciar"
        self.form.draw(surf)

    def event(self, ev, pos):
        return self.form.event(ev, pos)
