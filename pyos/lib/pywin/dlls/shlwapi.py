# shlwapi.dll: little helpers for paths (C:\folder\file.txt) and colours.
# Paths are edited in the program's own buffer, as Windows does.
from pywin import mem
from pywin.dlls import Dll

dll = Dll("shlwapi")
MAX_PATH = 260


def _get(ptr):
    return mem.wstr(ptr) or ""


def _set(ptr, text):
    mem.put_wstr(ptr, text[:MAX_PATH - 1])


def _join(a, b):
    if not a:
        return b
    if not b:
        return a
    return a.rstrip("\\") + "\\" + b.lstrip("\\")


def canonical(path):
    """Remove "." and ".." parts: C:\\a\\.\\b\\..\\c -> C:\\a\\c."""
    prefix = ""
    if len(path) >= 2 and path[1] == ":":
        prefix, path = path[:2], path[2:]
    absolute = path.startswith("\\")
    parts = []
    for part in path.split("\\"):
        if part == "..":
            if parts:
                parts.pop()
        elif part and part != ".":
            parts.append(part)
    out = "\\".join(parts)
    return prefix + ("\\" if absolute or prefix else "") + out


@dll(1)
def PathRemoveFileSpecW(p, ptr):
    path = _get(ptr)
    i = path.rfind("\\")
    if i < 0:
        return 0
    keep = path[:i + 1] if i == 2 and path[1:2] == ":" else path[:i]   # C:\ keeps its slash
    _set(ptr, keep)
    return 1 if keep != path else 0


@dll(1)
def PathStripPathW(p, ptr):
    path = _get(ptr)
    _set(ptr, path[path.rfind("\\") + 1:])


@dll(1)
def PathFindFileNameW(p, ptr):
    path = _get(ptr)
    return ptr + 2 * (path.rfind("\\") + 1)


@dll(1)
def PathFindExtensionW(p, ptr):
    path = _get(ptr)
    name = path.rfind("\\") + 1
    dot = path.rfind(".")
    return ptr + 2 * (dot if dot >= name else len(path))


@dll(1)
def PathRemoveExtensionW(p, ptr):
    path = _get(ptr)
    name = path.rfind("\\") + 1
    dot = path.rfind(".")
    if dot >= name:
        _set(ptr, path[:dot])


@dll(2)
def PathAppendW(p, ptr, more):
    _set(ptr, canonical(_join(_get(ptr), _get(more))))
    return 1


@dll(3)
def PathCombineW(p, out, a, b):
    second = _get(b)
    if len(second) >= 2 and second[1] == ":":
        path = second
    else:
        path = _join(_get(a), second)
    _set(out, canonical(path))
    return out


@dll(2)
def PathCanonicalizeW(p, out, src):
    _set(out, canonical(_get(src)))
    return 1


@dll(1)
def PathIsRelativeW(p, ptr):
    path = _get(ptr)
    return 0 if path.startswith("\\") or (len(path) >= 2 and path[1] == ":") else 1


@dll(1)
def PathFileExistsW(p, ptr):
    import os
    try:
        os.stat(p.host_path(_get(ptr)))
        return 1
    except OSError:
        return 0


@dll(1)
def PathIsDirectoryW(p, ptr):
    import os
    try:
        return 0x10 if os.stat(p.host_path(_get(ptr)))[0] & 0x4000 else 0
    except OSError:
        return 0


@dll(1)
def PathGetDriveNumberW(p, ptr):
    path = _get(ptr)
    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        return ord(path[0].upper()) - 65
    return -1


@dll(1)
def PathIsNetworkPathW(p, ptr):
    return 1 if _get(ptr).startswith("\\\\") else 0


dll.alias("PathIsUNCW", "PathIsNetworkPathW")


@dll(2)
def PathMatchSpecW(p, ptr, spec):
    from pywin.dlls.k32_files import match
    name = _get(ptr)
    name = name[name.rfind("\\") + 1:]
    return 1 if any(match(s.strip(), name) for s in _get(spec).split(";")) else 0


@dll(4)
def PathCompactPathExW(p, out, src, max_chars, flags):
    path = _get(src)
    if len(path) >= max_chars and max_chars > 4:
        name = path[path.rfind("\\"):]
        path = path[:max(0, max_chars - len(name) - 4)] + "..." + name
        path = path[-(max_chars - 1):]
    _set(out, path)
    return 1


@dll(4)
def PathCreateFromUrlW(p, url, out, size_ptr, reserved):
    text = _get(url)
    if text.lower().startswith("file:///"):
        text = text[8:]
    elif text.lower().startswith("file:"):
        text = text[5:]
    text = text.replace("/", "\\").replace("%20", " ")
    mem.put_wstr(out, text)
    mem.put32(size_ptr, len(text))
    return 0


@dll(6)
def AssocQueryStringW(p, flags, kind, assoc, extra, out, size_ptr):
    return 0x80070483                                       # HRESULT: no association


@dll(2)
def StrCmpIW(p, a, b):
    x, y = _get(a).lower(), _get(b).lower()
    return (x > y) - (x < y)


@dll(2)
def StrStrIW(p, hay, needle):
    k = _get(hay).lower().find(_get(needle).lower())
    return hay + 2 * k if k >= 0 else 0


@dll(3)
def SHAutoComplete(p, hwnd, flags, x):
    return 0


# ---- colours: hue, lightness, saturation (0-240, as Windows counts them) ----

def _rgb(c):
    return c & 255, (c >> 8) & 255, (c >> 16) & 255


@dll(4)
def ColorRGBToHLS(p, color, h_out, l_out, s_out):
    r, g, b = (v / 255 for v in _rgb(color))
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2
    if mx == mn:
        h = s = 0.0
    else:
        d = mx - mn
        s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == r:
            h = (g - b) / d + (6 if g < b else 0)
        elif mx == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        h /= 6
    mem.put16(h_out, int(h * 240 + 0.5))
    mem.put16(l_out, int(l * 240 + 0.5))
    mem.put16(s_out, int(s * 240 + 0.5))


def _hls_to_rgb(h, l, s):
    h, l, s = h / 240, l / 240, s / 240
    if s == 0:
        v = int(l * 255 + 0.5)
        return v, v, v

    def part(p_, q, t):
        t %= 1
        if t < 1 / 6:
            return p_ + (q - p_) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p_ + (q - p_) * (2 / 3 - t) * 6
        return p_
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p_ = 2 * l - q
    return tuple(int(part(p_, q, h + o) * 255 + 0.5) for o in (1 / 3, 0, -1 / 3))


@dll(3)
def ColorHLSToRGB(p, h, l, s):
    r, g, b = _hls_to_rgb(h & 0xFFFF, l & 0xFFFF, s & 0xFFFF)
    return r | g << 8 | b << 16


@dll(3)
def ColorAdjustLuma(p, color, n, scale):
    r, g, b = (v / 255 for v in _rgb(color))
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2 * 240
    n = n - (1 << 32) if n >> 31 else n
    l = max(0, min(240, l + n / 10 if scale else l + n))
    hcol = p.heap.alloc(16)
    ColorRGBToHLS(p, color, hcol, hcol + 2, hcol + 4)
    h, s = mem.u16(hcol), mem.u16(hcol + 4)
    p.heap.free(hcol)
    r2, g2, b2 = _hls_to_rgb(h, int(l), s)
    return r2 | g2 << 8 | b2 << 16

