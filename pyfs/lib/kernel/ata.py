# IDE/ATA disk driver (PIO, LBA28) and persistent storage.
#
# ATADisk is a block device: it only knows how to move 512-byte sectors.
# The on-disk format is FAT, so a disk written here can be opened on any
# other computer. mount() attaches the first disk at /disk.
import io
import vfs
import _thread
import _kernel
from _kernel import inb, outb
from kernel import timer

SECTOR = 512


class ATADisk:
    def __init__(self, base=0x1F0, ctrl=0x3F6, slave=False):
        self.base, self.ctrl = base, ctrl
        self.select = 0xF0 if slave else 0xE0
        outb(ctrl, 0x02)                     # no IRQs: this driver polls
        self.sectors = self._identify()

    def _wait(self, want_data, timeout_s=5):
        for _ in range(4):                   # ~400 ns settle time
            inb(self.ctrl)
        port = self.base + 7
        deadline = timer.ticks() + timeout_s * timer.HZ
        while True:
            for _ in range(2000):
                status = inb(port)
                if status & 0x80:            # busy
                    continue
                if status & 0x21:            # error / device fault
                    raise OSError(5)
                if not want_data or status & 0x08:
                    return
            if timer.ticks() > deadline:
                raise OSError(110)           # timed out

    def _identify(self):
        base = self.base
        outb(base + 6, self.select & 0xB0)
        for reg in (2, 3, 4, 5):
            outb(base + reg, 0)
        outb(base + 7, 0xEC)
        if inb(base + 7) in (0x00, 0xFF):
            raise OSError(19)                # no device
        self._wait(True)
        ident = bytearray(SECTOR)
        _kernel.insw(base, ident)
        return int.from_bytes(ident[120:124], "little")

    def _command(self, lba, cmd):
        base = self.base
        outb(base + 6, self.select | ((lba >> 24) & 0x0F))
        outb(base + 2, 1)
        outb(base + 3, lba & 0xFF)
        outb(base + 4, (lba >> 8) & 0xFF)
        outb(base + 5, (lba >> 16) & 0xFF)
        outb(base + 7, cmd)

    # -- block device protocol --
    def readblocks(self, block, buf, offset=0):
        view = memoryview(buf)
        for i in range(len(buf) // SECTOR):
            self._command(block + i, 0x20)
            self._wait(True)
            _kernel.insw(self.base, view[i * SECTOR:(i + 1) * SECTOR])

    def writeblocks(self, block, buf, offset=0):
        view = memoryview(buf)
        for i in range(len(buf) // SECTOR):
            self._command(block + i, 0x30)
            self._wait(True)
            _kernel.outsw(self.base, view[i * SECTOR:(i + 1) * SECTOR])
            self._wait(False)

    def flush(self):
        outb(self.base + 6, self.select)
        outb(self.base + 7, 0xE7)
        self._wait(False, 30)

    def ioctl(self, op, arg):
        if op == 3:
            self.flush()
        elif op == 4:
            return self.sectors
        elif op == 5:
            return SECTOR
        return 0


# ---- one thread at a time inside the FAT code ----
#
# MicroPython's FAT driver is not reentrant, and with preemptive threads two
# threads could otherwise be inside it at once (one is preempted while the
# driver calls readblocks() above). Every filesystem and open-file operation
# on the disk therefore holds this lock.

class DiskLock:
    def __init__(self):
        self._lock = _thread.allocate_lock()
        self.owner = None

    def __enter__(self):
        me = _thread.get_ident()
        if self.owner == me:
            # An interrupt handler or task used the disk in the middle of this
            # thread's own disk operation: refuse instead of corrupting it.
            raise OSError(16)               # EBUSY
        # From here until __exit__ this thread cannot be killed or interrupted
        # (the request waits), and interrupt handlers and tasks wait too: a
        # filesystem update is never left half done.
        _kernel.thread_mask(True)
        self._lock.acquire()
        self.owner = me

    def __exit__(self, *exc):
        self.owner = None
        self._lock.release()
        _kernel.thread_mask(False)


class LockedFile(io.IOBase):
    """An open file on the disk; each call holds the disk lock."""

    def __init__(self, f, lock):
        self._f = f
        self._lock = lock

    def read(self, *args):
        with self._lock:
            return self._f.read(*args)

    def readinto(self, *args):
        with self._lock:
            return self._f.readinto(*args)

    def readline(self, *args):
        with self._lock:
            return self._f.readline(*args)

    def readlines(self):
        with self._lock:
            return self._f.readlines()

    def write(self, data):
        with self._lock:
            return self._f.write(data)

    def seek(self, *args):
        with self._lock:
            return self._f.seek(*args)

    def tell(self):
        with self._lock:
            return self._f.tell()

    def flush(self):
        with self._lock:
            return self._f.flush()

    def close(self):
        with self._lock:
            return self._f.close()

    def ioctl(self, op, arg):
        if op == 1:                         # MP_STREAM_FLUSH
            self.flush()
        elif op == 4:                       # MP_STREAM_CLOSE
            self.close()
        return 0                            # buffer size etc.: use defaults

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class LockedFS:
    """A filesystem whose operations are serialised by a DiskLock."""

    def __init__(self, fs, lock=None):
        self.fs = fs
        self.lock = lock or DiskLock()

    def mount(self, readonly, mkfs):
        with self.lock:
            return self.fs.mount(readonly, mkfs)

    def umount(self):
        with self.lock:
            return self.fs.umount()

    def open(self, path, mode="r"):
        with self.lock:
            f = self.fs.open(path, mode)
        return LockedFile(f, self.lock)

    def ilistdir(self, path):
        with self.lock:
            entries = list(self.fs.ilistdir(path))   # finish while holding the lock
        return iter(entries)

    def chdir(self, path):
        with self.lock:
            return self.fs.chdir(path)

    def getcwd(self):
        with self.lock:
            return self.fs.getcwd()

    def mkdir(self, path):
        with self.lock:
            return self.fs.mkdir(path)

    def rmdir(self, path):
        with self.lock:
            return self.fs.rmdir(path)

    def remove(self, path):
        with self.lock:
            return self.fs.remove(path)

    def rename(self, old, new):
        with self.lock:
            return self.fs.rename(old, new)

    def stat(self, path):
        with self.lock:
            return self.fs.stat(path)

    def statvfs(self, path):
        with self.lock:
            return self.fs.statvfs(path)


disk = None
fs = None


def format(dev=None):
    """Erase the disk and create an empty FAT filesystem on it."""
    vfs.VfsFat.mkfs(dev or disk)


def find_disk():
    """The first disk: IDE, else SATA (AHCI), else NVMe."""
    try:
        return ATADisk()
    except OSError as e:
        first_error = e
    for name in ("ahci", "nvme"):
        try:
            found = __import__("kernel." + name, None, None, ["disks"]).disks()
        except Exception:
            found = []
        if found:
            return found[0]
    raise first_error


def mount(path="/disk"):
    """Attach the first IDE disk at `path`. A completely blank disk is
    formatted; one holding unknown data is left untouched."""
    global disk, fs
    disk = find_disk()
    try:
        fs = LockedFS(vfs.VfsFat(disk))
        vfs.mount(fs, path)
    except OSError:
        # an unformatted disk is only detected when mounting
        first = bytearray(SECTOR)
        disk.readblocks(0, first)
        if any(first):
            raise OSError("disk is not FAT; ata.format() would erase it")
        format(disk)
        fs = LockedFS(vfs.VfsFat(disk))
        vfs.mount(fs, path)
    return disk
