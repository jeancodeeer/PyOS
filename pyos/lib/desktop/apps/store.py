# Store: SnakeyOS apps (.py files) and Python packages.
#
# An app is one .py file with a '# pyos-app' header (see desktop/apps).
# Install one from a URL or a file (a USB stick, say): it goes to
# /disk/apps and shows up in the launcher. Plain pygame games are welcome
# too: they get a header and run full screen.
import pygame
from desktop import theme as T, ui, icons
from desktop.wm import App


class Store(App):
    title = "Tienda"
    size = (700, 460)

    def __init__(self, win):
        App.__init__(self, win)
        self.tab = 0
        self.msg = ""
        self.build()

    def build(self):
        f = self.form = ui.Form()
        for i, name in enumerate(("Apps de SnakeyOS", "Paquetes de Python")):
            b = f.add(ui.Button((16 + 170 * i, 12, 160, 30), name, lambda i=i: self.set_tab(i)))
            b.primary = i == self.tab
        if self.tab == 0:
            self.source = f.add(ui.Field((16, 58, self.win.w - 160, 32), "", self.install_app,
                                         placeholder="URL o ruta de un .py (https://.../juego.py, /usb/app.py)"))
            f.add(ui.Button((self.win.w - 136, 58, 120, 32), "Instalar", lambda: self.install_app(self.source.text), primary=True))
            self.list = f.add(ui.ListBox((16, 104, self.win.w - 32, self.win.h - 190), [], None, self.open_app, row_h=40))
            f.add(ui.Button((16, self.win.h - 74, 120, 30), "Abrir", lambda: self.open_app(self.current())))
            f.add(ui.Button((144, self.win.h - 74, 140, 30), "Desinstalar", self.uninstall))
            self.fill_apps()
        else:
            self.query = f.add(ui.Field((16, 58, self.win.w - 160, 32), "", self.search,
                                        placeholder="Buscar en micropython-lib (json, base64, pystone...)"))
            f.add(ui.Button((self.win.w - 136, 58, 120, 32), "Buscar", lambda: self.search(self.query.text), primary=True))
            self.list = f.add(ui.ListBox((16, 104, self.win.w - 32, self.win.h - 190), []))
            f.add(ui.Button((16, self.win.h - 74, 120, 30), "Instalar", self.install_pkg, primary=True))
            f.add(ui.Button((144, self.win.h - 74, 140, 30), "Instalados", self.show_installed))
            self.show_installed()

    def set_tab(self, i):
        self.tab = i
        self.msg = ""
        self.build()

    def resized(self, w, h):
        self.build()

    # ---- SnakeyOS apps ----
    def fill_apps(self):
        from desktop import apps
        apps.scan()
        rows = []
        for name, meta in sorted(apps.app_files().items()):
            where = "instalada por ti" if meta["path"].startswith("/disk/") else "del sistema"
            mode = "pantalla completa" if meta["mode"] == "fullscreen" else "ventana"
            rows.append((meta["label"], name, "%s  •  %s" % (where, mode)))
        self.list.set_items(rows)

    def current(self):
        if 0 <= self.list.selected < len(self.list.items):
            return self.list.items[self.list.selected]
        return None

    def open_app(self, item):
        if item:
            from desktop import wm
            wm.wm.launch(item[1])

    def install_app(self, source):
        from desktop import apps
        source = source.strip()
        if not source:
            return
        try:
            name = apps.install(source)
            self.msg = "instalada: %s (ya esta en el lanzador)" % name
            self.fill_apps()
        except Exception as e:
            self.msg = "no se pudo instalar: %s" % e

    def uninstall(self):
        from desktop import apps
        item = self.current()
        if not item:
            return
        try:
            apps.uninstall(item[1])
            self.msg = "desinstalada: " + item[0]
            self.fill_apps()
        except Exception as e:
            self.msg = str(e)

    # ---- Python packages (kernel/pkg.py) ----
    def search(self, text):
        from kernel import pkg
        try:
            found = pkg.search(text.strip())
            self.list.set_items([(n, n, v) for n, v, d in found[:300]])
            self.msg = "%d paquetes" % len(found)
        except Exception as e:
            self.msg = "sin acceso al indice: %s" % e

    def show_installed(self):
        from kernel import pkg
        items = sorted(pkg.installed().items())
        self.list.set_items([(n, n, e["version"]) for n, e in items] or [("(nada instalado todavia)", None, "")])

    def install_pkg(self):
        from kernel import pkg
        item = self.current()
        name = item[1] if item else self.query.text.strip()
        if not name:
            return
        try:
            self.msg = "instalado %s: %d archivos en /disk/lib" % (name, len(pkg.install(name)))
        except Exception as e:
            self.msg = "no se pudo instalar %s: %s" % (name, e)

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        self.form.draw(surf)
        ui.text(surf, self.msg or ("Las apps de SnakeyOS son archivos .py con pygame" if self.tab == 0 else ""),
                300, self.win.h - 68, T.MUTED, max_w=self.win.w - 316)

    def event(self, ev, pos):
        return self.form.event(ev, pos)
