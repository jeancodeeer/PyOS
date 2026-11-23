# Intel 8254x (e1000) network card, through its memory-mapped registers.
#
# QEMU: -nic user,model=e1000. Also VirtualBox, VMware and many older PCs.
# Two descriptor rings in RAM, like virtio: receive descriptors point at
# empty buffers, transmit descriptors at frames to send; head/tail
# registers say who owns which slot.
import struct
from kernel import pci
from kernel.hw import Regs, dma_buffer

IDS = {(0x8086, 0x100E), (0x8086, 0x100F), (0x8086, 0x10D3), (0x8086, 0x153A), (0x8086, 0x10EA)}
CTRL, STATUS, EERD, ICR, IMS, IMC = 0x0000, 0x0008, 0x0014, 0x00C0, 0x00D0, 0x00D8
RCTL, TCTL, TIPG = 0x0100, 0x0400, 0x0410
RDBAL, RDBAH, RDLEN, RDH, RDT = 0x2800, 0x2804, 0x2808, 0x2810, 0x2818
TDBAL, TDBAH, TDLEN, TDH, TDT = 0x3800, 0x3804, 0x3808, 0x3810, 0x3818
RAL, RAH, MTA = 0x5400, 0x5404, 0x5200
N, BUF = 64, 2048


class E1000:
    name = "e1000"

    def __init__(self, bus, dev, fn):
        bar0 = pci.read32(bus, dev, fn, 0x10)
        base = bar0 & ~0xF
        if bar0 & 0x4:                                   # 64-bit BAR
            base |= pci.read32(bus, dev, fn, 0x14) << 32
        pci.write32(bus, dev, fn, 0x04, pci.read32(bus, dev, fn, 0x04) | 0x6)  # memory + bus master
        self.r = r = Regs(base)
        self.irq_line = pci.read32(bus, dev, fn, 0x3C) & 0xFF
        r.write32(CTRL, r.read32(CTRL) | (1 << 26))      # reset
        for _ in range(100000):
            if not r.read32(CTRL) & (1 << 26):
                break
        r.write32(IMC, 0xFFFFFFFF)
        r.write32(CTRL, r.read32(CTRL) | (1 << 6))       # set link up
        self.mac = self._read_mac()
        for i in range(128):
            r.write32(MTA + 4 * i, 0)
        self._rx_raw, self.rxd, rx_addr = dma_buffer(16 * N, 128)
        self._tx_raw, self.txd, tx_addr = dma_buffer(16 * N, 128)
        self.rxb, self.txb, self._keep = [], [], []
        for i in range(N):
            raw, view, addr = dma_buffer(BUF, 16)
            self._keep.append(raw)
            self.rxb.append(view)
            struct.pack_into("<QHHBBH", self.rxd, 16 * i, addr, 0, 0, 0, 0, 0)
            raw, view, addr = dma_buffer(BUF, 16)
            self._keep.append(raw)
            self.txb.append((view, addr))
            struct.pack_into("<QHBBBBH", self.txd, 16 * i, addr, 0, 0, 0, 1, 0, 0)   # status DD: free
        r.write32(RDBAL, rx_addr & 0xFFFFFFFF)
        r.write32(RDBAH, rx_addr >> 32)
        r.write32(RDLEN, 16 * N)
        r.write32(RDH, 0)
        r.write32(RDT, N - 1)
        # enable, accept broadcast, strip CRC, 2 KiB buffers
        r.write32(RCTL, (1 << 1) | (1 << 15) | (1 << 26))
        r.write32(TDBAL, tx_addr & 0xFFFFFFFF)
        r.write32(TDBAH, tx_addr >> 32)
        r.write32(TDLEN, 16 * N)
        r.write32(TDH, 0)
        r.write32(TDT, 0)
        r.write32(TCTL, (1 << 1) | (1 << 3) | (15 << 4) | (64 << 12))
        r.write32(TIPG, 10 | (10 << 10) | (10 << 20))
        self.rx_next, self.tx_next = 0, 0
        self.sent = self.received = 0

    def _read_mac(self):
        r = self.r
        low, high = r.read32(RAL), r.read32(RAH)
        if high & (1 << 31):
            return low.to_bytes(4, "little") + (high & 0xFFFF).to_bytes(2, "little")
        words = []
        for i in range(3):                               # from the EEPROM
            r.write32(EERD, 1 | (i << 8))
            for _ in range(100000):
                v = r.read32(EERD)
                if v & 0x10:
                    break
            words.append(v >> 16)
        mac = b"".join(w.to_bytes(2, "little") for w in words)
        r.write32(RAL, int.from_bytes(mac[:4], "little"))
        r.write32(RAH, int.from_bytes(mac[4:], "little") | (1 << 31))
        return mac

    def send(self, frame):
        i = self.tx_next
        if not self.txd[16 * i + 12] & 1:                # descriptor still in flight
            return False
        view, addr = self.txb[i]
        view[:len(frame)] = frame
        # length, cso, cmd = EOP | IFCS | RS, status 0
        struct.pack_into("<QHBBBBH", self.txd, 16 * i, addr, len(frame), 0, 0x0B, 0, 0, 0)
        self.tx_next = (i + 1) % N
        self.r.write32(TDT, self.tx_next)
        self.sent += 1
        return True

    def recv(self):
        frames = []
        while True:
            i = self.rx_next
            status = self.rxd[16 * i + 12]
            if not status & 1:                           # descriptor done?
                break
            length = struct.unpack_from("<H", self.rxd, 16 * i + 8)[0]
            frames.append(bytes(self.rxb[i][:length]))
            self.rxd[16 * i + 12] = 0
            self.r.write32(RDT, i)
            self.rx_next = (i + 1) % N
        self.r.read32(ICR)
        self.received += len(frames)
        return frames


def probe():
    for bus, dev, fn, vendor, device, cls, sub in pci.scan():
        if (vendor, device) in IDS:
            return E1000(bus, dev, fn)
    return None
