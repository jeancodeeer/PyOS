# Realtek RTL8139 network card (QEMU: -nic user,model=rtl8139).
#
# The simplest PCI network card there is: received frames land one after
# another in a single ring buffer, each with a 4-byte header; frames to send
# go through four transmit slots used in turn.
import struct
from _kernel import inb, inw, inl, outb, outw, outl
from kernel import pci
from kernel.hw import dma_buffer

VENDOR, DEVICE = 0x10EC, 0x8139
RX_SIZE = 8192 + 16 + 1536            # 8 KiB ring, plus room for a frame that wraps
TSD, TSAD = 0x10, 0x20                # transmit status / address, 4 of each
RBSTART, CR, CAPR, IMR, ISR, TCR, RCR, CONFIG1 = 0x30, 0x37, 0x38, 0x3C, 0x3E, 0x40, 0x44, 0x52


class RTL8139:
    name = "rtl8139"

    def __init__(self, bus, dev, fn):
        pci.write32(bus, dev, fn, 0x04, pci.read32(bus, dev, fn, 0x04) | 0x5)   # I/O + bus master
        self.io = io = pci.read32(bus, dev, fn, 0x10) & ~3
        outb(io + CONFIG1, 0)                         # power on
        outb(io + CR, 0x10)                           # software reset
        while inb(io + CR) & 0x10:
            pass
        self.mac = bytes(inb(io + i) for i in range(6))
        _, self.rx, rx_addr = dma_buffer(RX_SIZE, 4096)
        outl(io + RBSTART, rx_addr)
        self.tx = []
        for i in range(4):
            _, view, addr = dma_buffer(1536, 16)
            self.tx.append((view, addr))
        outw(io + IMR, 0)                             # we poll: no interrupts
        outl(io + RCR, 0x8F)                          # accept broadcast, multicast, ours; wrap
        outl(io + TCR, 0x03000700)
        outb(io + CR, 0x0C)                           # receiver and transmitter on
        self.rx_pos = 0
        self.tx_next = 0
        self.sent = self.received = 0

    def send(self, frame):
        view, addr = self.tx[self.tx_next]
        status = inl(self.io + TSD + 4 * self.tx_next)
        if not status & 0x2000 and self.sent >= 4:     # OWN bit clear: slot still busy
            return False
        view[:len(frame)] = frame
        outl(self.io + TSAD + 4 * self.tx_next, addr)
        outl(self.io + TSD + 4 * self.tx_next, max(60, len(frame)))
        self.tx_next = (self.tx_next + 1) % 4
        self.sent += 1
        return True

    def recv(self):
        frames = []
        io = self.io
        while not inb(io + CR) & 0x01:                 # buffer not empty
            pos = self.rx_pos
            status, length = struct.unpack_from("<HH", self.rx, pos)
            if not status & 1 or length < 18 or length > 1536:
                break
            frames.append(bytes(self.rx[pos + 4:pos + length]))   # length includes the 4-byte CRC
            self.rx_pos = (pos + length + 4 + 3) & ~3
            if self.rx_pos >= 8192:
                self.rx_pos -= 8192
            outw(io + CAPR, (self.rx_pos - 16) & 0xFFFF)
        outw(io + ISR, 0xFFFF)
        self.received += len(frames)
        return frames


def probe():
    for bus, dev, fn, vendor, device, cls, sub in pci.scan():
        if vendor == VENDOR and device == DEVICE:
            return RTL8139(bus, dev, fn)
    return None
