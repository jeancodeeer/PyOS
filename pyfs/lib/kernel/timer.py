# System tick: the 8253/8254 PIT on IRQ 0.
#
# The tick count is simply how many times the interrupt has fired, which
# the Rust layer already counts, so keeping time costs no Python at all.
# Subscribers (the scheduler) get called once per tick.
import _kernel
from _kernel import outb
from kernel import irq, pic

HZ = 100
VECTOR = pic.BASE + 0
_subscribers = []
_base = 0
tsc_per_ms = 0


def _on_tick(vector):
    for fn in _subscribers:
        fn()


def subscribe(fn):
    if fn not in _subscribers:
        _subscribers.append(fn)
        irq.register(VECTOR, _on_tick)


def ticks():
    return _kernel.irq_count(VECTOR) - _base


def ms():
    return ticks() * 1000 // HZ


def init(hz=100):
    global HZ, _base, tsc_per_ms
    HZ = hz
    divisor = 1193182 // hz
    outb(0x43, 0x36)              # channel 0, lo/hi, square wave
    outb(0x40, divisor & 0xFF)
    outb(0x40, divisor >> 8)
    _base = _kernel.irq_count(VECTOR)
    _kernel.preempt(VECTOR, 1)    # threads get one tick each, round-robin
    pic.enable(0)


def calibrate():
    """Measure the TSC against the PIT (needs interrupts enabled)."""
    global tsc_per_ms
    t = ticks()
    while ticks() == t:
        _kernel.wait()
    start, t = _kernel.rdtsc(), ticks()
    while ticks() < t + 5:
        _kernel.wait()
    tsc_per_ms = (_kernel.rdtsc() - start) * HZ // 5000
    return tsc_per_ms
