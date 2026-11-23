# pyos-app
# name: Hoja de calculo
# icon: sheet
# mode: window
#
# A spreadsheet: click a cell, type, Enter. A cell that starts with '='
# is a Python expression; A1, B2... are the values of other cells, and
# sum(A1:A5) adds a column. Saved as CSV.
import pygame
from desktop import theme as T, ui
from desktop.wm import App as Base

COLS, ROWS = 8, 20
CW, RH, HEAD = 96, 24, 40


def cell_name(c, r):
    return "%s%d" % (chr(65 + c), r + 1)


class App(Base):
    title = "Hoja de calculo"
    size = (820, 560)

    def __init__(self, win, path="/disk/Documentos/hoja.csv"):
        Base.__init__(self, win)
        self.path = path
        self.cells = {}
        self.sel = (0, 0)
        self.editing = None
        self.load()
        self.form = ui.Form()
        self.form.add(ui.Button((self.win.w - 200, 6, 90, 28), "Guardar", self.save, primary=True))
        self.form.add(ui.Button((self.win.w - 104, 6, 90, 28), "Abrir", self.load))
        self.msg = ""

    def load(self):
        self.cells = {}
        try:
            with open(self.path) as f:
                for r, line in enumerate(f):
                    for c, v in enumerate(line.rstrip("\n").split(",")):
                        if v:
                            self.cells[(c, r)] = v.replace("\\x2c", ",")
        except OSError:
            pass

    def save(self):
        import os
        for d in ("/disk/Documentos",):
            try:
                os.mkdir(d)
            except OSError:
                pass
        rows = max([r for _, r in self.cells] + [0]) + 1
        with open(self.path, "w") as f:
            for r in range(rows):
                f.write(",".join(self.cells.get((c, r), "").replace(",", "\\x2c") for c in range(COLS)) + "\n")
        self.msg = "guardado en " + self.path

    def value(self, c, r, depth=0):
        raw = self.cells.get((c, r), "")
        if not raw.startswith("="):
            try:
                return float(raw) if "." in raw else int(raw)
            except ValueError:
                return raw
        if depth > 20:
            return "#ciclo"
        env = {"sum": self._sum, "max": max, "min": min, "abs": abs, "round": round}
        for cc in range(COLS):
            for rr in range(ROWS):
                if cell_name(cc, rr) in raw:
                    env[cell_name(cc, rr)] = self.value(cc, rr, depth + 1) or 0
        expr = raw[1:]
        for cc in range(COLS):                       # A1:A5 -> a list of the values
            col = chr(65 + cc)
            while col in expr and ":" in expr:
                i = expr.find(":")
                left = expr[:i].rstrip()
                j = len(left)
                while j > 0 and (left[j - 1].isdigit() or left[j - 1].isalpha()):
                    j -= 1
                a = left[j:]
                k = i + 1
                while k < len(expr) and (expr[k].isdigit() or expr[k].isalpha()):
                    k += 1
                b = expr[i + 1:k]
                if not (a and b):
                    break
                ca, ra = ord(a[0]) - 65, int(a[1:]) - 1
                cb, rb = ord(b[0]) - 65, int(b[1:]) - 1
                vals = [self.value(x, y, depth + 1) or 0 for x in range(ca, cb + 1) for y in range(ra, rb + 1)]
                expr = expr[:j] + repr(vals) + expr[k:]
            break
        try:
            return eval(expr, env)
        except Exception:
            return "#error"

    @staticmethod
    def _sum(values):
        return sum(v for v in values if isinstance(v, (int, float)))

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        c, r = self.sel
        ui.text(surf, cell_name(c, r), 12, 12, T.ACCENT, ui.font(15, True))
        bar = pygame.Rect(60, 6, self.win.w - 270, 28)
        ui.frame(surf, bar)
        shown = self.editing if self.editing is not None else self.cells.get(self.sel, "")
        ui.text(surf, shown, bar.x + 8, bar.y + 6, T.TEXT, max_w=bar.w - 16)
        self.form.draw(surf)
        f = ui.FONT()
        for cc in range(COLS):
            x = 40 + cc * CW
            pygame.draw.rect(surf, (230, 233, 240), (x, HEAD, CW, RH))
            ui.text(surf, chr(65 + cc), x + CW // 2, HEAD + 4, T.MUTED, f, center=True)
        rows = min(ROWS, (self.win.h - HEAD - RH - 24) // RH)
        for rr in range(rows):
            y = HEAD + RH + rr * RH
            pygame.draw.rect(surf, (230, 233, 240), (0, y, 40, RH))
            ui.text(surf, str(rr + 1), 20, y + 4, T.MUTED, f, center=True)
            for cc in range(COLS):
                x = 40 + cc * CW
                cell = pygame.Rect(x, y, CW, RH)
                pygame.draw.rect(surf, (255, 255, 255), cell)
                pygame.draw.rect(surf, (222, 225, 232), cell, 1)
                v = self.value(cc, rr) if (cc, rr) in self.cells else ""
                s = ("%.6g" % v) if isinstance(v, float) else str(v)
                num = isinstance(v, (int, float))
                w = ui.width(s, f)
                ui.text(surf, s, x + CW - w - 6 if num else x + 6, y + 4, T.TEXT, f, CW - 10)
        cx, cy = 40 + c * CW, HEAD + RH + r * RH
        pygame.draw.rect(surf, T.ACCENT, (cx, cy, CW, RH), 2)
        ui.text(surf, self.msg or "= para formulas: =A1*2   =sum(A1:A5)", 12, self.win.h - 20, T.MUTED)

    def commit(self):
        if self.editing is not None:
            if self.editing:
                self.cells[self.sel] = self.editing
            else:
                self.cells.pop(self.sel, None)
            self.editing = None

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and pos and pos[1] > HEAD + RH and pos[0] > 40:
            self.commit()
            self.sel = (min(COLS - 1, (pos[0] - 40) // CW), min(ROWS - 1, (pos[1] - HEAD - RH) // RH))
            return True
        if ev.type == pygame.KEYDOWN:
            c, r = self.sel
            moves = {pygame.K_UP: (0, -1), pygame.K_DOWN: (0, 1), pygame.K_LEFT: (-1, 0), pygame.K_RIGHT: (1, 0),
                     pygame.K_TAB: (1, 0)}
            if ev.key == pygame.K_RETURN:
                self.commit()
                self.sel = (c, min(ROWS - 1, r + 1))
            elif ev.key in moves and (self.editing is None or ev.key == pygame.K_TAB):
                self.commit()
                dx, dy = moves[ev.key]
                self.sel = (max(0, min(COLS - 1, c + dx)), max(0, min(ROWS - 1, r + dy)))
            elif ev.key == pygame.K_BACKSPACE:
                self.editing = (self.editing if self.editing is not None else self.cells.get(self.sel, ""))[:-1]
            elif ev.key == pygame.K_DELETE:
                self.cells.pop(self.sel, None)
            elif ev.key == pygame.K_ESCAPE:
                self.editing = None
            elif ui.is_text_key(ev):
                self.editing = (self.editing or "") + ev.unicode
            else:
                return False
            return True
        return self.form.event(ev, pos)

    def close(self):
        self.commit()
        return True
