# VGA text console (80x25 at 0xB8000) with an ANSI terminal emulator.
#
# All console output from the VM arrives in Console.write() as bytes. The
# same bytes are mirrored to the serial port so a serial terminal and the
# screen always show the same thing.
#
# Features: 16/256-colour SGR, cursor save/restore (ESC 7/8, CSI s/u),
# erase modes for J and K, show/hide cursor (CSI ?25 h/l), UTF-8 text shown
# through the VGA font (code page 437), an optional status bar on the top
# row, and a scrollback buffer (Shift+PgUp / Shift+PgDn).
import _kernel, uctypes
from _kernel import inb, outb

COLS, ROWS = 80, 25
ROW_BYTES = COLS * 2
SCROLLBACK = 500                 # rows kept after they leave the screen
DEFAULT_ATTR = 0x07
STATUS_ATTR = 0x70               # black on light grey
_ANSI_TO_VGA = (0, 4, 2, 6, 1, 5, 3, 7)

# Unicode -> VGA font (code page 437) for the characters Spanish and other
# Western European text needs. Anything else is shown as '?'.
CP437 = {
    0xC7: 0x80, 0xFC: 0x81, 0xE9: 0x82, 0xE2: 0x83, 0xE4: 0x84, 0xE0: 0x85, 0xE5: 0x86,
    0xE7: 0x87, 0xEA: 0x88, 0xEB: 0x89, 0xE8: 0x8A, 0xEF: 0x8B, 0xEE: 0x8C, 0xEC: 0x8D,
    0xC4: 0x8E, 0xC5: 0x8F, 0xC9: 0x90, 0xE6: 0x91, 0xC6: 0x92, 0xF4: 0x93, 0xF6: 0x94,
    0xF2: 0x95, 0xFB: 0x96, 0xF9: 0x97, 0xFF: 0x98, 0xD6: 0x99, 0xDC: 0x9A, 0xA2: 0x9B,
    0xA3: 0x9C, 0xA5: 0x9D, 0xE1: 0xA0, 0xED: 0xA1, 0xF3: 0xA2, 0xFA: 0xA3, 0xF1: 0xA4,
    0xD1: 0xA5, 0xAA: 0xA6, 0xBA: 0xA7, 0xBF: 0xA8, 0xAC: 0xAA, 0xBD: 0xAB, 0xBC: 0xAC,
    0xA1: 0xAD, 0xAB: 0xAE, 0xBB: 0xAF, 0xDF: 0xE1, 0xB5: 0xE6, 0xB1: 0xF1, 0xF7: 0xF6,
    0xB0: 0xF8, 0xB7: 0xFA, 0xB2: 0xFD, 0xA0: 0xFF,
    # box drawing and blocks
    0x2500: 0xC4, 0x2502: 0xB3, 0x250C: 0xDA, 0x2510: 0xBF, 0x2514: 0xC0, 0x2518: 0xD9,
    0x251C: 0xC3, 0x2524: 0xB4, 0x252C: 0xC2, 0x2534: 0xC1, 0x253C: 0xC5, 0x2550: 0xCD,
    0x2551: 0xBA, 0x2588: 0xDB, 0x2591: 0xB0, 0x2592: 0xB1, 0x2593: 0xB2,
    # no glyph in the VGA font: nearest look-alike
    0xC1: 0x41, 0xCD: 0x49, 0xD3: 0x4F, 0xDA: 0x55, 0xC0: 0x41, 0xC8: 0x45, 0xCC: 0x49,
    0xD2: 0x4F, 0xD9: 0x55, 0xC2: 0x41, 0xCA: 0x45, 0xCE: 0x49, 0xD4: 0x4F, 0xDB: 0x55,
    0xB4: 0x27, 0xA8: 0x22, 0x20AC: 0xEE, 0x2018: 0x27, 0x2019: 0x27, 0x201C: 0x22,
    0x201D: 0x22, 0x2013: 0x2D, 0x2014: 0x2D, 0x2026: 0x2E,
    # symbols the VGA font draws in its first 32 glyphs, and look-alikes
    0x2022: 0x07, 0x25CF: 0x07, 0x2219: 0xF9, 0x25A0: 0xFE, 0x25AA: 0xFE, 0x2192: 0x1A, 0x2190: 0x1B,
    0x2191: 0x18, 0x2193: 0x19, 0x25B6: 0x10, 0x25C0: 0x11, 0x25B2: 0x1E, 0x25BC: 0x1F, 0x266A: 0x0D,
    0x2713: 0xFB, 0x221A: 0xFB, 0xA9: 0x63, 0xAE: 0x52, 0x2122: 0x54, 0x00D7: 0x78, 0x2032: 0x27,
    0x2033: 0x22, 0x201E: 0x22, 0x201A: 0x2C, 0x2039: 0x3C, 0x203A: 0x3E, 0x2010: 0x2D, 0x2011: 0x2D,
    0x2212: 0x2D, 0x00AD: 0x2D, 0x2009: 0x20, 0x200A: 0x20, 0x2002: 0x20, 0x2003: 0x20, 0x202F: 0x20,
}
_FROM_CP437 = {}
for _u, _b in CP437.items():
    if _b >= 0x80 and _b not in _FROM_CP437:
        _FROM_CP437[_b] = chr(_u)

current = None


def _ansi256(n):
    """xterm 256-colour index -> VGA colour 0..15."""
    if n < 8:
        return _ANSI_TO_VGA[n]
    if n < 16:
        return _ANSI_TO_VGA[n - 8] | 8
    if n >= 232:                              # greyscale ramp
        level = n - 232
        return 0 if level < 6 else 8 if level < 12 else 7 if level < 19 else 15
    n -= 16
    return _rgb(n // 36 * 51, n // 6 % 6 * 51, n % 6 * 51)


def _rgb(r, g, b):
    """24-bit colour -> nearest-ish VGA colour 0..15."""
    ansi = (r >= 96) | (g >= 96) << 1 | (b >= 96) << 2
    bright = max(r, g, b) >= 200
    if ansi == 0:
        return 8 if max(r, g, b) >= 64 else 0
    return _ANSI_TO_VGA[ansi] | (8 if bright else 0)


class Console:
    def __init__(self, base=0xB8000, mirror_serial=True):
        self.fb = uctypes.bytearray_at(base, ROWS * ROW_BYTES)
        self.attr = DEFAULT_ATTR
        self.mirror_serial = mirror_serial
        self.top = 0                  # first row of the scrolling area (1 with a status bar)
        self.x = self.y = 0
        self.saved = (0, 0, DEFAULT_ATTR)
        self.scrollback = []          # rows (bytes of char/attr pairs) that left the top
        self.offset = 0               # rows scrolled back from the live screen
        self._snapshot = None
        self._state = 0               # 0 text, 1 after ESC, 2 inside CSI
        self._params = ""
        self._u_need = 0              # UTF-8 continuation bytes still expected
        self._u_cp = 0
        self._screen = None           # the real text buffer while graphics own the screen
        _bright_backgrounds()
        self.clear()

    # ---- screen primitives ----
    def _blank(self, cells):
        return bytes((0x20, self.attr)) * cells

    def clear(self):
        """Clear the scrolling area and home the cursor."""
        self.live()
        self.fb[self.top * ROW_BYTES:] = self._blank(COLS * (ROWS - self.top))
        self.x, self.y = 0, self.top
        self._cursor()

    def _scroll(self):
        fb, top = self.fb, self.top
        self.scrollback.append(bytes(fb[top * ROW_BYTES:(top + 1) * ROW_BYTES]))
        if len(self.scrollback) > SCROLLBACK:
            del self.scrollback[0]
        fb[top * ROW_BYTES:(ROWS - 1) * ROW_BYTES] = fb[(top + 1) * ROW_BYTES:ROWS * ROW_BYTES]
        fb[(ROWS - 1) * ROW_BYTES:] = self._blank(COLS)

    def _cursor(self):
        if self._screen is not None:          # a graphics mode has the screen
            return
        pos = self.y * COLS + min(self.x, COLS - 1)
        outb(0x3D4, 14)
        outb(0x3D5, pos >> 8)
        outb(0x3D4, 15)
        outb(0x3D5, pos & 0xFF)

    def show_cursor(self, on=True):
        outb(0x3D4, 0x0A)
        outb(0x3D5, 0x0D if on else 0x20)     # start scan line 13, or bit 5 = off
        outb(0x3D4, 0x0B)
        outb(0x3D5, 0x0E)

    # ---- output ----
    def write(self, data):
        if self.mirror_serial:
            _kernel.serial_write(data)
        if self.offset:
            self.live()
        fb = self.fb
        x, y, attr = self.x, self.y, self.attr
        for c in data:
            st = self._state
            if st == 0:
                if c >= 0x80:                 # UTF-8 sequence
                    if c >= 0xC0:
                        self._u_need = 1 if c < 0xE0 else 2 if c < 0xF0 else 3
                        self._u_cp = c & (0x1F, 0x0F, 0x07)[self._u_need - 1]
                        continue
                    if not self._u_need:
                        c = 0x3F              # stray continuation byte
                    else:
                        self._u_cp = (self._u_cp << 6) | (c & 0x3F)
                        self._u_need -= 1
                        if self._u_need:
                            continue
                        c = CP437.get(self._u_cp, 0x3F)
                elif c < 0x20:
                    self._u_need = 0
                    if c == 10:
                        y += 1
                        if y >= ROWS:
                            self._scroll()
                            y = ROWS - 1
                    elif c == 13:
                        x = 0
                    elif c == 8:
                        if x > 0:
                            x -= 1
                    elif c == 9:
                        x = min((x + 8) & ~7, COLS - 1)
                    elif c == 27:
                        self._state = 1
                    continue
                elif self._u_need:
                    self._u_need = 0          # unfinished UTF-8 character: drop it
                if x >= COLS:
                    x = 0
                    y += 1
                    if y >= ROWS:
                        self._scroll()
                        y = ROWS - 1
                i = (y * COLS + x) * 2
                fb[i] = c
                fb[i + 1] = attr
                x += 1
            elif st == 1:
                self._state = 0
                if c == 0x5B:                 # ESC [
                    self._state = 2
                    self._params = ""
                elif c == 0x37:               # ESC 7: save cursor
                    self.saved = (x, y, attr)
                elif c == 0x38:               # ESC 8: restore cursor
                    x, y, attr = self.saved
                    self.attr = attr
                elif c == 0x63:               # ESC c: reset
                    self.attr = attr = DEFAULT_ATTR
                    self.clear()
                    x, y = self.x, self.y
            else:
                if 0x30 <= c <= 0x3F:
                    self._params += chr(c)
                else:
                    self._state = 0
                    self.x, self.y = x, y
                    self._csi(chr(c))
                    x, y, attr = self.x, self.y, self.attr
        self.x, self.y = x, y
        self._cursor()

    def _csi(self, final):
        params = self._params
        if params.startswith("?"):
            if params == "?25" and final in "hl":
                self.show_cursor(final == "h")
            return
        nums = [int(p) if p.isdigit() else 0 for p in params.split(";")]
        n = nums[0] or 1
        top = self.top
        if final == "m":
            self._sgr(nums)
        elif final == "K":
            row = self.y * ROW_BYTES
            cut = row + min(self.x, COLS) * 2
            start, end = ((cut, row + ROW_BYTES), (row, min(cut + 2, row + ROW_BYTES)),
                          (row, row + ROW_BYTES))[min(nums[0], 2)]
            self.fb[start:end] = self._blank((end - start) // 2)
        elif final == "J":
            cut = (self.y * COLS + min(self.x, COLS)) * 2
            start, end = ((cut, ROWS * ROW_BYTES), (top * ROW_BYTES, min(cut + 2, ROWS * ROW_BYTES)),
                          (top * ROW_BYTES, ROWS * ROW_BYTES))[min(nums[0], 2)]
            self.fb[start:end] = self._blank((end - start) // 2)
        elif final == "D":
            self.x = max(0, min(self.x, COLS) - n)
        elif final == "C":
            self.x = min(COLS - 1, self.x + n)
        elif final == "A":
            self.y = max(top, self.y - n)
        elif final == "B":
            self.y = min(ROWS - 1, self.y + n)
        elif final == "G":
            self.x = max(0, min(COLS - 1, n - 1))
        elif final in "Hf":
            self.y = max(top, min(ROWS - 1, top + n - 1))
            self.x = max(0, min(COLS - 1, (nums[1] if len(nums) > 1 else 1) - 1))
        elif final == "s":
            self.saved = (self.x, self.y, self.attr)
        elif final == "u":
            self.x, self.y, self.attr = self.saved

    def _sgr(self, nums):
        attr = self.attr
        i = 0
        while i < len(nums):
            code = nums[i]
            if code == 0:
                attr = DEFAULT_ATTR
            elif code == 1:
                attr |= 0x08
            elif code == 22:
                attr &= ~0x08
            elif code == 7:
                attr = ((attr & 0x0F) << 4) | (attr >> 4)
            elif 30 <= code <= 37:
                attr = (attr & 0xF8) | _ANSI_TO_VGA[code - 30]
            elif 90 <= code <= 97:
                attr = (attr & 0xF0) | _ANSI_TO_VGA[code - 90] | 0x08
            elif 40 <= code <= 47:
                attr = (attr & 0x8F) | (_ANSI_TO_VGA[code - 40] << 4)
            elif 100 <= code <= 107:
                attr = (attr & 0x0F) | ((_ANSI_TO_VGA[code - 100] | 8) << 4)
            elif code == 39:
                attr = (attr & 0xF0) | (DEFAULT_ATTR & 0x0F)
            elif code == 49:
                attr = (attr & 0x0F) | (DEFAULT_ATTR & 0xF0)
            elif code in (38, 48) and i + 1 < len(nums):
                if nums[i + 1] == 5 and i + 2 < len(nums):
                    colour = _ansi256(nums[i + 2])
                    i += 2
                elif nums[i + 1] == 2 and i + 4 < len(nums):
                    colour = _rgb(nums[i + 2], nums[i + 3], nums[i + 4])
                    i += 4
                else:
                    break
                attr = (attr & 0xF0) | colour if code == 38 else (attr & 0x0F) | (colour << 4)
            i += 1
        self.attr = attr & 0xFF

    # ---- status bar ----
    def status_bar(self, on=True):
        """Reserve (or give back) the top row for set_status()."""
        self.live()
        if on and not self.top:
            # make room: shift the screen down one row (the bottom row is lost)
            self.fb[ROW_BYTES:] = bytes(self.fb[:(ROWS - 1) * ROW_BYTES])
            self.y = min(self.y + 1, ROWS - 1)
            self.top = 1
            self._cursor()
            self.set_status("")
        elif not on and self.top:
            self.top = 0
            self.fb[0:ROW_BYTES] = self._blank(COLS)

    def set_status(self, text):
        if not self.top:
            return
        raw = bytearray(COLS * 2)
        text = text[:COLS]
        for i in range(COLS):
            ch = ord(text[i]) if i < len(text) else 0x20
            raw[i * 2] = ch if ch < 0x80 else CP437.get(ch, 0x3F)
            raw[i * 2 + 1] = STATUS_ATTR
        self.fb[0:ROW_BYTES] = raw

    # ---- scrollback ----
    def scroll_view(self, rows):
        """Look back (rows > 0) or forward (rows < 0) through the scrollback."""
        height = ROWS - self.top
        offset = max(0, min(len(self.scrollback), self.offset + rows))
        if offset == self.offset:
            return
        if not self.offset:
            self._snapshot = bytes(self.fb)
            self.show_cursor(False)
        self.offset = offset
        if not offset:
            self.live()
            return
        hist, snap, top = self.scrollback, self._snapshot, self.top
        total = len(hist) + height
        first = total - offset - height
        for r in range(height):
            i = first + r
            if i < len(hist):
                row = hist[i]
            else:
                k = i - len(hist) + top
                row = snap[k * ROW_BYTES:(k + 1) * ROW_BYTES]
            self.fb[(top + r) * ROW_BYTES:(top + r + 1) * ROW_BYTES] = row

    def page_up(self):
        self.scroll_view(ROWS - self.top - 1)

    def page_down(self):
        self.scroll_view(-(ROWS - self.top - 1))

    def live(self):
        """Return from the scrollback to the live screen."""
        if self.offset:
            top = self.top
            self.fb[top * ROW_BYTES:] = self._snapshot[top * ROW_BYTES:]
            self.offset = 0
            self._snapshot = None
            self.show_cursor(True)
            self._cursor()

    # ---- sharing the screen with graphics ----
    def detach(self):
        """A graphics mode takes the screen: keep drawing into a copy."""
        if self._screen is None:
            self.live()
            self._screen = self.fb
            self.fb = bytearray(self._screen)

    def attach(self):
        """Back in text mode: show everything written in the meantime."""
        if self._screen is not None:
            self._screen[:] = self.fb
            self.fb, self._screen = self._screen, None
            self._cursor()

    # ---- inspection ----
    def text(self):
        """The screen as a list of strings (handy for testing)."""
        fb = self.fb
        rows = []
        for r in range(ROWS):
            chars = []
            for c in range(COLS):
                b = fb[(r * COLS + c) * 2]
                chars.append(_FROM_CP437.get(b, chr(b)) if b >= 0x80 else chr(b))
            rows.append("".join(chars).rstrip())
        return rows


def _bright_backgrounds():
    """Turn the VGA blink bit into a bright-background bit (16 background colours)."""
    inb(0x3DA)                                # reset the attribute controller flip-flop
    outb(0x3C0, 0x30)                         # register 0x10, keep the palette enabled
    mode = inb(0x3C1)
    outb(0x3C0, mode & ~0x08)
    inb(0x3DA)
    outb(0x3C0, 0x20)


def install():
    """Create the console and route all VM output through it."""
    global current
    current = Console()
    _kernel.stdout_hook(current.write)
    return current


def uninstall():
    _kernel.stdout_hook(None)
