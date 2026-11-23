# Reading and writing the Windows program's memory from Python.
#
# The program's memory is ordinary RAM, so these are plain loads and stores
# at an address: u32(addr), put32(addr, v), cstr(addr) for a C string...
import struct
import uctypes


def view(addr, size):
    return uctypes.bytearray_at(addr, size)


def read(addr, size):
    return bytes(uctypes.bytearray_at(addr, size))


def write(addr, data):
    if data:
        uctypes.bytearray_at(addr, len(data))[:] = data


def zero(addr, size):
    write(addr, bytes(size))


def u8(a):
    return uctypes.bytearray_at(a, 1)[0]


def u16(a):
    return struct.unpack("<H", read(a, 2))[0]


def u32(a):
    return struct.unpack("<I", read(a, 4))[0]


def i32(a):
    return struct.unpack("<i", read(a, 4))[0]


def u64(a):
    return struct.unpack("<Q", read(a, 8))[0]


def put8(a, v):
    uctypes.bytearray_at(a, 1)[0] = v & 0xFF


def put16(a, v):
    write(a, struct.pack("<H", v & 0xFFFF))


def put32(a, v):
    write(a, struct.pack("<I", v & 0xFFFFFFFF))


def put64(a, v):
    write(a, struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF))


def cbytes(a, limit=1 << 20):
    """The bytes of a C string (up to its zero byte)."""
    out = b""
    while len(out) < limit:
        n = min(256, 4096 - (a & 4095))          # never read past this page
        chunk = read(a, n)
        end = chunk.find(b"\0")
        if end >= 0:
            return out + chunk[:end]
        out += chunk
        a += n
    return out


def cstr(a):
    if not a:
        return None
    return _latin(cbytes(a))


def _latin(b):
    try:
        return b.decode()
    except UnicodeError:
        return "".join(chr(c) for c in b)


def wstr(a, limit=1 << 16):
    """A UTF-16 string (Windows' 'wide' strings)."""
    if not a:
        return None
    chars = []
    while len(chars) < limit:
        c = u16(a)
        if c == 0:
            break
        chars.append(chr(c))
        a += 2
    return "".join(chars)


def put_cstr(a, s):
    data = s.encode() if isinstance(s, str) else bytes(s)
    write(a, data + b"\0")
    return len(data)


def put_wstr(a, s):
    data = b"".join(struct.pack("<H", ord(c) & 0xFFFF) for c in s)
    write(a, data + b"\0\0")
    return len(s)
