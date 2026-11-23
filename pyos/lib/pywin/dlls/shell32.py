# shell32.dll: opening documents and web pages, and the special folders.
from pywin import mem
from pywin.dlls import Dll

dll = Dll("shell32")

# CSIDL numbers -> folders of the PyOS disk (C:\ is /disk)
FOLDERS = {0x00: "Escritorio", 0x10: "Escritorio", 0x05: "Documentos", 0x0D: "Musica", 0x27: "Imagenes",
           0x1A: "AppData", 0x1C: "AppData", 0x23: "AppData", 0x28: "", 0x26: "Programas", 0x24: "Windows",
           0x25: "Windows"}


def _folder(csidl):
    import os
    name = FOLDERS.get(csidl & 0xFF, "")
    path = "/disk/" + name if name else "/disk"
    try:
        os.mkdir(path)
    except OSError:
        pass
    from pywin.process import to_windows
    return to_windows(path)


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


def _execute(p, what, params):
    """Open a web page, a document or another program, the PyOS way."""
    if what.lower().startswith(("http://", "https://")):
        opener = getattr(p.ui, "open_url", None)
    else:
        what = p.host_path(what)
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
