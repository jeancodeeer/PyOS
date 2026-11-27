# About PyKernel, and a launcher for JeanCode (a full-screen app).
import sys
import pygame
from desktop import theme as T, ui
from desktop.wm import App


class About(App):
    title = "Acerca de SnakeyOS"
    size = (500, 330)
    resizable = False

    def draw(self, surf):
        import pyos
        from pyos import logo
        from kernel import shell, mm
        surf.fill(T.WIN_BG)
        surf.blit(logo.surface(110), (24, 24))
        ui.text(surf, "SnakeyOS %s" % pyos.version(), 156, 34, T.TEXT, ui.font(24, bold=True))
        ui.text(surf, "Un sistema operativo hecho en Python", 156, 68, T.MUTED, ui.font(15))
        rows = ["Nucleo: PyKernel %s (Rust + MicroPython)" % pyos.kernel_version(),
                "Escritorio, apps y navegador: Python y pygame",
                "Motor: MicroPython %s" % sys.version.split()[0],
                "CPU: " + shell.cpu_name(), "RAM: %d MiB" % (mm.total_ram >> 20),
                "El codigo esta en /lib, /apps y /etc: abrelo con Archivos."]
        for i, r in enumerate(rows):
            ui.text(surf, r, 24, 156 + 24 * i, T.TEXT, max_w=self.win.w - 40)
