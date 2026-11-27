# comctl32.dll: the "common controls" of Windows, drawn with pygame.
#
#   image lists        many small pictures of the same size (toolbar icons)
#   ToolbarWindow32    a row of buttons with icons
#   ReBarWindow32      a strip that holds toolbars ("bands")
#   msctls_statusbar32 the bar at the bottom, in parts
#   SysTabControl32    tabs (one per open file in Notepad++)
#   tooltips_class32   the little help text (accepted, never shown)
#   msctls_trackbar32, msctls_updown32, msctls_progress32, SysListView32,
#   SysTreeView32, SysLink, SysHeader32: simple boxes that accept their messages
#
# Every control is a window with a Python window procedure (see user32.py:
# a Python "proc" is called directly) and a render function that draws it.
import pygame
from pywin import mem, gui
from pywin.dlls import Dll
from pywin.dlls.user32 import EXTRA_CLASSES, _wnd, _send, _changed, _i32, _ui_font, DefWindowProcA, \
    _put_rect, state
from pywin.dlls.gdi32 import new_object, _obj, _dc

dll = Dll("comctl32")
WM_NOTIFY, WM_SIZE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE = 0x4E, 0x05, 0x201, 0x202, 0x200
WM_RBUTTONUP, WM_LBUTTONDBLCLK, WM_SETFONT, WM_GETFONT, WM_PAINT = 0x205, 0x203, 0x30, 0x31, 0x0F
WM_PRINT, WM_PRINTCLIENT = 0x317, 0x318
NM_CLICK, NM_RCLICK, NM_DBLCLK = -2, -5, -3


def _notify(p, w, code, extra=b""):
    """Send WM_NOTIFY to the control's parent: an NMHDR (who, its number, what) and maybe more."""
    if w.parent is None:
        return 0
    block = p.heap.alloc(24 + len(extra) + 16)
    mem.put64(block, w.handle)
    mem.put64(block + 8, w.id)
    mem.put32(block + 16, code & 0xFFFFFFFF)
    mem.put32(block + 20, 0)
    if extra:
        mem.write(block + 24, extra)
    try:
        return _send(p, w.parent, WM_NOTIFY, w.id, block)
    finally:
        p.heap.free(block)


def _xy(lparam):
    x, y = lparam & 0xFFFF, (lparam >> 16) & 0xFFFF
    return (x - 0x10000 if x & 0x8000 else x), (y - 0x10000 if y & 0x8000 else y)


# ---- the DLL's functions ----

@dll(1)
def InitCommonControlsEx(p, info):
    return 1


@dll(0)
def InitCommonControls(p):
    pass


@dll(1)
def _TrackMouseEvent(p, info):
    return 1


@dll(4)
def SetWindowSubclass(p, hwnd, proc, ident, data):
    """A newer way to subclass: proc(hwnd, msg, wparam, lparam, ident, data) runs first."""
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    chain = w.extra.setdefault("subclasses", [])
    chain.insert(0, (proc, ident, data))
    if "subclass_base" not in w.extra:
        w.extra["subclass_base"] = w.proc
        w.proc = _subclassed
    return 1


def _subclassed(p, w, msg, wparam, lparam, depth=0):
    chain = w.extra.get("subclasses", [])
    if depth < len(chain):
        proc, ident, data = chain[depth]
        w.extra["subclass_depth"] = depth + 1
        return p.call(proc, w.handle, msg, wparam, lparam, ident, data)
    base = w.extra.get("subclass_base")
    if callable(base):
        return base(p, w, msg, wparam, lparam)
    return p.call(base, w.handle, msg, wparam, lparam) if base else 0


@dll(4)
def DefSubclassProc(p, hwnd, msg, wparam, lparam):
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    depth = w.extra.get("subclass_depth", 0)
    try:
        return _subclassed(p, w, msg, wparam, lparam, depth)
    finally:
        w.extra["subclass_depth"] = depth


@dll(3)
def RemoveWindowSubclass(p, hwnd, proc, ident):
    w = _wnd(p, hwnd)
    if w is not None:
        chain = w.extra.get("subclasses", [])
        chain[:] = [c for c in chain if not (c[0] == proc and c[1] == ident)]
    return 1


@dll(4)
def GetWindowSubclass(p, hwnd, proc, ident, data_out):
    w = _wnd(p, hwnd)
    for c in (w.extra.get("subclasses", []) if w else []):
        if c[0] == proc and c[1] == ident:
            if data_out:
                mem.put64(data_out, c[2])
            return 1
    return 0


@dll(3)
def TaskDialogIndirect(p, config, button, radio):
    if button:
        mem.put32(button, 1)                               # IDOK
    return 0


@dll(4)
def LoadIconMetric(p, inst, name, metric, out):
    """An icon from the program's resources at the small (0) or large (1) size."""
    from pywin.dlls.u32_images import load_icon
    from pywin.dlls.user32 import _resource_name
    size = 16 if metric == 0 else 32
    h = load_icon(p, inst, _resource_name(name, True), size, size)
    mem.put64(out, h)
    return 0 if h else 0x80070714                          # S_OK, or "resource not found"


@dll(5)
def LoadIconWithScaleDown(p, inst, name, w, h, out):
    from pywin.dlls.u32_images import load_icon
    from pywin.dlls.user32 import _resource_name
    icon = load_icon(p, inst, _resource_name(name, True), _i32(w), _i32(h))
    mem.put64(out, icon)
    return 0 if icon else 0x80070714


dll.alias("#380", "LoadIconMetric")
dll.alias("#381", "LoadIconWithScaleDown")
dll.alias("#17", "InitCommonControls")
dll.alias("#410", "SetWindowSubclass")
dll.alias("#412", "RemoveWindowSubclass")
dll.alias("#413", "DefSubclassProc")


# ---- image lists ----

ILD_TRANSPARENT = 1
ILC_MASK = 1


class ImageList:
    def __init__(self, w, h, flags):
        self.w, self.h, self.flags = max(1, w), max(1, h), flags
        self.images = []
        self.background = None


def _il(p, h):
    il = _obj(p, h)
    return il if isinstance(il, ImageList) else None


@dll(5)
def ImageList_Create(p, w, h, flags, initial, grow):
    return new_object(p, ImageList(_i32(w), _i32(h), flags))


@dll(1)
def ImageList_Destroy(p, h):
    from pywin.dlls.gdi32 import _objects
    if _il(p, h) is not None:
        _objects(p).pop(h, None)
    return 1


def _split(il, surface, key):
    """Cut a strip of pictures into images of the list's size."""
    first = len(il.images)
    for x in range(0, max(1, surface.get_width() // il.w) * il.w, il.w):
        img = surface.subsurface(pygame.Rect(x, 0, il.w, min(il.h, surface.get_height())))
        if key is not None:
            img.set_colorkey(key)
        il.images.append(img)
    return first


@dll(3)
def ImageList_Add(p, h, bitmap, mask):
    il, bmp = _il(p, h), _obj(p, bitmap)
    if il is None or not isinstance(bmp, gui.Bitmap):
        return -1 & 0xFFFFFFFF
    return _split(il, _surface(p, bmp), None)


@dll(3)
def ImageList_AddMasked(p, h, bitmap, key):
    il, bmp = _il(p, h), _obj(p, bitmap)
    if il is None or not isinstance(bmp, gui.Bitmap):
        return -1 & 0xFFFFFFFF
    return _split(il, _surface(p, bmp), gui.rgb(key))


def _surface(p, bmp):
    from pywin.dlls.gdi32 import _dib
    dib = getattr(bmp, "dib", None)
    if dib:                                                # a DIB section: its pixels are in memory
        bmp.surface = _dib(*dib)
    return bmp.surface


@dll(3)
def ImageList_ReplaceIcon(p, h, index, icon):
    il = _il(p, h)
    if il is None:
        return -1 & 0xFFFFFFFF
    img = _icon_surface(p, icon, il.w, il.h)
    i = _i32(index)
    if 0 <= i < len(il.images):
        il.images[i] = img
        return i
    il.images.append(img)
    return len(il.images) - 1


def _icon_surface(p, icon, w, h):
    """An icon as a picture: from LoadImage when PyWin knows it, else a plain square."""
    known = p.state.get("icons", {}).get(icon)
    if known is not None:
        return pygame.transform.scale(known, (w, h)) if known.get_size() != (w, h) else known
    img = pygame.Surface((w, h))
    img.fill((255, 0, 255))
    img.set_colorkey((255, 0, 255))
    pygame.draw.rect(img, (90, 120, 170), (2, 2, w - 4, h - 4), 1)
    return img


@dll(2)
def ImageList_Remove(p, h, index):
    il = _il(p, h)
    if il is None:
        return 0
    i = _i32(index)
    if i == -1:
        il.images = []
    elif 0 <= i < len(il.images):
        del il.images[i]
    return 1


@dll(1)
def ImageList_GetImageCount(p, h):
    il = _il(p, h)
    return len(il.images) if il else 0


@dll(2)
def ImageList_SetImageCount(p, h, n):
    il = _il(p, h)
    if il is not None:
        while len(il.images) < n:
            il.images.append(pygame.Surface((il.w, il.h)))
        del il.images[n:]
    return 1


@dll(3)
def ImageList_SetIconSize(p, h, w, hh):
    il = _il(p, h)
    if il is not None:
        il.w, il.h, il.images = max(1, _i32(w)), max(1, _i32(hh)), []
    return 1


@dll(3)
def ImageList_GetIconSize(p, h, w_out, h_out):
    il = _il(p, h)
    if il is None:
        return 0
    mem.put32(w_out, il.w)
    mem.put32(h_out, il.h)
    return 1


def draw_image(p, h, index, surface, x, y, faded=False):
    """Draw picture number index of image list h onto a pygame surface."""
    il = _il(p, h)
    if il is None or not 0 <= index < len(il.images):
        return False
    img = il.images[index]
    if faded:
        img = img.copy()
        img.set_alpha(110)
    surface.blit(img, (x, y))
    return True


@dll(6)
def ImageList_Draw(p, h, index, hdc, x, y, style):
    dc = _dc(p, hdc)
    if dc is None:
        return 0
    from pywin.dlls.g32_extra import clipped_blit
    il = _il(p, h)
    i = _i32(index)
    if il is None or not 0 <= i < len(il.images):
        return 0
    clipped_blit(dc, il.images[i], _i32(x), _i32(y))
    dc.changed()
    return 1


@dll(10)
def ImageList_DrawEx(p, h, index, hdc, x, y, w, hh, bk, fg, style):
    return ImageList_Draw(p, h, index, hdc, x, y, style)


@dll(3)
def ImageList_GetImageInfo(p, h, index, info):
    il = _il(p, h)
    if il is None or not 0 <= index < len(il.images):
        return 0
    mem.zero(info, 40)
    _put_rect(info + 24, index * il.w, 0, (index + 1) * il.w, il.h)
    return 1


@dll(3)
def ImageList_GetIcon(p, h, index, flags):
    il = _il(p, h)
    if il is None or not 0 <= index < len(il.images):
        return 0
    icons = p.state.setdefault("icons", {})
    handle = 0x40000 + 2 * len(icons) + 2
    icons[handle] = il.images[index]
    return handle


@dll(1)
def ImageList_Duplicate(p, h):
    il = _il(p, h)
    if il is None:
        return 0
    copy = ImageList(il.w, il.h, il.flags)
    copy.images = list(il.images)
    return new_object(p, copy)


@dll(2)
def ImageList_SetBkColor(p, h, color):
    return 0xFFFFFFFF                                      # CLR_NONE


for _name, _n in (("ImageList_BeginDrag", 4), ("ImageList_DragEnter", 3), ("ImageList_DragMove", 2),
                  ("ImageList_DragShowNolock", 1), ("ImageList_DragLeave", 1)):
    dll.functions[_name] = ((lambda p, *a: 1), _n)


@dll(0)
def ImageList_EndDrag(p):
    pass


# ---- ToolbarWindow32 ----

TB_ENABLEBUTTON, TB_CHECKBUTTON, TB_PRESSBUTTON, TB_HIDEBUTTON = 0x401, 0x402, 0x403, 0x404
TB_ISBUTTONENABLED, TB_ISBUTTONCHECKED, TB_ISBUTTONHIDDEN = 0x409, 0x40A, 0x40C
TB_SETSTATE, TB_GETSTATE, TB_ADDBITMAP, TB_DELETEBUTTON, TB_GETBUTTON, TB_BUTTONCOUNT = \
    0x411, 0x412, 0x413, 0x416, 0x417, 0x418
TB_COMMANDTOINDEX, TB_SAVERESTOREW, TB_GETITEMRECT, TB_BUTTONSTRUCTSIZE, TB_SETBUTTONSIZE = \
    0x419, 0x44C, 0x41D, 0x41E, 0x41F
TB_SETBITMAPSIZE, TB_AUTOSIZE, TB_GETTOOLTIPS, TB_SETTOOLTIPS, TB_SETPARENT = 0x420, 0x421, 0x423, 0x424, 0x425
TB_SETROWS, TB_GETROWS, TB_SETCMDID, TB_SETINDENT, TB_SETIMAGELIST, TB_GETIMAGELIST = \
    0x427, 0x428, 0x42A, 0x42F, 0x430, 0x431
TB_GETRECT, TB_SETHOTIMAGELIST, TB_GETHOTIMAGELIST, TB_SETDISABLEDIMAGELIST = 0x433, 0x434, 0x435, 0x436
TB_GETDISABLEDIMAGELIST, TB_GETBUTTONSIZE, TB_SETMAXTEXTROWS, TB_GETBUTTONINFOW = 0x437, 0x43A, 0x43C, 0x43F
TB_SETBUTTONINFOW, TB_INSERTBUTTONW, TB_ADDBUTTONSW, TB_GETMAXSIZE = 0x440, 0x443, 0x444, 0x453
TB_SETEXTENDEDSTYLE, TB_GETEXTENDEDSTYLE, TB_GETPADDING, TB_SETPADDING = 0x454, 0x455, 0x456, 0x457
TB_GETIDEALSIZE, TB_SETLISTGAP, TB_SETDRAWTEXTFLAGS, TB_GETHOTITEM, TB_SETHOTITEM = \
    0x463, 0x460, 0x446, 0x447, 0x448
TBSTATE_CHECKED, TBSTATE_PRESSED, TBSTATE_ENABLED, TBSTATE_HIDDEN = 1, 2, 4, 8
BTNS_SEP, BTNS_CHECK, BTNS_DROPDOWN = 1, 2, 8
SEPARATOR_W = 8
TBN_DROPDOWN = -710


class Button:
    def __init__(self, raw):
        self.image = _i32(int.from_bytes(raw[0:4], "little"))
        self.id = int.from_bytes(raw[4:8], "little")
        self.state, self.style = raw[8], raw[9]
        self.data = int.from_bytes(raw[16:24], "little")
        self.text = int.from_bytes(raw[24:32], "little")

    def raw(self):
        return (self.image & 0xFFFFFFFF).to_bytes(4, "little") + self.id.to_bytes(4, "little") + \
            bytes((self.state, self.style)) + bytes(6) + self.data.to_bytes(8, "little") + \
            self.text.to_bytes(8, "little")


def _tb(w):
    if "buttons" not in w.extra:
        w.extra.update(buttons=[], bitmap=(16, 16), size=(23, 22), images=0, hot=0, disabled=0, pressed=-1,
                       ext=0)
    return w.extra


def _tb_layout(w):
    """Each visible button's rectangle, left to right."""
    t = _tb(w)
    bw, bh = t["size"]
    x, out = 0, []
    for b in t["buttons"]:
        if b.state & TBSTATE_HIDDEN:
            out.append(None)
            continue
        width = SEPARATOR_W if b.style & BTNS_SEP else bw + (12 if b.style & BTNS_DROPDOWN else 0)
        out.append(pygame.Rect(x, 0, width, bh))
        x += width
    return out


def _tb_index(w, ident):
    for i, b in enumerate(_tb(w)["buttons"]):
        if b.id == ident and not b.style & BTNS_SEP:
            return i
    return -1


def _tb_set_state(w, ident, bit, on):
    i = _tb_index(w, ident)
    if i < 0:
        return 0
    b = _tb(w)["buttons"][i]
    b.state = (b.state | bit) if on else (b.state & ~bit)
    _changed(w)
    return 1


def _toolbar_proc(p, w, msg, wparam, lparam):
    t = _tb(w)
    msg &= 0xFFFF
    if msg == TB_BUTTONSTRUCTSIZE or msg == TB_SETMAXTEXTROWS or msg == TB_SETINDENT or msg == TB_SETLISTGAP:
        return 1
    if msg in (TB_ADDBUTTONSW, 0x414):                     # 0x414: TB_ADDBUTTONSA
        for k in range(wparam):
            t["buttons"].append(Button(mem.read(lparam + 32 * k, 32)))
        _changed(w)
        return 1
    if msg in (TB_INSERTBUTTONW, 0x415):
        i = _i32(wparam)
        b = Button(mem.read(lparam, 32))
        t["buttons"].insert(i if 0 <= i <= len(t["buttons"]) else len(t["buttons"]), b)
        _changed(w)
        return 1
    if msg == TB_DELETEBUTTON:
        if wparam < len(t["buttons"]):
            del t["buttons"][wparam]
            _changed(w)
            return 1
        return 0
    if msg == TB_BUTTONCOUNT:
        return len(t["buttons"])
    if msg == TB_GETBUTTON:
        if wparam >= len(t["buttons"]):
            return 0
        mem.write(lparam, t["buttons"][wparam].raw())
        return 1
    if msg == TB_COMMANDTOINDEX:
        return _tb_index(w, wparam) & 0xFFFFFFFFFFFFFFFF
    if msg == TB_ENABLEBUTTON:
        return _tb_set_state(w, wparam, TBSTATE_ENABLED, lparam & 0xFFFF)
    if msg == TB_CHECKBUTTON:
        return _tb_set_state(w, wparam, TBSTATE_CHECKED, lparam & 0xFFFF)
    if msg == TB_PRESSBUTTON:
        return _tb_set_state(w, wparam, TBSTATE_PRESSED, lparam & 0xFFFF)
    if msg == TB_HIDEBUTTON:
        return _tb_set_state(w, wparam, TBSTATE_HIDDEN, lparam & 0xFFFF)
    if msg in (TB_ISBUTTONENABLED, TB_ISBUTTONCHECKED, TB_ISBUTTONHIDDEN, TB_GETSTATE):
        i = _tb_index(w, wparam)
        if i < 0:
            return -1 & 0xFFFFFFFFFFFFFFFF if msg == TB_GETSTATE else 0
        st = t["buttons"][i].state
        if msg == TB_GETSTATE:
            return st
        bit = {TB_ISBUTTONENABLED: TBSTATE_ENABLED, TB_ISBUTTONCHECKED: TBSTATE_CHECKED,
               TB_ISBUTTONHIDDEN: TBSTATE_HIDDEN}[msg]
        return 1 if st & bit else 0
    if msg == TB_SETSTATE:
        i = _tb_index(w, wparam)
        if i >= 0:
            t["buttons"][i].state = lparam & 0xFF
            _changed(w)
        return 1 if i >= 0 else 0
    if msg == TB_SETBUTTONSIZE:
        t["size"] = (max(8, lparam & 0xFFFF), max(8, (lparam >> 16) & 0xFFFF))
        return 1
    if msg == TB_SETBITMAPSIZE:
        t["bitmap"] = (lparam & 0xFFFF, (lparam >> 16) & 0xFFFF)
        bw, bh = t["bitmap"]
        t["size"] = (max(t["size"][0], bw + 7), max(t["size"][1], bh + 6))
        return 1
    if msg == TB_GETBUTTONSIZE:
        return t["size"][0] | t["size"][1] << 16
    if msg in (TB_SETIMAGELIST, TB_SETHOTIMAGELIST, TB_SETDISABLEDIMAGELIST):
        key = {TB_SETIMAGELIST: "images", TB_SETHOTIMAGELIST: "hot", TB_SETDISABLEDIMAGELIST: "disabled"}[msg]
        old, t[key] = t[key], lparam
        if key == "images":
            il = _il(p, lparam)
            if il is not None:
                t["bitmap"] = (il.w, il.h)
                t["size"] = (il.w + 7, il.h + 6)
        _changed(w)
        return old
    if msg in (TB_GETIMAGELIST, TB_GETHOTIMAGELIST, TB_GETDISABLEDIMAGELIST):
        return t[{TB_GETIMAGELIST: "images", TB_GETHOTIMAGELIST: "hot", TB_GETDISABLEDIMAGELIST: "disabled"}[msg]]
    if msg == TB_AUTOSIZE:
        rects = [r for r in _tb_layout(w) if r]
        width = rects[-1].right if rects else 0
        if w.parent is not None and not w.extra.get("in_rebar"):
            w.resize(max(w.w, width), t["size"][1] + 4)
        _changed(w)
        return 0
    if msg in (TB_GETITEMRECT, TB_GETRECT):
        rects = _tb_layout(w)
        i = wparam if msg == TB_GETITEMRECT else _tb_index(w, wparam)
        if not 0 <= i < len(rects) or rects[i] is None:
            return 0
        r = rects[i]
        _put_rect(lparam, r.x, r.y, r.right, r.bottom)
        return 1
    if msg in (TB_GETMAXSIZE, TB_GETIDEALSIZE):
        rects = [r for r in _tb_layout(w) if r]
        out = lparam
        mem.put32(out, rects[-1].right if rects else 0)
        mem.put32(out + 4, t["size"][1])
        return 1
    if msg == TB_SETEXTENDEDSTYLE:
        old, t["ext"] = t["ext"], lparam
        return old
    if msg == TB_GETEXTENDEDSTYLE:
        return t["ext"]
    if msg == TB_GETPADDING:
        return 7 | 6 << 16
    if msg in (TB_SETPADDING, TB_SETPARENT, TB_SETTOOLTIPS, TB_SETROWS, TB_SETDRAWTEXTFLAGS, TB_SETHOTITEM):
        return 0
    if msg in (TB_GETTOOLTIPS, TB_GETROWS):
        return 0 if msg == TB_GETTOOLTIPS else 1
    if msg == TB_GETHOTITEM:
        return -1 & 0xFFFFFFFFFFFFFFFF
    if msg == TB_ADDBITMAP:
        # TBADDBITMAP: (module, bitmap number) or (0, HBITMAP): cut it into
        # pictures of the toolbar's bitmap size and add them to our own list
        inst, ident = mem.u64(lparam), mem.u64(lparam + 8)
        bmp = _obj(p, ident) if not inst else None
        if not isinstance(bmp, gui.Bitmap):
            from pywin.dlls.u32_images import load_bitmap
            bmp = _obj(p, load_bitmap(p, inst, ident)) if inst and inst != 0xFFFFFFFFFFFFFFFF else None
        own = t.setdefault("own", ImageList(t["bitmap"][0], t["bitmap"][1], 0))
        first = len(own.images)
        if isinstance(bmp, gui.Bitmap):
            _split(own, _surface(p, bmp), (192, 192, 192))      # classic toolbar grey = transparent
        while len(own.images) < first + max(1, wparam):        # a picture that could not be read: blank
            blank = pygame.Surface((own.w, own.h))
            blank.fill((255, 0, 254))
            blank.set_colorkey((255, 0, 254))
            own.images.append(blank)
        _changed(w)
        return first
    if msg == TB_SETCMDID:
        if wparam < len(t["buttons"]):
            t["buttons"][wparam].id = lparam
        return 1
    if msg in (TB_GETBUTTONINFOW, TB_SETBUTTONINFOW):
        return _tb_button_info(w, msg, wparam, lparam)
    if msg == TB_SAVERESTOREW:
        return 0
    if msg == WM_LBUTTONDOWN:
        x, y = _xy(lparam)
        t["pressed"] = _tb_hit(w, x, y)
        _changed(w)
        return 0
    if msg == WM_LBUTTONUP:
        x, y = _xy(lparam)
        i = _tb_hit(w, x, y)
        pressed, t["pressed"] = t["pressed"], -1
        _changed(w)
        if i >= 0 and i == pressed:
            b = t["buttons"][i]
            if b.state & TBSTATE_ENABLED and not b.style & BTNS_SEP:
                if b.style & BTNS_CHECK:
                    b.state ^= TBSTATE_CHECKED
                target = w.extra.get("notify_to") or w.parent
                if target is not None:
                    _send(p, target, gui.WM_COMMAND, b.id & 0xFFFF, w.handle)
        return 0
    if msg == WM_RBUTTONUP:
        _notify(p, w, NM_RCLICK)
        return 0
    return DefWindowProcA(p, w.handle, msg, wparam, lparam)


def _tb_hit(w, x, y):
    for i, r in enumerate(_tb_layout(w)):
        if r is not None and r.collidepoint(x, y):
            return i
    return -1


def _tb_button_info(w, msg, wparam, info):
    # TBBUTTONINFOW: size, mask, command, image, state, style, cx, lParam, text, text size
    mask = mem.u32(info + 4)
    by_index = mask & 0x80000000
    i = wparam if by_index else _tb_index(w, wparam)
    buttons = _tb(w)["buttons"]
    if not 0 <= i < len(buttons):
        return -1 & 0xFFFFFFFFFFFFFFFF
    b = buttons[i]
    if msg == TB_GETBUTTONINFOW:
        mem.put32(info + 8, b.id)
        mem.put32(info + 12, b.image & 0xFFFFFFFF)
        mem.put8(info + 16, b.state)
        mem.put8(info + 17, b.style)
        mem.put64(info + 24, b.data)
        return i
    if mask & 0x20:
        b.id = mem.u32(info + 8)
    if mask & 1:
        b.image = mem.i32(info + 12)
    if mask & 4:
        b.state = mem.u8(info + 16)
    if mask & 8:
        b.style = mem.u8(info + 17)
    if mask & 0x10:
        b.data = mem.u64(info + 24)
    _changed(w)
    return 1


def _toolbar_render(w):
    p = w.extra.get("process")
    t = _tb(w)
    w.surface.fill((240, 240, 240))
    bw, bh = t["bitmap"]
    for b, r in zip(t["buttons"], _tb_layout(w)):
        if r is None:
            continue
        if b.style & BTNS_SEP:
            pygame.draw.line(w.surface, (200, 200, 200), (r.centerx, 3), (r.centerx, r.bottom - 3))
            continue
        if b.state & (TBSTATE_CHECKED | TBSTATE_PRESSED) or t["pressed"] == t["buttons"].index(b):
            pygame.draw.rect(w.surface, (204, 228, 247), r)
            pygame.draw.rect(w.surface, (0, 120, 215), r, 1)
        enabled = b.state & TBSTATE_ENABLED
        if not t["images"] and "own" in t and 0 <= b.image < len(t["own"].images):    # from TB_ADDBITMAP
            img = t["own"].images[b.image]
            if not enabled:
                img = img.copy()
                img.set_alpha(110)
            w.surface.blit(img, (r.x + (r.w - bw) // 2, r.y + (r.h - bh) // 2))
            continue
        lists = (t["images"],) if enabled else (t["disabled"], t["images"])
        for il in lists:
            if p is not None and il and draw_image(p, il, b.image, w.surface, r.x + (bw and (r.w - bw) // 2),
                                                   r.y + (r.h - bh) // 2, faded=not enabled and il == t["images"]):
                break
        else:
            if p is not None and not t["images"]:
                pygame.draw.rect(w.surface, (150, 160, 180), r.inflate(-8, -8), 1)
        if b.style & BTNS_DROPDOWN:
            x = r.right - 9
            pygame.draw.polygon(w.surface, (60, 60, 60), [(x, r.centery - 1), (x + 5, r.centery - 1),
                                                          (x + 2, r.centery + 2)])


# ---- ReBarWindow32 ----

RB_DELETEBAND, RB_SETBARINFO, RB_GETRECT, RB_INSERTBANDW, RB_SETBANDINFOW = 0x402, 0x404, 0x409, 0x40A, 0x40B
RB_GETBANDCOUNT, RB_GETROWCOUNT, RB_GETROWHEIGHT, RB_IDTOINDEX, RB_SIZETORECT = 0x40C, 0x40D, 0x40E, 0x410, 0x417
RB_GETBARHEIGHT, RB_GETBANDINFOW, RB_GETBANDBORDERS, RB_SHOWBAND, RB_MAXIMIZEBAND = 0x41B, 0x41C, 0x422, 0x423, 0x41F
RB_MOVEBAND, RB_GETBANDMARGINS = 0x427, 0x428
RBBIM_STYLE, RBBIM_TEXT, RBBIM_CHILD, RBBIM_CHILDSIZE, RBBIM_SIZE, RBBIM_ID, RBBIM_IDEALSIZE, RBBIM_LPARAM = \
    1, 4, 0x10, 0x20, 0x40, 0x100, 0x200, 0x400
RBBS_HIDDEN, RBBS_BREAK = 8, 1
GRIPPER = 10


class Band:
    def __init__(self):
        self.style, self.child, self.min_w, self.min_h, self.cx, self.id, self.ideal, self.lparam = \
            0, 0, 0, 0, 0, 0, 0, 0


def _bands(w):
    return w.extra.setdefault("bands", [])


def _band_from(p, band, info):
    mask = mem.u32(info + 4)
    if mask & RBBIM_STYLE:
        band.style = mem.u32(info + 8)
    if mask & RBBIM_CHILD:
        band.child = mem.u64(info + 40)
    if mask & RBBIM_CHILDSIZE:
        band.min_w, band.min_h = mem.u32(info + 48), mem.u32(info + 52)
    if mask & RBBIM_SIZE:
        band.cx = mem.u32(info + 56)
    if mask & RBBIM_ID:
        band.id = mem.u32(info + 72)
    if mask & RBBIM_IDEALSIZE and mem.u32(info) >= 92:
        band.ideal = mem.u32(info + 88)
    if mask & RBBIM_LPARAM and mem.u32(info) >= 104:
        band.lparam = mem.u64(info + 96)


def _rebar_layout(p, w):
    """Put each band's child window in its place; the rebar is as tall as its tallest band."""
    from pywin.dlls.u32_extra import SetParent
    x, y, row_h = 0, 0, 0
    for band in _bands(w):
        c = _wnd(p, band.child)
        if band.style & RBBS_HIDDEN:
            if c is not None:
                c.visible = False
            continue
        width = max(band.cx, band.ideal, band.min_w) + GRIPPER
        if band.style & RBBS_BREAK and x > 0 or x + width > w.w and x > 0:
            x, y, row_h = 0, y + row_h, 0
        if c is not None:
            if c.parent is not w:
                SetParent(p, band.child, w.handle)
            c.extra["in_rebar"] = True
            c.extra["notify_to"] = c.extra.get("notify_to") or (w.parent if w.parent else None)
            c.visible = True
            c.x, c.y = x + GRIPPER, y
            c.resize(max(1, width - GRIPPER), max(band.min_h, 1))
        row_h = max(row_h, band.min_h + 2)
        x += width
    height = y + row_h
    if height and height != w.h:
        w.resize(w.w, height)
    _changed(w)
    return height


def _rebar_proc(p, w, msg, wparam, lparam):
    msg &= 0xFFFF
    bands = _bands(w)
    if msg == RB_INSERTBANDW or msg == 0x401:                 # 0x401: RB_INSERTBANDA
        band = Band()
        _band_from(p, band, lparam)
        i = _i32(wparam)
        bands.insert(i if 0 <= i <= len(bands) else len(bands), band)
        _rebar_layout(p, w)
        return 1
    if msg == RB_SETBANDINFOW or msg == 0x406:
        if wparam >= len(bands):
            return 0
        _band_from(p, bands[wparam], lparam)
        _rebar_layout(p, w)
        return 1
    if msg == RB_GETBANDINFOW or msg == 0x41D:
        if wparam >= len(bands):
            return 0
        b, info = bands[wparam], lparam
        mem.put32(info + 8, b.style)
        mem.put64(info + 40, b.child)
        mem.put32(info + 48, b.min_w)
        mem.put32(info + 52, b.min_h)
        mem.put32(info + 56, b.cx)
        mem.put32(info + 72, b.id)
        if mem.u32(info) >= 92:
            mem.put32(info + 88, b.ideal)
        if mem.u32(info) >= 104:
            mem.put64(info + 96, b.lparam)
        return 1
    if msg == RB_DELETEBAND:
        if wparam < len(bands):
            del bands[wparam]
            _rebar_layout(p, w)
            return 1
        return 0
    if msg == RB_GETBANDCOUNT:
        return len(bands)
    if msg == RB_IDTOINDEX:
        for i, b in enumerate(bands):
            if b.id == wparam:
                return i
        return -1 & 0xFFFFFFFFFFFFFFFF
    if msg == RB_SHOWBAND:
        if wparam < len(bands):
            b = bands[wparam]
            b.style = b.style & ~RBBS_HIDDEN if lparam else b.style | RBBS_HIDDEN
            _rebar_layout(p, w)
            return 1
        return 0
    if msg in (RB_GETBARHEIGHT, RB_GETROWHEIGHT):
        return w.h
    if msg == RB_GETROWCOUNT:
        return 1
    if msg == RB_GETRECT:
        if wparam >= len(bands):
            return 0
        c = _wnd(p, bands[wparam].child)
        if c is None:
            _put_rect(lparam, 0, 0, 0, 0)
        else:
            _put_rect(lparam, c.x - GRIPPER, c.y, c.x + c.w, c.y + c.h)
        return 1
    if msg == RB_GETBANDBORDERS:
        _put_rect(lparam, GRIPPER, 0, 0, 0)
        return 1
    if msg in (RB_SETBARINFO, RB_MAXIMIZEBAND, RB_MOVEBAND, RB_SIZETORECT, RB_GETBANDMARGINS):
        return 1
    if msg == WM_SIZE:
        _rebar_layout(p, w)
        return 0
    if msg == WM_NOTIFY or msg == gui.WM_COMMAND:             # what the toolbars say goes to our parent
        return _send(p, w.parent, msg, wparam, lparam) if w.parent else 0
    return DefWindowProcA(p, w.handle, msg, wparam, lparam)


def _rebar_render(w):
    w.surface.fill((240, 240, 240))
    for band in _bands(w):
        if band.style & RBBS_HIDDEN:
            continue
        p = w.extra.get("process")
        c = _wnd(p, band.child) if p else None
        if c is not None:
            for k in range(3):                                # the gripper: a few dots
                pygame.draw.rect(w.surface, (170, 170, 170), (c.x - GRIPPER + 3, c.y + 5 + 4 * k, 2, 2))


# ---- msctls_statusbar32 ----

SB_SETTEXTW, SB_GETTEXTW, SB_GETTEXTLENGTHW, SB_SETPARTS, SB_GETPARTS, SB_GETBORDERS = \
    0x40B, 0x40D, 0x40C, 0x404, 0x406, 0x407
SB_SETMINHEIGHT, SB_SIMPLE, SB_GETRECT, SB_SETICON, SB_SETTIPTEXTW, SB_ISSIMPLE = \
    0x408, 0x409, 0x40A, 0x40F, 0x411, 0x40E
SB_SETTEXTA, SB_GETTEXTA, SB_SETBKCOLOR = 0x401, 0x402, 0x2001
STATUS_H = 22


def _status(w):
    if "parts" not in w.extra:
        w.extra.update(parts=[-1], texts={}, simple=False, min_h=STATUS_H)
    return w.extra


def _status_place(p, w):
    """A status bar sits at the bottom of its parent, as wide as it."""
    s = _status(w)
    if w.parent is not None and not w.style & 0x4:            # CCS_NORESIZE
        h = max(STATUS_H, s["min_h"])
        w.x, w.y = 0, w.parent.h - h
        w.resize(w.parent.w, h)
    _changed(w)


def _part_rects(w):
    s = _status(w)
    if s["simple"]:
        return [pygame.Rect(0, 0, w.w, w.h)]
    out, x = [], 0
    for right in s["parts"]:
        r = w.w if _i32(right) == -1 else min(_i32(right), w.w)
        out.append(pygame.Rect(x, 0, max(0, r - x), w.h))
        x = r
    return out


def _status_proc(p, w, msg, wparam, lparam):
    s = _status(w)
    msg &= 0xFFFF
    if msg in (SB_SETTEXTW, SB_SETTEXTA):
        part = wparam & 0xFF
        if wparam & 0x1000:                                   # SBT_OWNERDRAW: no text of ours
            s["texts"][part] = ""
        elif lparam:
            s["texts"][part] = (mem.wstr(lparam) if msg == SB_SETTEXTW else mem.cstr(lparam)) or ""
        else:
            s["texts"][part] = ""
        _changed(w)
        return 1
    if msg in (SB_GETTEXTW, SB_GETTEXTA):
        text = s["texts"].get(wparam & 0xFF, "")
        if lparam:
            (mem.put_wstr if msg == SB_GETTEXTW else mem.put_cstr)(lparam, text)
        return len(text)
    if msg == SB_GETTEXTLENGTHW:
        return len(s["texts"].get(wparam & 0xFF, ""))
    if msg == SB_SETPARTS:
        n = max(1, min(wparam, 256))
        s["parts"] = [mem.i32(lparam + 4 * k) for k in range(n)]
        _changed(w)
        return 1
    if msg == SB_GETPARTS:
        if lparam:
            for k, v in enumerate(s["parts"][:wparam]):
                mem.put32(lparam + 4 * k, v)
        return len(s["parts"])
    if msg == SB_GETRECT:
        rects = _part_rects(w)
        if wparam >= len(rects):
            return 0
        r = rects[wparam]
        _put_rect(lparam, r.x, r.y, r.right, r.bottom)
        return 1
    if msg == SB_SIMPLE:
        s["simple"] = bool(wparam)
        _changed(w)
        return 0
    if msg == SB_ISSIMPLE:
        return 1 if s["simple"] else 0
    if msg == SB_SETMINHEIGHT:
        s["min_h"] = wparam
        return 0
    if msg == SB_GETBORDERS:
        for k, v in enumerate((0, 2, 2)):
            mem.put32(lparam + 4 * k, v)
        return 1
    if msg in (SB_SETICON, SB_SETTIPTEXTW, SB_SETBKCOLOR):
        return 1
    if msg == WM_SIZE or msg == 1:                            # WM_SIZE, WM_CREATE
        _status_place(p, w)
        return 0
    return DefWindowProcA(p, w.handle, msg, wparam, lparam)


def _status_render(w):
    s = _status(w)
    w.surface.fill((240, 240, 240))
    pygame.draw.line(w.surface, (215, 215, 215), (0, 0), (w.w, 0))
    font = _ui_font(12)
    for i, r in enumerate(_part_rects(w)):
        text = s["texts"].get(255 if s["simple"] else i, "")
        if text:
            img = font.render(text.replace("\t", "  "), True, (0, 0, 0))
            w.surface.blit(img, (r.x + 4, r.y + (r.h - img.get_height()) // 2), (0, 0, max(0, r.w - 6), r.h))
        if i < len(s["parts"]) - 1:
            pygame.draw.line(w.surface, (200, 200, 200), (r.right - 1, 3), (r.right - 1, r.bottom - 3))


# ---- SysTabControl32 ----

TCM_GETIMAGELIST, TCM_SETIMAGELIST, TCM_GETITEMCOUNT, TCM_DELETEITEM, TCM_DELETEALLITEMS = \
    0x1302, 0x1303, 0x1304, 0x1308, 0x1309
TCM_GETITEMRECT, TCM_GETCURSEL, TCM_SETCURSEL, TCM_HITTEST, TCM_ADJUSTRECT = 0x130A, 0x130B, 0x130C, 0x130D, 0x1328
TCM_SETITEMSIZE, TCM_SETPADDING, TCM_GETROWCOUNT, TCM_GETTOOLTIPS, TCM_GETCURFOCUS, TCM_SETCURFOCUS = \
    0x1329, 0x132B, 0x132C, 0x132D, 0x132F, 0x1330
TCM_SETMINTABWIDTH, TCM_SETEXTENDEDSTYLE, TCM_GETITEMW, TCM_SETITEMW, TCM_INSERTITEMW = \
    0x1331, 0x1334, 0x133C, 0x133D, 0x133E
TCM_HIGHLIGHTITEM, TCM_DESELECTALL, TCM_SETTOOLTIPS = 0x1333, 0x1332, 0x132E
TCIF_TEXT, TCIF_IMAGE, TCIF_PARAM, TCIF_STATE = 1, 2, 8, 0x10
TCN_SELCHANGE, TCN_SELCHANGING = -551, -552
TCS_OWNERDRAWFIXED, TCS_FIXEDWIDTH, TCS_BUTTONS, TCS_VERTICAL = 0x2000, 0x400, 0x100, 0x80
TAB_H = 24
WM_DRAWITEM = 0x2B


def _tabs(w):
    if "tabs" not in w.extra:
        w.extra.update(tabs=[], sel=-1, images=0, item_size=None, min_w=40)
    return w.extra


def _tab_set(tab, info):
    mask = mem.u32(info)
    if mask & TCIF_TEXT and mem.u64(info + 16):
        tab["text"] = mem.wstr(mem.u64(info + 16)) or ""
    if mask & TCIF_IMAGE:
        tab["image"] = mem.i32(info + 28)
    if mask & TCIF_PARAM:
        tab["param"] = mem.u64(info + 32)
    if mask & TCIF_STATE:
        tab["state"] = mem.u32(info + 4)


def _tab_rects(w):
    t = _tabs(w)
    font = _ui_font(12)
    out, x = [], 0
    height = t["item_size"][1] if t["item_size"] else TAB_H
    for tab in t["tabs"]:
        if t["item_size"] and w.style & TCS_FIXEDWIDTH:
            width = t["item_size"][0]
        else:
            width = max(t["min_w"], font.size(tab["text"])[0] + 16 + (18 if tab["image"] >= 0 else 0))
        out.append(pygame.Rect(x, 0, width, height))
        x += width
    return out


def _tab_changed(w):
    _changed(w)
    if w.style & TCS_OWNERDRAWFIXED:
        w.invalid = True                     # the program draws the tabs: ask it again (WM_PAINT)


def _tab_proc(p, w, msg, wparam, lparam):
    t = _tabs(w)
    msg &= 0xFFFF
    tabs = t["tabs"]
    if msg == TCM_INSERTITEMW:
        tab = {"text": "", "image": -1, "param": 0, "state": 0}
        _tab_set(tab, lparam)
        i = wparam if wparam <= len(tabs) else len(tabs)
        tabs.insert(i, tab)
        if t["sel"] < 0:
            t["sel"] = 0
        elif i <= t["sel"] and len(tabs) > 1:
            t["sel"] += 1
        _tab_changed(w)
        return i
    if msg == TCM_SETITEMW:
        if wparam >= len(tabs):
            return 0
        _tab_set(tabs[wparam], lparam)
        _tab_changed(w)
        return 1
    if msg == TCM_GETITEMW:
        if wparam >= len(tabs):
            return 0
        tab, info = tabs[wparam], lparam
        mask = mem.u32(info)
        if mask & TCIF_TEXT and mem.u64(info + 16):
            room = mem.u32(info + 24)
            if room:
                mem.put_wstr(mem.u64(info + 16), tab["text"][:room - 1])
        if mask & TCIF_IMAGE:
            mem.put32(info + 28, tab["image"])
        if mask & TCIF_PARAM:
            mem.put64(info + 32, tab["param"])
        if mask & TCIF_STATE:
            mem.put32(info + 4, tab["state"])
        return 1
    if msg == TCM_DELETEITEM:
        if wparam >= len(tabs):
            return 0
        del tabs[wparam]
        if t["sel"] >= len(tabs) or wparam < t["sel"]:
            t["sel"] = max(-1, t["sel"] - 1) if tabs else -1
        _tab_changed(w)
        return 1
    if msg == TCM_DELETEALLITEMS:
        tabs.clear()
        t["sel"] = -1
        _tab_changed(w)
        return 1
    if msg == TCM_GETITEMCOUNT:
        return len(tabs)
    if msg in (TCM_GETCURSEL, TCM_GETCURFOCUS):
        return t["sel"] & 0xFFFFFFFFFFFFFFFF
    if msg in (TCM_SETCURSEL, TCM_SETCURFOCUS):
        old = t["sel"]
        i = _i32(wparam)
        if 0 <= i < len(tabs):
            t["sel"] = i
            _tab_changed(w)
        return old & 0xFFFFFFFFFFFFFFFF
    if msg == TCM_GETITEMRECT:
        rects = _tab_rects(w)
        if wparam >= len(rects):
            return 0
        r = rects[wparam]
        _put_rect(lparam, r.x, r.y, r.right, r.bottom)
        return 1
    if msg == TCM_HITTEST:
        x, y = mem.i32(lparam), mem.i32(lparam + 4)
        for i, r in enumerate(_tab_rects(w)):
            if r.collidepoint(x, y):
                mem.put32(lparam + 8, 6)                        # TCHT_ONITEM
                return i
        mem.put32(lparam + 8, 1)                                # TCHT_NOWHERE
        return -1 & 0xFFFFFFFFFFFFFFFF
    if msg == TCM_ADJUSTRECT:
        height = t["item_size"][1] if t["item_size"] else TAB_H
        x0, y0, x1, y1 = (mem.i32(lparam + 4 * k) for k in range(4))
        if wparam:                                              # display area -> window
            _put_rect(lparam, x0 - 2, y0 - height - 2, x1 + 2, y1 + 2)
        else:                                                   # window -> display area
            _put_rect(lparam, x0 + 2, y0 + height + 2, x1 - 2, y1 - 2)
        return 0
    if msg == TCM_SETITEMSIZE:
        old = t["item_size"] or (0, TAB_H)
        t["item_size"] = (lparam & 0xFFFF, (lparam >> 16) & 0xFFFF)
        return old[0] | old[1] << 16
    if msg == TCM_SETMINTABWIDTH:
        old, t["min_w"] = t["min_w"], max(8, _i32(lparam))
        return old
    if msg == TCM_SETIMAGELIST:
        old, t["images"] = t["images"], lparam
        return old
    if msg == TCM_GETIMAGELIST:
        return t["images"]
    if msg == TCM_GETROWCOUNT:
        return 1
    if msg in (TCM_SETPADDING, TCM_SETEXTENDEDSTYLE, TCM_HIGHLIGHTITEM, TCM_DESELECTALL, TCM_SETTOOLTIPS,
               TCM_GETTOOLTIPS):
        return 0
    if msg == WM_LBUTTONDOWN:
        x, y = _xy(lparam)
        for i, r in enumerate(_tab_rects(w)):
            if r.collidepoint(x, y) and i != t["sel"]:
                if _i32(_notify(p, w, TCN_SELCHANGING)) == 0:  # the parent may say no
                    t["sel"] = i
                    _tab_changed(w)
                    _notify(p, w, TCN_SELCHANGE)
                break
        return 0
    if msg == WM_RBUTTONUP:
        _notify(p, w, NM_RCLICK)
        return 0
    if msg == WM_PAINT and w.style & TCS_OWNERDRAWFIXED:
        _tab_paint_owner_drawn(p, w)
        return 0
    if msg in (WM_PRINTCLIENT, WM_PRINT):                 # "draw yourself into this DC" (double buffering)
        dc = _dc(p, wparam)
        if dc is not None:
            if w.style & TCS_OWNERDRAWFIXED:
                _tab_paint_owner_drawn(p, w, wparam)
            else:
                _draw_tabs(w, dc.surface)
            dc.changed()
        return 0
    return DefWindowProcA(p, w.handle, msg, wparam, lparam)


def _tab_render(w):
    """Draw the tabs (from the desktop's thread). Owner-drawn tabs are left
    alone: the program draws them itself, on its own thread (WM_PAINT)."""
    if w.style & TCS_OWNERDRAWFIXED:
        return
    _draw_tabs(w, w.surface)


def _draw_tabs(w, surf):
    """The tabs, drawn by PyWin, onto surf."""
    t = _tabs(w)
    p = w.extra.get("process")
    surf.fill((240, 240, 240))
    font = _ui_font(12)
    rects = _tab_rects(w)
    for i, (tab, r) in enumerate(zip(t["tabs"], rects)):
        selected = i == t["sel"]
        pygame.draw.rect(surf, (255, 255, 255) if selected else (225, 225, 225), r)
        pygame.draw.rect(surf, (180, 180, 180), r, 1)
        if selected:
            pygame.draw.line(surf, (0, 120, 215), (r.x + 1, r.y + 1), (r.right - 2, r.y + 1), 2)
        x = r.x + 8
        if tab["image"] >= 0 and t["images"] and p is not None:
            if draw_image(p, t["images"], tab["image"], surf, x, r.y + (r.h - 16) // 2):
                x += 18
        img = font.render(tab["text"].replace("&&", "&"), True, (0, 0, 0))
        surf.blit(img, (x, r.y + (r.h - img.get_height()) // 2))
    if rects:
        pygame.draw.line(surf, (180, 180, 180), (0, rects[0].bottom - 1), (w.w, rects[0].bottom - 1))


def _tab_paint_owner_drawn(p, w, hdc=0):
    """Paint an owner-drawn tab control, on the program's thread: the
    background here, then WM_DRAWITEM to the parent for each tab. Onto the
    window itself (WM_PAINT) or onto the DC hdc (WM_PRINTCLIENT)."""
    t = _tabs(w)
    target = _dc(p, hdc).surface if hdc else w.surface
    target.fill((240, 240, 240))
    rects = _tab_rects(w)
    for i, (tab, r) in enumerate(zip(t["tabs"], rects)):
        _owner_draw_tab(p, w, i, tab, r, i == t["sel"], hdc)
    if rects:
        pygame.draw.line(target, (180, 180, 180), (0, rects[0].bottom - 1), (w.w, rects[0].bottom - 1))
    if not hdc:
        w.invalid = False
    _changed(w)


def _owner_draw_tab(p, w, i, tab, r, selected, given_dc=0):
    """Ask the parent to draw tab i (WM_DRAWITEM with a DRAWITEMSTRUCT),
    onto the window or onto the DC given."""
    if w.parent is None or w.extra.get("drawing"):
        return False
    from pywin.dlls.gdi32 import _objects
    hdc = given_dc or new_object(p, gui.DC(w))
    item = p.heap.alloc(64)
    try:
        w.extra["drawing"] = True
        mem.zero(item, 64)
        mem.put32(item, 101)                                    # ODT_TAB
        mem.put32(item + 4, w.id)
        mem.put32(item + 8, i)
        mem.put32(item + 12, 1)                                 # ODA_DRAWENTIRE
        mem.put32(item + 16, 1 if selected else 0)              # ODS_SELECTED
        mem.put64(item + 24, w.handle)
        mem.put64(item + 32, hdc)
        _put_rect(item + 40, r.x, r.y, r.right, r.bottom)
        mem.put64(item + 56, tab["param"])
        _send(p, w.parent, WM_DRAWITEM, w.id, item)
    finally:
        w.extra["drawing"] = False
        p.heap.free(item)
        if not given_dc:
            _objects(p).pop(hdc, None)
    return True


# ---- tooltips_class32 and the other controls: they take their messages quietly ----

TTM_ADDTOOLW, TTM_GETTOOLINFOW, TTM_SETMAXTIPWIDTH, TTM_ACTIVATE = 0x432, 0x435, 0x418, 0x401
TBM_GETPOS, TBM_SETPOS, TBM_SETRANGE = 0x400, 0x405, 0x406
PBM_SETPOS, PBM_SETRANGE32, UDM_SETRANGE32, UDM_SETPOS32, UDM_GETPOS32 = 0x402, 0x406, 0x46F, 0x471, 0x472


def _quiet_proc(p, w, msg, wparam, lparam):
    msg &= 0xFFFF
    if msg in (TTM_ADDTOOLW, TTM_ACTIVATE, TTM_SETMAXTIPWIDTH, 0x404):
        return 1
    if msg in (TBM_SETPOS, PBM_SETPOS, UDM_SETPOS32):
        old = w.extra.get("pos", 0)
        w.extra["pos"] = _i32(lparam if msg != PBM_SETPOS else wparam)
        _changed(w)
        return old
    if msg in (TBM_GETPOS, UDM_GETPOS32):
        return w.extra.get("pos", 0) & 0xFFFFFFFF
    if 0x400 <= msg < 0x2000 or 0x1000 <= msg < 0x1200:
        return 0                                                # list view / tree view / ... messages
    return DefWindowProcA(p, w.handle, msg, wparam, lparam)


def _quiet_render(w):
    white = w.cls.name.lower() in ("syslistview32", "systreeview32", "msctls_hotkey32")
    w.surface.fill((255, 255, 255) if white else (240, 240, 240))
    if white:
        pygame.draw.rect(w.surface, (130, 135, 144), (0, 0, w.w, w.h), 1)


# every process gets these classes (see EXTRA_CLASSES in user32.py); the
# render functions need the process, so it is remembered on WM_NCCREATE
def _with_process(proc):
    def wrapped(p, w, msg, wparam, lparam):
        w.extra["process"] = p
        return proc(p, w, msg, wparam, lparam)
    return wrapped


for _name, _proc, _render, _bg in (
        ("ToolbarWindow32", _toolbar_proc, _toolbar_render, (240, 240, 240)),
        ("ReBarWindow32", _rebar_proc, _rebar_render, (240, 240, 240)),
        ("msctls_statusbar32", _status_proc, _status_render, (240, 240, 240)),
        ("SysTabControl32", _tab_proc, _tab_render, (240, 240, 240)),
        ("tooltips_class32", _quiet_proc, None, (255, 255, 225)),
        ("msctls_trackbar32", _quiet_proc, _quiet_render, (240, 240, 240)),
        ("msctls_updown32", _quiet_proc, _quiet_render, (240, 240, 240)),
        ("msctls_progress32", _quiet_proc, _quiet_render, (240, 240, 240)),
        ("SysListView32", _quiet_proc, _quiet_render, (255, 255, 255)),
        ("SysTreeView32", _quiet_proc, _quiet_render, (255, 255, 255)),
        ("SysHeader32", _quiet_proc, _quiet_render, (240, 240, 240)),
        ("SysLink", _quiet_proc, _quiet_render, (240, 240, 240)),
        ("msctls_hotkey32", _quiet_proc, _quiet_render, (255, 255, 255))):
    EXTRA_CLASSES.append(gui.WndClass(_name, _with_process(_proc), _bg, render=_render))
