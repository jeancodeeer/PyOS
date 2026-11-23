# Music: play WAV files from /share/sounds and /disk, with a level meter.
import os
import time
import struct
import pygame
from desktop import theme as T, ui
from desktop.wm import App

FOLDERS = ("/share/sounds", "/disk", "/disk/Musica", "/usb")


class Music(App):
    title = "Musica"
    size = (560, 380)

    def __init__(self, win, path=None):
        App.__init__(self, win)
        from kernel import sound
        self.sound = sound
        if sound.card is None:
            sound.init()
        self.files = []
        for d in FOLDERS:
            try:
                for n in sorted(os.listdir(d)):
                    if n.lower().endswith(".wav"):
                        self.files.append(d + "/" + n)
            except OSError:
                pass
        self.form = ui.Form()
        self.list = self.form.add(ui.ListBox((16, 16, 260, 300), [f.rsplit("/", 1)[-1] for f in self.files],
                                             None, lambda item: self.play()))
        self.form.add(ui.Button((296, 230, 110, 34), "Reproducir", self.play, primary=True))
        self.form.add(ui.Button((414, 230, 110, 34), "Detener", self.stop))
        self.form.add(ui.Button((296, 276, 50, 30), "-", lambda: self.set_volume(-10)))
        self.form.add(ui.Button((474, 276, 50, 30), "+", lambda: self.set_volume(10)))
        self.volume = 80
        self.now = None
        self.pcm = None
        self.started = 0
        if path:
            self.files.insert(0, path)
            self.list.set_items([f.rsplit("/", 1)[-1] for f in self.files])
            self.play()

    def play(self):
        if not self.files or self.list.selected < 0:
            return
        path = self.files[self.list.selected]
        try:
            self.pcm, self.rate, self.channels, self.bits = self.sound.read_wav(path)
            self.sound.play(self.pcm, self.rate, self.channels, self.bits)
            self.now = path.rsplit("/", 1)[-1]
            self.started = time.ticks_ms()
        except Exception as e:
            self.now = "no se pudo: %s" % e

    def stop(self):
        self.sound.stop()

    def set_volume(self, d):
        self.volume = max(0, min(100, self.volume + d))
        self.sound.volume(self.volume)

    def levels(self):
        """Loudness of 16 slices of the sound around what is playing now."""
        if not self.pcm or not self.sound.busy():
            return [0] * 16
        frame = self.channels * self.bits // 8
        pos = int((time.ticks_ms() - self.started) * self.rate / 1000) * frame
        out = []
        for k in range(16):
            i = pos + k * 64 * frame
            if i + 2 > len(self.pcm):
                out.append(0)
                continue
            v = struct.unpack_from("<h", self.pcm, i)[0] if self.bits == 16 else (self.pcm[i] - 128) * 256
            out.append(min(1.0, abs(v) / 20000))
        return out

    def tick(self, now):
        return self.sound.busy() or bool(self.now and not self.sound.busy() and self.started)

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        self.form.draw(surf)
        x = 296
        pygame.draw.rect(surf, (30, 32, 44), (x, 16, 228, 150), 0, 12)
        for i, lv in enumerate(self.levels()):
            h = int(8 + lv * 120)
            c = (90 + i * 9, 140, 255 - i * 6)
            pygame.draw.rect(surf, c, (x + 10 + i * 13, 160 - h, 9, h), 0, 3)
        if self.sound.card is None:
            ui.text(surf, "No hay tarjeta de sonido", x + 114, 80, (220, 224, 232), center=True)
        f = ui.font(15, bold=True)
        ui.text(surf, self.now or "Elige un sonido", x, 180, T.TEXT, f, 228)
        ui.text(surf, "sonando" if self.sound.busy() else "detenido", x, 202, T.MUTED)
        ui.text(surf, "volumen %d%%" % self.volume, x + 114, 282, T.TEXT, center=True)

    def event(self, ev, pos):
        return self.form.event(ev, pos)

    def close(self):
        self.sound.stop()
        return True
