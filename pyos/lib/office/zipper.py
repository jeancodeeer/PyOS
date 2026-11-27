# ZIP files, read and written in plain Python (MicroPython has no zipfile).
#
# Office documents (.docx, .xlsx, .pptx) are ZIP files full of XML. We
# write the entries "stored" (not compressed): every ZIP reader, Microsoft
# Office included, accepts that. Reading also understands "deflated"
# entries, which is what Office itself writes.
#
#   data = zipper.write({"a.txt": b"hola", "b/c.xml": b"<x/>"})
#   files = zipper.read(data)          # {"a.txt": b"hola", ...}
import struct

_TABLE = []


def crc32(data, crc=0):
    """The checksum every ZIP entry carries (the same as zlib.crc32)."""
    if not _TABLE:
        for n in range(256):
            c = n
            for _ in range(8):
                c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
            _TABLE.append(c)
    try:
        import binascii                       # done in C when this Python has it
        return binascii.crc32(data, crc) & 0xFFFFFFFF
    except (ImportError, AttributeError, TypeError):
        pass
    table = _TABLE
    crc ^= 0xFFFFFFFF
    for b in data:
        crc = table[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


DOS_DATE = (2026 - 1980) << 9 | 1 << 5 | 1     # a fixed date: 1 January 2026


def write(files):
    """The bytes of a ZIP file with these {name: bytes} entries, in order."""
    out = bytearray()
    central = bytearray()
    for name, data in files.items():
        if isinstance(data, str):
            data = data.encode()
        raw_name = name.encode()
        crc = crc32(data)
        at = len(out)
        out += struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0x0800, 0, 0, DOS_DATE, crc, len(data), len(data),
                           len(raw_name), 0) + raw_name + data
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0x0800, 0, 0, DOS_DATE, crc, len(data),
                               len(data), len(raw_name), 0, 0, 0, 0, 0, at) + raw_name
    start = len(out)
    out += central
    out += struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(files), len(files), len(central), start, 0)
    return bytes(out)


def _inflate(data):
    try:
        import deflate, io                     # MicroPython
        return deflate.DeflateIO(io.BytesIO(data), deflate.RAW, 15).read()     # 32 KiB window, as zip uses
    except ImportError:
        import zlib                            # CPython (tests on a PC)
        return zlib.decompress(data, -15)


MAX_ENTRY = 64 << 20                           # refuse "zip bombs" and damaged sizes


def read(data):
    """{name: bytes} of a ZIP file, from its central directory."""
    end = data.rfind(b"PK\x05\x06")
    if end < 0:
        raise ValueError("not a ZIP file")
    count, size, start = struct.unpack_from("<HII", data, end + 10)
    files = {}
    at = start
    for _ in range(count):
        if data[at:at + 4] != b"PK\x01\x02":
            raise ValueError("damaged ZIP directory")
        method, = struct.unpack_from("<H", data, at + 10)
        csize, usize, nlen, xlen, clen = struct.unpack_from("<IIHHH", data, at + 20)
        local, = struct.unpack_from("<I", data, at + 42)
        name = data[at + 46:at + 46 + nlen].decode()
        at += 46 + nlen + xlen + clen
        lnlen, lxlen = struct.unpack_from("<HH", data, local + 26)
        body = data[local + 30 + lnlen + lxlen:local + 30 + lnlen + lxlen + csize]
        if usize > MAX_ENTRY:
            raise ValueError("ZIP entry too big: " + name)
        if method == 0:
            files[name] = bytes(body)
        elif method == 8:
            files[name] = _inflate(body)
        else:
            raise ValueError("unsupported ZIP compression %d in %s" % (method, name))
    return files
