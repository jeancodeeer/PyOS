# Small DLLs, one Dll object each (the loader finds them through IN_FILE in
# __init__.py):
#
#   version   the version information of a program (its VS_VERSIONINFO resource)
#   dbghelp   one helper: where a module's PE header is
#   imm32     input methods for Asian languages: none here, so "no IME"
#   sensapi   "is there a network?": yes, a local one
#   wininet   only InternetCrackUrl, which splits a URL into its parts
import struct
from pywin import mem
from pywin.dlls import Dll

dll_version = Dll("version")
dll_dbghelp = Dll("dbghelp")
dll_imm32 = Dll("imm32")
dll_sensapi = Dll("sensapi")
dll_wininet = Dll("wininet")
dll = dll_version


# ---- version.dll ----

def _version_block(p, path):
    """The VS_VERSIONINFO resource of a program file, as bytes (or None)."""
    from pywin import pe
    try:
        host = p.host_path(path)
    except OSError:
        return None
    if host == p.path:
        found = p.image.resource(p.base, 16, 1)               # RT_VERSION, number 1
        return mem.read(found[0], found[1]) if found else None
    try:
        img = pe.Image(pe.read_file(host))
    except Exception:
        return None
    import uctypes
    buf = img._unpacked()
    found = img.resource(uctypes.addressof(buf), 16, 1)
    return mem.read(found[0], found[1]) if found else None


@dll_version(2)
def GetFileVersionInfoSizeW(p, name, handle):
    if handle:
        mem.put32(handle, 0)
    block = _version_block(p, mem.wstr(name))
    if block is None:
        p.last_error = 1813                                   # ERROR_RESOURCE_TYPE_NOT_FOUND
        return 0
    return len(block)


@dll_version(4)
def GetFileVersionInfoW(p, name, handle, size, out):
    block = _version_block(p, mem.wstr(name))
    if block is None:
        return 0
    mem.write(out, block[:size])
    return 1


def _walk(block, at, path, found):
    """Visit the tree of the version block: found[path] = (value offset, value length)."""
    length, value_len, kind = struct.unpack_from("<HHH", block, at)
    end = at + length
    k = at + 6
    key = ""
    while k + 1 < len(block):
        c = block[k] | block[k + 1] << 8
        k += 2
        if c == 0:
            break
        key += chr(c)
    k = (k + 3) & ~3
    here = path + "\\" + key if path is not None else ""
    size = value_len * 2 if kind == 1 else value_len          # text values count characters
    found[here or "\\"] = (k, value_len)
    k = (k + size + 3) & ~3
    while k < end:
        child_len = struct.unpack_from("<H", block, k)[0]
        if not child_len:
            break
        _walk(block, k, here, found)
        k = (k + child_len + 3) & ~3


@dll_version(4)
def VerQueryValueW(p, block_addr, sub, out_ptr, out_len):
    size = struct.unpack("<H", mem.read(block_addr, 2))[0]
    block = mem.read(block_addr, size)
    found = {}
    try:
        _walk(block, 0, None, found)
    except Exception:
        return 0
    want = (mem.wstr(sub) or "\\").rstrip("\\") or "\\"
    for path, (off, n) in found.items():
        if path.lower() == want.lower():
            mem.put64(out_ptr, block_addr + off)
            mem.put32(out_len, n)
            return 1
    return 0


# ---- dbghelp.dll ----

@dll_dbghelp(1)
def ImageNtHeader(p, base):
    return base + mem.u32(base + 0x3C)


# ---- imm32.dll: no input method editor ----

@dll_imm32(1)
def ImmGetContext(p, hwnd):
    return 0


for _name, _n in (("ImmReleaseContext", 2), ("ImmNotifyIME", 4), ("ImmSetCandidateWindow", 2),
                  ("ImmSetCompositionWindow", 2), ("ImmSetCompositionFontW", 2), ("ImmEscapeW", 4),
                  ("ImmSetCompositionStringW", 6), ("ImmGetCompositionStringW", 4), ("ImmAssociateContext", 2),
                  ("ImmGetOpenStatus", 1), ("ImmIsIME", 1)):
    dll_imm32.functions[_name] = ((lambda p, *a: 0), _n)


# ---- sensapi.dll ----

@dll_sensapi(1)
def IsNetworkAlive(p, flags):
    if flags:
        mem.put32(flags, 1)                                   # NETWORK_ALIVE_LAN
    return 1


@dll_sensapi(2)
def IsDestinationReachableW(p, dest, info):
    return 0


# ---- wininet.dll: InternetCrackUrlW ----

SCHEMES = {"http": 3, "https": 4, "ftp": 1, "file": 5}


@dll_wininet(4)
def InternetCrackUrlW(p, url, length, flags, parts):
    text = mem.wstr(url) if not length else mem.wstr(url, length)
    scheme, _, rest = text.partition("://")
    host, slash, path = rest.partition("/")
    path = slash + path
    extra = ""
    for mark in ("?", "#"):
        if mark in path:
            path, _, tail = path.partition(mark)
            extra = mark + tail + extra
            break
    port = 443 if scheme.lower() == "https" else 80
    if ":" in host:
        host, _, port_text = host.partition(":")
        port = int(port_text or port)
    offsets = {"scheme": 0, "host": len(scheme) + 3, "path": len(scheme) + 3 + len(rest) - len(path) - len(extra)}
    offsets["extra"] = offsets["path"] + len(path)

    def field(ptr_at, len_at, value, offset):
        given = mem.u64(parts + ptr_at)
        room = mem.u32(parts + len_at)
        if given and room:                                    # a buffer: copy the text
            if room <= len(value):
                return False
            mem.put_wstr(given, value)
            mem.put32(parts + len_at, len(value))
        elif room:                                            # no buffer: point into the URL
            mem.put64(parts + ptr_at, url + 2 * offset)
            mem.put32(parts + len_at, len(value))
        return True
    ok = field(8, 16, scheme, offsets["scheme"]) and field(24, 32, host, offsets["host"])
    mem.put32(parts + 20, SCHEMES.get(scheme.lower(), 0))
    mem.put16(parts + 36, port)
    ok = ok and field(72, 80, path, offsets["path"]) and field(88, 96, extra, offsets["extra"])
    for at in (48, 64):                                       # no user name, no password
        mem.put32(parts + at, 0)
    return 1 if ok else 0
