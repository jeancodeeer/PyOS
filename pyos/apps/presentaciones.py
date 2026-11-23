# pyos-app
# name: Presentaciones
# icon: presentaciones
# mode: window
#
# Slides with a title and bullet points, in a few colour themes. Click the
# title or the text of a slide to write in it; "Presentar" shows them full
# screen (arrows or click to move, Esc to stop). Saved as JSON.
import json
import pygame
from desktop import theme as T, ui
from desktop.wm import App as Base

THEMES = [  # background, title colour, text colour, accent
    ((255, 255, 255), (30, 50, 100), (40, 44, 52), (64, 120, 242)),
    ((24, 30, 48), (255, 255, 255), (210, 216, 232), (255, 200, 80)),
    ((240, 248, 240), (20, 110, 70), (40, 60, 50), (60, 170, 110)),
    ((255, 244, 230), (180, 70, 30), (70, 50, 40), (240, 130, 40)),
]
THUMB_W = 150
DEFAULT = "/disk/Documentos/presentacion.json"


class App(Base):
    title = "Presentaciones"
    size = (820, 540)

    def __init__(self, win, path=None):
        Base.__init__(self, win)
        self.path = path or DEFAULT
        self.slides = [{"title": "Mi presentacion", "body": "Hecha en PyOS\nCon Python y pygame"},
                       {"title": "Segunda diapositiva", "body": "Primer punto\nSegundo punto"}]
        self.theme = 0
        self.current = 0
        self.editing = "title"          # which part of the slide takes the keys
        self.menu = ui.MenuBar(win.w, [
            ("Archivo", [("Nueva", self.new), ("Abrir...", self.ask_open), ("Guardar", self.save),
                         ("Guardar como...", self.ask_save)]),
            ("Diapositiva", [("Nueva diapositiva", self.add), ("Borrar diapositiva", self.remove),
                             ("Subir", lambda: self.shift(-1)), ("Bajar", lambda: self.shift(1))]),
        ])
        self.form = ui.Form()
        self.form.add(ui.Button((THUMB_W + 20, 36, 130, 30), "▶ Presentar", self.present, primary=True))
        self.form.add(ui.Button((THUMB_W + 156, 36, 130, 30), "+ Diapositiva", self.add))
        self.form.add(ui.Button((THUMB_W + 292, 36, 110, 30), "Tema", self.next_theme))
        try:
            self.load(self.path)
        except (OSError, ValueError):
            pass

    # ---- slides ----
    def slide(self):
        return self.slides[self.current]

    def add(self):
        self.slides.insert(self.current + 1, {"title": "Nueva diapositiva", "body": ""})
        self.current += 1
        self.editing = "title"

    def remove(self):
        if len(self.slides) > 1:
            del self.slides[self.current]
            self.current = min(self.current, len(self.slides) - 1)

    def shift(self, d):
        j = self.current + d
        if 0 <= j < len(self.slides):
            self.slides[self.current], self.slides[j] = self.slides[j], self.slides[self.current]
            self.current = j

    def next_theme(self):
        self.theme = (self.theme + 1) % len(THEMES)

    # ---- files ----
    def new(self):
        self.slides = [{"title": "Titulo", "body": ""}]
        self.current, self.path = 0, DEFAULT

    def load(self, path):
        with open(path) as f:
            data = json.load(f)
        self.slides = data.get("slides") or self.slides
        self.theme = data.get("theme", 0) % len(THEMES)
        self.path = path
        self.current = 0

    def save(self):
        import os
        try:
            os.mkdir(self.path.rsplit("/", 1)[0])
        except OSError:
            pass
        with open(self.path, "w") as f:
            json.dump({"slides": self.slides, "theme": self.theme}, f)
        ui.toast("guardado: " + self.path)

    def ask_save(self):
        ui.ask("Guardar como", "Ruta (.json):", self.path, lambda p: (setattr(self, "path", p), self.save()))

    def ask_open(self):
        ui.ask("Abrir", "Ruta de la presentacion:", self.path,
               lambda p: self.load(p) if _exists(p) else ui.toast("no existe: " + p))

    # ---- drawing a slide at any size ----
    def render(self, surf, rect, slide, editing=None):
        bg, title_c, text_c, accent = THEMES[self.theme]
        pygame.draw.rect(surf, bg, rect)
        s = rect.w / 1024.0                                     # everything scales with the width
        pygame.draw.rect(surf, accent, (rect.x, rect.y, rect.w, max(2, int(10 * s))))
        tf = ui.font(_size(44 * s), bold=True)
        bf = ui.font(_size(24 * s))
        x = rect.x + int(70 * s)
        y = rect.y + int(70 * s)
        for line in ui.wrap(slide["title"], rect.w - int(140 * s), tf)[:2]:
            ui.text(surf, line, x, y, title_c, tf)
            y += tf.get_height()
        if editing == "title":
            pygame.draw.rect(surf, accent, (x - 6, rect.y + int(62 * s), rect.w - int(128 * s), y - rect.y - int(56 * s)), 1)
        y += int(30 * s)
        body_top = y
        for point in slide["body"].split("\n"):
            if not point.strip() and editing != "body":
                continue
            pygame.draw.circle(surf, accent, (x + int(8 * s), y + bf.get_height() // 2), max(2, int(6 * s)))
            for k, line in enumerate(ui.wrap(point, rect.w - int(190 * s), bf) or [""]):
                ui.text(surf, line, x + int(30 * s), y, text_c, bf)
                y += bf.get_height() + int(6 * s)
            y += int(8 * s)
        if editing == "body":
            pygame.draw.rect(surf, accent, (x - 6, body_top - 6, rect.w - int(128 * s), max(30, y - body_top + 6)), 1)

    def stage(self):
        w = self.win.w - THUMB_W - 40
        h = w * 3 // 4
        if h > self.win.h - 120:
            h = self.win.h - 120
            w = h * 4 // 3
        return pygame.Rect(THUMB_W + 20, 80, w, h)

    def draw(self, surf):
        surf.fill((228, 231, 238))
        self.menu.rect.w = self.win.w
        self.menu.draw(surf)
        self.form.draw(surf)
        for i, sl in enumerate(self.slides[:8]):                 # thumbnails on the left
            r = pygame.Rect(12, 40 + i * 92, THUMB_W - 10, 80)
            self.render(surf, r, sl)
            pygame.draw.rect(surf, T.ACCENT if i == self.current else (190, 194, 204), r, 3 if i == self.current else 1)
            ui.text(surf, str(i + 1), r.x + 4, r.bottom - 18, T.MUTED, ui.font(11))
        stage = self.stage()
        self.render(surf, stage, self.slide(), self.editing)
        hint = "Escribiendo en el %s - clic en el titulo o en el texto; Enter = nuevo punto" % (
            "titulo" if self.editing == "title" else "texto")
        ui.text(surf, "Diapositiva %d de %d.  %s" % (self.current + 1, len(self.slides), hint),
                THUMB_W + 20, self.win.h - 24, T.MUTED, max_w=self.win.w - THUMB_W - 30)

    # ---- presenting: the whole screen until Esc ----
    def present(self):
        from desktop import wm
        screen = wm.wm.screen
        clock = pygame.time.Clock()
        i = self.current
        while True:
            self.render(screen, screen.get_rect(), self.slides[i])
            ui.text(screen, "%d / %d" % (i + 1, len(self.slides)), screen.get_width() - 80, screen.get_height() - 34,
                    (150, 150, 160), ui.font(15))
            pygame.display.flip()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                    wm.wm.dirty = True
                    return
                forward = (ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RIGHT, pygame.K_DOWN, pygame.K_SPACE,
                                                                    pygame.K_PAGEDOWN)) or \
                          (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1)
                back = ev.type == pygame.KEYDOWN and ev.key in (pygame.K_LEFT, pygame.K_UP, pygame.K_PAGEUP)
                if forward:
                    if i + 1 >= len(self.slides):
                        wm.wm.dirty = True
                        return
                    i += 1
                elif back:
                    i = max(0, i - 1)
            clock.tick(20)

    # ---- events ----
    def event(self, ev, pos):
        if self.menu.event(ev, pos) or self.form.event(ev, pos):
            return True
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and pos:
            if pos[0] < THUMB_W:
                i = (pos[1] - 40) // 92
                if 0 <= i < min(8, len(self.slides)):
                    self.current = i
                return True
            stage = self.stage()
            if stage.collidepoint(pos):
                self.editing = "title" if pos[1] < stage.y + stage.h * 0.28 else "body"
                return True
        if ev.type == pygame.KEYDOWN:
            key = "title" if self.editing == "title" else "body"
            s = self.slide()[key]
            if ev.key == pygame.K_BACKSPACE:
                self.slide()[key] = s[:-1]
            elif ev.key == pygame.K_RETURN:
                if key == "title":
                    self.editing = "body"
                else:
                    self.slide()["body"] = s + "\n"
            elif ev.key == pygame.K_F5:
                self.present()
            elif ev.key == pygame.K_PAGEDOWN:
                self.current = min(len(self.slides) - 1, self.current + 1)
            elif ev.key == pygame.K_PAGEUP:
                self.current = max(0, self.current - 1)
            elif ui.ctrl(ev) and ev.key == pygame.K_s:
                self.save()
            elif ui.is_text_key(ev):
                self.slide()[key] = s + ev.unicode
            else:
                return False
            return True
        return False


def _size(px):
    """The nearest font size the system has."""
    return min((11, 13, 15, 18, 24, 32, 44), key=lambda s: abs(s - px))


def _exists(path):
    import os
    try:
        os.stat(path)
        return True
    except OSError:
        return False
