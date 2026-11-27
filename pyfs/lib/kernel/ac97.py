# AC'97 sound card (Intel ICH, QEMU's -device AC97).
#
# Two sets of I/O ports: the "mixer" (volumes, sample rate) and the "bus
# master" that copies samples from RAM to the card by itself. We give it a
# ring of 32 buffers; while it plays one, sound.py fills the ones it has
# already played. Samples are 16-bit stereo.
import struct
from _kernel import inb, inw, inl, outb, outw, outl
from kernel import pci, timer
from kernel.hw import dma_buffer

IDS = {(0x8086, 0x2415), (0x8086, 0x2425), (0x8086, 0x24C5), (0x8086, 0x24D5), (0x8086, 0x266E)}
BUFFERS = 32
BUF_BYTES = 8192                       # 2048 stereo frames each
# bus master registers of the PCM-out channel
BDBAR, CIV, LVI, SR, PICB, CR = 0x10, 0x14, 0x15, 0x16, 0x18, 0x1B
GLOB_CNT = 0x2C


class AC97:
    name = "AC97"
    BUFFERS = BUFFERS
    BUF_BYTES = BUF_BYTES

    def __init__(self, bus, dev, fn):
        pci.write32(bus, dev, fn, 0x04, pci.read32(bus, dev, fn, 0x04) | 0x5)   # I/O + bus master
        self.nam = pci.read32(bus, dev, fn, 0x10) & ~1          # mixer ports
        self.nabm = pci.read32(bus, dev, fn, 0x14) & ~1         # bus master ports
        outl(self.nabm + GLOB_CNT, 0x2)                          # out of cold reset
        timer_wait(20)
        outw(self.nam + 0x00, 0)                                 # reset the mixer
        timer_wait(20)
        self.volume(80)
        outw(self.nam + 0x18, 0x0808)                            # PCM out: 0 dB
        self.rate = 48000
        if inw(self.nam + 0x28) & 1:                             # variable rate supported
            outw(self.nam + 0x2A, inw(self.nam + 0x2A) | 1)
        # the ring of buffers and its descriptor list
        _, self.bdl, bdl_addr = dma_buffer(8 * BUFFERS, 8)
        self.bufs = []
        for i in range(BUFFERS):
            _, view, addr = dma_buffer(BUF_BYTES, 8)
            self.bufs.append(view)
            struct.pack_into("<IHH", self.bdl, 8 * i, addr, BUF_BYTES // 2, 0)
        self.bdl_addr = bdl_addr
        self.reset_channel()

    def reset_channel(self):
        outb(self.nabm + CR, 0x02)
        for _ in range(10000):
            if not inb(self.nabm + CR) & 0x02:
                break
        outw(self.nabm + SR, 0x1C)                               # clear status bits
        outl(self.nabm + BDBAR, self.bdl_addr)                   # a reset forgets the list

    def set_rate(self, rate):
        if inw(self.nam + 0x2A) & 1:
            outw(self.nam + 0x2C, rate)
            self.rate = inw(self.nam + 0x2C)
        return self.rate

    def volume(self, percent):
        """Master volume 0..100."""
        att = 0 if percent >= 100 else int((100 - max(0, percent)) * 31 / 100)
        outw(self.nam + 0x02, 0x8000 if percent <= 0 else (att << 8) | att)

    # -- the ring, used by sound.py --
    def current(self):
        return inb(self.nabm + CIV)

    def set_last(self, index):
        outb(self.nabm + LVI, index % BUFFERS)

    def start(self):
        outb(self.nabm + CR, 0x01)

    def stop(self):
        self.reset_channel()

    def running(self):
        return not inw(self.nabm + SR) & 0x01                    # bit 0: DMA halted


def timer_wait(ms):
    end = timer.ms() + ms
    while timer.ms() < end:
        pass


def probe():
    for bus, dev, fn, vendor, device, cls, sub in pci.scan():
        if (vendor, device) in IDS:
            return AC97(bus, dev, fn)
    return None
