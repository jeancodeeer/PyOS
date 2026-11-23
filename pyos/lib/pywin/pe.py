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


class BadExe(Exception):
    pass


class Section:
    def __init__(self, data, at):
        self.name = data[at:at + 8].rstrip(b"\0").decode()
        (self.vsize, self.rva, self.raw_size, self.raw_at) = struct.unpack_from("<IIII", data, at + 8)
        self.flags = struct.unpack_from("<I", data, at + 36)[0]

    def __repr__(self):
        return "<%s rva=%x size=%x>" % (self.name, self.rva, self.vsize)


class Image:
    def __init__(self, data):
        if data[:2] != b"MZ":
            raise BadExe("not an .exe file (no MZ header)")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
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
        self.sections = [Section(data, first + 40 * i) for i in range(nsections)]
        self.data = data

    def directory(self, n):
        return self.dirs[n] if n < len(self.dirs) else (0, 0)

    def load(self, base):
        """Copy the headers and sections to `base` and apply relocations."""
        mem.zero(base, self.size)
        mem.write(base, self.data[:self.header_size])
        for s in self.sections:
            n = min(s.raw_size, s.vsize or s.raw_size)
            if n and s.rva < self.size:
                mem.write(base + s.rva, self.data[s.raw_at:s.raw_at + n])
        delta = base - self.image_base
        if delta:
            self._relocate(base, delta)

    def can_move(self):
        return self.directory(DIR_RELOC)[1] > 0

    def _relocate(self, base, delta):
        """Pointers inside the program assume it sits at image_base: shift them."""
        rva, size = self.directory(DIR_RELOC)
        if not size:
            raise BadExe("this program cannot be moved (no relocations)")
        at, end = base + rva, base + rva + size
        while at < end:
            page, block = mem.u32(at), mem.u32(at + 4)
            if block < 8:
                break
            for k in range(8, block, 2):
                entry = mem.u16(at + k)
                kind, where = entry >> 12, base + page + (entry & 0xFFF)
                if kind == 10:                                   # 64-bit pointer
                    mem.put64(where, mem.u64(where) + delta)
                elif kind == 3:                                  # 32-bit pointer
                    mem.put32(where, mem.u32(where) + delta)
            at += block

    def imports(self, base):
        """Every function the program takes from a DLL: (dll, name, slot)."""
        out = []
        rva, size = self.directory(DIR_IMPORT)
        if not size:
            return out
        d = base + rva
        while mem.u32(d + 12):
            names, dll, slots = mem.u32(d), mem.cstr(base + mem.u32(d + 12)).lower(), mem.u32(d + 16)
            names = names or slots
            k = 0
            while True:
                entry = mem.u64(base + names + 8 * k)
                if not entry:
                    break
                if entry >> 63:
                    name = "#%d" % (entry & 0xFFFF)             # imported by number
                else:
                    name = mem.cstr(base + (entry & 0x7FFFFFFF) + 2)
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
        d = base + rva
        first = mem.u32(d + 16)                              # number of the first ordinal
        nfuncs, nnames = mem.u32(d + 20), mem.u32(d + 24)
        funcs, names, ords = mem.u32(d + 28), mem.u32(d + 32), mem.u32(d + 36)

        def target(k):
            f = mem.u32(base + funcs + 4 * k)
            if rva <= f < rva + size:                        # inside the export table: a forward
                return mem.cstr(base + f)
            return base + f

        for k in range(nfuncs):
            if mem.u32(base + funcs + 4 * k):
                out["#%d" % (first + k)] = target(k)
        for i in range(nnames):
            name = mem.cstr(base + mem.u32(base + names + 4 * i))
            out[name] = target(mem.u16(base + ords + 2 * i))
        return out

    def _unpacked(self):
        """The image laid out as in memory, but in a Python buffer (nothing runs)."""
        buf = bytearray(self.size)
        for s in self.sections:
            n = min(s.raw_size, s.vsize or s.raw_size, max(0, self.size - s.rva))
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
        if not size:
            return None
        root = base + rva

        def entry(table, wanted):
            # a table: 16 bytes of header, then (name or id, offset) pairs
            named, numbered = mem.u16(table + 12), mem.u16(table + 14)
            for k in range(named + numbered):
                at = table + 16 + 8 * k
                key, off = mem.u32(at), mem.u32(at + 4)
                if key & 0x80000000:                       # a name, as a counted UTF-16 string
                    s = root + (key & 0x7FFFFFFF)
                    n = mem.u16(s)
                    raw = mem.read(s + 2, 2 * n)
                    key = "".join(chr(raw[2 * i] | raw[2 * i + 1] << 8) for i in range(n)).upper()
                if wanted is None or key == wanted:
                    return off
            return None

        if isinstance(name, str):
            name = name.upper()
        off = entry(root, kind)
        if off is None or not off & 0x80000000:
            return None
        off = entry(root + (off & 0x7FFFFFFF), name)
        if off is None or not off & 0x80000000:
            return None
        off = entry(root + (off & 0x7FFFFFFF), None)       # any language
        if off is None:
            return None
        data = root + off
        return base + mem.u32(data), mem.u32(data + 4)

    def tls(self, base):
        """(data start, data end, index address, callbacks address, zero fill) or None."""
        rva, size = self.directory(DIR_TLS)
        if not size:
            return None
        d = base + rva
        return mem.u64(d), mem.u64(d + 8), mem.u64(d + 16), mem.u64(d + 24), mem.u32(d + 32)
