# pygame.key: key state and names, from the PS/2 scancodes (set 1).
from kernel import keyboard
from pygame import constants as C

# keys that are not characters (scancode, extended) -> pygame key
_SPECIAL = {
    (0x01, 0): C.K_ESCAPE, (0x0E, 0): C.K_BACKSPACE, (0x0F, 0): C.K_TAB,
    (0x1C, 0): C.K_RETURN, (0x39, 0): C.K_SPACE, (0x3A, 0): C.K_CAPSLOCK,
    (0x2A, 0): C.K_LSHIFT, (0x36, 0): C.K_RSHIFT, (0x1D, 0): C.K_LCTRL,
    (0x1D, 1): C.K_RCTRL, (0x38, 0): C.K_LALT, (0x38, 1): C.K_RALT,
    (0x5B, 1): C.K_LMETA, (0x5C, 1): C.K_RMETA,
    (0x48, 1): C.K_UP, (0x50, 1): C.K_DOWN, (0x4B, 1): C.K_LEFT, (0x4D, 1): C.K_RIGHT,
    (0x47, 1): C.K_HOME, (0x4F, 1): C.K_END, (0x49, 1): C.K_PAGEUP, (0x51, 1): C.K_PAGEDOWN,
    (0x52, 1): C.K_INSERT, (0x53, 1): C.K_DELETE, (0x1C, 1): C.K_KP_ENTER,
    (0x35, 1): C.K_KP_DIVIDE, (0x37, 0): C.K_KP_MULTIPLY, (0x4A, 0): C.K_KP_MINUS,
    (0x4E, 0): C.K_KP_PLUS, (0x45, 0): C.K_NUMLOCK, (0x46, 0): C.K_SCROLLOCK,
    (0x47, 0): C.K_KP7, (0x48, 0): C.K_KP8, (0x49, 0): C.K_KP9, (0x4B, 0): C.K_KP4,
    (0x4C, 0): C.K_KP5, (0x4D, 0): C.K_KP6, (0x4F, 0): C.K_KP1, (0x50, 0): C.K_KP2,
    (0x51, 0): C.K_KP3, (0x52, 0): C.K_KP0, (0x53, 0): C.K_KP_PERIOD,
}
for _i, _code in enumerate((0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x41, 0x42, 0x43, 0x44, 0x57, 0x58)):
    _SPECIAL[(_code, 0)] = C.K_F1 + _i

_NAMES = {C.K_ESCAPE: "escape", C.K_BACKSPACE: "backspace", C.K_TAB: "tab", C.K_RETURN: "return",
          C.K_SPACE: "space", C.K_CAPSLOCK: "caps lock", C.K_LSHIFT: "left shift",
          C.K_RSHIFT: "right shift", C.K_LCTRL: "left ctrl", C.K_RCTRL: "right ctrl",
          C.K_LALT: "left alt", C.K_RALT: "right alt", C.K_UP: "up", C.K_DOWN: "down",
          C.K_LEFT: "left", C.K_RIGHT: "right", C.K_HOME: "home", C.K_END: "end",
          C.K_PAGEUP: "page up", C.K_PAGEDOWN: "page down", C.K_INSERT: "insert",
          C.K_DELETE: "delete", C.K_KP_ENTER: "enter"}
for _i in range(12):
    _NAMES[C.K_F1 + _i] = "f%d" % (_i + 1)

_repeat = (0, 0)
_text_input = True


def _keycode(code, ext):
    k = _SPECIAL.get((code, 1 if ext else 0))
    if k is not None:
        return k
    entry = keyboard.LAYOUTS["us"].get(code)        # SDL keys follow the US layout
    if entry and entry[0] and len(entry[0]) == 1:
        return ord(entry[0].lower())
    return C.K_UNKNOWN


def _unicode(code, ext):
    if ext:
        return ""
    entry = keyboard.keys.get(code)
    if not entry:
        return ""
    normal, shifted, altgr, letter = entry
    if keyboard.altgr:
        ch = altgr
    else:
        ch = (shifted or normal) if keyboard.shift != (keyboard.caps and letter) else normal
    if not ch or ch.startswith("dead:") or len(ch) != 1:
        return ""
    if ch in "\x1b\x08\t\r":
        return ch
    return ch


def _ctrl():
    return keyboard.ctrl


class ScancodeWrapper:
    """What get_pressed() returns: index it with a key constant."""

    def __init__(self, keys):
        self._keys = keys

    def __getitem__(self, k):
        return k in self._keys

    def __len__(self):
        return 512

    def __iter__(self):
        return iter(sorted(self._keys))

    def __repr__(self):
        return "ScancodeWrapper(%r)" % sorted(self._keys)


def get_pressed():
    return ScancodeWrapper(set(_keycode(code, ext) for code, ext in keyboard.held))


def get_mods():
    m = 0
    for code, ext in keyboard.held:
        m |= {(0x2A, 0): C.KMOD_LSHIFT, (0x36, 0): C.KMOD_RSHIFT, (0x1D, 0): C.KMOD_LCTRL,
              (0x1D, 1): C.KMOD_RCTRL, (0x38, 0): C.KMOD_LALT, (0x38, 1): C.KMOD_RALT
              }.get((code, 1 if ext else 0), 0)
    if keyboard.caps:
        m |= C.KMOD_CAPS
    if keyboard.num:
        m |= C.KMOD_NUM
    return m


def set_mods(mods):
    pass


def name(key, use_compat=True):
    if key in _NAMES:
        return _NAMES[key]
    if 32 < key < 127:
        return chr(key)
    return "unknown key"


def key_code(name_):
    for k, n in _NAMES.items():
        if n == name_:
            return k
    if len(name_) == 1:
        return ord(name_.lower())
    raise ValueError("unknown key name")


def get_focused():
    return True


def set_repeat(delay=0, interval=0):
    global _repeat
    _repeat = (delay, interval)


def get_repeat():
    return _repeat


def start_text_input():
    global _text_input
    _text_input = True


def stop_text_input():
    global _text_input
    _text_input = False


def set_text_input_rect(rect):
    pass
