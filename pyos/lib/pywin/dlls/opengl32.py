# opengl32.dll: OpenGL for Windows programs, drawn by PyOS's own OpenGL
# (pyos/lib/OpenGL). Also the WGL functions that tie it to a window.
#
# Most gl* functions only need their arguments read and passed on, so they
# are described by a "signature", one letter per argument:
#
#   i  int (32 bits, with sign)     u  unsigned int / GLenum
#   f  float (in an XMM register)   d  double
#   3f, 4f, 16f...  a pointer to that many floats (3d: doubles)
#
#   glVertex3f fff   ->   OpenGL.GL.glVertex3f(x, y, z)
#
# A Windows program draws into a back Surface; SwapBuffers copies it to
# its window, so the desktop never shows a half-drawn picture.
import struct
import pygame
from pywin import mem
from pywin.dlls import Dll

dll = Dll("opengl32")

SIGNATURES = """
glClear u           glClearColor ffff     glClearDepth d        glViewport iiii
glMatrixMode u      glLoadIdentity -      glPushMatrix -        glPopMatrix -
glTranslatef fff    glTranslated ddd      glRotatef ffff        glRotated dddd
glScalef fff        glScaled ddd          glOrtho dddddd        glFrustum dddddd
glLoadMatrixf 16f   glLoadMatrixd 16d     glMultMatrixf 16f     glMultMatrixd 16d
glBegin u           glEnd -               glRectf ffff          glRecti iiii
glVertex2f ff       glVertex2d dd         glVertex2i ii         glVertex2fv 2f
glVertex3f fff      glVertex3d ddd        glVertex3i iii        glVertex3fv 3f
glVertex3dv 3d      glVertex4f ffff       glColor3f fff         glColor3d ddd
glColor4f ffff      glColor4d dddd        glColor3ub uuu        glColor4ub uuuu
glColor3fv 3f       glColor4fv 4f         glColor3dv 3d         glNormal3f fff
glNormal3d ddd      glNormal3fv 3f        glTexCoord2f ff       glTexCoord2d dd
glTexCoord2fv 2f    glTexCoord2i ii       glEnable u            glDisable u
glShadeModel u      glCullFace u          glFrontFace u         glDepthFunc u
glDepthMask u       glPolygonMode uu      glLineWidth f         glPointSize f
glHint uu           glBlendFunc uu        glFlush -             glFinish -
glLightfv uu4f      glLightf uuf          glLighti uui          glMaterialfv uu4f
glMaterialf uuf     glMateriali uui       glLightModelfv u4f    glLightModeli ui
glColorMaterial uu  glBindTexture uu      glTexParameteri uui   glTexParameterf uuf
glTexEnvi uui       glTexEnvf uuf         glNewList uu          glEndList -
glCallList u        glDeleteLists ui      glPixelStorei ui      glColorMask uuuu
glScissor iiii      glPolygonOffset ff    glFogi ui             glFogf uf
glLineStipple iu    glAlphaFunc uf        glClearStencil i      glStencilFunc uiu
glStencilOp uuu     glDrawBuffer u        glReadBuffer u        glEnableClientState u
glDisableClientState u
"""


def _gl():
    from OpenGL import GL
    return GL


def _read_args(p, sig):
    """The arguments of the call being handled, as the signature says."""
    out = []
    i = 0
    k = 0
    while k < len(sig):
        n = ""
        while sig[k].isdigit():
            n += sig[k]
            k += 1
        kind = sig[k]
        k += 1
        if n:                                          # a pointer to n numbers
            ptr = p.arg(i)
            size = 4 if kind == "f" else 8
            fmt = "<%d%s" % (int(n), "f" if kind == "f" else "d")
            out.append(list(struct.unpack(fmt, mem.read(ptr, int(n) * size))) if ptr else [0.0] * int(n))
        elif kind == "f":
            out.append(p.arg_float(i))
        elif kind == "d":
            out.append(p.arg_double(i))
        elif kind == "i":
            v = p.arg(i) & 0xFFFFFFFF
            out.append(v - (1 << 32) if v >> 31 else v)
        else:
            out.append(p.arg(i) & 0xFFFFFFFF)
        i += 1
    return out


def _wrap(name, sig):
    def call(p):
        if not bind(p):
            return 0                                   # no context yet: Windows ignores the call
        fn = getattr(_gl(), name)
        args = _read_args(p, sig)
        if name.endswith(("3ub", "4ub")):
            args = [a & 255 for a in args]
        return fn(*args)
    return call


for _line in SIGNATURES.split("\n"):
    _words = _line.split()
    for _k in range(0, len(_words), 2):
        _name, _sig = _words[_k], _words[_k + 1]
        dll.functions[_name] = (_wrap(_name, "" if _sig == "-" else _sig), 0)


# ---- the ones that read or write memory, or return something ----

@dll(1)
def glGetError(p):
    if not bind(p):
        return 0
    return _gl().glGetError()


@dll(1)
def glGetString(p, name):
    if not bind(p):
        return 0
    strings = p.state.setdefault("gl_strings", {})
    if name not in strings:
        text = _gl().glGetString(name & 0xFFFFFFFF)
        addr = p.heap.alloc(len(text) + 1)
        mem.write(addr, text + b"\0")
        strings[name] = addr
    return strings[name]


@dll(1)
def glIsEnabled(p, cap):
    if not bind(p):
        return 0
    return 1 if _gl().glIsEnabled(cap & 0xFFFFFFFF) else 0


@dll(1)
def glGenLists(p, n):
    if not bind(p):
        return 0
    return _gl().glGenLists(n & 0xFFFFFFFF)


@dll(2)
def glGenTextures(p, n, out):
    if not bind(p):
        return 0
    names = _gl().glGenTextures(n)
    for k, name in enumerate([names] if isinstance(names, int) else names):
        mem.put32(out + 4 * k, name)


@dll(2)
def glDeleteTextures(p, n, names):
    if not bind(p):
        return 0
    _gl().glDeleteTextures([mem.u32(names + 4 * k) for k in range(n)])


_CHANNELS = {0x1907: 3, 0x1908: 4, 0x80E0: 3, 0x80E1: 4, 0x1909: 1, 0x1906: 1, 0x190A: 2}


@dll(9)
def glTexImage2D(p, target, level, internal, w, h, border, fmt, kind, pixels):
    if not bind(p):
        return 0
    fmt &= 0xFFFFFFFF
    size = (w & 0xFFFFFFFF) * (h & 0xFFFFFFFF) * _CHANNELS.get(fmt, 4)
    data = mem.read(pixels, size) if pixels else bytes(size)
    _gl().glTexImage2D(target, level, internal, w, h, border, fmt, kind, data)


@dll(2)
def glGetFloatv(p, name, out):
    if not bind(p):
        return 0
    v = _gl().glGetFloatv(name & 0xFFFFFFFF)
    flat = [x for row in v for x in (row if isinstance(row, list) else [row])]
    mem.write(out, struct.pack("<%df" % len(flat), *flat))


@dll(2)
def glGetDoublev(p, name, out):
    if not bind(p):
        return 0
    v = _gl().glGetFloatv(name & 0xFFFFFFFF)
    flat = [x for row in v for x in (row if isinstance(row, list) else [row])]
    mem.write(out, struct.pack("<%dd" % len(flat), *flat))


@dll(2)
def glGetIntegerv(p, name, out):
    if not bind(p):
        return 0
    v = _gl().glGetIntegerv(name & 0xFFFFFFFF)
    values = v if isinstance(v, list) else [v]
    mem.write(out, struct.pack("<%di" % len(values), *[int(x) for x in values]))


@dll(4)
def glVertexPointer(p, size, kind, stride, ptr):
    _client_array(p, "vertex", size, kind, stride, ptr)


@dll(4)
def glColorPointer(p, size, kind, stride, ptr):
    _client_array(p, "color", size, kind, stride, ptr)


@dll(3)
def glNormalPointer(p, kind, stride, ptr):
    _client_array(p, "normal", 3, kind, stride, ptr)


@dll(4)
def glTexCoordPointer(p, size, kind, stride, ptr):
    _client_array(p, "texcoord", size, kind, stride, ptr)


def _client_array(p, which, size, kind, stride, ptr):
    """Remember where an array is; glDrawArrays reads it from the program's memory."""
    p.state.setdefault("gl_arrays", {})[which] = (size, kind & 0xFFFFFFFF, stride, ptr)


_TYPES = {0x1406: ("f", 4), 0x140A: ("d", 8), 0x1404: ("i", 4), 0x1401: ("B", 1), 0x1402: ("h", 2)}


def _element(p, k):
    gl = _gl()
    arrays = p.state.get("gl_arrays", {})
    on = gl._arrays.get("on", set())
    for which, kind_on, fn in (("color", gl.GL_COLOR_ARRAY, gl.glColor), ("normal", gl.GL_NORMAL_ARRAY, gl.glNormal),
                               ("texcoord", gl.GL_TEXTURE_COORD_ARRAY, gl.glTexCoord), ("vertex", None, gl.glVertex)):
        if which not in arrays or (kind_on is not None and kind_on not in on):
            continue
        size, kind, stride, ptr = arrays[which]
        code, width = _TYPES.get(kind, ("f", 4))
        at = ptr + k * (stride or size * width)
        values = struct.unpack("<%d%s" % (size, code), mem.read(at, size * width))
        if which == "color" and code == "B":
            values = [v / 255.0 for v in values]
        fn(*values)


@dll(3)
def glDrawArrays(p, mode, first, count):
    if not bind(p):
        return 0
    gl = _gl()
    gl.glBegin(mode)
    for k in range(first, first + count):
        _element(p, k)
    gl.glEnd()


@dll(4)
def glDrawElements(p, mode, count, kind, indices):
    if not bind(p):
        return 0
    gl = _gl()
    code, width = {0x1401: ("B", 1), 0x1403: ("H", 2), 0x1405: ("I", 4)}.get(kind & 0xFFFFFFFF, ("I", 4))
    gl.glBegin(mode)
    for k in struct.unpack("<%d%s" % (count, code), mem.read(indices, count * width)):
        _element(p, k)
    gl.glEnd()


@dll(2)
def glCallLists(p, n, kind):
    if not bind(p):
        return 0
    ptr = p.arg(2)
    code, width = {0x1401: ("B", 1), 0x1403: ("H", 2), 0x1405: ("I", 4)}.get(kind & 0xFFFFFFFF, ("I", 4))
    for name in struct.unpack("<%d%s" % (n, code), mem.read(ptr, n * width)):
        _gl().glCallList(name)


# ---- WGL: an OpenGL context for a window ----

class RenderContext:
    def __init__(self, wnd):
        from OpenGL import context
        self.wnd = wnd
        self.back = pygame.Surface((wnd.w, wnd.h))
        self.gl = context.Context(self.back)

    def fit(self):
        """Follow the window's size."""
        if (self.wnd.w, self.wnd.h) != self.back.get_size():
            self.back = pygame.Surface((self.wnd.w, self.wnd.h))
            self.gl.retarget(self.back)

    def close(self):
        pass


def bind(p):
    """Make this program's current context the one OpenGL.GL uses.
    False if it has none (before wglMakeCurrent): the call is then ignored."""
    from OpenGL import context
    rc = p.state.get("gl_current")
    if rc is None:
        return False
    if context.current is not rc.gl:
        context.make_current(rc.gl)
    return True


def _window_of(p, hdc):
    from pywin.dlls import gdi32
    dc = gdi32._dc(p, hdc)
    return dc.wnd if dc is not None else None


@dll(1)
def wglCreateContext(p, hdc):
    wnd = _window_of(p, hdc)
    if wnd is None:
        return 0
    return p.new_handle(RenderContext(wnd))


@dll(2)
def wglMakeCurrent(p, hdc, hrc):
    from OpenGL import context
    rc = p.handles.get(hrc)
    if not isinstance(rc, RenderContext):
        p.state["gl_current"] = None
        context.current = None
        return 1
    first = rc.gl.viewport == (0, 0, 0, 0) or not getattr(rc, "used", False)
    rc.fit()
    if first:
        rc.gl.viewport = (0, 0, rc.wnd.w, rc.wnd.h)
        rc.used = True
    p.state["gl_current"] = rc
    p.state.setdefault("gl_dc", {})[hdc] = rc
    context.make_current(rc.gl)
    return 1


@dll(1)
def wglDeleteContext(p, hrc):
    from OpenGL import context
    rc = p.handles.pop(hrc, None)
    if rc is not None and p.state.get("gl_current") is rc:
        p.state["gl_current"] = None
        context.current = None
    return 1


@dll(0)
def wglGetCurrentContext(p):
    rc = p.state.get("gl_current")
    for h, obj in p.handles.items():
        if obj is rc and rc is not None:
            return h
    return 0


@dll(0)
def wglGetCurrentDC(p):
    rc = p.state.get("gl_current")
    for hdc, obj in p.state.get("gl_dc", {}).items():
        if obj is rc:
            return hdc
    return 0


@dll(1)
def wglGetProcAddress(p, name):
    return 0                                 # no extensions


@dll(2)
def wglShareLists(p, a, b):
    return 1


def swap(p, hdc):
    """SwapBuffers: show the picture drawn so far in the window."""
    rc = p.state.get("gl_dc", {}).get(hdc) or p.state.get("gl_current")
    if rc is None:
        return 0
    wnd = rc.wnd
    wnd.surface.blit(rc.back, (0, 0))
    top = wnd
    while top.parent is not None and top.style & 0x40000000:
        top = top.parent
    top.changed = True
    rc.fit()
    return 1


@dll(1)
def wglSwapBuffers(p, hdc):
    return swap(p, hdc)
