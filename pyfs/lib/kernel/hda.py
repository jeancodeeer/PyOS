# Intel High Definition Audio ("HD Audio", "Azalia"): the sound of most PCs
# made since 2004. In QEMU: -device intel-hda -device hda-duplex
#
# HD Audio has two parts:
#   the controller  copies samples from RAM to the codec by itself (DMA)
#   the codec       a chip made of "widgets": converters (DAC: numbers ->
#                   sound), pins (the jacks: speaker, headphones), mixers...
#
# We talk to the codec with "verbs" (small commands) through two rings in
# RAM: the CORB (commands out) and the RIRB (responses in). Then we connect
# a DAC to an output pin, unmute both and start an output stream: a ring of
# 32 buffers the controller plays round and round. sound.py keeps the
# buffers ahead of the card full, exactly as with the AC'97 card.
import struct
from kernel import pci, timer
from kernel.hw import Regs, dma_buffer

CLASS = (0x04, 0x03)                    # PCI class: multimedia, HD audio
BUFFERS = 32
BUF_BYTES = 8192                         # 2048 stereo frames each
STREAM_TAG = 1

# controller registers
GCAP, GCTL, STATESTS = 0x00, 0x08, 0x0E
CORBLBASE, CORBUBASE, CORBWP, CORBRP, CORBCTL, CORBSIZE = 0x40, 0x44, 0x48, 0x4A, 0x4C, 0x4E
RIRBLBASE, RIRBUBASE, RIRBWP, RINTCNT, RIRBCTL, RIRBSTS, RIRBSIZE = 0x50, 0x54, 0x58, 0x5A, 0x5C, 0x5D, 0x5E
# stream descriptor registers (relative to the stream's base)
SD_CTL, SD_STS, SD_LPIB, SD_CBL, SD_LVI, SD_FMT, SD_BDPL, SD_BDPU = 0x00, 0x03, 0x04, 0x08, 0x0C, 0x12, 0x18, 0x1C

# codec verbs
GET_PARAM, GET_CONN_LIST, SET_POWER, SET_CONVERTER, SET_PIN_CTL, SET_EAPD, GET_CONFIG = \
    0xF00, 0xF02, 0x705, 0x706, 0x707, 0x70C, 0xF1C
SET_FORMAT, SET_AMP = 0x2, 0x3                         # the two "4-bit" verbs with a 16-bit payload
P_NODE_COUNT, P_FG_TYPE, P_WIDGET_CAPS, P_CONN_LEN, P_OUT_AMP = 0x04, 0x05, 0x09, 0x0E, 0x12
W_OUTPUT, W_PIN = 0, 4

# sample rates the format word can describe: rate -> (44.1 kHz base?, multiply, divide)
RATES = {48000: (0, 1, 1), 44100: (1, 1, 1), 96000: (0, 2, 1), 32000: (0, 2, 3), 24000: (0, 1, 2),
         22050: (1, 1, 2), 16000: (0, 1, 3), 11025: (1, 1, 4), 8000: (0, 1, 6)}


def wait(ms):
    end = timer.ms() + ms
    while timer.ms() < end:
        pass


def _format(rate):
    """The stream format word: 16-bit stereo at `rate`."""
    base44, mult, div = RATES[rate]
    return (base44 << 14) | ((mult - 1) << 11) | ((div - 1) << 8) | (1 << 4) | 1


class HDA:
    name = "HD Audio"
    BUFFERS = BUFFERS
    BUF_BYTES = BUF_BYTES

    def __init__(self, bus, dev, fn):
        pci.write32(bus, dev, fn, 0x04, pci.read32(bus, dev, fn, 0x04) | 0x6)    # memory + bus master
        bar = pci.read32(bus, dev, fn, 0x10)
        base = bar & ~0xF
        if bar & 0x4:                                                         # a 64-bit BAR
            base |= pci.read32(bus, dev, fn, 0x14) << 32
        self.r = Regs(base)
        self._reset()
        self._rings()
        self.codec = self._first_codec()
        if self.codec is None:
            raise OSError("HD Audio: no codec answered")
        self._find_path()
        self._stream_setup()
        self.rate = 48000
        self.last = BUFFERS - 1
        self.steps = 0x7F
        self.volume(80)

    # ---- the controller ----
    def _reset(self):
        r = self.r
        r.write32(GCTL, 0)                                   # into reset...
        for _ in range(1000):
            if not r.read32(GCTL) & 1:
                break
        wait(1)
        r.write32(GCTL, 1)                                   # ...and out again
        for _ in range(100000):
            if r.read32(GCTL) & 1:
                break
        wait(2)                                              # codecs need a moment to say hello

    def _rings(self):
        """The command ring (CORB, 256 x 4 bytes) and the response ring (RIRB, 256 x 8 bytes)."""
        r = self.r
        r.write8(CORBCTL, 0)
        r.write8(RIRBCTL, 0)
        _, self.corb, corb_addr = dma_buffer(1024, 128)
        _, self.rirb, rirb_addr = dma_buffer(2048, 128)
        r.write32(CORBLBASE, corb_addr & 0xFFFFFFFF)
        r.write32(CORBUBASE, corb_addr >> 32)
        r.write8(CORBSIZE, 0x2)                              # 256 entries
        r.write16(CORBRP, 0x8000)                            # reset the read pointer
        for _ in range(1000):
            if r.read16(CORBRP) & 0x8000:
                break
        r.write16(CORBRP, 0)
        r.write16(CORBWP, 0)
        r.write32(RIRBLBASE, rirb_addr & 0xFFFFFFFF)
        r.write32(RIRBUBASE, rirb_addr >> 32)
        r.write8(RIRBSIZE, 0x2)
        r.write16(RIRBWP, 0x8000)                            # reset the write pointer
        r.write16(RINTCNT, 0xFF)                            # answers before the ring pauses
        r.write8(CORBCTL, 0x2)                               # run both rings
        r.write8(RIRBCTL, 0x2)
        self.rirb_read = 0

    def verb(self, nid, verb, payload=0):
        """Send one command to the codec and return its 32-bit answer (None if it did not answer)."""
        if verb < 0x10:                                      # a 4-bit verb with a 16-bit payload
            command = (self.codec << 28) | (nid << 20) | (verb << 16) | (payload & 0xFFFF)
        else:
            command = (self.codec << 28) | (nid << 20) | (verb << 8) | (payload & 0xFF)
        return self._send(command)

    def _send(self, command):
        r = self.r
        wp = (r.read16(CORBWP) + 1) & 0xFF
        struct.pack_into("<I", self.corb, 4 * wp, command)
        r.write16(CORBWP, wp)
        end = timer.ms() + 50
        while timer.ms() < end:
            if (r.read16(RIRBWP) & 0xFF) != self.rirb_read:
                self.rirb_read = (self.rirb_read + 1) & 0xFF
                r.write8(RIRBSTS, 0x5)                       # "read": else the ring pauses after RINTCNT answers
                return struct.unpack_from("<I", self.rirb, 8 * self.rirb_read)[0]
        return None

    def _first_codec(self):
        present = self.r.read16(STATESTS)
        for address in range(15):
            if present & (1 << address):
                self.codec = address
                if self.verb(0, GET_PARAM, P_NODE_COUNT) is not None:
                    return address
        return None

    # ---- the codec: find a DAC and the jack it can reach ----
    def _nodes(self, nid):
        count = self.verb(nid, GET_PARAM, P_NODE_COUNT) or 0
        first, n = (count >> 16) & 0xFF, count & 0xFF
        return range(first, first + n)

    def _connections(self, nid):
        length = (self.verb(nid, GET_PARAM, P_CONN_LEN) or 0) & 0x7F
        out = []
        for k in range(0, min(length, 32), 4):               # four short entries per answer
            entries = self.verb(nid, GET_CONN_LIST, k) or 0
            for j in range(min(4, length - k)):
                out.append((entries >> (8 * j)) & 0xFF)
        return out

    def _find_path(self):
        self.afg = None
        dacs, pins = [], []
        for fg in self._nodes(0):
            if (self.verb(fg, GET_PARAM, P_FG_TYPE) or 0) & 0xFF == 1:        # an audio function group
                self.afg = fg
                for nid in self._nodes(fg):
                    caps = self.verb(nid, GET_PARAM, P_WIDGET_CAPS) or 0
                    kind = (caps >> 20) & 0xF
                    if kind == W_OUTPUT:
                        dacs.append(nid)
                    elif kind == W_PIN:
                        config = self.verb(nid, GET_CONFIG) or 0
                        device = (config >> 20) & 0xF                       # 0 line out, 1 speaker, 2 headphones
                        if config >> 30 != 1 and device in (0, 1, 2):        # 1 = nothing plugged there
                            pins.append(nid)
                break
        if self.afg is None or not dacs:
            raise OSError("HD Audio: the codec has no audio output")
        self.dac, self.pins = dacs[0], pins
        self.verb(self.afg, SET_POWER, 0)                    # D0: fully on
        self.verb(self.dac, SET_POWER, 0)
        for pin in pins:
            self.verb(pin, SET_POWER, 0)
            conns = self._connections(pin)
            if self.dac in conns:
                self.verb(pin, 0x701, conns.index(self.dac))  # select the DAC as the pin's input
            self.verb(pin, SET_PIN_CTL, 0xC0)                # output on, headphone amp on
            self.verb(pin, SET_EAPD, 0x2)                    # external amplifier on
            self.verb(pin, SET_AMP, 0xB000 | 0x7F)           # pin's output amp: unmuted, both sides
        amp = self.verb(self.dac, GET_PARAM, P_OUT_AMP) or self.verb(self.afg, GET_PARAM, P_OUT_AMP) or 0
        self.steps = ((amp >> 8) & 0x7F) or 0x7F

    # ---- the output stream ----
    def _stream_setup(self):
        gcap = self.r.read16(GCAP)
        inputs = (gcap >> 8) & 0xF
        if not (gcap >> 12) & 0xF:
            raise OSError("HD Audio: no output streams")
        self.sd = 0x80 + 0x20 * inputs                       # the first output stream
        _, self.bdl, self.bdl_addr = dma_buffer(16 * BUFFERS, 128)
        self.bufs = []
        for i in range(BUFFERS):
            _, view, addr = dma_buffer(BUF_BYTES, 128)
            self.bufs.append(view)
            struct.pack_into("<QII", self.bdl, 16 * i, addr, BUF_BYTES, 0)
        self.stop()

    def _sd8(self, off, value=None):
        if value is None:
            return self.r.read8(self.sd + off)
        self.r.write8(self.sd + off, value)

    def stop(self):
        r = self.r
        self._sd8(SD_CTL, 0)                                 # stop
        for _ in range(1000):
            if not self._sd8(SD_CTL) & 2:
                break
        self._sd8(SD_CTL, 1)                                 # stream reset
        for _ in range(1000):
            if self._sd8(SD_CTL) & 1:
                break
        self._sd8(SD_CTL, 0)
        for _ in range(1000):
            if not self._sd8(SD_CTL) & 1:
                break
        self._sd8(SD_STS, 0x1C)                              # clear status bits
        self._sd8(SD_CTL + 2, STREAM_TAG << 4)               # our stream number
        r.write32(self.sd + SD_BDPL, self.bdl_addr & 0xFFFFFFFF)
        r.write32(self.sd + SD_BDPU, self.bdl_addr >> 32)
        r.write32(self.sd + SD_CBL, BUFFERS * BUF_BYTES)
        r.write16(self.sd + SD_LVI, BUFFERS - 1)

    def set_rate(self, rate):
        """Choose the rate the card plays at; the nearest one it can do. Returns it."""
        if rate not in RATES:
            rate = min(RATES, key=lambda r: abs(r - rate))
        self.rate = rate
        return rate

    def start(self):
        fmt = _format(self.rate)
        self.r.write16(self.sd + SD_FMT, fmt)
        self.verb(self.dac, SET_FORMAT, fmt)
        self.verb(self.dac, SET_CONVERTER, STREAM_TAG << 4)  # the DAC listens to our stream
        self._sd8(SD_CTL, self._sd8(SD_CTL) | 2)             # run

    def volume(self, percent):
        """Volume 0..100 on the DAC's output amplifier."""
        if percent <= 0:
            self.verb(self.dac, SET_AMP, 0xB000 | 0x80)      # mute
            return
        gain = self.steps * min(100, percent) // 100
        self.verb(self.dac, SET_AMP, 0xB000 | gain)

    # ---- the ring, used by sound.py (the same calls as the AC'97 card) ----
    def current(self):
        """The buffer being played now."""
        return (self.r.read32(self.sd + SD_LPIB) // BUF_BYTES) % BUFFERS

    def set_last(self, index):
        """Play up to buffer `index`. HD Audio plays its ring round and round,
        so the buffer after it is cleared (silence) and running() stops the
        stream when it gets there."""
        self.last = index % BUFFERS
        nxt = self.bufs[(self.last + 1) % BUFFERS]
        nxt[:] = bytes(BUF_BYTES)

    def running(self):
        if not self._sd8(SD_CTL) & 2:
            return False
        if self.current() == (self.last + 1) % BUFFERS:      # all queued sound has been played
            self.stop()
            return False
        return True


def probe():
    for bus, dev, fn, vendor, device, cls, sub in pci.scan():
        if (cls, sub) == CLASS:
            return HDA(bus, dev, fn)
    return None
