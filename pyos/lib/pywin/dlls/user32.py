# user32.dll: windows, messages, timers, the built-in controls (BUTTON,
# STATIC, EDIT) and message boxes. Drawing is in gdi32.py; the shapes of
# windows and DCs are in pywin/gui.py.
import time
import _thread
from pywin import mem, cformat
from pywin.dlls import Dll
from pywin.gui import *          # noqa: F401,F403  (message numbers and classes)
from pywin import gui

dll = Dll("user32")
MSG_SIZE = 48


EXTRA_CLASSES = []                 # more built-in controls, added by the other parts of user32


class State:
    """Everything user32 keeps for one process."""

    def __init__(self, p):
        self.p = p
        self.classes = {}            # lower-case name -> WndClass
        self.windows = {}            # HWND -> Wnd
        self.queue = []              # posted messages: (hwnd, msg, wparam, lparam, thread)
        self.timers = {}             # (hwnd, id) -> [period ms, next time, callback]
        self.focus = 0
        self.atoms = {}              # RegisterClass number -> class name
        self.menus = {}              # HMENU -> gui.Menu
        self.quit = {}               # thread -> exit code, once that thread called PostQuitMessage
        self.next = 0x10010
        for name, proc, render in (("button", _button_proc, _button_render),
                                   ("static", _static_proc, _static_render),
                                   ("edit", _edit_proc, _edit_render)):
            self.classes[name] = gui.WndClass(name, proc, (240, 240, 240), render=render)
        for cls in EXTRA_CLASSES:
            self.classes[cls.name.lower()] = cls

    def new_handle(self):
        self.next += 2
        return self.next

    def post(self, hwnd, msg, wparam=0, lparam=0, thread=None):
        """Like Windows, each thread has its own messages: those for the
        windows it created. (thread None: whichever thread asks first.)"""
        w = self.windows.get(hwnd)
        if w is not None:
            thread = getattr(w, "thread", None)
        self.queue.append((hwnd, msg, wparam & 0xFFFFFFFFFFFFFFFF, lparam & 0xFFFFFFFFFFFFFFFF, thread))


def state(p):
    s = p.state.get("user32")
    if s is None:
        s = p.state["user32"] = State(p)
    return s


def _wnd(p, hwnd):
    return state(p).windows.get(hwnd)


def _send(p, w, msg, wparam=0, lparam=0):
    """Call a window's procedure now (SendMessage)."""
    if w is None or w.proc is None:
        return 0
    if callable(w.proc):                                   # a built-in control, in Python
        return w.proc(p, w, msg, wparam, lparam)
    return p.call(w.proc, w.handle, msg, wparam & 0xFFFFFFFFFFFFFFFF, lparam & 0xFFFFFFFFFFFFFFFF)


def _lparam_xy(x, y):
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def _s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def _i32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


# ---- window classes ----

def _register(p, name, proc, brush, style, extra):
    s = state(p)
    color = (255, 255, 255)
    from pywin.dlls import gdi32
    b = gdi32.brush_color(p, brush)
    if b is not None:
        color = b
    render = None
    fn = python_proc(p, proc)
    if fn is not None:                       # a "superclass" of a built-in control
        proc = fn
        render = next((c.render for c in s.classes.values() if c.proc is fn), None)
    s.classes[name.lower()] = gui.WndClass(name, proc, color, style, extra, render=render)
    atom = 0xC000 + len(s.atoms)
    s.atoms[atom] = name
    return atom


def _class_name(p, ptr, wide):
    if ptr < 0x10000:                                       # a number from RegisterClass
        return state(p).atoms.get(ptr, "#%d" % ptr)
    return mem.wstr(ptr) if wide else mem.cstr(ptr)


def _register_from(p, wc, wide, ex):
    """WNDCLASS: style, proc, class extra, window extra, instance, icon, cursor,
    brush, menu name, class name. WNDCLASSEX starts with its size, so its style
    is at 4 and its two extras move up by 4; the rest is at the same places."""
    text = mem.wstr if wide else mem.cstr
    style, extra = (mem.u32(wc + 4), mem.i32(wc + 20)) if ex else (mem.u32(wc), mem.i32(wc + 16))
    atom = _register(p, text(mem.u64(wc + 64)), mem.u64(wc + 8), mem.u64(wc + 48), style, extra)
    menu = mem.u64(wc + 56)                         # a menu every window of the class gets
    if menu:
        cls = state(p).classes[state(p).atoms[atom].lower()]
        cls.menu = (mem.u64(wc + 24), menu if menu < 0x10000 else text(menu), wide)
    return atom


@dll(1)
def RegisterClassA(p, wc):
    return _register_from(p, wc, False, False)


@dll(1)
def RegisterClassW(p, wc):
    return _register_from(p, wc, True, False)


@dll(1)
def RegisterClassExA(p, wc):
    return _register_from(p, wc, False, True)


@dll(1)
def RegisterClassExW(p, wc):
    return _register_from(p, wc, True, True)


@dll(2)
def UnregisterClassA(p, name, inst):
    return 1


dll.alias("UnregisterClassW", "UnregisterClassA")


# ---- creating and destroying windows ----

CW_USEDEFAULT = -0x80000000


def _create(p, ex_style, cls_name, title, style, x, y, w, h, parent, menu, inst, param, wide):
    s = state(p)
    cls = s.classes.get(cls_name.lower())
    if cls is None:                                     # a control from a DLL loaded later?
        cls = next((c for c in EXTRA_CLASSES if c.name.lower() == cls_name.lower()), None)
        if cls is not None:
            s.classes[cls_name.lower()] = cls
    if cls is None:
        p.warn("clase de ventana desconocida: " + cls_name)
        return 0
    x, y, w, h = _i32(x), _i32(y), _i32(w), _i32(h)
    parent_w = s.windows.get(parent)
    child = bool(style & gui.WS_CHILD) and parent_w is not None
    if not child:
        if w == CW_USEDEFAULT or w <= 0:
            w, h = 640, 480
        if x == CW_USEDEFAULT:
            x = y = 0
        w, h = max(80, w - gui.FRAME_W), max(40, h - gui.FRAME_H)     # the client area
    handle = s.new_handle()
    wnd = gui.Wnd(handle, cls, title or "", x, y, w, h, style, parent_w if child else None,
                  menu if child else 0, param)
    wnd.owner = parent_w if not child else None
    wnd.wide = wide
    if not child and menu:
        wnd.menu = _menu(p, menu)                       # a main window's hMenu is its menu bar
    elif not child and getattr(cls, "menu", None):     # else the class's menu, from the resources
        inst_, name, wide_ = cls.menu
        found = p.resource(inst_ or p.base, 4, name.upper() if isinstance(name, str) else name)
        if found:
            wnd.menu = _menu(p, _new_menu(p, _parse_menu(mem.read(found[0], found[1]))))
    wnd.thread = _thread.get_ident()                    # its messages go to this thread
    s.windows[handle] = wnd
    if child:
        parent_w.children.append(wnd)
    cs = p.heap.alloc(80)                               # CREATESTRUCT for WM_CREATE
    for off, v in ((0, param), (8, inst), (16, menu), (24, parent)):
        mem.put64(cs + off, v)
    for off, v in ((32, h), (36, w), (40, y), (44, x), (48, style)):
        mem.put32(cs + off, v)
    _send(p, wnd, WM_NCCREATE, 0, cs)
    r = _i32(_send(p, wnd, WM_CREATE, 0, cs))
    p.heap.free(cs)
    if r == -1:
        DestroyWindow(p, handle)
        return 0
    _send(p, wnd, WM_SIZE, 0, _lparam_xy(wnd.w, wnd.h))
    if wnd.visible and not child:
        p.ui.open_window(wnd)
    return handle


@dll(12)
def CreateWindowExA(p, ex, cls, title, style, x, y, w, h, parent, menu, inst, param):
    return _create(p, ex, _class_name(p, cls, False), mem.cstr(title) if title else "", style,
                   x, y, w, h, parent, menu, inst, param, False)


@dll(12)
def CreateWindowExW(p, ex, cls, title, style, x, y, w, h, parent, menu, inst, param):
    return _create(p, ex, _class_name(p, cls, True), mem.wstr(title) if title else "", style,
                   x, y, w, h, parent, menu, inst, param, True)


@dll(1)
def DestroyWindow(p, hwnd):
    s = state(p)
    w = s.windows.get(hwnd)
    if w is None:
        return 0
    w.destroyed = True
    _send(p, w, WM_DESTROY)
    for c in list(w.children):
        DestroyWindow(p, c.handle)
    _send(p, w, WM_NCDESTROY)
    s.windows.pop(hwnd, None)
    if w.parent is not None and w in w.parent.children:
        w.parent.children.remove(w)
    if w.host is not None:
        p.ui.close_window(w)
    for key in [k for k in s.timers if k[0] == hwnd]:
        del s.timers[key]
    return 1


@dll(2)
def ShowWindow(p, hwnd, how):
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    was = w.visible
    w.visible = how != 0
    if w.top_level:
        if w.visible and w.host is None:
            p.ui.open_window(w)
        elif not w.visible and w.host is not None:
            p.ui.close_window(w)
        if not w.visible:
            w.forget_pixels()                       # a hidden window needs no picture
    w.invalid = True
    _changed(w)
    return 1 if was else 0


@dll(1)
def UpdateWindow(p, hwnd):
    w = _wnd(p, hwnd)
    if w is not None and w.invalid:
        _paint(p, w)
    return 1


@dll(1)
def IsWindow(p, hwnd):
    return 1 if _wnd(p, hwnd) else 0


@dll(1)
def IsWindowVisible(p, hwnd):
    w = _wnd(p, hwnd)
    return 1 if w and w.visible else 0


@dll(2)
def EnableWindow(p, hwnd, on):
    w = _wnd(p, hwnd)
    if w:
        w.enabled = bool(on)
        _changed(w)
    return 0


@dll(1)
def IsWindowEnabled(p, hwnd):
    w = _wnd(p, hwnd)
    return 1 if w and w.enabled else 0


@dll(1)
def GetParent(p, hwnd):
    w = _wnd(p, hwnd)
    return w.parent.handle if w and w.parent else 0


@dll(2)
def GetDlgItem(p, hwnd, item):
    w = _wnd(p, hwnd)
    for c in (w.children if w else ()):
        if c.id == item:
            return c.handle
    return 0


@dll(1)
def GetDlgCtrlID(p, hwnd):
    w = _wnd(p, hwnd)
    return w.id if w else 0


@dll(1)
def SetFocus(p, hwnd):
    s = state(p)
    old = s.focus
    if old != hwnd:
        if old:
            _send(p, _wnd(p, old), WM_KILLFOCUS, hwnd)
        s.focus = hwnd
        _send(p, _wnd(p, hwnd), WM_SETFOCUS, old)
        for h in (old, hwnd):
            w = _wnd(p, h)
            if w:
                w.has_focus = h == hwnd
                _changed(w)
    return old


@dll(0)
def GetFocus(p):
    return state(p).focus


@dll(1)
def SetActiveWindow(p, hwnd):
    return hwnd


dll.alias("SetForegroundWindow", "SetActiveWindow")
dll.alias("BringWindowToTop", "SetActiveWindow")


@dll(0)
def GetActiveWindow(p):
    for w in state(p).windows.values():
        if w.host is not None:
            return w.handle
    return 0


dll.alias("GetForegroundWindow", "GetActiveWindow")


@dll(0)
def GetDesktopWindow(p):
    return 0x10010


# ---- size and position ----

def _put_rect(at, x0, y0, x1, y1):
    for k, v in enumerate((x0, y0, x1, y1)):
        mem.put32(at + 4 * k, v)


@dll(2)
def GetClientRect(p, hwnd, rect):
    w = _wnd(p, hwnd)
    if w is None:
        cw, ch = getattr(p.ui, "screen_size", (1024, 768))
        _put_rect(rect, 0, 0, cw, ch)
        return 1
    _put_rect(rect, 0, 0, w.w, w.h)
    return 1


@dll(2)
def GetWindowRect(p, hwnd, rect):
    w = _wnd(p, hwnd)
    if w is None:
        cw, ch = getattr(p.ui, "screen_size", (1024, 768))
        _put_rect(rect, 0, 0, cw, ch)
    elif w.top_level:
        _put_rect(rect, w.x, w.y, w.x + w.w + gui.FRAME_W, w.y + w.h + gui.FRAME_H)
    else:
        ox, oy = w.parent.offset_in_top()
        _put_rect(rect, ox + w.x, oy + w.y, ox + w.x + w.w, oy + w.y + w.h)
    return 1


@dll(3)
def AdjustWindowRect(p, rect, style, menu):
    x0, y0, x1, y1 = (mem.i32(rect + 4 * k) for k in range(4))
    _put_rect(rect, x0 - 8, y0 - 31, x1 + 8, y1 + 8)
    return 1


@dll(4)
def AdjustWindowRectEx(p, rect, style, menu, ex):
    return AdjustWindowRect(p, rect, style, menu)


def _move(p, w, x, y, cw, ch):
    if w.top_level:
        cw, ch = max(40, cw - gui.FRAME_W), max(20, ch - gui.FRAME_H)
    w.x, w.y = x, y
    if (cw, ch) != (w.w, w.h):
        w.resize(cw, ch)
        _send(p, w, WM_SIZE, 0, _lparam_xy(w.w, w.h))
        if w.host is not None:
            p.ui.resize_window(w)
    _changed(w)


@dll(6)
def MoveWindow(p, hwnd, x, y, w, h, repaint):
    wnd = _wnd(p, hwnd)
    if wnd:
        _move(p, wnd, _i32(x), _i32(y), _i32(w), _i32(h))
    return 1


HWND_TOP, HWND_BOTTOM, HWND_TOPMOST, HWND_NOTOPMOST = 0, 1, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFE


def _restack(p, wnd, after):
    """Move a child in its parent's list (top first): HWND_TOP, HWND_BOTTOM,
    or just below the window `after`."""
    siblings = wnd.parent.children if wnd.parent is not None and wnd in wnd.parent.children else None
    if siblings is None:
        return
    siblings.remove(wnd)
    if after in (HWND_TOP, HWND_TOPMOST, HWND_NOTOPMOST):
        siblings.insert(0, wnd)
    elif after == HWND_BOTTOM:
        siblings.append(wnd)
    else:
        other = _wnd(p, after)
        i = siblings.index(other) + 1 if other in siblings else 0
        siblings.insert(i, wnd)
    _changed(wnd)


@dll(7)
def SetWindowPos(p, hwnd, after, x, y, w, h, flags):
    wnd = _wnd(p, hwnd)
    if wnd is None:
        return 0
    if flags & 1:                                       # SWP_NOSIZE
        w, h = wnd.w + (gui.FRAME_W if wnd.top_level else 0), wnd.h + (gui.FRAME_H if wnd.top_level else 0)
    if flags & 2:                                       # SWP_NOMOVE
        x, y = wnd.x, wnd.y
    _move(p, wnd, _i32(x), _i32(y), _i32(w), _i32(h))
    if not flags & 0x4:                                 # SWP_NOZORDER not given: restack it
        _restack(p, wnd, after)
    if flags & 0x40:
        ShowWindow(p, hwnd, 5)
    if flags & 0x80:
        ShowWindow(p, hwnd, 0)
    return 1


@dll(1)
def GetSystemMetrics(p, n):
    sw, sh = getattr(p.ui, "screen_size", (1024, 768))
    return {0: sw, 1: sh, 4: 23, 5: 1, 6: 1, 7: 3, 8: 3, 11: 32, 12: 32, 15: 18, 16: sw, 17: sh - 40,
            32: 8, 33: 8, 43: 2, 49: 16, 50: 16, 80: 1}.get(n, 0)


@dll(2)
def ScreenToClient(p, hwnd, pt):
    w = _wnd(p, hwnd)
    if w:
        ox, oy = p.ui.client_origin(w) if hasattr(p.ui, "client_origin") else (0, 0)
        mem.put32(pt, mem.i32(pt) - ox)
        mem.put32(pt + 4, mem.i32(pt + 4) - oy)
    return 1


@dll(2)
def ClientToScreen(p, hwnd, pt):
    w = _wnd(p, hwnd)
    if w:
        ox, oy = p.ui.client_origin(w) if hasattr(p.ui, "client_origin") else (0, 0)
        mem.put32(pt, mem.i32(pt) + ox)
        mem.put32(pt + 4, mem.i32(pt + 4) + oy)
    return 1


@dll(1)
def GetCursorPos(p, pt):
    x, y = p.ui.mouse() if hasattr(p.ui, "mouse") else (0, 0)
    mem.put32(pt, x)
    mem.put32(pt + 4, y)
    return 1


# ---- text and extra data ----

@dll(2)
def SetWindowTextA(p, hwnd, text):
    return _set_text(p, hwnd, mem.cstr(text) or "")


@dll(2)
def SetWindowTextW(p, hwnd, text):
    return _set_text(p, hwnd, mem.wstr(text) or "")


def _set_text(p, hwnd, text):
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    w.title = text
    if w.host is not None:
        p.ui.title_window(w)
    _changed(w)
    return 1


@dll(3)
def GetWindowTextA(p, hwnd, buf, size):
    w = _wnd(p, hwnd)
    text = (w.title if w else "")[:max(0, size - 1)]
    if size:
        mem.put_cstr(buf, text)
    return len(text)


@dll(3)
def GetWindowTextW(p, hwnd, buf, size):
    w = _wnd(p, hwnd)
    text = (w.title if w else "")[:max(0, size - 1)]
    if size:
        mem.put_wstr(buf, text)
    return len(text)


@dll(1)
def GetWindowTextLengthA(p, hwnd):
    w = _wnd(p, hwnd)
    return len(w.title) if w else 0


dll.alias("GetWindowTextLengthW", "GetWindowTextLengthA")


@dll(3)
def SetDlgItemTextA(p, hwnd, item, text):
    return SetWindowTextA(p, GetDlgItem(p, hwnd, item), text)


@dll(4)
def GetDlgItemTextA(p, hwnd, item, buf, size):
    return GetWindowTextA(p, GetDlgItem(p, hwnd, item), buf, size)


@dll(4)
def GetDlgItemInt(p, hwnd, item, ok, signed):
    w = _wnd(p, GetDlgItem(p, hwnd, item))
    try:
        v = int((w.title if w else "").strip())
        good = 1
    except ValueError:
        v, good = 0, 0
    if ok:
        mem.put32(ok, good)
    return v


@dll(4)
def SetDlgItemInt(p, hwnd, item, value, signed):
    w = _wnd(p, GetDlgItem(p, hwnd, item))
    if w:
        _set_text(p, w.handle, str(_i32(value) if signed else value & 0xFFFFFFFF))
    return 1


GWL_WNDPROC, GWL_USERDATA, GWL_STYLE, GWL_ID = -4, -21, -16, -12


def proc_address(p, fn):
    """An address the program can call for a window procedure written in
    Python (a built-in control). Programs read it with GetWindowLongPtr to
    "subclass" a control and later pass it to CallWindowProc."""
    thunks = p.state.setdefault("proc_thunks", {})        # Python function -> address
    if fn not in thunks:
        def from_program(p, hwnd, msg, wparam, lparam):
            return fn(p, _wnd(p, hwnd), msg, wparam, lparam) if _wnd(p, hwnd) else 0
        addr = p._thunk(from_program, 4, "user32!<proc de control>")[1]
        thunks[fn] = addr
        p.state.setdefault("thunk_procs", {})[addr] = fn
    return thunks[fn]


def python_proc(p, addr):
    """The Python window procedure behind an address from proc_address (or None)."""
    return p.state.get("thunk_procs", {}).get(addr)


@dll(2)
def GetWindowLongPtrA(p, hwnd, index):
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    i = _i32(index)
    if i == GWL_USERDATA:
        return w.user_data
    if i == GWL_WNDPROC:
        return proc_address(p, w.proc) if callable(w.proc) else w.proc
    if i == GWL_STYLE:
        return w.style
    if i == GWL_ID:
        return w.id
    return w.extra.get(i, 0)


@dll(3)
def SetWindowLongPtrA(p, hwnd, index, value):
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    old = GetWindowLongPtrA(p, hwnd, index)
    i = _i32(index)
    if i == GWL_USERDATA:
        w.user_data = value
    elif i == GWL_WNDPROC:
        w.proc = python_proc(p, value) or value
    elif i == GWL_STYLE:
        w.style = value
    else:
        w.extra[i] = value
    return old


for _n in ("GetWindowLongPtrW", "GetWindowLongA", "GetWindowLongW"):
    dll.alias(_n, "GetWindowLongPtrA")
for _n in ("SetWindowLongPtrW", "SetWindowLongA", "SetWindowLongW"):
    dll.alias(_n, "SetWindowLongPtrA")


# ---- messages ----

def _changed(w):
    top = w
    while top.parent is not None and top.style & gui.WS_CHILD:
        top = top.parent
    top.changed = True


def _paint(p, w):
    """Send WM_PAINT to a window and its invalid children."""
    w.invalid = False
    _send(p, w, WM_PAINT)
    w.invalid = False
    for c in list(w.children):
        if c.invalid and c.visible:
            _paint(p, c)
    _changed(w)


def _invalid(windows):
    for w in windows:
        if w.invalid and w.visible:
            return w
    return None


def _next_message(p, hwnd, remove=True):
    """The next message for the program, or None. Like Windows: posted
    messages first, then WM_PAINT for windows that need it, then timers."""
    s = state(p)
    if p.killed:
        from pywin.process import Exit
        raise Exit(1)
    me = _thread.get_ident()
    for i, m in enumerate(s.queue):
        if (m[4] is None or m[4] == me) and (not hwnd or m[0] == hwnd):
            if remove:
                del s.queue[i]
            return m[:4]
    if me in s.quit:
        if remove:
            code = s.quit.pop(me)
            s.quit_sent = True
            return (0, WM_QUIT, code, 0)
        return (0, WM_QUIT, s.quit[me], 0)
    w = _invalid(x for x in s.windows.values() if getattr(x, "thread", None) in (None, me))
    if w is not None:
        if remove:
            w.invalid = False
            w.paint_pending = True
        return (w.handle, WM_PAINT, 0, 0)
    now = time.ticks_ms()
    for key, t in s.timers.items():
        if t[3] not in (None, me):                      # another thread's timer
            continue
        if time.ticks_diff(now, t[1]) >= 0:
            if remove:
                t[1] = time.ticks_add(now, t[0])
            return (key[0], WM_TIMER, key[1], t[2])
    return None


def _write_msg(at, m):
    hwnd, msg, wparam, lparam = m
    mem.put64(at, hwnd)
    mem.put32(at + 8, msg)
    mem.put64(at + 16, wparam)
    mem.put64(at + 24, lparam)
    mem.put32(at + 32, time.ticks_ms() & 0xFFFFFFFF)


@dll(4)
def GetMessageA(p, msg, hwnd, low, high):
    while True:
        m = _next_message(p, hwnd)
        if m is not None:
            _write_msg(msg, m)
            return 0 if m[1] == WM_QUIT else 1
        if getattr(state(p), "quit_sent", False) and not state(p).windows:
            _write_msg(msg, (0, WM_QUIT, 0, 0))
            return 0
        p.ui.wait(15)                       # let the desktop run


dll.alias("GetMessageW", "GetMessageA")


@dll(5)
def PeekMessageA(p, msg, hwnd, low, high, flags):
    m = _next_message(p, hwnd, remove=bool(flags & 1))
    if m is None:
        p.ui.wait(0)
        return 0
    _write_msg(msg, m)
    return 1


dll.alias("PeekMessageW", "PeekMessageA")


@dll(0)
def WaitMessage(p):
    while _next_message(p, 0, remove=False) is None:
        p.ui.wait(15)
    return 1


@dll(1)
def TranslateMessage(p, msg):
    return 0                    # the desktop already sends WM_CHAR


@dll(1)
def DispatchMessageA(p, msg):
    hwnd, m, wparam, lparam = mem.u64(msg), mem.u32(msg + 8), mem.u64(msg + 16), mem.u64(msg + 24)
    if m == WM_TIMER and lparam:
        return p.call(lparam, hwnd, WM_TIMER, wparam, time.ticks_ms() & 0xFFFFFFFF)
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    if m == WM_PAINT:
        w.paint_pending = False
        r = _send(p, w, m, wparam, lparam)
        for c in list(w.children):
            if c.invalid and c.visible:
                _paint(p, c)
        _changed(w)
        return r
    return _send(p, w, m, wparam, lparam)


dll.alias("DispatchMessageW", "DispatchMessageA")


@dll(2)
def IsDialogMessageA(p, hwnd, msg):
    return 0


dll.alias("IsDialogMessageW", "IsDialogMessageA")


@dll(4)
def SendMessageA(p, hwnd, msg, wparam, lparam):
    return _send(p, _wnd(p, hwnd), msg, wparam, lparam)


dll.alias("SendMessageW", "SendMessageA")


@dll(5)
def SendDlgItemMessageA(p, hwnd, item, msg, wparam, lparam):
    return SendMessageA(p, GetDlgItem(p, hwnd, item), msg, wparam, lparam)


@dll(4)
def PostMessageA(p, hwnd, msg, wparam, lparam):
    state(p).post(hwnd, msg, wparam, lparam)
    return 1


dll.alias("PostMessageW", "PostMessageA")


@dll(4)
def PostThreadMessageA(p, tid, msg, wparam, lparam):
    state(p).post(0, msg, wparam, lparam)
    return 1


@dll(1)
def PostQuitMessage(p, code):
    state(p).quit[_thread.get_ident()] = _i32(code)


@dll(4)
def DefWindowProcA(p, hwnd, msg, wparam, lparam):
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    if msg == WM_CLOSE:
        DestroyWindow(p, hwnd)
    elif msg == WM_NCCREATE:
        return 1
    elif msg == WM_ERASEBKGND:
        w.surface.fill(w.cls.background)
        return 1
    elif msg == WM_PAINT:
        from pywin.dlls import gdi32
        ps = p.heap.alloc(72)
        gdi32.BeginPaint(p, hwnd, ps)
        gdi32.EndPaint(p, hwnd, ps)
        p.heap.free(ps)
    elif msg == WM_SETTEXT:
        _set_text(p, hwnd, (mem.wstr(lparam) if getattr(w, "wide", False) else mem.cstr(lparam)) or "")
        return 1
    elif msg == WM_GETTEXT:
        return (GetWindowTextW if getattr(w, "wide", False) else GetWindowTextA)(p, hwnd, lparam, wparam)
    elif msg == WM_GETTEXTLENGTH:
        return len(w.title)
    return 0


dll.alias("DefWindowProcW", "DefWindowProcA")


@dll(5)
def CallWindowProcA(p, proc, hwnd, msg, wparam, lparam):
    if not proc:
        return 0
    fn = python_proc(p, proc)
    if fn is not None:                                   # a built-in control: straight to Python
        w = _wnd(p, hwnd)
        return fn(p, w, msg, wparam, lparam) if w else 0
    return p.call(proc, hwnd, msg, wparam, lparam)


dll.alias("CallWindowProcW", "CallWindowProcA")


# ---- painting the window again ----

@dll(3)
def InvalidateRect(p, hwnd, rect, erase):
    s = state(p)
    for w in ([s.windows[hwnd]] if hwnd in s.windows else s.windows.values()):
        w.invalid = True
        w.erase = w.erase or bool(erase)
    return 1


@dll(4)
def RedrawWindow(p, hwnd, rect, region, flags):
    InvalidateRect(p, hwnd, rect, 1)
    w = _wnd(p, hwnd)
    if w is not None and flags & 0x100:             # RDW_UPDATENOW
        _paint(p, w)
    return 1


@dll(2)
def ValidateRect(p, hwnd, rect):
    w = _wnd(p, hwnd)
    if w:
        w.invalid = False
    return 1


@dll(3)
def GetUpdateRect(p, hwnd, rect, erase):
    w = _wnd(p, hwnd)
    if rect and w:
        _put_rect(rect, 0, 0, w.w, w.h)
    return 1 if w and w.invalid else 0


# ---- timers ----

@dll(4)
def SetTimer(p, hwnd, n, ms, callback):
    s = state(p)
    if not n and not hwnd:
        n = 0x7000 + len(s.timers)
    owner = getattr(s.windows.get(hwnd), "thread", None) if hwnd else _thread.get_ident()
    s.timers[(hwnd, n)] = [max(10, ms), time.ticks_add(time.ticks_ms(), max(10, ms)), callback, owner]
    return n or 1


@dll(2)
def KillTimer(p, hwnd, n):
    return 1 if state(p).timers.pop((hwnd, n), None) else 0


# ---- input state ----

@dll(1)
def GetKeyState(p, vk):
    keys = getattr(p.ui, "keys_down", set())
    return 0xFF80 if vk in keys else 0


@dll(1)
def GetAsyncKeyState(p, vk):
    keys = getattr(p.ui, "keys_down", set())
    return 0x8000 if vk in keys else 0


@dll(1)
def SetCapture(p, hwnd):
    return 0


@dll(0)
def ReleaseCapture(p):
    return 1


@dll(1)
def ShowCursor(p, show):
    return 1


@dll(2)
def LoadCursorA(p, inst, name):
    return 0x20000 + (name & 0xFFFF)


for _n in ("LoadCursorW", "LoadIconA", "LoadIconW"):
    dll.alias(_n, "LoadCursorA")


@dll(1)
def SetCursor(p, cursor):
    return 0


@dll(6)
def LoadImageA(p, inst, name, kind, w, h, flags):
    return 0x20000


dll.alias("LoadImageW", "LoadImageA")


@dll(1)
def GetSysColor(p, n):
    r, g, b = gui.SYS_COLORS.get(n, (240, 240, 240))
    return r | g << 8 | b << 16


@dll(1)
def GetSysColorBrush(p, n):
    from pywin.dlls import gdi32
    return gdi32.new_object(p, gui.Brush(gui.SYS_COLORS.get(n, (240, 240, 240))))


@dll(3)
def CheckDlgButton(p, hwnd, item, on):
    w = _wnd(p, GetDlgItem(p, hwnd, item))
    if w:
        w.checked = on
        _changed(w)
    return 1


@dll(2)
def IsDlgButtonChecked(p, hwnd, item):
    w = _wnd(p, GetDlgItem(p, hwnd, item))
    return w.checked if w else 0


# ---- text formatting (user32 has its own sprintf) ----

@dll(2)
def wsprintfA(p, buf, fmt):
    data = cformat.printf(mem.cbytes(fmt), cformat.Args(p, 2))
    mem.write(buf, data[:1023] + b"\0")
    return min(len(data), 1023)


@dll(3)
def wvsprintfA(p, buf, fmt, va):
    data = cformat.printf(mem.cbytes(fmt), cformat.Args(p, va_list=va))
    mem.write(buf, data[:1023] + b"\0")
    return min(len(data), 1023)


@dll(1)
def CharUpperA(p, s):
    if s < 0x10000:
        return ord(chr(s).upper())
    mem.write(s, mem.cbytes(s).upper())
    return s


@dll(1)
def CharLowerA(p, s):
    if s < 0x10000:
        return ord(chr(s).lower())
    mem.write(s, mem.cbytes(s).lower())
    return s


# ---- menus: the bar above a window, pop-up menus, and menus from resources ----

def _menu(p, h):
    return state(p).menus.get(h)


def _new_menu(p, menu=None):
    s = state(p)
    h = 0x30000 + 2 * (len(s.menus) + 1)
    s.menus[h] = menu or gui.Menu()
    return h


@dll(0)
def CreateMenu(p):
    return _new_menu(p)


dll.alias("CreatePopupMenu", "CreateMenu")


def _append(p, h, flags, item, text):
    m = _menu(p, h)
    if m is None:
        return 0
    if flags & gui.MF_SEPARATOR:
        m.items.append(gui.MenuItem("", flags=flags))
    elif flags & gui.MF_POPUP:
        m.items.append(gui.MenuItem(text or "", popup=_menu(p, item), flags=flags))
    else:
        m.items.append(gui.MenuItem(text or "", item & 0xFFFF, flags=flags))
    return 1


@dll(4)
def AppendMenuA(p, h, flags, item, text):
    return _append(p, h, flags, item, mem.cstr(text) if text and not flags & gui.MF_SEPARATOR else "")


@dll(4)
def AppendMenuW(p, h, flags, item, text):
    return _append(p, h, flags, item, mem.wstr(text) if text and not flags & gui.MF_SEPARATOR else "")


def _item(p, h, which, flags):
    """A menu item by its command number, or by position (MF_BYPOSITION), in sub-menus too."""
    m = _menu(p, h)
    if m is None:
        return None
    if flags & gui.MF_BYPOSITION:
        return m.items[which] if 0 <= which < len(m.items) else None
    stack = [m]
    while stack:
        for it in stack.pop().items:
            if it.popup is not None:
                stack.append(it.popup)
            elif it.id == which:
                return it
    return None


@dll(3)
def CheckMenuItem(p, h, which, flags):
    it = _item(p, h, which, flags)
    if it is None:
        return 0xFFFFFFFF
    old = it.flags & gui.MF_CHECKED
    it.flags = (it.flags & ~gui.MF_CHECKED) | (flags & gui.MF_CHECKED)
    _menus_changed(p)
    return old


@dll(3)
def EnableMenuItem(p, h, which, flags):
    it = _item(p, h, which, flags)
    if it is None:
        return 0xFFFFFFFF
    old = it.flags & 3
    it.flags = (it.flags & ~3) | (flags & 3)
    _menus_changed(p)
    return old


@dll(5)
def ModifyMenuA(p, h, which, flags, ident, text):
    it = _item(p, h, which, flags)
    if it is not None:
        it.text = mem.cstr(text) if text else it.text
        it.flags = flags & ~gui.MF_BYPOSITION
        if not flags & gui.MF_POPUP:
            it.id = ident & 0xFFFF
        _menus_changed(p)
    return 1


@dll(3)
def DeleteMenu(p, h, which, flags):
    m = _menu(p, h)
    it = _item(p, h, which, flags)
    if m is not None and it in m.items:
        m.items.remove(it)
        _menus_changed(p)
    return 1


dll.alias("RemoveMenu", "DeleteMenu")


@dll(1)
def GetMenuItemCount(p, h):
    m = _menu(p, h)
    return len(m.items) if m else 0xFFFFFFFF


@dll(2)
def GetSubMenu(p, h, pos):
    m = _menu(p, h)
    if m is None or not 0 <= pos < len(m.items) or m.items[pos].popup is None:
        return 0
    sub = m.items[pos].popup
    for handle, other in state(p).menus.items():
        if other is sub:
            return handle
    return _new_menu(p, sub)


@dll(2)
def SetMenu(p, hwnd, h):
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    w.menu = _menu(p, h) if h else None
    if w.host is not None:
        p.ui.resize_window(w)
    _changed(w)
    return 1


@dll(1)
def GetMenu(p, hwnd):
    w = _wnd(p, hwnd)
    menu = getattr(w, "menu", None) if w else None
    for handle, other in (state(p).menus.items() if menu is not None else ()):
        if other is menu:
            return handle
    return 0


def _menus_changed(p):
    for w in state(p).windows.values():
        if getattr(w, "menu", None) is not None:
            _changed(w)


@dll(1)
def DrawMenuBar(p, hwnd):
    w = _wnd(p, hwnd)
    if w:
        _changed(w)
    return 1


@dll(1)
def DestroyMenu(p, h):
    return 1


@dll(7)
def TrackPopupMenu(p, h, flags, x, y, reserved, hwnd, rect):
    """A menu at the mouse. With TPM_RETURNCMD the choice is returned,
    otherwise it arrives as WM_COMMAND."""
    m = _menu(p, h)
    if m is None:
        return 0
    choice = p.ui.popup_menu(m, (_i32(x), _i32(y)))
    if flags & 0x100:                                   # TPM_RETURNCMD
        return choice or 0
    if choice:
        state(p).post(hwnd, WM_COMMAND, choice, 0)
    return 1


@dll(6)
def TrackPopupMenuEx(p, h, flags, x, y, hwnd, params):
    return TrackPopupMenu(p, h, flags, x, y, 0, hwnd, 0)


def _parse_menu(data):
    """A MENU resource (made by windres / rc) into a gui.Menu."""
    import struct
    at = 4 + struct.unpack_from("<H", data, 2)[0]       # after the header

    def text(at):
        chars = []
        while True:
            c = struct.unpack_from("<H", data, at)[0]
            at += 2
            if c == 0:
                return "".join(chars), at
            chars.append(chr(c))

    def level(at):
        menu = gui.Menu()
        while at < len(data):
            flags = struct.unpack_from("<H", data, at)[0]
            at += 2
            if flags & gui.MF_POPUP:
                label, at = text(at)
                sub, at = level(at)
                menu.items.append(gui.MenuItem(label, popup=sub, flags=flags & 0x0F))
            else:
                ident = struct.unpack_from("<H", data, at)[0]
                label, at = text(at + 2)
                if not label and not ident:
                    menu.items.append(gui.MenuItem("", flags=gui.MF_SEPARATOR))
                else:
                    menu.items.append(gui.MenuItem(label, ident, flags=flags & 0x0F))
            if flags & 0x80:                            # MF_END: the last item of this level
                break
        return menu, at

    return level(at)[0]


def _resource_name(name, wide):
    if name < 0x10000:
        return name
    return mem.wstr(name) if wide else mem.cstr(name)


def _load_menu(p, inst, name, wide):
    found = p.resource(inst, 4, _resource_name(name, wide))       # RT_MENU
    if not found:
        return 0
    return _new_menu(p, _parse_menu(mem.read(found[0], found[1])))


@dll(2)
def LoadMenuA(p, inst, name):
    return _load_menu(p, inst, name, False)


@dll(2)
def LoadMenuW(p, inst, name):
    return _load_menu(p, inst, name, True)


def _string(p, inst, n):
    """String n of the program's STRINGTABLE (stored 16 to a block)."""
    found = p.resource(inst, 6, n // 16 + 1)                        # RT_STRING
    if not found:
        return None
    at = found[0]
    for _ in range(n % 16):
        at += 2 + 2 * mem.u16(at)
    count = mem.u16(at)
    raw = mem.read(at + 2, 2 * count)
    return "".join(chr(raw[2 * k] | raw[2 * k + 1] << 8) for k in range(count))


@dll(4)
def LoadStringA(p, inst, n, buf, size):
    s = _string(p, inst, n)
    if s is None or size <= 0:
        return 0
    mem.put_cstr(buf, s[:size - 1])
    return min(len(s), size - 1)


@dll(4)
def LoadStringW(p, inst, n, buf, size):
    s = _string(p, inst, n)
    if s is None:
        return 0
    if size == 0:                                       # a pointer to the string itself is wanted
        return 0
    mem.put_wstr(buf, s[:size - 1])
    return min(len(s), size - 1)


@dll(2)
def LoadAcceleratorsA(p, inst, name):
    return 0x40001


dll.alias("LoadAcceleratorsW", "LoadAcceleratorsA")


@dll(3)
def TranslateAcceleratorA(p, hwnd, table, msg):
    return 0


dll.alias("TranslateAcceleratorW", "TranslateAcceleratorA")


# ---- message boxes ----

@dll(4)
def MessageBoxA(p, owner, text, caption, flags):
    return p.ui.message_box(mem.cstr(text) or "", mem.cstr(caption) or "Error", flags)


@dll(4)
def MessageBoxW(p, owner, text, caption, flags):
    return p.ui.message_box(mem.wstr(text) or "", mem.wstr(caption) or "Error", flags)


@dll(5)
def MessageBoxExA(p, owner, text, caption, flags, lang):
    return MessageBoxA(p, owner, text, caption, flags)


@dll(1)
def MessageBeep(p, kind):
    try:
        from kernel import sound
        sound.beep()
    except Exception:
        pass
    return 1


# ---- the built-in controls, written in Python ----

def _notify(p, w, code):
    """Tell the parent window something happened to a control (WM_COMMAND)."""
    if w.parent is not None:
        _send(p, w.parent, WM_COMMAND, (code << 16) | (w.id & 0xFFFF), w.handle)


def _button_kind(w):
    return w.style & 0xF


def _button_proc(p, w, msg, wparam, lparam):
    kind = _button_kind(w)
    if msg == WM_LBUTTONDOWN and w.enabled:
        w.pressed = True
        _changed(w)
    elif msg == WM_LBUTTONUP and w.pressed:
        w.pressed = False
        if kind in (BS_AUTOCHECKBOX,):
            w.checked = 0 if w.checked else 1
        elif kind == BS_AUTORADIOBUTTON:
            for c in (w.parent.children if w.parent else ()):
                if _button_kind(c) == BS_AUTORADIOBUTTON:
                    c.checked = 0
            w.checked = 1
        _changed(w)
        _notify(p, w, BN_CLICKED)
    elif msg == BM_GETCHECK:
        return w.checked
    elif msg == BM_SETCHECK:
        w.checked = wparam
        _changed(w)
    else:
        return DefWindowProcA(p, w.handle, msg, wparam, lparam)
    return 0


def _ui_font(size=13):
    import pygame
    return pygame.font.SysFont("sans", size)


def _button_render(w):
    import pygame
    s = w.surface
    kind = _button_kind(w)
    f = _ui_font()
    color = (40, 40, 40) if w.enabled else (150, 150, 150)
    if kind in (BS_CHECKBOX, BS_AUTOCHECKBOX, BS_RADIOBUTTON, BS_AUTORADIOBUTTON):
        s.fill(w.parent.cls.background if w.parent else (240, 240, 240))
        cy = w.h // 2
        if kind in (BS_RADIOBUTTON, BS_AUTORADIOBUTTON):
            pygame.draw.circle(s, (255, 255, 255), (8, cy), 6)
            pygame.draw.circle(s, (120, 120, 120), (8, cy), 6, 1)
            if w.checked:
                pygame.draw.circle(s, (0, 103, 192), (8, cy), 3)
        else:
            pygame.draw.rect(s, (255, 255, 255), (2, cy - 6, 13, 13))
            pygame.draw.rect(s, (120, 120, 120), (2, cy - 6, 13, 13), 1)
            if w.checked:
                pygame.draw.lines(s, (0, 103, 192), False, [(4, cy), (7, cy + 3), (13, cy - 4)], 2)
        img = f.render(w.title.replace("&", ""), True, color)
        s.blit(img, (20, cy - img.get_height() // 2))
        return
    if kind == BS_GROUPBOX:
        s.fill(w.parent.cls.background if w.parent else (240, 240, 240))
        pygame.draw.rect(s, (200, 200, 200), (0, 8, w.w, w.h - 8), 1)
        img = f.render(w.title, True, color)
        s.fill(w.parent.cls.background if w.parent else (240, 240, 240), (8, 0, img.get_width() + 4, 16))
        s.blit(img, (10, 0))
        return
    face = (204, 228, 247) if w.pressed else (225, 225, 225)
    s.fill(face)
    pygame.draw.rect(s, (0, 120, 215) if w.pressed else (173, 173, 173), (0, 0, w.w, w.h), 1)
    img = f.render(w.title.replace("&", ""), True, color)
    s.blit(img, ((w.w - img.get_width()) // 2, (w.h - img.get_height()) // 2))


def _static_proc(p, w, msg, wparam, lparam):
    return DefWindowProcA(p, w.handle, msg, wparam, lparam)


def _static_render(w):
    s = w.surface
    s.fill(w.parent.cls.background if w.parent else (240, 240, 240))
    f = _ui_font()
    y = 0
    for line in w.title.split("\n"):
        img = f.render(line, True, (0, 0, 0))
        x = (w.w - img.get_width()) // 2 if w.style & SS_CENTER else (
            w.w - img.get_width() if w.style & SS_RIGHT else 0)
        s.blit(img, (x, y))
        y += img.get_height()


def _edit_proc(p, w, msg, wparam, lparam):
    if msg == WM_LBUTTONDOWN:
        SetFocus(p, w.handle)
    elif msg == WM_CHAR and not w.style & ES_READONLY:
        c = wparam & 0xFFFF
        if c == 8:
            w.title = w.title[:-1]
        elif c == 13:
            if w.style & ES_MULTILINE:
                w.title += "\n"
        elif c >= 32:
            w.title += chr(c)
        else:
            return 0
        _changed(w)
        _notify(p, w, EN_CHANGE)
    else:
        return DefWindowProcA(p, w.handle, msg, wparam, lparam)
    return 0


def _edit_render(w):
    import pygame
    s = w.surface
    s.fill((255, 255, 255))
    focused = getattr(w, "has_focus", False)
    f = _ui_font()
    text = "*" * len(w.title) if w.style & ES_PASSWORD else w.title
    y = 3
    lines = text.split("\n") if w.style & ES_MULTILINE else [text]
    for line in lines:
        img = f.render(line, True, (0, 0, 0))
        x = 4 if img.get_width() < w.w - 8 else w.w - 8 - img.get_width()
        s.blit(img, (x, y))
        y += img.get_height()
    pygame.draw.rect(s, (0, 120, 215) if focused else (122, 122, 122), (0, 0, w.w, w.h), 1)


# ---- painting functions that Windows keeps in user32 (written in gdi32.py) ----
from pywin.dlls import gdi32 as _gdi    # noqa: E402

for _n in ("BeginPaint", "EndPaint", "GetDC", "GetWindowDC", "ReleaseDC", "FillRect", "FrameRect",
           "DrawTextA", "DrawTextW"):
    dll.functions[_n] = _gdi.dll.functions[_n]

from pywin.dlls import u32_extra, u32_dialogs, u32_images    # noqa: E402,F401  (the rest of user32)
