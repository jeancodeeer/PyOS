# Memory management policy.
#
# The Rust layer identity-maps the first 64 GiB, hands the VM an initial
# heap and sets aside a "reserve" the heap grows into by itself when it is
# full. Everything else about memory is decided here: which physical frames
# are free (for drivers, DMA buffers and programs) and the page tables.
#
#   mm.stats()   -> {"total", "free", "python_used", "python_free", ...} in bytes
import _kernel
from kernel.hw import mem, peek32, peek64, poke64

PAGE = 4096
PRESENT, WRITABLE, USER, HUGE = 0x01, 0x02, 0x04, 0x80
ADDR_MASK = 0x000FFFFFFFFFF000

regions = []      # [cursor, end] of unallocated physical RAM
_freed = []       # frames given back with free_frame()
total_ram = 0


def memory_map():
    """Yield (base, length, type) from the bootloader memory map."""
    from kernel.arch import ARM
    if ARM:
        from kernel import arch
        yield from arch.memory_map()
        return
    mbi = _kernel.info()["multiboot"]
    if not mbi or not peek32(mbi) & 0x40:
        return
    p = peek32(mbi + 48)
    end = p + peek32(mbi + 44)
    while p < end:
        yield peek64(p + 4), peek64(p + 12), peek32(p + 20)
        p += peek32(p) + 4


MAPPED = (1 << 40) if _kernel.info().get("arch") == 1 else 64 << 30   # identity-mapped by rust/boot.rs (1 TiB on ARM64)
LOW = 1 << 32            # many devices can only reach memory below 4 GiB (32-bit DMA)


def init():
    global total_ram
    info = _kernel.info()
    floor = max(info["heap_end"], info["kernel_end"], info["initrd_end"], 0x100000)
    pool = (info.get("pool_start", 0), info.get("pool_end", 0))
    regions.clear()
    _freed.clear()
    total_ram = 0
    for base, length, kind in memory_map():
        if kind != 1:
            continue
        total_ram += length
        start = (max(base, floor) + PAGE - 1) & ~(PAGE - 1)
        end = min(base + length, MAPPED) & ~(PAGE - 1)    # identity-mapped part
        for s, e in ((start, min(end, pool[0])), (max(start, pool[1]), end)) if pool[1] > pool[0] else ((start, end),):
            if e > s:                                    # the heap's reserve is not ours to hand out
                regions.append([s, e])


def free_bytes():
    return sum(r[1] - r[0] for r in regions) + len(_freed) * PAGE


def alloc_frame():
    """One zeroed 4 KiB physical frame."""
    if _freed:
        addr = _freed.pop()
    else:
        for r in regions:
            if r[0] < r[1]:
                addr = r[0]
                r[0] += PAGE
                break
        else:
            raise MemoryError("out of physical frames")
    mem(addr, PAGE)[:] = bytes(PAGE)
    return addr


def alloc_contiguous(count, high=False):
    """A run of physical frames. Low memory first (devices doing 32-bit DMA
    need it); high=True takes memory above 4 GiB first when there is some."""
    order = sorted(regions, key=lambda r: -r[0]) if high else regions
    for r in order:
        if r[1] - r[0] >= count * PAGE:
            addr = r[0]
            r[0] += count * PAGE
            return addr
    raise MemoryError("no contiguous run of %d frames" % count)


def free_frame(addr):
    _freed.append(addr)


def free_contiguous(addr, count):
    """Give back a run from alloc_contiguous(), so it can be handed out again."""
    regions.append([addr, addr + count * PAGE])


def grow_heap(mib=16, force=False):
    """Move `mib` MiB of free RAM into the Python heap. Usually not needed:
    the heap grows by itself from its reserve. Returns 0 when it did nothing
    because the reserve still has room."""
    try:
        if not force and _kernel.heap_pool()[1] >= (mib << 20):
            return 0
    except AttributeError:
        pass
    addr = alloc_contiguous(mib * 256, high=True)
    _kernel.heap_add(addr, mib << 20)
    return addr


def stats():
    """Where the RAM is, in bytes: total, free (for anything), and the Python heap."""
    import gc
    try:
        pool_size, pool_free = _kernel.heap_pool()
    except AttributeError:
        pool_size = pool_free = 0
    heap_free, heap_used = gc.mem_free(), gc.mem_alloc()   # mem_free counts the free reserve too
    heap_free_now = max(0, heap_free - pool_free)          # ...this is what the heap itself has free
    others = free_bytes()
    return {"total": total_ram, "free": others + heap_free, "python_used": heap_used,
            "python_free": heap_free_now, "heap": heap_free_now + heap_used, "reserve": pool_size,
            "reserve_free": pool_free, "frames_free": others,
            "spaces": len(spaces), "space_bytes": sum(sp.resident() for sp in spaces)}


# ---- page tables ----

def root():
    return _kernel.cr(3) & ADDR_MASK


def translate(vaddr):
    """Virtual -> physical address, or None if unmapped."""
    table = root()
    for shift in (39, 30, 21, 12):
        entry = peek64(table + ((vaddr >> shift) & 0x1FF) * 8)
        if not entry & PRESENT:
            return None
        if shift == 12 or (entry & HUGE and shift < 39):
            low = (1 << shift) - 1
            return (entry & ADDR_MASK & ~low) | (vaddr & low)
        table = entry & ADDR_MASK


def map_page(vaddr, paddr, flags=PRESENT | WRITABLE):
    """Map one 4 KiB page, creating intermediate tables as needed."""
    table = root()
    for shift in (39, 30, 21):
        slot = table + ((vaddr >> shift) & 0x1FF) * 8
        entry = peek64(slot)
        if not entry & PRESENT:
            entry = alloc_frame() | PRESENT | WRITABLE
            poke64(slot, entry)
        elif entry & HUGE:
            raise ValueError("address is covered by a huge page")
        table = entry & ADDR_MASK
    poke64(table + ((vaddr >> 12) & 0x1FF) * 8, (paddr & ADDR_MASK) | flags)
    _kernel.invlpg(vaddr)


def unmap_page(vaddr):
    table = root()
    for shift in (39, 30, 21):
        entry = peek64(table + ((vaddr >> shift) & 0x1FF) * 8)
        if not entry & PRESENT or entry & HUGE:
            return False
        table = entry & ADDR_MASK
    poke64(table + ((vaddr >> 12) & 0x1FF) * 8, 0)
    _kernel.invlpg(vaddr)
    return True


# ---- address spaces ----
#
# An AddressSpace is a private set of page tables. It shares the kernel's
# identity map (the first PML4 entry covers 0..512 GiB) and adds its own
# pages from 0x80_0000_0000 upwards. Switching CR3 swaps them in; every
# frame the space allocated is given back by destroy().

USER_BASE = 0x8000000000          # PML4 slot 1: nothing of the kernel lives here
spaces = []


class AddressSpace:
    def __init__(self, name="space"):
        self.name = name
        self.pml4 = alloc_frame()
        kernel_root = root()
        mem(self.pml4, 8)[:] = mem(kernel_root, 8)           # share the identity map
        self.frames = [self.pml4]                            # page-table frames we own
        self.pages = {}                                      # vaddr -> frame
        spaces.append(self)

    def _slot(self, vaddr, create=True):
        table = self.pml4
        for shift in (39, 30, 21):
            slot = table + ((vaddr >> shift) & 0x1FF) * 8
            entry = peek64(slot)
            if not entry & PRESENT:
                if not create:
                    return None
                frame = alloc_frame()
                self.frames.append(frame)
                entry = frame | PRESENT | WRITABLE | USER
                poke64(slot, entry)
            table = entry & ADDR_MASK
        return table + ((vaddr >> 12) & 0x1FF) * 8

    def map(self, vaddr, size, flags=PRESENT | WRITABLE | USER):
        """Back [vaddr, vaddr+size) with fresh zeroed frames."""
        if vaddr < USER_BASE:
            raise ValueError("below USER_BASE belongs to the kernel")
        for page in range(vaddr & ~(PAGE - 1), vaddr + size, PAGE):
            if page in self.pages:
                continue
            frame = alloc_frame()
            self.pages[page] = frame
            poke64(self._slot(page), frame | flags)
        if self.active():
            _kernel.cr(3, self.pml4)

    def unmap(self, vaddr, size):
        for page in range(vaddr & ~(PAGE - 1), vaddr + size, PAGE):
            frame = self.pages.pop(page, None)
            if frame is not None:
                poke64(self._slot(page, False), 0)
                free_frame(frame)
                if self.active():
                    _kernel.invlpg(page)

    def translate(self, vaddr):
        frame = self.pages.get(vaddr & ~(PAGE - 1))
        return None if frame is None else frame | (vaddr & (PAGE - 1))

    def write(self, vaddr, data):
        """Copy bytes into this space without switching to it (through the frames)."""
        i = 0
        while i < len(data):
            phys = self.translate(vaddr + i)
            if phys is None:
                raise MemoryError("unmapped %#x" % (vaddr + i))
            n = min(len(data) - i, PAGE - ((vaddr + i) & (PAGE - 1)))
            mem(phys, n)[:] = data[i:i + n]
            i += n

    def read(self, vaddr, size):
        out = bytearray()
        while len(out) < size:
            phys = self.translate(vaddr + len(out))
            if phys is None:
                raise MemoryError("unmapped %#x" % (vaddr + len(out)))
            n = min(size - len(out), PAGE - ((vaddr + len(out)) & (PAGE - 1)))
            out += mem(phys, n)
        return bytes(out)

    def active(self):
        return root() == self.pml4

    def activate(self):
        _kernel.cr(3, self.pml4)

    def resident(self):
        return len(self.pages) * PAGE

    def destroy(self):
        if self.active():
            _kernel.cr(3, kernel_pml4)
        for frame in self.pages.values():
            free_frame(frame)
        for frame in self.frames:
            free_frame(frame)
        self.pages.clear()
        self.frames.clear()
        if self in spaces:
            spaces.remove(self)

    def __repr__(self):
        return "<AddressSpace %s cr3=%#x %d KiB>" % (self.name, self.pml4, self.resident() >> 10)


kernel_pml4 = root()


