# The prompt's line editor, in Python.
#
# The VM asks this module for every line of console input (see install()).
# It provides: syntax colouring as you type, Tab completion, history with
# Up/Down, reverse history search (Ctrl+R), auto-indent, and the usual
# editing keys. If it ever fails, the built-in C editor takes over.
#
#   Left/Right Home/End   move            Ctrl+A / Ctrl+E   start / end of line
#   Up/Down               history         Ctrl+R            search history
#   Tab                   complete        Ctrl+K / Ctrl+U   delete to end / start
#   Ctrl+W                delete word     Ctrl+L            clear screen
#   Ctrl+C                cancel line     Ctrl+D            delete char / soft reboot
#
# read_key() and highlight() are also used by the full-screen editor.
import sys
import _kernel

WIDTH = 80
PROMPTS = (">>> ", "... ")
KEYWORDS = set(("False None True and as assert async await break class continue def del elif "
                "else except finally for from global if import in is lambda nonlocal not or "
                "pass raise return try while with yield").split())

# colours (ANSI): keywords, strings, numbers, comments, shell commands
C_KEYWORD, C_STRING, C_NUMBER, C_COMMENT, C_COMMAND, C_OFF = (
    "\x1b[96m", "\x1b[92m", "\x1b[95m", "\x1b[90m", "\x1b[93m", "\x1b[0m")

colour = True                    # set False for a plain prompt
active = None                    # the LineEditor reading input right now
last_statement = ""              # the complete statement most recently entered

_read = sys.stdin.buffer.read
_write = sys.stdout.write
pending = _kernel.stdin_pending


# ---- keys ----

_CSI = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end",
        "1~": "home", "7~": "home", "4~": "end", "8~": "end", "2~": "insert",
        "3~": "delete", "5~": "pgup", "6~": "pgdn", "1;5C": "ctrl-right",
        "1;5D": "ctrl-left", "15~": "f5", "17~": "f6", "18~": "f7", "19~": "f8",
        "20~": "f9", "21~": "f10", "23~": "f11", "24~": "f12"}
_SS3 = {"P": "f1", "Q": "f2", "R": "f3", "S": "f4", "H": "home", "F": "end"}
_CTRL = {8: "backspace", 127: "backspace", 9: "tab", 10: "enter", 13: "enter"}


ESC_WAIT_MS = 300                # how long the rest of an escape sequence may take
                                 # (readline waits 500; the PS/2 keyboard never needs it)


def _more():
    """After ESC: is the rest of a key's escape sequence coming? Over a
    serial line its bytes arrive one by one, so wait a little first."""
    if pending():
        return True
    from kernel import timer
    end = timer.ms() + ESC_WAIT_MS
    while timer.ms() < end:
        if pending():
            return True
        _kernel.wait()
    return False


def read_key():
    """Wait for one key. Returns a single character for text, or a name:
    enter, backspace, tab, esc, up, down, left, right, home, end, delete,
    insert, pgup, pgdn, f1..f12, ctrl-a .. ctrl-z, alt-x."""
    b = _read(1)[0]
    if b == 27:
        if not _more():
            return "esc"
        b = _read(1)[0]
        if b == 0x5B or b == 0x4F:               # ESC [ ...   or   ESC O ...
            table = _CSI if b == 0x5B else _SS3
            seq = ""
            while True:
                c = _read(1)[0]
                seq += chr(c)
                if 0x40 <= c <= 0x7E:
                    return table.get(seq, "unknown")
        return "alt-" + chr(b)
    if b < 32 or b == 127:
        return _CTRL.get(b) or "ctrl-" + chr(b + 96)
    if b < 0x80:
        return chr(b)
    if b < 0xC0:
        return "unknown"                         # stray UTF-8 continuation byte
    data = bytes((b,)) + _read(1 if b < 0xE0 else 2 if b < 0xF0 else 3)
    try:
        return str(data, "utf8")
    except Exception:
        return "unknown"


# ---- syntax colouring ----

def _is_ident(ch):
    return ch.isalpha() or ch.isdigit() or ch == "_" or ord(ch) > 127


def highlight(text, commands=()):
    """`text` (one line of Python) with ANSI colour codes added."""
    out = []
    i, n = 0, len(text)
    plain = 0                                    # start of text not yet emitted
    first_word = True
    while i < n:
        ch = text[i]
        start = i
        if ch == "#":
            code, i = C_COMMENT, n
        elif ch == '"' or ch == "'":
            quote = ch * 3 if text[i:i + 3] == ch * 3 else ch
            i += len(quote)
            while i < n and text[i:i + len(quote)] != quote:
                i += 2 if text[i] == "\\" else 1
            i = min(n, i + len(quote))
            code = C_STRING
        elif ch.isdigit() and (i == 0 or not _is_ident(text[i - 1])):
            while i < n and (_is_ident(text[i]) or text[i] == "."):
                i += 1
            code = C_NUMBER
        elif _is_ident(ch):
            while i < n and _is_ident(text[i]):
                i += 1
            word = text[start:i]
            if word in KEYWORDS:
                code = C_KEYWORD
            elif first_word and word in commands:
                code = C_COMMAND
            else:
                code = None
            first_word = False
        else:
            i += 1
            if ch != " ":
                first_word = False
            continue
        if code:
            out.append(text[plain:start])
            out.append(code)
            out.append(text[start:i])
            out.append(C_OFF)
            plain = i
    out.append(text[plain:])
    return "".join(out)


def _command_names():
    try:
        from kernel import shell
        return shell._commands
    except Exception:
        return ()


# ---- the editor ----

class LineEditor:
    """Edits one line, or -- at the Python prompt (shell=True) -- a whole
    statement of several lines, the way CPython 3.13's console does."""

    def __init__(self, prompt, so_far, shell=None, ps2=None, prompt_colour=""):
        self.prompt = prompt
        self.ps2 = ps2 if ps2 is not None else PROMPTS[1]
        self.prompt_colour = prompt_colour
        self.shell = prompt in PROMPTS if shell is None else shell
        self.block = shell is True                # multi-line statement editing
        self.fkeys = self.block                   # F1-F3 end editing (the console uses them)
        self.reset_pending = False
        self.continuation = self.shell and bool(so_far)
        self.buf = self._indent(so_far) if self.continuation else ""
        self.pos = len(self.buf)
        self.left = 0                             # first column shown on the cursor's line
        self.shown = 0                            # columns between text start and the cursor
        self.row = 0                              # screen row of the cursor, within the block
        self.rows = 1                             # rows the block occupies on screen
        self.hist = None
        self.hist_at = -1
        self.stash = ""

    @staticmethod
    def _indent(so_far):
        lines = so_far.split("\n")
        prev = lines[-2] if len(lines) >= 2 else ""
        if not prev.strip():
            return ""
        indent = len(prev) - len(prev.lstrip(" "))
        if prev.rstrip().endswith(":"):
            indent += 4
        return " " * indent

    # -- where the cursor is --
    def _line_start(self, pos=None):
        pos = self.pos if pos is None else pos
        return self.buf.rfind("\n", 0, pos) + 1

    def _line_end(self, pos=None):
        pos = self.pos if pos is None else pos
        end = self.buf.find("\n", pos)
        return len(self.buf) if end < 0 else end

    def _cursor_line(self):
        return self.buf.count("\n", 0, self.pos)

    def _prompt_for(self, i):
        return self.prompt if i == 0 else self.ps2

    def _write_prompt(self, i, reset=True):
        p = self._prompt_for(i)
        if not self.prompt_colour:
            _write(p)
        elif reset:
            _write(self.prompt_colour + p + C_OFF)
        else:
            # The prompt is the last thing written until a key arrives (the
            # colour is turned off by the first paint): programs and tests
            # that wait for it see it as the end of the output.
            _write(self.prompt_colour + p)
            self.reset_pending = True

    # -- drawing --
    def _draw_text(self, line, width, left):
        view = line[left:left + width]
        _write(highlight(view, _command_names()) if colour and self.shell else view)
        _write("\x1b[K")
        return view

    def paint(self):
        if self.reset_pending:
            self.reset_pending = False
            _write(C_OFF)
        if "\n" not in self.buf and self.rows == 1:
            return self._paint_one()
        lines = self.buf.split("\n")
        cl = self._cursor_line()
        col = self.pos - self._line_start()
        # back to the first row of the block
        _write("\r" + ("\x1b[%dA" % self.row if self.row else ""))
        for i, line in enumerate(lines):
            if i:
                _write("\n")
            p = len(self._prompt_for(i))
            if i >= self.rows:
                self._write_prompt(i)            # a new row: it needs its prompt
            else:
                _write("\x1b[%dC" % p if p else "")
            avail = WIDTH - p - 1
            if i == cl:
                if col < self.left:
                    self.left = col
                elif col > self.left + avail:
                    self.left = col - avail
                self._draw_text(line, avail, self.left)
            else:
                self._draw_text(line, avail, 0)
            _write("\r")
        extra = max(0, self.rows - len(lines))
        for _ in range(extra):                   # lines that were deleted
            _write("\n\x1b[K")
        up = extra + len(lines) - 1 - cl
        if up:
            _write("\x1b[%dA" % up)
        right = len(self._prompt_for(cl)) + col - self.left
        if right:
            _write("\x1b[%dC" % right)
        self.rows = len(lines)
        self.row = cl
        self.shown = col - self.left

    def _paint_one(self):
        avail = WIDTH - len(self.prompt) - 1
        if self.pos < self.left:
            self.left = self.pos
        elif self.pos > self.left + avail:
            self.left = self.pos - avail
        out = []
        if self.shown:
            out.append("\x1b[%dD" % self.shown)
        _write("".join(out))
        view = self._draw_text(self.buf, avail, self.left)
        back = len(view) - (self.pos - self.left)
        if back:
            _write("\x1b[%dD" % back)
        self.shown = self.pos - self.left

    def to_end(self):
        """Put the cursor after the last line (before leaving the editor)."""
        self.pos = len(self.buf)
        self.paint()

    def fresh_line(self):
        """Start again on the current row (after the screen was cleared)."""
        self._write_prompt(0)
        self.shown = 0
        self.row = 0
        self.rows = 1
        if "\n" in self.buf:
            self.paint()
        else:
            self._paint_one()

    # -- editing --
    def insert(self, text):
        self.buf = self.buf[:self.pos] + text + self.buf[self.pos:]
        self.pos += len(text)

    def delete(self, start, end):
        self.buf = self.buf[:start] + self.buf[end:]
        self.pos = start

    def _word_start(self):
        i, stop = self.pos, self._line_start()
        while i > stop and self.buf[i - 1] == " ":
            i -= 1
        while i > stop and self.buf[i - 1] not in " \n":
            i -= 1
        return i

    def history(self):
        if self.hist is None:
            self.hist = _kernel.history()         # newest first
        return self.hist

    def _recall(self, step):
        hist = self.history()
        at = self.hist_at + step
        if at < -1 or at >= len(hist):
            return
        if self.hist_at == -1:
            self.stash = self.buf
        self.hist_at = at
        self.buf = self.stash if at == -1 else hist[at]
        self.pos = len(self.buf)

    def _vertical(self, step):
        """Up/Down: move between the lines of the block, or through history."""
        cl, last = self._cursor_line(), self.buf.count("\n")
        if not self.block or not (0 <= cl + step <= last):
            self._recall(-step)
            return
        col = self.pos - self._line_start()
        if step < 0:
            start = self._line_start(self._line_start() - 1)
        else:
            start = self._line_end() + 1
        self.pos = min(start + col, self._line_end(start))

    def _enter(self):
        """Enter in block mode: run the statement, or open its next line."""
        buf = self.buf
        lines = buf.split("\n")
        if len(lines) > 1 and not lines[-1].strip():
            self.buf = "\n".join(lines[:-1])     # a blank line ends the block
            return True
        if not buf.strip():
            return True
        try:
            more = _kernel.repl_continue(buf)
        except Exception:
            more = False
        if not more:
            return True
        self.pos = len(buf)
        # pasted text brings its own indentation
        self.insert("\n" + ("" if pending() else self._indent(buf + "\n")))
        return False

    def handle(self, key):
        """Apply one key. Returns the finished text (str), a control code
        (int), or None to keep editing."""
        buf, pos = self.buf, self.pos
        if len(key) == 1:
            self.insert(key)
        elif key == "enter":
            if self.block and not self._enter():
                return None
            self.to_end()
            _write("\n")
            if self.continuation and not self.buf.strip():
                return ""
            return self.buf
        elif key == "backspace":
            start = self._line_start()
            if pos > start:
                col = pos - start
                step = 4 if col % 4 == 0 and not buf[start:pos].strip() else 1
                self.delete(pos - step, pos)
            elif pos:
                self.delete(pos - 1, pos)        # join with the line above
        elif key == "delete" or key == "ctrl-d":
            if key == "ctrl-d" and not buf:
                return 4
            if pos < len(buf):
                self.delete(pos, pos + 1)
        elif key == "left" or key == "ctrl-b":
            if key == "ctrl-b" and not buf:
                return 2
            self.pos = max(0, pos - 1)
        elif key == "right" or key == "ctrl-f":
            self.pos = min(len(buf), pos + 1)
        elif key == "home" or key == "ctrl-a":
            if key == "ctrl-a" and not buf:
                return 1
            self.pos = self._line_start()
        elif key == "end" or key == "ctrl-e":
            if key == "ctrl-e" and not buf:
                return 5
            self.pos = self._line_end()
        elif key == "ctrl-left":
            self.pos = self._word_start()
        elif key == "ctrl-right":
            i, end = pos, self._line_end()
            while i < end and buf[i] == " ":
                i += 1
            while i < end and buf[i] != " ":
                i += 1
            self.pos = i
        elif key == "up" or key == "ctrl-p":
            self._vertical(-1)
        elif key == "down" or key == "ctrl-n":
            self._vertical(1)
        elif key == "ctrl-k":
            self.buf = buf[:pos] + buf[self._line_end():]
        elif key == "ctrl-u":
            self.delete(self._line_start(), pos)
        elif key == "ctrl-w":
            self.delete(self._word_start(), pos)
        elif key == "ctrl-c":
            self.to_end()
            return 3
        elif key == "ctrl-l":
            _write("\x1b[2J\x1b[H")
            self.fresh_line()
        elif key == "tab":
            self.complete()
        elif key == "ctrl-r":
            return self.handle(self.search())
        elif key in ("f1", "f2", "f3") and self.fkeys:
            self.to_end()
            return 0xF0 + int(key[1])
        return None

    # -- Tab completion --
    def complete(self):
        left = self.buf[:self.pos]
        i = len(left)
        while i > 0 and (_is_ident(left[i - 1]) or left[i - 1] == "."):
            i -= 1
        word = left[i:]
        if not self.shell or not word:
            self.insert(" " * (4 - self.pos % 4))
            return
        import __main__
        import builtins
        if "." in word:
            parts = word.split(".")
            stem = parts.pop()
            try:
                obj = __main__.__dict__[parts[0]] if parts[0] in __main__.__dict__ else getattr(builtins, parts[0])
                for p in parts[1:]:
                    obj = getattr(obj, p)
                names = dir(obj)
            except Exception:
                return
        else:
            stem = word
            names = list(__main__.__dict__) + dir(builtins) + list(KEYWORDS)
        found = sorted(set(n for n in names
                           if n.startswith(stem) and (stem.startswith("_") or not n.startswith("_"))))
        if not found:
            return
        common = found[0]
        for name in found:
            while not name.startswith(common):
                common = common[:-1]
        if len(common) > len(stem):
            self.insert(common[len(stem):])
        elif len(found) > 1:
            self.pos = len(self.buf)
            self.paint()
            _write("\n")
            col = max(len(n) for n in found) + 2
            per_row = max(1, (WIDTH - 1) // col)
            for n, name in enumerate(found):
                _write(name + " " * (col - len(name)))
                if n % per_row == per_row - 1 or n == len(found) - 1:
                    _write("\n")
            self.pos = len(left)
            self.fresh_line()

    # -- Ctrl+R: search the history as you type --
    def search(self):
        """Returns the key that ended the search (handled by the caller)."""
        hist = self.history()
        original = self.buf
        query, at = "", -1

        def find(start):
            for i in range(start, len(hist)):
                if query in hist[i]:
                    return i
            return -1

        while True:
            shown = hist[at] if at >= 0 else ""
            line = "(search)'%s': %s" % (query, shown)
            _write("\r\x1b[K" + line[:WIDTH - 1])
            key = read_key()
            if len(key) == 1:
                query += key
                at = find(0)
            elif key == "backspace":
                query = query[:-1]
                at = find(0) if query else -1
            elif key == "ctrl-r":
                nxt = find(at + 1) if query else -1
                if nxt >= 0:
                    at = nxt
            else:
                break
        cancel = key in ("ctrl-c", "ctrl-g", "esc")
        self.buf = original if cancel or at < 0 else hist[at]
        self.pos = len(self.buf)
        _write("\r\x1b[K")
        self.fresh_line()
        return "none" if cancel else key

    def run(self):
        self._write_prompt(0, reset=False)
        if self.buf:
            self.paint()
        while True:
            result = self.handle(read_key())
            while result is None and pending():   # pasted / fast input: draw once
                result = self.handle(read_key())
            if result is not None:
                return result
            self.paint()


def readline(prompt, so_far):
    """Read one line for the VM. `so_far` is the statement entered so far
    (for continuation lines). Returns the line, or a control code."""
    global active, last_statement
    editor = LineEditor(prompt, so_far)
    active = editor
    try:
        result = editor.run()
    finally:
        active = None
    if isinstance(result, str):
        last_statement = so_far + result
    return result


def repaint():
    """Draw the prompt and the line being typed again (after a screen clear)."""
    if active:
        active.fresh_line()


def install():
    _kernel.line_editor(readline)


def uninstall():
    _kernel.line_editor(None)
