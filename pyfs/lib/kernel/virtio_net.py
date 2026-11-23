# virtio-net network card (legacy "transitional" interface, I/O ports).
#
# The card and the driver share two rings in RAM: we put empty buffers in
# the receive queue and full ones in the transmit queue, the card fills or
# sends them and hands them back through the "used" ring. Everything here is
# plain memory and port I/O; QEMU's `-nic user,model=virtio-net-pci` is the
# card this was written against.
import struct
import uctypes
from _kernel import inb, inw, inl, outb, outw, outl
from kernel import pci
from kernel.hw import dma_buffer

VENDOR, DEVICE = 0x1AF4, 0x1000
HDR = 10                     # struct virtio_net_hdr (no mergeable buffers)
BUF = 2048
RX, TX = 0, 1

# legacy register offsets
FEATURES, GUEST_FEATURES, QUEUE_PFN, QUEUE_SIZE, QUEUE_SEL, QUEUE_NOTIFY, STATUS, ISR, MAC = \
    0x00, 0x04, 0x08, 0x0C, 0x0E, 0x10, 0x12, 0x13, 0x14
F_MAC = 1 << 5


def _align(n, a=4096):
    return (n + a - 1) & ~(a - 1)


class Queue:
    def __init__(self, nic, index):
        self.nic, self.index = nic, index
        outw(nic.io + QUEUE_SEL, index)
        self.size = n = inw(nic.io + QUEUE_SIZE)
        if not n:
            raise OSError(19)
        self.avail_off = 16 * n
        self.used_off = _align(16 * n + 6 + 2 * n)
        total = self.used_off + _align(6 + 8 * n)
        self._raw, self.mem, self.addr = dma_buffer(total)
        self.bufs = []
        self._braw = []
        for i in range(n):
            raw, view, addr = dma_buffer(BUF, 16)
            self._braw.append(raw)
            self.bufs.append((view, addr))
            struct.pack_into("<QIHH", self.mem, 16 * i, addr, BUF, 0, 0)
        self.last_used = 0
        self.free = list(range(n))
        outl(nic.io + QUEUE_PFN, self.addr >> 12)

    def avail_idx(self):
        return struct.unpack_from("<H", self.mem, self.avail_off + 2)[0]

    def used_idx(self):
        return struct.unpack_from("<H", self.mem, self.used_off + 2)[0]

    def offer(self, desc, length, writable):
        """Put descriptor `desc` (length bytes) in the available ring."""
        struct.pack_into("<IHH", self.mem, 16 * desc + 8, length, 2 if writable else 0, 0)
        idx = self.avail_idx()
        struct.pack_into("<H", self.mem, self.avail_off + 4 + 2 * (idx % self.size), desc)
        struct.pack_into("<H", self.mem, self.avail_off + 2, (idx + 1) & 0xFFFF)

    def take(self):
        """Yield (desc, length) for every buffer the card has finished with."""
        while self.last_used != self.used_idx():
            off = self.used_off + 4 + 8 * (self.last_used % self.size)
            desc, length = struct.unpack_from("<II", self.mem, off)
            self.last_used = (self.last_used + 1) & 0xFFFF
            yield desc, length

    def notify(self):
        outw(self.nic.io + QUEUE_NOTIFY, self.index)


class VirtioNet:
    name = "virtio-net"

    def __init__(self, bus, dev, fn):
        self.where = (bus, dev, fn)
        bar0 = pci.read32(bus, dev, fn, 0x10)
        if not bar0 & 1:
            raise OSError(19)                       # modern-only device: no I/O BAR
        self.io = bar0 & ~3
        cmd = pci.read32(bus, dev, fn, 0x04)
        pci.write32(bus, dev, fn, 0x04, cmd | 0x5)  # I/O space + bus master
        self.irq_line = pci.read32(bus, dev, fn, 0x3C) & 0xFF
        io = self.io
        outb(io + STATUS, 0)                        # reset
        outb(io + STATUS, 1 | 2)                    # acknowledge, driver
        offered = inl(io + FEATURES)
        outl(io + GUEST_FEATURES, offered & F_MAC)
        self.mac = bytes(inb(io + MAC + i) for i in range(6)) if offered & F_MAC else b"\x52\x54\x00\x12\x34\x56"
        self.rx = Queue(self, RX)
        self.tx = Queue(self, TX)
        for d in range(self.rx.size):
            self.rx.offer(d, BUF, True)
        self.rx.free = []
        outb(io + STATUS, 1 | 2 | 4)                # driver ok
        self.rx.notify()
        self.sent = self.received = 0

    def send(self, frame):
        tx = self.tx
        for d, _ in tx.take():
            tx.free.append(d)
        if not tx.free:
            return False
        d = tx.free.pop()
        view = tx.bufs[d][0]
        n = len(frame)
        view[0:HDR] = bytes(HDR)
        view[HDR:HDR + n] = frame
        tx.offer(d, HDR + n, False)
        tx.notify()
        self.sent += 1
        return True

    def recv(self):
        """Every frame that has arrived since the last call."""
        rx = self.rx
        frames = []
        for d, length in rx.take():
            frames.append(bytes(rx.bufs[d][0][HDR:length]))
            rx.offer(d, BUF, True)
        if frames:
            rx.notify()
            self.received += len(frames)
        inb(self.io + ISR)                          # acknowledge the interrupt
        return frames


def probe():
    for bus, dev, fn, vendor, device, cls, sub in pci.scan():
        if vendor == VENDOR and device == DEVICE:
            return VirtioNet(bus, dev, fn)
    return None
