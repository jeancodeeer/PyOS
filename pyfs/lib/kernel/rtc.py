# CMOS real-time clock.
from _kernel import inb, outb


def _reg(n):
    outb(0x70, n)
    return inb(0x71)


def now():
    """(year, month, day, hour, minute, second) from the hardware clock."""
    from kernel.arch import ARM, info
    if ARM:                                  # the firmware told the time at boot
        from kernel import timer
        return _civil(info("epoch") + timer.ms() // 1000 + _offset)
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


_offset = 0


def _civil(t):
    """(year, month, day, hour, minute, second) for `t` seconds since 1970."""
    days, rest = divmod(t, 86400)
    z = days + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return (yoe + era * 400 + (m <= 2), m, d, rest // 3600, rest // 60 % 60, rest % 60)


def set(t):
    """Write (year, month, day, hour, minute, second) to the hardware clock (24-hour, as it is stored)."""
    from kernel.arch import ARM
    if ARM:                                  # no clock chip to write: remember the difference
        global _offset
        import time
        _offset += time.mktime(tuple(t) + (0, 0)) + 946684800 - (now_seconds())
        return
    status_b = _reg(0x0B)
    values = [t[0] % 100, t[1], t[2], t[3], t[4], t[5]]
    if not status_b & 0x04:                  # the chip counts in BCD
        values = [(v // 10) << 4 | (v % 10) for v in values]
    outb(0x70, 0x0B)
    outb(0x71, status_b | 0x80 | 0x02)       # stop updates while writing; 24-hour mode
    for reg, v in zip((0x09, 0x08, 0x07, 0x04, 0x02, 0x00), values):
        outb(0x70, reg)
        outb(0x71, v)
    outb(0x70, 0x0B)
    outb(0x71, (status_b | 0x02) & ~0x80)


def now_seconds():
    """Seconds since 1970 now (ARM64)."""
    from kernel.arch import info
    from kernel import timer
    return info("epoch") + timer.ms() // 1000 + _offset
