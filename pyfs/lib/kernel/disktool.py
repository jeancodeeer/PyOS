# Disks: partition tables, formatting and installing the system.
#
#   disktool.disks()                  every disk the drivers can see
#   disktool.partitions(disk)         the MBR table: [(n, type, start, sectors)]
#   disktool.partition(disk)          one FAT32 partition over the whole disk
#   disktool.install('/disk')         copy /lib, /bin and /etc to the disk
#
# FAT on a partition is mounted like FAT on a whole disk (FatFs reads the
# MBR). After install(), the copies on the disk come first on the import
# path at boot, so changes to the kernel's Python survive power-off.
import os
import struct
import vfs

FAT_TYPES = {0x01: "FAT12", 0x04: "FAT16", 0x06: "FAT16", 0x0B: "FAT32", 0x0C: "FAT32 LBA", 0x0E: "FAT16 LBA",
             0x07: "NTFS/exFAT", 0x83: "Linux", 0x82: "Linux swap", 0xEE: "GPT", 0xEF: "EFI"}
SYSTEM = "/system"                   # on the disk: /disk/system


def disks():
    out = []
    from kernel import ata
    try:
        out.append(ata.ATADisk())
    except OSError:
        pass
    for name in ("ahci", "nvme", "virtio_blk"):
        try:
            out += __import__("kernel." + name, None, None, ["disks"]).disks()
        except Exception:
            pass
    return out


def describe(disk):
    name = getattr(disk, "model", None) or ("IDE" if disk.__class__.__name__ == "ATADisk" else "disk")
    return "%s, %d MiB" % (name, disk.sectors >> 11)


def read_sector(disk, n):
    buf = bytearray(512)
    disk.readblocks(n, buf)
    return buf


def partitions(disk):
    mbr = read_sector(disk, 0)
    if mbr[510:512] != b"\x55\xaa":
        return []
    if mbr[0x36:0x3B] == b"FAT12" or mbr[0x36:0x3B] == b"FAT16" or mbr[0x52:0x57] == b"FAT32":
        return []                                 # a FAT volume without a partition table
    out = []
    for i in range(4):
        e = mbr[446 + 16 * i:462 + 16 * i]
        kind = e[4]
        start, count = struct.unpack_from("<II", e, 8)
        if kind:
            out.append((i + 1, kind, start, count))
    return out


def table_text(disk):
    rows = partitions(disk)
    if not rows:
        return "sin tabla de particiones (todo el disco es un volumen, o esta vacio)"
    return "\n".join("%d  %-10s inicio %8d  %6d MiB" % (n, FAT_TYPES.get(k, "%#x" % k), s, c >> 11)
                     for n, k, s, c in rows)


def partition(disk, kind=0x0C):
    """Write an MBR with one partition covering the disk (from 1 MiB) and
    format it as FAT. ERASES THE DISK."""
    start = 2048
    count = disk.sectors - start
    mbr = bytearray(512)
    entry = struct.pack("<B3sB3sII", 0x80, b"\xfe\xff\xff", kind, b"\xfe\xff\xff", start, count)
    mbr[446:462] = entry
    mbr[510:512] = b"\x55\xaa"
    disk.writeblocks(0, mbr)
    disk.ioctl(3, 0)
    vfs.VfsFat.mkfs(Partition(disk, start, count))
    return start, count


class Partition:
    """A slice of a disk as a block device (for mkfs and mounting)."""

    def __init__(self, disk, start, count):
        self.disk, self.start, self.count = disk, start, count

    def readblocks(self, block, buf, offset=0):
        self.disk.readblocks(self.start + block, buf)

    def writeblocks(self, block, buf, offset=0):
        self.disk.writeblocks(self.start + block, buf)

    def ioctl(self, op, arg):
        if op == 4:
            return self.count
        if op == 5:
            return 512
        return self.disk.ioctl(op, arg)


def _copy_tree(src, dst, skip=()):
    n = 0
    try:
        os.mkdir(dst)
    except OSError:
        pass
    for name in os.listdir(src):
        if name in skip or name == "__pycache__":
            continue
        a, b = src.rstrip("/") + "/" + name, dst.rstrip("/") + "/" + name
        if os.stat(a)[0] & 0x4000:
            n += _copy_tree(a, b)
        else:
            with open(a, "rb") as fa, open(b, "wb") as fb:
                while True:
                    chunk = fa.read(8192)
                    if not chunk:
                        break
                    fb.write(chunk)
            n += 1
    return n


def install(mount="/disk", progress=print):
    """Copy the running system to the disk mounted at `mount`."""
    target = mount + SYSTEM
    try:
        os.mkdir(target)
    except OSError:
        pass
    total = 0
    for part in ("lib", "bin", "etc"):
        progress("copiando /%s ..." % part)
        total += _copy_tree("/" + part, target + "/" + part)
    with open(target + "/INSTALLED", "w") as f:
        import time
        from kernel import VERSION
        f.write("PyKernel %s installed %04d-%02d-%02d\n" % ((VERSION,) + time.localtime()[:3]))
    progress("%d archivos copiados a %s" % (total, target))
    return total


def installed(mount="/disk"):
    try:
        os.stat(mount + SYSTEM + "/INSTALLED")
        return True
    except OSError:
        return False


def apply_update(mount="/disk", log=None):
    """At boot: an installed copy (an update from GitHub, or install()) also brings
    /etc, /apps, /share and /bin: copy them over the system in RAM, so the boot
    scripts, the apps, fonts and commands are the new ones too. (/lib needs no
    copy: its folder goes first in the import path.)"""
    src = mount + SYSTEM
    count = 0
    for part in ("etc", "apps", "share", "bin"):
        try:
            count += _copy_tree(src + "/" + part, "/" + part)
        except OSError:
            pass
    if log and count:
        log("update: %d files of %s applied" % (count, src))
    return count
