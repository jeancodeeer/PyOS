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
    size = (800, 500)

    def __init__(self, win, path=None):
        App.__init__(self, win)
        self.form = ui.Form()
        self.list = self.form.add(ui.ListBox((12, 64, LIST_W, 360), [], self.pick, self.run_selected, row_h=28))
        y = 434
        self.form.add(ui.Button((12, y, 96, 34), "Abrir", self.run_selected, primary=True))
        self.form.add(ui.Button((114, y, 96, 34), "Instalar...", self.ask_install))
        self.form.add(ui.Button((216, y, 96, 34), "Desinstalar", self.uninstall_selected))
        self.details = None
        self.message = ""
        from pywin import install
        install.on_change(lambda: self.win and self.refresh())
        self.refresh()
        if path:
            if path.lower().endswith((".zip", ".msi")) or install.is_installer(path):
                self.install(path)
            else:
                self.run(path)

    def refresh(self):
        from pywin import install
        try:
            links = install.shortcuts()
            progs = install.programs()
        except Exception as e:
            links, progs = [], []
            self.message = "No se pudo leer lo instalado: %s" % e
        self.entries = []
        for s in links:
            prog = None
            for pr in progs:
                if pr["location"] and s["target"].lower().startswith(_host(pr["location"]).lower()):
                    prog = pr
            self.entries.append(("app", s, prog))
        covered = set(id(e[2]) for e in self.entries if e[2])
        for pr in progs:
            if id(pr) not in covered:
                self.entries.append(("prog", None, pr))
        for p in find_programs():
            self.entries.append(("exe", p, None))
        items = []
        for kind, a, b in self.entries:
            if kind == "app":
                items.append((a["name"], a["target"], "Instalado"))
            elif kind == "prog":
                items.append((b["name"], b["location"], "Instalado"))
            else:
                items.append((a.rsplit("/", 1)[-1], a, a.rsplit("/", 2)[-2]))
        self.list.set_items(items)
        self.pick()
        self.redraw()

    def pick(self, item=None):
        e = self.entry()
        self.details = None
        if e and e[0] == "exe":
            try:
                self.details = (e[1], check(e[1]))
            except Exception as ex:
                self.details = (e[1], {"error": str(ex)})

    def entry(self):
        i = self.list.selected
        return self.entries[i] if 0 <= i < len(self.entries) else None

    def run_selected(self, *args):
        e = self.entry()
        if not e:
            return
        from pywin import install
        if e[0] == "app":
            install.launch(e[1])
        elif e[0] == "exe":
            if install.is_installer(e[1]):
                self.install(e[1])
            else:
                self.run(e[1])

    def run(self, path):
        from pywin import host
        host.start(path)

    def ask_install(self):
        ui.ask("Instalar un programa de Windows", "Instalador (.exe), programa portable (.zip) o .exe:",
               "/disk/Descargas/", self.install)

    def install(self, path):
        from pywin import install
        self.message = "Instalando %s..." % path.rsplit("/", 1)[-1]
        self.redraw()

        def done(ok, msg):
            self.message = msg
            ui.toast(msg)
            self.refresh()
        install.install(path, done)

    def uninstall_selected(self):
        e = self.entry()
        prog = e[2] if e else None
        if prog is None:
            ui.toast("Elige un programa instalado")
            return
        from pywin import install

        def go():
            def done(ok, msg):
                self.message = msg
                ui.toast(msg)
                self.refresh()
            install.uninstall(prog, done)
        ui.confirm("Desinstalar", "Desinstalar %s?" % prog["name"], go)

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        surf.blit(icons.icon("pywin", 44), (12, 10))
        ui.text(surf, "PyWin", 66, 12, T.TEXT, ui.font(18, bold=True))
        ui.text(surf, "Programas de Windows (x64) en SnakeyOS: se instalan en C:\\Program Files y se abren desde "
                      "el lanzador.", 66, 36, T.MUTED, ui.font(11), self.win.w - 80)
        self.form.draw(surf)
        x = LIST_W + 32
        w = self.win.w - x - 12
        if self.message:
            ui.text(surf, self.message, x, self.win.h - 30, T.MUTED, ui.font(12), w)
        e = self.entry()
        if not e:
            ui.text(surf, "No hay programas instalados ni archivos .exe en Escritorio, Descargas o Documentos.",
                    x, 70, T.MUTED, max_w=w)
            return
        kind, a, prog = e
        y = 70
        if kind in ("app", "prog"):
            name = a["name"] if kind == "app" else prog["name"]
            surf.blit(icons.icon("exe", 56), (x, y))
            ui.text(surf, name, x + 70, y + 6, T.TEXT, ui.font(16, bold=True), w - 70)
            ui.text(surf, "Instalado", x + 70, y + 30, (40, 130, 70), ui.font(12))
            y += 74
            rows = []
            if kind == "app":
                rows.append(("Programa", _win(a["target"])))
            if prog:
                for label, key in (("Editor", "publisher"), ("Version", "version"), ("Carpeta", "location")):
                    if prog.get(key):
                        rows.append((label, prog[key]))
            for label, value in rows:
                ui.text(surf, label, x, y, T.MUTED)
                ui.text(surf, value, x + 100, y, T.TEXT, max_w=w - 100)
                y += 24
            return
        if not self.details:
            return
        path, d = self.details
        ui.text(surf, path.rsplit("/", 1)[-1], x, y, T.TEXT, ui.font(15, bold=True), w)
        y += 26
        ui.text(surf, path, x, y, T.MUTED, ui.font(11), w)
        y += 26
        if "error" in d:
            ui.text(surf, "No es un programa que PyWin pueda abrir: " + d["error"], x, y, (200, 60, 60), max_w=w)
            return
        from pywin import install
        rows = [("Tipo", "instalador" if install.is_installer(path) else
                 ("programa de consola" if d["console"] else "programa con ventanas")),
                ("Tamano", "%d KB" % (d["size"] // 1024)),
                ("DLL", ", ".join(d["dlls"])),
                ("Funciones", "%d de Windows" % d["imports"])]
        for label, value in rows:
            ui.text(surf, label, x, y, T.MUTED)
            ui.text(surf, value, x + 100, y, T.TEXT, max_w=w - 100)
            y += 24
        y += 8
        if d["missing"]:
            ui.text(surf, "Le faltan %d funciones (devolveran 0):" % len(d["missing"]), x, y, (200, 120, 30))
            y += 22
            for name in d["missing"][:7]:
                ui.text(surf, "  " + name, x, y, T.MUTED, ui.font(11), w)
                y += 17
        else:
            pygame.draw.circle(surf, (60, 170, 90), (x + 8, y + 9), 8)
            ui.text(surf, "PyWin tiene todas las funciones que usa", x + 24, y, (40, 130, 70))

    def event(self, ev, pos):
        return self.form.event(ev, pos)


def _host(win_path):
    from pywin.process import to_host
    return to_host(win_path)


def _win(path):
    from pywin.process import to_windows
    return to_windows(path)
