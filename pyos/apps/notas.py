# pyos-app
# name: Notas
# icon: notes
# mode: window
#
# Sticky notes. Each note is a text file in /disk/Notas; changes are saved
# as you type. A small example of a SnakeyOS app in one .py file.
import os
import pygame
from desktop import theme as T, ui
from desktop.wm import App as Base

FOLDER = "/disk/Notas"
COLORS = [(255, 241, 150), (190, 235, 255), (205, 245, 195), (255, 210, 225)]


class App(Base):
    title = "Notas"
    size = (620, 420)

    def __init__(self, win):
        Base.__init__(self, win)
        try:
            os.mkdir(FOLDER)
        except OSError:
            pass
        self.notes = sorted(n for n in os.listdir(FOLDER) if n.endswith(".txt")) or [self.new_name()]
        self.current = 0
        self.text = self.load()
        self.form = ui.Form()
        self.form.add(ui.Button((12, 12, 150, 30), "+ Nueva nota", self.add, primary=True))
        self.form.add(ui.Button((12, 50, 150, 30), "Borrar nota", self.delete))

    def new_name(self):
        n = 1
        while _exists(FOLDER + "/nota%d.txt" % n):
            n += 1
        name = "nota%d.txt" % n
        with open(FOLDER + "/" + name, "w") as f:
            f.write("")
        return name

    def load(self):
        try:
            with open(FOLDER + "/" + self.notes[self.current]) as f:
                return f.read()
        except OSError:
            return ""

    def save(self):
        with open(FOLDER + "/" + self.notes[self.current], "w") as f:
            f.write(self.text)

    def add(self):
        self.save()
        self.notes.append(self.new_name())
        self.current = len(self.notes) - 1
        self.text = ""

    def delete(self):
        try:
            os.remove(FOLDER + "/" + self.notes[self.current])
        except OSError:
            pass
        del self.notes[self.current]
        if not self.notes:
            self.notes = [self.new_name()]
        self.current = 0
        self.text = self.load()

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        self.form.draw(surf)
        for i, name in enumerate(self.notes[:10]):          # the list of notes on the left
            r = pygame.Rect(12, 96 + i * 30, 150, 26)
            pygame.draw.rect(surf, COLORS[i % 4] if i == self.current else (232, 234, 240), r, 0, 6)
            first = self.text if i == self.current else _first_line(FOLDER + "/" + name)
            ui.text(surf, (first.split("\n")[0] or "(vacia)")[:30], r.x + 8, r.y + 5, T.TEXT, max_w=r.w - 14)
        paper = pygame.Rect(176, 12, self.win.w - 188, self.win.h - 24)
        pygame.draw.rect(surf, COLORS[self.current % 4], paper, 0, 10)
        f = ui.font(15)
        y = paper.y + 12
        for line in ui.wrap(self.text + "│", paper.w - 28, f):
            ui.text(surf, line, paper.x + 14, y, (60, 50, 20), f)
            y += f.get_height() + 2
            if y > paper.bottom - 20:
                break

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and pos and pos[0] < 170 and pos[1] >= 96:
            i = (pos[1] - 96) // 30
            if 0 <= i < len(self.notes):
                self.save()
                self.current = i
                self.text = self.load()
                return True
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif ev.key == pygame.K_RETURN:
                self.text += "\n"
            elif ui.is_text_key(ev):
                self.text += ev.unicode
            else:
                return False
            self.save()
            return True
        return self.form.event(ev, pos)

    def close(self):
        self.save()
        return True


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _first_line(path):
    try:
        with open(path) as f:
            return f.readline()
    except OSError:
        return ""
