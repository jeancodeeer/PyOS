# pyos-app
# name: Tareas
# icon: tareas
# mode: window
#
# A to-do list, saved in /disk/Documentos/tareas.txt ("[x] " marks done ones).
import pygame
from desktop import theme as T, ui
from desktop.wm import App as Base

PATH = "/disk/Documentos/tareas.txt"


class App(Base):
    title = "Tareas"
    size = (460, 440)

    def __init__(self, win):
        Base.__init__(self, win)
        self.items = []
        try:
            with open(PATH) as f:
                for line in f:
                    line = line.rstrip("\n")
                    if line:
                        self.items.append([line.startswith("[x] "), line[4:]])
        except OSError:
            pass
        self.form = ui.Form()
        self.field = self.form.add(ui.Field((14, 14, 320, 30), "", self.add, placeholder="Nueva tarea..."))
        self.form.add(ui.Button((342, 14, 100, 30), "Agregar", lambda: self.add(self.field.text), primary=True))
        self.form.add(ui.Button((14, 396, 200, 28), "Quitar las hechas", self.clear_done))

    def save(self):
        import os
        try:
            os.mkdir("/disk/Documentos")
        except OSError:
            pass
        with open(PATH, "w") as f:
            for done, text in self.items:
                f.write(("[x] " if done else "[ ] ") + text + "\n")

    def add(self, text):
        if text.strip():
            self.items.append([False, text.strip()])
            self.field.set("")
            self.save()

    def clear_done(self):
        self.items = [i for i in self.items if not i[0]]
        self.save()

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        self.form.draw(surf)
        for i, (done, text) in enumerate(self.items[:11]):
            y = 60 + i * 30
            box = pygame.Rect(18, y + 4, 18, 18)
            pygame.draw.rect(surf, T.GREEN if done else T.FIELD, box, 0, 4)
            pygame.draw.rect(surf, T.FIELD_BORDER, box, 1, 4)
            if done:
                pygame.draw.lines(surf, (255, 255, 255), False, [(22, y + 13), (26, y + 18), (33, y + 8)], 2)
            ui.text(surf, text, 46, y + 5, T.MUTED if done else T.TEXT, max_w=self.win.w - 60)
        left = len([1 for d, _ in self.items if not d])
        ui.text(surf, "%d pendientes" % left, self.win.w - 120, 402, T.MUTED)

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and pos and 60 <= pos[1] < 60 + 30 * 11 and pos[0] < 40:
            i = (pos[1] - 60) // 30
            if i < len(self.items):
                self.items[i][0] = not self.items[i][0]
                self.save()
                return True
        return self.form.event(ev, pos)
