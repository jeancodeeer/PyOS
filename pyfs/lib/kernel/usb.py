# USB devices on an xHCI controller: keyboards, mice and USB sticks.
#
#   usb.init()          find controllers, set up every device plugged in
#   usb.devices         what was found
#   usb.mount('/usb')   the first USB stick, as a FAT filesystem
#
# A keyboard's reports are turned into PS/2 scan codes and handed to
# keyboard.py, a mouse's into mouse.move(): the rest of the system cannot
# tell them from PS/2 ones.
import struct
from kernel import xhci, timer, log
from kernel.hw import dma_buffer

devices = []
_controllers = []

# HID usage id -> PS/2 set 1 scan code (0x100 = needs the E0 prefix)
_KEYS = {
    0x04: 0x1E, 0x05: 0x30, 0x06: 0x2E, 0x07: 0x20, 0x08: 0x12, 0x09: 0x21, 0x0A: 0x22, 0x0B: 0x23, 0x0C: 0x17,
    0x0D: 0x24, 0x0E: 0x25, 0x0F: 0x26, 0x10: 0x32, 0x11: 0x31, 0x12: 0x18, 0x13: 0x19, 0x14: 0x10, 0x15: 0x13,
    0x16: 0x1F, 0x17: 0x14, 0x18: 0x16, 0x19: 0x2F, 0x1A: 0x11, 0x1B: 0x2D, 0x1C: 0x15, 0x1D: 0x2C,
    0x1E: 0x02, 0x1F: 0x03, 0x20: 0x04, 0x21: 0x05, 0x22: 0x06, 0x23: 0x07, 0x24: 0x08, 0x25: 0x09, 0x26: 0x0A,
    0x27: 0x0B, 0x28: 0x1C, 0x29: 0x01, 0x2A: 0x0E, 0x2B: 0x0F, 0x2C: 0x39, 0x2D: 0x0C, 0x2E: 0x0D, 0x2F: 0x1A,
    0x30: 0x1B, 0x31: 0x2B, 0x33: 0x27, 0x34: 0x28, 0x35: 0x29, 0x36: 0x33, 0x37: 0x34, 0x38: 0x35, 0x39: 0x3A,
    0x3A: 0x3B, 0x3B: 0x3C, 0x3C: 0x3D, 0x3D: 0x3E, 0x3E: 0x3F, 0x3F: 0x40, 0x40: 0x41, 0x41: 0x42, 0x42: 0x43,
    0x43: 0x44, 0x44: 0x57, 0x45: 0x58, 0x46: 0x137, 0x47: 0x46, 0x49: 0x152, 0x4A: 0x147, 0x4B: 0x149,
    0x4C: 0x153, 0x4D: 0x14F, 0x4E: 0x151, 0x4F: 0x14D, 0x50: 0x14B, 0x51: 0x150, 0x52: 0x148, 0x53: 0x45,
    0x54: 0x135, 0x55: 0x37, 0x56: 0x4A, 0x57: 0x4E, 0x58: 0x11C, 0x59: 0x4F, 0x5A: 0x50, 0x5B: 0x51, 0x5C: 0x4B,
    0x5D: 0x4C, 0x5E: 0x4D, 0x5F: 0x47, 0x60: 0x48, 0x61: 0x49, 0x62: 0x52, 0x63: 0x53, 0x64: 0x56,
}
# modifier bits of byte 0: LCtrl LShift LAlt LGUI RCtrl RShift RAlt RGUI
_MODS = (0x1D, 0x2A, 0x38, 0x15B, 0x11D, 0x36, 0x138, 0x15C)


def _scancode(code, down):
    from kernel import keyboard
    if code & 0x100:
        keyboard._key(0xE0)
    keyboard._key((code & 0xFF) | (0 if down else 0x80))


class Device:
    def __init__(self, hc, port, speed):
        self.hc, self.port, self.speed = hc, port, speed
        self.kind = "unknown"
        self.name = ""
        ev = hc.command(control=xhci.ENABLE_SLOT << 10)
        self.slot = ev[3] >> 24
        csz = hc.csz
        _, self.out_ctx, out_addr = dma_buffer(32 * csz, 64)
        _, self.in_ctx, self.in_addr = dma_buffer(33 * csz, 64)
        struct.pack_into("<Q", hc.dcbaa, 8 * self.slot, out_addr)
        self.rings = {1: xhci.Ring()}
        _, self.buf, self.buf_addr = dma_buffer(4096, 64)
        max_packet = {1: 64, 2: 8, 3: 64, 4: 512}.get(speed, 8)
        self._ctx(add=0x3, entries=1)
        self._ep_ctx(1, 4, max_packet, 0)                       # endpoint 0: control
        hc.command(self.in_addr, 0, (xhci.ADDRESS_DEVICE << 10) | (self.slot << 24))

    # ---- contexts ----
    def _ctx(self, add, entries):
        csz = self.hc.csz
        self.in_ctx[:] = bytes(len(self.in_ctx))
        struct.pack_into("<II", self.in_ctx, 0, 0, add)          # input control: which contexts to use
        struct.pack_into("<II", self.in_ctx, csz, (entries << 27) | (self.speed << 20), self.port << 16)

    def _ep_ctx(self, dci, ep_type, max_packet, interval):
        off = (dci + 1) * self.hc.csz
        ring = self.rings.setdefault(dci, xhci.Ring())
        struct.pack_into("<IIQI", self.in_ctx, off, interval << 16, (3 << 1) | (ep_type << 3) | (max_packet << 16),
                         ring.addr | 1, 8 if ep_type == 4 else max_packet)

    # ---- transfers ----
    def control(self, request_type, request, value=0, index=0, length=0, data=None):
        """A control transfer on endpoint 0; returns the bytes read (IN) or None."""
        ring = self.rings[1]
        setup = struct.pack("<BBHHH", request_type, request, value, index, length)
        dir_in = request_type & 0x80
        trt = (3 if dir_in else 2) if length else 0
        ring.push(struct.unpack("<Q", setup)[0], 8, (xhci.SETUP << 10) | (1 << 6) | (trt << 16))
        if length:
            if data and not dir_in:
                self.buf[:length] = data
            ring.push(self.buf_addr, length, (xhci.DATA << 10) | ((1 << 16) if dir_in else 0))
        last = ring.push(0, 0, (xhci.STATUS << 10) | (1 << 5) | (0 if dir_in and length else (1 << 16)))
        self.hc.ring(self.slot, 1)
        self.hc.wait(last)
        return bytes(self.buf[:length]) if dir_in else None

    def bulk(self, dci, length, data=None):
        """One bulk transfer; returns the bytes read for an IN endpoint."""
        if data is not None:
            self.buf[:len(data)] = data
            length = len(data)
        trb = self.rings[dci].push(self.buf_addr, length, (xhci.NORMAL << 10) | (1 << 5) | (1 << 2))
        self.hc.ring(self.slot, dci)
        ev = self.hc.wait(trb, 5)
        left = ev[2] & 0xFFFFFF
        return bytes(self.buf[:length - left]) if data is None else None

    def descriptor(self, kind, index=0, length=255):
        return self.control(0x80, 6, (kind << 8) | index, 0, length)

    # ---- setting up ----
    def setup(self):
        d = self.descriptor(1, 0, 18)
        self.vendor, self.product = struct.unpack_from("<HH", d, 8)
        head = self.descriptor(2, 0, 9)
        total = struct.unpack_from("<H", head, 2)[0]
        cfg = self.descriptor(2, 0, min(total, 4096))
        self.control(0x00, 9, cfg[5])                             # SET_CONFIGURATION
        interfaces = _parse(cfg)
        for iface in interfaces:
            cls, sub, proto = iface["class"]
            if cls == 3 and sub == 1 and proto in (1, 2):
                return self._hid(iface, "keyboard" if proto == 1 else "mouse")
            if cls == 8 and sub == 6 and proto == 0x50:
                return self._storage(iface)
        self.kind = "class %02x" % (interfaces[0]["class"][0] if interfaces else 0)

    def _configure(self, endpoints):
        """Configure Endpoint: endpoints = [(address, attributes, max_packet, interval)]."""
        add, top = 1, 1
        entries = []
        for addr, attrs, mps, interval in endpoints:
            num, dir_in = addr & 0xF, addr & 0x80
            dci = 2 * num + (1 if dir_in else 0)
            ep_type = {(2, 0): 2, (3, 0): 3, (2, 1): 6, (3, 1): 7}[(attrs & 3, 1 if dir_in else 0)]
            if self.speed in (1, 2) and attrs & 3 == 3:          # full/low speed: interval is in ms
                n = 3
                while (1 << n) < interval * 8 and n < 10:
                    n += 1
                interval = n
            elif attrs & 3 == 3:
                interval = max(0, interval - 1)
            else:
                interval = 0
            entries.append((dci, ep_type, mps, interval))
            add |= 1 << dci
            top = max(top, dci)
        self._ctx(add, top)
        for dci, ep_type, mps, interval in entries:
            self._ep_ctx(dci, ep_type, mps, interval)
        self.hc.command(self.in_addr, 0, (xhci.CONFIGURE_EP << 10) | (self.slot << 24))
        return [e[0] for e in entries]

    # ---- keyboards and mice ----
    def _hid(self, iface, kind):
        self.kind = kind
        self.control(0x21, 0x0B, 0, iface["number"])              # SET_PROTOCOL: boot reports
        self.control(0x21, 0x0A, 0, iface["number"])              # SET_IDLE
        ep = [e for e in iface["endpoints"] if e[0] & 0x80][0]
        self.hid_dci = self._configure([ep])[0]
        self.report_len = min(8, ep[2])
        _, self.report, self.report_addr = dma_buffer(64, 64)
        self.last = bytes(8)
        self.hc.on_transfer[(self.slot, self.hid_dci)] = self._report
        self._queue_report()

    def _queue_report(self):
        self.rings[self.hid_dci].push(self.report_addr, self.report_len, (xhci.NORMAL << 10) | (1 << 5) | (1 << 2))
        self.hc.ring(self.slot, self.hid_dci)

    def _report(self, ev):
        data = bytes(self.report[:self.report_len])
        if self.kind == "keyboard":
            self._keyboard(data)
        else:
            from kernel import mouse
            dx = data[1] - 256 if data[1] > 127 else data[1]
            dy = data[2] - 256 if data[2] > 127 else data[2]
            mouse.move(dx, dy, data[0] & 7)
        self._queue_report()

    def _keyboard(self, data):
        old, new = self.last, data
        for bit, code in enumerate(_MODS):
            was, now = old[0] >> bit & 1, new[0] >> bit & 1
            if was != now:
                _scancode(code, now)
        for k in old[2:]:
            if k and k not in new[2:] and k in _KEYS:
                _scancode(_KEYS[k], False)
        for k in new[2:]:
            if k and k not in old[2:] and k in _KEYS:
                _scancode(_KEYS[k], True)
        self.last = new

    # ---- USB sticks (bulk-only transport, SCSI commands) ----
    def _storage(self, iface):
        self.kind = "storage"
        eps = [e for e in iface["endpoints"] if e[1] & 3 == 2]
        dcis = self._configure(eps)
        self.bulk_in = [d for d, e in zip(dcis, eps) if e[0] & 0x80][0]
        self.bulk_out = [d for d, e in zip(dcis, eps) if not e[0] & 0x80][0]
        self.tag = 1
        inquiry = self.scsi(bytes([0x12, 0, 0, 0, 36, 0]), 36)
        self.name = (inquiry[8:16] + inquiry[16:32]).decode("latin-1").strip()
        cap = self.scsi(bytes([0x25] + [0] * 9), 8)               # READ CAPACITY (10)
        last, self.block = struct.unpack(">II", cap)
        self.sectors = (last + 1) * self.block // 512

    def scsi(self, cdb, length, data=None):
        """Send a SCSI command wrapped in a CBW; data out or data in; read the CSW."""
        self.tag += 1
        flags = 0x80 if data is None and length else 0
        cbw = struct.pack("<IIIBBB", 0x43425355, self.tag, length if data is None else len(data), flags, 0, len(cdb))
        cbw += cdb + bytes(16 - len(cdb))
        self.bulk(self.bulk_out, 31, cbw)
        result = None
        if data is not None:
            self.bulk(self.bulk_out, len(data), data)
        elif length:
            result = self.bulk(self.bulk_in, length)
        csw = self.bulk(self.bulk_in, 13)
        if len(csw) < 13 or csw[12] != 0:
            raise OSError(5, "USB storage command %#x failed" % cdb[0])
        return result

    # -- block device protocol (512-byte sectors) --
    def readblocks(self, block, buf, offset=0):
        view = memoryview(buf)
        n = len(buf) // 512
        done = 0
        while done < n:
            k = min(8, n - done)
            data = self.scsi(struct.pack(">BBIBHB", 0x28, 0, block + done, 0, k, 0), k * 512)
            view[done * 512:(done + k) * 512] = data
            done += k

    def writeblocks(self, block, buf, offset=0):
        view = memoryview(buf)
        n = len(buf) // 512
        done = 0
        while done < n:
            k = min(8, n - done)
            self.scsi(struct.pack(">BBIBHB", 0x2A, 0, block + done, 0, k, 0), 0, bytes(view[done * 512:(done + k) * 512]))
            done += k

    def ioctl(self, op, arg):
        if op == 4:
            return self.sectors
        if op == 5:
            return 512
        return 0

    def __repr__(self):
        return "<USB %s %04x:%04x port %d %s %s>" % (self.kind, getattr(self, "vendor", 0), getattr(self, "product", 0),
                                                     self.port, xhci.SPEEDS.get(self.speed, "?"), self.name)


def _parse(cfg):
    """Interfaces and their endpoints from a configuration descriptor."""
    out, i = [], 0
    while i + 2 <= len(cfg):
        length, kind = cfg[i], cfg[i + 1]
        if length == 0:
            break
        if kind == 4:                                             # interface
            out.append({"number": cfg[i + 2], "class": (cfg[i + 5], cfg[i + 6], cfg[i + 7]), "endpoints": []})
        elif kind == 5 and out:                                   # endpoint
            addr, attrs = cfg[i + 2], cfg[i + 3]
            mps = struct.unpack_from("<H", cfg, i + 4)[0] & 0x7FF
            out[-1]["endpoints"].append((addr, attrs, mps, cfg[i + 6]))
        i += length
    return out


def _on_tick():
    for hc in _controllers:
        try:
            hc.poll()
        except Exception:
            pass


def init():
    """Find xHCI controllers and set up every device that is plugged in."""
    devices.clear()
    _controllers[:] = xhci.controllers()
    for hc in _controllers:
        for port in range(1, hc.max_ports + 1):
            speed = hc.reset_port(port)
            if not speed:
                continue
            try:
                d = Device(hc, port, speed)
                d.setup()
                devices.append(d)
                log.info("usb: %r" % d)
            except Exception as e:
                log.warn("usb: port %d: %r" % (port, e))
    if _controllers:
        timer.subscribe(_on_tick)
    return devices


def storage():
    return [d for d in devices if d.kind == "storage"]


def mount(path="/usb"):
    """Mount the first USB stick (FAT) at `path`."""
    import vfs
    import os
    from kernel import ata
    sticks = storage()
    if not sticks:
        raise OSError(19, "no USB stick")
    try:
        os.mkdir(path)
    except OSError:
        pass
    vfs.mount(ata.LockedFS(vfs.VfsFat(sticks[0])), path)
    return sticks[0]
