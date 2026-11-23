# Which driver handles which device: one table, read by `lsdrv`.
#
# (vendor, device) pairs or (class, subclass) pairs -> driver module name.
from kernel import pci

BY_ID = {
    (0x1AF4, 0x1000): "virtio_net", (0x10EC, 0x8139): "rtl8139",
    (0x8086, 0x100E): "e1000", (0x8086, 0x100F): "e1000", (0x8086, 0x10D3): "e1000", (0x8086, 0x153A): "e1000",
    (0x8086, 0x2415): "ac97", (0x8086, 0x2425): "ac97", (0x8086, 0x24C5): "ac97", (0x8086, 0x266E): "ac97",
    (0x1234, 0x1111): "video",
}
BY_CLASS = {
    (0x01, 0x01): "ata", (0x01, 0x06): "ahci", (0x01, 0x08): "nvme", (0x0C, 0x03): "xhci", (0x03, 0x00): "video",
}
WHAT = {"virtio_net": "network", "rtl8139": "network", "e1000": "network", "ac97": "sound", "video": "graphics",
        "ata": "IDE disks", "ahci": "SATA disks", "nvme": "NVMe disks", "xhci": "USB"}


def driver_for(vendor, device, cls, sub):
    return BY_ID.get((vendor, device)) or BY_CLASS.get((cls, sub))


def table():
    """[(bus:dev.fn, vendor:device, class, driver or None)] for every PCI function."""
    rows = []
    for bus, dev, fn, vendor, device, cls, sub in pci.scan():
        rows.append(("%02x:%02x.%d" % (bus, dev, fn), "%04x:%04x" % (vendor, device),
                     pci.CLASSES.get(cls, "%02x" % cls), driver_for(vendor, device, cls, sub)))
    return rows


def init_all():
    """Start the drivers that are not started elsewhere: sound and USB."""
    from kernel import log
    started = []
    names = {r[3] for r in table()}
    if "ac97" in names:
        from kernel import sound
        if sound.init():
            started.append("sound")
    if "xhci" in names:
        from kernel import usb
        try:
            found = usb.init()
            started.append("usb (%d devices)" % len(found))
            if usb.storage():
                usb.mount("/usb")
                log.info("usb: stick mounted at /usb", echo=True)
        except Exception as e:
            log.warn("usb: %r" % e)
    return started
