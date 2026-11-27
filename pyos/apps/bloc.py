# pyos-app
# name: Bloc de notas
# icon: bloc
# mode: window
#
# A plain text editor like the classic notepad: open and save files, find and
# replace, word wrap, date and time (F5), bigger or smaller text.
import time
import pygame
from desktop import theme as T, ui, clipboard
from desktop.wm import App as Base


class App(Base):
    title = "Bloc de notas"
    size = (680, 460)

    def __init__(self, win, path=None):
        Base.__init__(self, win)
        self.path = path
        self.lines = [""]
        self.row = self.col = 0
        self.top = 0
        self.wrap = True
        self.size_px = 13
        self.modified = False
        self.last_find = ""
        self.menu = ui.MenuBar(win.w, [
            ("Archivo", [("Nuevo", self.new), ("Abrir...", self.ask_open), ("Guardar", self.save),
                         ("Guardar como...", self.ask_save), None, ("Imprimir...", self.print)]),
            ("Editar", [("Copiar todo", lambda: clipboard.set("\n".join(self.lines))), ("Pegar", self.paste), None,
                        ("Buscar...", self.ask_find), ("Buscar siguiente (F3)", self.find_next),
                        ("Reemplazar...", self.ask_replace), None, ("Fecha y hora (F5)", self.insert_date)]),
            ("Formato", [("Ajuste de linea", self.toggle_wrap), ("Texto mas grande", lambda: self.zoom(2)),
                         ("Texto mas pequeno", lambda: self.zoom(-2))]),
        ])
        if path:
            self.open(path)

    # ---- files ----
    def new(self):
        self.path, self.lines, self.row, self.col, self.top, self.modified = None, [""], 0, 0, 0, False
        self.update_title()

    def ask_open(self):
        ui.ask("Abrir", "Ruta del archivo:", self.path or "/disk/Documentos/", self.open)

    def open(self, path):
        try:
            with open(path) as f:
                self.lines = f.read().replace("\r\n", "\n").split("\n")
        except OSError as e:
            ui.toast("no se pudo abrir: %s" % e)
            return
        self.path, self.row, self.col, self.top, self.modified = path, 0, 0, 0, False
        self.update_title()

    def save(self):
        if not self.path:
            return self.ask_save()
        try:
            with open(self.path, "w") as f:
                f.write("\n".join(self.lines))
            self.modified = False
            ui.toast("guardado: " + self.path)
        except OSError as e:
            ui.toast("no se pudo guardar: %s" % e)
        self.update_title()

    def print(self):
        from pyos import printing
        name = self.path.rsplit("/", 1)[-1] if self.path else "Sin titulo"
        printing.print_from_app("\n".join(self.lines), name)

    def ask_save(self):
        ui.ask("Guardar como", "Ruta del archivo:", self.path or "/disk/Documentos/sin titulo.txt",
               lambda p: (setattr(self, "path", p), self.save()))

    def update_title(self):
        name = self.path.rsplit("/", 1)[-1] if self.path else "Sin titulo"
        self.win.set_title(("*" if self.modified else "") + name + " - Bloc de notas")

    # ---- editing ----
    def insert(self, s):
        line = self.lines[self.row]
        parts = s.split("\n")
        rest = line[self.col:]
        self.lines[self.row] = line[:self.col] + parts[0]
        for p in parts[1:]:
            self.row += 1
            self.lines.insert(self.row, p)
        self.col = len(self.lines[self.row])
        self.lines[self.row] += rest
        if not self.modified:
            self.modified = True
            self.update_title()

    def paste(self):
        self.insert(clipboard.get())

    def insert_date(self):
        t = time.localtime()
        self.insert("%02d:%02d %02d/%02d/%04d" % (t[3], t[4], t[2], t[1], t[0]))

    def toggle_wrap(self):
        self.wrap = not self.wrap

    def zoom(self, d):
        self.size_px = 15 if self.size_px + d > 13 else 13

    def ask_find(self):
        ui.ask("Buscar", "Texto a buscar:", self.last_find, lambda s: (setattr(self, "last_find", s), self.find_next()))

    def find_next(self):
        word = self.last_find
        if not word:
            return
        n = len(self.lines)
        for k in range(n + 1):
            r = (self.row + k) % n
            start = self.col + 1 if k == 0 else 0
            j = self.lines[r].lower().find(word.lower(), start)
            if j >= 0:
                self.row, self.col = r, j
                return
        ui.toast("no se encontro “%s”" % word)

    def ask_replace(self):
        def step2(old):
            ui.ask("Reemplazar", "Reemplazar “%s” por:" % old, "", lambda new: self.replace_all(old, new))
        ui.ask("Reemplazar", "Texto a buscar:", self.last_find, step2)

    def replace_all(self, old, new):
        count = sum(line.count(old) for line in self.lines)
        self.lines = [line.replace(old, new) for line in self.lines]
        self.col = min(self.col, len(self.lines[self.row]))
        self.modified = True
        self.update_title()
        ui.toast("%d reemplazos" % count)

    # ---- layout: logical lines -> rows on screen ----
    def font(self):
        return ui.font(self.size_px, mono=True)

    def cw(self):
        return self.font().size("M")[0]

    def lh(self):
        return self.font().get_height() + 2

    def cols(self):
        return max(10, (self.win.w - 20) // self.cw()) if self.wrap else 100000

    def rows_on_screen(self):
        return max(1, (self.win.h - 28 - 26 - 8) // self.lh())

    def visual(self):
        """[(line index, start column)] for every row shown."""
        out, cols = [], self.cols()
        for i, line in enumerate(self.lines):
            for start in range(0, max(1, len(line) + (1 if len(line) % cols == 0 and line else 0)), cols):
                out.append((i, start))
                if not line:
                    break
        return out

    def cursor_row(self, vis):
        cols = self.cols()
        for k, (i, start) in enumerate(vis):
            if i == self.row and start <= self.col < start + cols:
                return k
            if i == self.row and self.col == len(self.lines[i]) and (k + 1 == len(vis) or vis[k + 1][0] != i):
                return k
        return 0

    # ---- drawing ----
    def draw(self, surf):
        surf.fill((255, 255, 255))
        self.menu.rect.w = self.win.w
        self.menu.draw(surf)
        f, lh, cw = self.font(), self.lh(), self.cw()
        vis = self.visual()
        cur = self.cursor_row(vis)
        n = self.rows_on_screen()
        self.top = min(self.top, cur)
        self.top = max(self.top, cur - n + 1)
        y0 = 34
        for k in range(n):
            j = self.top + k
            if j >= len(vis):
                break
            i, start = vis[j]
            ui.text(surf, self.lines[i][start:start + self.cols()][:400], 10, y0 + k * lh, T.TEXT, f)
            if j == cur:
                x = 10 + (self.col - start) * cw
                pygame.draw.line(surf, T.TEXT, (x, y0 + k * lh), (x, y0 + k * lh + lh - 3), 2)
        sb = self.win.h - 24
        pygame.draw.rect(surf, (242, 243, 246), (0, sb, self.win.w, 24))
        words = sum(len(line.split()) for line in self.lines)
        info = "Lin %d, Col %d    %d palabras    %s    UTF-8" % (self.row + 1, self.col + 1, words,
                                                                 "ajuste de linea" if self.wrap else "sin ajuste")
        ui.text(surf, info, 10, sb + 5, T.MUTED)

    def event(self, ev, pos):
        if self.menu.event(ev, pos):
            return True
        if ev.type == pygame.MOUSEBUTTONDOWN and pos and pos[1] > 34:
            if ev.button in (4, 5):
                self.top = max(0, self.top + (-3 if ev.button == 4 else 3))
                return True
            vis = self.visual()
            j = min(len(vis) - 1, self.top + (pos[1] - 34) // self.lh())
            i, start = vis[j]
            self.row = i
            self.col = min(len(self.lines[i]), start + max(0, (pos[0] - 10 + self.cw() // 2) // self.cw()))
            return True
        if ev.type != pygame.KEYDOWN:
            return False
        k, c = ev.key, ui.ctrl(ev)
        line = self.lines[self.row]
        if c and k == pygame.K_s:
            self.save()
        elif c and k == pygame.K_o:
            self.ask_open()
        elif c and k == pygame.K_n:
            self.new()
        elif c and k == pygame.K_f:
            self.ask_find()
        elif c and k == pygame.K_h:
            self.ask_replace()
        elif c and k == pygame.K_v:
            self.paste()
        elif k == pygame.K_F3:
            self.find_next()
        elif k == pygame.K_F5:
            self.insert_date()
        elif k == pygame.K_RETURN:
            self.insert("\n")
        elif k == pygame.K_TAB:
            self.insert("    ")
        elif k == pygame.K_BACKSPACE:
            if self.col:
                self.lines[self.row] = line[:self.col - 1] + line[self.col:]
                self.col -= 1
            elif self.row:
                self.col = len(self.lines[self.row - 1])
                self.lines[self.row - 1] += line
                del self.lines[self.row]
                self.row -= 1
            self.modified = True
        elif k == pygame.K_DELETE:
            if self.col < len(line):
                self.lines[self.row] = line[:self.col] + line[self.col + 1:]
            elif self.row + 1 < len(self.lines):
                self.lines[self.row] += self.lines.pop(self.row + 1)
            self.modified = True
        elif k == pygame.K_LEFT:
            if self.col:
                self.col -= 1
            elif self.row:
                self.row -= 1
                self.col = len(self.lines[self.row])
        elif k == pygame.K_RIGHT:
            if self.col < len(line):
                self.col += 1
            elif self.row + 1 < len(self.lines):
                self.row, self.col = self.row + 1, 0
        elif k == pygame.K_UP:
            self.row = max(0, self.row - 1)
        elif k == pygame.K_DOWN:
            self.row = min(len(self.lines) - 1, self.row + 1)
        elif k == pygame.K_HOME:
            self.col = 0
        elif k == pygame.K_END:
            self.col = len(line)
        elif k == pygame.K_PAGEUP:
            self.row = max(0, self.row - self.rows_on_screen())
        elif k == pygame.K_PAGEDOWN:
            self.row = min(len(self.lines) - 1, self.row + self.rows_on_screen())
        elif ui.is_text_key(ev):
            self.insert(ev.unicode)
        else:
            return False
        self.col = min(self.col, len(self.lines[self.row]))
        return True

    def close(self):
        if self.modified and self.path:
            self.save()
        return True
