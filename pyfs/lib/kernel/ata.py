# IDE/ATA disk driver (LBA28) and persistent storage.
#
# ATADisk is a block device: it only knows how to move 512-byte sectors.
# It moves them by DMA when the IDE controller can ("bus master", as on
# every PC and in QEMU): one command carries up to 128 sectors straight to
# memory. Otherwise it uses PIO, the CPU copying the data word by word
# through an I/O port, several sectors per command.
# The on-disk format is FAT, so a disk written here can be opened on any
# other computer. mount() attaches the first disk at /disk.
import io
import vfs
import _thread
import _kernel
from _kernel import inb, outb, inl, outl
from kernel import timer

SECTOR = 512
DMA_SECTORS = 128                            # 64 KiB per DMA command
READ_DMA, WRITE_DMA, READ_PIO, WRITE_PIO = 0xC8, 0xCA, 0x20, 0x30


def bus_master_port(channel_base):
    """The I/O port of the IDE controller's DMA engine for this channel, or None.
    Also lets the controller use the memory bus (PCI "bus master" bit)."""
    from kernel import pci
    for bus, dev, fn, vendor, device, cls, sub in pci.scan():
        if (cls, sub) != (0x01, 0x01):                 # mass storage, IDE
            continue
        bar4 = pci.read32(bus, dev, fn, 0x20)
        if not bar4 & 1 or bar4 & ~3 == 0:
            return None
        cmd = pci.read32(bus, dev, fn, 0x04)
        pci.write32(bus, dev, fn, 0x04, cmd | 0x05)    # I/O space + bus master
        return (bar4 & ~3) + (0 if channel_base == 0x1F0 else 8)
    return None


def _kernel_poke16(addr, value):
    from kernel import hw
    hw.poke16(addr, value)


class ATADisk:
    def __init__(self, base=0x1F0, ctrl=0x3F6, slave=False):
        self.base, self.ctrl = base, ctrl
        self.select = 0xF0 if slave else 0xE0
        outb(ctrl, 0x02)                     # no IRQs: this driver polls
        self.sectors = self._identify()
        self.dma = None
        try:
            self._setup_dma()
        except Exception:
            self.dma = None                  # PIO it is

    def _setup_dma(self):
        """A 64 KiB buffer that does not cross a 64 KiB line (a DMA rule) and
        a one-entry PRD table describing it."""
        from kernel import mm, hw
        port = bus_master_port(self.base)
        if port is None:
            return
        raw = mm.alloc_contiguous(32)                   # 128 KiB: a 64 KiB-aligned half fits
        buf = (raw + 0xFFFF) & ~0xFFFF
        prd = hw.mem(raw if buf - raw >= 16 else buf + 0x10000, 8)
        prd_addr = raw if buf - raw >= 16 else buf + 0x10000
        prd[:] = (buf.to_bytes(4, "little") + (0).to_bytes(2, "little") +   # 0 = 64 KiB
                  (0x8000).to_bytes(2, "little"))                         # last entry
        self.dma = (port, prd_addr, buf, hw.mem(buf, DMA_SECTORS * SECTOR))
        test = bytearray(SECTOR)
        self._dma(0, 1, False, memoryview(test))        # it must really work, or we stay on PIO

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

    def _command(self, lba, cmd, count=1):
        base = self.base
        outb(base + 6, self.select | ((lba >> 24) & 0x0F))
        outb(base + 2, count & 0xFF)              # 0 means 256
        outb(base + 3, lba & 0xFF)
        outb(base + 4, (lba >> 8) & 0xFF)
        outb(base + 5, (lba >> 16) & 0xFF)
        outb(base + 7, cmd)

    def _dma(self, lba, count, write, view):
        """Move count sectors between the disk and view, through the DMA buffer."""
        port, prd_addr, buf, window = self.dma
        size = count * SECTOR
        if write:
            window[:size] = view[:size]
        outb(port, 0)                                    # engine stopped
        outl(port + 4, prd_addr)                         # where the PRD table is
        outb(port + 2, 0x06)                             # clear "interrupt" and "error"
        dma_cmd = 0x00 if write else 0x08                # bit 3: the device writes to memory
        outb(port, dma_cmd)
        # the PRD entry says how many bytes this transfer is
        _kernel_poke16(prd_addr + 4, size & 0xFFFF)
        self._command(lba, WRITE_DMA if write else READ_DMA, count)
        outb(port, dma_cmd | 1)                          # go
        deadline = timer.ticks() + 5 * timer.HZ
        spins = 0
        while True:
            st = inb(port + 2)
            if not st & 1 or st & 4:                     # no longer active, or done
                break
            if timer.ticks() > deadline:
                outb(port, 0)
                raise OSError(110)
            spins += 1
            if spins > 20:                               # not done at once: let the CPU rest
                _kernel.wait()                           # (the disk finishes while we halt)
        outb(port, 0)
        self._wait(False)
        if st & 2:
            raise OSError(5)
        outb(port + 2, 0x06)
        if not write:
            view[:size] = window[:size]

    def _pio(self, lba, count, write, view):
        self._command(lba, WRITE_PIO if write else READ_PIO, count)
        for i in range(count):
            self._wait(True)
            part = view[i * SECTOR:(i + 1) * SECTOR]
            if write:
                _kernel.outsw(self.base, part)
            else:
                _kernel.insw(self.base, part)
        if write:
            self._wait(False)

    def _transfer(self, block, buf, write):
        view = memoryview(buf)
        total = len(buf) // SECTOR
        done = 0
        while done < total:
            n = min(DMA_SECTORS, total - done)
            part = view[done * SECTOR:(done + n) * SECTOR]
            if self.dma is not None:
                try:
                    self._dma(block + done, n, write, part)
                    done += n
                    continue
                except OSError:
                    self.dma = None                      # the controller refused: PIO from now on
            self._pio(block + done, n, write, part)
            done += n

    # -- block device protocol --
    def readblocks(self, block, buf, offset=0):
        self._transfer(block, buf, False)

    def writeblocks(self, block, buf, offset=0):
        self._transfer(block, buf, True)

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
    """The first disk: IDE, else SATA (AHCI), else NVMe, else virtio."""
    try:
        return ATADisk()
    except OSError as e:
        first_error = e
    for name in ("ahci", "nvme", "virtio_blk"):
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
