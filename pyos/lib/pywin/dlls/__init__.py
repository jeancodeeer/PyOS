# The Windows DLLs, written in Python.
#
# Each file here is one DLL. A function is declared with the number of
# arguments it takes; PyWin reads them from the CPU registers and the stack:
#
#   from pywin.dlls import Dll
#   kernel32 = Dll("kernel32")
#
#   @kernel32(1)
#   def Sleep(p, ms):            # p is the Process; the result goes back in RAX
#       time.sleep_ms(ms)
#
# A function with a variable number of arguments (printf) takes the fixed
# ones and reads the rest with p.arg(i). kernel32.variable("name", size)
# exports a variable instead of a function.

class Dll:
    def __init__(self, name):
        self.name = name
        self.functions = {}       # name -> (python function, number of arguments)
        self.variables = {}       # name -> (size in bytes, first value)

    def __call__(self, nargs=0, name=None):
        def add(fn):
            self.functions[name or fn.__name__] = (fn, nargs)
            return fn
        return add

    def variable(self, name, size=8, value=0):
        self.variables[name] = (size, value)

    def alias(self, new, old):
        self.functions[new] = self.functions[old]


# DLL names that are served by another one
SAME_AS = {"kernelbase": "kernel32", "ucrtbase": "msvcrt", "msvcr100": "msvcrt", "msvcr110": "msvcrt",
           "msvcr120": "msvcrt", "vcruntime140": "msvcrt", "msvcp_win": "msvcrt", "crtdll": "msvcrt"}
MODULES = ("kernel32", "msvcrt", "user32", "gdi32", "opengl32", "glu32", "advapi32", "shell32", "comdlg32")
_loaded = {}


def base_name(dll):
    n = dll.lower()
    if n.endswith(".dll"):
        n = n[:-4]
    if n.startswith("api-ms-win-crt-"):
        return "msvcrt"
    if n.startswith("api-ms-win-core-"):
        return "kernel32"
    return SAME_AS.get(n, n)


def module(name):
    """The Dll object of a DLL we implement, or None."""
    name = base_name(name)
    if name not in MODULES:
        return None
    if name not in _loaded:
        _loaded[name] = __import__("pywin.dlls." + name, None, None, ["dll"]).dll
    return _loaded[name]


def find(dll, name):
    """(function, nargs), ("data", size, value) or None if PyWin lacks it."""
    m = module(dll)
    if m is None:
        return None
    if name in m.functions:
        return m.functions[name]
    if name in m.variables:
        return ("data",) + m.variables[name]
    return None


def run_atexit(p):
    for fn in reversed(p.state.pop("atexit", [])):
        p.call(fn)
