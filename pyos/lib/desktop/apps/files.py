# Files: browse folders, open files with the right app, create folders and
# documents, rename, copy and paste, send to the trash. Right-click for a menu.
import os
import pygame
from desktop import theme as T, ui, icons, places
from desktop.wm import App
from desktop.deskicons import KIND_ICON

SIDE_W = 170
ROW_H = 30
SIDE = [("Escritorio", "Escritorio"), ("Documentos", "Documentos"), ("Descargas", "Descargas"),
        ("Imagenes", "Imagenes"), ("Musica", "Musica"), ("Papelera", ".Papelera")]
ROOTS = [("Disco", "/disk"), ("USB", "/usb"), ("Sistema", "/")]


def _size(n):
    if n < 1024:
        return "%d bytes" % n
    if n < 1 << 20:
        return "%.1f KB" % (n / 1024)
    return "%.1f MB" % (n / 1048576)


class Files(App):
    title = "Archivos"
    size = (760, 480)

    def __init__(self, win, path=None):
        App.__init__(self, win)
        places.ensure()
        self.path = path or places.desktop()
        self.entries = []              # (name, is_dir, size)
        self.selected = None
        self.top = 0
        self.clipboard = None          # (path, cut?)
        self.last_click = (0, None)
        self.form = ui.Form()
        self.bar = self.form.add(ui.Field((SIDE_W + 92, 8, 300, 30), self.path, self.go))
        self.form.add(ui.Button((SIDE_W + 10, 8, 34, 30), "←", self.up))
        self.form.add(ui.Button((SIDE_W + 48, 8, 38, 30), "⌂", lambda: self.go(places.home())))
        self.new_btn = self.form.add(ui.Button((0, 8, 130, 30), "+ Carpeta", self.new_folder, primary=True))
        self.layout()
        self.load()

    # ---- the folder ----
    def layout(self):
        self.bar.rect.w = max(120, self.win.w - SIDE_W - 92 - 150)
        self.new_btn.rect.x = self.bar.rect.right + 8

    def resized(self, w, h):
        self.layout()

    def load(self):
        try:
            names = sorted(os.listdir(self.path))
        except OSError:
            names = []
        dirs, files = [], []
        for n in names:
            if n.startswith(".") and self.path != places.trash():
                continue
            full = places.join(self.path, n)
            if places.is_dir(full):
                dirs.append((n, True, 0))
            else:
                try:
                    files.append((n, False, os.stat(full)[6]))
                except OSError:
                    files.append((n, False, 0))
        self.entries = dirs + files
        self.selected = None
        self.top = 0
        self.bar.set(self.path)
        self.win.set_title("Archivos - " + self.path)

    def go(self, path):
        path = path.rstrip("/") or "/"
        if places.is_dir(path):
            self.path = path
            self.load()
        else:
            places.open_path(path)

    def up(self):
        self.go(self.path.rsplit("/", 1)[0] or "/")

    def full(self, i):
        return places.join(self.path, self.entries[i][0])

    # ---- actions ----
    def wm(self):
        from desktop import wm
        return wm.wm

    def new_folder(self):
        self.wm().ask("Nueva carpeta", "Nombre de la carpeta:", "Carpeta nueva",
                      lambda name: (places.new_folder(self.path, name or "Carpeta nueva"), self.load()))

    def new_document(self):
        def done(name):
            places.new_file(self.path, name if "." in name else name + ".txt")
            self.load()
        self.wm().ask("Nuevo documento", "Nombre del documento:", "Documento nuevo.txt", done)

    def rename(self, i):
        name = self.entries[i][0]
        self.wm().ask("Renombrar", "Nuevo nombre para “%s”:" % name, name,
                      lambda new: (places.rename(self.path, name, new), self.load()))

    def trash(self, i):
        name = self.entries[i][0]
        if self.path == places.trash():
            self.wm().confirm("Borrar para siempre", "“%s” se borrara y no se podra recuperar." % name,
                              lambda ok: ok and (places.remove(self.full(i)), self.load()))
        else:
            places.to_trash(self.full(i))
            self.load()

    def copy(self, i, cut=False):
        self.clipboard = (self.full(i), cut)
        self.wm().toast(("cortado: " if cut else "copiado: ") + self.entries[i][0])

    def paste(self):
        if not self.clipboard:
            return
        src, cut = self.clipboard
        if cut:
            name = places.unique(self.path, src.rsplit("/", 1)[-1])
            os.rename(src, places.join(self.path, name))
            self.clipboard = None
        else:
            places.copy(src, self.path)
        self.load()

    def to_desktop(self, i):
        places.copy(self.full(i), places.desktop())
        self.wm().icons.reload()
        self.wm().toast("copiado al Escritorio")

    def item_menu(self, i):
        items = [("Abrir", lambda: places.open_path(self.full(i))), ("Renombrar", lambda: self.rename(i)),
                 ("Copiar", lambda: self.copy(i)), ("Cortar", lambda: self.copy(i, True)),
                 ("Enviar al Escritorio", lambda: self.to_desktop(i)), None,
                 ("Borrar para siempre" if self.path == places.trash() else "Mover a la papelera", lambda: self.trash(i))]
        if self.entries[i][0].endswith(".py"):
            items.insert(1, ("Editar el codigo", lambda: self.wm().launch("editor", self.full(i))))
        return items

    def folder_menu(self):
        items = [("Nueva carpeta", self.new_folder), ("Nuevo documento de texto", self.new_document)]
        if self.clipboard:
            items.append(("Pegar", self.paste))
        items += [None, ("Abrir una terminal aqui", lambda: self.wm().launch("terminal", self.path)),
                  ("Actualizar", self.load)]
        if self.path == places.trash():
            items.append(("Vaciar la papelera", lambda: self.wm().confirm(
                "Vaciar la papelera", "Se borrara todo lo que hay en la papelera.",
                lambda ok: ok and (places.empty_trash(), self.load()))))
        return items

    # ---- drawing ----
    def rows(self):
        return max(1, (self.win.h - 56 - 26) // ROW_H)

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        pygame.draw.rect(surf, (238, 240, 245), (0, 0, SIDE_W, self.win.h))
        f, fb = ui.FONT(), ui.font(11, bold=True)
        y = 14
        ui.text(surf, "LUGARES", 16, y, T.MUTED, fb)
        y += 20
        for entry in SIDE + [None] + ROOTS:
            if entry is None:
                y += 8
                ui.text(surf, "DISCOS", 16, y, T.MUTED, fb)
                y += 20
                continue
            label, rel = entry
            target = rel if rel.startswith("/") else places.path(rel)
            active = self.path == target
            if active:
                pygame.draw.rect(surf, T.SELECT, (8, y - 3, SIDE_W - 16, 26), 0, 6)
            name = "trash" if rel == ".Papelera" else "folder"
            surf.blit(icons.icon(name, 18, label), (16, y))
            ui.text(surf, label, 42, y + 2, T.TEXT, f)
            y += 28
        self.form.draw(surf)
        x0, y0 = SIDE_W + 10, 50
        n = self.rows()
        for k in range(n):
            j = self.top + k
            if j >= len(self.entries):
                break
            name, is_dir, size = self.entries[j]
            y = y0 + k * ROW_H
            if j == self.selected:
                pygame.draw.rect(surf, T.ACCENT, (x0, y, self.win.w - x0 - 10, ROW_H - 2), 0, 6)
            color = T.ACCENT_TEXT if j == self.selected else T.TEXT
            kind = "folder" if is_dir else places.kind(places.join(self.path, name))
            surf.blit(icons.icon(KIND_ICON.get(kind, "notes"), 22, name), (x0 + 6, y + 3))
            ui.text(surf, name, x0 + 38, y + 6, color, f, self.win.w - x0 - 160)
            info = "carpeta" if is_dir else _size(size)
            ui.text(surf, info, self.win.w - 20 - ui.width(info, f), y + 6, color if j == self.selected else T.MUTED, f)
        if not self.entries:
            ui.text(surf, "Carpeta vacia - clic derecho para crear algo", x0 + 10, y0 + 10, T.MUTED, f)
        status = "%d elementos" % len(self.entries)
        if self.clipboard:
            status += "   •   en el portapapeles: " + self.clipboard[0].rsplit("/", 1)[-1]
        ui.text(surf, status, SIDE_W + 14, self.win.h - 22, T.MUTED, f, self.win.w - SIDE_W - 20)

    # ---- events ----
    def side_click(self, y):
        yy = 34
        for entry in SIDE + [None] + ROOTS:
            if entry is None:
                yy += 28
                continue
            label, rel = entry
            if yy - 3 <= y < yy + 25:
                self.go(rel if rel.startswith("/") else places.path(rel))
                return True
            yy += 28
        return False

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and pos is not None:
            if pos[0] < SIDE_W:
                return ev.button == 1 and self.side_click(pos[1])
            if pos[1] < 46:
                return self.form.event(ev, pos)
            self.bar.focus = False
            if ev.button in (4, 5):
                self.top = max(0, min(max(0, len(self.entries) - self.rows()), self.top + (-3 if ev.button == 4 else 3)))
                return True
            j = self.top + (pos[1] - 50) // ROW_H
            hit = j if 0 <= j < len(self.entries) and pos[1] >= 50 else None
            if ev.button == 3:
                self.selected = hit
                self.wm().context_menu(pygame.mouse.get_pos(), self.item_menu(hit) if hit is not None else self.folder_menu())
                return True
            if ev.button == 1:
                import time
                now = time.ticks_ms()
                if hit is not None and self.last_click[1] == hit and now - self.last_click[0] < 450:
                    self.go(self.full(hit))
                    self.last_click = (0, None)
                else:
                    self.last_click = (now, hit)
                    self.selected = hit
                return True
        if ev.type == pygame.KEYDOWN and not self.bar.focus:
            k = ev.key
            if k in (pygame.K_UP, pygame.K_DOWN) and self.entries:
                cur = -1 if self.selected is None else self.selected
                self.selected = max(0, min(len(self.entries) - 1, cur + (1 if k == pygame.K_DOWN else -1)))
                self.top = min(self.top, self.selected)
                self.top = max(self.top, self.selected - self.rows() + 1)
                return True
            if self.selected is not None:
                if k == pygame.K_RETURN:
                    self.go(self.full(self.selected))
                    return True
                if k == pygame.K_DELETE:
                    self.trash(self.selected)
                    return True
                if k == pygame.K_F2:
                    self.rename(self.selected)
                    return True
                if ui.ctrl(ev) and k in (pygame.K_c, pygame.K_x):
                    self.copy(self.selected, k == pygame.K_x)
                    return True
            if ui.ctrl(ev) and k == pygame.K_v:
                self.paste()
                return True
            if k == pygame.K_BACKSPACE:
                self.up()
                return True
            if ui.ctrl(ev) and ui.shift(ev) and k == pygame.K_n:
                self.new_folder()
                return True
        return self.form.event(ev, pos)
