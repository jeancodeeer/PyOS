# Disks and installer: see the disks, their partitions, format them, and
# install the system on the hard disk.
import os
import pygame
from desktop import theme as T, ui
from desktop.wm import App


class Disks(App):
    title = "Discos e instalador"
    size = (620, 540)
    VOLUMES = (("/", "Sistema (memoria)"), ("/disk", "Disco duro"), ("/usb", "Memoria USB"))

    def __init__(self, win):
        App.__init__(self, win)
        from kernel import disktool
        self.dt = disktool
        self.disks = disktool.disks()
        self.form = ui.Form()
        self.list = self.form.add(ui.ListBox((8, 30, 300, 120), [disktool.describe(d) for d in self.disks], self.pick))
        self.view = self.form.add(ui.TextView((8, 300, 604, 150), []))
        self.form.add(ui.Button((320, 30, 290, 26), "Instalar PyKernel en /disk", self.install, primary=True))
        self.form.add(ui.Button((320, 62, 290, 26), "Crear particion FAT (borra todo)", self.ask_partition))
        self.confirm = self.form.add(ui.Button((320, 94, 290, 26), "Confirmar: BORRAR el disco", self.partition))
        self.confirm.visible = False
        self.log = []
        self.volumes = self.usage()
        self.pick(None)

    def usage(self):
        """(label, path, total bytes, free bytes) of each mounted volume."""
        out = []
        root = None
        for path, label in self.VOLUMES:
            try:
                st = os.statvfs(path)
            except (OSError, AttributeError):
                continue
            if path == "/":
                root = st
            elif st == root:                   # nothing mounted there: the system's own volume answered
                continue
            block = st[1] or st[0]
            if st[2]:
                out.append((label, path, st[2] * block, st[3] * block))
        return out

    def pick(self, item):
        i = self.list.selected
        if 0 <= i < len(self.disks):
            d = self.disks[i]
            self.view.lines = ["Disco: " + self.dt.describe(d), ""] + self.dt.table_text(d).split("\n") + [""] + self.log
        else:
            self.view.lines = ["No hay discos (IDE o SATA/AHCI)."]

    def say(self, s):
        self.log.append(s)
        self.pick(None)
        from desktop import wm
        wm.wm.draw()

    def install(self):
        from kernel import ata
        if ata.disk is None:
            self.say("no hay disco montado en /disk")
            return
        try:
            self.dt.install("/disk", self.say)
            self.say("listo: al arrancar, /disk/system/lib va primero en la ruta de import")
        except Exception as e:
            self.say("error: %s" % e)

    def ask_partition(self):
        self.confirm.visible = True

    def partition(self):
        self.confirm.visible = False
        i = self.list.selected
        if not 0 <= i < len(self.disks):
            return
        try:
            start, count = self.dt.partition(self.disks[i])
            self.say("particion creada: %d MiB desde el sector %d, formateada FAT" % (count >> 11, start))
            self.say("reinicia para montarla en /disk")
        except Exception as e:
            self.say("error: %s" % e)

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        ui.text(surf, "Discos", 8, 8, T.TEXT)
        ui.text(surf, "Espacio en los volumenes", 8, 160, T.TEXT)
        y = 184
        for label, path, total, free in self.volumes:
            used = total - free
            ui.text(surf, "%s  (%s)" % (label, path), 8, y, T.TEXT, ui.font(13))
            bar = pygame.Rect(200, y + 2, 260, 14)
            pygame.draw.rect(surf, T.BUTTON_HI, bar, 0, 4)
            share = used / float(total)
            color = T.RED if share > 0.9 else T.ACCENT
            pygame.draw.rect(surf, color, (bar.x, bar.y, int(bar.w * share), bar.h), 0, 4)
            ui.text(surf, "%s libres de %s" % (self.human(free), self.human(total)), 470, y, T.MUTED, ui.font(12))
            y += 26
        if not self.volumes:
            ui.text(surf, "ningun volumen montado", 8, y, T.MUTED)
        ui.text(surf, "Particiones y registro", 8, 280, T.TEXT)
        self.form.draw(surf)
        ui.text(surf, "Instalar copia /lib, /bin y /etc a /disk/system (sobrevive al apagado).", 8, self.win.h - 40,
                T.MUTED, max_w=self.win.w - 16)
        ui.text(surf, "El arranque sigue usando GRUB del CD/ISO.", 8, self.win.h - 22, T.MUTED)

    def human(self, n):
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return ("%d %s" if unit == "B" else "%.1f %s") % (n, unit)
            n /= 1024.0

    def event(self, ev, pos):
        return self.form.event(ev, pos)
