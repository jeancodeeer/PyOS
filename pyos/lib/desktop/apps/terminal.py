# Terminal: the Python console, in a window. Shell commands (ls, ps, ping,
# wget...) work here as at the text console; blocks ending in ':' continue
# on the next lines until an empty one.
import sys
import _kernel
import pygame
from desktop import theme as T, ui, clipboard
from desktop.wm import App


def CW():
    return ui.MONO().size("M")[0]          # every character of the mono font is this wide


def LH():
    return ui.MONO().get_height() + 1


class Terminal(App):
    title = "Terminal"
    icon = "terminal"
    size = (680, 420)

    def __init__(self, win, cwd=None):
        App.__init__(self, win)
        self.lines = ["PyKernel terminal - Python %s. Escribe help para ver los comandos." % sys.version.split()[0], ""]
        self.input = ""
        self.cursor = 0
        self.block = []
        self.history = []
        self.hpos = 0
        self.top = None
        import kernel.shell
        self.ns = {"__name__": "__main__"}
        exec("from kernel.shell import *", self.ns)
        if cwd:
            import os
            os.chdir(cwd)

    def prompt(self):
        return "... " if self.block else ">>> "

    def cols(self):
        return max(10, (self.win.w - 12) // CW())

    def rows(self):
        return max(2, (self.win.h - 8) // LH())

    def out(self, s):
        for line in s.replace("\r", "").split("\n"):
            while True:
                self.lines.append(line[:self.cols()])
                line = line[self.cols():]
                if not line:
                    break
        if len(self.lines) > 1500:
            self.lines = self.lines[-1000:]

    def draw(self, surf):
        surf.fill(T.DARK_BG)
        rows = self.rows()
        shown = self.lines + [self.prompt() + self.input]
        start = max(0, len(shown) - rows) if self.top is None else self.top
        for i, line in enumerate(shown[start:start + rows]):
            color = (150, 220, 150) if line.startswith((">>> ", "... ")) else T.DARK_TEXT
            ui.text(surf, line, 6, 4 + i * LH(), color, ui.MONO())
        if self.top is None or start + rows >= len(shown):
            y = 4 + (len(shown[start:start + rows]) - 1) * LH()
            x = 6 + (4 + self.cursor) * CW()
            pygame.draw.rect(surf, (150, 220, 150), (x, y + LH() - 4, CW(), 2))

    def run(self, source):
        chunks = []
        old = _kernel.stdout_hook(chunks.append)
        try:
            try:
                code = compile(source, "<terminal>", "eval")
                result = eval(code, self.ns)
                if result is not None:
                    self.ns["_"] = result
                    print(repr(result))
            except SyntaxError:
                exec(compile(source, "<terminal>", "exec"), self.ns)
        except SystemExit:
            self.win and __import__("desktop.wm").wm.wm.close(self.win)
        except BaseException as e:
            sys.print_exception(e)
        finally:
            _kernel.stdout_hook(old)
        text = b"".join(chunks).decode("utf-8", "replace")
        if text.endswith("\n"):
            text = text[:-1]
        if text:
            self.out(_strip_ansi(text))

    def submit(self):
        line = self.input
        self.out(self.prompt() + line)
        self.input, self.cursor, self.top = "", 0, None
        if line.strip():
            self.history.append(line)
        self.hpos = len(self.history)
        if self.block:
            if line.strip():
                self.block.append(line)
                return
            source = "\n".join(self.block)
            self.block = []
            self.run(source)
            return
        if line.rstrip().endswith(":"):
            self.block = [line]
            return
        if line.strip() in ("cls", "clear"):
            self.lines = []
            return
        if line.strip():
            self.run(line)

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (4, 5):
            start = max(0, len(self.lines) + 1 - self.rows()) if self.top is None else self.top
            self.top = max(0, start + (-3 if ev.button == 4 else 3))
            if self.top >= len(self.lines) + 1 - self.rows():
                self.top = None
            return True
        if ev.type != pygame.KEYDOWN:
            return False
        k = ev.key
        if k == pygame.K_RETURN:
            self.submit()
        elif k == pygame.K_BACKSPACE:
            if self.cursor:
                self.input = self.input[:self.cursor - 1] + self.input[self.cursor:]
                self.cursor -= 1
        elif k == pygame.K_LEFT:
            self.cursor = max(0, self.cursor - 1)
        elif k == pygame.K_RIGHT:
            self.cursor = min(len(self.input), self.cursor + 1)
        elif k == pygame.K_HOME:
            self.cursor = 0
        elif k == pygame.K_END:
            self.cursor = len(self.input)
        elif k == pygame.K_UP and self.history:
            self.hpos = max(0, self.hpos - 1)
            self.input = self.history[self.hpos]
            self.cursor = len(self.input)
        elif k == pygame.K_DOWN and self.history:
            self.hpos = min(len(self.history), self.hpos + 1)
            self.input = self.history[self.hpos] if self.hpos < len(self.history) else ""
            self.cursor = len(self.input)
        elif k == pygame.K_TAB:
            self.input = self.input[:self.cursor] + "    " + self.input[self.cursor:]
            self.cursor += 4
        elif ui.ctrl(ev) and k == pygame.K_v:
            s = clipboard.get().split("\n")[0]
            self.input = self.input[:self.cursor] + s + self.input[self.cursor:]
            self.cursor += len(s)
        elif ui.ctrl(ev) and k == pygame.K_l:
            self.lines = []
        elif ev.unicode and ord(ev.unicode[0]) >= 32 and not ui.ctrl(ev):
            self.input = self.input[:self.cursor] + ev.unicode + self.input[self.cursor:]
            self.cursor += 1
        else:
            return False
        return True


def _strip_ansi(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == "\x1b" and i + 1 < len(s) and s[i + 1] == "[":
            j = i + 2
            while j < len(s) and not s[j].isalpha():
                j += 1
            i = j + 1
            continue
        out.append(s[i])
        i += 1
    return "".join(out)
