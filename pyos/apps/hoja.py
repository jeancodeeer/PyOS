# pyos-app
# name: Hoja de calculo
# icon: sheet
# mode: window
#
# A spreadsheet: click a cell, type, Enter. A cell that starts with '='
# is a Python expression; A1, B2... are the values of other cells, and
# sum(A1:A5) adds a column. Saved like Excel does: .xlsx (Excel, LibreOffice
# and Google Sheets open it, formulas included), and also .csv or .pdf.
import pygame
from desktop import theme as T, ui
from desktop.wm import App as Base

COLS, ROWS = 8, 20
CW, RH, HEAD = 96, 24, 40


def _agg(fn):
    """max/min that work on a list (A1:A5) or on separate numbers, like Excel's."""
    def f(*args):
        vals = args[0] if len(args) == 1 and isinstance(args[0], list) else list(args)
        nums = [v for v in vals if isinstance(v, (int, float))]
        return fn(nums) if nums else 0
    return f


def cell_name(c, r):
    return "%s%d" % (chr(65 + c), r + 1)


class App(Base):
    title = "Hoja de calculo"
    size = (820, 560)

    def __init__(self, win, path="/disk/Documentos/hoja.xlsx"):
        Base.__init__(self, win)
        self.path = path
        self.cells = {}
        self.sel = (0, 0)
        self.editing = None
        self.load()
        self.form = ui.Form()
        self.form.add(ui.Button((self.win.w - 300, 6, 90, 28), "Guardar", self.save, primary=True))
        self.form.add(ui.Button((self.win.w - 204, 6, 110, 28), "Guardar como", self.ask_save))
        self.form.add(ui.Button((self.win.w - 88, 6, 76, 28), "Abrir", self.ask_open))
        self.msg = ""

    # ---- files: .xlsx like Excel, and .csv, .pdf ----
    def load(self, path=None):
        from office import excel, files
        path = path or self.path
        try:
            data = files.read(path)
        except OSError:
            return                                        # a new sheet
        try:
            if files.ext(path) == "xlsx":
                self.cells = excel.from_xlsx(data)
            else:
                self.cells = excel.from_csv(data.decode())
        except (ValueError, UnicodeError) as e:
            self.msg = "no se pudo abrir: %s" % e
            return
        self.path = path
        hidden = [k for k in self.cells if k[0] >= COLS or k[1] >= ROWS]
        self.msg = ("abierto: %s" % path) + (" (%d celdas fuera de la vista)" % len(hidden) if hidden else "")

    def write(self, path):
        from office import excel, files
        kind = files.ext(path)
        if kind == "xlsx":
            data = excel.to_xlsx(self.cells, self.value, "Hoja1")
        elif kind == "pdf":
            data = self.pdf(path.rsplit("/", 1)[-1])
        else:
            data = excel.to_csv(self.cells, self.value)
        files.write(path, data)

    def save(self):
        self.commit()
        try:
            self.write(self.path)
            self.msg = "guardado en " + self.path
        except OSError as e:
            self.msg = "no se pudo guardar: %s" % e

    def ask_save(self):
        from office import files

        def chosen(p):
            if files.ext(p) not in ("xlsx", "csv", "pdf"):
                p = files.with_ext(p, "xlsx")
            if files.ext(p) == "pdf":                      # a PDF is an export: keep editing the sheet
                self.write(p)
                self.msg = "exportado: " + p
                return
            self.path = p
            self.save()
        ui.ask("Guardar como", "Ruta (.xlsx, .csv o .pdf):", self.path, chosen)

    def ask_open(self):
        ui.ask("Abrir", "Ruta de la hoja (.xlsx o .csv):", self.path, lambda p: self.load(p))

    def pdf(self, title):
        """The sheet as a table in a PDF (values, not formulas), like Excel's export."""
        from pyos.printing import PDF, _pdf_string, _info
        from office import word
        used = [k for k in self.cells]
        cols = max([c for c, _ in used] + [0]) + 1
        rows = max([r for _, r in used] + [0]) + 1
        cw, rh, left, top = 64, 16, 40, 800
        pdf = PDF()
        pages_obj = pdf.reserve()
        font = pdf.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        per_page = (top - 40) // rh
        kids = []
        for first in range(0, rows, per_page):
            out = bytearray(b"0.8 g 0.5 w\n")
            n = min(per_page, rows - first)
            for k in range(n + 1):                                 # the grid
                y = top - k * rh
                out += b"%d %d m %d %d l S\n" % (left, y, left + cols * cw, y)
            for c in range(cols + 1):
                out += b"%d %d m %d %d l S\n" % (left + c * cw, top, left + c * cw, top - n * rh)
            out += b"0 g\n"
            for k in range(n):
                for c in range(cols):
                    v = self.value(c, first + k) if (c, first + k) in self.cells else ""
                    s = ("%.6g" % v) if isinstance(v, float) else str(v)
                    while s and word.text_width(s, 9) > cw - 6:
                        s = s[:-1]
                    x = left + c * cw + (cw - 3 - word.text_width(s, 9) if isinstance(v, (int, float)) else 3)
                    out += b"BT /F1 9 Tf %.1f %d Td " % (x, top - k * rh - 12) + _pdf_string(s) + b" Tj ET\n"
            stream = pdf.stream("", bytes(out))
            kids.append(pdf.add("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
                                "/Resources << /Font << /F1 %d 0 R >> >> >>" % (pages_obj, stream, font)))
        pdf.set(pages_obj, "<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kids), len(kids)))
        root = pdf.add("<< /Type /Catalog /Pages %d 0 R >>" % pages_obj)
        return pdf.output(root, _info(pdf, title))

    def value(self, c, r, depth=0):
        raw = self.cells.get((c, r), "")
        if not raw.startswith("="):
            try:
                return float(raw) if "." in raw else int(raw)
            except ValueError:
                return raw
        if depth > 20:
            return "#ciclo"
        env = {"sum": self._sum, "max": _agg(max), "min": _agg(min), "abs": abs, "round": round,
               "average": lambda v: self._sum(v) / max(1, len([x for x in v if isinstance(x, (int, float))]))}
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
