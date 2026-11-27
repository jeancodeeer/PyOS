"""PyWin and OpenGL checks: boot PyKernel + SnakeyOS in QEMU, run the example
Windows programs and draw with OpenGL into a Surface.

    python tools/test_pywin.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402
from run import make_disk  # noqa: E402

check = T.check

GL_SCRIPT = r"""
import pygame
from OpenGL import context
from OpenGL.GL import *
from OpenGL.GLU import *
surf = pygame.Surface((64, 64))
context.attach(surf)
glClearColor(0, 0, 1, 1)
glEnable(GL_DEPTH_TEST)
glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
glMatrixMode(GL_PROJECTION); gluPerspective(60, 1, 0.1, 10); glMatrixMode(GL_MODELVIEW)
glTranslatef(0, 0, -3)
glBegin(GL_QUADS); glColor3f(1, 0, 0)
for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1)): glVertex3f(x, y, 0)
glEnd()
glBegin(GL_TRIANGLES); glColor3f(0, 1, 0)
for x, y in ((-0.3, -0.3), (0.3, -0.3), (0, 0.3)): glVertex3f(x, y, -1)
glEnd()
gl = (tuple(surf.get_at((32, 32))[:3]), tuple(surf.get_at((2, 2))[:3]))
"""


DESKTOP_SCRIPT = r"""
from desktop import wm
from pywin import host
R = {}
H = {}
def start(name):
    H[name] = host.start('/share/pywin/ejemplos/' + name)
def app(title):
    for w in wm.wm.windows:
        if title in w.title:
            return w.app
#---
def type_and_menu():
    from pywin.dlls import user32
    s = user32.state(H['notas.exe'].p)
    for ch in 'Hola desde PyWin':
        s.post(s.focus, 0x102, ord(ch), 1)
    app('Notas').menu_click((12, 8))
def save():
    m = wm.wm.menu
    R['menu'] = [i[0].strip() for i in m.items if i]
    wm.wm.menu = None
    [i for i in m.items if i and 'Guardar' in i[0]][0][1]()
def answer():
    d = wm.wm.dialog
    d.field.text = '/disk/Documentos/prueba_notas.txt'
    d.done(True)
#---
def look():
    R['file'] = open('/disk/Documentos/prueba_notas.txt').read()
    R['reg'] = open('/disk/pywin/registro.json').read()
    a = app('OpenGL en PyWin')
    s = a.wnd.surface
    w, h = s.get_size()
    R['gl'] = len(set(tuple(s.get_at((x, h // 2))[:3]) for x in range(0, w, 8))) > 4
wm.SCRIPT = [(800, lambda: start('notas.exe')), (3000, type_and_menu), (4500, save), (6000, answer),
             (7000, lambda: start('cubo_gl.exe')), (14000, look), (15000, lambda: setattr(wm.wm, 'running', False))]
"""


def dll_argument_counts():
    """Every Windows function written in Python says how many arguments it
    takes (@dll(n)); a wrong n crashes the program that calls it."""
    import ast
    wrong = []
    for path in sorted((ROOT / "pyos" / "lib" / "pywin" / "dlls").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef):
                for d in node.decorator_list:
                    if (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id.startswith("dll")
                            and d.args and isinstance(d.args[0], ast.Constant) and node.args.vararg is None
                            and len(node.args.args) - 1 != d.args[0].value):
                        wrong.append("%s:%s" % (path.name, node.name))
    return wrong


def main():
    wrong = dll_argument_counts()
    check("DLL functions take the number of arguments they declare", not wrong, wrong)
    subprocess.run([sys.executable, str(ROOT / "tools" / "build.py"), "--fs"], check=True, capture_output=True)
    m = T.Machine(make_disk(ROOT / "build" / "test-disk.img"))
    try:
        m.until(T.PROMPT, 90)
        m.cmd("import pywin", 30)
        out = m.cmd("pywin.run('/share/pywin/ejemplos/hola.exe', ['uno'], cwd='/disk')", 60)
        check("console .exe: printf, malloc, files, a native loop", "Hola desde un .exe de Windows!" in out
              and "leido: escrito por un exe" in out and "bucle nativo: 2999998" in out, out)
        check("... and its exit code", m.cmd("pywin.process.Process('/share/pywin/ejemplos/hola.exe', cwd='/disk').run()",
                                             60).strip().endswith("7"), "")
        m.cmd("class UI(pywin.process.Console):\n    lines = ['Ana\\n', '30\\n']\n    def read_line(self):\n"
              "        return self.lines.pop(0) if self.lines else ''\n", 10)
        out = m.cmd("pywin.run('/share/pywin/ejemplos/entrada.exe', ui=UI())", 60)
        check("scanf reads the keyboard", "Hola Ana, en 10 anos tendras 40." in out, out)
        out = m.cmd("pywin.run('/share/pywin/ejemplos/cpp.exe')", 90)
        check("C++: STL and throw/catch", "C++ en PyWin: 1 3 5 7 9" in out and "excepcion capturada" in out, out)
        out = m.cmd("pywin.run('/share/pywin/ejemplos/mensaje.exe')", 60)
        check("MessageBoxA (text mode)", "[PyWin] Hola desde Win32" in out, out)
        out = m.cmd("pywin.run('/share/pywin/ejemplos/hilos.exe')", 90)
        check("threads: CreateThread, events, critical sections, WaitForMultipleObjects",
              "total = 4000 (esperado 4000), codigos = 406" in out, out)
        out = m.cmd("pywin.run('/share/pywin/ejemplos/usadll.exe')", 60)
        check("the program's own DLL: import table, DllMain, LoadLibrary + GetProcAddress",
              "[milib.dll] cargada" in out and "suma(20, 22) = 42" in out and "contador() = 1" in out, out)
        out = m.cmd("pywin.run('/share/pywin/ejemplos/colores.exe')", 60)
        check("console colours, the registry and special folders", "registro: Numero = 7" in out
              and "Documentos: C:\\Documentos" in out and "\x1b[91m" in out, out)
        out = m.cmd("from desktop.apps.pywin import check as c, find_programs as f; "
                    "[(p.rsplit('/', 1)[-1], c(p)['missing']) for p in f() if '/ejemplos/' in p]", 120)
        check("PyWin has every function the example programs use",
              out.count(", [])") >= 11 and "', ['" not in out, out)
        piece = ""
        for line in GL_SCRIPT.strip().splitlines(True):
            if len(piece) + len(line) > 400 and not line.startswith(" "):
                m.cmd("exec(%r)" % piece, 60)
                piece = ""
            piece += line
        m.cmd("exec(%r)" % piece, 60)
        out = m.cmd("gl", 20)
        check("OpenGL: depth test keeps the near quad, clear colour around it",
              "((255, 0, 0), (0, 0, 255))" in out, out)
        # on the desktop: a Win32 menu from resources, the Save dialog, and OpenGL for Windows
        for line in DESKTOP_SCRIPT.strip().split("\n#---\n"):
            m.cmd("exec(%r)" % line, 30)
        m.send(b"desktop\r")
        m.until(T.PROMPT, 120)
        m.cmd("", 10)
        out = m.cmd("R", 20)
        check("desktop: the notepad's menu (from its resources) has its items", "'Guardar como...'" in out, out)
        check("desktop: Save as dialog, file written, registry updated", "'Hola desde PyWin'" in out
              and "prueba_notas.txt" in out, out)
        check("desktop: an OpenGL program for Windows draws in its window", "'gl': True" in out, out)
    except TimeoutError as e:
        check("no timeout", False, str(e)[-1500:])
    finally:
        m.close()
    print("\n%d/%d PyWin/OpenGL checks passed" % (sum(T.CHECKS), len(T.CHECKS)))
    sys.exit(0 if all(T.CHECKS) else 1)


if __name__ == "__main__":
    main()
