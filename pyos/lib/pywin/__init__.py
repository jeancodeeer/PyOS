# PyWin: run Windows programs (.exe) on PyOS, a little like Wine.
#
#   import pywin
#   pywin.run("/disk/hola.exe")            # from the PyKernel prompt
#   pywin.run("/disk/hola.exe", ["arg"], ui=my_console)
#
# The program's own machine code runs directly on the processor. Every
# Windows function it uses (kernel32, msvcrt, user32...) is written in
# Python in pywin/dlls/. See pyos/README.md, "PyWin".
from pywin.process import Process, Exit, to_host, to_windows

VERSION = "1.0"


def run(path, args=(), ui=None, cwd=None):
    """Run a Windows program until it ends; returns its exit code."""
    return Process(path, args, ui=ui, cwd=cwd).run()


def info(path):
    """What kind of program an .exe is, without running it."""
    from pywin import pe
    with open(path, "rb") as f:
        img = pe.Image(f.read())
    return {"console": img.console, "dll": img.is_dll, "entry": img.entry, "size": img.size,
            "sections": [s.name for s in img.sections]}
