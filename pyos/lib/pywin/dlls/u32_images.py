# user32.dll, part 4: icons, cursors and bitmaps from a program's resources
# (or from .ico / .bmp files), decoded by pywin/pictures.py.
#
# An HICON is a number; p.state["icons"] maps it to a pygame Surface, which
# DrawIconEx and the image lists (comctl32.py) draw. An HBITMAP is a gdi32
# Bitmap object, like the ones CreateCompatibleBitmap makes.
from pywin import mem, gui, pictures
from pywin.dlls.user32 import dll, _i32, _resource_name

RT_CURSOR, RT_BITMAP, RT_ICON, RT_GROUP_CURSOR, RT_GROUP_ICON = 1, 2, 3, 12, 14
IMAGE_BITMAP, IMAGE_ICON, IMAGE_CURSOR = 0, 1, 2
LR_LOADFROMFILE, LR_DEFAULTSIZE, LR_SHARED = 0x10, 0x40, 0x8000
SYSTEM_CURSOR = 0x20001                    # every cursor is the desktop's own arrow
SM_ICON, SM_SMALL = 32, 16


def new_icon(p, surface):
    icons = p.state.setdefault("icons", {})
    handle = 0x40000 + 2 * len(icons) + 2
    while handle in icons:
        handle += 2
    icons[handle] = surface
    return handle


def icon_surface(p, handle):
    return p.state.get("icons", {}).get(handle)


def _icon_from_resources(p, inst, name, want, group_kind=RT_GROUP_ICON, kind=RT_ICON):
    found = p.resource(inst or p.base, group_kind, name)
    if not found:
        return None
    entries = pictures.group_entries(mem.read(found[0], min(found[1], 6 + 14 * 64)))
    if not entries:
        return None
    w, h, bits, ident, size = pictures.best_icon(entries, want)
    picture = p.resource(inst or p.base, kind, ident)
    if not picture:
        return None
    data = mem.read(picture[0], picture[1])
    if kind == RT_CURSOR:
        data = data[4:]                                    # a cursor picture starts with its hot spot
    return pictures.icon_image(data)


def load_icon(p, inst, name, w=0, h=0):
    """An HICON for icon `name` of module inst (0 if there is none)."""
    try:
        surf = _icon_from_resources(p, inst, name, w or SM_ICON)
    except (ValueError, IndexError) as e:
        p.warn("icono %r dañado: %s" % (name, e))
        return 0
    if surf is None:
        return 0
    return new_icon(p, pictures.fit(surf, w or SM_ICON, h or SM_ICON))


def load_bitmap(p, inst, name):
    from pywin.dlls import gdi32
    found = p.resource(inst or p.base, RT_BITMAP, name)
    if not found:
        return 0
    try:
        surf = pictures.dib(mem.read(found[0], found[1]))
    except (ValueError, IndexError) as e:
        p.warn("mapa de bits %r dañado: %s" % (name, e))
        return 0
    bmp = gui.Bitmap(1, 1)
    bmp.surface = surf
    return gdi32.new_object(p, bmp)


def _from_file(p, path, kind, w, h):
    from pywin import pe
    try:
        data = pe.read_file(p.host_path(path))
        if kind == IMAGE_BITMAP:
            from pywin.dlls import gdi32
            bmp = gui.Bitmap(1, 1)
            bmp.surface = pictures.bmp_file(data)
            return gdi32.new_object(p, bmp)
        if kind == IMAGE_CURSOR:
            return SYSTEM_CURSOR
        return new_icon(p, pictures.fit(pictures.ico_file(data, w or SM_ICON), w or SM_ICON, h or SM_ICON))
    except (OSError, ValueError, IndexError):
        return 0


def _load_image(p, inst, name, kind, w, h, flags, wide):
    w, h = _i32(w), _i32(h)
    if flags & LR_LOADFROMFILE:
        path = mem.wstr(name) if wide else mem.cstr(name)
        return _from_file(p, path or "", kind, w, h)
    if not inst and name < 0x10000:                       # a system picture (IDI_..., IDC_..., OBM_...)
        return SYSTEM_CURSOR if kind == IMAGE_CURSOR else (0x20000 + name if kind == IMAGE_ICON else 0)
    key = _resource_name(name, wide)
    if kind == IMAGE_BITMAP:
        return load_bitmap(p, inst, key)
    if kind == IMAGE_CURSOR:
        return SYSTEM_CURSOR
    if flags & LR_DEFAULTSIZE and not w:
        w = h = SM_ICON
    return load_icon(p, inst, key, w, h)


@dll(6)
def LoadImageW(p, inst, name, kind, w, h, flags):
    return _load_image(p, inst, name, kind, w, h, flags, True)


@dll(6)
def LoadImageA(p, inst, name, kind, w, h, flags):
    return _load_image(p, inst, name, kind, w, h, flags, False)


@dll(2)
def LoadIconW(p, inst, name):
    if not inst:
        return 0x20000 + (name & 0xFFFF)                  # IDI_APPLICATION, IDI_WARNING...
    return load_icon(p, inst, _resource_name(name, True))


@dll(2)
def LoadIconA(p, inst, name):
    if not inst:
        return 0x20000 + (name & 0xFFFF)
    return load_icon(p, inst, _resource_name(name, False))


@dll(2)
def LoadCursorW(p, inst, name):
    return SYSTEM_CURSOR


for _name in ("LoadCursorA",):
    dll.alias(_name, "LoadCursorW")


@dll(2)
def LoadBitmapW(p, inst, name):
    return load_bitmap(p, inst, _resource_name(name, True))


@dll(2)
def LoadBitmapA(p, inst, name):
    return load_bitmap(p, inst, _resource_name(name, False))


@dll(5)
def CopyImage(p, h, kind, w, hh, flags):
    if kind == IMAGE_ICON:
        surf = icon_surface(p, h)
        if surf is None:
            return h
        return new_icon(p, pictures.fit(surf, _i32(w), _i32(hh)) if w and hh else surf.copy())
    return h


@dll(7)
def CreateIconFromResourceEx(p, data, size, is_icon, version, w, h, flags):
    try:
        raw = mem.read(data, size)
        surf = pictures.icon_image(raw if is_icon else raw[4:])
    except (ValueError, IndexError):
        return 0
    return new_icon(p, pictures.fit(surf, _i32(w), _i32(h)))


@dll(1)
def DestroyIcon(p, icon):
    p.state.get("icons", {}).pop(icon, None)
    return 1


dll.alias("DestroyCursor", "DestroyIcon")


@dll(9)
def DrawIconEx(p, hdc, x, y, icon, w, h, step, brush, flags):
    from pywin.dlls import gdi32
    from pywin.dlls.g32_extra import clipped_blit
    dc = gdi32._dc(p, hdc)
    surf = icon_surface(p, icon)
    if dc is None or surf is None:
        return 1
    clipped_blit(dc, pictures.fit(surf, _i32(w), _i32(h)), _i32(x), _i32(y))
    dc.changed()
    return 1


@dll(4)
def DrawIcon(p, hdc, x, y, icon):
    return DrawIconEx(p, hdc, x, y, icon, 0, 0, 0, 0, 3)


@dll(2)
def GetIconInfo(p, icon, out):
    from pywin.dlls import gdi32
    mem.zero(out, 32)
    mem.put32(out, 1)                                      # an icon, not a cursor
    surf = icon_surface(p, icon)
    if surf is not None:
        bmp = gui.Bitmap(1, 1)
        bmp.surface = surf
        mem.put64(out + 24, gdi32.new_object(p, bmp))      # hbmColor
    return 1
