# The `time` module, implemented on the kernel's timer and clock drivers.
import _kernel
from kernel import timer, rtc

_boot_epoch = None


def ticks_ms():
    return timer.ms()


def ticks_us():
    if timer.tsc_per_ms:
        return _kernel.rdtsc() * 1000 // timer.tsc_per_ms
    return timer.ms() * 1000


def ticks_diff(a, b):
    return a - b


def ticks_add(a, b):
    return a + b


def sleep_ms(ms):
    end = timer.ticks() + max(1, ms * timer.HZ // 1000)
    while timer.ticks() < end:
        _kernel.wait()


def sleep(seconds):
    sleep_ms(int(seconds * 1000))


def _days(y, m, d):
    # days since 1970-01-01 (civil calendar)
    y -= m <= 2
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    return era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + doy - 719468


def mktime(t):
    return _days(t[0], t[1], t[2]) * 86400 + t[3] * 3600 + t[4] * 60 + t[5]


def time():
    global _boot_epoch
    if _boot_epoch is None:
        _boot_epoch = mktime(rtc.now()) - timer.ms() // 1000
    return _boot_epoch + timer.ms() // 1000


def gmtime(secs=None):
    if secs is None:
        secs = time()
    days, rem = divmod(secs, 86400)
    z = days + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    y = yoe + era * 400 + (m <= 2)
    return (y, m, d, rem // 3600, rem % 3600 // 60, rem % 60, (days + 3) % 7, 0)


# The time zone: minutes to add to UTC (the clock chip keeps UTC). Settings
# sets it, e.g. -300 for Peru or Colombia (UTC-5), 60 for Spain in winter.
TZ_MINUTES = 0


def localtime(secs=None):
    if secs is None:
        secs = time()
    return gmtime(secs + TZ_MINUTES * 60)
