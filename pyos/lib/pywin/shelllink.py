# CLSID_ShellLink: the COM object installers use to make shortcuts
# (IShellLinkW / IShellLinkA to fill it in, IPersistFile to save it as .lnk).
# The interfaces and the order of their methods are Windows' (as in Wine's
# dlls/shell32/shelllink.c, LGPL 2.1); the .lnk itself is pywin/shortcut.py.
from pywin import mem, shortcut
from pywin.com import ComClass, UNKNOWN, S_OK, E_NOTIMPL

CLSID = "00021401-0000-0000-c000-000000000046"
IID_ISHELLLINKW = "000214f9-0000-0000-c000-000000000046"
IID_ISHELLLINKA = "000214ee-0000-0000-c000-000000000046"
IID_IPERSISTFILE = "0000010b-0000-0000-c000-000000000046"
IID_IPERSIST = "0000010c-0000-0000-c000-000000000046"

LINK_METHODS = UNKNOWN + [("GetPath", 5), ("GetIDList", 2), ("SetIDList", 2), ("GetDescription", 3),
                          ("SetDescription", 2), ("GetWorkingDirectory", 3), ("SetWorkingDirectory", 2),
                          ("GetArguments", 3), ("SetArguments", 2), ("GetHotkey", 2), ("SetHotkey", 2),
                          ("GetShowCmd", 2), ("SetShowCmd", 2), ("GetIconLocation", 4), ("SetIconLocation", 3),
                          ("SetRelativePath", 3), ("Resolve", 3), ("SetPath", 2)]
FILE_METHODS = UNKNOWN + [("GetClassID", 2), ("IsDirty", 1), ("Load", 3), ("Save", 3), ("SaveCompleted", 2),
                          ("GetCurFile", 2)]
WIDE = (0,)                 # interface numbers whose strings are UTF-16 (IShellLinkW)


class ShellLink(ComClass):
    INTERFACES = [((IID_ISHELLLINKW,), LINK_METHODS), ((IID_IPERSISTFILE, IID_IPERSIST), FILE_METHODS),
                  ((IID_ISHELLLINKA,), LINK_METHODS)]

    def __init__(self, p):
        ComClass.__init__(self, p)
        self.f = {"target": "", "arguments": "", "workdir": "", "description": "", "icon": "", "icon_index": 0,
                  "show": 1, "hotkey": 0}
        self.file = None

    # strings in and out, wide or not by interface
    def _get(self, iface, addr):
        if not addr:
            return ""
        return mem.wstr(addr) if iface in WIDE else mem.cstr(addr)

    def _put(self, iface, addr, size, text):
        if not addr or size <= 0:
            return
        text = text[:size - 1]
        if iface in WIDE:
            mem.put_wstr(addr, text)
        else:
            mem.put_cstr(addr, text)

    def GetPath(self, iface, buf, size, find_data, flags):
        self._put(iface, buf, size, self.f["target"])
        return S_OK if self.f["target"] else 1

    def GetIDList(self, iface, out):
        if out:
            mem.put64(out, 0)
        return E_NOTIMPL

    def SetIDList(self, iface, pidl):
        return E_NOTIMPL

    def GetDescription(self, iface, buf, size):
        self._put(iface, buf, size, self.f["description"])
        return S_OK

    def SetDescription(self, iface, text):
        self.f["description"] = self._get(iface, text)
        return S_OK

    def GetWorkingDirectory(self, iface, buf, size):
        self._put(iface, buf, size, self.f["workdir"])
        return S_OK

    def SetWorkingDirectory(self, iface, text):
        self.f["workdir"] = self._get(iface, text)
        return S_OK

    def GetArguments(self, iface, buf, size):
        self._put(iface, buf, size, self.f["arguments"])
        return S_OK

    def SetArguments(self, iface, text):
        self.f["arguments"] = self._get(iface, text)
        return S_OK

    def GetHotkey(self, iface, out):
        if out:
            mem.put16(out, self.f["hotkey"])
        return S_OK

    def SetHotkey(self, iface, key):
        self.f["hotkey"] = key & 0xFFFF
        return S_OK

    def GetShowCmd(self, iface, out):
        if out:
            mem.put32(out, self.f["show"])
        return S_OK

    def SetShowCmd(self, iface, show):
        self.f["show"] = show & 0xFFFFFFFF
        return S_OK

    def GetIconLocation(self, iface, buf, size, index):
        self._put(iface, buf, size, self.f["icon"])
        if index:
            mem.put32(index, self.f["icon_index"] & 0xFFFFFFFF)
        return S_OK

    def SetIconLocation(self, iface, text, index):
        self.f["icon"] = self._get(iface, text)
        self.f["icon_index"] = index if index < 0x80000000 else index - (1 << 32)
        return S_OK

    def SetRelativePath(self, iface, text, reserved):
        return S_OK

    def Resolve(self, iface, hwnd, flags):
        return S_OK

    def SetPath(self, iface, text):
        from pywin import winpaths
        self.f["target"] = winpaths.expand(self._get(iface, text))
        return S_OK

    # IPersistFile
    def GetClassID(self, iface, out):
        from pywin.com import guid_bytes
        if out:
            mem.write(out, guid_bytes(CLSID))
        return S_OK

    def IsDirty(self, iface):
        return S_OK

    def Load(self, iface, name, mode):
        from pywin.process import to_host
        path = to_host(mem.wstr(name))
        try:
            with open(path, "rb") as fh:
                self.f.update(shortcut.read(fh.read()))
            self.file = path
            return S_OK
        except (OSError, ValueError):
            return 0x80070002                          # file not found

    def Save(self, iface, name, remember):
        from pywin.process import to_host, allowed
        path = to_host(mem.wstr(name)) if name else self.file
        if not path or not allowed(path, write=True):
            return 0x80070005                          # access denied
        folder = path.rsplit("/", 1)[0]
        from pywin import winpaths
        winpaths._make(folder)
        f = self.f
        data = shortcut.write(f["target"], f["arguments"], f["workdir"], f["description"], f["icon"],
                              f["icon_index"], f["show"], f["hotkey"])
        try:
            with open(path, "wb") as fh:
                fh.write(data)
        except OSError:
            return 0x80004005
        if remember:
            self.file = path
        try:
            from pywin import install
            install.changed()                          # the launcher shows the new shortcut
        except Exception:
            pass
        return S_OK

    def SaveCompleted(self, iface, name):
        return S_OK

    def GetCurFile(self, iface, out):
        if out:
            mem.put64(out, 0)
        return 1


CLASSES = {CLSID: ShellLink}
