# 8259A programmable interrupt controller.
#
# Remapped so IRQ n arrives on vector BASE + n, and put in automatic-EOI
# mode so handlers never have to acknowledge anything.
from _kernel import inb, outb
from kernel.arch import ARM          # ARM64: the GIC is programmed by rust/arm64; all of this is a no-op

BASE = 0x20
MASTER_CMD, MASTER_DATA = 0x20, 0x21
SLAVE_CMD, SLAVE_DATA = 0xA0, 0xA1


def init():
    if ARM:
        return
    outb(MASTER_CMD, 0x11)        # ICW1: initialise, expect ICW4
    outb(SLAVE_CMD, 0x11)
    outb(MASTER_DATA, BASE)       # ICW2: vector offsets
    outb(SLAVE_DATA, BASE + 8)
    outb(MASTER_DATA, 0x04)       # ICW3: slave on IRQ2
    outb(SLAVE_DATA, 0x02)
    outb(MASTER_DATA, 0x03)       # ICW4: 8086 mode, automatic EOI
    outb(SLAVE_DATA, 0x03)
    outb(MASTER_DATA, 0xFB)       # mask everything except the cascade
    outb(SLAVE_DATA, 0xFF)


def vector(irq):
    return BASE + irq


def enable(irq):
    if ARM:
        return
    port = MASTER_DATA if irq < 8 else SLAVE_DATA
    outb(port, inb(port) & ~(1 << (irq & 7)) & 0xFF)


def disable(irq):
    if ARM:
        return
    port = MASTER_DATA if irq < 8 else SLAVE_DATA
    outb(port, inb(port) | (1 << (irq & 7)))


def masks():
    if ARM:
        return 0
    return inb(MASTER_DATA) | (inb(SLAVE_DATA) << 8)
