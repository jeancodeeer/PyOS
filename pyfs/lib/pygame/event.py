# pygame.event: the event queue. While pygame is running, the keyboard and
# mouse drivers hand their input here (instead of typing at the console).
#
# There is no window to close: Ctrl+Q posts QUIT. Ctrl+C still raises
# KeyboardInterrupt in the program, as it does in a terminal.
from pygame import constants as C

_queue = []
_blocked = set()
_attached = False
_next_custom = C.USEREVENT + 1
MAX = 256


class Event:
    def __init__(self, type, dict=None, **attrs):
        self.type = type
        if dict:
            attrs.update(dict)
        for k, v in attrs.items():
            setattr(self, k, v)
        self._attrs = attrs

    @property
    def dict(self):
        return self._attrs

    def __eq__(self, other):
        return isinstance(other, Event) and self.type == other.type and self._attrs == other._attrs

    def __bool__(self):
        return self.type != C.NOEVENT

    def __repr__(self):
        return "<Event(%d-%s %r)>" % (self.type, event_name(self.type), self._attrs)


EventType = Event

_NAMES = {C.NOEVENT: "NoEvent", C.QUIT: "Quit", C.KEYDOWN: "KeyDown", C.KEYUP: "KeyUp",
          C.MOUSEMOTION: "MouseMotion", C.MOUSEBUTTONDOWN: "MouseButtonDown",
          C.MOUSEBUTTONUP: "MouseButtonUp", C.TEXTINPUT: "TextInput",
          C.ACTIVEEVENT: "ActiveEvent", C.WINDOWEVENT: "WindowEvent",
          C.MOUSEWHEEL: "MouseWheel"}


def event_name(type):
    if type >= C.USEREVENT:
        return "UserEvent"
    return _NAMES.get(type, "Unknown")


def _add(ev):
    if ev.type in _blocked:
        return
    if len(_queue) >= MAX:
        del _queue[0]
    _queue.append(ev)


# ---- input from the drivers (runs in interrupt handlers) ----

def _on_key(code, ext, down):
    from pygame import key
    k = key._keycode(code, ext)
    if down and code == 0x10 and not ext and key._ctrl():      # Ctrl+Q
        _add(Event(C.QUIT))
        return True
    if down and code == 0x2E and not ext and key._ctrl():      # Ctrl+C: interrupt
        return True
    text = key._unicode(code, ext) if down else ""
    attrs = {"key": k, "mod": key.get_mods(), "scancode": code | (0x80 if ext else 0),
             "unicode": text}
    _add(Event(C.KEYDOWN if down else C.KEYUP, attrs))
    if down and text and ord(text[0]) >= 32 and text != "\x7f":
        _add(Event(C.TEXTINPUT, text=text))
    return True


def _on_mouse(dx, dy, buttons):
    from pygame import mouse
    mouse._moved(dx, dy, buttons, _add, Event)


def _attach():
    global _attached
    from kernel import keyboard, mouse
    keyboard.listener = _on_key
    mouse.listener = _on_mouse
    _attached = True


def _detach():
    global _attached
    from kernel import keyboard, mouse
    if keyboard.listener is _on_key:
        keyboard.listener = None
    if mouse.listener is _on_mouse:
        mouse.listener = None
    _attached = False


# ---- the queue ----

def _match(ev, eventtype):
    if eventtype is None:
        return True
    if isinstance(eventtype, int):
        return ev.type == eventtype
    return ev.type in eventtype


def pump():
    pass


def get(eventtype=None, pump=True, exclude=None):
    out, keep = [], []
    for ev in _queue[:]:
        wanted = _match(ev, eventtype) and not (exclude is not None and _match(ev, exclude))
        (out if wanted else keep).append(ev)
    _queue[:] = keep
    return out


def poll():
    if _queue:
        return _queue.pop(0)
    return Event(C.NOEVENT)


def wait(timeout=0):
    import _kernel
    from kernel import timer
    end = timer.ms() + timeout if timeout else None
    while not _queue:
        if end is not None and timer.ms() >= end:
            return Event(C.NOEVENT)
        _kernel.wait()
    return _queue.pop(0)


def peek(eventtype=None, pump=True):
    if eventtype is None:
        return bool(_queue)
    return any(_match(ev, eventtype) for ev in _queue)


def clear(eventtype=None, pump=True):
    get(eventtype)


def post(event):
    if isinstance(event, int):
        event = Event(event)
    _add(event)
    return True


def set_blocked(types):
    if types is None:
        _blocked.clear()
        return
    for t in ([types] if isinstance(types, int) else types):
        _blocked.add(t)


def set_allowed(types):
    if types is None:
        _blocked.clear()
        return
    for t in ([types] if isinstance(types, int) else types):
        _blocked.discard(t)


def get_blocked(type):
    return type in _blocked


def custom_type():
    global _next_custom
    _next_custom += 1
    return _next_custom - 1


def set_grab(on):
    pass


def get_grab():
    return _attached


def set_keyboard_grab(on):
    pass


def get_keyboard_grab():
    return _attached
