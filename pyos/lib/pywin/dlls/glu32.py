# glu32.dll: the OpenGL helpers (cameras, spheres...) for Windows programs,
# passed on to OpenGL.GLU. Same signatures as in opengl32.py; "q" is a
# quadric made by gluNewQuadric.
from pywin.dlls import Dll
from pywin.dlls.opengl32 import _read_args, bind

dll = Dll("glu32")

SIGNATURES = {
    "gluPerspective": "dddd", "gluOrtho2D": "dddd", "gluLookAt": "ddddddddd",
    "gluSphere": "qdii", "gluCylinder": "qdddii", "gluDisk": "qddii", "gluPartialDisk": "qddiidd",
    "gluQuadricDrawStyle": "qu", "gluQuadricNormals": "qu", "gluQuadricTexture": "qu",
    "gluQuadricOrientation": "qu", "gluDeleteQuadric": "q",
}


def _wrap(name, sig):
    def call(p):
        if not bind(p):
            return 0
        from OpenGL import GLU
        args = _read_args(p, sig.replace("q", "u"))
        for k, kind in enumerate(sig):
            if kind == "q":
                args[k] = p.handles.get(p.arg(k))
        return getattr(GLU, name)(*args)
    return call


for _name, _sig in SIGNATURES.items():
    dll.functions[_name] = (_wrap(_name, _sig), 0)


@dll(0)
def gluNewQuadric(p):
    from OpenGL import GLU
    return p.new_handle(GLU.gluNewQuadric())


@dll(7)
def gluBuild2DMipmaps(p, target, internal, w, h, fmt, kind, pixels):
    from pywin.dlls import opengl32
    opengl32.glTexImage2D(p, target, 0, internal, w, h, 0, fmt, kind, pixels)
    return 0


@dll(1)
def gluErrorString(p, code):
    if "glu_error" not in p.state:
        from pywin import mem
        p.state["glu_error"] = p.heap.alloc(16)
        mem.put_cstr(p.state["glu_error"], "no error")
    return p.state["glu_error"]
