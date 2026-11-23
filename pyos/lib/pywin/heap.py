# The Windows program's heap: malloc, HeapAlloc and VirtualAlloc all come
# from here. Memory is taken from the kernel in big pieces ("arenas") and
# cut into blocks. A free list keeps the holes, and neighbouring holes are
# joined again when a block is freed.
from kernel import mm
from pywin import mem

ARENA = 4 << 20          # bytes asked from the kernel at a time
ALIGN = 16


class Heap:
    def __init__(self):
        self.free_list = []         # [(address, size)], sorted by address
        self.used = {}              # address -> size
        self.arenas = []            # (address, pages), to give back at the end

    def _grow(self, need):
        pages = (max(ARENA, need) + 4095) // 4096
        base = mm.alloc_contiguous(pages)
        if base is None:
            raise MemoryError("PyWin: out of memory")
        self.arenas.append((base, pages))
        self._release(base, pages * 4096)

    def alloc(self, size, zero=True):
        size = max(ALIGN, (size + ALIGN - 1) & ~(ALIGN - 1))
        for _ in range(2):
            for i, (addr, hole) in enumerate(self.free_list):
                if hole >= size:
                    if hole == size:
                        del self.free_list[i]
                    else:
                        self.free_list[i] = (addr + size, hole - size)
                    self.used[addr] = size
                    if zero:
                        mem.zero(addr, size)
                    return addr
            self._grow(size)
        raise MemoryError("PyWin: out of memory")

    def free(self, addr):
        size = self.used.pop(addr, None)
        if size:
            self._release(addr, size)

    def size(self, addr):
        return self.used.get(addr, 0)

    def realloc(self, addr, size):
        if not addr:
            return self.alloc(size)
        old = self.used.get(addr, 0)
        if size <= old:
            return addr
        new = self.alloc(size, zero=False)
        mem.write(new, mem.read(addr, old))
        self.free(addr)
        return new

    def _release(self, addr, size):
        """Put a block back in the free list, joined with its neighbours."""
        holes = self.free_list
        i = 0
        while i < len(holes) and holes[i][0] < addr:
            i += 1
        holes.insert(i, (addr, size))
        if i + 1 < len(holes) and addr + size == holes[i + 1][0]:          # join the next hole
            holes[i] = (addr, size + holes[i + 1][1])
            del holes[i + 1]
        if i > 0 and holes[i - 1][0] + holes[i - 1][1] == addr:           # join the previous one
            holes[i - 1] = (holes[i - 1][0], holes[i - 1][1] + holes[i][1])
            del holes[i]

    def destroy(self):
        for base, pages in self.arenas:
            mm.free_contiguous(base, pages)
        self.arenas, self.free_list, self.used = [], [], {}
