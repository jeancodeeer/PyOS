# Disks and installer: see the disks, their partitions, format them, and
# install the system on the hard disk.
import pygame
from desktop import theme as T, ui
from desktop.wm import App


class Disks(App):
    title = "Discos e instalador"
    size = (620, 420)

    def __init__(self, win):
        App.__init__(self, win)
        from kernel import disktool
        self.dt = disktool
        self.disks = disktool.disks()
        self.form = ui.Form()
        self.list = self.form.add(ui.ListBox((8, 30, 300, 120), [disktool.describe(d) for d in self.disks], self.pick))
        self.view = self.form.add(ui.TextView((8, 180, 604, 150), []))
        self.form.add(ui.Button((320, 30, 290, 26), "Instalar PyKernel en /disk", self.install, primary=True))
        self.form.add(ui.Button((320, 62, 290, 26), "Crear particion FAT (borra todo)", self.ask_partition))
        self.confirm = self.form.add(ui.Button((320, 94, 290, 26), "Confirmar: BORRAR el disco", self.partition))
        self.confirm.visible = False
        self.log = []
        self.pick(None)

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
        ui.text(surf, "Particiones y registro", 8, 160, T.TEXT)
        self.form.draw(surf)
        ui.text(surf, "Instalar copia /lib, /bin y /etc a /disk/system (sobrevive al apagado).", 8, self.win.h - 40,
                T.MUTED, max_w=self.win.w - 16)
        ui.text(surf, "El arranque sigue usando GRUB del CD/ISO.", 8, self.win.h - 22, T.MUTED)

    def event(self, ev, pos):
        return self.form.event(ev, pos)
