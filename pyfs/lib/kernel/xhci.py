# xHCI: the USB 3 host controller every modern PC has (QEMU: -device qemu-xhci).
#
# Everything goes through "rings" of 16-byte TRBs (transfer request blocks)
# in RAM: we put commands on the command ring and transfers on one ring per
# endpoint, ring a doorbell, and the controller answers on the event ring.
# usb.py uses this to talk to keyboards, mice and USB sticks.
import struct
from kernel import pci, timer, log
from kernel.hw import Regs, dma_buffer

RING = 64                                   # TRBs per ring (the last one links back)
# TRB types
NORMAL, SETUP, DATA, STATUS, LINK = 1, 2, 3, 4, 6
ENABLE_SLOT, ADDRESS_DEVICE, CONFIGURE_EP, EVALUATE = 9, 11, 12, 13
TRANSFER_EVENT, COMMAND_DONE, PORT_CHANGE = 32, 33, 34
SPEEDS = {1: "full", 2: "low", 3: "high", 4: "super"}


class Ring:
    """A producer ring: we write TRBs, the controller consumes them."""

    def __init__(self):
        _, self.mem, self.addr = dma_buffer(16 * RING, 64)
        self.i = 0
        self.cycle = 1
        # the last TRB links back to the start and flips the cycle bit
        struct.pack_into("<QII", self.mem, 16 * (RING - 1), self.addr, 0, (LINK << 10) | 2)

    def push(self, param, status, control):
        """Add one TRB; returns its physical address."""
        at = self.addr + 16 * self.i
        struct.pack_into("<QII", self.mem, 16 * self.i, param, status, control | self.cycle)
        self.i += 1
        if self.i == RING - 1:                       # reached the link TRB: hand it over too
            c = struct.unpack_from("<I", self.mem, 16 * self.i + 12)[0]
            struct.pack_into("<I", self.mem, 16 * self.i + 12, (c & ~1) | self.cycle)
            self.i = 0
            self.cycle ^= 1
        return at


class Controller:
    def __init__(self, bus, dev, fn):
        pci.write32(bus, dev, fn, 0x04, pci.read32(bus, dev, fn, 0x04) | 0x6)
        bar = pci.read32(bus, dev, fn, 0x10)
        base = bar & ~0xF
        if bar & 0x4:
            base |= pci.read32(bus, dev, fn, 0x14) << 32
        cap = Regs(base)
        self.op = Regs(base + cap.read8(0))
        self.rt = Regs(base + (cap.read32(0x18) & ~0x1F))
        self.db = Regs(base + (cap.read32(0x14) & ~0x3))
        hcs1, hcs2, hcc1 = cap.read32(0x04), cap.read32(0x08), cap.read32(0x10)
        self.max_slots, self.max_ports = hcs1 & 0xFF, hcs1 >> 24
        self.csz = 64 if hcc1 & 0x4 else 32          # size of one context entry
        self._reset()
        # device context table, plus scratchpad pages if the controller wants them
        _, self.dcbaa, dcbaa_addr = dma_buffer(8 * (self.max_slots + 1), 64)
        pads = ((hcs2 >> 27) & 0x1F) | (((hcs2 >> 21) & 0x1F) << 5)
        if pads:
            _, arr, arr_addr = dma_buffer(8 * pads, 64)
            for i in range(pads):
                struct.pack_into("<Q", arr, 8 * i, dma_buffer(4096)[2])
            struct.pack_into("<Q", self.dcbaa, 0, arr_addr)
        self.op.write64(0x30, dcbaa_addr)
        self.op.write32(0x38, self.max_slots)
        # command ring
        self.commands = Ring()
        self.op.write64(0x18, self.commands.addr | 1)
        # event ring: one segment, described by a one-entry table
        _, self.events, ev_addr = dma_buffer(16 * RING, 64)
        _, erst, erst_addr = dma_buffer(16, 64)
        struct.pack_into("<QI", erst, 0, ev_addr, RING)
        self.ev_addr = ev_addr
        self.ev_i, self.ev_cycle = 0, 1
        ir = 0x20                                         # interrupter 0
        self.rt.write32(ir + 0x08, 1)
        self.rt.write64(ir + 0x18, ev_addr)
        self.rt.write64(ir + 0x10, erst_addr)
        self.rt.write32(ir + 0x00, 0x2)                   # enable (we poll, but keep it tidy)
        self.op.write32(0x00, self.op.read32(0x00) | 1)   # run
        self.busy = False
        self.waiting = {}                                 # TRB address -> event, for synchronous calls
        self.on_transfer = {}                             # (slot, endpoint) -> fn(event)

    def _reset(self):
        op = self.op
        op.write32(0x00, op.read32(0x00) & ~1)            # stop
        self._until(lambda: op.read32(0x04) & 1)          # halted
        op.write32(0x00, 0x2)                             # reset
        self._until(lambda: not op.read32(0x00) & 0x2 and not op.read32(0x04) & (1 << 11))

    def _until(self, cond, seconds=2):
        deadline = timer.ticks() + seconds * timer.HZ
        while not cond():
            if timer.ticks() > deadline:
                raise OSError(110, "xHCI does not answer")

    # ---- events ----
    def poll(self):
        """Handle every event the controller has posted."""
        if self.busy:                                 # the timer interrupted a poll: let it finish
            return 0
        self.busy = True
        try:
            return self._poll()
        finally:
            self.busy = False

    def _poll(self):
        handled = 0
        while True:
            param, status, control = struct.unpack_from("<QII", self.events, 16 * self.ev_i)
            if (control & 1) != self.ev_cycle:
                break
            kind = (control >> 10) & 0x3F
            ev = (kind, param, status, control)
            if kind == COMMAND_DONE:
                self.waiting[param] = ev
            elif kind == TRANSFER_EVENT:
                slot, ep = control >> 24, (control >> 16) & 0x1F
                fn = self.on_transfer.get((slot, ep))
                if fn is not None:
                    try:
                        fn(ev)
                    except Exception as e:
                        log.warn("usb: %r" % e)
                else:
                    self.waiting[param] = ev
            self.ev_i += 1
            if self.ev_i == RING:
                self.ev_i, self.ev_cycle = 0, self.ev_cycle ^ 1
            handled += 1
        if handled:                                   # tell it how far we have read
            self.rt.write64(0x20 + 0x18, (self.ev_addr + 16 * self.ev_i) | 0x8)
        return handled

    def wait(self, trb, seconds=2):
        """Wait for the event that answers the TRB at physical address `trb`."""
        deadline = timer.ticks() + seconds * timer.HZ
        while trb not in self.waiting:
            self.poll()
            if timer.ticks() > deadline:
                raise OSError(110, "USB request timed out")
        ev = self.waiting.pop(trb)
        code = (ev[2] >> 24) & 0xFF
        if code not in (1, 13):                     # success, short packet
            raise OSError(5, "USB error, completion code %d" % code)
        return ev

    def command(self, param=0, status=0, control=0):
        trb = self.commands.push(param, status, control)
        self.db.write32(0, 0)
        return self.wait(trb)

    def ring(self, slot, endpoint):
        self.db.write32(4 * slot, endpoint)

    # ---- ports ----
    def portsc(self, port):
        return self.op.read32(0x400 + 0x10 * (port - 1))

    def set_portsc(self, port, bits):
        # keep "port power", never write 1 to "enabled" (that would disable the port)
        value = (self.portsc(port) & 0x0E00C3E0 & ~0x2) | bits
        self.op.write32(0x400 + 0x10 * (port - 1), value)

    def reset_port(self, port):
        if not self.portsc(port) & 1:
            return None                                       # nothing plugged in
        self.set_portsc(port, 1 << 4)                         # port reset
        deadline = timer.ticks() + timer.HZ
        while not self.portsc(port) & (1 << 21) and timer.ticks() < deadline:
            pass
        self.set_portsc(port, 0x00FE0000)                     # clear the change bits
        sc = self.portsc(port)
        if not sc & 2:
            return None
        return (sc >> 10) & 0xF                               # speed


def controllers():
    found = []
    for bus, dev, fn, vendor, device, cls, sub in pci.scan():
        if cls == 0x0C and sub == 0x03 and (pci.read32(bus, dev, fn, 0x08) >> 8) & 0xFF == 0x30:
            try:
                c = Controller(bus, dev, fn)
                found.append(c)
            except OSError as e:
                log.warn("xhci: %s" % e)
    return found
