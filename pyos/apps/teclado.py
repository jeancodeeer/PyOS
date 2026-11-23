# pyos-app
# name: Teclado en pantalla
# icon: teclado
# mode: window
#
# A keyboard you click with the mouse. The keys go to the window you used
# last (the one under this one), as if they were typed.
import pygame
from desktop import theme as T, ui
from desktop.wm import App as Base

ROWS = [
    ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=", ("← Borrar", pygame.K_BACKSPACE, 2)],
    ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "[", "]", ("Enter", pygame.K_RETURN, 2)],
    [("Mayus", "shift", 1.5), "a", "s", "d", "f", "g", "h", "j", "k", "l", "ñ", ";", "'"],
    ["z", "x", "c", "v", "b", "n", "m", ",", ".", "/", ("↑", pygame.K_UP, 1), ("Tab", pygame.K_TAB, 1.5)],
    [("Esc", pygame.K_ESCAPE, 1.5), ("Espacio", pygame.K_SPACE, 7), ("←", pygame.K_LEFT, 1),
     ("↓", pygame.K_DOWN, 1), ("→", pygame.K_RIGHT, 1)],
]
KEY = 44


class App(Base):
    title = "Teclado en pantalla"
    size = (13 * (KEY + 4) + 70, 5 * (KEY + 6) + 30)

    def __init__(self, win):
        Base.__init__(self, win)
        self.shift = False
        self.pressed = None

    def target(self):
        from desktop import wm
        others = [w for w in wm.wm.windows if w is not self.win and not w.minimized]
        return others[-1] if others else None

    def keys(self):
        """(rect, key spec) for every key."""
        out = []
        for r, row in enumerate(ROWS):
            x = 12
            for spec in row:
                width = spec[2] if isinstance(spec, tuple) else 1
                w = int(KEY * width + 4 * (width - 1))
                out.append((pygame.Rect(x, 12 + r * (KEY + 6), w, KEY), spec))
                x += w + 4
        return out

    def draw(self, surf):
        surf.fill((228, 231, 238))
        f = ui.font(15)
        for rect, spec in self.keys():
            label = spec[0] if isinstance(spec, tuple) else (spec.upper() if self.shift else spec)
            on = (spec == ("Mayus", "shift", 1.5) and self.shift) or self.pressed == rect.topleft
            pygame.draw.rect(surf, T.ACCENT if on else (255, 255, 255), rect, 0, 8)
            pygame.draw.rect(surf, (200, 204, 212), rect, 1, 8)
            ui.text(surf, label, rect.centerx, rect.y + (KEY - f.get_height()) // 2, T.ACCENT_TEXT if on else T.TEXT, f,
                    rect.w - 6, center=True)
        t = self.target()
        ui.text(surf, "Escribe en: " + (t.title if t else "(ninguna ventana)"), 12, self.win.h - 22, T.MUTED,
                max_w=self.win.w - 24)

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONUP:
            self.pressed = None
            return True
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1 or pos is None:
            return False
        for rect, spec in self.keys():
            if rect.collidepoint(pos):
                self.pressed = rect.topleft
                self.press(spec)
                return True
        return False

    def press(self, spec):
        if spec == ("Mayus", "shift", 1.5):
            self.shift = not self.shift
            return
        if isinstance(spec, tuple):
            key, text = spec[1], {pygame.K_SPACE: " ", pygame.K_RETURN: "\r", pygame.K_TAB: "\t"}.get(spec[1], "")
        else:
            text = spec.upper() if self.shift else spec
            key = ord(spec) if len(spec) == 1 and ord(spec) < 128 else 0
            self.shift = False
        t = self.target()
        if t is None:
            return
        from desktop import wm
        ev = pygame.event.Event(pygame.KEYDOWN, key=key, unicode=text, mod=pygame.KMOD_SHIFT if text.isupper() else 0)
        wm.wm.send(t, ev)
