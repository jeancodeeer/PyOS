# Raw hardware access helpers.
from _kernel import inb, inw, inl, outb, outw, outl
import uctypes


def mem(addr, size):
    """A live bytearray view of `size` bytes of memory at `addr`."""
    return uctypes.bytearray_at(addr, size)


def peek(addr, width=8):
    """Read a little-endian integer of `width` bytes at `addr`."""
    return int.from_bytes(uctypes.bytearray_at(addr, width), "little")


def poke(addr, value, width=8):
    uctypes.bytearray_at(addr, width)[:] = value.to_bytes(width, "little")


def peek8(a):
    return uctypes.bytearray_at(a, 1)[0]


def peek16(a):
    return peek(a, 2)


def peek32(a):
    return peek(a, 4)


def peek64(a):
    return peek(a, 8)


def poke8(a, v):
    uctypes.bytearray_at(a, 1)[0] = v


def poke16(a, v):
    poke(a, v, 2)


def poke32(a, v):
    poke(a, v, 4)


def poke64(a, v):
    poke(a, v, 8)


def hexdump(addr, size=128):
    data = uctypes.bytearray_at(addr, size)
    for off in range(0, size, 16):
        row = data[off:off + 16]
        hexs = " ".join("%02x" % b for b in row)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        print("%012x  %-47s  %s" % (addr + off, hexs, text))


# ---- memory-mapped device registers ----
# Device registers (APIC, HPET, PCI BARs) must be read with one load of the
# right width; the byte-at-a-time helpers above would read garbage.
_R32 = {"v": uctypes.UINT32 | 0}
_R64 = {"v": uctypes.UINT64 | 0}
_R16 = {"v": uctypes.UINT16 | 0}


def mmio32(addr, value=None):
    r = uctypes.struct(addr, _R32)
    if value is None:
        return r.v
    r.v = value & 0xFFFFFFFF


def mmio64(addr, value=None):
    r = uctypes.struct(addr, _R64)
    if value is None:
        return r.v
    r.v = value


def mmio16(addr, value=None):
    r = uctypes.struct(addr, _R16)
    if value is None:
        return r.v
    r.v = value & 0xFFFF


class Regs:
    """Registers of one device at a fixed base: r.read32(off), r.write32(off, v)."""

    def __init__(self, base):
        self.base = base

    def read32(self, off):
        return mmio32(self.base + off)

    def write32(self, off, v):
        mmio32(self.base + off, v)

    def read64(self, off):
        return mmio64(self.base + off)

    def write64(self, off, v):
        mmio64(self.base + off, v)

    def read16(self, off):
        return mmio16(self.base + off)

    def write16(self, off, v):
        mmio16(self.base + off, v)

    def read8(self, off):
        return uctypes.bytearray_at(self.base + off, 1)[0]

    def write8(self, off, v):
        uctypes.bytearray_at(self.base + off, 1)[0] = v


def addr_of(buf):
    """Physical (= virtual, identity-mapped) address of a bytearray."""
    return uctypes.addressof(buf)


_dma_pool = []        # [address, bytes left] of a run of physical frames


def dma_buffer(size, align=4096):
    """Memory a device can read and write: (None, view, physical address).
    It comes from free physical frames, outside the Python heap, so drivers
    do not eat into the memory programs use. Never freed: drivers keep
    their rings for as long as the machine runs."""
    from kernel import mm
    if align > 4096:
        raise ValueError("alignment above one page")
    for chunk in _dma_pool:
        start = (chunk[0] + align - 1) & ~(align - 1)
        if start + size <= chunk[0] + chunk[1]:
            chunk[1] -= start + size - chunk[0]
            chunk[0] = start + size
            break
    else:
        pages = max(16, (size + 4095) // 4096)
        base = mm.alloc_contiguous(pages)
        uctypes.bytearray_at(base, pages * 4096)[:] = bytes(pages * 4096)
        _dma_pool.append([base + size, pages * 4096 - size])
        start = base
    return None, uctypes.bytearray_at(start, size), start
