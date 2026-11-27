# SnakeyOS: the operating system that runs on PyKernel.
#
# PyKernel (pyfs/ in the repository) is the kernel: drivers, memory, network,
# processes, the console. SnakeyOS (pyos/) is what people use on top of it: the
# desktop, the apps, the web browser, fonts, sounds and images.
NAME = "SnakeyOS"
VERSION = "1.2.0"          # the version this image was built as; updates write theirs in /etc/version


_running = None


def running_version():
    """The version this boot started with (an update installed since waits for the restart)."""
    global _running
    if _running is None:
        _running = version()
    return _running


def version():
    """The version running now (an update installed from GitHub changes it)."""
    for path in ("/disk/system/etc/version", "/etc/version"):
        try:
            with open(path) as f:
                v = f.read().strip()
            if v:
                return v
        except OSError:
            pass
    return VERSION


def kernel_version():
    from kernel import VERSION as k
    return k


def banner():
    return "%s %s sobre PyKernel %s" % (NAME, VERSION, kernel_version())


running_version()          # remembered at boot
