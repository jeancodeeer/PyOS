# Local APIC, I/O APIC and HPET, through their memory-mapped registers.
#
# The legacy 8259 PIC (pic.py) still delivers the interrupts at boot; this
# module lets you read and program the modern controllers from Python:
# who is CPU 0, how the I/O APIC routes each line, and a 64-bit timer that
# counts in femtoseconds.
import _kernel
from kernel import acpi
from kernel.hw import mmio32 as _m32, mmio64 as _m64


def peek32(a):
    return _m32(a)


def poke32(a, v):
    _m32(a, v)


def peek64(a):
    return _m64(a)


def poke64(a, v):
    _m64(a, v)

IA32_APIC_BASE = 0x1B


def lapic_base():
    return _kernel.rdmsr(IA32_APIC_BASE) & 0xFFFFF000


def lapic_read(reg):
    return peek32(lapic_base() + reg)


def lapic_write(reg, value):
    poke32(lapic_base() + reg, value)


def lapic_id():
    return lapic_read(0x20) >> 24


def lapic_version():
    return lapic_read(0x30) & 0xFF


def lapic_enabled():
    return bool(_kernel.rdmsr(IA32_APIC_BASE) & (1 << 11))


def eoi():
    lapic_write(0xB0, 0)


def send_ipi(apic_id, low):
    """Interrupt-command register: send an inter-processor interrupt."""
    lapic_write(0x310, apic_id << 24)
    lapic_write(0x300, low)
    for _ in range(100000):
        if not lapic_read(0x300) & (1 << 12):   # delivery pending
            return True
    return False


# ---- I/O APIC ----

class IOAPIC:
    def __init__(self, ident, addr, gsi_base):
        self.id, self.addr, self.gsi_base = ident, addr, gsi_base

    def read(self, reg):
        poke32(self.addr, reg)
        return peek32(self.addr + 0x10)

    def write(self, reg, value):
        poke32(self.addr, reg)
        poke32(self.addr + 0x10, value)

    def lines(self):
        return ((self.read(1) >> 16) & 0xFF) + 1

    def route(self, line):
        low, high = self.read(0x10 + 2 * line), self.read(0x11 + 2 * line)
        return {"vector": low & 0xFF, "masked": bool(low & 0x10000), "level": bool(low & 0x8000),
                "active_low": bool(low & 0x2000), "dest": high >> 24}

    def set_route(self, line, vector, dest=0, masked=False, level=False, active_low=False):
        low = vector | (0x10000 if masked else 0) | (0x8000 if level else 0) | (0x2000 if active_low else 0)
        self.write(0x11 + 2 * line, dest << 24)
        self.write(0x10 + 2 * line, low)


def ioapics():
    if not acpi.tables:
        acpi.init()
    return [IOAPIC(*t) for t in acpi.ioapics]


# ---- HPET ----

class HPET:
    def __init__(self, addr):
        self.addr = addr
        caps = peek64(addr)
        self.period_fs = caps >> 32               # femtoseconds per tick
        self.timers = ((caps >> 8) & 0x1F) + 1
        self.vendor = (caps >> 16) & 0xFFFF
        poke64(addr + 0x10, peek64(addr + 0x10) | 1)   # main counter on

    def counter(self):
        return peek64(self.addr + 0xF0)

    def nanos(self):
        return self.counter() * self.period_fs // 1000000

    def hz(self):
        return 10 ** 15 // self.period_fs if self.period_fs else 0


hpet = None


def init_hpet():
    global hpet
    if not acpi.tables:
        acpi.init()
    t = acpi.tables.get("HPET")
    if t:
        from kernel.hw import peek64 as table64
        hpet = HPET(table64(t + 44))     # generic address structure: address at +4
    return hpet


def summary():
    lines = ["local APIC %#x: id %d, version %#x, %s" % (
        lapic_base(), lapic_id(), lapic_version(), "enabled" if lapic_enabled() else "disabled")]
    for io in ioapics():
        lines.append("I/O APIC %d at %#x: %d lines from GSI %d" % (io.id, io.addr, io.lines(), io.gsi_base))
    h = hpet or init_hpet()
    if h:
        lines.append("HPET at %#x: %d timers, %d Hz, counter %d" % (h.addr, h.timers, h.hz(), h.counter()))
    return "\n".join(lines)
