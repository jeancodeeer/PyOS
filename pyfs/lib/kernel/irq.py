# Interrupt vector registry.
#
# The Rust layer only counts interrupts and queues the Python handler for
# the vector; everything about what an interrupt *means* is decided here
# and in the drivers.
import _kernel

handlers = {}


def register(vector, fn):
    """Run fn(vector) whenever interrupt `vector` fires."""
    handlers[vector] = fn
    _kernel.irq_handler(vector, fn)


def unregister(vector):
    handlers.pop(vector, None)
    _kernel.irq_handler(vector, None)


def count(vector):
    return _kernel.irq_count(vector)


class critical:
    """with irq.critical(): ... runs with interrupts disabled."""

    def __enter__(self):
        self.was_on = _kernel.irq_disable()

    def __exit__(self, *exc):
        if self.was_on:
            _kernel.irq_enable()
