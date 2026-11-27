# advapi32.dll: the Windows registry, kept in a JSON file on the SnakeyOS disk
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


# ---- the wide (W) versions that were still missing ----

@dll(2)
def RegDeleteValueW(p, h, name):
    values = _values(p, h)
    target = (mem.wstr(name) if name else "").lower()
    for k in list(values or {}):
        if k.lower() == target:
            del values[k]
            _save(p)
            return ERROR_SUCCESS
    return ERROR_FILE_NOT_FOUND


@dll(2)
def RegDeleteKeyW(p, h, sub):
    path = _path(p, h, mem.wstr(sub) if sub else "")
    reg = _load(p)
    real = _find(reg, path) if path else None
    if real is None:
        return ERROR_FILE_NOT_FOUND
    del reg[real]
    _save(p)
    return ERROR_SUCCESS


def _subkeys(p, h):
    base = _path(p, h, "")
    if base is None:
        return None
    prefix = (base + "\\").lower()
    return sorted(set(k[len(prefix):].split("\\")[0] for k in _load(p) if k.lower().startswith(prefix)))


@dll(8)
def RegEnumKeyExW(p, h, index, buf, size, reserved, cls, cls_size, when):
    names = _subkeys(p, h)
    if names is None:
        return 6
    if index >= len(names):
        return ERROR_NO_MORE_ITEMS
    room = mem.u32(size)
    if room <= len(names[index]):
        return ERROR_MORE_DATA
    mem.put_wstr(buf, names[index])
    mem.put32(size, len(names[index]))
    if when:
        mem.put64(when, 0)
    return ERROR_SUCCESS


@dll(4)
def RegEnumKeyW(p, h, index, buf, size):
    names = _subkeys(p, h)
    if names is None:
        return 6
    if index >= len(names):
        return ERROR_NO_MORE_ITEMS
    mem.put_wstr(buf, names[index][:size - 1])
    return ERROR_SUCCESS


@dll(8)
def RegEnumValueW(p, h, index, name, name_size, reserved, kind, data, data_size):
    values = _values(p, h)
    if values is None:
        return 6
    keys = list(values)
    if index >= len(keys):
        return ERROR_NO_MORE_ITEMS
    if mem.u32(name_size) <= len(keys[index]):
        return ERROR_MORE_DATA
    mem.put_wstr(name, keys[index])
    mem.put32(name_size, len(keys[index]))
    return _query(p, h, keys[index], kind, data, data_size, True)


@dll(12)
def RegQueryInfoKeyW(p, h, cls, cls_size, reserved, subkeys, max_sub, max_cls, values, max_name, max_value,
                     security, when):
    names = _subkeys(p, h)
    vals = _values(p, h)
    if names is None or vals is None:
        return ERROR_FILE_NOT_FOUND
    for ptr, v in ((subkeys, len(names)), (max_sub, max([len(n) for n in names] or [0])), (max_cls, 0),
                   (values, len(vals)), (max_name, max([len(n) for n in vals] or [0])), (max_value, 4096),
                   (security, 0)):
        if ptr:
            mem.put32(ptr, v)
    if cls_size:
        mem.put32(cls_size, 0)
    if when:
        mem.put64(when, 0)
    return ERROR_SUCCESS


@dll(7)
def RegGetValueW(p, h, sub, name, flags, kind, data, size):
    handle = h
    opened = 0
    if sub:
        out = p.heap.alloc(8)
        r = RegOpenKeyExW(p, h, sub, 0, 0, out)
        opened = handle = mem.u64(out)
        p.heap.free(out)
        if r != ERROR_SUCCESS:
            return r
    try:
        return _query(p, handle, mem.wstr(name) if name else "", kind, data, size, True)
    finally:
        if opened:
            p.handles.pop(opened, None)


# ---- the old CryptoAPI: hashes, done for real with hashlib ----

CALG = {0x8003: "md5", 0x8004: "sha1", 0x800C: "sha256", 0x800D: "sha384", 0x800E: "sha512"}
HP_HASHVAL, HP_HASHSIZE, HP_ALGID = 2, 4, 1


class CryptHash:
    def __init__(self, algid):
        import hashlib
        self.algid = algid
        name = CALG[algid]
        if hasattr(hashlib, name):
            self.h = getattr(hashlib, name)()
        else:
            import crypto
            self.h = getattr(crypto, name)()


@dll(5)
def CryptAcquireContextW(p, out, container, provider, kind, flags):
    mem.put64(out, 1)
    return 1


@dll(5)
def CryptCreateHash(p, prov, algid, key, flags, out):
    if algid not in CALG:
        p.last_error = 0x80090008                            # NTE_BAD_ALGID
        return 0
    mem.put64(out, p.new_handle(CryptHash(algid)))
    return 1


@dll(4)
def CryptHashData(p, h, data, size, flags):
    obj = p.handles.get(h)
    if not isinstance(obj, CryptHash):
        return 0
    obj.h.update(mem.read(data, size))
    return 1


@dll(5)
def CryptGetHashParam(p, h, param, data, size, flags):
    obj = p.handles.get(h)
    if not isinstance(obj, CryptHash):
        return 0
    if param == HP_HASHVAL:
        value = obj.h.digest()
    elif param == HP_HASHSIZE:
        value = struct.pack("<I", len(obj.h.digest()))
    elif param == HP_ALGID:
        value = struct.pack("<I", obj.algid)
    else:
        return 0
    room = mem.u32(size)
    mem.put32(size, len(value))
    if data:
        if room < len(value):
            p.last_error = ERROR_MORE_DATA
            return 0
        mem.write(data, value)
    return 1


@dll(1)
def CryptDestroyHash(p, h):
    p.handles.pop(h, None)
    return 1


# ---- security identifiers (SIDs): "is the user an administrator?" -> no ----

@dll(11)
def AllocateAndInitializeSid(p, authority, count, s0, s1, s2, s3, s4, s5, s6, s7, out):
    count = min(count, 8)
    sid = p.heap.alloc(8 + 4 * 8)
    mem.put8(sid, 1)                                         # revision
    mem.put8(sid + 1, count)
    mem.write(sid + 2, mem.read(authority, 6))
    for k, v in enumerate((s0, s1, s2, s3, s4, s5, s6, s7)[:count]):
        mem.put32(sid + 8 + 4 * k, v)
    mem.put64(out, sid)
    return 1


@dll(1)
def FreeSid(p, sid):
    if sid:
        p.heap.free(sid)
    return 0


@dll(1)
def GetSidSubAuthorityCount(p, sid):
    return sid + 1


@dll(2)
def GetSidSubAuthority(p, sid, n):
    return sid + 8 + 4 * n


@dll(3)
def CheckTokenMembership(p, token, sid, member):
    mem.put32(member, 0)                                     # PyWin programs never run as admin
    return 1


@dll(4)
def ConvertStringSecurityDescriptorToSecurityDescriptorW(p, text, revision, out, size):
    sd = p.heap.alloc(40)                                    # an empty descriptor: no rules
    mem.zero(sd, 40)
    mem.put8(sd, 1)
    mem.put64(out, sd)
    if size:
        mem.put32(size, 40)
    return 1


@dll(3)
def IsTextUnicode(p, buf, size, result):
    """A guess like Windows makes: many zero bytes in odd places means UTF-16."""
    data = mem.read(buf, min(_i32_size(size), 4096))
    if len(data) < 2:
        return 0
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        found = True
    else:
        odd_zeros = sum(1 for k in range(1, len(data), 2) if data[k] == 0)
        found = odd_zeros > len(data) // 4
    if result:
        mem.put32(result, 1 if found else 0)
    return 1 if found else 0


def _i32_size(v):
    v &= 0xFFFFFFFF
    return 0 if v >> 31 else v
