# pyos-app
# name: Calendario
# icon: calendario
# mode: window
#
# A month calendar with events. Click a day, write what is on, press Enter.
# Events are kept in /disk/Documentos/calendario.json.
import json
import time
import pygame
from desktop import theme as T, ui
from desktop.wm import App as Base

PATH = "/disk/Documentos/calendario.json"
MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre",
          "Noviembre", "Diciembre"]
DAYS = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]
CELL_W, CELL_H, X0, Y0 = 62, 56, 16, 92


def days_in(y, m):
    return [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]


def weekday(y, m, d):
    return time.gmtime(time.mktime((y, m, d, 0, 0, 0, 0, 0)))[6]       # 0 = Monday


class App(Base):
    title = "Calendario"
    size = (760, 470)

    def __init__(self, win):
        Base.__init__(self, win)
        t = time.localtime()
        self.today = t[:3]
        self.year, self.month = t[0], t[1]
        self.day = t[2]
        self.events = {}
        try:
            with open(PATH) as f:
                self.events = json.load(f)
        except (OSError, ValueError):
            pass
        self.form = ui.Form()
        self.form.add(ui.Button((16, 14, 36, 32), "←", lambda: self.move(-1)))
        self.form.add(ui.Button((56, 14, 36, 32), "→", lambda: self.move(1)))
        self.form.add(ui.Button((96, 14, 70, 32), "Hoy", self.go_today))
        x = X0 + 7 * CELL_W + 20
        self.field = self.form.add(ui.Field((x, 300, self.win.w - x - 16, 32), "", self.add, placeholder="Nuevo evento..."))
        self.form.add(ui.Button((x, 342, 120, 30), "Agregar", lambda: self.add(self.field.text), primary=True))
        self.form.add(ui.Button((x + 128, 342, 120, 30), "Borrar", self.remove))
        self.list = self.form.add(ui.ListBox((x, 64, self.win.w - x - 16, 222), []))
        self.refresh()

    def key(self):
        return "%04d-%02d-%02d" % (self.year, self.month, self.day)

    def refresh(self):
        self.list.set_items(self.events.get(self.key(), []))

    def save(self):
        import os
        try:
            os.mkdir("/disk/Documentos")
        except OSError:
            pass
        with open(PATH, "w") as f:
            json.dump(self.events, f)

    def add(self, text):
        if text.strip():
            self.events.setdefault(self.key(), []).append(text.strip())
            self.field.set("")
            self.save()
            self.refresh()

    def remove(self):
        items = self.events.get(self.key(), [])
        if 0 <= self.list.selected < len(items):
            del items[self.list.selected]
            if not items:
                self.events.pop(self.key(), None)
            self.save()
            self.refresh()

    def move(self, d):
        self.month += d
        if self.month < 1:
            self.month, self.year = 12, self.year - 1
        elif self.month > 12:
            self.month, self.year = 1, self.year + 1
        self.day = min(self.day, days_in(self.year, self.month))
        self.refresh()

    def go_today(self):
        self.year, self.month, self.day = self.today
        self.refresh()

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        self.form.draw(surf)
        ui.text(surf, "%s %d" % (MONTHS[self.month - 1], self.year), 182, 16, T.TEXT, ui.font(24, bold=True))
        for i, name in enumerate(DAYS):
            ui.text(surf, name, X0 + i * CELL_W + CELL_W // 2, Y0 - 24, T.MUTED, center=True)
        first = weekday(self.year, self.month, 1)
        for d in range(1, days_in(self.year, self.month) + 1):
            k = first + d - 1
            r = pygame.Rect(X0 + (k % 7) * CELL_W + 2, Y0 + (k // 7) * CELL_H + 2, CELL_W - 4, CELL_H - 4)
            is_today = (self.year, self.month, d) == self.today
            chosen = d == self.day
            fill = T.ACCENT if chosen else ((230, 238, 255) if is_today else T.FIELD)
            pygame.draw.rect(surf, fill, r, 0, 8)
            ui.text(surf, str(d), r.x + 8, r.y + 6, T.ACCENT_TEXT if chosen else T.TEXT, ui.font(15, bold=is_today))
            n = len(self.events.get("%04d-%02d-%02d" % (self.year, self.month, d), []))
            for j in range(min(n, 4)):                      # one dot per event
                pygame.draw.circle(surf, (255, 255, 255) if chosen else T.ACCENT, (r.x + 10 + j * 9, r.bottom - 10), 3)
        x = X0 + 7 * CELL_W + 20
        ui.text(surf, "%d de %s" % (self.day, MONTHS[self.month - 1].lower()), x, 22, T.TEXT, ui.font(18, bold=True))

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and pos and X0 <= pos[0] < X0 + 7 * CELL_W and pos[1] >= Y0:
            k = ((pos[1] - Y0) // CELL_H) * 7 + (pos[0] - X0) // CELL_W
            d = k - weekday(self.year, self.month, 1) + 1
            if 1 <= d <= days_in(self.year, self.month):
                self.day = d
                self.refresh()
                return True
        return self.form.event(ev, pos)
