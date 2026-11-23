# Full-screen text editor:  edit('/disk/notes.py')
#
# Drawn with ANSI sequences, so it works on the PC screen and on a serial
# terminal alike. Python files are syntax-coloured.
#
#   arrows, Home/End, PgUp/PgDn   move
#   Ctrl+S (or Ctrl+O)            save            Ctrl+Q (or Ctrl+X)   quit
#   Ctrl+F (or Ctrl+W)            find (Enter on an empty box repeats)
#   Ctrl+G                        go to line      Ctrl+L               redraw
#   Ctrl+K                        cut line        Ctrl+U               paste cut lines
import micropython
import sys
from kernel import console, keyboard
from kernel.lineedit import C_OFF, highlight, pending, read_key

_write = sys.stdout.write
HELP = " ^S save  ^Q quit  ^F find  ^G go to line  ^K cut  ^U paste"


class Editor:
    def __init__(self, path):
        self.path = path
        try:
            with open(path) as f:
                text = f.read()
            self.new = False
        except OSError:
            text = ""
            self.new = True
        lines = text.replace("\r\n", "\n").replace("\t", "    ").split("\n")
        if len(lines) > 1 and lines[-1] == "":
            lines.pop()
        self.lines = lines
        self.cx = self.cy = 0          # cursor: column, line
        self.top = self.left = 0       # first line / column shown
        self.modified = False
        self.colour = path.endswith(".py")
        self.clip = []
        self.cutting = False           # consecutive Ctrl+K presses extend the clipboard
        self.query = ""
        self.message = "new file" if self.new else ""
        self.confirm_quit = False
        self.done = False
        con = console.current
        self.rows = console.ROWS - con.top if con else 24
        self.cols = console.COLS
        self.body = self.rows - 2      # text rows between the title and the help line
        self.dirty = "all"             # what to redraw: "all", "line" or None

    # ---- drawing ----
    def _at(self, row, col=1):
        return "\x1b[%d;%dH" % (row, col)

    def _bar(self, row, text):
        return self._at(row) + "\x1b[7m" + (text + " " * self.cols)[:self.cols - 1] + C_OFF

    def _text_row(self, i):
        row = self._at(i - self.top + 2)
        if i >= len(self.lines):
            return row + "\x1b[90m~" + C_OFF + "\x1b[K"
        view = self.lines[i][self.left:self.left + self.cols - 1]
        return row + (highlight(view) if self.colour else view) + "\x1b[K"

    def render(self):
        out = ["\x1b[?25l"]
        if self.dirty == "all":
            for i in range(self.top, self.top + self.body):
                out.append(self._text_row(i))
        elif self.dirty == "line":
            out.append(self._text_row(self.cy))
        title = " %s%s" % (self.path, " *" if self.modified else "")
        where = "Ln %d/%d  Col %d " % (self.cy + 1, len(self.lines), self.cx + 1)
        out.append(self._bar(1, title + " " * max(1, self.cols - 1 - len(title) - len(where)) + where))
        out.append(self._bar(self.rows, " " + self.message if self.message else HELP))
        out.append(self._at(self.cy - self.top + 2, self.cx - self.left + 1))
        out.append("\x1b[?25h")
        _write("".join(out))
        self.dirty = None

    def scroll(self):
        """Keep the cursor inside the window."""
        top, left = self.top, self.left
        if self.cy < top:
            top = self.cy
        elif self.cy >= top + self.body:
            top = self.cy - self.body + 1
        if self.cx < left:
            left = self.cx
        elif self.cx >= left + self.cols - 1:
            left = self.cx - self.cols + 2
        if (top, left) != (self.top, self.left):
            self.top, self.left = top, left
            self.dirty = "all"

    def touch(self, what):
        if self.dirty != "all":
            self.dirty = what

    def ask(self, label):
        """One-line input box on the bottom row. Returns None if cancelled."""
        text = ""
        while True:
            _write(self._bar(self.rows, " " + label + text) + self._at(self.rows, len(label) + len(text) + 2))
            key = read_key()
            if key == "enter":
                return text
            if key in ("esc", "ctrl-c", "ctrl-g", "ctrl-q", "ctrl-x"):
                return None
            if key == "backspace":
                text = text[:-1]
            elif len(key) == 1:
                text += key

    # ---- editing ----
    def changed(self, what="line"):
        self.modified = True
        self.confirm_quit = False
        self.touch(what)

    def key(self, key):
        lines, cy, cx = self.lines, self.cy, self.cx
        line = lines[cy]
        self.message = ""
        cutting, self.cutting = self.cutting, False
        if len(key) == 1:
            lines[cy] = line[:cx] + key + line[cx:]
            self.cx += 1
            self.changed()
        elif key == "enter":
            indent = len(line) - len(line.lstrip(" "))
            indent = min(indent, cx)
            if line[:cx].rstrip().endswith(":"):
                indent += 4
            lines[cy] = line[:cx]
            lines.insert(cy + 1, " " * indent + line[cx:])
            self.cy += 1
            self.cx = indent
            self.changed("all")
        elif key == "backspace":
            if cx:
                step = 4 if cx % 4 == 0 and not line[:cx].strip() else 1
                lines[cy] = line[:cx - step] + line[cx:]
                self.cx -= step
                self.changed()
            elif cy:
                self.cx = len(lines[cy - 1])
                lines[cy - 1] += lines.pop(cy)
                self.cy -= 1
                self.changed("all")
        elif key == "delete":
            if cx < len(line):
                lines[cy] = line[:cx] + line[cx + 1:]
                self.changed()
            elif cy + 1 < len(lines):
                lines[cy] += lines.pop(cy + 1)
                self.changed("all")
        elif key == "tab":
            pad = 4 - cx % 4
            lines[cy] = line[:cx] + " " * pad + line[cx:]
            self.cx += pad
            self.changed()
        elif key == "left":
            if cx:
                self.cx -= 1
            elif cy:
                self.cy -= 1
                self.cx = len(lines[self.cy])
        elif key == "right":
            if cx < len(line):
                self.cx += 1
            elif cy + 1 < len(lines):
                self.cy += 1
                self.cx = 0
        elif key == "up":
            self.cy = max(0, cy - 1)
        elif key == "down":
            self.cy = min(len(lines) - 1, cy + 1)
        elif key == "pgup":
            self.cy = max(0, cy - self.body)
        elif key == "pgdn":
            self.cy = min(len(lines) - 1, cy + self.body)
        elif key == "home" or key == "ctrl-a":
            self.cx = 0
        elif key == "end" or key == "ctrl-e":
            self.cx = len(line)
        elif key == "ctrl-k":
            if not cutting:
                self.clip = []
            self.cutting = True
            self.clip.append(line)
            if len(lines) > 1:
                lines.pop(cy)
            else:
                lines[0] = ""
            self.cy = min(cy, len(lines) - 1)
            self.cx = 0
            self.changed("all")
        elif key == "ctrl-u":
            if self.clip:
                lines[cy:cy] = self.clip
                self.cy += len(self.clip)
                self.changed("all")
        elif key == "ctrl-s" or key == "ctrl-o":
            self.save()
        elif key == "ctrl-q" or key == "ctrl-x":
            if self.modified and not self.confirm_quit:
                self.confirm_quit = True
                self.message = "unsaved changes: ^Q again to discard them, ^S to save"
            else:
                self.done = True
        elif key == "ctrl-f" or key == "ctrl-w":
            self.find()
        elif key == "ctrl-g":
            answer = self.ask("go to line: ")
            if answer and answer.isdigit():
                self.cy = max(0, min(len(lines) - 1, int(answer) - 1))
                self.cx = 0
            self.touch("all")
        elif key == "ctrl-l":
            self.touch("all")
        if key not in ("ctrl-q", "ctrl-x"):
            self.confirm_quit = False
        self.cx = min(self.cx, len(self.lines[self.cy]))

    def find(self):
        answer = self.ask("find: ")
        self.touch("all")
        if answer is None:
            return
        self.query = answer or self.query
        if not self.query:
            return
        n = len(self.lines)
        for step in range(n + 1):
            i = (self.cy + step) % n
            start = self.cx + 1 if step == 0 else 0
            col = self.lines[i].find(self.query, start)
            if col >= 0:
                self.cy, self.cx = i, col
                return
        self.message = "not found: " + self.query

    def save(self):
        try:
            with open(self.path, "w") as f:
                f.write("\n".join(self.lines) + "\n")
        except OSError as e:
            self.message = "could not save: %s" % e
            return
        self.modified = False
        self.message = "saved %d lines to %s" % (len(self.lines), self.path)

    # ---- main loop ----
    def run(self):
        con = console.current
        if con:
            con.live()
            snapshot = (bytes(con.fb), con.x, con.y, con.attr)
        saved = (keyboard.raw_keys, keyboard.bindings_enabled)
        keyboard.raw_keys, keyboard.bindings_enabled = True, False
        micropython.kbd_intr(-1)                 # Ctrl+C is just a key in here
        _write("\x1b[?1049h\x1b[0m")             # serial terminals: alternate screen
        try:
            while not self.done:
                self.scroll()
                self.render()
                self.key(read_key())
                while pending() and not self.done:   # pasted text: draw once
                    self.scroll()
                    self.key(read_key())
                    self.dirty = "all"
        finally:
            _write("\x1b[0m\x1b[?1049l")
            micropython.kbd_intr(3)
            keyboard.raw_keys, keyboard.bindings_enabled = saved
            if con:
                con.fb[:] = snapshot[0]
                con.x, con.y, con.attr = snapshot[1:]
                con.show_cursor(True)
                con._cursor()
