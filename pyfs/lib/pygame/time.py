# pygame.time: milliseconds since pygame.init(), delays and frame clocks.
import _kernel
import time as _t

_start = _t.ticks_us()
_timers = {}


def _now_us():
    return _t.ticks_us() - _start


def get_ticks():
    return _now_us() // 1000


def _sleep_us(us):
    end = _t.ticks_us() + us
    while end - _t.ticks_us() > 12000:   # the timer ticks every 10 ms: sleep...
        _kernel.wait()
    while _t.ticks_us() < end:           # ... and wait out the rest precisely
        pass


def wait(milliseconds):
    t = _t.ticks_us()
    _sleep_us(int(milliseconds) * 1000)
    return (_t.ticks_us() - t) // 1000


delay = wait


def set_timer(event, millis, loops=0):
    """Post `event` every `millis` ms (from the timer interrupt)."""
    from kernel import sched
    from pygame import event as ev
    if hasattr(event, "type"):
        make = lambda: event
        key = event.type
    else:
        make = lambda: ev.Event(event)
        key = event
    old = _timers.pop(key, None)
    if old is not None:
        sched.kill(old.id)
    if millis <= 0:
        return

    def ticker():
        n = 0
        while not loops or n < loops:
            yield millis
            ev.post(make())
            n += 1

    _timers[key] = sched.spawn(ticker, "pygame timer")


class Clock:
    def __init__(self):
        self._last = _now_us()
        self._time = 0
        self._raw = 0
        self._frames = []

    def tick(self, framerate=0):
        now = _now_us()
        self._raw = (now - self._last) // 1000
        if framerate:
            target = self._last + 1000000 // framerate
            if target > now:
                _sleep_us(target - now)
            now = _now_us()
        self._time = (now - self._last) // 1000
        self._last = now
        self._frames.append(now)
        if len(self._frames) > 10:
            del self._frames[0]
        return self._time

    tick_busy_loop = tick

    def get_time(self):
        return self._time

    def get_rawtime(self):
        return self._raw

    def get_fps(self):
        f = self._frames
        if len(f) < 2 or f[-1] == f[0]:
            return 0.0
        return (len(f) - 1) * 1000000 / (f[-1] - f[0])
