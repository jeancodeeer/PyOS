# shell32.dll: opening documents and web pages, and the special folders.
from pywin import mem
from pywin.dlls import Dll

dll = Dll("shell32")

# CSIDL numbers -> folders of the SnakeyOS disk (C:\ is /disk): pywin/winpaths.py


def _folder(csidl):
    from pywin import winpaths
    path = winpaths.folder(csidl)
    return winpaths.windows(path if path is not None else "/disk")


@dll(5)
def SHGetFolderPathA(p, hwnd, csidl, token, flags, out):
    mem.put_cstr(out, _folder(csidl))
    return 0


@dll(5)
def SHGetFolderPathW(p, hwnd, csidl, token, flags, out):
    mem.put_wstr(out, _folder(csidl))
    return 0


@dll(4)
def SHGetSpecialFolderPathA(p, hwnd, out, csidl, create):
    mem.put_cstr(out, _folder(csidl))
    return 1


@dll(4)
def SHGetSpecialFolderPathW(p, hwnd, out, csidl, create):
    mem.put_wstr(out, _folder(csidl))
    return 1


RUNNABLE = (".py", ".exe", ".com", ".bat", ".cmd", ".sh", ".msi", ".scr")
SE_ERR_ACCESSDENIED, SE_ERR_FNF = 5, 2


def _execute(p, what, params):
    """Open a web page, a document or another program, the SnakeyOS way.
    Starting a program (or installing a .py app) needs the user's yes:
    otherwise any Windows program could start others behind their back."""
    low = what.lower()
    if low.startswith(("http://", "https://")):
        opener = getattr(p.ui, "open_url", None)
    elif ":" in low.split("/")[0] and not (len(low) > 1 and low[1] == ":"):
        p.warn("ShellExecute: esquema no permitido: " + what)          # mailto:, ms-settings:, ...
        return SE_ERR_ACCESSDENIED
    else:
        try:
            what = p.host_path(what)
        except OSError:
            return SE_ERR_ACCESSDENIED
        if what.lower().endswith(RUNNABLE):
            name = p.path.rsplit("/", 1)[-1]
            ok = p.ui.choose("Ejecutar programa", "%s quiere ejecutar %s" % (name, what), ["Ejecutar"]) \
                if hasattr(p.ui, "choose") else None
            if ok is None:
                return SE_ERR_ACCESSDENIED
        opener = getattr(p.ui, "open_path", None)
    if opener is None:
        p.ui.write("PyWin: abrir %s\n" % what)
        return 42
    opener(what)
    return 42                                       # > 32: it worked


@dll(6)
def ShellExecuteA(p, hwnd, op, file, params, folder, show):
    return _execute(p, mem.cstr(file) or "", mem.cstr(params) if params else "")


@dll(6)
def ShellExecuteW(p, hwnd, op, file, params, folder, show):
    return _execute(p, mem.wstr(file) or "", mem.wstr(params) if params else "")


@dll(2)
def CommandLineToArgvW(p, line, argc_out):
    text = mem.wstr(line) or ""
    args, cur, quoted = [], "", False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        elif ch == " " and not quoted:
            if cur:
                args.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        args.append(cur)
    table = p.heap.alloc(8 * (len(args) + 1))
    for k, a in enumerate(args):
        s = p.heap.alloc(2 * len(a) + 2)
        mem.put_wstr(s, a)
        mem.put64(table + 8 * k, s)
    mem.put32(argc_out, len(args))
    return table


@dll(2)
def DragAcceptFiles(p, hwnd, accept):
    pass


@dll(2)
def Shell_NotifyIconA(p, message, data):
    return 1


dll.alias("Shell_NotifyIconW", "Shell_NotifyIconA")


# ---- more of shell32 ----

S_OK, E_FAIL, E_NOTIMPL = 0, 0x80004005, 0x80004001


@dll(1)
def ShellExecuteExW(p, info):
    verb, file, params = mem.u64(info + 16), mem.u64(info + 24), mem.u64(info + 32)
    code = _execute(p, mem.wstr(file) if file else "", mem.wstr(params) if params else "")
    mem.put64(info + 56, code)                               # hInstApp
    if mem.u32(info) >= 112:
        mem.put64(info + 104, 0)                             # no process handle to give
    return 1


@dll(4)
def SHCreateItemFromParsingName(p, path, bind, iid, out):
    mem.put64(out, 0)
    return E_NOTIMPL


@dll(5)
def SHParseDisplayName(p, name, bind, out, attrs_in, attrs_out):
    mem.put64(out, 0)
    return E_FAIL


@dll(4)
def SHOpenFolderAndSelectItems(p, folder, n, items, flags):
    return E_FAIL


def _path_list(ptr):
    """A list of paths ended by an empty one (two zero characters)."""
    out = []
    while ptr:
        s = mem.wstr(ptr) or ""
        if not s:
            break
        out.append(s)
        ptr += 2 * (len(s) + 1)
    return out


FO_MOVE, FO_COPY, FO_DELETE, FO_RENAME = 1, 2, 3, 4


@dll(1)
def SHFileOperationW(p, op):
    """Copy, move, rename or delete files (one level, no folders inside folders)."""
    import os
    func = mem.u32(op + 8)
    try:
        sources = [p.host_path(s, write=func != FO_COPY) for s in _path_list(mem.u64(op + 16))]
        targets = [p.host_path(s, write=True) for s in _path_list(mem.u64(op + 24))]
        for k, src in enumerate(sources):
            if func == FO_DELETE:
                os.remove(src)
                continue
            dst = targets[k] if k < len(targets) else (targets[0] if targets else "")
            try:
                if os.stat(dst)[0] & 0x4000:                 # into a folder
                    dst = dst.rstrip("/") + "/" + src.rstrip("/").split("/")[-1]
            except OSError:
                pass
            if func in (FO_MOVE, FO_RENAME):
                os.rename(src, dst)
            elif func == FO_COPY:
                with open(src, "rb") as f, open(dst, "wb") as g:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        g.write(chunk)
    except (OSError, IndexError):
        return 0x7C                                          # DE_INVALIDFILES
    return 0


# ---- files dropped on a window (WM_DROPFILES) ----

@dll(4)
def DragQueryFileW(p, drop, index, buf, size):
    paths = p.handles.get(drop)
    if not isinstance(paths, list):
        return 0
    if index == 0xFFFFFFFF:
        return len(paths)
    if index >= len(paths):
        return 0
    from pywin.process import to_windows
    name = to_windows(paths[index])
    if buf and size:
        mem.put_wstr(buf, name[:size - 1])
    return len(name)


@dll(2)
def DragQueryPoint(p, drop, pt):
    mem.put64(pt, 0)
    return 1


@dll(1)
def DragFinish(p, drop):
    p.handles.pop(drop, None)


@dll(4)
def SHGetKnownFolderPath(p, folder_id, flags, token, out):
    """The path of a known folder, in memory the program frees with CoTaskMemFree."""
    from pywin import winpaths
    path = winpaths.known_folder(winpaths.guid_text(folder_id)) if folder_id else None
    if path is None:
        if out:
            mem.put64(out, 0)
        return E_FAIL
    text = winpaths.windows(path)
    block = p.heap.alloc(2 * len(text) + 2)
    mem.put_wstr(block, text)
    mem.put64(out, block)
    return 0
