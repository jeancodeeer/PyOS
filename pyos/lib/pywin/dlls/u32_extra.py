# user32.dll, part 2: everything around the windows. Rectangles, the
# clipboard (shared with the SnakeyOS desktop), the text caret, scroll bars,
# window properties and relations, hooks, monitors, more of the menus,
# drawing edges and frames, and the keyboard state.
import struct
import time
from pywin import mem, gui, cformat
from pywin.dlls.user32 import dll, state, _wnd, _send, _changed, _put_rect, _set_text, _menu, _item, \
    _menus_changed, _i32
from pywin.dlls.user32 import GetDlgItem


def _rect(at):
    return [mem.i32(at + 4 * k) for k in range(4)]


# ---- rectangles ----

@dll(1)
def SetRectEmpty(p, r):
    mem.zero(r, 16)
    return 1


@dll(5)
def SetRect(p, r, x0, y0, x1, y1):
    _put_rect(r, _i32(x0), _i32(y0), _i32(x1), _i32(y1))
    return 1


@dll(3)
def InflateRect(p, r, dx, dy):
    x0, y0, x1, y1 = _rect(r)
    dx, dy = _i32(dx), _i32(dy)
    _put_rect(r, x0 - dx, y0 - dy, x1 + dx, y1 + dy)
    return 1


@dll(3)
def OffsetRect(p, r, dx, dy):
    x0, y0, x1, y1 = _rect(r)
    dx, dy = _i32(dx), _i32(dy)
    _put_rect(r, x0 + dx, y0 + dy, x1 + dx, y1 + dy)
    return 1


@dll(3)
def IntersectRect(p, out, a, b):
    ax0, ay0, ax1, ay1 = _rect(a)
    bx0, by0, bx1, by1 = _rect(b)
    x0, y0, x1, y1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
    if x0 >= x1 or y0 >= y1:
        mem.zero(out, 16)
        return 0
    _put_rect(out, x0, y0, x1, y1)
    return 1


@dll(3)
def UnionRect(p, out, a, b):
    ax0, ay0, ax1, ay1 = _rect(a)
    bx0, by0, bx1, by1 = _rect(b)
    _put_rect(out, min(ax0, bx0), min(ay0, by0), max(ax1, bx1), max(ay1, by1))
    return 1


@dll(2)
def EqualRect(p, a, b):
    return 1 if _rect(a) == _rect(b) else 0


@dll(1)
def IsRectEmpty(p, r):
    x0, y0, x1, y1 = _rect(r)
    return 1 if x1 <= x0 or y1 <= y0 else 0


@dll(2)
def PtInRect(p, r, pt):
    x0, y0, x1, y1 = _rect(r)
    x, y = _i32(pt & 0xFFFFFFFF), _i32(pt >> 32)            # the POINT comes in one register
    return 1 if x0 <= x < x1 and y0 <= y < y1 else 0


@dll(2)
def CopyRect(p, dst, src):
    mem.write(dst, mem.read(src, 16))
    return 1


@dll(4)
def MapWindowPoints(p, src, dst, pts, n):
    def origin(h):
        w = _wnd(p, h)
        if w is None:
            return 0, 0
        return p.ui.client_origin(w) if hasattr(p.ui, "client_origin") else (0, 0)
    sx, sy = origin(src)
    tx, ty = origin(dst)
    dx, dy = sx - tx, sy - ty
    for k in range(n):
        mem.put32(pts + 8 * k, mem.i32(pts + 8 * k) + dx)
        mem.put32(pts + 8 * k + 4, mem.i32(pts + 8 * k + 4) + dy)
    return ((dy & 0xFFFF) << 16) | (dx & 0xFFFF)


# ---- the clipboard: text goes to and from the SnakeyOS desktop's ----

CF_TEXT, CF_UNICODETEXT = 1, 13


@dll(1)
def OpenClipboard(p, hwnd):
    return 1


@dll(0)
def CloseClipboard(p):
    return 1


@dll(0)
def EmptyClipboard(p):
    p.state["clip_formats"] = {}
    return 1


@dll(2)
def SetClipboardData(p, fmt, h):
    from desktop import clipboard
    if fmt == CF_UNICODETEXT:
        clipboard.set(mem.wstr(h) or "")
    elif fmt == CF_TEXT:
        clipboard.set(mem.cstr(h) or "")
    else:
        p.state.setdefault("clip_formats", {})[fmt] = h       # private formats stay in the program
    return h


@dll(1)
def GetClipboardData(p, fmt):
    if fmt in (CF_UNICODETEXT, CF_TEXT):
        from desktop import clipboard
        text = clipboard.get() or ""
        block = p.heap.alloc(2 * len(text) + 4)
        if fmt == CF_UNICODETEXT:
            mem.put_wstr(block, text.replace("\n", "\r\n") if "\r" not in text else text)
        else:
            mem.put_cstr(block, text)
        return block
    return p.state.get("clip_formats", {}).get(fmt, 0)


@dll(1)
def IsClipboardFormatAvailable(p, fmt):
    if fmt in (CF_UNICODETEXT, CF_TEXT):
        from desktop import clipboard
        return 1 if clipboard.get() else 0
    return 1 if fmt in p.state.get("clip_formats", {}) else 0


@dll(1)
def RegisterClipboardFormatW(p, name):
    names = p.state.setdefault("clip_names", {})
    key = mem.wstr(name) or ""
    if key not in names:
        names[key] = 0xC000 + len(names) + 0x100
    return names[key]


dll.alias("RegisterWindowMessageW", "RegisterClipboardFormatW")   # both: a number per name


@dll(1)
def RegisterWindowMessageA(p, name):
    names = p.state.setdefault("clip_names", {})
    key = mem.cstr(name) or ""
    if key not in names:
        names[key] = 0xC000 + len(names) + 0x100
    return names[key]


@dll(1)
def AddClipboardFormatListener(p, hwnd):
    return 1


dll.alias("RemoveClipboardFormatListener", "AddClipboardFormatListener")


@dll(1)
def SetClipboardViewer(p, hwnd):
    return 0


@dll(2)
def ChangeClipboardChain(p, hwnd, nxt):
    return 0


@dll(0)
def CountClipboardFormats(p):
    return 1


# ---- the caret (the blinking text cursor) ----

@dll(4)
def CreateCaret(p, hwnd, bitmap, w, h):
    p.state["caret"] = {"hwnd": hwnd, "w": max(1, _i32(w)), "h": max(1, _i32(h)), "x": 0, "y": 0, "shown": 0}
    return 1


@dll(2)
def SetCaretPos(p, x, y):
    c = p.state.get("caret")
    if c:
        c["x"], c["y"] = _i32(x), _i32(y)
    return 1


@dll(1)
def GetCaretPos(p, out):
    c = p.state.get("caret") or {"x": 0, "y": 0}
    mem.put32(out, c["x"])
    mem.put32(out + 4, c["y"])
    return 1


@dll(1)
def ShowCaret(p, hwnd):
    c = p.state.get("caret")
    if c:
        c["shown"] += 1
    return 1


@dll(1)
def HideCaret(p, hwnd):
    c = p.state.get("caret")
    if c:
        c["shown"] -= 1
    return 1


@dll(0)
def DestroyCaret(p):
    p.state.pop("caret", None)
    return 1


@dll(0)
def GetCaretBlinkTime(p):
    return 530


@dll(1)
def SetCaretBlinkTime(p, ms):
    return 1


# ---- scroll bars: kept per window and bar; the program draws its own content ----

SB_HORZ, SB_VERT, SB_CTL, SB_BOTH = 0, 1, 2, 3
SIF_RANGE, SIF_PAGE, SIF_POS, SIF_TRACKPOS = 1, 2, 4, 0x10


def _bar(p, hwnd, which):
    bars = p.state.setdefault("scroll", {})
    return bars.setdefault((hwnd, which), {"min": 0, "max": 100, "page": 0, "pos": 0, "shown": True})


@dll(4)
def SetScrollInfo(p, hwnd, which, info, redraw):
    b = _bar(p, hwnd, which)
    mask = mem.u32(info + 4)
    if mask & SIF_RANGE:
        b["min"], b["max"] = mem.i32(info + 8), mem.i32(info + 12)
    if mask & SIF_PAGE:
        b["page"] = mem.u32(info + 16)
    if mask & SIF_POS:
        b["pos"] = mem.i32(info + 20)
    hi = max(b["min"], b["max"] - max(0, b["page"] - 1)) if b["page"] else b["max"]
    b["pos"] = max(b["min"], min(b["pos"], hi))
    return b["pos"]


@dll(3)
def GetScrollInfo(p, hwnd, which, info):
    b = _bar(p, hwnd, which)
    mask = mem.u32(info + 4)
    if mask & SIF_RANGE:
        mem.put32(info + 8, b["min"])
        mem.put32(info + 12, b["max"])
    if mask & SIF_PAGE:
        mem.put32(info + 16, b["page"])
    if mask & SIF_POS:
        mem.put32(info + 20, b["pos"])
    if mask & SIF_TRACKPOS:
        mem.put32(info + 24, b["pos"])
    return 1


@dll(5)
def SetScrollRange(p, hwnd, which, lo, hi, redraw):
    b = _bar(p, hwnd, which)
    b["min"], b["max"] = _i32(lo), _i32(hi)
    return 1


@dll(4)
def GetScrollRange(p, hwnd, which, lo, hi):
    b = _bar(p, hwnd, which)
    mem.put32(lo, b["min"])
    mem.put32(hi, b["max"])
    return 1


@dll(4)
def SetScrollPos(p, hwnd, which, pos, redraw):
    b = _bar(p, hwnd, which)
    old, b["pos"] = b["pos"], _i32(pos)
    return old


@dll(2)
def GetScrollPos(p, hwnd, which):
    return _bar(p, hwnd, which)["pos"]


@dll(3)
def ShowScrollBar(p, hwnd, which, show):
    for w in ((SB_HORZ, SB_VERT) if which == SB_BOTH else (which,)):
        _bar(p, hwnd, w)["shown"] = bool(show)
    return 1


@dll(3)
def EnableScrollBar(p, hwnd, which, arrows):
    return 1


@dll(3)
def GetScrollBarInfo(p, hwnd, obj, info):
    mem.zero(info + 4, 56)
    return 1


@dll(5)
def ScrollWindow(p, hwnd, dx, dy, rect, clip):
    w = _wnd(p, hwnd)
    if w is not None:
        dx, dy = _i32(dx), _i32(dy)
        old = w.surface.copy()
        w.surface.blit(old, (dx, dy))
        w.invalid = True                                  # the uncovered strip is painted again
        _changed(w)
    return 1


@dll(8)
def ScrollWindowEx(p, hwnd, dx, dy, rect, clip, region, update, flags):
    ScrollWindow(p, hwnd, dx, dy, rect, clip)
    return 1


# ---- windows: relations, properties, placement ----

GW_HWNDFIRST, GW_HWNDLAST, GW_HWNDNEXT, GW_HWNDPREV, GW_OWNER, GW_CHILD = 0, 1, 2, 3, 4, 5


@dll(2)
def GetWindow(p, hwnd, rel):
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    if rel == GW_CHILD:
        return w.children[0].handle if w.children else 0
    if rel == GW_OWNER:
        owner = getattr(w, "owner", None)
        return owner.handle if owner is not None else 0
    siblings = w.parent.children if w.parent is not None else \
        [x for x in state(p).windows.values() if x.parent is None]
    if w not in siblings:
        return 0
    i = siblings.index(w)
    j = {GW_HWNDFIRST: 0, GW_HWNDLAST: len(siblings) - 1, GW_HWNDNEXT: i + 1, GW_HWNDPREV: i - 1}.get(rel, -1)
    return siblings[j].handle if 0 <= j < len(siblings) else 0


@dll(2)
def IsChild(p, parent, child):
    w = _wnd(p, child)
    while w is not None and w.parent is not None:
        if w.parent.handle == parent:
            return 1
        w = w.parent
    return 0


@dll(2)
def SetParent(p, child, parent):
    w, new = _wnd(p, child), _wnd(p, parent)
    if w is None:
        return 0
    old = w.parent
    if old is not None and w in old.children:
        old.children.remove(w)
    w.parent = new
    if new is not None:
        new.children.append(w)
        w.style |= gui.WS_CHILD
    _changed(w)
    return old.handle if old is not None else 0


@dll(2)
def GetAncestor(p, hwnd, how):
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    if how == 1:                                             # GA_PARENT
        return w.parent.handle if w.parent is not None else 0
    while w.parent is not None:                              # GA_ROOT, GA_ROOTOWNER
        w = w.parent
    return w.handle


@dll(1)
def GetLastActivePopup(p, hwnd):
    return hwnd


@dll(2)
def GetWindowThreadProcessId(p, hwnd, pid):
    if pid:
        mem.put32(pid, 4)
    return 8


@dll(2)
def FindWindowW(p, cls, title):
    return 0                                                 # no other program's windows


@dll(4)
def FindWindowExW(p, parent, after, cls, title):
    return 0


dll.alias("FindWindowA", "FindWindowW")


def _class_of(w):
    return w.cls.name if w.cls else ""


@dll(3)
def GetClassNameW(p, hwnd, buf, size):
    w = _wnd(p, hwnd)
    name = _class_of(w) if w else ""
    if size:
        mem.put_wstr(buf, name[:size - 1])
    return min(len(name), size - 1)


@dll(3)
def GetClassNameA(p, hwnd, buf, size):
    w = _wnd(p, hwnd)
    name = _class_of(w) if w else ""
    if size:
        mem.put_cstr(buf, name[:size - 1])
    return min(len(name), size - 1)


@dll(3)
def EnumChildWindows(p, parent, fn, lparam):
    w = _wnd(p, parent)
    if w is None:
        return 0

    def every(win):
        for c in list(win.children):
            yield c
            for g in every(c):
                yield g
    for c in list(every(w)):
        if not p.call(fn, c.handle, lparam) & 0xFFFFFFFF:
            break
    return 1


@dll(3)
def EnumThreadWindows(p, tid, fn, lparam):
    for w in list(state(p).windows.values()):
        if w.parent is None and not p.call(fn, w.handle, lparam) & 0xFFFFFFFF:
            break
    return 1


dll.alias("EnumWindows", "EnumThreadWindows")


@dll(3)
def SetPropW(p, hwnd, name, value):
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    key = mem.wstr(name) if name >= 0x10000 else name
    w.extra[("prop", key)] = value
    return 1


@dll(2)
def GetPropW(p, hwnd, name):
    w = _wnd(p, hwnd)
    key = mem.wstr(name) if name >= 0x10000 else name
    return w.extra.get(("prop", key), 0) if w else 0


@dll(2)
def RemovePropW(p, hwnd, name):
    w = _wnd(p, hwnd)
    key = mem.wstr(name) if name >= 0x10000 else name
    return w.extra.pop(("prop", key), 0) if w else 0


@dll(1)
def IsZoomed(p, hwnd):
    w = _wnd(p, hwnd)
    return 1 if w is not None and getattr(w.host, "maximized", None) else 0


@dll(1)
def IsIconic(p, hwnd):
    w = _wnd(p, hwnd)
    return 1 if w is not None and getattr(w.host, "minimized", False) else 0


@dll(2)
def GetWindowPlacement(p, hwnd, out):
    w = _wnd(p, hwnd)
    mem.zero(out + 4, 40)
    mem.put32(out + 8, 1)                                    # SW_SHOWNORMAL
    if w is not None:
        _put_rect(out + 28, w.x, w.y, w.x + w.w + gui.FRAME_W, w.y + w.h + gui.FRAME_H)
    return 1


@dll(2)
def SetWindowPlacement(p, hwnd, wp):
    from pywin.dlls.user32 import MoveWindow
    x0, y0, x1, y1 = _rect(wp + 28)
    if x1 > x0 and y1 > y0:
        MoveWindow(p, hwnd, x0, y0, x1 - x0, y1 - y0, 1)
    return 1


@dll(1)
def BeginDeferWindowPos(p, n):
    return p.new_handle([])


@dll(8)
def DeferWindowPos(p, h, hwnd, after, x, y, cx, cy, flags):
    batch = p.handles.get(h)
    if isinstance(batch, list):
        batch.append((hwnd, after, x, y, cx, cy, flags))
    return h


@dll(1)
def EndDeferWindowPos(p, h):
    from pywin.dlls.user32 import SetWindowPos
    batch = p.handles.pop(h, [])
    for args in batch:
        SetWindowPos(p, *args)
    return 1


@dll(1)
def LockWindowUpdate(p, hwnd):
    return 1


@dll(1)
def FlashWindowEx(p, info):
    return 0


@dll(4)
def SetLayeredWindowAttributes(p, hwnd, key, alpha, flags):
    return 1


@dll(3)
def GetDCEx(p, hwnd, region, flags):
    from pywin.dlls import gdi32
    return gdi32.GetDC(p, hwnd)


@dll(4)
def NotifyWinEvent(p, event, hwnd, obj, child):
    pass


@dll(4)
def ChangeWindowMessageFilterEx(p, hwnd, msg, action, info):
    return 1


@dll(7)
def SendMessageTimeoutW(p, hwnd, msg, wparam, lparam, flags, timeout, result):
    r = _send(p, _wnd(p, hwnd), msg, wparam, lparam)
    if result:
        mem.put64(result, r or 0)
    return 1


@dll(3)
def GetUpdateRgn(p, hwnd, region, erase):
    w = _wnd(p, hwnd)
    return 2 if w is not None and w.invalid else 1           # SIMPLEREGION / NULLREGION


@dll(3)
def ChildWindowFromPointEx(p, hwnd, pt, flags):
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    x, y = _i32(pt & 0xFFFFFFFF), _i32(pt >> 32)
    child, _ = w.child_at((x, y))
    return child.handle


dll.alias("ChildWindowFromPoint", "ChildWindowFromPointEx")


@dll(1)
def WindowFromPoint(p, pt):
    x, y = _i32(pt & 0xFFFFFFFF), _i32(pt >> 32)
    for w in state(p).windows.values():
        if w.parent is None and w.host is not None and hasattr(p.ui, "client_origin"):
            ox, oy = p.ui.client_origin(w)
            if ox <= x < ox + w.w and oy <= y < oy + w.h:
                return w.child_at((x - ox, y - oy))[0].handle
    return 0


@dll(2)
def GetMenuBarInfo(p, hwnd, obj):
    return 0


@dll(2)
def GetComboBoxInfo(p, hwnd, info):
    return 0


# ---- hooks: accepted, never called ----

@dll(4)
def SetWindowsHookExW(p, kind, fn, module, tid):
    return 0x60000 + kind


dll.alias("SetWindowsHookExA", "SetWindowsHookExW")


@dll(1)
def UnhookWindowsHookEx(p, hook):
    return 1


@dll(4)
def CallNextHookEx(p, hook, code, wparam, lparam):
    return 0


# ---- monitors: one screen ----

MONITOR = 0x70001


def _screen(p):
    return getattr(p.ui, "screen_size", (1024, 768))


@dll(2)
def MonitorFromWindow(p, hwnd, flags):
    return MONITOR


dll.alias("MonitorFromRect", "MonitorFromWindow")
dll.alias("MonitorFromPoint", "MonitorFromWindow")


@dll(2)
def GetMonitorInfoW(p, mon, info):
    w, h = _screen(p)
    _put_rect(info + 4, 0, 0, w, h)
    _put_rect(info + 20, 0, 24, w, h - 60)                   # the work area: between top bar and dock
    mem.put32(info + 36, 1)                                  # MONITORINFOF_PRIMARY
    if mem.u32(info) >= 104:
        mem.put_wstr(info + 40, "\\\\.\\DISPLAY1")
    return 1


dll.alias("GetMonitorInfoA", "GetMonitorInfoW")


@dll(4)
def EnumDisplayMonitors(p, hdc, clip, fn, lparam):
    rect = p.heap.alloc(16)
    w, h = _screen(p)
    _put_rect(rect, 0, 0, w, h)
    p.call(fn, MONITOR, 0, rect, lparam)
    p.heap.free(rect)
    return 1


@dll(4)
def SystemParametersInfoW(p, action, param, out, flags):
    w, h = _screen(p)
    if action == 0x0030 and out:                             # SPI_GETWORKAREA
        _put_rect(out, 0, 24, w, h - 60)
    elif action == 0x0029 and out:                           # SPI_GETNONCLIENTMETRICS
        size = mem.u32(out) or 504
        mem.zero(out + 4, size - 4)
        for k, at in enumerate((4, 8, 12, 16, 20, 24)):
            mem.put32(out + at, (1, 17, 17, 22, 22, 22)[k])
        for font_at in (24 + 4, 24 + 4 + 92 + 8, 24 + 4 + 2 * 92 + 16, 24 + 4 + 3 * 92 + 16, 24 + 4 + 4 * 92 + 16):
            if font_at + 92 <= size:
                mem.put32(out + font_at, -12 & 0xFFFFFFFF)   # lfHeight
                mem.put32(out + font_at + 16, 400)           # lfWeight
                mem.put_wstr(out + font_at + 28, "Segoe UI")
    elif action == 0x001F and out:                           # SPI_GETICONTITLELOGFONT
        mem.zero(out, 92)
        mem.put32(out, -12 & 0xFFFFFFFF)
        mem.put32(out + 16, 400)
        mem.put_wstr(out + 28, "Segoe UI")
    elif action in (0x0068, 0x006A) and out:                 # wheel lines / chars
        mem.put32(out, 3)
    elif action == 0x2000 or action == 0x1022:               # focus border, client area animation...
        if out:
            mem.put32(out, 1)
    elif out:
        mem.put32(out, 0)
    return 1


@dll(4)
def SystemParametersInfoA(p, action, param, out, flags):
    return SystemParametersInfoW(p, action, param, out, flags)


@dll(5)
def SystemParametersInfoForDpi(p, action, param, out, flags, dpi):
    return SystemParametersInfoW(p, action, param, out, flags)


@dll(1)
def GetDpiForWindow(p, hwnd):
    return 96


@dll(0)
def GetDpiForSystem(p):
    return 96


@dll(1)
def SetProcessDpiAwarenessContext(p, ctx):
    return 1


@dll(0)
def SetProcessDPIAware(p):
    return 1


@dll(2)
def GetSystemMetricsForDpi(p, n, dpi):
    from pywin.dlls.user32 import GetSystemMetrics
    return GetSystemMetrics(p, n)


# ---- the keyboard and the mouse ----

@dll(1)
def GetKeyboardState(p, out):
    keys = getattr(p.ui, "keys_down", set())
    data = bytearray(256)
    for vk in keys:
        if 0 <= vk < 256:
            data[vk] = 0x80
    mem.write(out, bytes(data))
    return 1


@dll(5)
def ToAscii(p, vk, scan, state_ptr, out, flags):
    vk &= 0xFF
    ch = chr(vk) if 0x30 <= vk <= 0x39 or vk == 0x20 else (chr(vk + 32) if 0x41 <= vk <= 0x5A else "")
    if not ch:
        return 0
    mem.put16(out, ord(ch))
    return 1


@dll(2)
def MapVirtualKeyW(p, code, kind):
    return code & 0xFF


dll.alias("MapVirtualKeyA", "MapVirtualKeyW")


@dll(1)
def GetKeyboardLayout(p, tid):
    return 0x0C0A0C0A                                        # Spanish


@dll(2)
def GetKeyboardLayoutList(p, n, out):
    if n and out:
        mem.put64(out, 0x0C0A0C0A)
    return 1


@dll(5)
def mouse_event(p, flags, dx, dy, data, extra):
    pass


@dll(1)
def TrackMouseEvent(p, info):
    return 1


@dll(0)
def GetCapture(p):
    return state(p).__dict__.get("capture", 0)


@dll(0)
def GetMessageTime(p):
    return time.ticks_ms() & 0x7FFFFFFF


@dll(0)
def GetDoubleClickTime(p):
    return 500


@dll(5)
def MsgWaitForMultipleObjects(p, n, handles, wait_all, ms, mask):
    from pywin.dlls.user32 import _next_message
    end = time.ticks_add(time.ticks_ms(), ms if ms != 0xFFFFFFFF else 1 << 29)
    while True:
        if _next_message(p, 0, remove=False) is not None:
            return n                                         # WAIT_OBJECT_0 + n: a message
        if time.ticks_diff(end, time.ticks_ms()) <= 0:
            return 0x102                                     # WAIT_TIMEOUT
        p.ui.wait(10)


# ---- menus: the rest ----

MIIM_STATE, MIIM_ID, MIIM_SUBMENU, MIIM_DATA, MIIM_STRING, MIIM_FTYPE = 1, 2, 4, 0x20, 0x40, 0x100
MFT_SEPARATOR, MFS_CHECKED, MFS_DISABLED = 0x800, 8, 3


def _menu_item_from_info(p, info, item=None):
    """Read a MENUITEMINFOW into a gui.MenuItem (new, or the one given)."""
    mask = mem.u32(info + 4)
    item = item or gui.MenuItem("")
    if mask & MIIM_FTYPE or mask & 0x100:
        if mem.u32(info + 8) & MFT_SEPARATOR:
            item.flags |= gui.MF_SEPARATOR
    if mask & MIIM_STATE:
        st = mem.u32(info + 12)
        item.flags = (item.flags & ~0x0B) | (st & 0x0B)
    if mask & MIIM_ID:
        item.id = mem.u32(info + 16) & 0xFFFF
    if mask & MIIM_SUBMENU:
        sub = _menu(p, mem.u64(info + 24))
        if sub is not None:
            item.popup = sub
    if mask & MIIM_STRING or (mask & 0x10 and not mem.u32(info + 8) & MFT_SEPARATOR):
        text_ptr = mem.u64(info + 56)
        if text_ptr:
            item.text = mem.wstr(text_ptr) or ""
    return item


@dll(4)
def InsertMenuItemW(p, h, pos, by_position, info):
    m = _menu(p, h)
    if m is None:
        return 0
    item = _menu_item_from_info(p, info)
    if by_position:
        i = pos if pos < len(m.items) else len(m.items)
    else:
        found = _item(p, h, pos, 0)
        i = m.items.index(found) if found in m.items else len(m.items)
    m.items.insert(i, item)
    _menus_changed(p)
    return 1


@dll(4)
def SetMenuItemInfoW(p, h, which, by_position, info):
    it = _item(p, h, which, gui.MF_BYPOSITION if by_position else 0)
    if it is None:
        return 0
    _menu_item_from_info(p, info, it)
    _menus_changed(p)
    return 1


@dll(4)
def GetMenuItemInfoW(p, h, which, by_position, info):
    it = _item(p, h, which, gui.MF_BYPOSITION if by_position else 0)
    if it is None:
        return 0
    mask = mem.u32(info + 4)
    if mask & (MIIM_FTYPE | 0x100):
        mem.put32(info + 8, MFT_SEPARATOR if it.flags & gui.MF_SEPARATOR else 0)
    if mask & MIIM_STATE:
        mem.put32(info + 12, it.flags & 0x0B)
    if mask & MIIM_ID:
        mem.put32(info + 16, it.id)
    if mask & MIIM_SUBMENU:
        sub = 0
        for handle, m in state(p).menus.items():
            if m is it.popup and it.popup is not None:
                sub = handle
        mem.put64(info + 24, sub)
    if mask & MIIM_STRING or mask & 0x10:
        buf, room = mem.u64(info + 56), mem.u32(info + 64)
        if buf and room:
            mem.put_wstr(buf, it.text[:room - 1])
        mem.put32(info + 64, len(it.text))
    return 1


@dll(5)
def InsertMenuW(p, h, pos, flags, ident, text):
    m = _menu(p, h)
    if m is None:
        return 0
    label = mem.wstr(text) if text and not flags & gui.MF_SEPARATOR else ""
    if flags & gui.MF_SEPARATOR:
        item = gui.MenuItem("", flags=gui.MF_SEPARATOR)
    elif flags & gui.MF_POPUP:
        item = gui.MenuItem(label, popup=_menu(p, ident), flags=flags & 0x0F)
    else:
        item = gui.MenuItem(label, ident & 0xFFFF, flags=flags & 0x0F)
    if flags & gui.MF_BYPOSITION:
        i = pos if pos < len(m.items) else len(m.items)
    else:
        found = _item(p, h, pos, 0)
        i = m.items.index(found) if found in m.items else len(m.items)
    m.items.insert(i, item)
    _menus_changed(p)
    return 1


@dll(5)
def ModifyMenuW(p, h, which, flags, ident, text):
    it = _item(p, h, which, flags)
    if it is not None:
        if text and not flags & gui.MF_SEPARATOR:
            it.text = mem.wstr(text) or it.text
        it.flags = flags & 0x0F | (flags & gui.MF_SEPARATOR)
        if flags & gui.MF_POPUP:
            it.popup = _menu(p, ident)
        else:
            it.id = ident & 0xFFFF
        _menus_changed(p)
    return 1


@dll(3)
def GetMenuState(p, h, which, flags):
    it = _item(p, h, which, flags)
    if it is None:
        return 0xFFFFFFFF
    count = len(it.popup.items) << 8 if it.popup is not None else 0
    return count | (it.flags & 0x0B) | (gui.MF_POPUP if it.popup is not None else 0)


@dll(2)
def GetMenuItemID(p, h, pos):
    m = _menu(p, h)
    if m is None or not 0 <= pos < len(m.items):
        return 0xFFFFFFFF
    it = m.items[pos]
    return 0xFFFFFFFF if it.popup is not None else it.id


@dll(5)
def GetMenuStringW(p, h, which, buf, size, flags):
    it = _item(p, h, which, flags)
    text = it.text if it is not None else ""
    if buf and size:
        mem.put_wstr(buf, text[:size - 1])
    return len(text)


@dll(5)
def CheckMenuRadioItem(p, h, first, last, check, flags):
    m = _menu(p, h)
    if m is None:
        return 0
    for k in range(first, last + 1):
        it = _item(p, h, k, flags)
        if it is not None:
            it.flags = (it.flags & ~gui.MF_CHECKED) | (gui.MF_CHECKED if k == check else 0)
    _menus_changed(p)
    return 1


@dll(5)
def SetMenuItemBitmaps(p, h, pos, flags, unchecked, checked):
    return 1


@dll(2)
def CreateAcceleratorTableW(p, entries, n):
    return p.new_handle(mem.read(entries, 6 * n) if n > 0 else b"")


@dll(1)
def DestroyAcceleratorTable(p, h):
    p.handles.pop(h, None)
    return 1


# ---- drawing helpers that live in user32 ----

def _gdi():
    from pywin.dlls import gdi32
    return gdi32


@dll(4)
def DrawEdge(p, hdc, rect, edge, flags):
    import pygame
    dc = _gdi()._dc(p, hdc)
    if dc is None:
        return 0
    x0, y0, x1, y1 = _rect(rect)
    light, dark = (255, 255, 255), (160, 160, 160)
    sunken = edge & 0x0A                                     # BDR_SUNKENOUTER / INNER
    tl, br = (dark, light) if sunken else (light, dark)
    if flags & 1:
        pygame.draw.line(dc.surface, tl, (x0, y0), (x0, y1 - 1))
    if flags & 2:
        pygame.draw.line(dc.surface, tl, (x0, y0), (x1 - 1, y0))
    if flags & 4:
        pygame.draw.line(dc.surface, br, (x1 - 1, y0), (x1 - 1, y1 - 1))
    if flags & 8:
        pygame.draw.line(dc.surface, br, (x0, y1 - 1), (x1 - 1, y1 - 1))
    dc.changed()
    return 1


@dll(4)
def DrawFrameControl(p, hdc, rect, kind, flags):
    import pygame
    dc = _gdi()._dc(p, hdc)
    if dc is None:
        return 0
    x0, y0, x1, y1 = _rect(rect)
    r = pygame.Rect(x0, y0, max(1, x1 - x0), max(1, y1 - y0))
    pygame.draw.rect(dc.surface, (225, 225, 225), r)
    pygame.draw.rect(dc.surface, (160, 160, 160), r, 1)
    if kind == 1 and flags & 0x0400:                         # a checked check box
        pygame.draw.lines(dc.surface, (0, 0, 0), False, [(r.x + 3, r.centery), (r.centerx - 1, r.bottom - 4),
                                                         (r.right - 3, r.y + 3)], 2)
    dc.changed()
    return 1


@dll(2)
def DrawFocusRect(p, hdc, rect):
    import pygame
    dc = _gdi()._dc(p, hdc)
    if dc is not None:
        x0, y0, x1, y1 = _rect(rect)
        pygame.draw.rect(dc.surface, (120, 120, 120), (x0, y0, max(1, x1 - x0), max(1, y1 - y0)), 1)
        dc.changed()
    return 1


@dll(6)
def DrawTextExW(p, hdc, text, n, rect, flags, params):
    from pywin.dlls import gdi32
    return gdi32.dll.functions["DrawTextW"][0](p, hdc, text, n, rect, flags)


@dll(9)
def DrawIconEx(p, hdc, x, y, icon, w, h, step, brush, flags):
    return 1


@dll(4)
def DrawIcon(p, hdc, x, y, icon):
    return 1


@dll(1)
def DestroyIcon(p, icon):
    return 1


dll.alias("DestroyCursor", "DestroyIcon")


@dll(1)
def CreateIconIndirect(p, info):
    return p.new_handle(("icon", mem.read(info, 32)))


@dll(2)
def GetIconInfo(p, icon, out):
    mem.zero(out, 32)
    mem.put32(out, 1)
    return 1


@dll(2)
def LoadBitmapW(p, inst, name):
    from pywin.dlls import gdi32
    return gdi32.new_object(p, gui.Bitmap(16, 16))


# ---- text: wsprintfW ----

@dll(2)
def wsprintfW(p, buf, fmt):
    text = cformat.printf(mem.wstr(fmt).encode(), cformat.Args(p, 2)).decode()
    mem.put_wstr(buf, text[:1023])
    return min(len(text), 1023)


@dll(3)
def wvsprintfW(p, buf, fmt, va):
    text = cformat.printf(mem.wstr(fmt).encode(), cformat.Args(p, va_list=va)).decode()
    mem.put_wstr(buf, text[:1023])
    return min(len(text), 1023)


@dll(3)
def SetDlgItemTextW(p, hwnd, item, text):
    return _set_text(p, GetDlgItem(p, hwnd, item), mem.wstr(text) or "")


@dll(4)
def GetDlgItemTextW(p, hwnd, item, buf, size):
    from pywin.dlls.user32 import GetWindowTextW
    return GetWindowTextW(p, GetDlgItem(p, hwnd, item), buf, size)


@dll(5)
def SendDlgItemMessageW(p, hwnd, item, msg, wparam, lparam):
    return _send(p, _wnd(p, GetDlgItem(p, hwnd, item)), msg, wparam, lparam)


@dll(1)
def LoadCursorFromFileW(p, name):
    return 0x20001


@dll(2)
def LoadIconW(p, inst, name):
    return 0x20000 + (name & 0xFFFF)


dll.alias("LoadCursorW", "LoadIconW")


@dll(1)
def IsWindowUnicode(p, hwnd):
    return 1


@dll(1)
def GetWindowDpiAwarenessContext(p, hwnd):
    return 0x12


@dll(1)
def AllowSetForegroundWindow(p, pid):
    return 1


@dll(2)
def SetWindowRgn(p, hwnd, region):
    return 1


# the character tests live in kernel32's text part; user32 exports them too
from pywin.dlls import k32_text as _text    # noqa: E402
for _name in ("CharUpperW", "CharLowerW", "IsCharAlphaW", "IsCharAlphaNumericW", "IsCharLowerW", "IsCharUpperW"):
    dll.functions[_name] = _text.dll.functions[_name]


# ---- reading a window class back (programs do it to "superclass" a control) ----

def _class_info(p, inst, name_ptr, out, wide, ex):
    from pywin.dlls.user32 import _class_name, proc_address
    name = _class_name(p, name_ptr, wide)
    cls = state(p).classes.get(name.lower())
    if cls is None:
        p.last_error = 1411                                  # ERROR_CLASS_DOES_NOT_EXIST
        return 0
    at = out + 4 if ex else out                              # WNDCLASSEX starts with its size
    mem.put32(at, cls.style)
    mem.put64(at + 4, proc_address(p, cls.proc) if callable(cls.proc) else cls.proc)
    mem.put32(at + 12, 0)
    mem.put32(at + 16, cls.extra)
    mem.put64(at + 20, inst)
    for off in (28, 36, 44, 52):                             # icon, cursor, brush, menu name
        mem.put64(at + off, 0)
    mem.put64(at + 60, name_ptr)
    return 0xC000 + 1


@dll(3)
def GetClassInfoExW(p, inst, name, out):
    return _class_info(p, inst, name, out, True, True)


@dll(3)
def GetClassInfoW(p, inst, name, out):
    return _class_info(p, inst, name, out, True, False)


@dll(3)
def GetClassInfoExA(p, inst, name, out):
    return _class_info(p, inst, name, out, False, True)


@dll(2)
def GetClassLongPtrW(p, hwnd, index):
    w = _wnd(p, hwnd)
    if w is None or not w.cls:
        return 0
    i = _i32(index)
    if i == -26:                                             # GCL_STYLE
        return w.cls.style
    if i == -24:                                             # GCLP_WNDPROC
        from pywin.dlls.user32 import proc_address
        return proc_address(p, w.cls.proc) if callable(w.cls.proc) else w.cls.proc
    return 0


@dll(3)
def SetClassLongPtrW(p, hwnd, index, value):
    w = _wnd(p, hwnd)
    if w is None or not w.cls:
        return 0
    if _i32(index) == -26:
        old, w.cls.style = w.cls.style, value
        return old
    return 0


for _name in ("GetClassLongW", "GetClassLongA", "GetClassLongPtrA"):
    dll.alias(_name, "GetClassLongPtrW")
for _name in ("SetClassLongW", "SetClassLongPtrA"):
    dll.alias(_name, "SetClassLongPtrW")


@dll(1)
def BringWindowToTop(p, hwnd):
    from pywin.dlls.user32 import _restack, SetActiveWindow
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    if w.parent is not None:
        _restack(p, w, 0)                                    # HWND_TOP among its siblings
        return 1
    return SetActiveWindow(p, hwnd)
