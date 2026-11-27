# The icons on the desktop: the files and folders in /disk/Escritorio, plus
# the trash. Double-click opens, drag moves, right-click gives a menu.
import json
import os
import time
import pygame
from desktop import theme as T, ui, icons, places

CELL_W, CELL_H = 92, 92
KIND_ICON = {"folder": "folder", "image": "images", "sound": "music", "web": "browser", "app": "about",
             "python": "editor", "text": "notes", "sheet": "sheet", "exe": "exe", "document": "escritor",
             "slides": "presentaciones", "pdf": "browser",
             "video": "videos"}


class DesktopIcons:
    def __init__(self, wm):
        self.wm = wm
        self.items = []            # [name, x, y]; name "" is the trash
        self.selected = None
        self.drag = None           # (index, dx, dy, moved)
        self.last_click = (0, None)
        self.reload()

    # ---- what is on the desktop ----
    def positions_file(self):
        return places.desktop() + "/.posiciones.json"

    def reload(self):
        places.ensure()
        try:
            names = sorted(n for n in os.listdir(places.desktop()) if not n.startswith("."))
        except OSError:
            names = []
        try:
            with open(self.positions_file()) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        self.items = []
        taken = set()
        for name in [""] + names:
            pos = saved.get(name)
            if pos is None:
                pos = self.free_spot(taken)
            taken.add(tuple(pos))
            self.items.append([name, pos[0], pos[1]])
        self.wm.dirty = True

    def free_spot(self, taken):
        cols = (T.SCREEN[1] - T.TOP_H - T.DOCK_H - 20) // CELL_H
        i = 0
        while True:
            x = 16 + (i // cols) * CELL_W
            y = T.TOP_H + 14 + (i % cols) * CELL_H
            if (x, y) not in taken:
                return [x, y]
            i += 1

    def save_positions(self):
        try:
            with open(self.positions_file(), "w") as f:
                json.dump({n: [x, y] for n, x, y in self.items}, f)
        except OSError:
            pass

    def path(self, name):
        return places.trash() if name == "" else places.join(places.desktop(), name)

    def label(self, name):
        return "Papelera" if name == "" else name

    def icon_for(self, name):
        if name == "":
            return "trash"
        k = places.kind(self.path(name))
        if k == "app":
            from desktop import apps
            meta = apps.read_header(self.path(name)) or {}
            return meta.get("icon", "about")
        return KIND_ICON.get(k, "notes")

    # ---- drawing ----
    def draw(self, scr):
        f = ui.font(13)
        for i, (name, x, y) in enumerate(self.items):
            if i == self.selected:
                pygame.draw.rect(scr, (255, 255, 255), (x - 2, y - 2, CELL_W - 8, CELL_H - 6), 1, 10)
            scr.blit(icons.icon(self.icon_for(name), 48, self.label(name)), (x + (CELL_W - 8 - 48) // 2 - 2, y + 4))
            lines = ui.wrap(self.label(name), CELL_W - 12, f)[:2]
            for k, line in enumerate(lines):
                cx = x + (CELL_W - 8) // 2 - 2
                ui.text(scr, line, cx + 1, y + 57 + k * 15, (20, 20, 30), f, CELL_W - 10, center=True)     # shadow
                ui.text(scr, line, cx, y + 56 + k * 15, (255, 255, 255), f, CELL_W - 10, center=True)

    def at(self, pos):
        for i in range(len(self.items) - 1, -1, -1):
            name, x, y = self.items[i]
            if x <= pos[0] < x + CELL_W - 8 and y <= pos[1] < y + CELL_H - 6:
                return i
        return None

    # ---- events (only those that land on the desktop itself) ----
    def mouse_down(self, ev):
        i = self.at(ev.pos)
        if ev.button == 3:
            self.selected = i
            self.wm.context_menu(ev.pos, self.item_menu(i) if i is not None else self.desktop_menu())
            return
        if ev.button != 1:
            return
        self.selected = i
        if i is None:
            return
        now = time.ticks_ms()
        if self.last_click[1] == i and now - self.last_click[0] < 450:
            self.open(i)
            self.last_click = (0, None)
            return
        self.last_click = (now, i)
        name, x, y = self.items[i]
        self.drag = [i, ev.pos[0] - x, ev.pos[1] - y, False]

    def mouse_move(self, ev):
        if not self.drag:
            return False
        i, dx, dy, _ = self.drag
        self.items[i][1] = max(0, min(T.SCREEN[0] - CELL_W, ev.pos[0] - dx))
        self.items[i][2] = max(T.TOP_H, min(T.SCREEN[1] - T.DOCK_H - CELL_H, ev.pos[1] - dy))
        self.drag[3] = True
        return True

    def mouse_up(self, ev):
        if not self.drag:
            return False
        moved = self.drag[3]
        self.drag = None
        if moved:
            self.save_positions()
        return True

    def key(self, ev):
        if self.selected is None:
            return False
        if ev.key == pygame.K_RETURN:
            self.open(self.selected)
        elif ev.key in (pygame.K_DELETE,) and self.items[self.selected][0]:
            self.trash(self.selected)
        elif ev.key == pygame.K_F2 and self.items[self.selected][0]:
            self.rename(self.selected)
        else:
            return False
        return True

    # ---- actions ----
    def open(self, i):
        places.open_path(self.path(self.items[i][0]))

    def rename(self, i):
        name = self.items[i][0]

        def done(new):
            places.rename(places.desktop(), name, new)
            self.reload()
        self.wm.ask("Renombrar", "Nuevo nombre para “%s”:" % name, name, done)

    def trash(self, i):
        places.to_trash(self.path(self.items[i][0]))
        self.selected = None
        self.reload()

    def new_folder(self):
        def done(name):
            places.new_folder(places.desktop(), name or "Carpeta nueva")
            self.reload()
        self.wm.ask("Nueva carpeta", "Nombre de la carpeta:", "Carpeta nueva", done)

    def new_document(self):
        def done(name):
            if "." not in name:
                name += ".txt"
            places.new_file(places.desktop(), name)
            self.reload()
        self.wm.ask("Nuevo documento", "Nombre del documento:", "Documento nuevo.txt", done)

    def desktop_menu(self):
        return [("Nueva carpeta", self.new_folder), ("Nuevo documento de texto", self.new_document), None,
                ("Abrir el Escritorio en Archivos", lambda: self.wm.launch("files", places.desktop())),
                ("Abrir una terminal aqui", lambda: self.wm.launch("terminal", places.desktop())), None,
                ("Cambiar el fondo de pantalla", self.wm.next_wallpaper),
                ("Ordenar los iconos", self.arrange), ("Actualizar", self.reload)]

    def item_menu(self, i):
        name = self.items[i][0]
        if name == "":
            return [("Abrir la papelera", lambda: self.open(i)),
                    ("Vaciar la papelera", lambda: self.wm.confirm(
                        "Vaciar la papelera", "Se borraran para siempre los archivos de la papelera.",
                        lambda ok: ok and (places.empty_trash(), self.reload())))]
        return [("Abrir", lambda: self.open(i)), ("Renombrar", lambda: self.rename(i)),
                ("Duplicar", lambda: (places.copy(self.path(name), places.desktop()), self.reload())), None,
                ("Mover a la papelera", lambda: self.trash(i))]

    def arrange(self):
        try:
            os.remove(self.positions_file())
        except OSError:
            pass
        self.reload()
