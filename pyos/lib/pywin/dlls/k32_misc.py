# kernel32.dll, part 4: the rest. Processes (only this one exists),
# encoded pointers, lock-free lists, the thread pool, one-time
# initialisation, and things programs ask about the system.
from pywin import mem
from pywin.dlls.kernel32 import dll, INVALID


# ---- pointers and lists the C runtime uses ----

@dll(1)
def EncodePointer(p, ptr):
    return ptr                     # "encoding" is only a defence on real Windows: here, the same value


dll.alias("DecodePointer", "EncodePointer")
dll.alias("EncodeSystemPointer", "EncodePointer")
dll.alias("DecodeSystemPointer", "EncodePointer")


@dll(1)
def InitializeSListHead(p, head):
    mem.zero(head, 16)


@dll(1)
def InterlockedFlushSList(p, head):
    first = mem.u64(head + 8)
    mem.zero(head, 16)
    return first


@dll(1)
def GlobalSize(p, h):
    return p.heap.size(h)


dll.alias("LocalSize", "GlobalSize")


@dll(3)
def GlobalReAlloc(p, h, size, flags):
    return p.heap.realloc(h, size)


dll.alias("LocalReAlloc", "GlobalReAlloc")


# ---- processes: there is only this one ----

@dll(3)
def OpenProcess(p, access, inherit, pid):
    if pid in (0, 4):
        return 0xFFFFFFFFFFFFFFFF
    p.last_error = 87
    return 0


@dll(2)
def GetExitCodeProcess(p, h, out):
    mem.put32(out, 0x103)                                  # STILL_ACTIVE
    return 1


@dll(4)
def QueryFullProcessImageNameW(p, h, flags, buf, size_ptr):
    name = p.argv[0]
    if mem.u32(size_ptr) <= len(name):
        p.last_error = 122
        return 0
    mem.put_wstr(buf, name)
    mem.put32(size_ptr, len(name))
    return 1


@dll(2)
def CreateToolhelp32Snapshot(p, flags, pid):
    p.last_error = 50
    return INVALID


@dll(2)
def Process32FirstW(p, snap, entry):
    return 0


dll.alias("Process32NextW", "Process32FirstW")


@dll(2)
def TerminateThread(p, h, code):
    return 0                                               # not supported: threads must end by themselves


@dll(3)
def QueueUserAPC(p, fn, thread, data):
    return 0


@dll(7)
def DuplicateHandle(p, src_proc, src, dst_proc, out, access, inherit, options):
    obj = p.handles.get(src)
    if out:
        mem.put64(out, p.new_handle(obj) if obj is not None else src)
    return 1


@dll(4)
def GetProductInfo(p, major, minor, sp_major, out):
    mem.put32(out, 0x30)                                   # PRODUCT_PROFESSIONAL
    return 1


@dll(2)
def RegisterApplicationRestart(p, cmdline, flags):
    return 0


@dll(0)
def UnregisterApplicationRestart(p):
    return 0


@dll(4)
def GetApplicationRestartSettings(p, process, cmdline, size, flags):
    return 0x80070490                                      # HRESULT: element not found


@dll(3)
def GetModuleHandleExW(p, flags, name, out):
    if flags & 4:                                          # FROM_ADDRESS: the module holding that address
        addr = name
        base = p.base
        for lib in p.libraries.values():
            if lib.base <= addr < lib.base + lib.image.size:
                base = lib.base
        mem.put64(out, base)
        return 1
    from pywin.dlls import kernel32
    h = kernel32.GetModuleHandleW(p, name)
    mem.put64(out, h)
    return 1 if h else 0


@dll(2)
def RtlPcToFileHeader(p, pc, base_out):
    base = 0
    if p.base <= pc < p.base + p.image.size:
        base = p.base
    for lib in p.libraries.values():
        if lib.base <= pc < lib.base + lib.image.size:
            base = lib.base
    mem.put64(base_out, base)
    return base


@dll(2)
def FreeLibraryAndExitThread(p, module, code):
    from pywin.dlls import kernel32
    kernel32.ExitThread(p, code)


# ---- the thread pool: each piece of work runs in a new thread ----

class Work:
    def __init__(self, fn, context):
        self.fn, self.context = fn, context

    def close(self):
        pass


@dll(3)
def CreateThreadpoolWork(p, fn, context, environ):
    return p.new_handle(Work(fn, context))


@dll(1)
def SubmitThreadpoolWork(p, h):
    w = p.handles.get(h)
    if isinstance(w, Work):
        # the callback gets (instance, context, work): run it as a thread function
        trampoline_ctx = w.context
        p.start_thread_call(w.fn, (0, trampoline_ctx, h))


@dll(1)
def CloseThreadpoolWork(p, h):
    p.handles.pop(h, None)


@dll(2)
def WaitForThreadpoolWorkCallbacks(p, h, cancel):
    pass


@dll(2)
def FreeLibraryWhenCallbackReturns(p, instance, module):
    pass


@dll(3)
def TrySubmitThreadpoolCallback(p, fn, context, environ):
    p.start_thread_call(fn, (0, context))
    return 1


# ---- one-time initialisation (InitOnce) ----

@dll(4)
def InitOnceBeginInitialize(p, once, flags, pending, context):
    done = mem.u64(once) == 2
    mem.put32(pending, 0 if done else 1)
    if not done:
        mem.put64(once, 1)
    if context:
        mem.put64(context, 0)
    return 1


@dll(3)
def InitOnceComplete(p, once, flags, context):
    mem.put64(once, 2)
    return 1


@dll(1)
def InitOnceInitialize(p, once):
    mem.put64(once, 0)


# ---- .ini files (GetPrivateProfileString...): sections of key=value lines ----

def _ini_read(p, path):
    """{section lower-case: (name, {key lower-case: (key, value)})} of an .ini file."""
    out = {}
    try:
        with open(p.host_path(path), "rb") as f:
            raw = f.read()
    except OSError:
        return out
    if raw[:2] == b"\xff\xfe":                                   # UTF-16 with its mark
        text = mem._from_utf16(raw[2:])
    else:
        try:
            text = raw.decode()
        except UnicodeError:
            text = "".join(chr(b) for b in raw)
    section = None
    for line in text.replace("\r", "").split("\n"):
        line = line.strip()
        if line.startswith("[") and "]" in line:
            name = line[1:line.index("]")].strip()
            section = out.setdefault(name.lower(), (name, {}))
        elif section is not None and "=" in line and not line.startswith(";"):
            key, _, value = line.partition("=")
            section[1][key.strip().lower()] = (key.strip(), value.strip())
    return out


def _ini_write(p, path, data):
    lines = []
    for name, keys in data.values():
        lines.append("[%s]" % name)
        lines += ["%s=%s" % kv for kv in keys.values()]
        lines.append("")
    with open(p.host_path(path, write=True), "w") as f:
        f.write("\r\n".join(lines))


def _ini_path(p, name):
    """A bare name like 'plugin.ini' lives in the Windows folder, as on Windows."""
    if "\\" in name or "/" in name:
        return name
    return "C:\\Windows\\" + name


def _put_list(p, buf, size, items):
    """Strings one after another, each ended by a zero, then one more zero."""
    if not buf or size < 2:
        return 0
    out, used = [], 0
    for s in items:
        if used + len(s) + 2 > size:
            break
        out.append(s)
        used += len(s) + 1
    data = "\0".join(out) + "\0\0" if out else "\0\0"
    mem.write(buf, mem.to_utf16(data))
    return used


@dll(6)
def GetPrivateProfileStringW(p, section, key, default, buf, size, file):
    if not size:
        return 0
    data = _ini_read(p, _ini_path(p, mem.wstr(file) or "win.ini"))
    if not section:                                              # every section name
        return _put_list(p, buf, size, [v[0] for v in data.values()])
    sec = data.get((mem.wstr(section) or "").lower())
    if not key:                                                  # every key of the section
        return _put_list(p, buf, size, [k for k, _ in sec[1].values()] if sec else [])
    found = sec[1].get((mem.wstr(key) or "").lower()) if sec else None
    value = found[1] if found else (mem.wstr(default) or "" if default else "")
    value = value[:size - 1]
    mem.put_wstr(buf, value)
    return len(value)


@dll(4)
def GetPrivateProfileIntW(p, section, key, default, file):
    data = _ini_read(p, _ini_path(p, mem.wstr(file) or "win.ini"))
    sec = data.get((mem.wstr(section) or "").lower())
    found = sec[1].get((mem.wstr(key) or "").lower()) if sec else None
    try:
        return int(found[1].split()[0], 0) & 0xFFFFFFFF if found else default
    except (ValueError, IndexError):
        return default


@dll(4)
def WritePrivateProfileStringW(p, section, key, value, file):
    path = _ini_path(p, mem.wstr(file) or "win.ini")
    try:
        data = _ini_read(p, path)
        name = mem.wstr(section) or ""
        sec = data.setdefault(name.lower(), (name, {}))
        if not key:
            del data[name.lower()]                                # NULL key: remove the section
        elif not value:
            sec[1].pop((mem.wstr(key) or "").lower(), None)       # NULL value: remove the key
        else:
            k = mem.wstr(key) or ""
            sec[1][k.lower()] = (k, mem.wstr(value) or "")
        _ini_write(p, path, data)
        return 1
    except OSError:
        p.last_error = 5
        return 0


@dll(3)
def GetPrivateProfileSectionNamesW(p, buf, size, file):
    data = _ini_read(p, _ini_path(p, mem.wstr(file) or "win.ini"))
    return _put_list(p, buf, size, [v[0] for v in data.values()])


@dll(4)
def GetPrivateProfileSectionW(p, section, buf, size, file):
    data = _ini_read(p, _ini_path(p, mem.wstr(file) or "win.ini"))
    sec = data.get((mem.wstr(section) or "").lower())
    return _put_list(p, buf, size, ["%s=%s" % kv for kv in sec[1].values()] if sec else [])


@dll(5)
def GetPrivateProfileStructW(p, section, key, out, size, file):
    return 0


@dll(5)
def GetProfileStringW(p, section, key, default, buf, size):
    return GetPrivateProfileStringW(p, section, key, default, buf, size, 0)
