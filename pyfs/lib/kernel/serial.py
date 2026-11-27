# COM1 input driver: received bytes become console input.
# (Output to the serial port is mirrored by the console driver.)
import _kernel
from _kernel import inb, outb
from kernel import irq, pic

PORT = 0x3F8


def _on_irq(vector):
    inb(PORT + 2)                            # acknowledge
    while inb(PORT + 5) & 1:
        _kernel.stdin_push(inb(PORT))


def init():
    from kernel.arch import ARM
    if ARM:                                  # ARM64: the console reads the UART (PL011) itself (mpy/mphal.c)
        return
    irq.register(pic.vector(4), _on_irq)
    outb(PORT + 1, 0x01)                     # interrupt on received data
    pic.enable(4)
