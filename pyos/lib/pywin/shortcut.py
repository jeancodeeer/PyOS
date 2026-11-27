# Windows shortcuts (.lnk): reading and writing them.
#
# The layout and the order of the parts follow Wine's dlls/shell32/shelllink.c
# (IPersistStream_fnSave / Load, LGPL 2.1, see THIRD_PARTY.md) and Microsoft's
# [MS-SHLLINK]: a 0x4C-byte header, an optional item ID list, the link info
# (where the target is), then counted UTF-16 strings, and a final zero dword.
#
#   data = write(target="C:\\Program Files\\App\\app.exe", description="App", ...)
#   info = read(data)       {"target", "arguments", "workdir", "description", "icon", "icon_index", "show"}
import struct

CLSID_SHELLLINK = b"\x01\x14\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46"
HAS_ID_LIST, HAS_LINK_INFO, HAS_NAME, HAS_RELPATH = 0x01, 0x02, 0x04, 0x08
HAS_WORKINGDIR, HAS_ARGS, HAS_ICONLOCATION, UNICODE = 0x10, 0x20, 0x40, 0x80
VOLUME_ID_AND_LOCAL_BASE_PATH = 0x01


def _string(s):
    """A counted string: the number of UTF-16 units, then the units (Stream_WriteString)."""
    from pywin import mem
    raw = mem.to_utf16(s)
    return struct.pack("<H", len(raw) // 2) + raw


def _link_info(target):
    """LinkInfo with a local base path (Stream_WriteLocationInfo): the volume is a fixed disk."""
    label = b"SNAKEYOS\x00"
    volume = struct.pack("<IIII", 16 + len(label), 3, 0x534E4B59, 16) + label     # size, DRIVE_FIXED, serial
    path = target.encode("latin-1", "replace") if hasattr(target, "encode") else target
    path += b"\x00"
    header = 0x1C
    volume_at = header
    path_at = volume_at + len(volume)
    suffix_at = path_at + len(path)
    total = suffix_at + 1
    return struct.pack("<IIIIIII", total, header, VOLUME_ID_AND_LOCAL_BASE_PATH, volume_at, path_at, 0,
                       suffix_at) + volume + path + b"\x00"


def write(target, arguments="", workdir="", description="", icon="", icon_index=0, show=1, hotkey=0):
    flags = UNICODE
    parts = []
    if target:
        flags |= HAS_LINK_INFO
        parts.append(_link_info(target))
    for flag, text in ((HAS_NAME, description), (HAS_WORKINGDIR, workdir), (HAS_ARGS, arguments),
                       (HAS_ICONLOCATION, icon)):
        if text:
            flags |= flag
            parts.append(_string(text))
    header = struct.pack("<I", 0x4C) + CLSID_SHELLLINK + struct.pack("<II", flags, 0x20) + bytes(24) + \
        struct.pack("<IiIHHII", 0, icon_index, show, hotkey, 0, 0, 0)
    return header + b"".join(parts) + b"\x00\x00\x00\x00"


def _read_string(data, at, unicode):
    n = struct.unpack_from("<H", data, at)[0]
    at += 2
    if unicode:
        from pywin import mem
        raw = bytes(data[at:at + 2 * n])
        return mem._from_utf16(raw) if hasattr(mem, "_from_utf16") else raw.decode("utf-16-le", "replace"), at + 2 * n
    return bytes(data[at:at + n]).decode("latin-1"), at + n


def read(data):
    """A .lnk file -> its target and the rest (raises ValueError when it is not one)."""
    if len(data) < 0x4C or struct.unpack_from("<I", data, 0)[0] != 0x4C or bytes(data[4:20]) != CLSID_SHELLLINK:
        raise ValueError("not a Windows shortcut")
    flags = struct.unpack_from("<I", data, 0x14)[0]
    icon_index, show = struct.unpack_from("<iI", data, 0x38)
    at = 0x4C
    out = {"target": "", "arguments": "", "workdir": "", "description": "", "relative": "", "icon": "",
           "icon_index": icon_index, "show": show}
    if flags & HAS_ID_LIST:
        at += 2 + struct.unpack_from("<H", data, at)[0]
    if flags & HAS_LINK_INFO:
        total, header, lflags, vol_at, path_at, net_at, suffix_at = struct.unpack_from("<IIIIIII", data, at)
        if lflags & VOLUME_ID_AND_LOCAL_BASE_PATH and path_at:
            end = data.find(b"\x00", at + path_at)
            base = bytes(data[at + path_at:end]).decode("latin-1")
            end2 = data.find(b"\x00", at + suffix_at) if suffix_at else -1
            suffix = bytes(data[at + suffix_at:end2]).decode("latin-1") if end2 > 0 else ""
            out["target"] = base + suffix
        at += total
    unicode = bool(flags & UNICODE)
    for flag, key in ((HAS_NAME, "description"), (HAS_RELPATH, "relative"), (HAS_WORKINGDIR, "workdir"),
                      (HAS_ARGS, "arguments"), (HAS_ICONLOCATION, "icon")):
        if flags & flag:
            out[key], at = _read_string(data, at, unicode)
    if not out["target"] and out["relative"]:
        out["target"] = out["relative"]
    return out
