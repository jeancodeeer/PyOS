# OpenGL.GL: OpenGL 1.x, as PyOpenGL offers it, drawn by software.
#
#   import pygame
#   from pygame.locals import *
#   from OpenGL.GL import *
#   from OpenGL.GLU import *
#
#   pygame.display.set_mode((640, 480), DOUBLEBUF | OPENGL)
#   gluPerspective(45, 640 / 480, 0.1, 50.0)
#   glTranslatef(0, 0, -5)
#   glBegin(GL_TRIANGLES); glColor3f(1, 0, 0); glVertex3f(0, 1, 0); ...; glEnd()
#   pygame.display.flip()
#
# Each function changes the state in OpenGL/context.py or sends vertices to
# it. Immediate mode (glBegin/glEnd), display lists, vertex arrays, matrices,
# lighting, materials, textures, depth test, culling, wireframe and
# blending are here; shaders and buffer objects (OpenGL 2+) are not.
import math
from OpenGL import context
from OpenGL.context import multiply, identity

# ---- the numbers OpenGL gives names to ----
GL_FALSE, GL_TRUE = 0, 1
GL_POINTS, GL_LINES, GL_LINE_LOOP, GL_LINE_STRIP = 0, 1, 2, 3
GL_TRIANGLES, GL_TRIANGLE_STRIP, GL_TRIANGLE_FAN, GL_QUADS, GL_QUAD_STRIP, GL_POLYGON = 4, 5, 6, 7, 8, 9
GL_DEPTH_BUFFER_BIT, GL_ACCUM_BUFFER_BIT, GL_STENCIL_BUFFER_BIT, GL_COLOR_BUFFER_BIT = 0x100, 0x200, 0x400, 0x4000
GL_MODELVIEW, GL_PROJECTION, GL_TEXTURE = 0x1700, 0x1701, 0x1702
GL_POINT_SMOOTH, GL_LINE_SMOOTH, GL_CULL_FACE, GL_LIGHTING = 0x0B10, 0x0B20, 0x0B44, 0x0B50
GL_LIGHT_MODEL_LOCAL_VIEWER, GL_LIGHT_MODEL_TWO_SIDE, GL_LIGHT_MODEL_AMBIENT = 0x0B51, 0x0B52, 0x0B53
GL_COLOR_MATERIAL, GL_FOG, GL_DEPTH_TEST, GL_STENCIL_TEST, GL_NORMALIZE = 0x0B57, 0x0B60, 0x0B71, 0x0B90, 0x0BA1
GL_ALPHA_TEST, GL_DITHER, GL_BLEND, GL_SCISSOR_TEST, GL_TEXTURE_2D = 0x0BC0, 0x0BD0, 0x0BE2, 0x0C11, 0x0DE1
GL_POLYGON_SMOOTH, GL_POLYGON_OFFSET_FILL, GL_RESCALE_NORMAL, GL_MULTISAMPLE = 0x0B41, 0x8037, 0x803A, 0x809D
GL_TEXTURE_1D, GL_LINE_STIPPLE, GL_AUTO_NORMAL = 0x0DE0, 0x0B24, 0x0D80
GL_LIGHT0, GL_LIGHT1, GL_LIGHT2, GL_LIGHT3 = 0x4000, 0x4001, 0x4002, 0x4003
GL_LIGHT4, GL_LIGHT5, GL_LIGHT6, GL_LIGHT7 = 0x4004, 0x4005, 0x4006, 0x4007
GL_AMBIENT, GL_DIFFUSE, GL_SPECULAR, GL_POSITION, GL_SPOT_DIRECTION = 0x1200, 0x1201, 0x1202, 0x1203, 0x1204
GL_SPOT_EXPONENT, GL_SPOT_CUTOFF, GL_CONSTANT_ATTENUATION = 0x1205, 0x1206, 0x1207
GL_LINEAR_ATTENUATION, GL_QUADRATIC_ATTENUATION = 0x1208, 0x1209
GL_EMISSION, GL_SHININESS, GL_AMBIENT_AND_DIFFUSE = 0x1600, 0x1601, 0x1602
GL_FRONT, GL_BACK, GL_FRONT_AND_BACK, GL_CW, GL_CCW = 0x0404, 0x0405, 0x0408, 0x0900, 0x0901
GL_FLAT, GL_SMOOTH = 0x1D00, 0x1D01
GL_NEVER, GL_LESS, GL_EQUAL, GL_LEQUAL, GL_GREATER, GL_NOTEQUAL, GL_GEQUAL, GL_ALWAYS = range(0x200, 0x208)
GL_POINT, GL_LINE, GL_FILL = 0x1B00, 0x1B01, 0x1B02
GL_ZERO, GL_ONE, GL_SRC_COLOR, GL_ONE_MINUS_SRC_COLOR, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA = 0, 1, 0x300, 0x301, 0x302, 0x303
GL_DST_ALPHA, GL_ONE_MINUS_DST_ALPHA, GL_DST_COLOR, GL_ONE_MINUS_DST_COLOR = 0x304, 0x305, 0x306, 0x307
GL_BYTE, GL_UNSIGNED_BYTE, GL_SHORT, GL_UNSIGNED_SHORT, GL_INT, GL_UNSIGNED_INT, GL_FLOAT, GL_DOUBLE = \
    0x1400, 0x1401, 0x1402, 0x1403, 0x1404, 0x1405, 0x1406, 0x140A
GL_ALPHA, GL_RGB, GL_RGBA, GL_LUMINANCE, GL_LUMINANCE_ALPHA = 0x1906, 0x1907, 0x1908, 0x1909, 0x190A
GL_BGR, GL_BGRA, GL_RGB8, GL_RGBA8 = 0x80E0, 0x80E1, 0x8051, 0x8058
GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T = 0x2800, 0x2801, 0x2802, 0x2803
GL_NEAREST, GL_LINEAR, GL_NEAREST_MIPMAP_NEAREST, GL_LINEAR_MIPMAP_NEAREST = 0x2600, 0x2601, 0x2700, 0x2701
GL_NEAREST_MIPMAP_LINEAR, GL_LINEAR_MIPMAP_LINEAR = 0x2702, 0x2703
GL_CLAMP, GL_REPEAT, GL_CLAMP_TO_EDGE, GL_MIRRORED_REPEAT = 0x2900, 0x2901, 0x812F, 0x8370
GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE, GL_DECAL, GL_REPLACE = 0x2300, 0x2200, 0x2100, 0x2101, 0x1E01
GL_COMPILE, GL_COMPILE_AND_EXECUTE = 0x1300, 0x1301
GL_VENDOR, GL_RENDERER, GL_VERSION, GL_EXTENSIONS = 0x1F00, 0x1F01, 0x1F02, 0x1F03
GL_VIEWPORT, GL_MODELVIEW_MATRIX, GL_PROJECTION_MATRIX, GL_TEXTURE_MATRIX = 0x0BA2, 0x0BA6, 0x0BA7, 0x0BA8
GL_CURRENT_COLOR, GL_MAX_TEXTURE_SIZE, GL_DEPTH_BITS = 0x0B00, 0x0D33, 0x0D56
GL_NO_ERROR, GL_INVALID_ENUM, GL_INVALID_VALUE, GL_INVALID_OPERATION = 0, 0x500, 0x501, 0x502
GL_STACK_OVERFLOW, GL_STACK_UNDERFLOW, GL_OUT_OF_MEMORY = 0x503, 0x504, 0x505
GL_DONT_CARE, GL_FASTEST, GL_NICEST = 0x1100, 0x1101, 0x1102
GL_PERSPECTIVE_CORRECTION_HINT, GL_POINT_SMOOTH_HINT, GL_LINE_SMOOTH_HINT = 0x0C50, 0x0C51, 0x0C52
GL_POLYGON_SMOOTH_HINT, GL_FOG_HINT = 0x0C53, 0x0C54
GL_VERTEX_ARRAY, GL_NORMAL_ARRAY, GL_COLOR_ARRAY, GL_TEXTURE_COORD_ARRAY = 0x8074, 0x8075, 0x8076, 0x8078
GL_UNPACK_ALIGNMENT, GL_PACK_ALIGNMENT = 0x0CF5, 0x0D05
GL_FOG_MODE, GL_FOG_DENSITY, GL_FOG_START, GL_FOG_END, GL_FOG_COLOR, GL_EXP, GL_EXP2 = \
    0x0B65, 0x0B62, 0x0B63, 0x0B64, 0x0B66, 0x0800, 0x0801

# what glEnable's numbers mean to context.py
_CAPS = {GL_DEPTH_TEST: "depth_test", GL_LIGHTING: "lighting", GL_COLOR_MATERIAL: "color_material",
         GL_CULL_FACE: "cull_face", GL_TEXTURE_2D: "texture_2d", GL_BLEND: "blend", GL_NORMALIZE: "normalize"}
_PRIMS = {GL_POINTS: "points", GL_LINES: "lines", GL_LINE_LOOP: "line_loop", GL_LINE_STRIP: "line_strip",
          GL_TRIANGLES: "triangles", GL_TRIANGLE_STRIP: "triangle_strip", GL_TRIANGLE_FAN: "triangle_fan",
          GL_QUADS: "quads", GL_QUAD_STRIP: "quad_strip", GL_POLYGON: "polygon"}
_FACES = {GL_FRONT: "front", GL_BACK: "back", GL_FRONT_AND_BACK: "front_and_back"}


class GLerror(Exception):
    pass


def _c():
    c = context.current
    if c is None:
        raise GLerror("no hay contexto OpenGL: usa pygame.display.set_mode(size, OPENGL)")
    return c


def _rec(fn):
    """Functions that a display list (glNewList) records instead of, or as well as, running."""
    def call(*args):
        c = context.current
        if c is not None and c.recording is not None:
            c.recording[1].append((fn, args))
            if not c.recording[2]:
                return None
        return fn(*args)
    return call


# ---- the frame ----

def glClearColor(r, g, b, a=1.0):
    _c().clear_color = (r, g, b, a)


def glClearDepth(d):
    _c().clear_depth = max(0.0, min(1.0, d))


glClearDepthf = glClearDepth


@_rec
def glClear(mask):
    _c().clear(bool(mask & GL_COLOR_BUFFER_BIT), bool(mask & GL_DEPTH_BUFFER_BIT))


def glViewport(x, y, w, h):
    _c().viewport = (int(x), int(y), int(w), int(h))


def glFlush():
    pass


def glFinish():
    pass


def glGetError():
    c = _c()
    e, c.error = c.error, 0
    return e


def glGetString(name):
    return {GL_VENDOR: b"PyOS", GL_RENDERER: b"PyOS software rasterizer (Python + viper)",
            GL_VERSION: b"1.5 PyOS", GL_EXTENSIONS: b""}.get(name, b"")


def glHint(target, mode):
    pass


# ---- switches ----

@_rec
def glEnable(cap):
    c = _c()
    if GL_LIGHT0 <= cap <= GL_LIGHT7:
        c.lights[cap - GL_LIGHT0].on = True
    elif cap in _CAPS:
        c.enabled.add(_CAPS[cap])


@_rec
def glDisable(cap):
    c = _c()
    if GL_LIGHT0 <= cap <= GL_LIGHT7:
        c.lights[cap - GL_LIGHT0].on = False
    elif cap in _CAPS:
        c.enabled.discard(_CAPS[cap])


def glIsEnabled(cap):
    c = _c()
    if GL_LIGHT0 <= cap <= GL_LIGHT7:
        return c.lights[cap - GL_LIGHT0].on
    return _CAPS.get(cap) in c.enabled


@_rec
def glShadeModel(mode):
    _c().flat = mode == GL_FLAT


@_rec
def glCullFace(mode):
    _c().cull = _FACES.get(mode, "back")


@_rec
def glFrontFace(mode):
    _c().front_ccw = mode == GL_CCW


@_rec
def glDepthFunc(func):
    _c().depth_func_lequal = func in (GL_LEQUAL, GL_EQUAL, GL_ALWAYS)


@_rec
def glDepthMask(flag):
    _c().depth_write = bool(flag)


@_rec
def glPolygonMode(face, mode):
    _c().polygon_line = mode in (GL_LINE, GL_POINT)


@_rec
def glLineWidth(w):
    _c().line_width = max(1, int(w + 0.5))


@_rec
def glPointSize(s):
    _c().point_size = max(1, s)


def glBlendFunc(src, dst):
    pass


def glColorMask(r, g, b, a):
    pass


def glPixelStorei(name, value):
    pass


def glPolygonOffset(factor, units):
    pass


def glFogi(name, value):
    pass


glFogf = glFogfv = glFogiv = glFogi


def glScissor(x, y, w, h):
    pass


def glLineStipple(factor, pattern):
    pass


# ---- matrices ----

_MODES = {GL_MODELVIEW: "modelview", GL_PROJECTION: "projection", GL_TEXTURE: "texture"}


@_rec
def glMatrixMode(mode):
    _c().mode = _MODES.get(mode, "modelview")


@_rec
def glLoadIdentity():
    _c().set_top(identity())


@_rec
def glPushMatrix():
    c = _c()
    stack = c.matrices[c.mode]
    stack.append(list(stack[-1]))


@_rec
def glPopMatrix():
    c = _c()
    stack = c.matrices[c.mode]
    if len(stack) > 1:
        stack.pop()
    else:
        c.error = GL_STACK_UNDERFLOW


def _flat(m):
    """A matrix given as 16 numbers or as 4 rows of 4."""
    if len(m) == 4:
        return [float(v) for col in m for v in col]
    return [float(v) for v in m]


@_rec
def glLoadMatrixf(m):
    _c().set_top(_flat(m))


glLoadMatrixd = glLoadMatrixf


@_rec
def glMultMatrixf(m):
    _c().mult(_flat(m))


glMultMatrixd = glMultMatrixf


@_rec
def glTranslatef(x, y, z):
    _c().mult([1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, x, y, z, 1.0])


glTranslated = glTranslatef


@_rec
def glScalef(x, y, z):
    _c().mult([x, 0.0, 0.0, 0.0, 0.0, y, 0.0, 0.0, 0.0, 0.0, z, 0.0, 0.0, 0.0, 0.0, 1.0])


glScaled = glScalef


@_rec
def glRotatef(angle, x, y, z):
    n = math.sqrt(x * x + y * y + z * z)
    if n == 0:
        return
    x, y, z = x / n, y / n, z / n
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    t = 1 - c
    _c().mult([t * x * x + c, t * x * y + s * z, t * x * z - s * y, 0.0,
               t * x * y - s * z, t * y * y + c, t * y * z + s * x, 0.0,
               t * x * z + s * y, t * y * z - s * x, t * z * z + c, 0.0,
               0.0, 0.0, 0.0, 1.0])


glRotated = glRotatef


@_rec
def glOrtho(left, right, bottom, top, near, far):
    _c().mult([2.0 / (right - left), 0.0, 0.0, 0.0,
               0.0, 2.0 / (top - bottom), 0.0, 0.0,
               0.0, 0.0, -2.0 / (far - near), 0.0,
               -(right + left) / (right - left), -(top + bottom) / (top - bottom), -(far + near) / (far - near), 1.0])


@_rec
def glFrustum(left, right, bottom, top, near, far):
    _c().mult([2.0 * near / (right - left), 0.0, 0.0, 0.0,
               0.0, 2.0 * near / (top - bottom), 0.0, 0.0,
               (right + left) / (right - left), (top + bottom) / (top - bottom), -(far + near) / (far - near), -1.0,
               0.0, 0.0, -2.0 * far * near / (far - near), 0.0])


def glGetFloatv(name):
    c = _c()
    if name in (GL_MODELVIEW_MATRIX, GL_PROJECTION_MATRIX, GL_TEXTURE_MATRIX):
        m = c.matrices[{GL_MODELVIEW_MATRIX: "modelview", GL_PROJECTION_MATRIX: "projection"}.get(name, "texture")][-1]
        return [m[0:4], m[4:8], m[8:12], m[12:16]]
    if name == GL_VIEWPORT:
        return list(c.viewport)
    if name == GL_CURRENT_COLOR:
        return list(c.color)
    return [0.0]


glGetDoublev = glGetFloatv


def glGetIntegerv(name):
    c = _c()
    if name == GL_VIEWPORT:
        return list(c.viewport)
    if name == GL_MAX_TEXTURE_SIZE:
        return 1024
    if name == GL_DEPTH_BITS:
        return 18
    return 0


# ---- vertices ----

@_rec
def glBegin(mode):
    c = _c()
    c.prim = _PRIMS.get(mode)
    c.verts = []


@_rec
def glEnd():
    _c().end()


@_rec
def glVertex(x, y, z=0.0, w=1.0):
    _c().vertex(x, y, z, w)


def glVertexv(v):
    glVertex(*v)


glVertex2f = glVertex2d = glVertex2i = glVertex2s = glVertex
glVertex3f = glVertex3d = glVertex3i = glVertex3s = glVertex
glVertex4f = glVertex4d = glVertex4i = glVertex4s = glVertex
glVertex2fv = glVertex2dv = glVertex2iv = glVertex3fv = glVertex3dv = glVertex3iv = glVertexv
glVertex4fv = glVertex4dv = glVertexv


@_rec
def glColor(r, g=None, b=None, a=1.0):
    if g is None:                                   # glColor((r, g, b))
        return glColor(*r)
    _c().color = (r, g, b, a)


def _ub(r, g, b, a=255):
    glColor(r / 255.0, g / 255.0, b / 255.0, a / 255.0)


glColor3f = glColor3d = glColor4f = glColor4d = glColor
glColor3fv = glColor3dv = glColor4fv = glColor4dv = glColor
glColor3ub = glColor4ub = _ub


def glColor3ubv(v):
    _ub(*v)


glColor4ubv = glColor3ubv


def glColor3i(r, g, b):
    glColor(r / 2147483647.0, g / 2147483647.0, b / 2147483647.0)


@_rec
def glNormal(x, y=None, z=None):
    if y is None:
        x, y, z = x
    _c().normal = (x, y, z)


glNormal3f = glNormal3d = glNormal3i = glNormal3fv = glNormal3dv = glNormal


@_rec
def glTexCoord(s, t=0.0):
    if not isinstance(s, (int, float)):
        s, t = s[0], s[1]
    _c().texcoord = (s, t)


glTexCoord2f = glTexCoord2d = glTexCoord2i = glTexCoord2fv = glTexCoord2dv = glTexCoord
glTexCoord1f = glTexCoord


@_rec
def glRectf(x0, y0, x1, y1):
    glBegin(GL_QUADS)
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        glVertex(x, y)
    glEnd()


glRectd = glRecti = glRectf


# ---- vertex arrays ----

_arrays = {}


def glEnableClientState(kind):
    _arrays.setdefault("on", set()).add(kind)


def glDisableClientState(kind):
    _arrays.setdefault("on", set()).discard(kind)


def _flatten(data):
    out = []
    for item in data:
        if isinstance(item, (int, float)):
            out.append(item)
        else:
            out.extend(item)
    return out


def glVertexPointer(size, kind, stride, data):
    _arrays[GL_VERTEX_ARRAY] = (size, _flatten(data))


def glColorPointer(size, kind, stride, data):
    values = _flatten(data)
    if kind == GL_UNSIGNED_BYTE:
        values = [v / 255.0 for v in values]
    _arrays[GL_COLOR_ARRAY] = (size, values)


def glNormalPointer(kind, stride, data):
    _arrays[GL_NORMAL_ARRAY] = (3, _flatten(data))


def glTexCoordPointer(size, kind, stride, data):
    _arrays[GL_TEXTURE_COORD_ARRAY] = (size, _flatten(data))


glVertexPointerf = lambda data: glVertexPointer(len(data[0]), GL_FLOAT, 0, data)   # noqa: E731
glColorPointerf = lambda data: glColorPointer(len(data[0]), GL_FLOAT, 0, data)     # noqa: E731


def _element(i):
    on = _arrays.get("on", set())
    for kind, fn in ((GL_COLOR_ARRAY, glColor), (GL_NORMAL_ARRAY, glNormal), (GL_TEXTURE_COORD_ARRAY, glTexCoord)):
        if kind in on and kind in _arrays:
            size, values = _arrays[kind]
            fn(*values[i * size:i * size + size])
    size, values = _arrays[GL_VERTEX_ARRAY]
    glVertex(*values[i * size:i * size + size])


def glArrayElement(i):
    _element(i)


def glDrawArrays(mode, first, count):
    glBegin(mode)
    for i in range(first, first + count):
        _element(i)
    glEnd()


def glDrawElements(mode, count, kind, indices):
    glBegin(mode)
    for i in list(_flatten(indices))[:count]:
        _element(int(i))
    glEnd()


# ---- lights and materials ----

def _vec4(v):
    if isinstance(v, (int, float)):
        return (float(v), 0.0, 0.0, 1.0)
    v = [float(x) for x in v] + [0.0, 0.0, 0.0, 1.0][len(v):]
    return tuple(v[:4])


@_rec
def glLightfv(light, name, value):
    c = _c()
    L = c.lights[light - GL_LIGHT0]
    v = _vec4(value)
    if name == GL_POSITION:                  # kept in eye space, as OpenGL does
        L.position = context.transform(c.modelview(), v[0], v[1], v[2], v[3])
    elif name == GL_AMBIENT:
        L.ambient = v
    elif name == GL_DIFFUSE:
        L.diffuse = v
    elif name == GL_SPECULAR:
        L.specular = v


glLightf = glLighti = glLightiv = glLightfv


@_rec
def glLightModelfv(name, value):
    if name == GL_LIGHT_MODEL_AMBIENT:
        _c().light_ambient = _vec4(value)


glLightModelf = glLightModeli = glLightModeliv = glLightModelfv


@_rec
def glMaterialfv(face, name, value):
    m = _c().material
    if name == GL_SHININESS:
        m.shininess = float(value if isinstance(value, (int, float)) else value[0])
        return
    v = _vec4(value)
    if name in (GL_AMBIENT, GL_AMBIENT_AND_DIFFUSE):
        m.ambient = v
    if name in (GL_DIFFUSE, GL_AMBIENT_AND_DIFFUSE):
        m.diffuse = v
    if name == GL_SPECULAR:
        m.specular = v
    if name == GL_EMISSION:
        m.emission = v


glMaterialf = glMateriali = glMaterialiv = glMaterialfv


@_rec
def glColorMaterial(face, mode):
    _c().color_material = (_FACES.get(face, "front_and_back"),
                           {GL_AMBIENT: "ambient", GL_DIFFUSE: "diffuse", GL_SPECULAR: "specular",
                            GL_EMISSION: "emission"}.get(mode, "ambient_and_diffuse"))


# ---- textures ----

def glGenTextures(n):
    c = _c()
    names = list(range(c.next_texture, c.next_texture + n))
    c.next_texture += n
    for k in names:
        c.textures[k] = context.Texture()
    return names[0] if n == 1 else names


def glDeleteTextures(names):
    c = _c()
    for k in ([names] if isinstance(names, int) else names):
        if k:
            c.textures.pop(k, None)


@_rec
def glBindTexture(target, name):
    c = _c()
    if name not in c.textures:
        c.textures[name] = context.Texture()
    c.texture = name


def glTexParameteri(target, name, value):
    pass


glTexParameterf = glTexParameteriv = glTexParameterfv = glTexParameteri


@_rec
def glTexEnvi(target, name, value):
    if name == GL_TEXTURE_ENV_MODE:
        _c().modulate = value == GL_MODULATE


glTexEnvf = glTexEnviv = glTexEnvfv = glTexEnvi


def _pow2(n):
    p = 1
    while p < n and p < 1024:
        p *= 2
    return p


def glTexImage2D(target, level, internal, w, h, border, fmt, kind, data):
    """Load a picture into the bound texture: data has w x h pixels in fmt
    (GL_RGB, GL_RGBA, GL_BGR(A), GL_LUMINANCE), one byte per channel."""
    if level:
        return                                       # mipmaps: the first level is enough
    c = _c()
    tex = c.textures.setdefault(c.texture, context.Texture())
    src = bytes(data) if not isinstance(data, (bytes, bytearray)) else data
    n = {GL_RGB: 3, GL_BGR: 3, GL_RGBA: 4, GL_BGRA: 4, GL_LUMINANCE: 1, GL_ALPHA: 1, GL_LUMINANCE_ALPHA: 2}.get(fmt, 4)
    tw, th = _pow2(w), _pow2(h)
    out = bytearray(tw * th * 4)
    if n == 4 and fmt == GL_RGBA and (tw, th) == (w, h):
        out[:] = src[:tw * th * 4]
    elif n == 3 and fmt == GL_RGB and (tw, th) == (w, h):
        from OpenGL import raster
        raster.rgb_to_rgba(src, out, w * h)
    else:                                            # any other case: pixel by pixel, resized
        for y in range(th):
            sy = y * h // th
            for x in range(tw):
                i = (sy * w + x * w // tw) * n
                o = (y * tw + x) * 4
                if n >= 3:
                    r, g, b = src[i], src[i + 1], src[i + 2]
                    if fmt in (GL_BGR, GL_BGRA):
                        r, b = b, r
                    out[o:o + 4] = bytes((r, g, b, src[i + 3] if n == 4 else 255))
                else:
                    out[o:o + 4] = bytes((src[i], src[i], src[i], 255))
    tex.w, tex.h, tex.pixels = tw, th, out


def glTexSubImage2D(*args):
    pass


# ---- display lists ----

def glGenLists(n):
    c = _c()
    first = c.next_list
    c.next_list += n
    return first


def glNewList(n, mode):
    _c().recording = (n, [], mode == GL_COMPILE_AND_EXECUTE)


def glEndList():
    c = _c()
    if c.recording is not None:
        n, calls, _ = c.recording
        c.lists[n] = calls
        c.recording = None


def glCallList(n):
    c = _c()
    if c.recording is not None:
        c.recording[1].append((glCallList, (n,)))
        if not c.recording[2]:
            return
    for fn, args in c.lists.get(n, ()):
        fn(*args)


def glCallLists(names):
    for n in names:
        glCallList(n)


def glDeleteLists(first, count):
    c = _c()
    for n in range(first, first + count):
        c.lists.pop(n, None)


def glIsList(n):
    return n in _c().lists


# ---- accepted but without effect here (no stencil buffer, one colour buffer) ----

def glAlphaFunc(func, ref):
    pass


def glClearStencil(s):
    pass


def glStencilFunc(func, ref, mask):
    pass


def glStencilOp(fail, zfail, zpass):
    pass


def glDrawBuffer(mode):
    pass


glReadBuffer = glDrawBuffer
