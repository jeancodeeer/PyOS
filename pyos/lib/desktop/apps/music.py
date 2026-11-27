# Musica: a music player. MP3, M4A (AAC) and WAV songs from the Musica
# folder, the disk and USB sticks: a list, play / pause, previous / next,
# a bar to jump in the song, shuffle and repeat, and the volume.
#
# MP3 and M4A are decoded by the kernel's media module (machine code);
# WAV files are played as they are.
import os
import time
import pygame
from desktop import theme as T, ui
from desktop.wm import App

FOLDERS = ("/disk/Musica", "/disk", "/disk/Descargas", "/usb", "/share/sounds")
KINDS = (".mp3", ".m4a", ".wav")


def _clock(t):
    t = int(max(0, t))
    return "%d:%02d" % (t // 60, t % 60)


class WavSong:
    """A WAV file with the same controls as media.player.Player."""

    def __init__(self, sound, path):
        self.sound, self.path = sound, path
        self.pcm, self.rate, self.channels, self.bits = sound.read_wav(path)
        self.frame = self.channels * self.bits // 8
        self.duration = len(self.pcm) / float(self.frame * self.rate)
        self.base, self.started, self.playing, self.ended = 0.0, 0, False, False
        self.title = path.rsplit("/", 1)[-1]

    def clock(self):
        if not self.playing:
            return self.base
        return self.base + time.ticks_diff(time.ticks_ms(), self.started) / 1000.0

    def play(self):
        if self.ended:
            self.base, self.ended = 0.0, False
        start = int(self.base * self.rate) * self.frame
        self.sound.play(self.pcm[start:], self.rate, self.channels, self.bits)
        self.started, self.playing = time.ticks_ms(), True

    def pause(self):
        self.base = self.clock()
        self.playing = False
        self.sound.stop()

    def toggle(self):
        self.pause() if self.playing else self.play()

    def seek(self, t):
        was = self.playing
        self.sound.stop()
        self.base = max(0.0, min(t, self.duration))
        self.playing = False
        if was:
            self.play()

    def update(self):
        if self.playing and self.clock() >= self.duration:
            self.playing, self.ended, self.base = False, True, self.duration
        return False

    def close(self):
        self.sound.stop()


class Music(App):
    title = "Musica"
    size = (720, 460)

    def __init__(self, win, path=None):
        App.__init__(self, win)
        from kernel import sound
        self.sound = sound
        if sound.card is None:
            sound.init()
        self.files = self.find_files()
        if path and path not in self.files:
            self.files.insert(0, path)
        self.song = None
        self.index = -1
        self.shuffle = False
        self.repeat = False
        self.message = ""
        from pyos import settings
        self.volume = settings.get("volumen")
        self.form = ui.Form()
        self.list = self.form.add(ui.ListBox((12, 12, 300, self.win.h - 24), [self.label(f) for f in self.files],
                                             None, lambda item: self.play_index(self.list.selected)))
        x = 330
        self.form.add(ui.Button((x, 300, 50, 36), "|◀", self.previous))
        self.form.add(ui.Button((x + 58, 300, 80, 36), "▶ / ❚❚", self.toggle, primary=True))
        self.form.add(ui.Button((x + 146, 300, 50, 36), "▶|", self.next))
        self.form.add(ui.Button((x + 214, 300, 80, 36), "Aleatorio", self.flip_shuffle))
        self.form.add(ui.Button((x + 302, 300, 74, 36), "Repetir", self.flip_repeat))
        self.form.add(ui.Button((x, 380, 40, 30), "-", lambda: self.set_volume(-10)))
        self.form.add(ui.Button((x + 150, 380, 40, 30), "+", lambda: self.set_volume(10)))
        if path:
            self.play_index(self.files.index(path))
        elif not self.files:
            self.message = "Copia canciones (.mp3, .m4a, .wav) en Documentos > Musica"

    def find_files(self):
        out = []
        for d in FOLDERS:
            try:
                for n in sorted(os.listdir(d)):
                    if n.lower().endswith(KINDS):
                        out.append(d.rstrip("/") + "/" + n)
            except OSError:
                pass
        return out

    def label(self, path):
        name = path.rsplit("/", 1)[-1]
        return name.rsplit(".", 1)[0]

    # ---- playing ----
    def play_index(self, i):
        if not 0 <= i < len(self.files):
            return
        if self.song:
            self.song.close()
            self.song = None
        self.index = i
        self.list.selected = i
        path = self.files[i]
        try:
            if path.lower().endswith(".wav"):
                self.song = WavSong(self.sound, path)
            else:
                from media import player
                self.song = player.Player(path)
            self.song.play()
            self.message = ""
        except Exception as e:
            self.message = "No se puede reproducir %s: %s" % (path.rsplit("/", 1)[-1], e)
        self.redraw()

    def toggle(self):
        if self.song:
            self.song.toggle()
        elif self.files:
            self.play_index(max(0, self.list.selected if self.list.selected is not None else 0))

    def next(self):
        if not self.files:
            return
        if self.shuffle:
            import random
            self.play_index(random.randrange(len(self.files)))
        else:
            self.play_index((self.index + 1) % len(self.files))

    def previous(self):
        if self.song and self.song.clock() > 3:
            self.song.seek(0)                          # like other players: back to the start first
        elif self.files:
            self.play_index((self.index - 1) % len(self.files))

    def flip_shuffle(self):
        self.shuffle = not self.shuffle

    def flip_repeat(self):
        self.repeat = not self.repeat

    def set_volume(self, d):
        from pyos import settings
        self.volume = max(0, min(100, self.volume + d))
        settings.set("volumen", self.volume)

    def tick(self, now):
        s = self.song
        if s is None:
            return False
        try:
            s.update()
        except Exception as e:
            self.message = "Error: %r" % e
            s.playing = False
        if s.ended:
            if self.repeat:
                self.play_index(self.index)
            elif self.index + 1 < len(self.files) or self.shuffle:
                self.next()
            else:
                s.ended = False
                s.base = 0.0
            return True
        return s.playing and (now // 500) != getattr(self, "_q", None) and self._mark(now)

    def _mark(self, now):
        self._q = now // 500
        return True

    def bar(self):
        return pygame.Rect(330, 250, self.win.w - 350, 8)

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and pos and self.song and \
                self.bar().inflate(0, 16).collidepoint(pos):
            b = self.bar()
            self.song.seek((pos[0] - b.x) / float(b.w) * self.song.duration)
            self.redraw()
            return True
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_SPACE:
            self.toggle()
            return True
        return self.form.event(ev, pos)

    # ---- drawing ----
    def draw(self, surf):
        surf.fill(T.WIN_BG)
        x = 330
        cover = pygame.Rect(x, 12, 180, 180)
        pygame.draw.rect(surf, (40, 44, 70), cover, 0, 14)
        t = time.ticks_ms() / 300.0
        playing = self.song and self.song.playing
        for k in range(12):                            # a little animation while it plays
            import math
            h = int(20 + (45 * abs(math.sin(t + k * 0.7)) if playing else 10))
            pygame.draw.rect(surf, (120 + k * 10, 120, 255 - k * 8), (cover.x + 18 + k * 13, cover.bottom - 20 - h, 9, h), 0, 3)
        ui.text(surf, "♪", cover.centerx, cover.y + 30, (230, 230, 250), ui.font(40, True), center=True)
        s = self.song
        title = s.title.rsplit(".", 1)[0] if s else "Elige una cancion"
        ui.text(surf, title, x + 196, 40, T.TEXT, ui.font(18, True), self.win.w - x - 210)
        folder = self.files[self.index].rsplit("/", 1)[0] if s and 0 <= self.index < len(self.files) else ""
        ui.text(surf, folder, x + 196, 68, T.MUTED, ui.font(13), self.win.w - x - 210)
        ui.text(surf, ("sonando" if playing else "en pausa") if s else "", x + 196, 92, T.ACCENT, ui.font(13))
        ui.text(surf, "%d canciones" % len(self.files), x + 196, 116, T.MUTED, ui.font(12))
        if self.sound.card is None:
            ui.text(surf, "No hay tarjeta de sonido", x + 196, 140, T.RED, ui.font(13))
        b = self.bar()
        pygame.draw.rect(surf, T.BUTTON_HI, b, 0, 4)
        if s and s.duration:
            pos = s.clock()
            done = int(b.w * min(1.0, pos / s.duration))
            pygame.draw.rect(surf, T.ACCENT, (b.x, b.y, done, b.h), 0, 4)
            pygame.draw.circle(surf, T.ACCENT, (b.x + done, b.centery), 7)
            ui.text(surf, _clock(pos), b.x, b.y + 14, T.MUTED, ui.font(12))
            right = _clock(s.duration)
            ui.text(surf, right, b.right - ui.width(right, ui.font(12)), b.y + 14, T.MUTED, ui.font(12))
        self.form.draw(surf)
        ui.text(surf, "volumen %d%%" % self.volume, x + 95, 386, T.TEXT, ui.font(13), center=True)
        flags = ("aleatorio" if self.shuffle else "") + ("  repetir" if self.repeat else "")
        ui.text(surf, flags.strip(), x + 214, 346, T.ACCENT, ui.font(12))
        if self.message:
            ui.text(surf, self.message, x, self.win.h - 24, T.RED, ui.font(12), self.win.w - x - 12)

    def close(self):
        if self.song:
            self.song.close()
        return True
