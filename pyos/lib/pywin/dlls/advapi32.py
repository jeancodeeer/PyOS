# advapi32.dll: the Windows registry, kept in a JSON file on the PyOS disk
# (/disk/pywin/registro.json), and a few things about the user.
#
#   {"HKEY_CURRENT_USER\\Software\\Juego": {"Puntos": [4, 1200]}}
#
# Each value is [type, data]: 1 text (REG_SZ), 4 number (REG_DWORD),
# 11 big number (REG_QWORD), 3 bytes as hex (REG_BINARY).
import json
import struct
from pywin import mem
from pywin.dlls import Dll

dll = Dll("advapi32")
FILE = "/disk/pywin/registro.json"
ROOTS = {0x80000000: "HKEY_CLASSES_ROOT", 0x80000001: "HKEY_CURRENT_USER", 0x80000002: "HKEY_LOCAL_MACHINE",
         0x80000003: "HKEY_USERS", 0x80000005: "HKEY_CURRENT_CONFIG"}
ERROR_SUCCESS, ERROR_FILE_NOT_FOUND, ERROR_MORE_DATA, ERROR_NO_MORE_ITEMS = 0, 2, 234, 259
REG_SZ, REG_EXPAND_SZ, REG_BINARY, REG_DWORD, REG_MULTI_SZ, REG_QWORD = 1, 2, 3, 4, 7, 11


class Key:
    def __init__(self, path):
        self.path = path

    def close(self):
        pass


def _load(p):
    if "registry" not in p.state:
        try:
            with open(FILE) as f:
                p.state["registry"] = json.load(f)
        except (OSError, ValueError):
            p.state["registry"] = {}
    return p.state["registry"]


def _save(p):
    import os
    for folder in ("/disk/pywin",):
        try:
            os.mkdir(folder)
        except OSError:
            pass
    try:
        with open(FILE, "w") as f:
            json.dump(_load(p), f)
    except OSError:
        pass


def _path(p, h, sub):
    if h >> 32 == 0xFFFFFFFF:                             # HKEY_CURRENT_USER and friends come sign-extended
        h &= 0xFFFFFFFF
    base = ROOTS.get(h)
    if base is None:
        key = p.handles.get(h)
        if not isinstance(key, Key):
            return None
        base = key.path
    sub = (sub or "").strip("\\")
    return base + ("\\" + sub if sub else "")


def _find(reg, path):
    """The key's real spelling (keys ignore upper and lower case)."""
    low = path.lower()
    for k in reg:
        if k.lower() == low:
            return k
    return None


def _open(p, h, sub, out, create):
    path = _path(p, h, sub)
    if path is None:
        return 6                                          # ERROR_INVALID_HANDLE
    reg = _load(p)
    real = _find(reg, path)
    if real is None:
        if "\\" not in path:                              # a root key always exists
            reg[path] = {}
            real = path
        elif not create:
            return ERROR_FILE_NOT_FOUND
        else:
            reg[path] = {}
            real = path
            _save(p)
    mem.put64(out, p.new_handle(Key(real)))
    return ERROR_SUCCESS


@dll(5)
def RegOpenKeyExA(p, h, sub, options, access, out):
    return _open(p, h, mem.cstr(sub) if sub else "", out, False)


@dll(5)
def RegOpenKeyExW(p, h, sub, options, access, out):
    return _open(p, h, mem.wstr(sub) if sub else "", out, False)


@dll(3)
def RegOpenKeyA(p, h, sub, out):
    return _open(p, h, mem.cstr(sub) if sub else "", out, False)


@dll(9)
def RegCreateKeyExA(p, h, sub, reserved, cls, options, access, security, out, disposition):
    if disposition:
        mem.put32(disposition, 1)                         # REG_CREATED_NEW_KEY
    return _open(p, h, mem.cstr(sub) if sub else "", out, True)


@dll(9)
def RegCreateKeyExW(p, h, sub, reserved, cls, options, access, security, out, disposition):
    if disposition:
        mem.put32(disposition, 1)
    return _open(p, h, mem.wstr(sub) if sub else "", out, True)


@dll(3)
def RegCreateKeyA(p, h, sub, out):
    return _open(p, h, mem.cstr(sub) if sub else "", out, True)


@dll(1)
def RegCloseKey(p, h):
    p.handles.pop(h, None)
    return ERROR_SUCCESS


def _values(p, h):
    path = _path(p, h, "")
    reg = _load(p)
    real = _find(reg, path) if path else None
    return reg.get(real) if real else None


def _query(p, h, name, kind_out, data, size_out, wide):
    values = _values(p, h)
    if values is None:
        return ERROR_FILE_NOT_FOUND
    entry = None
    for k, v in values.items():
        if k.lower() == (name or "").lower():
            entry = v
    if entry is None:
        return ERROR_FILE_NOT_FOUND
    kind, value = entry
    if kind in (REG_SZ, REG_EXPAND_SZ):
        raw = (value.encode() + b"\0") if not wide else b"".join(struct.pack("<H", ord(c)) for c in value + "\0")
    elif kind == REG_DWORD:
        raw = struct.pack("<I", value & 0xFFFFFFFF)
    elif kind == REG_QWORD:
        raw = struct.pack("<Q", value)
    else:
        raw = bytes.fromhex(value)
    if kind_out:
        mem.put32(kind_out, kind)
    if size_out:
        room = mem.u32(size_out)
        mem.put32(size_out, len(raw))
        if data:
            if room < len(raw):
                return ERROR_MORE_DATA
            mem.write(data, raw)
    return ERROR_SUCCESS


@dll(6)
def RegQueryValueExA(p, h, name, reserved, kind, data, size):
    return _query(p, h, mem.cstr(name) if name else "", kind, data, size, False)


@dll(6)
def RegQueryValueExW(p, h, name, reserved, kind, data, size):
    return _query(p, h, mem.wstr(name) if name else "", kind, data, size, True)


def _set(p, h, name, kind, data, size, wide):
    values = _values(p, h)
    if values is None:
        return ERROR_FILE_NOT_FOUND
    raw = mem.read(data, size) if data and size else b""
    if kind in (REG_SZ, REG_EXPAND_SZ):
        if wide:
            value = "".join(chr(raw[k] | raw[k + 1] << 8) for k in range(0, len(raw) - 1, 2)).split("\0")[0]
        else:
            value = raw.split(b"\0")[0].decode()
    elif kind == REG_DWORD:
        value = struct.unpack("<I", raw[:4])[0]
    elif kind == REG_QWORD:
        value = struct.unpack("<Q", raw[:8])[0]
    else:
        value = raw.hex()
    for k in list(values):
        if k.lower() == name.lower():
            del values[k]
    values[name] = [kind, value]
    _save(p)
    return ERROR_SUCCESS


@dll(6)
def RegSetValueExA(p, h, name, reserved, kind, data, size):
    return _set(p, h, mem.cstr(name) if name else "", kind, data, size, False)


@dll(6)
def RegSetValueExW(p, h, name, reserved, kind, data, size):
    return _set(p, h, mem.wstr(name) if name else "", kind, data, size, True)


@dll(2)
def RegDeleteValueA(p, h, name):
    values = _values(p, h)
    target = (mem.cstr(name) or "").lower()
    for k in list(values or {}):
        if k.lower() == target:
            del values[k]
            _save(p)
            return ERROR_SUCCESS
    return ERROR_FILE_NOT_FOUND


@dll(2)
def RegDeleteKeyA(p, h, sub):
    path = _path(p, h, mem.cstr(sub))
    reg = _load(p)
    real = _find(reg, path) if path else None
    if real is None:
        return ERROR_FILE_NOT_FOUND
    del reg[real]
    _save(p)
    return ERROR_SUCCESS


@dll(4)
def RegEnumKeyA(p, h, index, buf, size):
    base = _path(p, h, "")
    prefix = (base + "\\").lower()
    names = sorted(set(k[len(prefix):].split("\\")[0] for k in _load(p) if k.lower().startswith(prefix)))
    if index >= len(names):
        return ERROR_NO_MORE_ITEMS
    mem.put_cstr(buf, names[index][:size - 1])
    return ERROR_SUCCESS


@dll(1)
def RegFlushKey(p, h):
    return ERROR_SUCCESS


@dll(2)
def GetUserNameA(p, buf, size):
    name = _user()
    if mem.u32(size) <= len(name):
        mem.put32(size, len(name) + 1)
        return 0
    mem.put_cstr(buf, name)
    mem.put32(size, len(name) + 1)
    return 1


@dll(2)
def GetUserNameW(p, buf, size):
    name = _user()
    if mem.u32(size) <= len(name):
        mem.put32(size, len(name) + 1)
        return 0
    mem.put_wstr(buf, name)
    mem.put32(size, len(name) + 1)
    return 1


def _user():
    try:
        from kernel import users
        return users.whoami() or "usuario"
    except Exception:
        return "usuario"


# security functions programs call "just in case": all is allowed here
@dll(3)
def OpenProcessToken(p, process, access, out):
    mem.put64(out, p.new_handle(Key("token")))
    return 1


@dll(5)
def GetTokenInformation(p, token, kind, info, size, needed):
    if needed:
        mem.put32(needed, 0)
    return 0


@dll(3)
def CryptAcquireContextA(p, out, container, provider):
    mem.put64(out, 1)
    return 1


@dll(3)
def CryptGenRandom(p, prov, n, buf):
    import os
    try:
        mem.write(buf, os.urandom(n))
    except Exception:
        import crypto
        mem.write(buf, crypto.random_bytes(n))
    return 1


@dll(2)
def CryptReleaseContext(p, prov, flags):
    return 1


@dll(2)
def SystemFunction036(p, buf, n):                   # RtlGenRandom
    return CryptGenRandom(p, 0, n, buf)
