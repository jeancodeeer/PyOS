# Reading and writing the Windows program's memory from Python.
#
# The program's memory is ordinary RAM, so these are plain loads and stores
# at an address: u32(addr), put32(addr, v), cstr(addr) for a C string...
import struct
import uctypes

# Fast helpers in "viper" (MicroPython compiles them to machine code): text
# is converted between 1-byte and 2-byte (UTF-16) characters a lot.
try:
    import micropython

    @micropython.viper
    def widen(src: ptr8, dst: ptr8, n: int):
        """n bytes of plain ASCII -> UTF-16 (each byte, then a zero)."""
        i = 0
        while i < n:
            dst[2 * i] = src[i]
            dst[2 * i + 1] = 0
            i += 1

    @micropython.viper
    def wide_len(src: ptr16, limit: int) -> int:
        """Characters before the zero that ends a UTF-16 string (at most limit)."""
        i = 0
        while i < limit and src[i] != 0:
            i += 1
        return i

    @micropython.viper
    def narrow(src: ptr16, dst: ptr8, n: int) -> int:
        """UTF-16 -> 1 byte each; returns 0 if a character did not fit (not ASCII)."""
        i = 0
        while i < n:
            c = src[i]
            if c > 127:
                return 0
            dst[i] = c
            i += 1
        return 1
except (ImportError, AttributeError, SyntaxError):           # plain Python (tests on a PC)
    def widen(src, dst, n):
        for i in range(n):
            dst[2 * i], dst[2 * i + 1] = src[i], 0

    def wide_len(src, limit):
        raise NotImplementedError

    def narrow(src, dst, n):
        return 0

FAST = "micropython" in globals()


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


def cstr_limited(a, limit):
    """Like cstr, but never reads more than limit bytes (for tables of a file)."""
    raw = cbytes(a, max(0, min(limit, 1 << 16)))
    try:
        return raw.decode()
    except UnicodeError:
        return _latin(raw)


def _latin(b):
    try:
        return b.decode()
    except UnicodeError:
        return "".join(chr(c) for c in b)


def wstr(a, limit=1 << 16):
    """A UTF-16 string (Windows' 'wide' strings)."""
    if not a:
        return None
    if FAST:
        n = wide_len(a, limit)
        out = bytearray(n)
        if narrow(a, out, n):                                 # plain ASCII: the quick way
            return out.decode()
        raw = read(a, 2 * n)
        return _from_utf16(raw)
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
    raw = s.encode()
    if len(raw) == len(s):                                    # plain ASCII: the quick way
        out = bytearray(2 * len(raw) + 2)
        widen(raw, out, len(raw))
        write(a, out)
        return len(s)
    data = to_utf16(s)
    write(a, data + b"\0\0")
    return len(data) // 2


def to_utf16(s):
    """Text as UTF-16 bytes; characters past U+FFFF become two "surrogates"."""
    raw = s.encode()
    if len(raw) == len(s):
        out = bytearray(2 * len(raw))
        widen(raw, out, len(raw))
        return bytes(out)
    out = bytearray()
    for c in s:
        n = ord(c)
        if n > 0xFFFF:
            n -= 0x10000
            for half in (0xD800 | (n >> 10), 0xDC00 | (n & 0x3FF)):
                out += bytes((half & 255, half >> 8))
        else:
            out += bytes((n & 255, n >> 8))
    return bytes(out)


def _from_utf16(raw):
    """UTF-16 bytes -> text (surrogate pairs joined again)."""
    out, k = [], 0
    while k + 1 < len(raw):
        c = raw[k] | raw[k + 1] << 8
        k += 2
        if 0xD800 <= c < 0xDC00 and k + 1 < len(raw):
            low = raw[k] | raw[k + 1] << 8
            if 0xDC00 <= low < 0xE000:
                c = 0x10000 + ((c - 0xD800) << 10) + (low - 0xDC00)
                k += 2
        out.append(chr(c))
    return "".join(out)
