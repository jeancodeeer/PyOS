# uxtheme.dll and dwmapi.dll: visual styles and the desktop compositor.
# PyWin draws controls in one plain style, so there are no themes: programs
# ask, get "no theme", and draw the classic way themselves.
from pywin import mem
from pywin.dlls import Dll

dll = Dll("uxtheme")
dll_dwmapi = Dll("dwmapi")
S_OK, E_FAIL, E_NOTIMPL = 0, 0x80004005, 0x80004001


@dll(2)
def OpenThemeData(p, hwnd, classes):
    return 0                                       # no theme for this window


dll.alias("OpenThemeDataForDpi", "OpenThemeData")


@dll(1)
def CloseThemeData(p, theme):
    return S_OK


@dll(3)
def SetWindowTheme(p, hwnd, app_name, id_list):
    return S_OK


@dll(2)
def EnableThemeDialogTexture(p, hwnd, flags):
    return S_OK


@dll(0)
def IsThemeActive(p):
    return 0


dll.alias("IsAppThemed", "IsThemeActive")


for _name, _n in (("GetThemeColor", 5), ("GetThemeFont", 6), ("GetThemeBackgroundContentRect", 6),
                  ("GetThemePartSize", 7), ("DrawThemeBackground", 6), ("DrawThemeTextEx", 9),
                  ("DrawThemeParentBackground", 3), ("GetThemeTransitionDuration", 6)):
    dll.functions[_name] = ((lambda p, *a: E_FAIL), _n)


@dll(8)
def BeginBufferedAnimation(p, hwnd, hdc, rect, fmt, params, anim, from_dc, to_dc):
    return 0                                       # no animation: the program paints directly


@dll(2)
def EndBufferedAnimation(p, anim, update):
    return S_OK


@dll(2)
def BufferedPaintRenderAnimation(p, hwnd, hdc):
    return 0


@dll(1)
def BufferedPaintStopAllAnimations(p, hwnd):
    return S_OK


@dll(0)
def BufferedPaintInit(p):
    return S_OK


dll.alias("BufferedPaintUnInit", "BufferedPaintInit")


# ---- dwmapi.dll ----

@dll_dwmapi(2)
def DwmGetColorizationColor(p, color, opaque):
    mem.put32(color, 0xC40078D7)                   # Windows blue, mostly opaque
    if opaque:
        mem.put32(opaque, 1)
    return S_OK


@dll_dwmapi(4)
def DwmSetWindowAttribute(p, hwnd, attr, value, size):
    return S_OK


@dll_dwmapi(4)
def DwmGetWindowAttribute(p, hwnd, attr, value, size):
    return E_NOTIMPL


@dll_dwmapi(1)
def DwmIsCompositionEnabled(p, out):
    mem.put32(out, 0)
    return S_OK


@dll_dwmapi(2)
def DwmExtendFrameIntoClientArea(p, hwnd, margins):
    return S_OK
