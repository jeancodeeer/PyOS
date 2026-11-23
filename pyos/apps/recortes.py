# pyos-app
# name: Recortes
# icon: recortes
# mode: window
#
# Screenshots: the whole screen, or the window behind this one, now or after a
# few seconds. Pictures are saved as BMP in /disk/Imagenes.
import os
import time
import pygame
from desktop import theme as T, ui
from desktop.wm import App as Base

FOLDER = "/disk/Imagenes"


class App(Base):
    title = "Recortes"
    size = (560, 400)

    def __init__(self, win):
        Base.__init__(self, win)
        self.delay = 0
        self.pending = None           # (when, what)
        self.shot = None              # the last picture, scaled for the preview
        self.path = None
        self.form = ui.Form()
        self.form.add(ui.Button((16, 14, 170, 34), "Pantalla completa", lambda: self.start("screen"), primary=True))
        self.form.add(ui.Button((194, 14, 170, 34), "Ventana de atras", lambda: self.start("window")))
        self.delay_btn = self.form.add(ui.Button((372, 14, 170, 34), "Retardo: no", self.cycle_delay))
        self.form.add(ui.Button((16, self.win.h - 46, 170, 32), "Abrir en Imagenes", self.open_image))

    def cycle_delay(self):
        self.delay = {0: 3, 3: 5, 5: 0}[self.delay]
        self.delay_btn.label = "Retardo: %s" % ("%d s" % self.delay if self.delay else "no")

    def start(self, what):
        from desktop import wm
        self.target = None
        if what == "window":
            others = [w for w in wm.wm.windows if w is not self.win and not w.minimized]
            if not others:
                ui.toast("no hay otra ventana abierta")
                return
            self.target = others[-1]
        self.win.minimized = True                       # out of the picture
        self.pending = time.ticks_ms() + max(400, self.delay * 1000)
        wm.wm.dirty = True

    def tick(self, now):
        if self.pending is None or now < self.pending:
            return False
        from desktop import wm, theme
        self.pending = None
        w = wm.wm
        w.draw()                                        # a fresh frame without this window
        if self.target is not None:
            t = self.target
            rect = pygame.Rect(t.x, t.y, t.w, t.h + theme.TITLE_H).clip(w.screen.get_rect())
            picture = pygame.Surface(rect.size)
            picture.blit(w.screen, (0, 0), rect)
        else:
            picture = w.screen.copy()
        try:
            os.mkdir(FOLDER)
        except OSError:
            pass
        n = 1
        while _exists("%s/Captura %d.bmp" % (FOLDER, n)):
            n += 1
        self.path = "%s/Captura %d.bmp" % (FOLDER, n)
        pygame.image.save(picture, self.path)
        pw, ph = picture.get_size()
        scale = min((self.win.w - 32) / pw, (self.win.h - 120) / ph)
        self.shot = pygame.transform.scale(picture, (int(pw * scale), int(ph * scale)))
        self.win.minimized = False
        w.focus(self.win)
        try:
            from kernel import sound
            if sound.card:
                sound.play_wav("/share/sounds/clic.wav")
        except Exception:
            pass
        return True

    def open_image(self):
        if self.path:
            from desktop import wm
            wm.wm.launch("images", self.path)

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        self.form.draw(surf)
        area = pygame.Rect(16, 60, self.win.w - 32, self.win.h - 120)
        pygame.draw.rect(surf, (230, 232, 238), area, 0, 10)
        if self.shot:
            surf.blit(self.shot, (area.centerx - self.shot.get_width() // 2, area.centery - self.shot.get_height() // 2))
            ui.text(surf, "Guardada en " + self.path, 196, self.win.h - 38, T.MUTED, max_w=self.win.w - 210)
        else:
            ui.text(surf, "Elige que capturar", area.centerx, area.centery - 8, T.MUTED, ui.font(15), center=True)

    def event(self, ev, pos):
        return self.form.event(ev, pos)


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False
