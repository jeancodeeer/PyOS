# gdi32.dll: drawing on windows and bitmaps (with pygame).
#
# HDC, HPEN, HBRUSH, HFONT and HBITMAP are handles to the Python objects in
# pywin/gui.py. BeginPaint / GetDC give a DC for a window; SelectObject
# chooses the pen (lines), the brush (fills) and the font of a DC.
import pygame
from pywin import mem
from pywin.dlls import Dll
from pywin import gui

dll = Dll("gdi32")
TRANSPARENT, OPAQUE = 1, 2
SRCCOPY = 0x00CC0020


def _i32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


def _objects(p):
    o = p.state.get("gdi")
    if o is None:
        o = p.state["gdi"] = {}
    return o


def new_object(p, obj):
    objs = _objects(p)
    h = 0x50000 + 4 * (len(objs) + 1)
    while h in objs:
        h += 4
    objs[h] = obj
    return h


def _obj(p, h):
    return _objects(p).get(h)


STOCK = {0: ("brush", (255, 255, 255)), 1: ("brush", (192, 192, 192)), 2: ("brush", (128, 128, 128)),
         3: ("brush", (64, 64, 64)), 4: ("brush", (0, 0, 0)), 5: ("brush", None), 6: ("pen", (255, 255, 255)),
         7: ("pen", (0, 0, 0)), 8: ("pen", None), 10: ("font", 16), 12: ("font", 16), 13: ("font", 16),
         14: ("font", 16), 16: ("font", 16), 17: ("font", 14), 18: ("brush", (220, 220, 220)),
         19: ("pen", (0, 0, 0))}


@dll(1)
def GetStockObject(p, n):
    key = "stock%d" % n
    if key not in p.state:
        kind, v = STOCK.get(n, ("brush", (255, 255, 255)))
        obj = (gui.Brush(v or (0, 0, 0), null=v is None) if kind == "brush" else
               gui.Pen(v or (0, 0, 0), null=v is None) if kind == "pen" else gui.Font(v))
        p.state[key] = new_object(p, obj)
    return p.state[key]


def brush_color(p, h):
    """The colour of a brush handle, also for (COLOR_xxx + 1) numbers."""
    if not h:
        return None
    if h < 64:
        return gui.SYS_COLORS.get(h - 1, (240, 240, 240))
    b = _obj(p, h)
    return b.color if isinstance(b, gui.Brush) and not b.null else None


# ---- device contexts ----

def _dc(p, h):
    d = _obj(p, h)
    return d if isinstance(d, gui.DC) else None


@dll(2)
def BeginPaint(p, hwnd, ps):
    from pywin.dlls import user32
    w = user32._wnd(p, hwnd)
    if w is None:
        return 0
    dc = gui.DC(w)
    h = new_object(p, dc)
    if w.erase:
        r = user32._send(p, w, gui.WM_ERASEBKGND, h, 0)
        if not r:
            w.surface.fill(w.cls.background)
        w.erase = False
    w.invalid = False
    mem.zero(ps, 72)
    mem.put64(ps, h)                                   # PAINTSTRUCT: hdc, erase, rect...
    mem.put32(ps + 8, 1)
    for k, v in enumerate((0, 0, w.w, w.h)):
        mem.put32(ps + 12 + 4 * k, v)
    return h


@dll(2)
def EndPaint(p, hwnd, ps):
    h = mem.u64(ps)
    dc = _dc(p, h)
    if dc:
        dc.changed()
    _objects(p).pop(h, None)
    return 1


@dll(1)
def GetDC(p, hwnd):
    from pywin.dlls import user32
    w = user32._wnd(p, hwnd)
    if w is None:
        if "screen_dc" not in p.state:
            p.state["screen_dc"] = new_object(p, gui.DC(surface=pygame.Surface((8, 8))))
        return p.state["screen_dc"]
    return new_object(p, gui.DC(w))


dll.alias("GetWindowDC", "GetDC")


@dll(2)
def ReleaseDC(p, hwnd, h):
    dc = _dc(p, h)
    if dc:
        dc.changed()
        if dc.wnd is not None:
            _objects(p).pop(h, None)
    return 1


@dll(1)
def CreateCompatibleDC(p, h):
    dc = gui.DC(surface=pygame.Surface((1, 1)))
    return new_object(p, dc)


@dll(1)
def DeleteDC(p, h):
    _objects(p).pop(h, None)
    return 1


@dll(3)
def CreateCompatibleBitmap(p, h, w, hh):
    return new_object(p, gui.Bitmap(_i32(w), _i32(hh)))


@dll(5)
def CreateBitmap(p, w, h, planes, bits, data):
    return new_object(p, gui.Bitmap(_i32(w), _i32(h)))


SAVED = ("pen", "brush", "font", "text_color", "bk_color", "transparent", "align", "clip")


@dll(1)
def SaveDC(p, h):
    """Remember the DC's pen, brush, font, colours and clip; RestoreDC brings them back."""
    dc = _dc(p, h)
    if dc is None:
        return 0
    if not hasattr(dc, "saved"):
        dc.saved = []
    dc.saved.append({k: getattr(dc, k, None) for k in SAVED})
    return len(dc.saved)


@dll(2)
def RestoreDC(p, h, n):
    dc = _dc(p, h)
    saved = getattr(dc, "saved", None) if dc else None
    if not saved:
        return 0
    n = _i32(n)
    keep = len(saved) + n if n < 0 else n - 1          # -1 means the last one saved
    if not 0 <= keep < len(saved):
        return 0
    state = saved[keep]
    del saved[keep:]
    for k, v in state.items():
        setattr(dc, k, v)
    return 1


# ---- pens, brushes, fonts ----

@dll(1)
def CreateSolidBrush(p, color):
    return new_object(p, gui.Brush(gui.rgb(color)))


@dll(2)
def CreateHatchBrush(p, style, color):
    return new_object(p, gui.Brush(gui.rgb(color)))


@dll(3)
def CreatePen(p, style, width, color):
    return new_object(p, gui.Pen(gui.rgb(color), _i32(width), null=style == 5))


def _font(height, weight, face):
    f = face.lower() if face else ""
    family = "mono" if any(k in f for k in ("courier", "consol", "mono", "fixed", "terminal")) else "sans"
    return gui.Font(_i32(height) or 16, _i32(weight) >= 600, family)


@dll(14)
def CreateFontA(p, height, width, esc, orient, weight, italic, under, strike, charset, out, clip, quality, pitch, face):
    return new_object(p, _font(height, weight, mem.cstr(face) if face else ""))


@dll(14)
def CreateFontW(p, height, width, esc, orient, weight, italic, under, strike, charset, out, clip, quality, pitch, face):
    return new_object(p, _font(height, weight, mem.wstr(face) if face else ""))


@dll(1)
def CreateFontIndirectA(p, lf):
    return new_object(p, _font(mem.i32(lf), mem.i32(lf + 16), mem.cstr(lf + 28)))


@dll(1)
def CreateFontIndirectW(p, lf):
    return new_object(p, _font(mem.i32(lf), mem.i32(lf + 16), mem.wstr(lf + 28)))


@dll(2)
def SelectObject(p, h, obj):
    dc, o = _dc(p, h), _obj(p, obj)
    if dc is None or o is None:
        return 0
    old_kind = {gui.Pen: "pen", gui.Brush: "brush", gui.Font: "font", gui.Bitmap: "bitmap"}.get(type(o))
    if old_kind is None:
        return 0
    old = getattr(dc, old_kind)
    setattr(dc, old_kind, o)
    if old_kind == "bitmap":
        dc.surface = o.surface                      # a memory DC now draws on the bitmap
    for handle, v in _objects(p).items():           # give back the old object's handle
        if v is old:
            return handle
    return new_object(p, old) if old is not None else 0


@dll(1)
def DeleteObject(p, h):
    o = _obj(p, h)
    if o is not None and not isinstance(o, gui.DC):
        _objects(p).pop(h, None)
    return 1


@dll(2)
def SetTextColor(p, h, color):
    dc = _dc(p, h)
    if not dc:
        return 0
    old = dc.text_color
    dc.text_color = gui.rgb(color)
    return old[0] | old[1] << 8 | old[2] << 16


@dll(2)
def SetBkColor(p, h, color):
    dc = _dc(p, h)
    if not dc:
        return 0
    old = dc.bk_color
    dc.bk_color = gui.rgb(color)
    return old[0] | old[1] << 8 | old[2] << 16


@dll(2)
def SetBkMode(p, h, mode):
    dc = _dc(p, h)
    if not dc:
        return 0
    old = TRANSPARENT if dc.transparent else OPAQUE
    dc.transparent = mode == TRANSPARENT
    return old


@dll(2)
def SetTextAlign(p, h, align):
    dc = _dc(p, h)
    if dc:
        dc.align = align
    return 0


@dll(2)
def SetROP2(p, h, mode):
    return 13


@dll(2)
def SetStretchBltMode(p, h, mode):
    return 1


@dll(2)
def SetMapMode(p, h, mode):
    return 1


# ---- drawing ----

def _rect_args(x0, y0, x1, y1):
    x0, y0, x1, y1 = _i32(x0), _i32(y0), _i32(x1), _i32(y1)
    return pygame.Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))


def _shape(dc, kind, r, extra=None):
    if not dc.brush.null:
        if kind == "rect":
            pygame.draw.rect(dc.surface, dc.brush.color, r)
        elif kind == "round":
            pygame.draw.rect(dc.surface, dc.brush.color, r, 0, extra)
        else:
            pygame.draw.ellipse(dc.surface, dc.brush.color, r)
    if not dc.pen.null:
        if kind == "rect":
            pygame.draw.rect(dc.surface, dc.pen.color, r, dc.pen.width)
        elif kind == "round":
            pygame.draw.rect(dc.surface, dc.pen.color, r, dc.pen.width, extra)
        else:
            pygame.draw.ellipse(dc.surface, dc.pen.color, r, dc.pen.width)
    dc.changed()


@dll(5)
def Rectangle(p, h, x0, y0, x1, y1):
    dc = _dc(p, h)
    if dc:
        _shape(dc, "rect", _rect_args(x0, y0, x1, y1))
    return 1


@dll(5)
def Ellipse(p, h, x0, y0, x1, y1):
    dc = _dc(p, h)
    if dc:
        _shape(dc, "ellipse", _rect_args(x0, y0, x1, y1))
    return 1


@dll(7)
def RoundRect(p, h, x0, y0, x1, y1, rw, rh):
    dc = _dc(p, h)
    if dc:
        _shape(dc, "round", _rect_args(x0, y0, x1, y1), max(1, _i32(rw) // 2))
    return 1


def _read_rect(at):
    return _rect_args(mem.u32(at), mem.u32(at + 4), mem.u32(at + 8), mem.u32(at + 12))


@dll(3)
def FillRect(p, h, rect, brush):
    dc = _dc(p, h)
    color = brush_color(p, brush)
    if dc and color is not None:
        if getattr(dc, "clip", None) is not None:
            from pywin.dlls.g32_extra import clipped_fill
            clipped_fill(dc, color, _read_rect(rect))
        else:
            dc.surface.fill(color, _read_rect(rect))
        dc.changed()
    return 1


@dll(3)
def FrameRect(p, h, rect, brush):
    dc = _dc(p, h)
    color = brush_color(p, brush)
    if dc and color is not None:
        pygame.draw.rect(dc.surface, color, _read_rect(rect), 1)
        dc.changed()
    return 1


@dll(6)
def PatBlt(p, h, x, y, w, hh, rop):
    dc = _dc(p, h)
    if dc:
        color = (0, 0, 0) if rop == 0x42 else (255, 255, 255) if rop == 0xFF0062 else dc.brush.color
        dc.surface.fill(color, (_i32(x), _i32(y), _i32(w), _i32(hh)))
        dc.changed()
    return 1


@dll(4)
def MoveToEx(p, h, x, y, old):
    dc = _dc(p, h)
    if dc:
        if old:
            mem.put32(old, dc.pos[0])
            mem.put32(old + 4, dc.pos[1])
        dc.pos = (_i32(x), _i32(y))
    return 1


@dll(3)
def LineTo(p, h, x, y):
    dc = _dc(p, h)
    if dc:
        end = (_i32(x), _i32(y))
        if not dc.pen.null:
            pygame.draw.line(dc.surface, dc.pen.color, dc.pos, end, dc.pen.width)
        dc.pos = end
        dc.changed()
    return 1


def _points(at, n):
    return [(mem.i32(at + 8 * k), mem.i32(at + 8 * k + 4)) for k in range(n)]


@dll(3)
def Polyline(p, h, pts, n):
    dc = _dc(p, h)
    if dc and n > 1 and not dc.pen.null:
        pygame.draw.lines(dc.surface, dc.pen.color, False, _points(pts, n), dc.pen.width)
        dc.changed()
    return 1


@dll(3)
def Polygon(p, h, pts, n):
    dc = _dc(p, h)
    if dc and n > 2:
        points = _points(pts, n)
        if not dc.brush.null:
            pygame.draw.polygon(dc.surface, dc.brush.color, points)
        if not dc.pen.null:
            pygame.draw.polygon(dc.surface, dc.pen.color, points, dc.pen.width)
        dc.changed()
    return 1


@dll(4)
def SetPixel(p, h, x, y, color):
    dc = _dc(p, h)
    if dc:
        x, y = _i32(x), _i32(y)
        if 0 <= x < dc.surface.get_width() and 0 <= y < dc.surface.get_height():
            dc.surface.set_at((x, y), gui.rgb(color))
        dc.changed()
    return color


dll.alias("SetPixelV", "SetPixel")


@dll(3)
def GetPixel(p, h, x, y):
    dc = _dc(p, h)
    if not dc:
        return 0xFFFFFFFF
    x, y = _i32(x), _i32(y)
    if not (0 <= x < dc.surface.get_width() and 0 <= y < dc.surface.get_height()):
        return 0xFFFFFFFF
    c = dc.surface.get_at((x, y))
    return c[0] | c[1] << 8 | c[2] << 16


# ---- text ----

def _text_out(dc, x, y, text):
    f = dc.font.pygame_font()
    img = f.render(text, True, dc.text_color, None if dc.transparent else dc.bk_color)
    if dc.align & 6 == 6:                       # TA_CENTER
        x -= img.get_width() // 2
    elif dc.align & 2:                          # TA_RIGHT
        x -= img.get_width()
    if dc.align & 8:                            # TA_BOTTOM
        y -= img.get_height()
    if getattr(dc, "clip", None) is not None:
        from pywin.dlls.g32_extra import clipped_blit
        clipped_blit(dc, img, x, y)
    else:
        dc.surface.blit(img, (x, y))
    dc.changed()


@dll(5)
def TextOutA(p, h, x, y, text, n):
    dc = _dc(p, h)
    if dc:
        _text_out(dc, _i32(x), _i32(y), _str(mem.read(text, n)))
    return 1


@dll(5)
def TextOutW(p, h, x, y, text, n):
    dc = _dc(p, h)
    if dc:
        raw = mem.read(text, 2 * n)
        _text_out(dc, _i32(x), _i32(y), "".join(chr(raw[2 * k] | raw[2 * k + 1] << 8) for k in range(n)))
    return 1


def _str(b):
    try:
        return b.decode()
    except UnicodeError:
        return "".join(chr(c) for c in b)


DT_CENTER, DT_RIGHT, DT_VCENTER, DT_BOTTOM, DT_SINGLELINE, DT_CALCRECT = 1, 2, 4, 8, 0x20, 0x400


def _draw_text(p, h, text, rect, flags):
    dc = _dc(p, h)
    if not dc:
        return 0
    r = _read_rect(rect)
    f = dc.font.pygame_font()
    lines = [text.replace("\n", " ")] if flags & DT_SINGLELINE else text.split("\n")
    height = f.get_height() * len(lines)
    if flags & DT_CALCRECT:
        width = max(f.size(line)[0] for line in lines) if lines else 0
        mem.put32(rect + 8, r.x + width)
        mem.put32(rect + 12, r.y + height)
        return height
    y = r.y
    if flags & DT_VCENTER:
        y = r.y + (r.h - height) // 2
    elif flags & DT_BOTTOM:
        y = r.bottom - height
    for line in lines:
        img = f.render(line.replace("&", ""), True, dc.text_color, None if dc.transparent else dc.bk_color)
        x = r.x + (r.w - img.get_width()) // 2 if flags & DT_CENTER else (
            r.right - img.get_width() if flags & DT_RIGHT else r.x)
        dc.surface.blit(img, (x, y))
        y += f.get_height()
    dc.changed()
    return height


@dll(5, "DrawTextA")
def _DrawTextA(p, h, text, n, rect, flags):
    s = _str(mem.cbytes(text) if _i32(n) == -1 else mem.read(text, n))
    return _draw_text(p, h, s, rect, flags)


@dll(5, "DrawTextW")
def _DrawTextW(p, h, text, n, rect, flags):
    s = mem.wstr(text) if _i32(n) == -1 else mem.wstr(text, n)
    return _draw_text(p, h, s, rect, flags)


@dll(4)
def GetTextExtentPoint32A(p, h, text, n, size):
    dc = _dc(p, h)
    w, hh = dc.font.pygame_font().size(_str(mem.read(text, n))) if dc else (0, 0)
    mem.put32(size, w)
    mem.put32(size + 4, hh)
    return 1


dll.alias("GetTextExtentPointA", "GetTextExtentPoint32A")


@dll(2)
def GetTextMetricsA(p, h, tm):
    dc = _dc(p, h)
    f = dc.font.pygame_font() if dc else None
    mem.zero(tm, 56)
    if f:
        for k, v in enumerate((f.get_height(), f.get_ascent(), -f.get_descent(), 0, 0,
                               f.size("x")[0], f.size("W")[0], 400)):
            mem.put32(tm + 4 * k, v)
    return 1


dll.alias("GetTextMetricsW", "GetTextMetricsA")


# ---- copying pixels ----

@dll(9)
def BitBlt(p, dst, x, y, w, h, src, sx, sy, rop):
    d, s = _dc(p, dst), _dc(p, src)
    x, y, w, h, sx, sy = _i32(x), _i32(y), _i32(w), _i32(h), _i32(sx), _i32(sy)
    if d is None:
        return 0
    if s is None or rop in (0x42, 0xFF0062):          # BLACKNESS, WHITENESS
        return PatBlt(p, dst, x, y, w, h, rop)
    d.surface.blit(_source(s), (x, y), (sx, sy, w, h))
    d.changed()
    return 1


@dll(11)
def StretchBlt(p, dst, x, y, w, h, src, sx, sy, sw, sh, rop):
    d, s = _dc(p, dst), _dc(p, src)
    if d is None or s is None:
        return 0
    part = pygame.Surface((max(1, _i32(sw)), max(1, _i32(sh))))
    part.blit(_source(s), (0, 0), (_i32(sx), _i32(sy), _i32(sw), _i32(sh)))
    d.surface.blit(pygame.transform.scale(part, (max(1, _i32(w)), max(1, _i32(h)))), (_i32(x), _i32(y)))
    d.changed()
    return 1


def _dib(info, bits):
    """A pygame Surface from a 32- or 24-bit device-independent bitmap."""
    w, h = mem.i32(info + 4), mem.i32(info + 8)
    bpp = mem.u16(info + 14)
    top_down = h < 0
    h = abs(h)
    surf = pygame.Surface((w, h))
    stride = ((w * bpp // 8) + 3) & ~3
    data = mem.read(bits, stride * h)
    buf = surf._buf
    for row in range(h):
        src = row if top_down else h - 1 - row
        line = data[src * stride:src * stride + stride]
        if bpp == 32:
            buf[row * w * 4:(row + 1) * w * 4] = line[:w * 4]
        elif bpp == 24:
            o = row * w * 4
            for k in range(w):
                buf[o + 4 * k:o + 4 * k + 3] = line[3 * k:3 * k + 3]
    return surf


def _source(dc):
    """A DC's pixels; for a DIB section, read again from the program's memory."""
    bmp = dc.bitmap
    if bmp is not None and getattr(bmp, "dib", None):
        info, bits = bmp.dib
        bmp.surface = dc.surface = _dib(info, bits)
    return dc.surface


def _dib_into(surf, x, y, info, bits):
    """Copy a 32-bit DIB straight into a Surface's pixels (no new Surface):
    the fast way for games that draw a whole frame each time."""
    w, h = mem.i32(info + 4), mem.i32(info + 8)
    if mem.u16(info + 14) != 32 or x < 0 or y < 0:
        return False
    top_down = h < 0
    h = abs(h)
    sw, shh = surf.get_size()
    if x + w > sw or y + h > shh:
        return False
    data = mem.read(bits, w * h * 4)
    buf, row = surf._buf, w * 4
    for r in range(h):
        src = (r if top_down else h - 1 - r) * row
        o = ((y + r) * sw + x) * 4
        buf[o:o + row] = data[src:src + row]
    return True


@dll(13)
def StretchDIBits(p, h, x, y, w, hh, sx, sy, sw, sh, bits, info, usage, rop):
    dc = _dc(p, h)
    if dc is None:
        return 0
    if (_i32(w), abs(_i32(hh))) == (mem.i32(info + 4), abs(mem.i32(info + 8))) and \
            _dib_into(dc.surface, _i32(x), _i32(y), info, bits):
        dc.changed()
        return abs(_i32(hh))
    img = _dib(info, bits)
    if (_i32(w), _i32(hh)) != img.get_size():
        img = pygame.transform.scale(img, (max(1, _i32(w)), max(1, abs(_i32(hh)))))
    dc.surface.blit(img, (_i32(x), _i32(y)))
    dc.changed()
    return abs(_i32(hh))


@dll(12)
def SetDIBitsToDevice(p, h, x, y, w, hh, sx, sy, start, lines, bits, info, usage):
    dc = _dc(p, h)
    if dc is None:
        return 0
    dc.surface.blit(_dib(info, bits), (_i32(x), _i32(y)))
    dc.changed()
    return lines


@dll(6)
def CreateDIBSection(p, h, info, usage, bits_out, section, offset):
    w, hh = mem.i32(info + 4), abs(mem.i32(info + 8))
    bpp = mem.u16(info + 14)
    stride = ((w * bpp // 8) + 3) & ~3
    bits = p.heap.alloc(stride * hh)
    bmp = gui.Bitmap(w, hh)
    header = p.heap.alloc(64)                     # keep our own copy of the header
    mem.write(header, mem.read(info, 40))
    bmp.dib = (header, bits)
    if bits_out:
        mem.put64(bits_out, bits)
    return new_object(p, bmp)


# ---- pixel formats and SwapBuffers, for OpenGL (see opengl32.py) ----

@dll(2)
def ChoosePixelFormat(p, h, pfd):
    return 1                                       # one format: 32-bit colour with depth


@dll(3)
def SetPixelFormat(p, h, n, pfd):
    return 1


@dll(1)
def GetPixelFormat(p, h):
    return 1


@dll(4)
def DescribePixelFormat(p, h, n, size, pfd):
    if pfd and size >= 40:
        mem.zero(pfd, size)
        mem.put16(pfd, 40)                         # nSize
        mem.put16(pfd + 2, 1)                      # nVersion
        mem.put32(pfd + 4, 0x25)                   # draw to window, OpenGL, double buffer
        mem.put8(pfd + 9, 32)                      # colour bits
        mem.put8(pfd + 23, 24)                     # depth bits
    return 1


@dll(1)
def SwapBuffers(p, h):
    from pywin.dlls import opengl32
    return opengl32.swap(p, h)


from pywin.dlls import g32_extra                 # noqa: E402  (the rest of gdi32)
from pywin.dlls.g32_extra import dll_msimg32     # noqa: E402,F401
