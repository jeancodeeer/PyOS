# PS/2 mouse driver (the second port of the keyboard controller).
#
# The mouse sends 3-byte packets: buttons, dx, dy. This keeps an absolute
# position inside `bounds` (set by whoever owns the screen, e.g. pygame)
# and tells `listener(dx, dy, buttons)` about every packet.
#
#   mouse.x, mouse.y, mouse.buttons      # buttons: bit 0 left, 1 right, 2 middle
import _kernel
from _kernel import inb, outb
from kernel import irq, pic

IRQ = 12
x = y = 0
buttons = 0
bounds = (640, 480)
speed = 1.0                # pointer speed (Settings): 0.5 slower ... 2.0 faster
left_handed = False        # swap the left and right buttons
listener = None          # fn(dx, dy, buttons)
present = False
_packet = []


def _wait_write():
    for _ in range(100000):
        if not inb(0x64) & 2:
            return


def _send(byte):
    """A command for the mouse; returns its reply (0xFA = acknowledged)."""
    _wait_write()
    outb(0x64, 0xD4)                 # next data byte goes to the mouse
    _wait_write()
    outb(0x60, byte)
    from kernel import timer
    end = timer.ms() + 100
    while timer.ms() < end:
        data = _kernel.irq_read(pic.vector(IRQ))
        if data:
            return data[0]
        _kernel.wait()
    return None


def _config(update):
    with irq.critical():             # or the keyboard interrupt takes the reply
        _config_locked(update)


def _config_locked(update):
    _wait_write()
    outb(0x64, 0x20)                 # read the controller configuration byte
    for _ in range(100000):
        if inb(0x64) & 1:
            break
    cfg = update(inb(0x60))
    _wait_write()
    outb(0x64, 0x60)
    _wait_write()
    outb(0x60, cfg)


def move(dx, dy, new_buttons):
    """Any pointing device (PS/2 here, USB in usb.py) reports movement here."""
    global x, y, buttons
    if speed != 1.0:
        dx, dy = int(round(dx * speed)), int(round(dy * speed))
    if left_handed:                       # bit 0 = left, bit 1 = right
        new_buttons = (new_buttons & ~3) | ((new_buttons & 1) << 1) | ((new_buttons & 2) >> 1)
    x = max(0, min(bounds[0] - 1, x + dx))
    y = max(0, min(bounds[1] - 1, y + dy))
    buttons = new_buttons
    if listener is not None:
        try:
            listener(dx, dy, buttons)
        except Exception:
            pass


def _on_irq(vector):
    while True:
        data = _kernel.irq_read(vector)
        if not data:
            return
        for b in data:
            if not _packet and not b & 0x08:
                continue                 # not the first byte of a packet: resync
            _packet.append(b)
            if len(_packet) < 3:
                continue
            flags, dx, dy = _packet
            _packet.clear()
            if flags & 0xC0:             # overflow: drop the packet
                continue
            if flags & 0x10:
                dx -= 256
            if flags & 0x20:
                dy -= 256
            move(dx, -dy, flags & 7)     # the mouse counts up; the screen counts down


def init():
    """Find and switch on the mouse. Returns True if there is one."""
    global present
    vector = pic.vector(IRQ)
    # mouse bytes: output buffer full (bit 0) and from the mouse (bit 5)
    _kernel.irq_fifo(vector, 0x64, 0x21, 0x21, 0x60)
    pic.enable(2)                    # the cascade that IRQ 12 comes through
    pic.enable(IRQ)
    _wait_write()
    outb(0x64, 0xA8)                 # enable the second port
    _config(lambda c: (c | 0x02) & ~0x20)    # its interrupt on, its clock on
    present = _send(0xF6) == 0xFA and _send(0xF4) == 0xFA   # defaults, start reporting
    _kernel.irq_read(vector)
    irq.register(vector, _on_irq)
    return present
