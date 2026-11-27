# PyWin: run Windows programs (.exe). Lists the .exe files it finds, says
# whether PyWin has every Windows function each one uses, and runs them.
# A double click on an .exe anywhere (desktop, Archivos) does the same.
import os
import pygame
from desktop import theme as T, ui, icons
from desktop.wm import App

PLACES = ("/share/pywin/ejemplos", "/share/pywin/doom", "/disk/Escritorio", "/disk/Descargas", "/disk/Documentos", "/disk", "/usb")
LIST_W = 300


def find_programs():
    out = []
    for folder in PLACES:
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            if name.lower().endswith(".exe"):
                out.append(folder + "/" + name)
    return out


def check(path):
    """What an .exe is and which of its Windows functions PyWin lacks."""
    from pywin import pe, dlls
    img = pe.Image(pe.read_file(path))
    imports = img.file_imports()
    folder = path.rsplit("/", 1)[0]
    own = {}                                        # DLL files that come with the program
    try:
        for entry in os.listdir(folder):
            if entry.lower().endswith(".dll"):
                own[entry.lower()] = pe.Image(pe.read_file(folder + "/" + entry)).file_exports()
    except OSError:
        pass
    missing = [dll + "!" + name for dll, name, _ in imports
               if dlls.find(dll, name) is None and name not in own.get(dll.lower(), ())]
    used = sorted(set(dlls.base_name(d) for d, _, _ in imports))
    return {"console": img.console, "size": len(img.data), "imports": len(imports),
            "missing": missing, "dlls": used, "own": sorted(own)}


class PyWin(App):
    title = "PyWin"
    size = (760, 470)

    def __init__(self, win, path=None):
        App.__init__(self, win)
        self.form = ui.Form()
        self.list = self.form.add(ui.ListBox((12, 64, LIST_W, 330), [], self.pick, self.run_selected, row_h=28))
        self.form.add(ui.Button((12, 404, 140, 34), "Ejecutar", self.run_selected, primary=True))
        self.form.add(ui.Button((160, 404, 152, 34), "Abrir otro...", self.ask_path))
        self.details = None
        self.refresh()
        if path:
            self.run(path)

    def refresh(self):
        self.paths = find_programs()
        self.list.set_items([(p.rsplit("/", 1)[-1], p, p.rsplit("/", 2)[-2]) for p in self.paths])
        self.pick()

    def pick(self, item=None):
        if 0 <= self.list.selected < len(self.paths):
            path = self.paths[self.list.selected]
            try:
                self.details = (path, check(path))
            except Exception as e:
                self.details = (path, {"error": str(e)})

    def selected(self):
        i = self.list.selected
        return self.paths[i] if 0 <= i < len(self.paths) else None

    def run_selected(self, *args):
        path = self.selected()
        if path:
            self.run(path)

    def run(self, path):
        from pywin import host
        host.start(path)

    def ask_path(self):
        ui.ask("Abrir un programa de Windows", "Ruta del .exe:", "/disk/Descargas/",
               lambda p: self.run(p) if p.lower().endswith(".exe") else ui.toast("no es un .exe"))

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        surf.blit(icons.icon("pywin", 40), (12, 12))
        ui.text(surf, "PyWin", 62, 12, T.TEXT, ui.font(18, bold=True))
        ui.text(surf, "Programas de Windows (x64) en SnakeyOS: su codigo corre en el procesador; Windows es Python.",
                62, 36, T.MUTED, ui.font(11), self.win.w - 80)
        self.form.draw(surf)
        x = LIST_W + 32
        if not self.paths:
            ui.text(surf, "No hay archivos .exe en Escritorio, Descargas, Documentos ni USB.", x, 70, T.MUTED)
            return
        if not self.details:
            return
        path, d = self.details
        y = 70
        ui.text(surf, path.rsplit("/", 1)[-1], x, y, T.TEXT, ui.font(15, bold=True), self.win.w - x - 12)
        y += 26
        ui.text(surf, path, x, y, T.MUTED, ui.font(11), self.win.w - x - 12)
        y += 26
        if "error" in d:
            ui.text(surf, "No es un programa que PyWin pueda abrir: " + d["error"], x, y, (200, 60, 60),
                    max_w=self.win.w - x - 12)
            return
        rows = [("Tipo", "programa de consola" if d["console"] else "programa con ventanas"),
                ("Tamano", "%d KB" % (d["size"] // 1024)),
                ("DLL", ", ".join(d["dlls"])),
                ("Funciones", "%d de Windows" % d["imports"])]
        for label, value in rows:
            ui.text(surf, label, x, y, T.MUTED)
            ui.text(surf, value, x + 100, y, T.TEXT, max_w=self.win.w - x - 112)
            y += 24
        y += 8
        if d["missing"]:
            ui.text(surf, "Le faltan %d funciones (devolveran 0):" % len(d["missing"]), x, y, (200, 120, 30))
            y += 22
            for name in d["missing"][:9]:
                ui.text(surf, "  " + name, x, y, T.MUTED, ui.font(11), self.win.w - x - 12)
                y += 17
        else:
            pygame.draw.circle(surf, (60, 170, 90), (x + 8, y + 9), 8)
            ui.text(surf, "PyWin tiene todas las funciones que usa", x + 24, y, (40, 130, 70))

    def event(self, ev, pos):
        return self.form.event(ev, pos)
