# AHCI: SATA disks on modern PCs (and QEMU's q35 machine).
#
# The controller's registers are memory-mapped (PCI BAR 5). Each port has a
# list of 32 command slots in RAM; a command is a small "FIS" (the packet a
# SATA drive understands) plus a list of memory regions to read into or
# write from. We use slot 0 only and wait for it: simple, and plenty fast.
#
# An AHCIDisk is a block device, like ata.ATADisk: the FAT code in
# ata.mount() works on either.
import struct
from kernel import pci, timer
from kernel.hw import Regs, dma_buffer

SECTOR = 512
# global registers
CAP, GHC, IS, PI, VS = 0x00, 0x04, 0x08, 0x0C, 0x10
# per-port registers (base 0x100 + 0x80 * port)
PxCLB, PxFB, PxIS, PxIE, PxCMD, PxTFD, PxSIG, PxSSTS, PxSERR, PxCI = \
    0x00, 0x08, 0x10, 0x14, 0x18, 0x20, 0x24, 0x28, 0x30, 0x38
CMD_ST, CMD_FRE, CMD_FR, CMD_CR = 1 << 0, 1 << 4, 1 << 14, 1 << 15
SIG_ATA, SIG_ATAPI = 0x00000101, 0xEB140101
READ_DMA_EXT, WRITE_DMA_EXT, IDENTIFY, FLUSH_EXT = 0x25, 0x35, 0xEC, 0xEA
MAX_SECTORS = 128                    # per command: 64 KiB through one buffer


class AHCIDisk:
    def __init__(self, hba, port):
        self.hba, self.port = hba, port
        self.r = Regs(hba.base + 0x100 + 0x80 * port)
        self._stop()
        self._cl_raw, self.cl, cl_addr = dma_buffer(1024, 1024)        # command list
        self._fb_raw, self.fb, fb_addr = dma_buffer(256, 256)           # received FISes
        self._ct_raw, self.ct, self.ct_addr = dma_buffer(256, 128)     # command table, 1 PRD
        self._buf_raw, self.buf, self.buf_addr = dma_buffer(MAX_SECTORS * SECTOR, 4096)
        self.r.write64(PxCLB, cl_addr)
        self.r.write64(PxFB, fb_addr)
        self.r.write32(PxSERR, 0xFFFFFFFF)
        self.r.write32(PxIS, 0xFFFFFFFF)
        self._start()
        ident = self._command(IDENTIFY, 0, 1, False)
        self.model = bytes(ident[54 + (i ^ 1)] for i in range(40)).decode("latin-1").strip()
        self.sectors = struct.unpack_from("<Q", ident, 200)[0] or struct.unpack_from("<I", ident, 120)[0]

    def _stop(self):
        r = self.r
        r.write32(PxCMD, r.read32(PxCMD) & ~(CMD_ST | CMD_FRE))
        for _ in range(100000):
            if not r.read32(PxCMD) & (CMD_CR | CMD_FR):
                return
        raise OSError(16, "AHCI port will not stop")

    def _start(self):
        r = self.r
        for _ in range(100000):
            if not r.read32(PxCMD) & CMD_CR:
                break
        r.write32(PxCMD, r.read32(PxCMD) | CMD_FRE)
        r.write32(PxCMD, r.read32(PxCMD) | CMD_ST)

    def _command(self, cmd, lba, count, write):
        r = self.r
        nbytes = count * SECTOR
        # command header, slot 0: FIS length 5 dwords, W bit, 1 PRD entry
        flags = 5 | (0x40 if write else 0)
        struct.pack_into("<HHIQ", self.cl, 0, flags, 1, 0, self.ct_addr)
        ct = self.ct
        ct[:128] = bytes(128)
        # register host-to-device FIS
        struct.pack_into("<BBBBBBBBBBBBBBBBIII", ct, 0,
                         0x27, 0x80, cmd, 0,
                         lba & 0xFF, (lba >> 8) & 0xFF, (lba >> 16) & 0xFF, 0x40,
                         (lba >> 24) & 0xFF, (lba >> 32) & 0xFF, (lba >> 40) & 0xFF, 0,
                         count & 0xFF, (count >> 8) & 0xFF, 0, 0, 0, 0, 0)
        # physical region descriptor: our bounce buffer
        struct.pack_into("<QII", ct, 0x80, self.buf_addr, 0, (nbytes - 1) | (1 << 31) if nbytes else 0)
        deadline = timer.ticks() + 10 * timer.HZ
        while r.read32(PxTFD) & 0x88:                 # busy / data request
            if timer.ticks() > deadline:
                raise OSError(110, "AHCI port busy")
        r.write32(PxIS, 0xFFFFFFFF)
        r.write32(PxCI, 1)
        while r.read32(PxCI) & 1:
            if r.read32(PxIS) & (1 << 30):            # task file error
                raise OSError(5, "AHCI disk error %#x" % r.read32(PxTFD))
            if timer.ticks() > deadline:
                raise OSError(110, "AHCI command timed out")
        if r.read32(PxTFD) & 0x01:
            raise OSError(5, "AHCI disk error %#x" % r.read32(PxTFD))
        return self.buf[:nbytes]

    # -- block device protocol --
    def readblocks(self, block, buf, offset=0):
        view = memoryview(buf)
        total = len(buf) // SECTOR
        done = 0
        while done < total:
            n = min(MAX_SECTORS, total - done)
            view[done * SECTOR:(done + n) * SECTOR] = self._command(READ_DMA_EXT, block + done, n, False)
            done += n

    def writeblocks(self, block, buf, offset=0):
        view = memoryview(buf)
        total = len(buf) // SECTOR
        done = 0
        while done < total:
            n = min(MAX_SECTORS, total - done)
            self.buf[:n * SECTOR] = view[done * SECTOR:(done + n) * SECTOR]
            self._command(WRITE_DMA_EXT, block + done, n, True)
            done += n

    def flush(self):
        self._command(FLUSH_EXT, 0, 0, False)

    def ioctl(self, op, arg):
        if op == 3:
            self.flush()
        elif op == 4:
            return self.sectors
        elif op == 5:
            return SECTOR
        return 0

    def __repr__(self):
        return "<AHCIDisk port %d: %s, %d MiB>" % (self.port, self.model, self.sectors >> 11)


class HBA:
    def __init__(self, bus, dev, fn):
        pci.write32(bus, dev, fn, 0x04, pci.read32(bus, dev, fn, 0x04) | 0x6)   # memory + bus master
        self.base = pci.read32(bus, dev, fn, 0x24) & ~0xF                       # BAR 5 (ABAR)
        self.r = Regs(self.base)
        self.r.write32(GHC, self.r.read32(GHC) | (1 << 31))                     # AHCI mode
        v = self.r.read32(VS)
        self.version = "%d.%d" % (v >> 16, (v >> 8) & 0xFF)
        self.ports = []
        implemented = self.r.read32(PI)
        for port in range(32):
            if not implemented & (1 << port):
                continue
            pr = Regs(self.base + 0x100 + 0x80 * port)
            if pr.read32(PxSSTS) & 0xF != 3:                                    # no device / no link
                continue
            if pr.read32(PxSIG) == SIG_ATA:
                self.ports.append(port)


def controllers():
    for bus, dev, fn, vendor, device, cls, sub in pci.scan():
        if cls == 0x01 and sub == 0x06:
            yield HBA(bus, dev, fn)


def disks():
    """Every SATA disk on every AHCI controller."""
    out = []
    for hba in controllers():
        for port in hba.ports:
            try:
                out.append(AHCIDisk(hba, port))
            except OSError:
                pass
    return out
