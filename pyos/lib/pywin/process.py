# A running Windows program.
#
#   p = Process("/disk/hola.exe", ["uno", "dos"])
#   code = p.run()
#
# What happens:
#   1. the .exe is copied into memory and its pointers fixed (pe.py)
#   2. every function it imports gets a thunk (cpu.py) bound to the Python
#      code that implements it (dlls/kernel32.py, dlls/msvcrt.py...)
#   3. a stack and the TEB/PEB (the blocks Windows code finds through the
#      GS register) are made, and the program starts at its entry point
#   4. each time the program calls Windows, Python runs the function and
#      the program continues, until it calls ExitProcess or returns.
#
# Threads (CreateThread) are real: each one is a Python thread with its own
# registers, stack and TEB. Only one of them runs program code at a time
# (the GS register belongs to the processor), but they take turns at every
# Windows call, and while one waits (Sleep, GetMessage...) the others run.
import struct
import _thread
import _kernel
import time
from kernel import mm
from pywin import cpu, mem, pe, dlls, seh
from pywin.heap import Heap
from pywin.cpu import RAX, RCX, RDX, R8, R9, RSP

GS_BASE = 0xC0000101
STACK = 1 << 20
_native = _thread.allocate_lock()     # one program on the CPU at a time (GS is per CPU)


class Exit(Exception):
    """ExitProcess(), exit() or the program's main() returned."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class ThreadExit(Exception):
    """ExitThread(): only this thread ends."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Thread:
    """One thread of the program: registers, stack and TEB of its own."""
    STILL_ACTIVE = 0x103

    def __init__(self, p, tid, stack_size=STACK):
        self.id = tid
        self.regs = cpu.Registers(p.heap)
        self.pages = max(16, (stack_size + 4095) // 4096)
        self.stack = mm.alloc_contiguous(self.pages)
        top = self.stack + self.pages * 4096
        self.regs.set(RSP, top - 64)
        self.code = Thread.STILL_ACTIVE
        self.done = False
        teb = self.teb = p.heap.alloc(0x2000)
        mem.put64(teb + 0x08, top)                           # stack top
        mem.put64(teb + 0x10, self.stack)                    # stack bottom
        mem.put64(teb + 0x30, teb)                           # pointer to itself
        mem.put64(teb + 0x40, 4)                             # process id
        mem.put64(teb + 0x48, tid)                           # thread id
        mem.put64(teb + 0x60, p.peb)
        if p.tls_template:                                   # this thread's copy of the TLS data
            start, size, fill = p.tls_template
            block = p.heap.alloc(size + fill + 16)
            mem.write(block, mem.read(start, size))
            slots = p.heap.alloc(64 * 8)
            mem.put64(slots, block)
            mem.put64(teb + 0x58, slots)

    def wait(self, ms=None):
        """Wait until the thread ends (or ms pass). True if it ended."""
        import time
        start = time.ticks_ms()
        while not self.done:
            if ms is not None and time.ticks_diff(time.ticks_ms(), start) >= ms:
                return False
            time.sleep_ms(2)
        return True

    def close(self):
        pass


class Console:
    """Where a program's text goes when it runs from the PyKernel prompt."""

    def write(self, text):
        print(text, end="")

    def read_line(self):
        try:
            return input() + "\n"
        except EOFError:
            return ""

    def message_box(self, text, caption, flags):
        print("\n[%s] %s\n" % (caption, text))
        return 1                                    # IDOK

    def title(self, text):
        pass

    def wait(self, ms):
        import time
        time.sleep_ms(ms or 1)

    def open_window(self, wnd):
        raise RuntimeError("este programa abre ventanas: ejecutalo desde el escritorio "
                           "(doble clic en el .exe, o la app PyWin)")

    def close_window(self, wnd):
        pass

    resize_window = title_window = close_window

    def ask_path(self, title, default, save):
        try:
            return input("%s [%s]: " % (title, default)).strip() or default
        except EOFError:
            return None

    def choose(self, caption, text, options):
        return 0 if options else None             # no one to ask: the first choice

    def popup_menu(self, menu, pos):
        return 0

    def open_url(self, url):
        print("[abrir] %s" % url)

    open_path = open_url

    def color(self, attr):
        # the PyKernel console understands ANSI colours
        fg = attr & 15
        code = (30 + [0, 4, 2, 6, 1, 5, 3, 7][fg & 7]) + (60 if fg & 8 else 0)
        print("\x1b[%dm" % code, end="")


class Module:
    """A DLL that came with the program (a real .dll file, run natively)."""

    def __init__(self, name, path, image, base, phys, pages):
        self.name, self.path, self.image = name, path, image
        self.base, self.phys, self.pages = base, phys, pages
        self.exports = {}
        self.ready = False              # DllMain called


class Process:
    def __init__(self, path, args=(), ui=None, cwd=None):
        self.image = pe.Image(pe.read_file(path))
        self.path = path
        self.cwd = cwd or (path.rsplit("/", 1)[0] or "/")
        self.argv = [to_windows(path)] + [str(a) for a in args]
        self.ui = ui or Console()
        self.heap = Heap()
        self.code = cpu.Switch()
        self.threads = {}           # Python thread id -> Thread
        self.all_threads = []
        self.next_tid = 8
        self.exit_request = None    # exit code asked by a thread other than the main one
        self.handlers = {}          # thunk number -> (function, number of arguments, "dll!name")
        self.bound = {}             # (dll, name) -> address given to the program
        self.handles = {}           # Windows handles -> Python objects
        self.calls = {}             # "dll!function" -> how many times the program called it
        self.recent = []            # the last Windows functions called (to see where a program is)
        self.spent = {}             # "dll!function" -> microseconds spent in it (Python side)
        self.timing = [0, 0, 0, 0]  # microseconds: waiting for the native lock, in native code,
        #                             sleeping to share the CPU, in _dispatch (all of it)
        self.next_handle = 0x100
        self.last_error = 0
        self.exit_code = None
        self.killed = False         # set by the desktop to stop the program
        self.last_yield = 0
        self.warned = set()
        self.state = {}             # each DLL keeps its own things here
        self.modules = {}           # fake module handles -> DLL name (DLLs written in Python)
        self.libraries = {}         # lower-case name -> Module (DLLs loaded from files)
        self.load_order = []
        self._ret = self._thunk(None, 0, "return")[0]
        self._load()

    # ---- loading ----
    @staticmethod
    def _place(img):
        """Memory for an image: (address it runs at, physical address, pages)."""
        pages = (img.size + 4095) // 4096
        phys = mm.alloc_contiguous(pages)
        if img.can_move():
            base = phys
        else:                                       # it must sit at its own address
            base = img.image_base
            for k in range(pages):
                mm.map_page(base + k * 4096, phys + k * 4096)
        img.load(base)
        img.data = b""                              # the file's bytes are in place now: free them
        more_heap(16 << 20 if img.size > (4 << 20) else 4 << 20)   # a big program has a big window tree
        return base, phys, pages

    def _load(self):
        img = self.image
        self.base, self.phys, self.image_pages = self._place(img)
        self.peb = self.heap.alloc(0x400)
        mem.put64(self.peb + 0x10, self.base)                # the program's address
        mem.put64(self.peb + 0x30, 0x11110000)               # "process heap" handle
        tls = self.image.tls(self.base)
        self.tls_template, self.tls_callbacks = None, 0
        if tls:
            start, end, index_at, self.tls_callbacks, fill = tls
            self.tls_template = (start, end - start, fill)
            if index_at:
                mem.put32(index_at, 0)
        self.main = self.new_thread()
        for dll, name, slot in img.imports(self.base):
            mem.put64(slot, self.resolve(dll, name))

    def new_thread(self, stack_size=STACK):
        t = Thread(self, self.next_tid, stack_size or STACK)
        self.next_tid += 4
        self.all_threads.append(t)
        return t

    def thread(self):
        """The Thread running this Python code."""
        return self.threads.get(_thread.get_ident(), self.main)

    @property
    def regs(self):
        return self.thread().regs

    def start_thread_call(self, fn, args):
        """Run fn(*args) of the program in a new thread (thread pool work)."""
        return self.start_thread(fn, None, 0, args)

    def start_thread(self, fn, param, stack_size=0, args=None):
        """CreateThread: run fn(param) of the program in a new thread."""
        t = self.new_thread(stack_size)

        def body():
            self.threads[_thread.get_ident()] = t
            try:
                self._tls_callbacks(2)                       # DLL_THREAD_ATTACH
                t.code = self.call(fn, *(args if args is not None else (param,))) & 0xFFFFFFFF
            except ThreadExit as e:
                t.code = e.code & 0xFFFFFFFF
            except Exit as e:                                 # ExitProcess from this thread
                t.code = e.code & 0xFFFFFFFF
                if self.exit_request is None:
                    self.exit_request = t.code
                self.killed = True
            except Exception as e:
                self.ui.write("\nPyWin: un hilo se ha detenido: %s\n" % self.explain(e))
                t.code = 0xC0000005
            finally:
                t.done = True
                self.threads.pop(_thread.get_ident(), None)
        try:
            _thread.stack_size(32 * 1024)
        except Exception:
            pass
        _thread.start_new_thread(body, ())
        return t

    def _tls_callbacks(self, reason):
        at = self.tls_callbacks
        while at and mem.u64(at):
            self.call(mem.u64(at), self.base, reason, 0)
            at += 8

    def _thunk(self, fn, nargs, label):
        n, addr = self.code.new_thunk()
        self.handlers[n] = (fn, nargs, label)
        return n, addr

    def resolve(self, dll, name):
        """The address the program should call for dll!name."""
        key = (dlls.base_name(dll), name)
        if key in self.bound:
            return self.bound[key]
        found = dlls.find(dll, name)
        if found is None and dlls.module(dll) is None:
            lib = self.load_library(dll)                 # a DLL that came with the program?
            if lib is not None:
                addr = lib.exports.get(name)
                if isinstance(addr, str):                # forwarded to another DLL
                    fdll, fname = addr.split(".", 1)
                    addr = self.resolve(fdll + ".dll", fname)
                if addr:
                    self.bound[key] = addr
                    return addr
        if found is None:
            addr = self._thunk(None, 0, "%s!%s" % key)[1]
        elif found[0] == "data":                          # a variable, not a function
            addr = self.heap.alloc(max(16, found[1]))
            mem.put64(addr, found[2])
        else:
            addr = self._thunk(found[0], found[1], "%s!%s" % key)[1]
        self.bound[key] = addr
        return addr

    # ---- DLLs that come with the program ----
    def find_library(self, name):
        """A .dll file: where the name says (a full path), else next to the
        program, in the current folder or in /disk/pywin/system32 (Windows
        names ignore upper/lower case)."""
        import os
        if "\\" in name or "/" in name:                     # a path: that very file
            try:
                path = self.host_path(name if name.lower().endswith(".dll") else name + ".dll")
                folder, _, wanted = path.rpartition("/")
                for entry in os.listdir(folder or "/"):
                    if entry.lower() == wanted.lower():
                        return (folder or "") + "/" + entry
            except OSError:
                pass
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        if not name.lower().endswith(".dll"):
            name += ".dll"
        for folder in (self.path.rsplit("/", 1)[0] or "/", self.cwd, "/disk/pywin/system32"):
            try:
                for entry in os.listdir(folder):
                    if entry.lower() == name.lower():
                        return folder.rstrip("/") + "/" + entry
            except OSError:
                pass
        return None

    def load_library(self, name, init_now=False):
        """Load a DLL file: place it, link it, and (now or at start) call DllMain."""
        key = dlls.base_name(name.replace("\\", "/").rsplit("/", 1)[-1])
        if key in self.libraries:
            return self.libraries[key]
        path = self.find_library(name)
        if path is None:
            return None
        img = pe.Image(pe.read_file(path))
        base, phys, pages = self._place(img)
        lib = Module(key, path, img, base, phys, pages)
        self.libraries[key] = lib                        # before its imports: DLLs may need each other
        lib.exports = img.exports(base)
        for dll, fname, slot in img.imports(base):
            mem.put64(slot, self.resolve(dll, fname))
        self.load_order.append(lib)                      # after the DLLs it needs
        if init_now:
            self.init_libraries()
        return lib

    def init_libraries(self):
        """Call DllMain(DLL_PROCESS_ATTACH) of the DLLs not started yet."""
        for lib in self.load_order:
            if not lib.ready:
                lib.ready = True
                if lib.image.entry:
                    self.call(lib.base + lib.image.entry, lib.base, 1, 0)

    def image_name(self):
        return dlls.base_name(self.path.rsplit("/", 1)[-1])

    def module_at(self, handle):
        """The image whose module handle (base address) this is."""
        if not handle or handle == self.base:
            return self.image, self.base
        for lib in self.libraries.values():
            if lib.base == handle:
                return lib.image, lib.base
        return None, None

    def resource(self, handle, kind, name):
        img, base = self.module_at(handle)
        return img.resource(base, kind, name) if img is not None else None

    # ---- running ----
    def run(self):
        code = -1
        self.threads[_thread.get_ident()] = self.main
        try:
            self.init_libraries()                            # the program's own DLLs first
            self._tls_callbacks(1)                           # DLL_PROCESS_ATTACH
            code = self.call(self.base + self.image.entry, self.peb) & 0xFFFFFFFF
            dlls.run_atexit(self)
        except Exit as e:
            code = e.code & 0xFFFFFFFF
        except Exception as e:
            self.ui.write("\nPyWin: el programa se ha detenido: %s\n" % self.explain(e))
            self.log_exception(e)
            code = 0xC0000005
        finally:
            self.main.done = True
            self.killed = True                               # the other threads stop too
            for t in self.all_threads:
                t.wait(2000)
            self.threads.pop(_thread.get_ident(), None)
            self.close()
        self.exit_code = code
        return code

    def log_exception(self, e):
        """The Python side of a failure, in the system log (for whoever fixes PyWin)."""
        try:
            import io
            import sys
            from kernel import log
            buf = io.StringIO()
            sys.print_exception(e, buf)
            log.error("pywin: " + buf.getvalue().strip().replace("\n", " | "))
            _debug(buf.getvalue())
        except Exception:
            pass

    def explain(self, e):
        args = getattr(e, "args", ())
        if len(args) >= 3 and isinstance(args[2], int):
            rip = args[2]
            where = ("en %s+%#x" % (self.path.rsplit("/", 1)[-1], rip - self.base)
                     if self.base <= rip < self.base + self.image.size else "en %#x" % rip)
            return "%s %s" % (e, where)
        return repr(e)

    def _native(self):
        """Run the program until it calls a thunk; returns that thunk's number."""
        t = self.thread()
        t0 = time.ticks_us()
        with _native:
            t1 = time.ticks_us()
            self.code.use(t.regs)
            old = _kernel.rdmsr(GS_BASE)
            _kernel.wrmsr(GS_BASE, t.teb)
            try:
                return _kernel.call(self.code.base)
            finally:
                _kernel.wrmsr(GS_BASE, old)
                t2 = time.ticks_us()
                self.timing[0] += time.ticks_diff(t1, t0)          # waiting for another thread
                self.timing[1] += time.ticks_diff(t2, t1)          # running the program's own code

    def call(self, addr, *args):
        """Call a function inside the program and return what it returns.
        Python can do this at any moment, even while handling a Windows call
        (callbacks like window procedures or qsort comparisons).
        Only from one of the program's own threads: each has its registers,
        and code run from another thread (the desktop's) would overwrite them."""
        if _thread.get_ident() not in self.threads:
            raise RuntimeError("PyWin: program code called from a thread that is not the program's")
        s = self.regs
        saved = s.save()
        rsp = (s.get(RSP) - 256) & ~15                       # below whatever is on the stack
        extra = args[4:]
        frame = ((rsp - 8 - 32 - 8 * len(extra)) & ~15) - 8  # 8 mod 16, as after a `call`
        mem.put64(frame, self.code.thunk_base + self._ret * cpu.THUNK_SIZE)     # where it returns
        for k, v in enumerate(extra):
            mem.put64(frame + 0x28 + 8 * k, v)
        mem.put64(frame - 8, addr)                           # `enter` ends with ret -> addr
        s.set(RSP, frame - 8)
        for reg, v in zip((RCX, RDX, R8, R9), args):
            s.set(reg, v)
        try:
            while True:
                try:
                    n = self._native()
                    if n == self._ret:
                        return s.get(RAX)
                    t0 = time.ticks_us()
                    self._dispatch(n)
                    self.timing[3] += time.ticks_diff(time.ticks_us(), t0)
                except seh.Resume as r:          # a C++ catch block in this part of the stack
                    if r.rsp >= frame:
                        raise
                    seh.load(self, r.context)
        finally:
            s.restore(saved)

    def _dispatch(self, n):
        if self.killed:
            raise Exit(self.exit_request if self.exit_request is not None else 1)
        self._share_cpu()
        fn, nargs, label = self.handlers[n]
        self.calls[label] = self.calls.get(label, 0) + 1        # for `stats()`: what the program uses most
        recent = self.recent
        recent.append(label)
        if len(recent) > 64:
            del recent[:32]
        s = self.regs
        if _trace_on():
            _debug("%s(%s)" % (label, ", ".join(_show(self.arg(i)) for i in range(min(nargs, 6)))))
        t0 = time.ticks_us()
        if fn is None:
            self.warn("falta %s (devuelve 0)" % label)
            result = 0
        else:
            result = fn(self, *[self.arg(i) for i in range(nargs)])
        self.spent[label] = self.spent.get(label, 0) + time.ticks_diff(time.ticks_us(), t0)
        if isinstance(result, float):
            s.set_double(0, result)
            result = 0
        s.set(RAX, int(result or 0))     # `enter` then returns to the program's call

    def _share_cpu(self):
        """Program code keeps Python's turn while it runs. Every 25 ms of it,
        sleep a moment at a Windows call so the desktop (and the mouse and
        the keyboard) can get on with their work."""
        import time
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_yield) >= 25:
            t0 = time.ticks_us()
            time.sleep_ms(6)
            self.last_yield = time.ticks_ms()
            self.timing[2] += time.ticks_diff(time.ticks_us(), t0)

    # ---- helpers for the DLLs ----
    def arg(self, i):
        """Argument i of the Windows call being handled (Windows x64 rules)."""
        if i < 4:
            return self.regs.get((RCX, RDX, R8, R9)[i])
        return mem.u64(self.regs.get(RSP) + 8 + 8 * i)

    def arg_double(self, i):
        """Argument i when it is a double: in XMM i, or on the stack after the 4th."""
        if i < 4:
            return self.regs.get_double(i)
        return struct.unpack("<d", mem.read(self.regs.get(RSP) + 8 + 8 * i, 8))[0]

    def arg_float(self, i):
        """Argument i when it is a float (32 bits)."""
        if i < 4:
            return self.regs.get_float(i)
        return struct.unpack("<f", mem.read(self.regs.get(RSP) + 8 + 8 * i, 4))[0]

    def new_handle(self, obj):
        h = self.next_handle
        self.next_handle += 4
        self.handles[h] = obj
        return h

    def stats(self, top=20):
        """The Windows functions called most, and the last ones: where is the program?"""
        most = sorted(self.calls.items(), key=lambda kv: -kv[1])[:top]
        slow = sorted(((k, v // 1000) for k, v in self.spent.items()), key=lambda kv: -kv[1])[:top]
        return {"most": most, "slow_ms": slow, "last": self.recent[-24:], "total": sum(self.calls.values()),
                "python_ms": sum(self.spent.values()) // 1000, "lock_wait_ms": self.timing[0] // 1000,
                "native_ms": self.timing[1] // 1000, "sleep_ms": self.timing[2] // 1000,
                "dispatch_ms": self.timing[3] // 1000, "threads": len(self.threads)}

    def warn(self, text):
        """Say once that something is missing: in the console, or in the system log."""
        if text not in self.warned:
            self.warned.add(text)
            try:
                from kernel import log
                log.info("pywin: %s: %s" % (self.path.rsplit("/", 1)[-1], text))
            except Exception:
                pass
            if self.image.console:
                self.ui.write("PyWin: %s\n" % text)
            _debug(text)

    def host_path(self, path, write=False):
        """The SnakeyOS path for a Windows path, if this program may use it
        (else OSError 13, "access denied"; see allowed() below)."""
        host = to_host(path, self.cwd)
        if not allowed(host, write):
            self.warn("acceso denegado: %s %s" % ("escribir" if write else "leer", host))
            raise OSError(13, "acceso denegado: " + host)
        return host

    def close(self):
        if self.code is None:
            return
        for obj in self.handles.values():
            try:
                obj.close()
            except Exception:
                pass
        self.heap.destroy()
        self.code.free()
        self.code = None
        for t in self.all_threads:
            mm.free_contiguous(t.stack, t.pages)
        for base, phys, pages in [(self.base, self.phys, self.image_pages)] + \
                [(m.base, m.phys, m.pages) for m in self.libraries.values()]:
            if base != phys:
                for k in range(pages):
                    mm.unmap_page(base + k * 4096)
            mm.free_contiguous(phys, pages)


def _show(v):
    """An argument for the trace: a number, or the text it points to."""
    if 0x100000 < v < 0x100000000:
        try:
            raw = mem.read(v, 64)
            if raw[1] == 0 and 32 <= raw[0] < 127 and raw[3] == 0:       # UTF-16 text
                s = mem.wstr(v, 60)
                if s and all(32 <= ord(c) < 0x3000 for c in s):
                    return repr(s)
            if all(32 <= b < 127 for b in raw[:4]):                       # 8-bit text
                s = mem.cbytes(v, 60)
                if s and all(32 <= b < 127 for b in s):
                    return repr(s.decode())
        except Exception:
            pass
    return "%#x" % v


def _trace_on():
    import pywin
    return getattr(pywin, "DEBUG", 0) == 2


def _debug(text):
    """With pywin.DEBUG on, notes also go out of the serial port (for developers)."""
    import pywin
    if getattr(pywin, "DEBUG", False):
        _kernel.serial_write(("[pywin] %s\n" % text).encode())


# ---- paths: C:\ is the SnakeyOS disk (/disk), Z:\ is the whole file system ----

# What a Windows program may touch. It runs with the user's files (C: is
# /disk) and may read the rest of the system (Z:), but it must not be able to
# change the system, install Python apps (they run with full power), read
# the accounts and passwords, or write to a raw disk.
NO_ACCESS = ("/disk/etc", "/dev")                 # not even to read
WRITABLE = ("/disk", "/tmp")                      # writing only in here...
READ_ONLY = ("/disk/apps", "/disk/etc")           # ...but not in these
DEVICES_OK = ("/dev/null",)


def _under(path, folders):
    return any(path == f or path.startswith(f + "/") for f in folders)


def allowed(path, write=False):
    # the disk (FAT) ignores upper/lower case and Windows drops dots and spaces
    # at the end of a name, so "/DISK/Etc./passwd" must count as /disk/etc
    path = "/".join(part.rstrip(". ").lower() if part not in (".", "..") else part for part in path.split("/"))
    if path in DEVICES_OK:
        return True
    if _under(path, NO_ACCESS):
        return False
    if write:
        return _under(path, WRITABLE) and not _under(path, READ_ONLY)
    return True


def more_heap(want):
    """Make sure `want` bytes are free in the Python heap, moving free RAM
    into it if needed (big programs need many window pictures and handles).
    The machine always keeps 96 MiB for drivers and the programs' own memory."""
    import gc
    try:
        from kernel import mm
    except ImportError:
        return
    gc.collect()
    while gc.mem_free() < want and mm.free_bytes() > (96 << 20):
        try:
            if not mm.grow_heap(16):
                return                     # the heap grows from its reserve by itself
        except (MemoryError, AttributeError):
            return


def heap_area_for(nbytes):
    """After a MemoryError: the heap may have enough free bytes in total but
    no single free piece that big. Add a fresh area of RAM where it fits."""
    try:
        from kernel import mm
        if mm.free_bytes() > (96 << 20):
            mm.grow_heap(max(16, (2 * nbytes >> 20) + 1), force=True)
            return True
    except (ImportError, MemoryError, AttributeError):
        pass
    return False


def to_host(path, cwd="/"):
    if path.upper() in ("NUL", "NUL:", "\\\\.\\NUL"):
        return "/dev/null"
    if path.startswith("\\\\.\\") or path.startswith("\\\\?\\GLOBALROOT"):
        return "/dev/" + path[4:].replace("\\", "/")     # a raw Windows device: refused by allowed()
    if path.startswith("\\\\?\\"):
        path = path[4:]                                   # long-path prefix: an ordinary path follows
    p = path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        drive, p = p[0].upper(), p[2:]
        root = "/disk" if drive == "C" else ""
        p = root + "/" + p.lstrip("/")
    elif not p.startswith("/"):
        p = cwd.rstrip("/") + "/" + p
    parts = []
    for part in p.split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part and part != ".":
            parts.append(part)
    return "/" + "/".join(parts)


def to_windows(path):
    if path.startswith("/disk/") or path == "/disk":
        return "C:" + (path[5:] or "/").replace("/", "\\")
    return "Z:" + path.replace("/", "\\")
