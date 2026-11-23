# Status bar on the top screen row, refreshed every second by a background
# task:  time, uptime, free memory, threads, keyboard layout.
#
#   status.start()      status.stop()      status.extra = lambda: "text"
import gc
import _kernel
from kernel import console, keyboard, rtc, sched, timer

running = False
extra = None                      # optional callable adding text at the end


def text():
    _, _, _, hh, mm, ss = rtc.now()
    up = timer.ms() // 1000
    line = " PyKernel  %02d:%02d:%02d  up %d:%02d:%02d  free %d KiB  threads %d  kbd %s" % (
        hh, mm, ss, up // 3600, up % 3600 // 60, up % 60,
        gc.mem_free() >> 10, len(_kernel.threads()), keyboard.current)
    con = console.current
    if con and con.offset:
        line += "  [scrollback -%d]" % con.offset
    if extra:
        try:
            line += "  " + str(extra())
        except Exception:
            pass
    return line


def _task():
    while running:
        if console.current:
            console.current.set_status(text())
        yield 1000


def start():
    global running
    if running or not console.current:
        return
    console.current.status_bar(True)
    console.current.set_status(text())
    running = True
    sched.spawn(_task, name="status bar")


def stop():
    global running
    running = False
    if console.current:
        console.current.status_bar(False)
