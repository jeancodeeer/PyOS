# ole32.dll and oleaut32.dll: COM, the Windows object system.
# PyWin has no COM objects: initialising works, and asking for an object
# answers "class not registered", so programs take their non-COM path
# (for example the classic Open dialog instead of IFileDialog).
import struct
from pywin import mem
from pywin.dlls import Dll

dll = Dll("ole32")
dll_oleaut32 = Dll("oleaut32")
S_OK, S_FALSE = 0, 1
REGDB_E_CLASSNOTREG, E_NOINTERFACE, CO_E_CLASSSTRING = 0x80040154, 0x80004002, 0x800401F3
DRAGDROP_S_CANCEL = 0x00040101


@dll(1)
def CoInitialize(p, reserved):
    return S_OK


@dll(2)
def CoInitializeEx(p, reserved, flags):
    return S_OK


dll.alias("OleInitialize", "CoInitialize")


@dll(0)
def CoUninitialize(p):
    pass


dll.alias("OleUninitialize", "CoUninitialize")


@dll(5)
def CoCreateInstance(p, clsid, outer, context, iid, out):
    if out:
        mem.put64(out, 0)
    return REGDB_E_CLASSNOTREG


@dll(1)
def CoTaskMemAlloc(p, size):
    return p.heap.alloc(max(1, size))


@dll(1)
def CoTaskMemFree(p, addr):
    if addr:
        p.heap.free(addr)


@dll(2)
def CoTaskMemRealloc(p, addr, size):
    return p.heap.realloc(addr, size)


@dll(2)
def RegisterDragDrop(p, hwnd, target):
    return S_OK


@dll(1)
def RevokeDragDrop(p, hwnd):
    return S_OK


@dll(4)
def DoDragDrop(p, data, source, effects, effect_out):
    if effect_out:
        mem.put32(effect_out, 0)
    return DRAGDROP_S_CANCEL


@dll(1)
def ReleaseStgMedium(p, medium):
    pass


@dll(2)
def CLSIDFromProgID(p, progid, out):
    return CO_E_CLASSSTRING


@dll(2)
def CLSIDFromString(p, text, out):
    return CO_E_CLASSSTRING


def guid_text(raw):
    a, b, c = struct.unpack_from("<IHH", raw)
    d = raw[8:16]
    return "{%08X-%04X-%04X-%02X%02X-%s}" % (a, b, c, d[0], d[1], "".join("%02X" % x for x in d[2:]))


@dll(3)
def StringFromGUID2(p, guid, buf, size):
    text = guid_text(mem.read(guid, 16))
    if size <= len(text):
        return 0
    mem.put_wstr(buf, text)
    return len(text) + 1


@dll(1)
def CoCreateGuid(p, out):
    import crypto
    raw = bytearray(crypto.random_bytes(16))
    raw[7] = (raw[7] & 0x0F) | 0x40                         # version 4: random
    raw[8] = (raw[8] & 0x3F) | 0x80
    mem.write(out, bytes(raw))
    return S_OK


@dll(1)
def OleSetClipboard(p, data):
    return S_OK


@dll(1)
def OleGetClipboard(p, out):
    mem.put64(out, 0)
    return 0x800401D0                                       # CLIPBRD_E_CANT_OPEN


# ---- oleaut32.dll: BSTR strings (a length, then UTF-16 text) ----

def _bstr(p, text_ptr, n):
    block = p.heap.alloc(4 + 2 * n + 2)
    mem.put32(block, 2 * n)
    if text_ptr:
        mem.write(block + 4, mem.read(text_ptr, 2 * n))
    mem.put16(block + 4 + 2 * n, 0)
    return block + 4


@dll_oleaut32(2, "SysAllocStringLen")
def SysAllocStringLen(p, text, n):
    return _bstr(p, text, n)


@dll_oleaut32(1, "SysAllocString")
def SysAllocString(p, text):
    return _bstr(p, text, len(mem.wstr(text) or "")) if text else 0


@dll_oleaut32(1, "SysFreeString")
def SysFreeString(p, bstr):
    if bstr:
        p.heap.free(bstr - 4)


@dll_oleaut32(1, "SysStringLen")
def SysStringLen(p, bstr):
    return mem.u32(bstr - 4) // 2 if bstr else 0


@dll_oleaut32(1, "VariantInit")
def VariantInit(p, v):
    mem.zero(v, 24)


dll_oleaut32.alias("VariantClear", "VariantInit")

# oleaut32 is mostly imported by number
for _number, _name in ((2, "SysAllocString"), (4, "SysAllocStringLen"), (6, "SysFreeString"),
                       (7, "SysStringLen"), (8, "VariantInit"), (9, "VariantClear")):
    dll_oleaut32.alias("#%d" % _number, _name)
