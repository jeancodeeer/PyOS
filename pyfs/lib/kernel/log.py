# Kernel log.
#
# Two sources, shown together by `dmesg`: what the Rust layer printed while
# bringing the machine up (kept in a ring in Rust, read with _kernel.klog)
# and messages logged from Python with log.info() / warn() / error().
import _kernel

LEVELS = ("debug", "info", "warn", "error")
MAX_ENTRIES = 300
entries = []                  # (milliseconds since boot, level, text)


def _now():
    try:
        from kernel import timer
        return timer.ms()
    except Exception:
        return 0


def log(level, text, echo=False):
    entries.append((_now(), level, text))
    if len(entries) > MAX_ENTRIES:
        del entries[0]
    if echo:
        print(text)


def debug(text, echo=False):
    log("debug", text, echo)


def info(text, echo=False):
    log("info", text, echo)


def warn(text, echo=False):
    log("warn", text, echo)


def error(text, echo=False):
    log("error", text, echo)


def lines(level="debug"):
    """Rust boot log followed by Python entries at `level` or above."""
    out = []
    for line in str(_kernel.klog(), "utf8").replace("\r", "").split("\n"):
        if line.strip():
            out.append("[  rust  ] " + line)
    floor = LEVELS.index(level)
    for ms, lvl, text in entries:
        if LEVELS.index(lvl) >= floor:
            out.append("[%4d.%03d] %-5s %s" % (ms // 1000, ms % 1000, lvl, text))
    return out
