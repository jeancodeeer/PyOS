# NVMe: the fast SSDs of modern PCs (and QEMU's -device nvme).
#
# The controller and the driver talk through queues in RAM. Each queue is a
# pair: we write 64-byte commands into a submission queue and ring a
# doorbell; the controller writes 16-byte results into a completion queue.
# One "admin" pair sets things up, one "I/O" pair reads and writes blocks.
import struct
from kernel import pci, timer
from kernel.hw import Regs, dma_buffer

DEPTH = 16                      # entries per queue: we only ever have one command in flight
SECTOR = 512
MAX_SECTORS = 8                 # one 4 KiB page per command


class Queue:
    """A submission queue and its completion queue."""

    def __init__(self, ctrl, qid):
        self.ctrl, self.qid = ctrl, qid
        _, self.sq, self.sq_addr = dma_buffer(64 * DEPTH)
        _, self.cq, self.cq_addr = dma_buffer(16 * DEPTH)
        self.tail = self.head = 0
        self.phase = 1                       # flips each time the completion queue wraps
        self.cid = 0

    def run(self, opcode, nsid=0, prp1=0, prp2=0, cdw10=0, cdw11=0, cdw12=0):
        """Submit one command, wait for its completion, return dword 0 of the result."""
        self.cid = (self.cid + 1) & 0xFFFF
        cmd = struct.pack("<BBHIQQQQIIIIII", opcode, 0, self.cid, nsid, 0, 0, prp1, prp2,
                          cdw10, cdw11, cdw12, 0, 0, 0)
        self.sq[64 * self.tail:64 * self.tail + 64] = cmd
        self.tail = (self.tail + 1) % DEPTH
        r = self.ctrl.r
        r.write32(0x1000 + (2 * self.qid) * self.ctrl.stride, self.tail)          # SQ tail doorbell
        deadline = timer.ticks() + 5 * timer.HZ
        while True:
            dw0 = struct.unpack_from("<I", self.cq, 16 * self.head)[0]
            status = struct.unpack_from("<H", self.cq, 16 * self.head + 14)[0]
            if (status & 1) == self.phase:
                break
            if timer.ticks() > deadline:
                raise OSError(110, "NVMe command %#x timed out" % opcode)
        self.head = (self.head + 1) % DEPTH
        if self.head == 0:
            self.phase ^= 1
        r.write32(0x1000 + (2 * self.qid + 1) * self.ctrl.stride, self.head)      # CQ head doorbell
        if status >> 1:
            raise OSError(5, "NVMe error %#x on command %#x" % (status >> 1, opcode))
        return dw0


class NVMe:
    def __init__(self, bus, dev, fn):
        pci.write32(bus, dev, fn, 0x04, pci.read32(bus, dev, fn, 0x04) | 0x6)   # memory + bus master
        base = pci.read32(bus, dev, fn, 0x10) & ~0xF
        if pci.read32(bus, dev, fn, 0x10) & 0x4:
            base |= pci.read32(bus, dev, fn, 0x14) << 32
        self.r = r = Regs(base)
        cap = r.read64(0x00)
        self.stride = 4 << ((cap >> 32) & 0xF)
        # reset: disable, wait, set up the admin queues, enable
        r.write32(0x14, 0)
        self._wait_ready(False)
        self.admin = Queue(self, 0)
        r.write32(0x24, ((DEPTH - 1) << 16) | (DEPTH - 1))       # admin queue sizes
        r.write64(0x28, self.admin.sq_addr)
        r.write64(0x30, self.admin.cq_addr)
        r.write32(0x14, (4 << 20) | (6 << 16) | 1)              # 16-byte CQ, 64-byte SQ entries, enable
        self._wait_ready(True)
        _, self.page, self.page_addr = dma_buffer(4096)
        self._identify()
        # one I/O queue pair: create the completion queue first
        self.io = Queue(self, 1)
        self.admin.run(0x05, prp1=self.io.cq_addr, cdw10=((DEPTH - 1) << 16) | 1, cdw11=1)
        self.admin.run(0x01, prp1=self.io.sq_addr, cdw10=((DEPTH - 1) << 16) | 1, cdw11=(1 << 16) | 1)

    def _wait_ready(self, ready):
        deadline = timer.ticks() + 5 * timer.HZ
        while bool(self.r.read32(0x1C) & 1) != ready:
            if timer.ticks() > deadline:
                raise OSError(110, "NVMe controller not ready")

    def _identify(self):
        self.admin.run(0x06, prp1=self.page_addr, cdw10=1)              # identify controller
        self.model = bytes(self.page[24:64]).decode("latin-1").strip()
        self.admin.run(0x06, nsid=1, prp1=self.page_addr, cdw10=0)      # identify namespace 1
        nsze = struct.unpack_from("<Q", self.page, 0)[0]
        fmt = self.page[26] & 0xF
        lbads = self.page[128 + 4 * fmt + 2]
        self.block = 1 << lbads                                      # usually 512 or 4096
        self.sectors = nsze * self.block // SECTOR

    def _rw(self, opcode, sector, count):
        per = self.block // SECTOR
        lba, nblocks = sector // per, max(1, count // per)
        self.io.run(opcode, nsid=1, prp1=self.page_addr, cdw10=lba & 0xFFFFFFFF, cdw11=lba >> 32,
                    cdw12=nblocks - 1)

    # -- block device protocol (512-byte sectors, like the other disks) --
    def readblocks(self, block, buf, offset=0):
        view = memoryview(buf)
        n = len(buf) // SECTOR
        done = 0
        while done < n:
            k = min(MAX_SECTORS, n - done)
            self._rw(0x02, block + done, k)
            view[done * SECTOR:(done + k) * SECTOR] = self.page[:k * SECTOR]
            done += k

    def writeblocks(self, block, buf, offset=0):
        view = memoryview(buf)
        n = len(buf) // SECTOR
        done = 0
        while done < n:
            k = min(MAX_SECTORS, n - done)
            self.page[:k * SECTOR] = view[done * SECTOR:(done + k) * SECTOR]
            self._rw(0x01, block + done, k)
            done += k

    def flush(self):
        self.io.run(0x00, nsid=1)

    def ioctl(self, op, arg):
        if op == 3:
            self.flush()
        elif op == 4:
            return self.sectors
        elif op == 5:
            return SECTOR
        return 0

    def __repr__(self):
        return "<NVMe %s, %d MiB>" % (self.model, self.sectors >> 11)


def disks():
    out = []
    for bus, dev, fn, vendor, device, cls, sub in pci.scan():
        if cls == 0x01 and sub == 0x08:
            try:
                out.append(NVMe(bus, dev, fn))
            except OSError:
                pass
    return out
