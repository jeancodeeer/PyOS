# Exceptions, the Windows way (SEH), so C++ `throw` and `catch` work.
#
# On 64-bit Windows the compiler writes, for every function, how its
# prologue changed the stack (.pdata and .xdata in the .exe). To throw, the
# program calls RaiseException; we walk up the stack one function at a time
# with those tables ("unwinding") and ask each function's handler whether
# it catches. The handler that does calls RtlUnwindEx, which unwinds again
# up to that function and resumes the program at its catch block.
#
# A CONTEXT is Windows' structure with every register; here it lives in the
# program's memory because the handlers read and write it.
import struct
from pywin import mem, cpu

CONTEXT_SIZE = 0x4D0
RIP = 0xF8
XMM = 0x1A0
EXCEPTION_NONCONTINUABLE, UNWINDING, EXIT_UNWIND, TARGET_UNWIND = 1, 2, 4, 0x20
EHANDLER, UHANDLER, CHAININFO = 1, 2, 4
STATUS_UNWIND = 0xC0000027


def reg_at(n):
    """Where register n (CPU numbering: rax, rcx, rdx, rbx, rsp...) is in a CONTEXT."""
    return 0x78 + 8 * n


def get(ctx, n):
    return mem.u64(ctx + reg_at(n))


def put(ctx, n, v):
    mem.put64(ctx + reg_at(n), v)


class Resume(Exception):
    """Jump back into the program with the registers of a CONTEXT."""

    def __init__(self, context):
        super().__init__()
        self.context = context          # bytes of a CONTEXT
        self.rsp = struct.unpack_from("<Q", context, reg_at(cpu.RSP))[0]


# ---- between the saved registers and a CONTEXT ----

def capture(p, ctx):
    """The registers of the code that called the Windows function now being handled."""
    s = p.regs
    mem.zero(ctx, CONTEXT_SIZE)
    mem.put32(ctx + 0x30, 0x10001F)                       # ContextFlags: everything
    mem.put32(ctx + 0x34, 0x1F80)                         # MxCsr
    for r in cpu.SLOT:
        put(ctx, r, s.get(r))
    rsp = s.get(cpu.RSP)
    put(ctx, cpu.RSP, rsp + 8)                            # as after the `ret`
    mem.put64(ctx + RIP, mem.u64(rsp))
    for x in cpu.SAVED_XMM:
        mem.write(ctx + XMM + 16 * x, mem.read(s.ctx + cpu.XMM + 16 * x, 16))


def load(p, context):
    """Make the program continue with these registers (from Resume)."""
    s = p.regs
    for r in cpu.SLOT:
        s.set(r, struct.unpack_from("<Q", context, reg_at(r))[0])
    for x in cpu.SAVED_XMM:
        mem.write(s.ctx + cpu.XMM + 16 * x, context[XMM + 16 * x:XMM + 16 * x + 16])
    rsp = struct.unpack_from("<Q", context, reg_at(cpu.RSP))[0]
    rip = struct.unpack_from("<Q", context, RIP)[0]
    mem.put64(rsp - 8, rip)                               # `enter` ends with ret
    s.set(cpu.RSP, rsp - 8)


# ---- the unwind tables ----

def lookup(p, pc):
    """The RUNTIME_FUNCTION entry (start, end, unwind info) covering pc, or None."""
    base = p.base
    if not base <= pc < base + p.image.size:
        return None
    rva, size = p.image.directory(3)                       # the exception directory (.pdata)
    lo, hi = 0, size // 12 - 1
    off = pc - base
    while lo <= hi:                                        # the table is sorted: binary search
        mid = (lo + hi) // 2
        e = base + rva + 12 * mid
        start, end = mem.u32(e), mem.u32(e + 4)
        if off < start:
            hi = mid - 1
        elif off >= end:
            lo = mid + 1
        else:
            return e
    return None


def virtual_unwind(p, kind, pc, entry, ctx):
    """Undo one function's prologue in ctx (now its caller's registers).
    Returns (handler, handler data, establisher frame)."""
    base = p.base
    frame = get(ctx, cpu.RSP)
    handler = data = 0
    first = True
    while True:
        start = mem.u32(entry)
        info = base + mem.u32(entry + 8)
        flags, prolog, count, fr = mem.u8(info) >> 3, mem.u8(info + 1), mem.u8(info + 2), mem.u8(info + 3)
        offset = pc - (base + start) if first else 0xFFFF   # chained parts: whole prologue
        if fr & 15 and first:
            frame = get(ctx, fr & 15) - (fr >> 4) * 16
        codes = info + 4
        i = 0
        while i < count:
            at, op = mem.u8(codes + 2 * i), mem.u8(codes + 2 * i + 1)
            code, opinfo = op & 15, op >> 4
            size = _slots(code, opinfo)
            if not first or offset >= at:              # skip prologue steps not yet run
                _apply(ctx, code, opinfo, codes + 2 * i, frame, fr)
            i += size
        after = codes + 2 * ((count + 1) & ~1)
        if flags & CHAININFO:
            entry = after                                  # continue with the parent's info
            first = False
            continue
        if flags & kind and first:
            handler = base + mem.u32(after)
            data = after + 4
        break
    rsp = get(ctx, cpu.RSP)
    mem.put64(ctx + RIP, mem.u64(rsp))                     # the return address
    put(ctx, cpu.RSP, rsp + 8)
    return handler, data, frame


def _slots(code, opinfo):
    if code == 1:
        return 2 if opinfo == 0 else 3
    return {4: 2, 5: 3, 8: 2, 9: 3}.get(code, 1)


def _apply(ctx, code, opinfo, at, frame, fr):
    rsp = get(ctx, cpu.RSP)
    if code == 0:                                          # push register
        put(ctx, opinfo, mem.u64(rsp))
        put(ctx, cpu.RSP, rsp + 8)
    elif code == 1:                                        # big stack allocation
        n = mem.u16(at + 2) * 8 if opinfo == 0 else mem.u32(at + 2)
        put(ctx, cpu.RSP, rsp + n)
    elif code == 2:                                        # small stack allocation
        put(ctx, cpu.RSP, rsp + opinfo * 8 + 8)
    elif code == 3:                                        # frame pointer set
        put(ctx, cpu.RSP, frame)
    elif code == 4:                                        # register saved with mov
        put(ctx, opinfo, mem.u64(frame + mem.u16(at + 2) * 8))
    elif code == 5:
        put(ctx, opinfo, mem.u64(frame + mem.u32(at + 2)))
    elif code == 8:                                        # XMM register saved
        mem.write(ctx + XMM + 16 * opinfo, mem.read(frame + mem.u16(at + 2) * 16, 16))
    elif code == 9:
        mem.write(ctx + XMM + 16 * opinfo, mem.read(frame + mem.u32(at + 2), 16))
    elif code == 10:                                       # interrupt frame
        top = rsp + (8 if opinfo else 0)
        mem.put64(ctx + RIP, mem.u64(top))
        put(ctx, cpu.RSP, mem.u64(top + 24))


def step(p, ctx, kind):
    """Move ctx one function up. Returns (handler, data, frame, entry) or None at the top."""
    pc = mem.u64(ctx + RIP)
    entry = lookup(p, pc)
    if entry is None:
        rsp = get(ctx, cpu.RSP)
        if not p.base <= pc < p.base + p.image.size:
            return None                                    # left the program: the top
        mem.put64(ctx + RIP, mem.u64(rsp))                 # a leaf function: just `ret`
        put(ctx, cpu.RSP, rsp + 8)
        return 0, 0, rsp, 0
    handler, data, frame = virtual_unwind(p, kind, pc, entry, ctx)
    return handler, data, frame, entry


def _dispatcher(d, p, pc, entry, frame, ctx, handler, data, target=0):
    """Fill a DISPATCHER_CONTEXT, what a handler gets to know where it is."""
    for k, v in enumerate((pc, p.base, entry, frame, target, ctx, handler, data, 0)):
        mem.put64(d + 8 * k, v)


# ---- the three functions kernel32/ntdll offer ----

def raise_exception(p, code, flags, nargs, args):
    record = p.heap.alloc(160)                             # freed with the process
    mem.put32(record, code)
    mem.put32(record + 4, flags)
    nargs = min(nargs, 15)
    mem.put32(record + 24, nargs)
    if nargs:
        mem.write(record + 32, mem.read(args, 8 * nargs))
    ctx = p.heap.alloc(CONTEXT_SIZE)
    capture(p, ctx)
    mem.put64(record + 16, mem.u64(ctx + RIP))             # ExceptionAddress
    dispatch(p, record, ctx)


def dispatch(p, record, ctx):
    """First pass: find a handler that takes the exception."""
    p.state.setdefault("seh", []).append((record, ctx))
    walk = p.heap.alloc(CONTEXT_SIZE)
    here = p.heap.alloc(CONTEXT_SIZE)
    d = p.heap.alloc(80)
    mem.write(walk, mem.read(ctx, CONTEXT_SIZE))
    try:
        for _ in range(1000):
            pc = mem.u64(walk + RIP)
            mem.write(here, mem.read(walk, CONTEXT_SIZE))
            found = step(p, walk, EHANDLER)
            if found is None:
                break
            handler, data, frame, entry = found
            if handler:
                _dispatcher(d, p, pc, entry, frame, here, handler, data)
                r = p.call(handler, record, frame, here, d)
                if r == 0:                                 # ExceptionContinueExecution
                    return
    finally:
        p.state["seh"].pop()
        for block in (walk, here, d):
            p.heap.free(block)
    from pywin.process import Exit
    p.ui.write("\nPyWin: excepcion no controlada %#x\n" % mem.u32(record))
    raise Exit(mem.u32(record))


def unwind(p, target_frame, target_ip, record, value, original):
    """RtlUnwindEx: run the clean-ups up to target_frame and continue at target_ip."""
    if not record:
        record = p.heap.alloc(160)
        mem.put32(record, STATUS_UNWIND)
    flags = mem.u32(record + 4) | UNWINDING
    active = p.state.get("seh")
    ctx = p.state.get("unwind_ctx")
    if ctx is None:                                        # kept: unwinding never returns to free it
        ctx = p.state["unwind_ctx"] = p.heap.alloc(CONTEXT_SIZE)
        p.state["unwind_here"] = p.heap.alloc(CONTEXT_SIZE)
        p.state["unwind_d"] = p.heap.alloc(80)
    here, d = p.state["unwind_here"], p.state["unwind_d"]
    if active:
        mem.write(ctx, mem.read(active[-1][1], CONTEXT_SIZE))   # from where it was thrown
    else:
        capture(p, ctx)
    for _ in range(1000):
        pc = mem.u64(ctx + RIP)
        before = mem.read(ctx, CONTEXT_SIZE)
        found = step(p, ctx, UHANDLER)
        if found is None:
            break
        handler, data, frame, entry = found
        last = frame == target_frame
        if handler:
            mem.put32(record + 4, flags | (TARGET_UNWIND if last else 0))
            mem.write(here, before)
            _dispatcher(d, p, pc, entry, frame, here, handler, data, target_ip)
            p.call(handler, record, frame, here, d)
            before = mem.read(here, CONTEXT_SIZE)          # the handler may change registers
        if last:
            out = bytearray(before)
            struct.pack_into("<Q", out, reg_at(cpu.RAX), value)
            struct.pack_into("<Q", out, RIP, target_ip)
            raise Resume(bytes(out))
    from pywin.process import Exit
    p.ui.write("\nPyWin: no se encontro el marco de la excepcion\n")
    raise Exit(0xC0000027)
