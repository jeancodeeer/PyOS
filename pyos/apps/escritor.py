# pyos-app
# name: Escritor
# icon: escritor
# mode: window
#
# A word processor: paragraphs with a style (title, subtitle, normal), bold,
# alignment and colour. Formatting applies to the paragraph the cursor is
# in. Documents are saved as HTML, so the web browser can show them too.
import pygame
from desktop import theme as T, ui, clipboard
from desktop.wm import App as Base

STYLES = {"titulo": (32, True), "subtitulo": (24, True), "normal": (15, False)}
COLORS = [(28, 30, 36), (200, 40, 40), (40, 120, 220), (40, 150, 80), (150, 60, 190), (230, 130, 30)]
TOOL_H = 76
MARGIN = 40


def new_par(text="", style="normal"):
    return {"text": text, "style": style, "bold": False, "align": "left", "color": 0}


class App(Base):
    title = "Escritor"
    size = (760, 540)

    def __init__(self, win, path=None):
        Base.__init__(self, win)
        self.path = path
        self.pars = [new_par("Titulo del documento", "titulo"), new_par("Escribe aqui.")]
        self.p, self.col = 1, len(self.pars[1]["text"])
        self.scroll = 0
        self.modified = False
        self.menu = ui.MenuBar(win.w, [
            ("Archivo", [("Nuevo", self.new), ("Abrir...", self.ask_open), ("Guardar", self.save),
                         ("Guardar como...", self.ask_save), None, ("Ver en el navegador", self.preview)]),
            ("Editar", [("Copiar todo el texto", lambda: clipboard.set(self.plain())), ("Pegar", self.paste)]),
        ])
        self.form = ui.Form()
        x = 10
        for label, fn, w in (("Titulo", lambda: self.set("style", "titulo"), 70),
                             ("Subtitulo", lambda: self.set("style", "subtitulo"), 86),
                             ("Normal", lambda: self.set("style", "normal"), 72),
                             ("N", self.toggle_bold, 34),
                             ("←", lambda: self.set("align", "left"), 34),
                             ("↔", lambda: self.set("align", "center"), 34),
                             ("→", lambda: self.set("align", "right"), 34)):
            self.form.add(ui.Button((x, 36, w, 30), label, fn))
            x += w + 6
        self.swatch_x = x + 10
        if path:
            self.open(path)

    # ---- document ----
    def cur(self):
        return self.pars[self.p]

    def set(self, key, value):
        self.cur()[key] = value
        self.touch()

    def toggle_bold(self):
        self.set("bold", not self.cur()["bold"])

    def touch(self):
        if not self.modified:
            self.modified = True
            self.update_title()

    def plain(self):
        return "\n\n".join(p["text"] for p in self.pars)

    def paste(self):
        for k, piece in enumerate(clipboard.get().split("\n")):
            if k:
                self.split()
            self.insert(piece)

    def insert(self, s):
        t = self.cur()["text"]
        self.cur()["text"] = t[:self.col] + s + t[self.col:]
        self.col += len(s)
        self.touch()

    def split(self):
        t = self.cur()["text"]
        after = new_par(t[self.col:])
        after["align"], after["color"] = self.cur()["align"], self.cur()["color"]
        self.cur()["text"] = t[:self.col]
        self.pars.insert(self.p + 1, after)
        self.p, self.col = self.p + 1, 0
        self.touch()

    # ---- files (HTML) ----
    def new(self):
        self.path = None
        self.pars = [new_par()]
        self.p = self.col = 0
        self.modified = False
        self.update_title()

    def update_title(self):
        name = self.path.rsplit("/", 1)[-1] if self.path else "Documento"
        self.win.set_title(("*" if self.modified else "") + name + " - Escritor")

    def html(self):
        out = ["<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>%s</title></head><body>" %
               _esc(self.pars[0]["text"] if self.pars else "")]
        for par in self.pars:
            tag = {"titulo": "h1", "subtitulo": "h2"}.get(par["style"], "p")
            css = "text-align:%s;color:#%02x%02x%02x" % ((par["align"],) + COLORS[par["color"]])
            if par["bold"] and tag == "p":
                css += ";font-weight:bold"
            out.append('<%s style="%s">%s</%s>' % (tag, css, _esc(par["text"]), tag))
        return "\n".join(out) + "\n</body></html>\n"

    def save(self):
        if not self.path:
            return self.ask_save()
        with open(self.path, "w") as f:
            f.write(self.html())
        self.modified = False
        self.update_title()
        ui.toast("guardado: " + self.path)

    def ask_save(self):
        ui.ask("Guardar como", "Ruta del documento (.html):", self.path or "/disk/Documentos/documento.html",
               lambda p: (setattr(self, "path", p if p.endswith((".html", ".htm")) else p + ".html"), self.save()))

    def ask_open(self):
        ui.ask("Abrir", "Ruta del documento:", self.path or "/disk/Documentos/", self.open)

    def open(self, path):
        try:
            with open(path) as f:
                text = f.read()
        except OSError as e:
            ui.toast("no se pudo abrir: %s" % e)
            return
        pars = []
        if path.endswith((".html", ".htm")):
            from browser import html
            doc = html.parse(text)
            for node in doc.iter():
                if node.tag in ("h1", "h2", "h3", "p", "li"):
                    par = new_par(" ".join(node.text_content().split()),
                                  {"h1": "titulo", "h2": "subtitulo", "h3": "subtitulo"}.get(node.tag, "normal"))
                    style = node.attrs.get("style", "")
                    for a in ("center", "right"):
                        if "text-align:" + a in style.replace(" ", ""):
                            par["align"] = a
                    par["bold"] = "bold" in style
                    for i, c in enumerate(COLORS):
                        if "#%02x%02x%02x" % c in style:
                            par["color"] = i
                    pars.append(par)
        else:
            pars = [new_par(p) for p in text.split("\n")]
        self.pars = pars or [new_par()]
        self.path, self.p, self.col, self.modified = path, 0, 0, False
        self.update_title()

    def preview(self):
        if not self.path:
            ui.toast("guarda el documento primero")
            return
        self.save()
        from desktop import wm
        wm.wm.launch("browser", "file://" + self.path)

    # ---- layout ----
    def font(self, par):
        size, bold = STYLES[par["style"]]
        return ui.font(size, bold or par["bold"])

    def layout(self):
        """[(paragraph index, start, line text, x, y, font)] for the whole document."""
        out, y = [], 0
        width = self.win.w - 2 * MARGIN
        for i, par in enumerate(self.pars):
            f = self.font(par)
            lines = ui.wrap(par["text"], width, f) if par["text"] else [""]
            start = 0
            for line in lines:
                w = f.size(line)[0]
                x = MARGIN + {"left": 0, "center": (width - w) // 2, "right": width - w}[par["align"]]
                out.append((i, start, line, x, y, f))
                start += len(line) + 1
                y += f.get_height() + 4
            y += 10 if par["style"] == "normal" else 14
        return out, y

    def cursor_xy(self, rows):
        for k, (i, start, line, x, y, f) in enumerate(rows):
            nxt = rows[k + 1] if k + 1 < len(rows) else None
            last_of_par = nxt is None or nxt[0] != i
            if i == self.p and start <= self.col and (self.col <= start + len(line) or last_of_par):
                if self.col <= start + len(line) or last_of_par:
                    return x + f.size(line[:self.col - start])[0], y, f.get_height()
        return MARGIN, 0, 16

    # ---- drawing ----
    def draw(self, surf):
        surf.fill((228, 231, 238))
        self.menu.rect.w = self.win.w
        self.menu.draw(surf)
        pygame.draw.rect(surf, (246, 247, 250), (0, 28, self.win.w, TOOL_H - 28))
        self.form.draw(surf)
        for i, c in enumerate(COLORS):
            r = pygame.Rect(self.swatch_x + i * 30, 40, 24, 24)
            pygame.draw.rect(surf, c, r, 0, 12)
            if i == self.cur()["color"]:
                pygame.draw.rect(surf, (255, 255, 255), r.inflate(-10, -10), 0, 6)
        page = pygame.Rect(MARGIN // 2, TOOL_H + 8, self.win.w - MARGIN, self.win.h - TOOL_H - 34)
        pygame.draw.rect(surf, (255, 255, 255), page, 0, 6)
        rows, total = self.layout()
        cx, cy, ch = self.cursor_xy(rows)
        view_h = page.h - 30
        if cy - self.scroll > view_h:
            self.scroll = cy - view_h
        if cy < self.scroll:
            self.scroll = cy
        oy = page.y + 16 - self.scroll
        for i, start, line, x, y, f in rows:
            if 0 <= y - self.scroll < view_h + 20:
                ui.text(surf, line, x, oy + y, COLORS[self.pars[i]["color"]], f)
        if 0 <= cy - self.scroll <= view_h + 10:
            pygame.draw.line(surf, T.ACCENT, (cx, oy + cy), (cx, oy + cy + ch), 2)
        words = sum(len(p["text"].split()) for p in self.pars)
        style = {"titulo": "Titulo", "subtitulo": "Subtitulo", "normal": "Normal"}[self.cur()["style"]]
        ui.text(surf, "%d palabras    parrafo %d de %d    estilo: %s%s" % (
            words, self.p + 1, len(self.pars), style, ", negrita" if self.cur()["bold"] else ""), 12, self.win.h - 22, T.MUTED)

    # ---- events ----
    def event(self, ev, pos):
        if self.menu.event(ev, pos) or (pos and pos[1] < TOOL_H and self.form.event(ev, pos)):
            return True
        if ev.type == pygame.MOUSEBUTTONDOWN and pos and pos[1] < TOOL_H and ev.button == 1:
            for i in range(len(COLORS)):
                if pygame.Rect(self.swatch_x + i * 30, 40, 24, 24).collidepoint(pos):
                    self.set("color", i)
                    return True
            return False
        if ev.type == pygame.MOUSEBUTTONDOWN and pos:
            if ev.button in (4, 5):
                self.scroll = max(0, self.scroll + (-40 if ev.button == 4 else 40))
                return True
            rows, _ = self.layout()
            y = pos[1] - (TOOL_H + 24) + self.scroll
            best = None
            for i, start, line, x, ly, f in rows:
                if ly <= y:
                    best = (i, start, line, x, f)
            if best:
                i, start, line, x, f = best
                k = 0
                while k < len(line) and f.size(line[:k + 1])[0] < pos[0] - x:
                    k += 1
                self.p, self.col = i, start + k
            return True
        if ev.type != pygame.KEYDOWN:
            return False
        k, c = ev.key, ui.ctrl(ev)
        text = self.cur()["text"]
        if c and k == pygame.K_s:
            self.save()
        elif c and k == pygame.K_b:
            self.toggle_bold()
        elif c and k == pygame.K_v:
            self.paste()
        elif k == pygame.K_RETURN:
            self.split()
        elif k == pygame.K_BACKSPACE:
            if self.col:
                self.cur()["text"] = text[:self.col - 1] + text[self.col:]
                self.col -= 1
            elif self.p:
                self.p -= 1
                self.col = len(self.cur()["text"])
                self.cur()["text"] += self.pars.pop(self.p + 1)["text"]
            self.touch()
        elif k == pygame.K_DELETE:
            if self.col < len(text):
                self.cur()["text"] = text[:self.col] + text[self.col + 1:]
            elif self.p + 1 < len(self.pars):
                self.cur()["text"] += self.pars.pop(self.p + 1)["text"]
            self.touch()
        elif k == pygame.K_LEFT:
            if self.col:
                self.col -= 1
            elif self.p:
                self.p -= 1
                self.col = len(self.cur()["text"])
        elif k == pygame.K_RIGHT:
            if self.col < len(text):
                self.col += 1
            elif self.p + 1 < len(self.pars):
                self.p, self.col = self.p + 1, 0
        elif k == pygame.K_UP:
            self.p = max(0, self.p - 1)
            self.col = min(self.col, len(self.cur()["text"]))
        elif k == pygame.K_DOWN:
            self.p = min(len(self.pars) - 1, self.p + 1)
            self.col = min(self.col, len(self.cur()["text"]))
        elif k == pygame.K_HOME:
            self.col = 0
        elif k == pygame.K_END:
            self.col = len(text)
        elif ui.is_text_key(ev):
            self.insert(ev.unicode)
        else:
            return False
        return True

    def close(self):
        if self.modified and self.path:
            self.save()
        return True


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
