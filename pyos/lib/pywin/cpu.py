# The switch between Python and the Windows program, in machine code.
#
# A Windows program runs natively on the CPU. When it calls a Windows
# function (WriteFile, printf, MessageBoxA...) it really jumps to a tiny
# "thunk" we made, which saves the program's registers in a block of memory
# (the context) and returns to Python with the thunk's number. Python does
# the work of that function, puts the result in the context, and jumps back
# into the program as if the function had returned normally.
#
#   enter     Python -> program: load the registers from the context, `ret`
#   leave     program -> Python: save the registers, return the thunk number
#   thunk n   mov r10d, n ; jmp leave
#
# Each thread of the program has its own context (Registers). The code
# finds the one in use through a pointer next to it, which Python sets
# before running a thread.
#
# The code is written with the little assembler below, so it can be read.
import struct
from kernel import mm
from pywin import mem

# register numbers, as the CPU encodes them
RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI = range(8)
R8, R9, R10, R11, R12, R13, R14, R15 = range(8, 16)

# where each register lives in the context (byte offsets)
SLOT = {RAX: 16, RBX: 24, RCX: 32, RDX: 40, RSI: 48, RDI: 56, RBP: 64,
        R8: 72, R9: 80, R12: 88, R13: 96, R14: 104, R15: 112}
HOST_RSP, GUEST_RSP, NUMBER, XMM = 0, 8, 120, 128      # XMM: 16 registers of 16 bytes
CONTEXT_SIZE = XMM + 16 * 16
SAVED_XMM = (0, 1, 2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)   # 4 and 5 are scratch on Windows
HOST_SAVED = (RBX, RBP, R12, R13, R14, R15)                     # what Python's side expects kept

THUNK_SIZE = 16


# ---- a tiny assembler: only the instructions this file needs ----

class Asm:
    def __init__(self):
        self.code = bytearray()

    def push(self, r):
        self.code += (b"\x41" if r >= 8 else b"") + bytes([0x50 + (r & 7)])

    def pop(self, r):
        self.code += (b"\x41" if r >= 8 else b"") + bytes([0x58 + (r & 7)])

    def _mem_r11(self, opcode, r, off, prefix=b"", wide=True):
        # [r11 + off] with a 32-bit offset: ModRM mod=10, rm=011 (r11)
        rex = (0x48 if wide else 0x40) | (0x04 if r >= 8 else 0) | 0x01
        self.code += prefix + bytes([rex]) + opcode + bytes([0x80 | ((r & 7) << 3) | 3]) + struct.pack("<i", off)

    def load(self, r, off):           # mov r, [r11 + off]
        self._mem_r11(b"\x8b", r, off)

    def store(self, off, r):          # mov [r11 + off], r
        self._mem_r11(b"\x89", r, off)

    def load_xmm(self, x, off):       # movdqu xmmX, [r11 + off]
        self._mem_r11(b"\x0f\x6f", x, off, b"\xf3", wide=False)

    def store_xmm(self, off, x):      # movdqu [r11 + off], xmmX
        self._mem_r11(b"\x0f\x7f", x, off, b"\xf3", wide=False)

    def r11_from(self, target):       # mov r11, [rip + to target]: the context in use
        self.code += b"\x4c\x8b\x1d" + struct.pack("<i", target - (len(self.code) + 7))

    def ret(self):
        self.code += b"\xc3"


def _enter(asm, ctx):
    for r in HOST_SAVED:                  # keep what Python's C code needs
        asm.push(r)
    asm.r11_from(ctx)
    asm.store(HOST_RSP, RSP)
    asm.load(RSP, GUEST_RSP)              # now on the program's stack
    for x in SAVED_XMM:
        asm.load_xmm(x, XMM + 16 * x)
    for r, off in SLOT.items():
        asm.load(r, off)
    asm.ret()                             # pops the address to continue at


def _leave(asm, ctx):
    asm.r11_from(ctx)
    asm.store(NUMBER, R10)                # which thunk was called
    asm.store(GUEST_RSP, RSP)
    for r, off in SLOT.items():
        asm.store(off, r)
    for x in SAVED_XMM:
        asm.store_xmm(XMM + 16 * x, x)
    asm.load(RSP, HOST_RSP)               # back on Python's stack
    for r in reversed(HOST_SAVED):
        asm.pop(r)
    asm.load(RAX, NUMBER)                 # _kernel.call() returns the number
    asm.ret()


class Switch:
    """The machine code of one Windows process: enter, leave and the thunks."""

    def __init__(self, max_thunks=2048):
        # layout of the block: enter | leave | pointer to the context in use | thunks
        code_room = 512
        size = code_room + 64 + max_thunks * THUNK_SIZE
        self.pages = (size + 4095) // 4096
        self.base = mm.alloc_contiguous(self.pages)
        self.current = self.base + code_room          # where the pointer lives
        self.thunk_base = self.current + 64
        self.max_thunks = max_thunks
        a = Asm()
        _enter(a, code_room)
        self.leave = self.base + len(a.code)
        _leave(a, code_room)                          # same Asm: offsets from the block start
        if len(a.code) > code_room:
            raise RuntimeError("trampolines do not fit")
        mem.zero(self.base, self.pages * 4096)
        mem.write(self.base, a.code)
        self.count = 0

    def new_thunk(self):
        """Machine code that hands control to Python with a new number."""
        n = self.count
        if n >= self.max_thunks:
            raise RuntimeError("too many imported functions")
        addr = self.thunk_base + n * THUNK_SIZE
        jump = self.leave - (addr + 11)
        mem.write(addr, b"\x41\xba" + struct.pack("<I", n) + b"\xe9" + struct.pack("<i", jump))
        self.count += 1
        return n, addr

    def use(self, regs):
        """The thread whose registers enter/leave work with from now on."""
        mem.put64(self.current, regs.ctx)

    def free(self):
        mm.free_contiguous(self.base, self.pages)


class Registers:
    """The saved registers of one thread of the program."""

    def __init__(self, heap):
        self.heap = heap
        self.ctx = heap.alloc(CONTEXT_SIZE)

    def get(self, r):
        return mem.u64(self.ctx + (GUEST_RSP if r == RSP else SLOT[r]))

    def set(self, r, value):
        mem.put64(self.ctx + (GUEST_RSP if r == RSP else SLOT[r]), value & 0xFFFFFFFFFFFFFFFF)

    def get_double(self, x):
        return struct.unpack("<d", mem.read(self.ctx + XMM + 16 * x, 8))[0]

    def get_float(self, x):
        return struct.unpack("<f", mem.read(self.ctx + XMM + 16 * x, 4))[0]

    def set_double(self, x, value):
        mem.write(self.ctx + XMM + 16 * x, struct.pack("<d", value))

    def set_float(self, x, value):
        mem.write(self.ctx + XMM + 16 * x, struct.pack("<f", value) + bytes(4))

    def save(self):
        return mem.read(self.ctx, CONTEXT_SIZE)

    def restore(self, saved):
        mem.write(self.ctx, saved)
