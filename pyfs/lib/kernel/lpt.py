# The parallel port (LPT1, LPT2...): where classic printers are plugged in.
#
# A parallel port has three registers next to each other:
#   base + 0  data     the byte to send
#   base + 1  status   what the printer says (busy, out of paper, error...)
#   base + 2  control  what we say (strobe = "the byte is ready", init...)
#
# Sending one byte: wait until the printer is not busy, put the byte on the
# data lines, then pulse the strobe line. The printer reads the byte.
#
# Each port found becomes a device: /dev/lp0, /dev/lp1... Writing to it
# prints. In QEMU, `-parallel file:out.prn` saves what is printed to a file.
import time
from _kernel import inb, outb

PORTS = (0x378, 0x278, 0x3BC)              # where LPT1, LPT2 and LPT3 usually are
STATUS_BUSY = 0x80                         # 0 = busy (this line is inverted)
STATUS_ACK = 0x40
STATUS_PAPER_OUT = 0x20
STATUS_SELECTED = 0x10
STATUS_ERROR = 0x08                        # 0 = error (inverted too)
CONTROL_STROBE = 0x01
CONTROL_INIT = 0x04                        # 0 = reset the printer
CONTROL_SELECT = 0x08
WAIT_MS = 3000                             # how long a busy printer may make us wait

ports = []                                 # the Port objects that were found


class PrinterError(OSError):
    pass


class Port:
    def __init__(self, base, number):
        self.base = base
        self.number = number               # 0 for LPT1 / lp0
        self.sent = 0                      # bytes printed since boot

    @property
    def name(self):
        return "LPT%d" % (self.number + 1)

    def reset(self):
        outb(self.base + 2, CONTROL_SELECT)                    # INIT low: reset
        time.sleep_ms(1)
        outb(self.base + 2, CONTROL_SELECT | CONTROL_INIT)     # back to normal

    def status(self):
        s = inb(self.base + 1)
        return {"busy": not s & STATUS_BUSY, "paper_out": bool(s & STATUS_PAPER_OUT),
                "error": not s & STATUS_ERROR, "selected": bool(s & STATUS_SELECTED)}

    def _wait_ready(self):
        if inb(self.base + 1) & STATUS_BUSY:
            return
        end = time.ticks_add(time.ticks_ms(), WAIT_MS)
        while not inb(self.base + 1) & STATUS_BUSY:
            if time.ticks_diff(end, time.ticks_ms()) <= 0:
                raise PrinterError(5, "la impresora %s no responde" % self.name)
            time.sleep_ms(1)

    def write_byte(self, b):
        self._wait_ready()
        outb(self.base, b)
        control = CONTROL_SELECT | CONTROL_INIT
        outb(self.base + 2, control | CONTROL_STROBE)          # "the byte is ready"
        outb(self.base + 2, control)

    def write(self, data):
        """Print bytes. Returns how many were sent."""
        if isinstance(data, str):
            data = data.encode()
        st = self.status()
        if st["paper_out"]:
            raise PrinterError(5, "la impresora %s no tiene papel" % self.name)
        for b in data:
            self.write_byte(b)
        self.sent += len(data)
        return len(data)


def _present(base):
    """Is there a parallel port here? Its data register keeps what is written."""
    for pattern in (0xAA, 0x55):
        outb(base, pattern)
        if inb(base) != pattern:
            return False
    outb(base, 0)
    return True


def init():
    """Find the parallel ports and add /dev/lp0, /dev/lp1..."""
    from kernel import log
    if ports:
        return ports
    for base in PORTS:
        try:
            if _present(base):
                port = Port(base, len(ports))
                port.reset()
                ports.append(port)
        except Exception as e:
            log.warn("lpt: %#x: %r" % (base, e))
    try:
        from kernel import devfs
        for port in ports:
            devfs.dev.add("lp%d" % port.number, None, port.write)
    except Exception as e:
        log.warn("lpt: /dev: %r" % e)
    for port in ports:
        log.info("lpt: %s at %#x -> /dev/lp%d" % (port.name, port.base, port.number))
    return ports


def find(name):
    """A port by its name: 'LPT1', 'lp0' or '/dev/lp0'."""
    name = name.lower().replace("/dev/", "")
    for port in ports:
        if name in (port.name.lower(), "lp%d" % port.number):
            return port
    return None
