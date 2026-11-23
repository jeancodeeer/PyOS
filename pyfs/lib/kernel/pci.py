# PCI bus enumeration through configuration mechanism #1.
from _kernel import inl, outl

CLASSES = {
    0x00: "legacy", 0x01: "storage", 0x02: "network", 0x03: "display",
    0x04: "multimedia", 0x05: "memory", 0x06: "bridge", 0x07: "serial",
    0x08: "system", 0x09: "input", 0x0C: "serial bus", 0x0D: "wireless",
}


def read32(bus, dev, fn, offset):
    outl(0xCF8, 0x80000000 | (bus << 16) | (dev << 11) | (fn << 8) | (offset & 0xFC))
    return inl(0xCFC)


def write32(bus, dev, fn, offset, value):
    outl(0xCF8, 0x80000000 | (bus << 16) | (dev << 11) | (fn << 8) | (offset & 0xFC))
    outl(0xCFC, value)


def scan():
    """Yield (bus, dev, fn, vendor, device, class, subclass) for each function."""
    buses, seen = [0], set()
    while buses:
        bus = buses.pop()
        if bus in seen:
            continue
        seen.add(bus)
        for dev in range(32):
            if read32(bus, dev, 0, 0) & 0xFFFF == 0xFFFF:
                continue
            multi = (read32(bus, dev, 0, 0x0C) >> 16) & 0x80
            for fn in range(8 if multi else 1):
                ident = read32(bus, dev, fn, 0)
                if ident & 0xFFFF == 0xFFFF:
                    continue
                cls = read32(bus, dev, fn, 0x08) >> 16
                if cls == 0x0604:            # PCI-PCI bridge: follow it
                    buses.append((read32(bus, dev, fn, 0x18) >> 8) & 0xFF)
                yield bus, dev, fn, ident & 0xFFFF, ident >> 16, cls >> 8, cls & 0xFF
