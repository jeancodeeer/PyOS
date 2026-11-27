# Videos: a video player. MP4 files (H.264 video + AAC sound, the usual
# kind from phones, cameras and the web) from /disk/Videos, /disk and USB
# sticks; MP3 and M4A songs too.
#
# Space: play / pause. Left / right: 5 seconds back / forward. F: the
# picture as big as the window allows (the list hides). Click the bar to jump.
import os
import pygame
from desktop import theme as T, ui
from desktop.wm import App

FOLDERS = ("/disk/Videos", "/disk/Descargas", "/disk", "/usb", "/share/videos")
KINDS = (".mp4", ".m4v", ".mov", ".m4a", ".mp3")
BAR_H = 64
LIST_W = 220


def _clock(t):
    t = int(max(0, t))
    return "%d:%02d:%02d" % (t // 3600, t // 60 % 60, t % 60) if t >= 3600 else "%d:%02d" % (t // 60, t % 60)


class Videos(App):
    title = "Videos"
    size = (900, 560)

    def __init__(self, win, path=None):
        App.__init__(self, win)
        try:
            from kernel import sound
            if sound.card is None:
                sound.init()
        except Exception:
            pass
        self.player = None
        self.message = ""
        self.big = False
        self.files = self.find_files()
        self.form = ui.Form()
        self.list = self.form.add(ui.ListBox((8, 8, LIST_W - 16, 100), [f.rsplit("/", 1)[-1] for f in self.files],
                                             None, lambda item: self.open(self.files[self.list.selected])))
        self.layout()
        if path:
            self.open(path)
        elif not self.files:
            self.message = "No hay videos en /disk/Videos. Abre un .mp4 desde Archivos o el navegador."

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

    def layout(self):
        self.list.rect = pygame.Rect(8, 8, LIST_W - 16, self.win.h - 16)
        self.list.visible = not self.big

    def resized(self, w, h):
        self.layout()

    def screen_rect(self):
        x = 0 if self.big else LIST_W
        return pygame.Rect(x, 0, self.win.w - x, self.win.h - BAR_H)

    # ---- playing ----
    def open(self, path):
        """A file, a web address (http...), or "youtube:VIDEO_ID"."""
        if self.player:
            self.player.close()
            self.player = None
        if path.startswith(("http://", "https://", "youtube:")):
            self.message = "Cargando..."             # the network can take a while: not in the desktop's loop
            import _thread
            _thread.start_new_thread(self._open_remote, (path,))
            self.redraw()
            return
        self._start(path)

    def _open_remote(self, path):
        from desktop import wm
        try:
            title = None
            if path.startswith("youtube:"):
                from media import youtube
                path, title = youtube.stream(path[8:])
            from media import player
            p = player.Player(path)
            if title:
                p.title = title
            wm.wm.later(lambda: self._started(p))
        except Exception as e:
            msg = "No se puede reproducir: %s" % e
            wm.wm.later(lambda: self._failed(msg))

    def _started(self, p):
        self.player = p
        p.play()
        self.message = p.error or ""
        self.redraw()

    def _failed(self, msg):
        self.message = msg
        self.redraw()

    def _start(self, path):
        try:
            from media import player
            self._started(player.Player(path))
        except Exception as e:
            self._failed("No se puede reproducir: %s" % e)

    def tick(self, now):
        p = self.player
        if p is None:
            return False
        try:
            changed = p.update()
        except Exception as e:
            self.message = "Error al reproducir: %r" % e
            p.playing = False
            return True
        return changed or p.playing and (now // 250) != getattr(self, "_last_q", None) and self._set_q(now)

    def _set_q(self, now):
        self._last_q = now // 250                         # the time label: four times a second
        return True

    def bar(self):
        return pygame.Rect(150, self.win.h - BAR_H + 14, self.win.w - 330, 10)

    def event(self, ev, pos):
        p = self.player
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_SPACE and p:
                p.toggle()
            elif ev.key == pygame.K_RIGHT and p:
                p.seek(p.clock() + 5)
            elif ev.key == pygame.K_LEFT and p:
                p.seek(p.clock() - 5)
            elif ev.key == pygame.K_f:
                self.big = not self.big
                self.layout()
            else:
                return self.form.event(ev, pos)
            self.redraw()
            return True
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and pos:
            if p and self.bar().inflate(0, 16).collidepoint(pos):
                b = self.bar()
                p.seek((pos[0] - b.x) / float(b.w) * p.duration)
                self.redraw()
                return True
            if pygame.Rect(16, self.win.h - BAR_H + 10, 44, 44).collidepoint(pos) and p:
                p.toggle()
                self.redraw()
                return True
            if pygame.Rect(68, self.win.h - BAR_H + 10, 44, 44).collidepoint(pos):
                self.big = not self.big
                self.layout()
                self.redraw()
                return True
            if self.screen_rect().collidepoint(pos) and p:
                p.toggle()
                self.redraw()
                return True
        return self.form.event(ev, pos)

    # ---- drawing ----
    def draw(self, surf):
        surf.fill(T.WIN_BG)
        if not self.big:
            pygame.draw.rect(surf, T.BUTTON, (0, 0, LIST_W, self.win.h))
        self.form.draw(surf)
        area = self.screen_rect()
        pygame.draw.rect(surf, (0, 0, 0), area)
        p = self.player
        if p and p.vdec:
            p.draw(surf, area)
        elif p and p.mp3 or p and p.audio and not p.vdec:
            f = ui.font(22, True)
            ui.text(surf, "♪ " + p.title, area.centerx, area.centery - 20, (230, 230, 240), f, area.w - 40, center=True)
            ui.text(surf, "solo sonido", area.centerx, area.centery + 16, (160, 160, 170), ui.font(14), center=True)
        if self.message:
            for k, line in enumerate(ui.wrap(self.message, area.w - 40, ui.font(14))[:4]):
                ui.text(surf, line, area.centerx, area.centery + 50 + 20 * k, (255, 200, 120), ui.font(14),
                        center=True)
        # controls
        y = self.win.h - BAR_H
        pygame.draw.rect(surf, T.BUTTON, (0, y, self.win.w, BAR_H))
        play = pygame.Rect(16, y + 10, 44, 44)
        ui.box(surf, play, T.ACCENT, None, 22)
        if p and p.playing:
            pygame.draw.rect(surf, (255, 255, 255), (play.x + 14, play.y + 12, 6, 20))
            pygame.draw.rect(surf, (255, 255, 255), (play.x + 24, play.y + 12, 6, 20))
        else:
            pygame.draw.polygon(surf, (255, 255, 255), [(play.x + 16, play.y + 11), (play.x + 16, play.y + 33),
                                                        (play.x + 34, play.y + 22)])
        big = pygame.Rect(68, y + 10, 44, 44)
        ui.box(surf, big, T.BUTTON_HI, None, 8)
        pygame.draw.rect(surf, T.TEXT, big.inflate(-22, -24), 2)
        b = self.bar()
        pygame.draw.rect(surf, T.BUTTON_HI, b, 0, 5)
        if p and p.duration:
            t = p.clock()
            done = int(b.w * min(1.0, t / p.duration))
            pygame.draw.rect(surf, T.ACCENT, (b.x, b.y, done, b.h), 0, 5)
            pygame.draw.circle(surf, T.ACCENT, (b.x + done, b.centery), 8)
            ui.text(surf, "%s / %s" % (_clock(t), _clock(p.duration)), b.right + 16, b.y - 3, T.TEXT, ui.font(13))
            ui.text(surf, p.title, b.x, b.y + 18, T.MUTED, ui.font(12), b.w)
        else:
            ui.text(surf, "Elige un video de la lista", b.x, b.y + 18, T.MUTED, ui.font(12))

    def close(self):
        if self.player:
            self.player.close()
        return True
