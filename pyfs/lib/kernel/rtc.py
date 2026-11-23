# CMOS real-time clock.
from _kernel import inb, outb


def _reg(n):
    outb(0x70, n)
    return inb(0x71)


def now():
    """(year, month, day, hour, minute, second) from the hardware clock."""
    while _reg(0x0A) & 0x80:                 # update in progress
        pass
    raw = [_reg(r) for r in (0x09, 0x08, 0x07, 0x04, 0x02, 0x00)]
    status_b = _reg(0x0B)
    if not status_b & 0x04:                  # BCD
        pm = raw[3] & 0x80
        raw[3] &= 0x7F
        raw = [(v >> 4) * 10 + (v & 0x0F) for v in raw]
        raw[3] |= pm
    if not status_b & 0x02 and raw[3] & 0x80:    # 12-hour clock, PM
        raw[3] = (raw[3] & 0x7F) % 12 + 12
    raw[0] += 2000
    return tuple(raw)
