# Editor: a text editor in a window. Ctrl+S saves, Ctrl+O opens the path in
# the bar, Ctrl+F finds, F5 runs a .py file in a new process.
import pygame
from desktop import theme as T, ui, clipboard
from desktop.wm import App


def CW():
    return ui.MONO().size("M")[0]


def LH():
    return ui.MONO().get_height() + 1

KEYWORDS = set("and as assert async await break class continue def del elif else except finally for from global "
               "if import in is lambda nonlocal not or pass raise return try while with yield True False None".split())


class Editor(App):
    title = "Editor"
    size = (700, 460)

    def __init__(self, win, path=None):
        App.__init__(self, win)
        self.path = path
        self.lines = [""]
        self.row = self.col = 0
        self.top = 0
        self.left = 0
        self.modified = False
        self.status = "Ctrl+S guardar  Ctrl+O abrir  Ctrl+F buscar  F5 ejecutar"
        self.bar = ui.Field((8, 4, 400, 26), path or "/disk/nuevo.txt", self.open_path)
        self.find = ""
        if path:
            self.load(path)

    def load(self, path):
        try:
            with open(path) as f:
                self.lines = f.read().replace("\r\n", "\n").split("\n")
            self.path = path
            self.bar.set(path)
            self.row = self.col = self.top = 0
            self.modified = False
            self.status = "abierto %s (%d lineas)" % (path, len(self.lines))
        except OSError as e:
            self.status = "no se pudo abrir: %s" % e
        self.win.set_title("Editor - " + (self.path or "sin nombre"))

    def open_path(self, path):
        self.load(path)

    def save(self):
        path = self.bar.text.strip() or self.path
        try:
            with open(path, "w") as f:
                f.write("\n".join(self.lines))
            self.path = path
            self.modified = False
            self.status = "guardado %s" % path
            self.win.set_title("Editor - " + path)
        except OSError as e:
            self.status = "no se pudo guardar: %s" % e

    def rows(self):
        return max(1, (self.win.h - 64) // LH())

    def cols(self):
        return max(1, (self.win.w - 56) // CW())

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        self.bar.rect.w = self.win.w - 16
        self.bar.draw(surf)
        y0 = 34
        pygame.draw.rect(surf, T.FIELD, (0, y0, self.win.w, self.rows() * LH() + 4))
        python = (self.path or "").endswith(".py")
        if self.row < self.top:
            self.top = self.row
        if self.row >= self.top + self.rows():
            self.top = self.row - self.rows() + 1
        if self.col < self.left:
            self.left = self.col
        if self.col >= self.left + self.cols():
            self.left = self.col - self.cols() + 1
        for i in range(self.rows()):
            n = self.top + i
            if n >= len(self.lines):
                break
            y = y0 + 2 + i * LH()
            ui.text(surf, "%4d" % (n + 1), 2, y, T.MUTED, ui.MONO())
            line = self.lines[n][self.left:self.left + self.cols()]
            if python:
                self._draw_python(surf, line, 44, y)
            else:
                ui.text(surf, line, 44, y, T.TEXT, ui.MONO())
        cy = y0 + 2 + (self.row - self.top) * LH()
        cx = 44 + (self.col - self.left) * CW()
        pygame.draw.line(surf, T.ACCENT, (cx, cy), (cx, cy + LH() - 2), 2)
        ui.text(surf, ("* " if self.modified else "") + self.status + "   L%d C%d" % (self.row + 1, self.col + 1),
                8, self.win.h - 20, T.MUTED, max_w=self.win.w - 16)

    def _draw_python(self, surf, line, x, y):
        """Colour one line of Python: keywords, numbers, strings, comments."""
        i, n = 0, len(line)
        while i < n:
            ch = line[i]
            if ch == "#":
                ui.text(surf, line[i:], x + i * CW(), y, (110, 130, 110), ui.MONO())
                return
            if ch in "'\"":
                j = i + 1
                while j < n and line[j] != ch:
                    j += 2 if line[j] == "\\" else 1
                j = min(n, j + 1)
                ui.text(surf, line[i:j], x + i * CW(), y, (170, 90, 30), ui.MONO())
                i = j
                continue
            if ch.isalpha() or ch == "_" or ch.isdigit():
                j = i
                while j < n and (line[j].isalpha() or line[j].isdigit() or line[j] == "_"):
                    j += 1
                word = line[i:j]
                color = (150, 40, 160) if word in KEYWORDS else ((20, 120, 160) if word[0].isdigit() else T.TEXT)
                ui.text(surf, word, x + i * CW(), y, color, ui.MONO())
                i = j
                continue
            j = i
            while j < n and not (line[j].isalpha() or line[j].isdigit() or line[j] in "_#'\""):
                j += 1
            ui.text(surf, line[i:j], x + i * CW(), y, (80, 84, 92), ui.MONO())
            i = j

    def _insert(self, s):
        line = self.lines[self.row]
        parts = s.split("\n")
        if len(parts) == 1:
            self.lines[self.row] = line[:self.col] + s + line[self.col:]
            self.col += len(s)
        else:
            rest = line[self.col:]
            self.lines[self.row] = line[:self.col] + parts[0]
            for p in parts[1:]:
                self.row += 1
                self.lines.insert(self.row, p)
            self.col = len(self.lines[self.row])
            self.lines[self.row] += rest
        self.modified = True

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if self.bar.event(ev, pos):
                return True
            if ev.button in (4, 5):
                self.top = max(0, min(len(self.lines) - 1, self.top + (-3 if ev.button == 4 else 3)))
                self.row = max(self.top, min(self.row, self.top + self.rows() - 1, len(self.lines) - 1))
                return True
            if ev.button == 1 and pos[1] > 34:
                self.row = min(len(self.lines) - 1, self.top + (pos[1] - 36) // LH())
                self.col = min(len(self.lines[self.row]), self.left + max(0, (pos[0] - 44 + CW() // 2) // CW()))
                return True
            return False
        if ev.type != pygame.KEYDOWN:
            return False
        if self.bar.focus:
            return self.bar.event(ev, pos)
        k, c = ev.key, ui.ctrl(ev)
        line = self.lines[self.row]
        if c and k == pygame.K_s:
            self.save()
        elif c and k == pygame.K_o:
            self.load(self.bar.text.strip())
        elif c and k == pygame.K_f:
            self._find_next()
        elif c and k == pygame.K_c:
            clipboard.set(line)
            self.status = "linea copiada"
        elif c and k == pygame.K_x:
            clipboard.set(line)
            if len(self.lines) > 1:
                del self.lines[self.row]
                self.row = min(self.row, len(self.lines) - 1)
            else:
                self.lines[0] = ""
            self.col = 0
            self.modified = True
        elif c and k == pygame.K_v:
            self._insert(clipboard.get())
        elif k == pygame.K_F5:
            self.run()
        elif k == pygame.K_RETURN:
            indent = len(line) - len(line.lstrip(" "))
            if line[:self.col].rstrip().endswith(":"):
                indent += 4
            self._insert("\n" + " " * indent)
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
        elif k == pygame.K_TAB:
            self._insert("    ")
        elif k == pygame.K_UP:
            self.row = max(0, self.row - 1)
        elif k == pygame.K_DOWN:
            self.row = min(len(self.lines) - 1, self.row + 1)
        elif k == pygame.K_PAGEUP:
            self.row = max(0, self.row - self.rows())
        elif k == pygame.K_PAGEDOWN:
            self.row = min(len(self.lines) - 1, self.row + self.rows())
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
                self.row += 1
                self.col = 0
        elif k == pygame.K_HOME:
            self.col = 0
        elif k == pygame.K_END:
            self.col = len(line)
        elif ev.unicode and ord(ev.unicode[0]) >= 32 and not c:
            self._insert(ev.unicode)
        else:
            return False
        self.col = min(self.col, len(self.lines[self.row]))
        return True

    def _find_next(self):
        word = self.bar.text if not self.bar.text.startswith("/") else self.find
        if not word:
            self.status = "escribe el texto a buscar en la barra (sin / al inicio) y Ctrl+F"
            return
        self.find = word
        n = len(self.lines)
        for i in range(1, n + 1):
            r = (self.row + i) % n
            j = self.lines[r].find(word)
            if j >= 0:
                self.row, self.col = r, j
                self.status = "encontrado en la linea %d" % (r + 1)
                return
        self.status = "no encontrado: " + word

    def run(self):
        if self.modified:
            self.save()
        if not self.path or not self.path.endswith(".py"):
            self.status = "solo se ejecutan archivos .py"
            return
        from kernel import proc
        pid = proc.spawn(self.path, [self.path])
        self.status = "ejecutando %s como proceso %d (la salida va a la consola de texto)" % (self.path, pid)

    def close(self):
        return True
