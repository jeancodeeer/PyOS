# Calculator: buttons or the keyboard; any Python expression with math works.
import math
import pygame
from desktop import theme as T, ui
from desktop.wm import App

KEYS = ["7", "8", "9", "/", "sqrt", "4", "5", "6", "*", "(", "1", "2", "3", "-", ")",
        "0", ".", "C", "+", "=", "pi", "**", "%", "<-", "ans"]


class Calculator(App):
    title = "Calculadora"
    size = (300, 330)
    resizable = False

    def __init__(self, win):
        App.__init__(self, win)
        self.expr = ""
        self.result = "0"
        self.ans = 0
        self.form = ui.Form()
        for i, k in enumerate(KEYS):
            x, y = 8 + (i % 5) * 57, 80 + (i // 5) * 48
            self.form.add(ui.Button((x, y, 52, 42), k, lambda k=k: self.press(k), primary=k == "="))

    def press(self, k):
        if k == "C":
            self.expr, self.result = "", "0"
        elif k == "<-":
            self.expr = self.expr[:-1]
        elif k == "=":
            try:
                env = {n: getattr(math, n) for n in dir(math) if not n.startswith("_")}
                env["ans"] = self.ans
                v = eval(self.expr.replace("^", "**"), env)
                self.ans = v
                self.result = ("%.12g" % v) if isinstance(v, float) else str(v)
            except Exception as e:
                self.result = "error"
        elif k == "sqrt":
            self.expr += "sqrt("
        else:
            self.expr += k

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        ui.frame(surf, (8, 8, 284, 60))
        ui.text(surf, self.expr[-34:], 14, 14, T.MUTED)
        r = self.result[-34:]
        ui.text(surf, r, 286 - ui.width(r), 42, T.TEXT)
        self.form.draw(surf)

    def event(self, ev, pos):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_RETURN:
                self.press("=")
            elif ev.key == pygame.K_BACKSPACE:
                self.press("<-")
            elif ev.key == pygame.K_ESCAPE:
                self.press("C")
            elif ev.unicode and ev.unicode in "0123456789+-*/().%^abcdefghijklmnopqrstuvwxyz,":
                self.expr += ev.unicode
            else:
                return False
            return True
        return self.form.event(ev, pos)
