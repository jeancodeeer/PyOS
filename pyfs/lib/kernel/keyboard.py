# PS/2 keyboard driver (scancode set 1).
#
# Turns scancodes into the bytes a terminal would send (UTF-8 for accented
# letters) and feeds them to the console input queue.
#
#   keyboard.layout("es")             # "us", "es" (Spain), "latam"
#   keyboard.bind("f2", fn)           # run fn() when F2 is pressed
#   keyboard.bind("ctrl-alt-t", fn)   # names: ctrl-/alt-/shift- + key
#   keyboard.unbind("f2")
#
# Default bindings: Ctrl+L clears the screen, PgUp/PgDn (with or without
# Shift) scroll back through the console history, Ctrl+Alt+Del resets.
# Set keyboard.raw_keys = True to receive F1-F12, Insert, PgUp and PgDn as
# escape sequences instead (for full-screen programs).
import sys
import _kernel
from _kernel import inb, outb
from kernel import irq, pic

# ---- layouts ----
# The printable keys come from kernel/layouts.py, generated from the X11
# keyboard definitions by tools/gen_layouts.py: scancode -> (normal, shift,
# AltGr, caps-affects). "dead:x" is a dead key. The keys below are the same
# on every layout.
from kernel.layouts import LAYOUTS as _GENERATED

_COMMON = {
    0x01: ("\x1b", "\x1b", "", False), 0x0E: ("\x08", "\x08", "", False),
    0x0F: ("\t", "\t", "", False), 0x1C: ("\r", "\r", "", False),
    0x37: ("*", "*", "", False), 0x39: (" ", " ", "", False),
}
LAYOUTS = {}
for _name, _table in _GENERATED.items():
    LAYOUTS[_name] = dict(_COMMON)
    LAYOUTS[_name].update(_table)

COMPOSE = {
    "´": dict(zip("aeiouyAEIOUYcCnNsSzZ", "áéíóúýÁÉÍÓÚÝćĆńŃśŚźŹ")),
    "`": dict(zip("aeiouAEIOU", "àèìòùÀÈÌÒÙ")),
    "^": dict(zip("aeiouAEIOU", "âêîôûÂÊÎÔÛ")),
    "¨": dict(zip("aeiouyAEIOU", "äëïöüÿÄËÏÖÜ")),
    "~": dict(zip("anoANO", "ãñõÃÑÕ")),
    "¸": dict(zip("cCsS", "çÇşŞ")),
    "°": dict(zip("aAuU", "åÅůŮ")),
}

# ---- non-character keys ----
_FKEYS = {0x3B: 1, 0x3C: 2, 0x3D: 3, 0x3E: 4, 0x3F: 5, 0x40: 6, 0x41: 7, 0x42: 8,
          0x43: 9, 0x44: 10, 0x57: 11, 0x58: 12}
_FKEY_SEQ = {1: b"\x1bOP", 2: b"\x1bOQ", 3: b"\x1bOR", 4: b"\x1bOS", 5: b"\x1b[15~",
             6: b"\x1b[17~", 7: b"\x1b[18~", 8: b"\x1b[19~", 9: b"\x1b[20~",
             10: b"\x1b[21~", 11: b"\x1b[23~", 12: b"\x1b[24~"}
_NAV = {0x48: "up", 0x50: "down", 0x4D: "right", 0x4B: "left", 0x47: "home",
        0x4F: "end", 0x52: "insert", 0x53: "delete", 0x49: "pgup", 0x51: "pgdn"}
_NAV_SEQ = {"up": b"\x1b[A", "down": b"\x1b[B", "right": b"\x1b[C", "left": b"\x1b[D",
            "home": b"\x1b[H", "end": b"\x1b[F", "delete": b"\x1b[3~"}
_RAW_SEQ = {"insert": b"\x1b[2~", "pgup": b"\x1b[5~", "pgdn": b"\x1b[6~"}
_KEYPAD = {0x47: "7", 0x48: "8", 0x49: "9", 0x4A: "-", 0x4B: "4", 0x4C: "5",
           0x4D: "6", 0x4E: "+", 0x4F: "1", 0x50: "2", 0x51: "3", 0x52: "0", 0x53: "."}

LED_SCROLL, LED_NUM, LED_CAPS = 1, 2, 4

current = "us"
keys = LAYOUTS["us"]
raw_keys = False
shift = ctrl = alt = altgr = caps = False
num = True
leds = 0
dead = None
_ext = False
_bindings = {}


def layout(name=None):
    """Select a keyboard layout ("us", "es", "latam"); returns the current one."""
    global current, keys
    if name is not None:
        keys = LAYOUTS[name]
        current = name
    return current


def bind(name, fn):
    """Run fn() when the named key is pressed, instead of typing it."""
    _bindings[name.lower()] = fn


def unbind(name):
    _bindings.pop(name.lower(), None)


def bindings():
    return sorted(_bindings)


capture = None                               # a list: typed text goes there instead (testing)
listener = None                              # fn(scancode, extended, down) -> True to take the key
held = set()                                 # (scancode, extended) of keys held down now


def _push(data):
    if capture is not None:
        capture.append(str(data, "utf8"))
        return
    from kernel import console
    if console.current and console.current.offset:
        console.current.live()               # typing returns from the scrollback
    _kernel.stdin_push(data)


def _emit(ch):
    """Type one character, resolving a pending dead key."""
    global dead
    if dead is not None:
        accent, dead = dead, None
        composed = COMPOSE.get(accent, {}).get(ch)
        if composed:
            ch = composed
        elif ch == " ":
            ch = accent
        else:
            ch = accent + ch
    _push(ch.encode())


def _wait_input_clear():
    for _ in range(100000):
        if not inb(0x64) & 2:
            return


def set_leds():
    """Send the Caps/Num/Scroll lock state to the keyboard's lights."""
    global leds
    leds = (LED_CAPS if caps else 0) | (LED_NUM if num else 0)
    _wait_input_clear()
    outb(0x60, 0xED)
    _wait_input_clear()
    outb(0x60, leds)


def _modifiers(name):
    prefix = ""
    if ctrl:
        prefix += "ctrl-"
    if alt:
        prefix += "alt-"
    if shift:
        prefix += "shift-"
    return prefix + name


bindings_enabled = True                      # full-screen programs turn these off


def _bound(name):
    fn = _bindings.get(name) if bindings_enabled else None
    if fn is None:
        return False
    try:
        fn()
    except Exception as e:
        print("key binding %s failed:" % name)
        sys.print_exception(e)
    return True


def _special(name):
    """A non-character key: binding, escape sequence, or nothing."""
    if _bound(_modifiers(name)):
        return
    seq = _NAV_SEQ.get(name) or (_RAW_SEQ.get(name) if raw_keys else None)
    if seq:
        _push(seq)


def _key(code):
    global shift, ctrl, alt, altgr, caps, num, dead, _ext
    if code in (0xFA, 0xFE, 0xEE, 0x00, 0xFF):  # controller replies, not keys
        return
    if code == 0xE0:
        _ext = True
        return
    ext, _ext = _ext, False
    down = not (code & 0x80)
    code &= 0x7F
    if down:
        held.add((code, ext))
    else:
        held.discard((code, ext))
    if listener is not None:
        # A program (pygame) reads the keys itself; modifier state is still
        # kept here, and Ctrl-C still interrupts.
        try:
            taken = listener(code, ext, down)
        except Exception:
            taken = False
        if taken and code not in (0x2A, 0x36, 0x1D, 0x38):
            if down and ctrl and code == 0x2E and not ext:
                _push(b"\x03")
            return
    if code in (0x2A, 0x36) and not ext:
        shift = down
    elif code == 0x1D:
        ctrl = down
    elif code == 0x38:
        if ext:
            altgr = down
        else:
            alt = down
    elif not down:
        return
    elif code == 0x3A:
        caps = not caps
        set_leds()
    elif code == 0x45 and not ext:
        num = not num
        set_leds()
    elif code in _FKEYS:
        n = _FKEYS[code]
        if not _bound(_modifiers("f%d" % n)):
            _push(_FKEY_SEQ[n])              # as a terminal sends it (F1 help, F2, F3 ...)
    elif ext:
        if code == 0x53 and ctrl and alt:
            outb(0x64, 0xFE)                 # Ctrl-Alt-Del: reset the machine
        elif code == 0x1C:
            _push(b"\r")                     # keypad Enter
        elif code == 0x35:
            _emit("/")                       # keypad /
        elif code in _NAV:
            _special(_NAV[code])
    elif code in _KEYPAD and (num and not shift or code in (0x4A, 0x4E)):
        _emit(_KEYPAD[code])
    elif code in _NAV:
        _special(_NAV[code])                 # keypad with Num Lock off
    elif code in keys:
        normal, shifted, alt_gr, letter = keys[code]
        if altgr or (ctrl and alt and alt_gr):
            ch = alt_gr
        else:
            ch = (shifted or normal) if shift != (caps and letter) else normal
        if not ch:
            return
        if ch.startswith("dead:"):
            accent = ch[5:]
            if dead is not None:             # two dead keys: type the first
                _emit(" ")
            dead = accent
            return
        if (ctrl or alt) and not altgr and len(normal) == 1 and _bound(_modifiers(normal.lower())):
            return
        if ctrl and not altgr and len(ch) == 1 and ord(ch) < 0x80:
            _push(bytes((ord(ch) & 0x1F,)))
            return
        _emit(ch)


def _on_irq(vector):
    # The bytes were already read from the controller at interrupt time
    # (see init); the controller itself only holds a handful.
    while True:
        data = _kernel.irq_read(vector)
        if not data:
            break
        for code in data:
            _key(code)


def _clear_screen():
    from kernel import console
    if console.current:
        console.current.clear()
    _kernel.serial_write(b"\x1b[2J\x1b[H")
    from kernel import lineedit
    lineedit.repaint()


def _page(direction):
    def scroll():
        from kernel import console
        if console.current:
            if direction > 0:
                console.current.page_up()
            else:
                console.current.page_down()
    return scroll


def _defaults():
    _bindings.clear()
    bind("ctrl-l", _clear_screen)
    for prefix in ("", "shift-"):
        bind(prefix + "pgup", _page(1))
        bind(prefix + "pgdn", _page(-1))


def init():
    from kernel.arch import ARM
    if ARM:                                  # no PS/2: USB keyboards (kernel/usb.py) type here
        _defaults()
        return
    while inb(0x64) & 1:                     # drain anything pending
        inb(0x60)
    _defaults()
    # keyboard bytes: output buffer full (bit 0) and not from the mouse (bit 5)
    _kernel.irq_fifo(pic.vector(1), 0x64, 0x21, 0x01, 0x60)
    irq.register(pic.vector(1), _on_irq)
    pic.enable(1)
    set_leds()
