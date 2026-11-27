# kernel32.dll: processes, memory, files, the console, time.
import time
from pywin import mem, seh
from pywin.dlls import Dll

dll = Dll("kernel32")

STD_INPUT, STD_OUTPUT, STD_ERROR = -10, -11, -12
INVALID = 0xFFFFFFFFFFFFFFFF
ERROR_FILE_NOT_FOUND, ERROR_INVALID_HANDLE, ERROR_NO_MORE_FILES = 2, 6, 18
_start = time.ticks_ms()


def _i32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


# ---- what a handle can be ----

class ConsoleOut:
    def __init__(self, p):
        self.p = p

    def write(self, data):
        self.p.ui.write(_text(data))
        return len(data)

    def close(self):
        pass


class ConsoleIn:
    def __init__(self, p):
        self.p = p
        self.pending = b""

    def read(self, n):
        if not self.pending:
            self.pending = self.p.ui.read_line().replace("\n", "\r\n").encode()
        data, self.pending = self.pending[:n], self.pending[n:]
        return data

    def close(self):
        pass


class HostFile:
    """A file of the SnakeyOS file system, opened by a Windows program."""

    def __init__(self, path, mode):
        self.f = open(path, mode)
        self.path = path

    def read(self, n):
        return self.f.read(n)

    def write(self, data):
        return self.f.write(data)

    def seek(self, offset, whence):
        return self.f.seek(offset, whence)

    def size(self):
        here = self.f.tell()
        end = self.f.seek(0, 2)
        self.f.seek(here)
        return end

    def close(self):
        self.f.close()


def _text(data):
    try:
        return data.decode()
    except UnicodeError:
        return "".join(chr(b) for b in data)


def std(p, which):
    """The console handles, made the first time they are asked for."""
    key = "std%d" % which
    if key not in p.state:
        obj = ConsoleIn(p) if which == STD_INPUT else ConsoleOut(p)
        p.state[key] = p.new_handle(obj)
    return p.state[key]


def _obj(p, h):
    return p.handles.get(h)


# ---- the process ----

@dll(1)
def ExitProcess(p, code):
    from pywin.process import Exit
    from pywin import dlls
    dlls.run_atexit(p)
    raise Exit(code)


@dll(2)
def TerminateProcess(p, handle, code):
    from pywin.process import Exit
    raise Exit(code)


@dll(0)
def GetCommandLineA(p):
    if "cmdline" not in p.state:
        line = " ".join('"%s"' % a if " " in a else a for a in p.argv)
        p.state["cmdline"] = p.heap.alloc(len(line) * 2 + 4)
        p.state["cmdlinew"] = p.heap.alloc(len(line) * 2 + 4)
        mem.put_cstr(p.state["cmdline"], line)
        mem.put_wstr(p.state["cmdlinew"], line)
    return p.state["cmdline"]


@dll(0)
def GetCommandLineW(p):
    GetCommandLineA(p)
    return p.state["cmdlinew"]


@dll(0)
def GetCurrentProcess(p):
    return INVALID                      # the pseudo-handle -1


@dll(0)
def GetCurrentThread(p):
    return INVALID - 1


@dll(0)
def GetCurrentProcessId(p):
    return 4


@dll(1)
def GetModuleHandleA(p, name):
    return _module(p, mem.cstr(name), False) if name else p.base


@dll(1)
def GetModuleHandleW(p, name):
    return _module(p, mem.wstr(name), False) if name else p.base


def _module(p, name, load):
    """A module handle: a DLL file of the program (its address), or one of
    PyWin's Python DLLs (a made-up number)."""
    from pywin import dlls
    base = dlls.base_name(name.replace("\\", "/").rsplit("/", 1)[-1])
    if p.image_name() == base:
        return p.base
    if dlls.module(base) is None:
        lib = p.libraries.get(base) or (p.load_library(name, init_now=True) if load else None)
        if lib is None:
            p.last_error = 126                              # ERROR_MOD_NOT_FOUND
            return 0
        return lib.base
    for h, n in p.modules.items():
        if n == base:
            return h
    h = 0x7FF000000000 + len(p.modules) * 0x100000      # a handle, never read as memory
    p.modules[h] = base
    return h


@dll(1)
def LoadLibraryA(p, name):
    return _module(p, mem.cstr(name), True)


@dll(1)
def LoadLibraryW(p, name):
    return _module(p, mem.wstr(name), True)


@dll(3)
def LoadLibraryExA(p, name, file, flags):
    return _module(p, mem.cstr(name), True)


@dll(3)
def LoadLibraryExW(p, name, file, flags):
    return _module(p, mem.wstr(name), True)


@dll(1)
def FreeLibrary(p, h):
    return 1


@dll(2)
def GetProcAddress(p, module, name):
    fn = ("#%d" % name) if name < 0x10000 else mem.cstr(name)
    if not module or module == p.base:
        return 0
    for lib in p.libraries.values():                    # a real DLL: its export table
        if lib.base == module:
            addr = lib.exports.get(fn)
            if isinstance(addr, str):
                fdll, fname = addr.split(".", 1)
                return p.resolve(fdll + ".dll", fname)
            if not addr:
                p.last_error = 127                      # ERROR_PROC_NOT_FOUND
            return addr or 0
    dll_name = p.modules.get(module)
    if dll_name is None:
        return 0
    from pywin import dlls
    if dlls.find(dll_name, fn) is None:
        p.last_error = 127
        return 0
    return p.resolve(dll_name, fn)


def _file_name(p, module):
    for lib in p.libraries.values():
        if lib.base == module:
            from pywin.process import to_windows
            return to_windows(lib.path)
    return p.argv[0]


@dll(3)
def GetModuleFileNameA(p, module, buf, size):
    name = _file_name(p, module)[:size - 1]
    mem.put_cstr(buf, name)
    return len(name)


@dll(3)
def GetModuleFileNameW(p, module, buf, size):
    name = _file_name(p, module)[:size - 1]
    mem.put_wstr(buf, name)
    return len(name)


@dll(1)
def DisableThreadLibraryCalls(p, module):
    return 1


@dll(3)
def FindResourceA(p, module, name, kind):
    def key(v):
        return v if v < 0x10000 else mem.cstr(v)
    found = p.resource(module or p.base, key(kind), key(name))
    if not found:
        return 0
    return p.new_handle(found)


@dll(3)
def FindResourceW(p, module, name, kind):
    def key(v):
        return v if v < 0x10000 else mem.wstr(v)
    found = p.resource(module or p.base, key(kind), key(name))
    if not found:
        return 0
    return p.new_handle(found)


@dll(4)
def FindResourceExW(p, module, kind, name, language):
    return FindResourceW(p, module, name, kind)            # the same, with kind before name


@dll(2)
def LoadResource(p, module, res):
    found = p.handles.get(res)
    return found[0] if isinstance(found, tuple) else 0


@dll(2)
def SizeofResource(p, module, res):
    found = p.handles.get(res)
    return found[1] if isinstance(found, tuple) else 0


@dll(1)
def LockResource(p, data):
    return data


@dll(1)
def GetStartupInfoA(p, info):
    mem.zero(info, 104)
    mem.put32(info, 104)


dll.alias("GetStartupInfoW", "GetStartupInfoA")


@dll(1)
def SetUnhandledExceptionFilter(p, fn):
    return 0


@dll(1)
def UnhandledExceptionFilter(p, info):
    return 1


@dll(0)
def IsDebuggerPresent(p):
    return 0


@dll(1)
def IsProcessorFeaturePresent(p, feature):
    return 1 if feature in (6, 7, 10, 17) else 0        # SSE, SSE2...


@dll(0)
def GetLastError(p):
    return p.last_error


@dll(1)
def SetLastError(p, code):
    p.last_error = code


@dll(0)
def GetVersion(p):
    return (19041 << 16) | (0 << 8) | 10         # Windows 10


@dll(1)
def GetVersionExA(p, info):
    mem.put32(info + 4, 10)
    mem.put32(info + 8, 0)
    mem.put32(info + 12, 19041)
    mem.put32(info + 16, 2)
    return 1


dll.alias("GetVersionExW", "GetVersionExA")


@dll(1)
def GetSystemInfo(p, info):
    mem.zero(info, 48)
    mem.put32(info + 4, 4096)                    # page size
    mem.put64(info + 8, 0x10000)
    mem.put64(info + 16, 0x7FFFFFFEFFFF)
    mem.put32(info + 32, 1)                      # processors
    mem.put32(info + 40, 0x10000)                # allocation granularity


dll.alias("GetNativeSystemInfo", "GetSystemInfo")


@dll(0)
def GetACP(p):
    return 65001                                 # UTF-8


dll.alias("GetOEMCP", "GetACP")


@dll(2)
def IsDBCSLeadByteEx(p, cp, byte):
    return 0


@dll(1)
def IsValidCodePage(p, cp):
    return 1


@dll(3)
def GetEnvironmentVariableA(p, name, buf, size):
    p.last_error = 203                           # ERROR_ENVVAR_NOT_FOUND
    return 0


dll.alias("GetEnvironmentVariableW", "GetEnvironmentVariableA")


@dll(2)
def SetEnvironmentVariableA(p, name, value):
    return 1


dll.alias("SetEnvironmentVariableW", "SetEnvironmentVariableA")


@dll(0)
def GetEnvironmentStringsW(p):
    block = p.heap.alloc(16)
    return block


dll.alias("GetEnvironmentStrings", "GetEnvironmentStringsW")
dll.alias("GetEnvironmentStringsA", "GetEnvironmentStringsW")


@dll(1)
def FreeEnvironmentStringsW(p, block):
    return 1


dll.alias("FreeEnvironmentStringsA", "FreeEnvironmentStringsW")


# ---- memory ----

@dll(0)
def GetProcessHeap(p):
    return 0x11110000


@dll(3)
def HeapCreate(p, flags, initial, maximum):
    return 0x11110000


@dll(1)
def HeapDestroy(p, heap):
    return 1


@dll(3)
def HeapAlloc(p, heap, flags, size):
    return p.heap.alloc(size)


@dll(3)
def HeapFree(p, heap, flags, addr):
    p.heap.free(addr)
    return 1


@dll(4)
def HeapReAlloc(p, heap, flags, addr, size):
    return p.heap.realloc(addr, size)


@dll(3)
def HeapSize(p, heap, flags, addr):
    return p.heap.size(addr)


@dll(3)
def HeapValidate(p, heap, flags, addr):
    return 1


@dll(4)
def VirtualAlloc(p, addr, size, kind, protect):
    if addr and p.heap.size(addr):
        return addr                              # committing what was reserved
    block = p.heap.alloc(size + 4096)
    return (block + 4095) & ~4095 if block & 4095 else block


@dll(3)
def VirtualFree(p, addr, size, kind):
    return 1


@dll(4)
def VirtualProtect(p, addr, size, new, old):
    if old:
        mem.put32(old, 0x40)                     # it was "read, write, execute"
    return 1


@dll(3)
def VirtualQuery(p, addr, info, size):
    mem.zero(info, 48)
    page = addr & ~4095
    mem.put64(info, page)                        # BaseAddress
    mem.put64(info + 8, page)                    # AllocationBase
    mem.put32(info + 16, 0x40)                   # AllocationProtect
    mem.put64(info + 24, 4096)                   # RegionSize
    mem.put32(info + 32, 0x1000)                 # State: MEM_COMMIT
    mem.put32(info + 36, 0x40)                   # Protect
    mem.put32(info + 40, 0x20000)                # Type: MEM_PRIVATE
    return 48


@dll(2)
def GlobalAlloc(p, flags, size):
    return p.heap.alloc(size)


dll.alias("LocalAlloc", "GlobalAlloc")


@dll(1)
def GlobalFree(p, addr):
    p.heap.free(addr)
    return 0


dll.alias("LocalFree", "GlobalFree")


@dll(1)
def GlobalLock(p, h):
    return h


@dll(1)
def GlobalUnlock(p, h):
    return 1


# ---- threads and the things they wait on ----
# Program threads are Python threads (see Thread in process.py). Waiting is
# done in Python, a few milliseconds at a time, so the others can run.

INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0, WAIT_ABANDONED, WAIT_TIMEOUT, WAIT_FAILED = 0, 0x80, 0x102, 0xFFFFFFFF


def _me(p):
    return p.thread().id


class Event:
    def __init__(self, manual, signaled):
        self.manual, self.signaled = bool(manual), bool(signaled)

    def ready(self, tid):
        return self.signaled

    def take(self, tid):
        if not self.manual:
            self.signaled = False

    def close(self):
        pass


class Mutex:
    def __init__(self, owner=None):
        self.owner, self.count = owner, 1 if owner is not None else 0

    def ready(self, tid):
        return self.owner is None or self.owner == tid

    def take(self, tid):
        self.owner = tid
        self.count += 1

    def release(self):
        self.count -= 1
        if self.count <= 0:
            self.owner, self.count = None, 0

    def close(self):
        pass


class Semaphore:
    def __init__(self, count, maximum):
        self.count, self.maximum = count, maximum

    def ready(self, tid):
        return self.count > 0

    def take(self, tid):
        self.count -= 1

    def close(self):
        pass


def _ready(obj, tid):
    from pywin.process import Thread
    if isinstance(obj, Thread):
        return obj.done
    return obj.ready(tid) if hasattr(obj, "ready") else True


def _take(obj, tid):
    if hasattr(obj, "take"):
        obj.take(tid)


def _wait(p, objs, all_of, ms):
    """Wait for one (or all) of objs. Returns the WAIT_ code."""
    tid = _me(p)
    start = time.ticks_ms()
    while True:
        if p.killed:
            from pywin.process import Exit
            raise Exit(p.exit_request if p.exit_request is not None else 1)
        ready = [_ready(o, tid) for o in objs]
        if all_of and all(ready):
            for o in objs:
                _take(o, tid)
            return WAIT_OBJECT_0
        if not all_of:
            for i, ok in enumerate(ready):
                if ok:
                    _take(objs[i], tid)
                    return WAIT_OBJECT_0 + i
        if ms != INFINITE and time.ticks_diff(time.ticks_ms(), start) >= ms:
            return WAIT_TIMEOUT
        time.sleep_ms(1)


@dll(2)
def WaitForSingleObject(p, h, ms):
    obj = p.handles.get(h)
    if obj is None:
        return WAIT_FAILED
    return _wait(p, [obj], True, ms & 0xFFFFFFFF)


@dll(3)
def WaitForSingleObjectEx(p, h, ms, alertable):
    return WaitForSingleObject(p, h, ms)


@dll(4)
def WaitForMultipleObjects(p, n, handles, all_of, ms):
    objs = [p.handles.get(mem.u64(handles + 8 * k)) for k in range(n)]
    if None in objs:
        return WAIT_FAILED
    return _wait(p, objs, bool(all_of), ms & 0xFFFFFFFF)


@dll(4)
def CreateEventA(p, attrs, manual, initial, name):
    return p.new_handle(Event(manual, initial))


dll.alias("CreateEventW", "CreateEventA")


@dll(4)
def CreateEventExA(p, attrs, name, flags, access):
    return p.new_handle(Event(flags & 1, flags & 2))


dll.alias("CreateEventExW", "CreateEventExA")


@dll(1)
def SetEvent(p, h):
    obj = p.handles.get(h)
    if isinstance(obj, Event):
        obj.signaled = True
    return 1


@dll(1)
def ResetEvent(p, h):
    obj = p.handles.get(h)
    if isinstance(obj, Event):
        obj.signaled = False
    return 1


@dll(3)
def CreateMutexA(p, attrs, owned, name):
    return p.new_handle(Mutex(_me(p) if owned else None))


dll.alias("CreateMutexW", "CreateMutexA")


@dll(1)
def ReleaseMutex(p, h):
    obj = p.handles.get(h)
    if isinstance(obj, Mutex):
        obj.release()
    return 1


@dll(4)
def CreateSemaphoreA(p, attrs, initial, maximum, name):
    return p.new_handle(Semaphore(initial, maximum))


dll.alias("CreateSemaphoreW", "CreateSemaphoreA")


@dll(3)
def ReleaseSemaphore(p, h, count, previous):
    obj = p.handles.get(h)
    if isinstance(obj, Semaphore):
        if previous:
            mem.put32(previous, obj.count)
        obj.count = min(obj.maximum, obj.count + count)
    return 1


@dll(1)
def CloseHandle(p, h):
    obj = p.handles.pop(h, None)
    if obj is not None:
        obj.close()
    return 1


# threads

@dll(6)
def CreateThread(p, attrs, stack, fn, param, flags, tid_out):
    if flags & 4:                                       # CREATE_SUSPENDED: starts at ResumeThread
        t = _Suspended(fn, param, stack)
        h = p.new_handle(t)
        t.handle = h
    else:
        t = p.start_thread(fn, param, stack)
        h = p.new_handle(t)
    if tid_out:
        mem.put32(tid_out, getattr(t, "id", 0))
    return h


class _Suspended:
    def __init__(self, fn, param, stack):
        self.fn, self.param, self.stack = fn, param, stack
        self.id = 0
        self.done = False

    def close(self):
        pass


@dll(1)
def ResumeThread(p, h):
    t = p.handles.get(h)
    if isinstance(t, _Suspended):
        p.handles[h] = p.start_thread(t.fn, t.param, t.stack)
    return 1


@dll(1)
def SuspendThread(p, h):
    return 0


@dll(1)
def ExitThread(p, code):
    from pywin.process import ThreadExit, Exit
    if p.thread() is p.main:
        raise Exit(code)
    raise ThreadExit(code)


@dll(2)
def GetExitCodeThread(p, h, out):
    t = p.handles.get(h)
    mem.put32(out, getattr(t, "code", 0x103) if getattr(t, "done", False) else 0x103)
    return 1


@dll(0)
def GetCurrentThreadId(p):
    return _me(p)


@dll(1)
def GetThreadId(p, h):
    t = p.handles.get(h)
    return getattr(t, "id", 0) if t is not None else _me(p)


@dll(0)
def SwitchToThread(p):
    time.sleep_ms(1)
    return 1


@dll(2)
def SetThreadPriority(p, h, priority):
    return 1


@dll(1)
def GetThreadPriority(p, h):
    return 0


@dll(2)
def SetThreadAffinityMask(p, h, mask):
    return 1


# critical sections and slim locks: real locks, owned by a thread, re-entrant

def _locks(p):
    return p.state.setdefault("locks", {})


def _enter(p, key, wait=True):
    locks = _locks(p)
    tid = _me(p)
    while True:
        owner = locks.get(key)
        if owner is None or owner[0] == tid:
            locks[key] = (tid, (owner[1] if owner else 0) + 1)
            return True
        if not wait:
            return False
        if p.killed:
            from pywin.process import Exit
            raise Exit(p.exit_request if p.exit_request is not None else 1)
        time.sleep_ms(1)


def _leave(p, key):
    locks = _locks(p)
    owner = locks.get(key)
    if owner is not None:
        if owner[1] <= 1:
            del locks[key]
        else:
            locks[key] = (owner[0], owner[1] - 1)


@dll(1)
def InitializeCriticalSection(p, cs):
    mem.zero(cs, 40)
    _locks(p).pop(cs, None)


@dll(2)
def InitializeCriticalSectionAndSpinCount(p, cs, spin):
    InitializeCriticalSection(p, cs)
    return 1


@dll(3)
def InitializeCriticalSectionEx(p, cs, spin, flags):
    InitializeCriticalSection(p, cs)
    return 1


@dll(1)
def EnterCriticalSection(p, cs):
    _enter(p, cs)


@dll(1)
def LeaveCriticalSection(p, cs):
    _leave(p, cs)


@dll(1)
def TryEnterCriticalSection(p, cs):
    return 1 if _enter(p, cs, wait=False) else 0


@dll(1)
def DeleteCriticalSection(p, cs):
    _locks(p).pop(cs, None)


@dll(1)
def InitializeSRWLock(p, lock):
    mem.put64(lock, 0)


dll.alias("AcquireSRWLockExclusive", "EnterCriticalSection")
dll.alias("ReleaseSRWLockExclusive", "LeaveCriticalSection")
dll.alias("AcquireSRWLockShared", "EnterCriticalSection")
dll.alias("ReleaseSRWLockShared", "LeaveCriticalSection")
dll.alias("TryAcquireSRWLockExclusive", "TryEnterCriticalSection")


# condition variables: a counter of wake-ups each waiter watches

@dll(1)
def InitializeConditionVariable(p, cv):
    mem.put64(cv, 0)


def _sleep_cv(p, cv, lock, ms):
    gen = p.state.setdefault("cv", {}).get(cv, 0)
    _leave(p, lock)
    start = time.ticks_ms()
    ok = 1
    while p.state["cv"].get(cv, 0) == gen:
        if ms != INFINITE and time.ticks_diff(time.ticks_ms(), start) >= ms:
            ok = 0
            p.last_error = 1460                         # ERROR_TIMEOUT
            break
        if p.killed:
            break
        time.sleep_ms(1)
    _enter(p, lock)
    return ok


@dll(3)
def SleepConditionVariableCS(p, cv, cs, ms):
    return _sleep_cv(p, cv, cs, ms & 0xFFFFFFFF)


@dll(4)
def SleepConditionVariableSRW(p, cv, lock, ms, flags):
    return _sleep_cv(p, cv, lock, ms & 0xFFFFFFFF)


@dll(1)
def WakeConditionVariable(p, cv):
    gens = p.state.setdefault("cv", {})
    gens[cv] = gens.get(cv, 0) + 1


dll.alias("WakeAllConditionVariable", "WakeConditionVariable")


# thread-local storage: each thread its own values

def _tls(p):
    return p.state.setdefault("tls", {})


@dll(0)
def TlsAlloc(p):
    n = p.state.get("tls_next", 1)
    p.state["tls_next"] = n + 1
    return n


@dll(1)
def TlsGetValue(p, n):
    return _tls(p).get((_me(p), n), 0)


@dll(2)
def TlsSetValue(p, n, value):
    _tls(p)[(_me(p), n)] = value
    return 1


@dll(1)
def TlsFree(p, n):
    return 1


@dll(1)
def FlsAlloc(p, callback):
    return TlsAlloc(p)


dll.alias("FlsGetValue", "TlsGetValue")
dll.alias("FlsSetValue", "TlsSetValue")
dll.alias("FlsFree", "TlsFree")


@dll(4)
def InitOnceExecuteOnce(p, once, fn, param, ctx):
    if not mem.u64(once):
        mem.put64(once, 1)
        p.call(fn, once, param, ctx)
    return 1


# ---- time ----

@dll(1)
def Sleep(p, ms):
    ms &= 0xFFFFFFFF
    end = time.ticks_add(time.ticks_ms(), min(ms, 3600000))
    while True:                                         # in steps, so a stopped program wakes up
        if p.killed:
            from pywin.process import Exit
            raise Exit(p.exit_request if p.exit_request is not None else 1)
        left = time.ticks_diff(end, time.ticks_ms())
        if left <= 0:
            time.sleep_ms(0 if ms else 1)
            return
        time.sleep_ms(min(left, 50))


@dll(2)
def SleepEx(p, ms, alertable):
    Sleep(p, ms)
    return 0


@dll(0)
def GetTickCount(p):
    return (time.ticks_ms() - _start + 1000) & 0xFFFFFFFF


@dll(0)
def GetTickCount64(p):
    return time.ticks_ms() - _start + 1000


@dll(1)
def QueryPerformanceCounter(p, out):
    mem.put64(out, time.ticks_us())
    return 1


@dll(1)
def QueryPerformanceFrequency(p, out):
    mem.put64(out, 1000000)
    return 1


def _filetime():
    # 100 ns steps since 1601; time.time() counts from 2000 on MicroPython
    epoch = time.mktime((1970, 1, 1, 0, 0, 0, 0, 0)) if hasattr(time, "mktime") else 0
    seconds = time.time() - epoch
    return int((seconds + 11644473600) * 10000000)


@dll(1)
def GetSystemTimeAsFileTime(p, out):
    mem.put64(out, _filetime())


dll.alias("GetSystemTimePreciseAsFileTime", "GetSystemTimeAsFileTime")


@dll(1)
def GetLocalTime(p, out):
    t = time.localtime()
    for k, v in enumerate((t[0], t[1], (t[6] + 1) % 7, t[2], t[3], t[4], t[5], 0)):
        mem.put16(out + 2 * k, v)


dll.alias("GetSystemTime", "GetLocalTime")


@dll(2)
def Beep(p, freq, ms):
    try:
        from kernel import sound
        sound.tone(freq, ms)
    except Exception:
        pass
    return 1


# ---- the console ----

@dll(1)
def GetStdHandle(p, which):
    which = _i32(which)
    return std(p, which) if which in (STD_INPUT, STD_OUTPUT, STD_ERROR) else INVALID


@dll(2)
def SetStdHandle(p, which, h):
    p.state["std%d" % _i32(which)] = h
    return 1


@dll(5)
def WriteFile(p, h, buf, n, written, overlapped):
    obj = _obj(p, h)
    if obj is None:
        p.last_error = ERROR_INVALID_HANDLE
        return 0
    count = obj.write(mem.read(buf, n)) or n
    if written:
        mem.put32(written, count)
    return 1


@dll(5)
def WriteConsoleA(p, h, buf, n, written, reserved):
    return WriteFile(p, h, buf, n, written, 0)


@dll(5)
def WriteConsoleW(p, h, buf, n, written, reserved):
    text = mem.read(buf, n * 2)
    s = "".join(chr(text[2 * k] | text[2 * k + 1] << 8) for k in range(n))
    p.ui.write(s)
    if written:
        mem.put32(written, n)
    return 1


@dll(5)
def ReadFile(p, h, buf, n, done, overlapped):
    obj = _obj(p, h)
    if obj is None:
        p.last_error = ERROR_INVALID_HANDLE
        return 0
    data = obj.read(n) or b""
    mem.write(buf, data)
    if done:
        mem.put32(done, len(data))
    return 1


@dll(5)
def ReadConsoleA(p, h, buf, n, done, control):
    return ReadFile(p, h, buf, n, done, 0)


@dll(5)
def ReadConsoleW(p, h, buf, n, done, control):
    obj = _obj(p, h)
    data = _text(obj.read(n)) if obj else ""
    mem.write(buf, b"".join(bytes((ord(c) & 255, ord(c) >> 8)) for c in data))
    if done:
        mem.put32(done, len(data))
    return 1


@dll(2)
def GetConsoleMode(p, h, out):
    mem.put32(out, 3)
    return 1


@dll(2)
def SetConsoleMode(p, h, mode):
    return 1


@dll(0)
def GetConsoleCP(p):
    return 65001


dll.alias("GetConsoleOutputCP", "GetConsoleCP")


@dll(1)
def SetConsoleCP(p, cp):
    return 1


dll.alias("SetConsoleOutputCP", "SetConsoleCP")


@dll(1)
def SetConsoleTitleA(p, title):
    p.ui.title(mem.cstr(title))
    return 1


@dll(1)
def SetConsoleTitleW(p, title):
    p.ui.title(mem.wstr(title))
    return 1


@dll(2)
def SetConsoleTextAttribute(p, h, attr):
    color = getattr(p.ui, "color", None)
    if color:
        color(attr)
    return 1


@dll(2)
def GetConsoleScreenBufferInfo(p, h, info):
    cols, rows = getattr(p.ui, "size", (80, 25))
    mem.zero(info, 22)
    for k, v in enumerate((cols, rows, 0, 0, 7, 0, 0, cols - 1, rows - 1, cols, rows)):
        mem.put16(info + 2 * k, v)
    return 1


@dll(2)
def SetConsoleCursorPosition(p, h, pos):
    move = getattr(p.ui, "move", None)
    if move:
        move(pos & 0xFFFF, (pos >> 16) & 0xFFFF)
    return 1


@dll(0)
def AllocConsole(p):
    return 1


dll.alias("FreeConsole", "AllocConsole")


@dll(2)
def SetConsoleCtrlHandler(p, fn, add):
    return 1


@dll(1)
def FlushFileBuffers(p, h):
    return 1


@dll(1)
def GetFileType(p, h):
    obj = _obj(p, h)
    return 2 if isinstance(obj, (ConsoleIn, ConsoleOut)) else 1      # CHAR or DISK


# ---- files ----

@dll(7)
def CreateFileA(p, name, access, share, security, disposition, flags, template):
    return _create(p, mem.cstr(name), access, disposition)


@dll(7)
def CreateFileW(p, name, access, share, security, disposition, flags, template):
    return _create(p, mem.wstr(name), access, disposition)


def _create(p, name, access, disposition):
    if name.upper() in ("CONOUT$", "CON"):
        return std(p, STD_OUTPUT)
    if name.upper() == "CONIN$":
        return std(p, STD_INPUT)
    # GENERIC_WRITE, GENERIC_ALL, FILE_WRITE_DATA, FILE_APPEND_DATA, DELETE; or a disposition that creates
    write = bool(access & 0x50010006) or disposition in (1, 2, 4, 5)
    try:
        path = p.host_path(name, write=write)
    except OSError:
        p.last_error = 5                                   # ERROR_ACCESS_DENIED
        return INVALID
    write = bool(access & 0x50010006)
    exists = _exists(path)
    # 1 CREATE_NEW, 2 CREATE_ALWAYS, 3 OPEN_EXISTING, 4 OPEN_ALWAYS, 5 TRUNCATE_EXISTING
    if disposition in (3, 5) and not exists or disposition == 1 and exists:
        p.last_error = ERROR_FILE_NOT_FOUND if not exists else 80
        return INVALID
    mode = "wb" if disposition in (1, 2, 5) or (write and not exists) else ("r+b" if write else "rb")
    try:
        return p.new_handle(HostFile(path, mode))
    except OSError:
        p.last_error = ERROR_FILE_NOT_FOUND
        return INVALID


def _exists(path):
    import os
    try:
        os.stat(path)
        return True
    except OSError:
        return False


@dll(2)
def GetFileSize(p, h, high):
    obj = _obj(p, h)
    if high:
        mem.put32(high, 0)
    return obj.size() if isinstance(obj, HostFile) else 0


@dll(2)
def GetFileSizeEx(p, h, out):
    mem.put64(out, GetFileSize(p, h, 0))
    return 1


@dll(4)
def SetFilePointer(p, h, low, high, method):
    obj = _obj(p, h)
    return obj.seek(_i32(low), method) if isinstance(obj, HostFile) else 0


@dll(4)
def SetFilePointerEx(p, h, distance, out, method):
    obj = _obj(p, h)
    pos = obj.seek(distance, method) if isinstance(obj, HostFile) else 0
    if out:
        mem.put64(out, pos)
    return 1


@dll(1)
def DeleteFileA(p, name):
    import os
    try:
        os.remove(p.host_path(mem.cstr(name), write=True))
        return 1
    except OSError:
        p.last_error = ERROR_FILE_NOT_FOUND
        return 0


@dll(2)
def CreateDirectoryA(p, name, security):
    import os
    try:
        os.mkdir(p.host_path(mem.cstr(name), write=True))
        return 1
    except OSError:
        return 0


@dll(1)
def GetFileAttributesA(p, name):
    import os
    try:
        st = os.stat(p.host_path(mem.cstr(name)))
    except OSError:
        p.last_error = ERROR_FILE_NOT_FOUND
        return 0xFFFFFFFF
    return 0x10 if st[0] & 0x4000 else 0x80           # DIRECTORY or NORMAL


@dll(2)
def GetCurrentDirectoryA(p, size, buf):
    from pywin.process import to_windows
    path = to_windows(p.cwd)
    if size > len(path):
        mem.put_cstr(buf, path)
    return len(path)


@dll(1)
def SetCurrentDirectoryA(p, name):
    p.cwd = p.host_path(mem.cstr(name))
    return 1


@dll(2)
def GetTempPathA(p, size, buf):
    path = "C:\\Temp\\"
    mem.put_cstr(buf, path)
    return len(path)


# ---- text conversion ----

def _utf16(text):
    return mem.to_utf16(text)


ERROR_INSUFFICIENT_BUFFER = 122


@dll(6)
def MultiByteToWideChar(p, cp, flags, src, n, dst, size):
    n, size = _i32(n), _i32(size)                  # int arguments: only the low 32 bits count
    if n == 0 or size < 0 or n < -1:
        p.last_error = 87                          # ERROR_INVALID_PARAMETER
        return 0
    data = mem.cbytes(src) + b"\0" if n == -1 else mem.read(src, n)
    wide = _utf16(_text(data))
    chars = len(wide) // 2
    if size:
        if chars > size:                           # like Windows: fail, never cut the text
            p.last_error = ERROR_INSUFFICIENT_BUFFER
            return 0
        mem.write(dst, wide)
    return chars


@dll(8)
def WideCharToMultiByte(p, cp, flags, src, n, dst, size, default, used):
    n, size = _i32(n), _i32(size)
    if n == 0 or size < 0 or n < -1:
        p.last_error = 87
        return 0
    if n == -1:
        text = mem.wstr(src) + "\0"
    else:
        raw = mem.read(src, n * 2)
        text = _from_utf16(raw)
    data = text.encode()
    if size:
        if len(data) > size:
            p.last_error = ERROR_INSUFFICIENT_BUFFER
            return 0
        mem.write(dst, data)
    if used:
        mem.put32(used, 0)
    return len(data)


def _from_utf16(raw):
    return mem._from_utf16(raw)


@dll(1)
def lstrlenA(p, s):
    return len(mem.cbytes(s)) if s else 0


@dll(1)
def lstrlenW(p, s):
    return len(mem.wstr(s)) if s else 0


@dll(2)
def lstrcpyA(p, dst, src):
    mem.write(dst, mem.cbytes(src) + b"\0")
    return dst


@dll(2)
def lstrcatA(p, dst, src):
    mem.write(dst + len(mem.cbytes(dst)), mem.cbytes(src) + b"\0")
    return dst


@dll(2)
def lstrcmpA(p, a, b):
    x, y = mem.cbytes(a), mem.cbytes(b)
    return (x > y) - (x < y)


@dll(2)
def lstrcmpiA(p, a, b):
    x, y = mem.cbytes(a).lower(), mem.cbytes(b).lower()
    return (x > y) - (x < y)


# ---- exceptions (C++ throw/catch): see pywin/seh.py ----

@dll(1)
def RtlCaptureContext(p, ctx):
    seh.capture(p, ctx)


@dll(4)
def RaiseException(p, code, flags, nargs, args):
    seh.raise_exception(p, code & 0xFFFFFFFF, flags, nargs, args)


@dll(6)
def RtlUnwindEx(p, frame, ip, record, value, ctx, history):
    seh.unwind(p, frame, ip, record, value, ctx)


@dll(4)
def RtlUnwind(p, frame, ip, record, value):
    seh.unwind(p, frame, ip, record, value, 0)


@dll(3)
def RtlLookupFunctionEntry(p, pc, base_out, history):
    entry = seh.lookup(p, pc)
    if entry and base_out:
        mem.put64(base_out, p.base)
    return entry or 0


@dll(8)
def RtlVirtualUnwind(p, kind, base, pc, entry, ctx, data_out, frame_out, pointers):
    handler, data, frame = seh.virtual_unwind(p, kind, pc, entry, ctx)
    if data_out:
        mem.put64(data_out, data)
    if frame_out:
        mem.put64(frame_out, frame)
    return handler


@dll(2)
def RtlRestoreContext(p, ctx, record):
    raise seh.Resume(mem.read(ctx, seh.CONTEXT_SIZE))


@dll(1)
def OutputDebugStringA(p, s):
    p.ui.write("[debug] %s\n" % mem.cstr(s))


@dll(7)
def FormatMessageA(p, flags, source, msg_id, lang, buf, size, args):
    text = "Error %d\r\n" % msg_id
    if flags & 0x100:                                  # FORMAT_MESSAGE_ALLOCATE_BUFFER
        block = p.heap.alloc(len(text) + 1)
        mem.put_cstr(block, text)
        mem.put64(buf, block)
    elif size:
        mem.put_cstr(buf, text[:size - 1])
    return len(text)





# ---- the rest of kernel32, in files of their own ----
from pywin.dlls import k32_files, k32_text, k32_misc    # noqa: E402,F401
