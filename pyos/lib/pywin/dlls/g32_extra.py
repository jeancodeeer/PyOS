# gdi32.dll, part 2: text with clipping, regions, more about fonts and
# bitmaps, alpha blending (also msimg32.dll) and printing.
#
# Clipping: a DC can have a clip rectangle (dc.clip). Text and fills only
# change the pixels inside it. A region is kept as one rectangle (its
# bounding box), which is what programs like Scintilla use in practice.
#
# Printing: CreateDC with a printer name gives a DC that draws on a white
# page. EndPage keeps the page, and EndDoc gives all the pages to the SnakeyOS
# print spooler (pyos/printing.py), which prints them or saves a PDF.
import pygame
from pywin import mem, gui
from pywin.dlls.gdi32 import dll, new_object, _obj, _objects, _dc, _i32, _read_rect, _str, _dib, \
    GetStockObject, brush_color

from pywin.dlls import Dll

dll_msimg32 = Dll("msimg32")
NULLREGION, SIMPLEREGION, COMPLEXREGION, ERROR = 1, 2, 3, 0
RGN_AND, RGN_OR, RGN_XOR, RGN_DIFF, RGN_COPY = 1, 2, 3, 4, 5
ETO_OPAQUE, ETO_CLIPPED = 2, 4


class Region:
    def __init__(self, rect):
        self.rect = pygame.Rect(rect)


def _clip_of(dc):
    """Where drawing on this DC may change pixels."""
    whole = pygame.Rect(0, 0, dc.surface.get_width(), dc.surface.get_height())
    clip = getattr(dc, "clip", None)
    return whole.clip(clip) if clip is not None else whole


def clipped_blit(dc, img, x, y, limit=None):
    """Blit img at (x, y), keeping inside the clip (and inside limit, if given)."""
    box = _clip_of(dc)
    if limit is not None:
        box = box.clip(limit)
    target = pygame.Rect(x, y, img.get_width(), img.get_height()).clip(box)
    if target.w > 0 and target.h > 0:
        dc.surface.blit(img, (target.x, target.y), (target.x - x, target.y - y, target.w, target.h))


def clipped_fill(dc, color, rect):
    r = pygame.Rect(rect).clip(_clip_of(dc))
    if r.w > 0 and r.h > 0:
        dc.surface.fill(color, r)


# ---- text ----

def _wtext(ptr, n):
    if not n:
        return ""
    raw = mem.read(ptr, 2 * n)
    return "".join(chr(raw[2 * k] | raw[2 * k + 1] << 8) for k in range(n))


def _ext_text_out(p, h, x, y, flags, rect, text):
    dc = _dc(p, h)
    if dc is None:
        return 0
    x, y = _i32(x), _i32(y)
    box = None
    if rect:
        box = _read_rect(rect)
        if flags & ETO_OPAQUE:
            clipped_fill(dc, dc.bk_color, box)
    if text:
        f = dc.font.pygame_font()
        opaque = not dc.transparent and not flags & ETO_OPAQUE
        img = f.render(text, True, dc.text_color, dc.bk_color if opaque else None)
        if dc.align & 6 == 6:                          # TA_CENTER
            x -= img.get_width() // 2
        elif dc.align & 2:                             # TA_RIGHT
            x -= img.get_width()
        if dc.align & 8:                               # TA_BOTTOM
            y -= img.get_height()
        elif dc.align & 24 == 24:                      # TA_BASELINE
            y -= f.get_ascent()
        clipped_blit(dc, img, x, y, box if flags & ETO_CLIPPED else None)
    dc.changed()
    return 1


@dll(8)
def ExtTextOutW(p, h, x, y, flags, rect, text, n, dx):
    return _ext_text_out(p, h, x, y, flags, rect, _wtext(text, n & 0xFFFFFFFF) if text else "")


@dll(8)
def ExtTextOutA(p, h, x, y, flags, rect, text, n, dx):
    return _ext_text_out(p, h, x, y, flags, rect, _str(mem.read(text, n & 0xFFFFFFFF)) if text else "")


def _char_widths(font, text):
    """The width of each character (cached per font)."""
    cache = getattr(font, "pywin_widths", None)
    if cache is None:
        cache = font.pywin_widths = {}
    out = []
    for ch in text:
        w = cache.get(ch)
        if w is None:
            w = cache[ch] = font.size(ch)[0]
        out.append(w)
    return out


def _extent_ex(p, h, text, max_w, fit_out, dx_out, size_out):
    dc = _dc(p, h)
    f = dc.font.pygame_font() if dc else pygame.font.SysFont("sans", 13)
    total, fit = 0, 0
    limit = _i32(max_w)
    for k, w in enumerate(_char_widths(f, text)):
        total += w
        if dx_out:
            mem.put32(dx_out + 4 * k, total)
        if fit_out and (limit < 0 or total <= limit):
            fit = k + 1
    if fit_out:
        mem.put32(fit_out, fit)
    mem.put32(size_out, total)
    mem.put32(size_out + 4, f.get_height())
    return 1


@dll(7)
def GetTextExtentExPointW(p, h, text, n, max_w, fit, dx, size):
    return _extent_ex(p, h, _wtext(text, n & 0xFFFFFFFF), max_w, fit, dx, size)


@dll(7)
def GetTextExtentExPointA(p, h, text, n, max_w, fit, dx, size):
    return _extent_ex(p, h, _str(mem.read(text, n & 0xFFFFFFFF)), max_w, fit, dx, size)


@dll(4)
def GetTextExtentPoint32W(p, h, text, n, size):
    return _extent_ex(p, h, _wtext(text, n & 0xFFFFFFFF), -1, 0, 0, size)


dll.alias("GetTextExtentPointW", "GetTextExtentPoint32W")


@dll(3)
def GetTextFaceW(p, h, n, buf):
    dc = _dc(p, h)
    name = getattr(dc.font, "name", "Segoe UI") if dc else "Segoe UI"
    if buf and n:
        mem.put_wstr(buf, name[:n - 1])
    return len(name) + 1


@dll(4)
def GetCharWidth32W(p, h, first, last, out):
    dc = _dc(p, h)
    f = dc.font.pygame_font() if dc else pygame.font.SysFont("sans", 13)
    for k, c in enumerate(range(first, last + 1)):
        mem.put32(out + 4 * k, _char_widths(f, chr(c))[0])
    return 1


dll.alias("GetCharWidthW", "GetCharWidth32W")


@dll(1)
def GetTextCharset(p, h):
    return 0                                           # ANSI_CHARSET


@dll(2)
def SetTextCharacterExtra(p, h, extra):
    return 0


# ---- regions and the clip ----

@dll(4)
def CreateRectRgn(p, x0, y0, x1, y1):
    x0, y0, x1, y1 = _i32(x0), _i32(y0), _i32(x1), _i32(y1)
    return new_object(p, Region((x0, y0, max(0, x1 - x0), max(0, y1 - y0))))


@dll(1)
def CreateRectRgnIndirect(p, rect):
    return new_object(p, Region(_read_rect(rect)))


dll.alias("CreateEllipticRgnIndirect", "CreateRectRgnIndirect")


@dll(6)
def CreateRoundRectRgn(p, x0, y0, x1, y1, w, h):
    return CreateRectRgn(p, x0, y0, x1, y1)


def _kind(r):
    return NULLREGION if r.w <= 0 or r.h <= 0 else SIMPLEREGION


@dll(5)
def SetRectRgn(p, h, x0, y0, x1, y1):
    rgn = _obj(p, h)
    if isinstance(rgn, Region):
        x0, y0, x1, y1 = _i32(x0), _i32(y0), _i32(x1), _i32(y1)
        rgn.rect = pygame.Rect(x0, y0, max(0, x1 - x0), max(0, y1 - y0))
    return 1


@dll(4)
def CombineRgn(p, dst, a, b, mode):
    d, ra, rb = _obj(p, dst), _obj(p, a), _obj(p, b)
    if not isinstance(d, Region) or not isinstance(ra, Region):
        return ERROR
    if mode == RGN_COPY:
        d.rect = pygame.Rect(ra.rect)
    elif not isinstance(rb, Region):
        return ERROR
    elif mode == RGN_AND:
        d.rect = ra.rect.clip(rb.rect)
    elif mode in (RGN_OR, RGN_XOR):
        d.rect = ra.rect.union(rb.rect) if ra.rect.w and rb.rect.w else pygame.Rect(ra.rect if ra.rect.w else rb.rect)
    elif mode == RGN_DIFF:
        d.rect = _subtract(ra.rect, rb.rect)
    return _kind(d.rect)


def _subtract(a, b):
    """a minus b, when the answer is still a rectangle (else a itself)."""
    if not a.colliderect(b):
        return pygame.Rect(a)
    if b.contains(a):
        return pygame.Rect(a.x, a.y, 0, 0)
    if b.x <= a.x and b.right >= a.right:                  # b covers a full width band
        if b.y <= a.y:
            return pygame.Rect(a.x, b.bottom, a.w, a.bottom - b.bottom)
        if b.bottom >= a.bottom:
            return pygame.Rect(a.x, a.y, a.w, b.y - a.y)
    if b.y <= a.y and b.bottom >= a.bottom:                # ... or a full height band
        if b.x <= a.x:
            return pygame.Rect(b.right, a.y, a.right - b.right, a.h)
        if b.right >= a.right:
            return pygame.Rect(a.x, a.y, b.x - a.x, a.h)
    return pygame.Rect(a)


@dll(2)
def GetRgnBox(p, h, rect):
    rgn = _obj(p, h)
    if not isinstance(rgn, Region):
        return ERROR
    r = rgn.rect
    for k, v in enumerate((r.x, r.y, r.right, r.bottom)):
        mem.put32(rect + 4 * k, v)
    return _kind(r)


@dll(3)
def OffsetRgn(p, h, dx, dy):
    rgn = _obj(p, h)
    if not isinstance(rgn, Region):
        return ERROR
    rgn.rect.move_ip(_i32(dx), _i32(dy))
    return _kind(rgn.rect)


@dll(3)
def PtInRegion(p, h, x, y):
    rgn = _obj(p, h)
    return 1 if isinstance(rgn, Region) and rgn.rect.collidepoint(_i32(x), _i32(y)) else 0


@dll(2)
def RectInRegion(p, h, rect):
    rgn = _obj(p, h)
    return 1 if isinstance(rgn, Region) and rgn.rect.colliderect(_read_rect(rect)) else 0


@dll(2)
def SelectClipRgn(p, h, region):
    dc = _dc(p, h)
    if dc is None:
        return ERROR
    rgn = _obj(p, region)
    dc.clip = pygame.Rect(rgn.rect) if isinstance(rgn, Region) else None
    return _kind(_clip_of(dc))


@dll(3)
def ExtSelectClipRgn(p, h, region, mode):
    dc = _dc(p, h)
    rgn = _obj(p, region)
    if dc is None:
        return ERROR
    if mode == RGN_COPY or not isinstance(rgn, Region):
        return SelectClipRgn(p, h, region)
    if mode == RGN_AND:
        dc.clip = _clip_of(dc).clip(rgn.rect)
    return _kind(_clip_of(dc))


@dll(2)
def GetClipRgn(p, h, region):
    dc, rgn = _dc(p, h), _obj(p, region)
    if dc is None or getattr(dc, "clip", None) is None:
        return 0                                           # no clip region
    if isinstance(rgn, Region):
        rgn.rect = pygame.Rect(dc.clip)
    return 1


@dll(2)
def GetClipBox(p, h, rect):
    dc = _dc(p, h)
    if dc is None:
        return ERROR
    r = _clip_of(dc)
    for k, v in enumerate((r.x, r.y, r.right, r.bottom)):
        mem.put32(rect + 4 * k, v)
    return _kind(r)


@dll(5)
def IntersectClipRect(p, h, x0, y0, x1, y1):
    dc = _dc(p, h)
    if dc is None:
        return ERROR
    x0, y0, x1, y1 = _i32(x0), _i32(y0), _i32(x1), _i32(y1)
    dc.clip = _clip_of(dc).clip(pygame.Rect(x0, y0, max(0, x1 - x0), max(0, y1 - y0)))
    return _kind(dc.clip)


@dll(5)
def ExcludeClipRect(p, h, x0, y0, x1, y1):
    dc = _dc(p, h)
    if dc is None:
        return ERROR
    x0, y0, x1, y1 = _i32(x0), _i32(y0), _i32(x1), _i32(y1)
    dc.clip = _subtract(_clip_of(dc), pygame.Rect(x0, y0, max(0, x1 - x0), max(0, y1 - y0)))
    return _kind(dc.clip)


@dll(2)
def RectVisible(p, h, rect):
    dc = _dc(p, h)
    return 1 if dc is not None and _clip_of(dc).colliderect(_read_rect(rect)) else 0


@dll(3)
def PtVisible(p, h, x, y):
    dc = _dc(p, h)
    return 1 if dc is not None and _clip_of(dc).collidepoint(_i32(x), _i32(y)) else 0


@dll(3)
def FillRgn(p, h, region, brush):
    dc, rgn = _dc(p, h), _obj(p, region)
    color = brush_color(p, brush)
    if dc is not None and isinstance(rgn, Region) and color is not None:
        clipped_fill(dc, color, rgn.rect)
        dc.changed()
    return 1


# ---- the device and its objects ----

LOGPIXELSX, LOGPIXELSY, HORZRES, VERTRES, BITSPIXEL, PLANES = 88, 90, 8, 10, 12, 14
HORZSIZE, VERTSIZE, NUMCOLORS, RASTERCAPS, TECHNOLOGY = 4, 6, 24, 38, 2
PHYSICALWIDTH, PHYSICALHEIGHT, PHYSICALOFFSETX, PHYSICALOFFSETY = 110, 111, 112, 113


@dll(2)
def GetDeviceCaps(p, h, index):
    dc = _dc(p, h)
    printer = getattr(dc, "printer", None)
    if printer is not None:
        dpi = printer.dpi
        w, hh = printer.size
        return {LOGPIXELSX: dpi, LOGPIXELSY: dpi, HORZRES: w, VERTRES: hh, PHYSICALWIDTH: w,
                PHYSICALHEIGHT: hh, PHYSICALOFFSETX: 0, PHYSICALOFFSETY: 0, BITSPIXEL: 24, PLANES: 1,
                HORZSIZE: w * 254 // (10 * dpi), VERTSIZE: hh * 254 // (10 * dpi),
                NUMCOLORS: -1 & 0xFFFFFFFF, TECHNOLOGY: 2, RASTERCAPS: 0x7E99}.get(index, 0)
    sw, sh = getattr(p.ui, "screen_size", (1024, 768))
    return {LOGPIXELSX: 96, LOGPIXELSY: 96, HORZRES: sw, VERTRES: sh, BITSPIXEL: 32, PLANES: 1,
            HORZSIZE: sw * 254 // 960, VERTSIZE: sh * 254 // 960, NUMCOLORS: -1 & 0xFFFFFFFF,
            TECHNOLOGY: 1, RASTERCAPS: 0x7E99}.get(index, 0)


def _put_logfont(at, font, wide=True):
    mem.zero(at, 92 if wide else 60)
    mem.put32(at, -abs(font.height) & 0xFFFFFFFF)
    mem.put32(at + 16, 700 if font.bold else 400)
    face = getattr(font, "name", None) or ("Courier New" if font.face == "mono" else "Segoe UI")
    (mem.put_wstr if wide else mem.put_cstr)(at + 28, face[:31])


@dll(3)
def GetObjectW(p, h, size, out):
    o = _obj(p, h)
    if isinstance(o, gui.Font):
        if out:
            _put_logfont(out, o)
        return 92
    if isinstance(o, gui.Bitmap):
        if out:
            w, hh = o.surface.get_size()
            mem.zero(out, min(size, 32))
            mem.put32(out + 4, w)
            mem.put32(out + 8, hh)
            mem.put32(out + 12, w * 4)
            mem.put16(out + 16, 1)
            mem.put16(out + 18, 32)
            dib = getattr(o, "dib", None)
            if dib and size >= 32:
                mem.put64(out + 24, dib[1])
        return 32 if size >= 32 else 24
    if isinstance(o, gui.Brush):
        if out:
            c = o.color
            mem.put32(out, 1 if o.null else 0)
            mem.put32(out + 4, c[0] | c[1] << 8 | c[2] << 16)
            mem.put64(out + 8, 0)
        return 16
    if isinstance(o, gui.Pen):
        if out:
            c = o.color
            mem.put32(out, 5 if o.null else 0)
            mem.put32(out + 4, o.width)
            mem.put32(out + 12, c[0] | c[1] << 8 | c[2] << 16)
        return 16
    return 0


@dll(3)
def GetObjectA(p, h, size, out):
    o = _obj(p, h)
    if isinstance(o, gui.Font):
        if out:
            _put_logfont(out, o, wide=False)
        return 60
    return GetObjectW(p, h, size, out)


@dll(1)
def GetObjectType(p, h):
    o = _obj(p, h)
    return {gui.Pen: 1, gui.Brush: 2, gui.DC: 3, gui.Bitmap: 7, gui.Font: 6, Region: 8}.get(type(o), 0)


@dll(2)
def GetCurrentObject(p, h, kind):
    dc = _dc(p, h)
    if dc is None:
        return 0
    want = {1: dc.pen, 2: dc.brush, 6: dc.font, 7: dc.bitmap}.get(kind)
    for handle, v in _objects(p).items():
        if v is want:
            return handle
    return 0


FONTS = (("Courier New", "mono"), ("Consolas", "mono"), ("Lucida Console", "mono"), ("Segoe UI", "sans"),
         ("Arial", "sans"), ("Tahoma", "sans"), ("Verdana", "sans"), ("Times New Roman", "serif"))


@dll(5)
def EnumFontFamiliesExW(p, h, logfont, fn, lparam, flags):
    want = mem.wstr(logfont + 28) if logfont else ""
    elf = p.heap.alloc(92 + 128 + 64 + 64)
    tm = p.heap.alloc(256)
    result = 1
    try:
        for name, family in FONTS:
            if want and want.lower() != name.lower():
                continue
            mem.zero(elf, 92 + 256)
            mem.zero(tm, 256)
            mem.put32(elf, -13 & 0xFFFFFFFF)
            mem.put32(elf + 16, 400)
            mem.put8(elf + 27, 0x31 if family == "mono" else 0x22)    # pitch and family
            mem.put_wstr(elf + 28, name)
            mem.put_wstr(elf + 92, name)                              # the full name
            mem.put_wstr(elf + 92 + 128, "Regular")
            mem.put_wstr(elf + 92 + 192, "Western")
            mem.put32(tm, 13)                                         # tmHeight
            result = p.call(fn, elf, tm, 4, lparam) & 0xFFFFFFFF      # TRUETYPE_FONTTYPE
            if not result:
                break
    finally:
        p.heap.free(elf)
        p.heap.free(tm)
    return result


dll.alias("EnumFontFamiliesW", "EnumFontFamiliesExW")


@dll(2)
def AddFontResourceExW(p, name, flags):
    return 0


# ---- brushes and pens ----

@dll(1)
def CreatePatternBrush(p, bitmap):
    bmp = _obj(p, bitmap)
    color = bmp.surface.get_at((0, 0))[:3] if isinstance(bmp, gui.Bitmap) else (128, 128, 128)
    return new_object(p, gui.Brush(tuple(color)))


@dll(1)
def CreateBrushIndirect(p, lb):
    style, color = mem.u32(lb), mem.u32(lb + 4)
    return new_object(p, gui.Brush(gui.rgb(color), null=style == 1))


@dll(5)
def ExtCreatePen(p, style, width, lb, n, styles):
    color = mem.u32(lb + 4) if lb else 0
    return new_object(p, gui.Pen(gui.rgb(color), _i32(width), null=style & 0xF == 5))


@dll(4)
def SetBrushOrgEx(p, h, x, y, old):
    if old:
        mem.put64(old, 0)
    return 1


@dll(2)
def SetDCBrushColor(p, h, color):
    brush = _obj(p, GetStockObject(p, 18))                 # DC_BRUSH
    old = brush.color
    brush.color = gui.rgb(color)
    return old[0] | old[1] << 8 | old[2] << 16


@dll(2)
def SetDCPenColor(p, h, color):
    pen = _obj(p, GetStockObject(p, 19))                   # DC_PEN
    old = pen.color
    pen.color = gui.rgb(color)
    return old[0] | old[1] << 8 | old[2] << 16


@dll(1)
def GetROP2(p, h):
    dc = _dc(p, h)
    return getattr(dc, "rop2", 13)                         # R2_COPYPEN


@dll(1)
def GetBkMode(p, h):
    dc = _dc(p, h)
    return 1 if dc is not None and dc.transparent else 2


@dll(1)
def GetTextColor(p, h):
    dc = _dc(p, h)
    c = dc.text_color if dc else (0, 0, 0)
    return c[0] | c[1] << 8 | c[2] << 16


@dll(1)
def GetBkColor(p, h):
    dc = _dc(p, h)
    c = dc.bk_color if dc else (255, 255, 255)
    return c[0] | c[1] << 8 | c[2] << 16


# ---- coordinates: the window origin is kept, drawing stays in device units ----

def _origin(p, h, key, x, y, old, relative):
    dc = _dc(p, h)
    if dc is None:
        return 0
    ox, oy = getattr(dc, key, (0, 0))
    if old:
        mem.put32(old, ox)
        mem.put32(old + 4, oy)
    x, y = _i32(x), _i32(y)
    setattr(dc, key, (ox + x, oy + y) if relative else (x, y))
    return 1


@dll(4)
def SetWindowOrgEx(p, h, x, y, old):
    return _origin(p, h, "window_org", x, y, old, False)


@dll(4)
def OffsetWindowOrgEx(p, h, x, y, old):
    return _origin(p, h, "window_org", x, y, old, True)


@dll(4)
def SetViewportOrgEx(p, h, x, y, old):
    return _origin(p, h, "viewport_org", x, y, old, False)


@dll(4)
def OffsetViewportOrgEx(p, h, x, y, old):
    return _origin(p, h, "viewport_org", x, y, old, True)


@dll(2)
def GetViewportOrgEx(p, h, out):
    return _origin(p, h, "viewport_org", 0, 0, out, True)       # moving by (0, 0) only reads it


@dll(2)
def GetWindowOrgEx(p, h, out):
    return _origin(p, h, "window_org", 0, 0, out, True)


@dll(3)
def DPtoLP(p, h, pts, n):
    return 1                                               # one logical unit = one pixel


dll.alias("LPtoDP", "DPtoLP")


@dll(1)
def GetMapMode(p, h):
    return 1                                               # MM_TEXT


# ---- device-independent bitmaps ----

@dll(7)
def GetDIBits(p, h, bitmap, start, lines, bits, info, usage):
    bmp = _obj(p, bitmap)
    if not isinstance(bmp, gui.Bitmap):
        return 0
    w, hh = bmp.surface.get_size()
    if not bits:                                           # only the header is wanted
        mem.put32(info + 4, w)
        mem.put32(info + 8, hh)
        mem.put16(info + 12, 1)
        mem.put16(info + 14, 32)
        mem.put32(info + 16, 0)
        mem.put32(info + 20, w * hh * 4)
        return hh
    top_down = mem.i32(info + 8) < 0
    if mem.u16(info + 14) != 32:
        return 0
    buf = bmp.surface._buf
    row = w * 4
    lines = min(lines, hh - start) if start < hh else 0
    for k in range(lines):
        src_row = start + k if top_down else hh - 1 - (start + k)
        mem.write(bits + k * row, bytes(buf[src_row * row:(src_row + 1) * row]))
    return lines


@dll(7)
def SetDIBits(p, h, bitmap, start, lines, bits, info, usage):
    bmp = _obj(p, bitmap)
    if not isinstance(bmp, gui.Bitmap):
        return 0
    img = _dib(info, bits)
    bmp.surface.blit(img, (0, 0))
    return abs(mem.i32(info + 8))


@dll(3)
def SetBitmapBits(p, bitmap, size, bits):
    return 0


@dll(2)
def GetBitmapDimensionEx(p, bitmap, out):
    mem.put64(out, 0)
    return 1


# ---- alpha blending ----

def _alpha_blend(p, dst, x, y, w, h, src, sx, sy, sw, sh, blend):
    from pywin.dlls.gdi32 import _source
    d, s = _dc(p, dst), _dc(p, src)
    if d is None or s is None:
        return 0
    x, y, w, h = _i32(x), _i32(y), _i32(w), _i32(h)
    sx, sy, sw, sh = _i32(sx), _i32(sy), _i32(sw), _i32(sh)
    if w <= 0 or h <= 0 or sw <= 0 or sh <= 0:
        return 0
    part = _source(s).subsurface(pygame.Rect(sx, sy, sw, sh).clip(
        pygame.Rect(0, 0, *s.surface.get_size())))
    if (sw, sh) != (w, h):
        part = pygame.transform.scale(part, (w, h))
    part.set_alpha((blend >> 16) & 0xFF)                   # SourceConstantAlpha
    clipped_blit(d, part, x, y)
    d.changed()
    return 1


@dll(11)
def GdiAlphaBlend(p, dst, x, y, w, h, src, sx, sy, sw, sh, blend):
    return _alpha_blend(p, dst, x, y, w, h, src, sx, sy, sw, sh, blend)


@dll_msimg32(11)
def AlphaBlend(p, dst, x, y, w, h, src, sx, sy, sw, sh, blend):
    return _alpha_blend(p, dst, x, y, w, h, src, sx, sy, sw, sh, blend)


@dll_msimg32(11)
def TransparentBlt(p, dst, x, y, w, h, src, sx, sy, sw, sh, key):
    return _alpha_blend(p, dst, x, y, w, h, src, sx, sy, sw, sh, 0xFF << 16)


@dll_msimg32(6)
def GradientFill(p, h, vertices, n, mesh, count, mode):
    return 1


# ---- printing: a DC that draws pages for the SnakeyOS print spooler ----

class Printer:
    """The paper of a print job: A4 at 150 dots per inch, and the pages so far."""

    def __init__(self, name):
        self.name = name
        self.dpi = 150
        self.size = (1240, 1754)                           # 8.27 x 11.69 inches
        self.pages = []
        self.title = "Documento"


def printer_names():
    try:
        from pyos import printing
        return printing.printer_names()
    except ImportError:
        return ["PDF"]


def _new_page(dc):
    dc.surface = pygame.Surface(dc.printer.size)
    dc.surface.fill((255, 255, 255))


def create_printer_dc(p, name):
    printer = Printer(name or printer_names()[0])
    dc = gui.DC(surface=pygame.Surface((1, 1)))
    dc.printer = printer
    _new_page(dc)
    return new_object(p, dc)


@dll(4)
def CreateDCW(p, driver, device, port, mode):
    drv = (mem.wstr(driver) or "").upper() if driver else ""
    dev = mem.wstr(device) if device else ""
    if drv == "DISPLAY" or (not dev and drv != "WINSPOOL"):
        from pywin.dlls.gdi32 import CreateCompatibleDC
        return CreateCompatibleDC(p, 0)
    return create_printer_dc(p, dev)


@dll(4)
def CreateDCA(p, driver, device, port, mode):
    drv = (mem.cstr(driver) or "").upper() if driver else ""
    dev = mem.cstr(device) if device else ""
    if drv == "DISPLAY" or (not dev and drv != "WINSPOOL"):
        from pywin.dlls.gdi32 import CreateCompatibleDC
        return CreateCompatibleDC(p, 0)
    return create_printer_dc(p, dev)


dll.alias("CreateICW", "CreateDCW")


def _printer_dc(p, h):
    dc = _dc(p, h)
    return dc if dc is not None and getattr(dc, "printer", None) is not None else None


@dll(2)
def StartDocW(p, h, info):
    dc = _printer_dc(p, h)
    if dc is None:
        return -1 & 0xFFFFFFFF
    name = mem.u64(info + 8)
    dc.printer.title = (mem.wstr(name) if name else "") or "Documento"
    dc.printer.pages = []
    return 1


@dll(2)
def StartDocA(p, h, info):
    dc = _printer_dc(p, h)
    if dc is None:
        return -1 & 0xFFFFFFFF
    name = mem.u64(info + 8)
    dc.printer.title = (mem.cstr(name) if name else "") or "Documento"
    dc.printer.pages = []
    return 1


@dll(1)
def StartPage(p, h):
    dc = _printer_dc(p, h)
    if dc is None:
        return 0
    _new_page(dc)
    return 1


@dll(1)
def EndPage(p, h):
    dc = _printer_dc(p, h)
    if dc is None:
        return 0
    dc.printer.pages.append(dc.surface)
    _new_page(dc)
    return 1


@dll(1)
def EndDoc(p, h):
    dc = _printer_dc(p, h)
    if dc is None:
        return 0
    job = dc.printer
    if not job.pages:
        return 1
    try:
        from pyos import printing
        printing.submit(job.name, job.title, job.pages, job.dpi)
    except Exception as e:
        p.warn("no se pudo imprimir: %s" % e)
        return 0
    job.pages = []
    return 1


@dll(1)
def AbortDoc(p, h):
    dc = _printer_dc(p, h)
    if dc is not None:
        dc.printer.pages = []
    return 1


@dll(2)
def SetAbortProc(p, h, proc):
    return 1


@dll(5)
def Escape(p, h, code, n, data, out):
    return 0
