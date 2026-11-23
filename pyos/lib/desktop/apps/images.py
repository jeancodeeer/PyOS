# Images: view PNG, BMP, GIF and JPEG files, zoom with + and -, browse the
# folder with the arrow keys.
import os
import pygame
from desktop import theme as T, ui
from desktop.wm import App

EXT = (".png", ".bmp", ".gif", ".jpg", ".jpeg")


class Images(App):
    title = "Imagenes"
    size = (640, 480)

    def __init__(self, win, path=None):
        App.__init__(self, win)
        self.img = None
        self.zoom = 1.0
        self.msg = ""
        self.path = None
        self.bar = ui.Field((8, 6, 400, 22), path or "/share/images", self.open)
        self.open(path or "/share/images")      # no file given: the first picture of the folder

    def open(self, path):
        try:
            if os.stat(path)[0] & 0x4000:
                files = [n for n in sorted(os.listdir(path)) if n.lower().endswith(EXT)]
                if not files:
                    self.msg = "no hay imagenes en " + path
                    return
                path = path.rstrip("/") + "/" + files[0]
            self.path = path
            self.bar.set(path)
            self.img = load_any(path)
            self.zoom = 1.0
            self.scaled = self.img
            w, h = self.img.get_size()
            self.msg = "%s  %dx%d" % (path.rsplit("/", 1)[-1], w, h)
            self.win.set_title("Imagenes - " + path.rsplit("/", 1)[-1])
        except Exception as e:
            self.msg = "no se pudo abrir: %s" % e
            self.img = None

    def step(self, d):
        if not self.path:
            return
        folder = self.path.rsplit("/", 1)[0] or "/"
        files = [n for n in sorted(os.listdir(folder)) if n.lower().endswith(EXT)]
        name = self.path.rsplit("/", 1)[-1]
        if name in files:
            self.open(folder + "/" + files[(files.index(name) + d) % len(files)])

    def set_zoom(self, z):
        if not self.img:
            return
        self.zoom = max(0.1, min(8.0, z))
        w, h = self.img.get_size()
        self.scaled = pygame.transform.scale(self.img, (max(1, int(w * self.zoom)), max(1, int(h * self.zoom))))

    def draw(self, surf):
        surf.fill((40, 42, 48))
        self.bar.rect.w = self.win.w - 16
        if self.img:
            iw, ih = self.scaled.get_size()
            surf.blit(self.scaled, ((self.win.w - iw) // 2, 34 + (self.win.h - 58 - ih) // 2))
        pygame.draw.rect(surf, T.WIN_BG, (0, 0, self.win.w, 32))
        self.bar.draw(surf)
        ui.text(surf, self.msg + "   (+/- zoom, flechas: anterior/siguiente)", 8, self.win.h - 20, (200, 204, 212),
                max_w=self.win.w - 16)

    def event(self, ev, pos):
        if self.bar.event(ev, pos):
            return True
        if ev.type == pygame.KEYDOWN:
            if ev.unicode == "+":
                self.set_zoom(self.zoom * 1.25)
            elif ev.unicode == "-":
                self.set_zoom(self.zoom / 1.25)
            elif ev.key == pygame.K_RIGHT:
                self.step(1)
            elif ev.key == pygame.K_LEFT:
                self.step(-1)
            else:
                return False
            return True
        return False


def load_any(path):
    low = path.lower()
    if low.endswith((".jpg", ".jpeg")):
        from imaging import jpeg
        return jpeg.load(path)
    if low.endswith(".gif"):
        from imaging import gif
        return gif.load(path)
    return pygame.image.load(path)
