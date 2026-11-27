# Kernel bring-up, in Python. Called once by /init.py after the root
# filesystem is mounted. Change the order, swap a driver, add your own.
import sys
import _kernel
from kernel import (VERSION, ata, console, errors, history, keyboard, lineedit, log, mm, mouse, pic,
                    repl, serial, shell, status, timer)


def main():
    _kernel.irq_disable()
    pic.init()                    # interrupt controller: all lines masked
    console.install()             # screen takes over from the serial log
    mm.init()                     # physical memory inventory
    if mm.free_bytes() > (192 << 20):
        mm.grow_heap(64)          # plenty of RAM: give Python room (pygame windows are big)
    timer.init(100)               # 100 Hz system tick
    keyboard.init()
    serial.init()
    _kernel.irq_enable()
    timer.calibrate()
    mouse.init()                  # PS/2 mouse (pygame uses it)
    status.start()                # status bar on the top row
    errors.install()              # tracebacks show the failing source lines
    lineedit.install()            # the prompt's line editor (colours, Tab, Ctrl-R)
    repl.install()                # the console loop itself: behaves like CPython's
    log.info("drivers up: pic, console, timer %d Hz, keyboard, serial, mouse %s" % (
        timer.HZ, "yes" if mouse.present else "none"))

    info = _kernel.info()
    print("\x1b[1;32mPyKernel %s\x1b[0m -- Python is the operating system" % VERSION)
    print("CPU: %s   RAM: %d MiB   heap: %d MiB" % (
        shell.cpu_name(), mm.total_ram >> 20, (info["heap_end"] - info["heap_start"]) >> 20))
    print("Type \x1b[1mhelp\x1b[0m for commands. The kernel lives in /lib/kernel.")

    try:
        disk = ata.mount("/disk")            # persistent storage
        sys.path.append("/disk/lib")
        from kernel import disktool
        if disktool.installed():             # the installed copy comes before the boot image
            sys.path.insert(0, "/disk/system/lib")
            try:
                disktool.apply_update(log=log.info)   # and its /etc, /apps, /share, /bin (updates)
            except Exception as e:
                log.warn("update: could not apply: %r" % e)
        line = "Disk: %d MiB mounted at /disk (files there survive power-off)" % (disk.sectors >> 11)
        log.info(line, echo=True)
        n = history.enable()
        shell.load_aliases()
        if n:
            log.info("history: %d commands restored" % n)
    except OSError as e:
        log.warn("Disk: none (%s); files live in RAM only" % e, echo=True)

    _network()
    _system()
    _init_scripts()

    import __main__
    for script in ("/autoexec.py", "/disk/autoexec.py"):
        try:
            with open(script) as f:
                source = f.read()
        except OSError:
            continue
        try:
            exec(compile(source, script, "exec"), __main__.__dict__)
            log.info("ran " + script)
        except Exception as e:
            log.error("%s failed: %r" % (script, e))
            errors.show(e, script + " failed:")


def _network():
    """Network card up now; DHCP runs as a background task (a few seconds)."""
    from kernel import net

    def done(err):
        if err is None:
            log.info("net: %s on %s (%s)" % (net.ntoa(net.ip), net.nic.name, net.mac_text()))
        else:
            log.info("net: DHCP failed (%s)" % (err.args[-1] if err.args else err))

    try:
        net.up_background(done)
    except OSError as e:
        log.info("net: %s" % (e.args[-1] if e.args else e))


def _system():
    """/dev and /proc, the process table, and the boot services."""
    import os
    for d in ("/dev", "/proc", "/bin", "/etc", "/tmp"):
        try:
            os.mkdir(d)
        except OSError:
            pass
    from kernel import devfs, proc, services, drivers
    devfs.install()
    try:
        for name in drivers.init_all():
            log.info("driver: " + name)
    except Exception as e:
        log.error("drivers: %r" % e)
    try:
        services.boot()
    except Exception as e:
        log.error("services: %r" % e)


def _init_scripts():
    """Run /etc/init.d/*.py in order: how an operating system built on the
    kernel (SnakeyOS, for one) starts itself and adds its commands."""
    import os
    import __main__
    try:
        names = sorted(n for n in os.listdir("/etc/init.d") if n.endswith(".py"))
    except OSError:
        return
    for name in names:
        path = "/etc/init.d/" + name
        try:
            with open(path) as f:
                exec(compile(f.read(), path, "exec"), {"__name__": "init", "__file__": path})
            log.info("init: " + name)
        except Exception as e:
            log.error("init %s failed: %r" % (name, e))
            errors.show(e, path + " failed:")
