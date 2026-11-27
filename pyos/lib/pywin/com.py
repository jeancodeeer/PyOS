# COM objects written in Python, for Windows programs: a block of memory
# with one vtable pointer per interface, each vtable full of thunks into
# Python methods. Vtables are made once per class and process (thunks are few).
#
#   class Thing(ComClass):
#       INTERFACES = [(("00000000-0000-0000-c000-000000000046", ...), ("QueryInterface", 3), ...)]
#   addr = Thing(p).addr        # what CoCreateInstance hands to the program
import struct
from pywin import mem

IID_IUNKNOWN = "00000000-0000-0000-c000-000000000046"
S_OK, E_NOINTERFACE, E_POINTER, E_NOTIMPL = 0, 0x80004002, 0x80004003, 0x80004001


class ComClass:
    INTERFACES = []         # [(iids, [(method name, number of arguments with `this`)])]

    def __init__(self, p):
        self.p = p
        self.refs = 1
        n = len(self.INTERFACES)
        self.addr = p.heap.alloc(8 * n + 8)
        objects = p.state.setdefault("com", {})
        tables = p.state.setdefault("com_vtables", {})
        key = type(self).__name__
        if key not in tables:
            tables[key] = [self._make_vtable(k) for k in range(n)]
        for k in range(n):
            mem.put64(self.addr + 8 * k, tables[key][k])
            objects[self.addr + 8 * k] = (self, k)

    def _make_vtable(self, k):
        p = self.p
        iids, methods = self.INTERFACES[k]
        vt = p.heap.alloc(8 * len(methods))
        cls = type(self)
        for j, (name, nargs) in enumerate(methods):
            def handler(proc, this, *args, name=name):
                found = proc.state.get("com", {}).get(this)
                if found is None:
                    return E_POINTER
                obj, iface = found
                return getattr(obj, name)(iface, *args)
            mem.put64(vt + 8 * j, p._thunk(handler, nargs, "%s::%s" % (cls.__name__, name))[1])
        return vt

    # ---- IUnknown, the same for every interface ----
    def QueryInterface(self, iface, riid, out):
        from pywin import winpaths
        if not out:
            return E_POINTER
        want = winpaths.guid_text(riid)
        for k, (iids, _) in enumerate(self.INTERFACES):
            if want in iids or want == IID_IUNKNOWN and k == 0:
                mem.put64(out, self.addr + 8 * k)
                self.refs += 1
                return S_OK
        mem.put64(out, 0)
        return E_NOINTERFACE

    def AddRef(self, iface):
        self.refs += 1
        return self.refs

    def Release(self, iface):
        self.refs -= 1
        if self.refs <= 0:
            objects = self.p.state.get("com", {})
            for k in range(len(self.INTERFACES)):
                objects.pop(self.addr + 8 * k, None)
            self.closed()
            return 0
        return self.refs

    def closed(self):
        pass


UNKNOWN = [("QueryInterface", 3), ("AddRef", 1), ("Release", 1)]


def guid_bytes(text):
    """'xxxxxxxx-xxxx-...' -> the 16 bytes of the GUID in memory."""
    t = text.strip("{}").replace("-", "")
    d1, d2, d3 = int(t[0:8], 16), int(t[8:12], 16), int(t[12:16], 16)
    return struct.pack("<IHH", d1, d2, d3) + bytes(int(t[16 + 2 * i:18 + 2 * i], 16) for i in range(8))
