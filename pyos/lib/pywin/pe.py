# The Windows .exe format (PE32+, 64-bit), read in Python.
#
#   img = pe.Image(open("hola.exe", "rb").read())
#   img.entry, img.image_base, img.size, img.sections, img.console
#   img.load(address)    copy it into memory at `address` and fix its pointers
#   img.imports(address) -> [(dll, function, slot address)]
#
# A PE file is: an old MS-DOS header, "PE\0\0", a header describing the
# program, a table of sections (.text = code, .data, .rdata, .bss...) and
# "data directories" pointing at the import table, relocations, TLS...
import struct
from pywin import mem

DIR_EXPORT, DIR_IMPORT, DIR_RESOURCE, DIR_RELOC, DIR_TLS = 0, 1, 2, 5, 9

# Safety: a .exe file can be made on purpose with wrong numbers in it
# (sizes, offsets) so that a careless loader writes outside the program's
# memory. Every number taken from the file is checked against these limits
# and against the size of the image before it is used.
MAX_IMAGE = 512 << 20            # 512 MiB: bigger than any real program
MAX_SECTIONS = 96                # the Windows limit
MAX_NAMES = 65536                # imports / exports per table


class BadExe(Exception):
    pass


def read_file(path):
    """A whole file, read in one go: the file system then moves whole runs of
    clusters at a time (much faster than an open-ended read() for big .exe)."""
    import os
    size = os.stat(path)[6]
    with open(path, "rb") as f:
        data = f.read(size)
    return data


class Section:
    def __init__(self, data, at):
        self.name = "".join(chr(c) for c in data[at:at + 8].rstrip(b"\0"))
        (self.vsize, self.rva, self.raw_size, self.raw_at) = struct.unpack_from("<IIII", data, at + 8)
        self.flags = struct.unpack_from("<I", data, at + 36)[0]

    def __repr__(self):
        return "<%s rva=%x size=%x>" % (self.name, self.rva, self.vsize)


class Image:
    def __init__(self, data):
        if data[:2] != b"MZ":
            raise BadExe("not an .exe file (no MZ header)")
        if len(data) < 0x40:
            raise BadExe("file too small")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if pe + 24 + 240 > len(data) or data[pe:pe + 4] != b"PE\0\0":
            raise BadExe("no PE header")
        machine, nsections = struct.unpack_from("<HH", data, pe + 4)
        opt_size, self.characteristics = struct.unpack_from("<HH", data, pe + 20)
        opt = pe + 24
        if machine != 0x8664 or struct.unpack_from("<H", data, opt)[0] != 0x20B:
            raise BadExe("only 64-bit (x64) programs are supported")
        self.entry = struct.unpack_from("<I", data, opt + 16)[0]
        self.image_base = struct.unpack_from("<Q", data, opt + 24)[0]
        self.size = struct.unpack_from("<I", data, opt + 56)[0]
        self.header_size = struct.unpack_from("<I", data, opt + 60)[0]
        self.subsystem = struct.unpack_from("<H", data, opt + 68)[0]
        self.console = self.subsystem == 3            # 2 = windows (GUI), 3 = console
        self.is_dll = bool(self.characteristics & 0x2000)
        count = struct.unpack_from("<I", data, opt + 108)[0]
        self.dirs = [struct.unpack_from("<II", data, opt + 112 + 8 * i) for i in range(min(count, 16))]
        first = opt + opt_size
        if not 0 < self.size <= MAX_IMAGE or nsections > MAX_SECTIONS or first + 40 * nsections > len(data):
            raise BadExe("damaged header (sizes out of range)")
        self.header_size = min(self.header_size, self.size, len(data))
        self.sections = [Section(data, first + 40 * i) for i in range(nsections)]
        self.data = data

    def directory(self, n):
        return self.dirs[n] if n < len(self.dirs) else (0, 0)

    def load(self, base):
        """Copy the headers and sections to `base` and apply relocations."""
        mem.zero(base, self.size)
        mem.write(base, self.data[:self.header_size])
        for s in self.sections:
            n = self._section_bytes(s)
            if n:
                mem.write(base + s.rva, self.data[s.raw_at:s.raw_at + n])
        delta = base - self.image_base
        if delta:
            self._relocate(base, delta)

    def _section_bytes(self, s):
        """How many bytes of section s to copy: never past the image nor past the file."""
        if s.rva >= self.size or s.raw_at >= len(self.data):
            return 0
        return max(0, min(s.raw_size, s.vsize or s.raw_size, self.size - s.rva, len(self.data) - s.raw_at))

    def inside(self, rva, n=1):
        """Is [rva, rva + n) inside the loaded image?"""
        return 0 <= rva and n >= 0 and rva + n <= self.size

    def _check(self, rva, n=1):
        if not self.inside(rva, n):
            raise BadExe("damaged file: a table points outside the program (%#x)" % rva)

    def _text(self, base, rva):
        """A zero-ended ASCII name inside the image."""
        self._check(rva)
        return mem.cstr_limited(base + rva, self.size - rva)

    def can_move(self):
        return self.directory(DIR_RELOC)[1] > 0

    def _relocate(self, base, delta):
        """Pointers inside the program assume it sits at image_base: shift them."""
        rva, size = self.directory(DIR_RELOC)
        if not size:
            raise BadExe("this program cannot be moved (no relocations)")
        self._check(rva, size)
        at, end = base + rva, base + rva + size
        while at + 8 <= end:
            page, block = mem.u32(at), mem.u32(at + 4)
            if block < 8 or at + block > end:
                break
            for k in range(8, block - 1, 2):
                entry = mem.u16(at + k)
                kind, offset = entry >> 12, page + (entry & 0xFFF)
                if kind == 10 and self.inside(offset, 8):        # 64-bit pointer
                    mem.put64(base + offset, (mem.u64(base + offset) + delta) & 0xFFFFFFFFFFFFFFFF)
                elif kind == 3 and self.inside(offset, 4):       # 32-bit pointer
                    mem.put32(base + offset, (mem.u32(base + offset) + delta) & 0xFFFFFFFF)
            at += block

    def imports(self, base):
        """Every function the program takes from a DLL: (dll, name, slot)."""
        out = []
        rva, size = self.directory(DIR_IMPORT)
        if not size:
            return out
        d = rva
        while self.inside(d, 20) and mem.u32(base + d + 12) and len(out) < MAX_NAMES:
            names, slots = mem.u32(base + d), mem.u32(base + d + 16)
            dll = self._text(base, mem.u32(base + d + 12)).lower()
            names = names or slots
            k = 0
            while self.inside(names + 8 * k, 8) and self.inside(slots + 8 * k, 8) and len(out) < MAX_NAMES:
                entry = mem.u64(base + names + 8 * k)
                if not entry:
                    break
                if entry >> 63:
                    name = "#%d" % (entry & 0xFFFF)             # imported by number
                else:
                    name = self._text(base, (entry & 0x7FFFFFFF) + 2)
                out.append((dll, name, base + slots + 8 * k))
                k += 1
            d += 20
        return out

    def exports(self, base):
        """What a DLL offers: {name or "#ordinal": address}. A function that
        lives in another DLL ("forwarded") is given as the text "DLL.name"."""
        out = {}
        rva, size = self.directory(DIR_EXPORT)
        if not size:
            return out
        self._check(rva, 40)
        d = base + rva
        first = mem.u32(d + 16)                              # number of the first ordinal
        nfuncs, nnames = min(mem.u32(d + 20), MAX_NAMES), min(mem.u32(d + 24), MAX_NAMES)
        funcs, names, ords = mem.u32(d + 28), mem.u32(d + 32), mem.u32(d + 36)
        self._check(funcs, 4 * nfuncs)
        self._check(names, 4 * nnames)
        self._check(ords, 2 * nnames)

        def target(k):
            if k >= nfuncs:
                return None
            f = mem.u32(base + funcs + 4 * k)
            if rva <= f < rva + size:                        # inside the export table: a forward
                return self._text(base, f)
            return base + f if self.inside(f) else None

        for k in range(nfuncs):
            if mem.u32(base + funcs + 4 * k):
                t = target(k)
                if t is not None:
                    out["#%d" % (first + k)] = t
        for i in range(nnames):
            name = self._text(base, mem.u32(base + names + 4 * i))
            t = target(mem.u16(base + ords + 2 * i))
            if t is not None:
                out[name] = t
        return out

    def _unpacked(self):
        """The image laid out as in memory, but in a Python buffer (nothing runs)."""
        buf = bytearray(self.size)
        for s in self.sections:
            n = self._section_bytes(s)                       # exactly n bytes: buf keeps its size
            if n:
                buf[s.rva:s.rva + n] = self.data[s.raw_at:s.raw_at + n]
        return buf

    def file_imports(self):
        """imports(), read straight from the file (for a look before running it)."""
        import uctypes
        buf = self._unpacked()
        return self.imports(uctypes.addressof(buf))

    def file_exports(self):
        """The names a DLL file offers, without loading it."""
        import uctypes
        buf = self._unpacked()
        return set(self.exports(uctypes.addressof(buf)))

    def resource(self, base, kind, name):
        """(address, size) of a resource (a menu, a dialog, strings...) or None.
        kind and name are numbers (RT_MENU = 4...) or text."""
        rva, size = self.directory(DIR_RESOURCE)
        if not size or not self.inside(rva, size):
            return None
        root = base + rva

        def ok(off, n):                                    # inside the resource directory?
            return 0 <= off and off + n <= size

        def entry(table_off, wanted):
            # a table: 16 bytes of header, then (name or id, offset) pairs
            if not ok(table_off, 16):
                return None
            table = root + table_off
            named, numbered = mem.u16(table + 12), mem.u16(table + 14)
            for k in range(named + numbered):
                if not ok(table_off + 16 + 8 * k, 8):
                    return None
                at = table + 16 + 8 * k
                key, off = mem.u32(at), mem.u32(at + 4)
                if key & 0x80000000:                       # a name, as a counted UTF-16 string
                    s_off = key & 0x7FFFFFFF
                    if not ok(s_off, 2):
                        continue
                    s = root + s_off
                    n = mem.u16(s)
                    if not ok(s_off + 2, 2 * n):
                        continue
                    raw = mem.read(s + 2, 2 * n)
                    key = "".join(chr(raw[2 * i] | raw[2 * i + 1] << 8) for i in range(n)).upper()
                if wanted is None or key == wanted:
                    return off
            return None

        if isinstance(name, str):
            name = name.upper()
        off = entry(0, kind)
        if off is None or not off & 0x80000000:
            return None
        off = entry(off & 0x7FFFFFFF, name)
        if off is None or not off & 0x80000000:
            return None
        off = entry(off & 0x7FFFFFFF, None)                # any language
        if off is None or off & 0x80000000 or not ok(off, 16):
            return None
        data = root + off
        data_rva, data_size = mem.u32(data), mem.u32(data + 4)
        if not self.inside(data_rva, data_size):
            return None
        return base + data_rva, data_size

    def tls(self, base):
        """(data start, data end, index address, callbacks address, zero fill) or None."""
        rva, size = self.directory(DIR_TLS)
        if not size or not self.inside(rva, 40):
            return None
        d = base + rva
        return mem.u64(d), mem.u64(d + 8), mem.u64(d + 16), mem.u64(d + 24), mem.u32(d + 32)
