# Graphics modes: the Bochs display adapter ("BGA", VBE DISPI registers).
#
# QEMU's standard VGA, Bochs and VirtualBox all have it. It gives a linear
# framebuffer of 32-bit pixels (B G R x in memory) at any size up to
# 1600x1200; text mode comes back when it is switched off.
#
#   fb = video.set_mode(640, 480)    # -> Framebuffer (fb.buf, fb.width, ...)
#   video.text_mode()
#
# The console keeps working while graphics own the screen (it writes into
# a copy, and to the serial port) and shows everything when text returns.
import uctypes
import _kernel
from _kernel import inb, inw, outb, outw
from kernel import console, irq, log, pci

INDEX, DATA = 0x1CE, 0x1CF
R_ID, R_XRES, R_YRES, R_BPP, R_ENABLE = 0, 1, 2, 3, 4
R_VIRT_W, R_VIRT_H, R_X_OFF, R_Y_OFF = 6, 7, 8, 9
R_VIDEO_MEMORY_64K = 0x0A
ENABLED, LFB = 0x01, 0x40
DEVICES = ((0x1234, 0x1111), (0x80EE, 0xBEEF))   # QEMU/Bochs, VirtualBox

current = None           # the Framebuffer while a graphics mode is on
_font = None


def _reg(i, value=None):
    outw(INDEX, i)
    if value is None:
        return inw(DATA)
    outw(DATA, value)


def available():
    from kernel.arch import ARM, info
    if ARM:
        return bool(info("fb_addr"))
    return 0xB0C0 <= _reg(R_ID) <= 0xB0CF


def framebuffer_address():
    for bus, dev, fn, vendor, device, cls, sub in pci.scan():
        if (vendor, device) in DEVICES:
            return pci.read32(bus, dev, fn, 0x10) & ~0xF
    return 0xE0000000                    # the Bochs default


class Framebuffer:
    def __init__(self, addr, width, height):
        self.addr, self.width, self.height = addr, width, height
        self.pitch = width * 4
        self.buf = uctypes.bytearray_at(addr, self.pitch * height)

    def __repr__(self):
        return "<Framebuffer %dx%d at 0x%x>" % (self.width, self.height, self.addr)


# ---- the text-mode font (VGA plane 2) ----

_SEQ_TEXT = {2: 0x03, 4: 0x02}
_GC_TEXT = {4: 0x00, 5: 0x10, 6: 0x0E}


def _font_access(on):
    """Map VGA plane 2 (the font) at 0xA0000, or go back to text access."""
    seq = {2: 0x04, 4: 0x07} if on else _SEQ_TEXT
    gc = {4: 0x02, 5: 0x00, 6: 0x04} if on else _GC_TEXT
    for i, v in seq.items():
        outb(0x3C4, i)
        outb(0x3C5, v)
    for i, v in gc.items():
        outb(0x3CE, i)
        outb(0x3CF, v)


def font():
    """The text-mode font: 256 glyphs x 16 rows of 8 pixels (4096 bytes).
    Read from the video card the first time (while still in text mode)."""
    global _font
    if _font is None:
        if current is not None:
            raise OSError("the font can only be read in text mode")
        with irq.critical():
            _font_access(True)
            raw = bytes(uctypes.bytearray_at(0xA0000, 256 * 32))
            _font_access(False)
        f = bytearray(4096)
        for c in range(256):
            f[c * 16:c * 16 + 16] = raw[c * 32:c * 32 + 16]
        _font = bytes(f)
    return _font


def _restore_font():
    if _font is None:
        return
    raw = bytearray(256 * 32)
    for c in range(256):
        raw[c * 32:c * 32 + 16] = _font[c * 16:c * 16 + 16]
    with irq.critical():
        _font_access(True)
        uctypes.bytearray_at(0xA0000, len(raw))[:] = raw
        _font_access(False)


# ---- the VGA registers (the adapter changes them for graphics) ----

def _save_vga():
    regs = {"misc": inb(0x3CC)}
    for name, port, count in (("seq", 0x3C4, 5), ("gc", 0x3CE, 9), ("crtc", 0x3D4, 0x19)):
        vals = []
        for i in range(count):
            outb(port, i)
            vals.append(inb(port + 1))
        regs[name] = vals
    att = []
    for i in range(0x15):
        inb(0x3DA)
        outb(0x3C0, i | 0x20)
        att.append(inb(0x3C1))
    inb(0x3DA)
    regs["att"] = att
    return regs


def _restore_vga(regs):
    with irq.critical():
        outb(0x3C2, regs["misc"])
        for i, v in enumerate(regs["seq"]):
            outb(0x3C4, i)
            outb(0x3C5, v)
        outb(0x3D4, 0x11)                    # unlock CRTC registers 0-7
        outb(0x3D5, regs["crtc"][0x11] & 0x7F)
        for i, v in enumerate(regs["crtc"]):
            outb(0x3D4, i)
            outb(0x3D5, v & 0x7F if i == 0x11 else v)
        outb(0x3D4, 0x11)
        outb(0x3D5, regs["crtc"][0x11])
        for i, v in enumerate(regs["gc"]):
            outb(0x3CE, i)
            outb(0x3CF, v)
        for i, v in enumerate(regs["att"]):
            inb(0x3DA)
            outb(0x3C0, i)
            outb(0x3C0, v)
        inb(0x3DA)
        outb(0x3C0, 0x20)                    # palette back on: the screen shows again


_text_regs = None


# ---- modes ----

def video_memory():
    """Bytes of video memory the adapter has (16 MiB when it does not say)."""
    from kernel.arch import ARM, info
    if ARM:
        return info("fb_pitch") * info("fb_height") if info("fb_addr") else 0
    if not available():
        return 0
    k = _reg(R_VIDEO_MEMORY_64K) if _reg(R_ID) >= 0xB0C5 else 0
    return k * 65536 if k else 16 << 20


def supported(width, height):
    """Can the adapter show width x height at 32 bpp? (Bochs wants widths in steps of 8.)"""
    from kernel.arch import ARM, info
    if ARM:
        return info("fb_addr") and width <= info("fb_width") and height <= info("fb_height")
    if width % 8 or width < 320 or height < 200 or width > 2560 or height > 1600:
        return False
    return width * height * 4 <= video_memory()


def set_mode(width=640, height=480):
    """Switch to a width x height, 32 bpp graphics mode."""
    global current, _text_regs
    from kernel.arch import ARM, info
    if ARM:                              # ARM64: the screen UEFI set up; its size is fixed
        if not info("fb_addr"):
            raise OSError("no screen (UEFI gave no framebuffer)")
        if current is None and console.current:
            console.current.detach()
        current = Framebuffer(info("fb_addr"), info("fb_width"), info("fb_height"))
        current.pitch = info("fb_pitch")
        current.buf = uctypes.bytearray_at(current.addr, current.pitch * current.height)
        return current
    if not available():
        raise OSError("no Bochs/QEMU/VirtualBox display adapter (BGA)")
    if not supported(width, height):
        # refused before touching the adapter: the screen stays as it was
        raise ValueError("the adapter cannot do %dx%d (%d KB of video memory)" %
                         (width, height, video_memory() // 1024))
    font()                               # keep the font: graphics overwrite it
    if current is None:
        with irq.critical():
            _text_regs = _save_vga()
        if console.current:
            console.current.detach()
    _reg(R_ENABLE, 0)
    _reg(R_XRES, width)
    _reg(R_YRES, height)
    _reg(R_BPP, 32)
    _reg(R_VIRT_W, width)
    _reg(R_X_OFF, 0)
    _reg(R_Y_OFF, 0)
    _reg(R_ENABLE, ENABLED | LFB)
    if (_reg(R_XRES), _reg(R_YRES)) != (width, height):
        old = current
        if old is not None:
            # back to the mode that worked, so the desktop keeps its screen
            current = None
            set_mode(old.width, old.height)
        else:
            text_mode()
        raise ValueError("the adapter cannot do %dx%d" % (width, height))
    current = Framebuffer(framebuffer_address(), width, height)
    log.info("video: %dx%d, 32 bpp at 0x%x" % (width, height, current.addr))
    return current


def text_mode():
    """Back to the 80x25 text console."""
    global current
    if current is None:
        return
    from kernel.arch import ARM
    if ARM:
        current = None
        if console.current:
            console.current.attach()
        return
    _reg(R_ENABLE, 0)
    current = None
    if _text_regs:
        _restore_vga(_text_regs)
    _restore_font()
    if console.current:
        console.current.attach()
    log.info("video: text mode")
