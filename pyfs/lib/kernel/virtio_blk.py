# virtio-blk: the disk of virtual machines (QEMU -drive if=virtio, KVM,
# cloud servers). Legacy "transitional" interface, with I/O ports, like
# virtio_net.py.
#
# One request is a chain of three pieces of memory the disk reads or fills:
#   header   what to do (read 0 / write 1 / flush 4) and the first sector
#   data     the sectors (up to 64 KiB here)
#   status   one byte the disk writes back: 0 = done
# We put the chain in the "available" ring, tell the disk, and wait until
# it shows up in the "used" ring.
#
#   from kernel import virtio_blk
#   d = virtio_blk.disks()[0]       # a block device, like the IDE and NVMe ones
#   os.mount(os.VfsFat(d), "/vd")
import struct
from _kernel import inb, inw, inl, outb, outw, outl
from kernel import pci, timer
from kernel.hw import dma_buffer

VENDOR, DEVICE = 0x1AF4, 0x1001
SECTOR = 512
MAX_SECTORS = 128                          # 64 KiB per request
T_IN, T_OUT, T_FLUSH = 0, 1, 4
F_RO = 1 << 5                              # the disk is read-only
# legacy register offsets (as in virtio_net.py); the disk's own settings start at 0x14
FEATURES, GUEST_FEATURES, QUEUE_PFN, QUEUE_SIZE, QUEUE_SEL, QUEUE_NOTIFY, STATUS, ISR, CONFIG = \
    0x00, 0x04, 0x08, 0x0C, 0x0E, 0x10, 0x12, 0x13, 0x14
NEXT, WRITE = 1, 2                         # descriptor flags: chained, the device writes here


def _align(n, a=4096):
    return (n + a - 1) & ~(a - 1)


class VirtioBlk:
    model = "virtio disk"

    def __init__(self, bus, dev, fn):
        bar0 = pci.read32(bus, dev, fn, 0x10)
        if not bar0 & 1:
            raise OSError(19, "virtio-blk without I/O ports (modern only)")
        self.io = io = bar0 & ~3
        pci.write32(bus, dev, fn, 0x04, pci.read32(bus, dev, fn, 0x04) | 0x5)    # I/O + bus master
        outb(io + STATUS, 0)                                 # reset
        outb(io + STATUS, 1 | 2)                             # acknowledge, driver
        offered = inl(io + FEATURES)
        outl(io + GUEST_FEATURES, offered & F_RO)
        self.readonly = bool(offered & F_RO)
        self.sectors = inl(io + CONFIG) | inl(io + CONFIG + 4) << 32
        # the queue: descriptors, then the available ring, then (page aligned) the used ring
        outw(io + QUEUE_SEL, 0)
        self.size = n = inw(io + QUEUE_SIZE)
        if n < 3:
            raise OSError(19, "virtio-blk queue too small")
        self.avail_off = 16 * n
        self.used_off = _align(16 * n + 6 + 2 * n)
        total = self.used_off + _align(6 + 8 * n)
        _, self.ring, ring_addr = dma_buffer(total)
        _, self.header, self.header_addr = dma_buffer(16, 16)
        _, self.data, self.data_addr = dma_buffer(MAX_SECTORS * SECTOR)
        _, self.status, self.status_addr = dma_buffer(16, 16)
        self.last_used = 0
        outl(io + QUEUE_PFN, ring_addr >> 12)
        outb(io + STATUS, 1 | 2 | 4)                         # driver ok

    def _request(self, kind, sector, count):
        """Run one request (the data is in self.data) and wait for it."""
        struct.pack_into("<IIQ", self.header, 0, kind, 0, sector)
        self.status[0] = 0xFF
        nbytes = count * SECTOR
        ring = self.ring
        # descriptor 0: the header -> 1: the data -> 2: the status byte
        struct.pack_into("<QIHH", ring, 0, self.header_addr, 16, NEXT, 1)
        if nbytes:
            struct.pack_into("<QIHH", ring, 16, self.data_addr, nbytes, NEXT | (WRITE if kind == T_IN else 0), 2)
            struct.pack_into("<QIHH", ring, 32, self.status_addr, 1, WRITE, 0)
        else:                                                # a flush has no data
            struct.pack_into("<QIHH", ring, 0, self.header_addr, 16, NEXT, 2)
            struct.pack_into("<QIHH", ring, 32, self.status_addr, 1, WRITE, 0)
        idx = struct.unpack_from("<H", ring, self.avail_off + 2)[0]
        struct.pack_into("<H", ring, self.avail_off + 4 + 2 * (idx % self.size), 0)
        struct.pack_into("<H", ring, self.avail_off + 2, (idx + 1) & 0xFFFF)
        outw(self.io + QUEUE_NOTIFY, 0)
        deadline = timer.ms() + 10000
        spins = 0
        while struct.unpack_from("<H", ring, self.used_off + 2)[0] == self.last_used:
            spins += 1
            if spins > 50:
                if timer.ms() > deadline:
                    raise OSError(5, "virtio-blk: the disk did not answer")
                import _kernel
                _kernel.wait()                               # let the interrupt (or the next tick) come
        self.last_used = (self.last_used + 1) & 0xFFFF
        inb(self.io + ISR)                                   # acknowledge the interrupt
        if self.status[0] != 0:
            raise OSError(5, "virtio-blk: error %d" % self.status[0])

    # -- block device protocol (512-byte sectors, like the other disks) --
    def readblocks(self, block, buf, offset=0):
        view = memoryview(buf)
        n = len(buf) // SECTOR
        done = 0
        while done < n:
            k = min(MAX_SECTORS, n - done)
            self._request(T_IN, block + done, k)
            view[done * SECTOR:(done + k) * SECTOR] = self.data[:k * SECTOR]
            done += k

    def writeblocks(self, block, buf, offset=0):
        if self.readonly:
            raise OSError(30, "read-only disk")              # EROFS
        view = memoryview(buf)
        n = len(buf) // SECTOR
        done = 0
        while done < n:
            k = min(MAX_SECTORS, n - done)
            self.data[:k * SECTOR] = view[done * SECTOR:(done + k) * SECTOR]
            self._request(T_OUT, block + done, k)
            done += k

    def ioctl(self, op, arg):
        if op == 3:                                          # sync
            try:
                self._request(T_FLUSH, 0, 0)
            except OSError:
                pass
        elif op == 4:
            return self.sectors
        elif op == 5:
            return SECTOR
        return 0

    def __repr__(self):
        return "<virtio-blk %d MiB%s>" % (self.sectors >> 11, ", read-only" if self.readonly else "")


_found = None


def disks():
    """Every virtio disk (found once, then remembered)."""
    global _found
    if _found is None:
        _found = []
        for bus, dev, fn, vendor, device, cls, sub in pci.scan():
            if vendor == VENDOR and device == DEVICE:
                try:
                    _found.append(VirtioBlk(bus, dev, fn))
                except OSError:
                    pass
    return _found
