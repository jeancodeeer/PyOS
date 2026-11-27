# kernel32.dll, part 2: files and folders with Unicode ("W") names,
# searching folders (FindFirstFile), file times, and file mappings.
# These functions join the kernel32 Dll object; see kernel32.py.
import os
import struct
import time
from pywin import mem
from pywin.dlls.kernel32 import dll, HostFile, INVALID, _exists, _i32

FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_NORMAL, FILE_ATTRIBUTE_ARCHIVE = 0x10, 0x80, 0x20
ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND, ERROR_NO_MORE_FILES, ERROR_ALREADY_EXISTS = 2, 3, 18, 183
EPOCH_1601 = 11644473600                     # seconds between 1601 and 1970


def _unix_epoch():
    return time.mktime((1970, 1, 1, 0, 0, 0, 0, 0)) if hasattr(time, "mktime") else 0


def filetime(seconds):
    """Seconds (time.time() style) -> a Windows FILETIME number (100 ns since 1601)."""
    return int((seconds - _unix_epoch() + EPOCH_1601) * 10000000)


def _stat(p, name):
    try:
        return os.stat(p.host_path(name))
    except OSError:
        return None


def _attrs(st):
    return FILE_ATTRIBUTE_DIRECTORY if st[0] & 0x4000 else FILE_ATTRIBUTE_ARCHIVE


def _fail(p, code=ERROR_FILE_NOT_FOUND):
    p.last_error = code
    return 0


# ---- attributes ----

@dll(1)
def GetFileAttributesW(p, name):
    st = _stat(p, mem.wstr(name))
    if st is None:
        p.last_error = ERROR_FILE_NOT_FOUND
        return 0xFFFFFFFF
    return _attrs(st)


@dll(3)
def GetFileAttributesExW(p, name, level, out):
    st = _stat(p, mem.wstr(name))
    if st is None:
        return _fail(p)
    ft = filetime(st[8])
    mem.write(out, struct.pack("<IQQQII", _attrs(st), ft, ft, ft, 0, st[6] & 0xFFFFFFFF))
    return 1


@dll(2)
def SetFileAttributesW(p, name, attrs):
    return 1 if _stat(p, mem.wstr(name)) else _fail(p)


@dll(4)
def SetFileTime(p, h, created, accessed, written):
    return 1


# ---- folders and names ----

@dll(2)
def GetCurrentDirectoryW(p, size, buf):
    from pywin.process import to_windows
    path = to_windows(p.cwd)
    if size > len(path):
        mem.put_wstr(buf, path)
        return len(path)
    return len(path) + 1


@dll(1)
def SetCurrentDirectoryW(p, name):
    try:
        path = p.host_path(mem.wstr(name))
    except OSError:
        return _fail(p, 5)
    st = _stat(p, mem.wstr(name))
    if st is None or not st[0] & 0x4000:
        return _fail(p, ERROR_PATH_NOT_FOUND)
    p.cwd = path
    return 1


@dll(2)
def CreateDirectoryW(p, name, security):
    try:
        path = p.host_path(mem.wstr(name), write=True)
    except OSError:
        return _fail(p, 5)                                 # ERROR_ACCESS_DENIED
    if _exists(path):
        return _fail(p, ERROR_ALREADY_EXISTS)
    try:
        os.mkdir(path)
        return 1
    except OSError:
        return _fail(p, ERROR_PATH_NOT_FOUND)


@dll(1)
def DeleteFileW(p, name):
    try:
        os.remove(p.host_path(mem.wstr(name), write=True))
        return 1
    except OSError:
        return _fail(p)


@dll(3)
def MoveFileExW(p, old, new, flags):
    src, dst = p.host_path(mem.wstr(old), write=True), p.host_path(mem.wstr(new), write=True) if new else None
    try:
        if dst is None:
            os.remove(src)
        else:
            if _exists(dst) and flags & 1:                # MOVEFILE_REPLACE_EXISTING
                os.remove(dst)
            os.rename(src, dst)
        return 1
    except OSError:
        return _fail(p)


def _copy(src, dst):
    with open(src, "rb") as a, open(dst, "wb") as b:
        while True:
            chunk = a.read(32768)
            if not chunk:
                break
            b.write(chunk)


@dll(3)
def CopyFileW(p, old, new, fail_if_exists):
    src, dst = p.host_path(mem.wstr(old)), p.host_path(mem.wstr(new), write=True)
    if fail_if_exists and _exists(dst):
        return _fail(p, 80)                              # ERROR_FILE_EXISTS
    try:
        _copy(src, dst)
        return 1
    except OSError:
        return _fail(p)


@dll(6)
def CopyFileExW(p, old, new, progress, data, cancel, flags):
    return CopyFileW(p, old, new, flags & 1)


@dll(6)
def ReplaceFileW(p, replaced, replacement, backup, flags, exclude, reserved):
    dst, src = p.host_path(mem.wstr(replaced), write=True), p.host_path(mem.wstr(replacement), write=True)
    try:
        if backup:
            _copy(dst, p.host_path(mem.wstr(backup), write=True))
        os.remove(dst)
        os.rename(src, dst)
        return 1
    except OSError:
        return _fail(p)


@dll(4)
def GetFullPathNameW(p, name, size, buf, filepart):
    from pywin.process import to_windows
    full = to_windows(p.host_path(mem.wstr(name)))
    if size <= len(full):
        return len(full) + 1
    mem.put_wstr(buf, full)
    if filepart:
        mem.put64(filepart, buf + 2 * (full.rfind("\\") + 1))
    return len(full)


@dll(3)
def GetLongPathNameW(p, short, buf, size):
    name = mem.wstr(short)
    if size <= len(name):
        return len(name) + 1
    mem.put_wstr(buf, name)
    return len(name)


dll.alias("GetShortPathNameW", "GetLongPathNameW")


@dll(4)
def GetFinalPathNameByHandleW(p, h, buf, size, flags):
    from pywin.process import to_windows
    obj = p.handles.get(h)
    if not isinstance(obj, HostFile):
        return _fail(p, 6)
    name = "\\\\?\\" + to_windows(obj.path)
    if size <= len(name):
        return len(name) + 1
    mem.put_wstr(buf, name)
    return len(name)


@dll(2)
def GetTempPathW(p, size, buf):
    try:
        os.mkdir("/disk/Temp")
    except OSError:
        pass
    path = "C:\\Temp\\"
    if size > len(path):
        mem.put_wstr(buf, path)
    return len(path)


@dll(4)
def GetTempFileNameW(p, folder, prefix, unique, out):
    n = unique or (time.ticks_ms() & 0xFFFF) or 1
    name = "%s\\%s%04X.tmp" % (mem.wstr(folder).rstrip("\\"), (mem.wstr(prefix) or "")[:3], n)
    mem.put_wstr(out, name)
    if not unique:
        open(p.host_path(name, write=True), "wb").close()
    return n


@dll(4)
def GetDiskFreeSpaceExW(p, root, free_caller, total, free_all):
    for at, value in ((free_caller, 24 << 20), (total, 32 << 20), (free_all, 24 << 20)):
        if at:
            mem.put64(at, value)
    return 1


@dll(1)
def GetDriveTypeW(p, root):
    return 3                                              # DRIVE_FIXED


@dll(1)
def SetEndOfFile(p, h):
    """Cut the file where the file pointer is."""
    obj = p.handles.get(h)
    if not isinstance(obj, HostFile):
        return _fail(p, 6)
    pos = obj.f.tell()
    obj.f.seek(0)
    keep = obj.f.read(pos)
    obj.f.close()
    with open(obj.path, "wb") as f:
        f.write(keep)
    obj.f = open(obj.path, "r+b")
    obj.f.seek(pos)
    return 1


# ---- searching a folder: FindFirstFileW / FindNextFileW ----

def match(pattern, name):
    """Windows wildcards: * any run of characters, ? any one (case ignored)."""
    pattern, name = pattern.lower(), name.lower()
    if pattern in ("*", "*.*"):
        return True
    p = n = 0
    star, back = -1, 0
    while n < len(name):
        if p < len(pattern) and (pattern[p] == "?" or pattern[p] == name[n]):
            p += 1
            n += 1
        elif p < len(pattern) and pattern[p] == "*":
            star, back = p, n
            p += 1
        elif star >= 0:
            p = star + 1
            back += 1
            n = back
        else:
            return False
    while p < len(pattern) and pattern[p] == "*":
        p += 1
    return p == len(pattern)


class Search:
    def __init__(self, folder, names):
        self.folder, self.names = folder, names

    def close(self):
        pass


def _fill_find_data(out, folder, name):
    try:
        st = os.stat(folder.rstrip("/") + "/" + name)
    except OSError:
        st = (0x8000, 0, 0, 0, 0, 0, 0, 0, 0)
    ft = filetime(st[8])
    mem.zero(out, 592)
    mem.write(out, struct.pack("<IQQQII", _attrs(st), ft, ft, ft, 0, st[6] & 0xFFFFFFFF))
    mem.put_wstr(out + 44, name[:259])


def _find_first(p, pattern, out):
    try:
        host = p.host_path(pattern)
    except OSError:
        p.last_error = 5                                  # ERROR_ACCESS_DENIED
        return INVALID
    folder, _, wild = host.rpartition("/")
    folder = folder or "/"
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        p.last_error = ERROR_PATH_NOT_FOUND
        return INVALID
    if "*" not in wild and "?" not in wild:               # one exact name
        names = [n for n in names if n.lower() == wild.lower()]
    else:
        names = [".", ".."] + names if folder != "/" else names
        names = [n for n in names if match(wild, n)]
    if not names:
        p.last_error = ERROR_FILE_NOT_FOUND
        return INVALID
    _fill_find_data(out, folder, names[0])
    return p.new_handle(Search(folder, names[1:]))


@dll(2)
def FindFirstFileW(p, pattern, out):
    return _find_first(p, mem.wstr(pattern), out)


@dll(2)
def FindFirstFileA(p, pattern, out):
    h = _find_first(p, mem.cstr(pattern), out)
    if h != INVALID:                                      # the A structure has a byte name
        name = mem.wstr(out + 44)
        mem.zero(out + 44, 260)
        mem.put_cstr(out + 44, name[:259])
    return h


@dll(6)
def FindFirstFileExW(p, pattern, level, out, search, filt, flags):
    return _find_first(p, mem.wstr(pattern), out)


@dll(2)
def FindNextFileW(p, h, out):
    s = p.handles.get(h)
    if not isinstance(s, Search) or not s.names:
        return _fail(p, ERROR_NO_MORE_FILES)
    _fill_find_data(out, s.folder, s.names.pop(0))
    return 1


@dll(1)
def FindClose(p, h):
    p.handles.pop(h, None)
    return 1


@dll(4)
def FindFirstStreamW(p, name, level, out, flags):
    p.last_error = 38                                     # ERROR_HANDLE_EOF: no alternate streams
    return INVALID


@dll(4)
def GetFileInformationByHandleEx(p, h, kind, out, size):
    obj = p.handles.get(h)
    if not isinstance(obj, HostFile):
        return _fail(p, 6)
    mem.zero(out, size)
    if kind == 1 and size >= 24:                          # FileStandardInfo
        n = obj.size()
        mem.put64(out, (n + 4095) & ~4095)
        mem.put64(out + 8, n)
        mem.put32(out + 16, 1)
    return 1


@dll(8)
def ReadDirectoryChangesW(p, h, buf, size, subtree, kinds, returned, overlapped, routine):
    return _fail(p, 50)                                   # ERROR_NOT_SUPPORTED: no folder watching


@dll(1)
def CancelIo(p, h):
    return 1


# ---- file times ----

@dll(2)
def CompareFileTime(p, a, b):
    x, y = mem.u64(a), mem.u64(b)
    return (x > y) - (x < y)


def _systemtime(out, t):
    y, mo, d, h, mi, s, wd = t[:7]
    mem.write(out, struct.pack("<8H", y, mo, (wd + 1) % 7, d, h, mi, s, 0))


@dll(2)
def FileTimeToSystemTime(p, ft, out):
    seconds = mem.u64(ft) // 10000000 - EPOCH_1601 + _unix_epoch()
    _systemtime(out, time.localtime(max(0, seconds)))
    return 1


@dll(2)
def FileTimeToLocalFileTime(p, ft, out):
    mem.put64(out, mem.u64(ft))                           # SnakeyOS keeps local time: no shift
    return 1


dll.alias("LocalFileTimeToFileTime", "FileTimeToLocalFileTime")


@dll(2)
def SystemTimeToFileTime(p, st, out):
    y, mo, wd, d, h, mi, s, ms = struct.unpack("<8H", mem.read(st, 16))
    seconds = time.mktime((y, mo, d, h, mi, s, 0, 0)) if hasattr(time, "mktime") else 0
    mem.put64(out, filetime(seconds) + ms * 10000)
    return 1


@dll(3)
def SystemTimeToTzSpecificLocalTime(p, tz, utc, out):
    mem.write(out, mem.read(utc, 16))
    return 1


@dll(1)
def GetTimeZoneInformation(p, out):
    mem.zero(out, 172)
    mem.put_wstr(out + 4, "Hora local")
    mem.put_wstr(out + 88, "Hora local")
    return 0                                               # TIME_ZONE_ID_UNKNOWN


# ---- file mappings: a file (or plain memory) seen as memory ----

class Mapping:
    def __init__(self, file, size, writable):
        self.file, self.size, self.writable = file, size, writable
        self.views = []

    def close(self):
        pass


@dll(6)
def CreateFileMappingW(p, h, security, protect, size_high, size_low, name):
    f = p.handles.get(h)
    size = (size_high << 32) | size_low
    if isinstance(f, HostFile):
        size = size or f.size()
    elif not size:
        return _fail(p, 87)
    writable = protect & 0x0C != 0                         # PAGE_READWRITE / WRITECOPY
    return p.new_handle(Mapping(f if isinstance(f, HostFile) else None, size, writable))


dll.alias("CreateFileMappingA", "CreateFileMappingW")


@dll(3)
def OpenFileMappingW(p, access, inherit, name):
    return _fail(p)                                        # no shared memory between programs


@dll(5)
def MapViewOfFile(p, h, access, off_high, off_low, size):
    m = p.handles.get(h)
    if not isinstance(m, Mapping):
        return _fail(p, 6)
    offset = (off_high << 32) | off_low
    size = size or (m.size - offset)
    addr = p.heap.alloc(size + 1)
    if m.file is not None:
        m.file.seek(offset, 0)
        mem.write(addr, m.file.read(size))
    m.views.append((addr, offset, size))
    p.state.setdefault("views", {})[addr] = m
    return addr


@dll(1)
def UnmapViewOfFile(p, addr):
    m = p.state.get("views", {}).pop(addr, None)
    if m is None:
        return 0
    for view in list(m.views):
        if view[0] == addr:
            m.views.remove(view)
            if m.file is not None and m.writable:          # write the changes back
                m.file.seek(view[1], 0)
                m.file.write(mem.read(addr, view[2]))
    p.heap.free(addr)
    return 1


@dll(2)
def FlushViewOfFile(p, addr, size):
    return 1
