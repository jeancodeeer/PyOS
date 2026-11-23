# pyos-app
# name: Lupa
# icon: lupa
# mode: window
#
# Shows what is around the mouse pointer, bigger. + and - change the zoom.
import pygame
from desktop import theme as T, ui
from desktop.wm import App as Base


class App(Base):
    title = "Lupa"
    size = (420, 300)

    def __init__(self, win):
        Base.__init__(self, win)
        self.zoom = 3
        self.last = None

    def tick(self, now):
        from desktop import wm
        m = wm.wm.mouse
        if m != self.last:
            self.last = m
            return True
        return False

    def draw(self, surf):
        from desktop import wm
        scr = wm.wm.screen
        w, h = self.win.w, self.win.h - 24
        sw, sh = w // self.zoom, h // self.zoom
        mx, my = wm.wm.mouse
        area = pygame.Rect(mx - sw // 2, my - sh // 2, sw, sh).clamp(scr.get_rect())
        piece = pygame.Surface((sw, sh))
        piece.blit(scr, (0, 0), area)
        surf.blit(pygame.transform.scale(piece, (sw * self.zoom, sh * self.zoom)), (0, 0))
        pygame.draw.rect(surf, (240, 242, 246), (0, h, w, 24))
        ui.text(surf, "Aumento x%d   (+ / - para cambiar)   puntero en %d, %d" % (self.zoom, mx, my), 8, h + 4, T.MUTED)

    def event(self, ev, pos):
        if ev.type == pygame.KEYDOWN and ev.unicode in ("+", "-"):
            self.zoom = max(2, min(8, self.zoom + (1 if ev.unicode == "+" else -1)))
            return True
        return False
