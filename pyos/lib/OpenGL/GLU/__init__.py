# OpenGL.GLU: the helpers around OpenGL (cameras and round shapes).
#
#   gluPerspective(45, w / h, 0.1, 100)      a camera with perspective
#   gluLookAt(eye..., centre..., up...)      point it
#   q = gluNewQuadric(); gluSphere(q, 1, 24, 16)
import math
from OpenGL import context
from OpenGL.GL import (glMultMatrixf, glTranslatef, glOrtho, glBegin, glEnd, glVertex3f, glNormal3f,
                       glTexCoord2f, GL_QUAD_STRIP, GL_LINE_STRIP, GL_LINES, GL_POINTS, glTexImage2D)

GLU_FILL, GLU_LINE, GLU_POINT, GLU_SILHOUETTE = 100012, 100011, 100010, 100013
GLU_SMOOTH, GLU_FLAT, GLU_NONE = 100000, 100001, 100002
GLU_OUTSIDE, GLU_INSIDE = 100020, 100021
GLU_TRUE, GLU_FALSE = 1, 0


def gluPerspective(fovy, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fovy) / 2)
    glMultMatrixf([f / aspect, 0.0, 0.0, 0.0,
                   0.0, f, 0.0, 0.0,
                   0.0, 0.0, (far + near) / (near - far), -1.0,
                   0.0, 0.0, 2.0 * far * near / (near - far), 0.0])


def gluOrtho2D(left, right, bottom, top):
    glOrtho(left, right, bottom, top, -1.0, 1.0)


def gluLookAt(ex, ey, ez, cx, cy, cz, ux, uy, uz):
    fx, fy, fz = context.normalize(cx - ex, cy - ey, cz - ez)
    sx, sy, sz = context.normalize(fy * uz - fz * uy, fz * ux - fx * uz, fx * uy - fy * ux)   # f x up
    ux, uy, uz = sy * fz - sz * fy, sz * fx - sx * fz, sx * fy - sy * fx                       # s x f
    glMultMatrixf([sx, ux, -fx, 0.0, sy, uy, -fy, 0.0, sz, uz, -fz, 0.0, 0.0, 0.0, 0.0, 1.0])
    glTranslatef(-ex, -ey, -ez)


def gluProject(x, y, z, model=None, proj=None, view=None):
    """Where a point lands on the window: (x, y, depth 0..1), y from the bottom."""
    c = context.current
    model = _flat(model) if model is not None else c.modelview()
    proj = _flat(proj) if proj is not None else c.projection()
    vx, vy, vw, vh = view if view is not None else c.viewport
    e = context.transform(model, x, y, z)
    cx, cy, cz, cw = context.transform(proj, *e)
    if cw == 0:
        return None
    return (vx + (cx / cw + 1) * vw / 2, vy + (cy / cw + 1) * vh / 2, (cz / cw + 1) / 2)


def _flat(m):
    return [float(v) for col in m for v in col] if len(m) == 4 else [float(v) for v in m]


def gluErrorString(code):
    return b"no error" if not code else b"OpenGL error %d" % code


def gluBuild2DMipmaps(target, internal, w, h, fmt, kind, data):
    glTexImage2D(target, 0, internal, w, h, 0, fmt, kind, data)
    return 0


# ---- quadrics: spheres, cylinders, disks ----

class Quadric:
    def __init__(self):
        self.style = GLU_FILL
        self.normals = GLU_SMOOTH
        self.texture = False
        self.inside = False


def gluNewQuadric():
    return Quadric()


def gluDeleteQuadric(q):
    pass


def gluQuadricDrawStyle(q, style):
    q.style = style


def gluQuadricNormals(q, normals):
    q.normals = normals


def gluQuadricTexture(q, on):
    q.texture = bool(on)


def gluQuadricOrientation(q, orientation):
    q.inside = orientation == GLU_INSIDE


def _strips(q, rows, cols, point):
    """Draw a grid of quads: point(i, j) gives (vertex, normal, texcoord)."""
    for i in range(rows):
        glBegin(GL_QUAD_STRIP if q.style == GLU_FILL else GL_LINE_STRIP)
        for j in range(cols + 1):
            for k in (i + 1, i) if not q.inside else (i, i + 1):
                v, n, t = point(k, j)
                if q.normals != GLU_NONE:
                    glNormal3f(*n)
                if q.texture:
                    glTexCoord2f(*t)
                glVertex3f(*v)
        glEnd()


def gluSphere(q, radius, slices, stacks):
    def point(i, j):
        phi = math.pi * i / stacks                 # from the top (0) to the bottom (pi)
        theta = 2 * math.pi * j / slices
        n = (math.sin(phi) * math.sin(theta), math.sin(phi) * math.cos(theta), math.cos(phi))
        return (radius * n[0], radius * n[1], radius * n[2]), n, (j / slices, 1 - i / stacks)
    _strips(q, stacks, slices, point)


def gluCylinder(q, base, top, height, slices, stacks):
    def point(i, j):
        theta = 2 * math.pi * j / slices
        r = base + (top - base) * i / stacks
        s, c = math.sin(theta), math.cos(theta)
        n = context.normalize(s * height, c * height, base - top)
        return (r * s, r * c, height * i / stacks), n, (j / slices, i / stacks)
    _strips(q, stacks, slices, point)


def gluDisk(q, inner, outer, slices, loops):
    def point(i, j):
        theta = 2 * math.pi * j / slices
        r = inner + (outer - inner) * i / loops
        s, c = math.sin(theta), math.cos(theta)
        return (r * s, r * c, 0.0), (0.0, 0.0, 1.0), (0.5 + 0.5 * s * r / outer, 0.5 + 0.5 * c * r / outer)
    _strips(q, loops, slices, point)


def gluPartialDisk(q, inner, outer, slices, loops, start, sweep):
    def point(i, j):
        theta = math.radians(start + sweep * j / slices)
        r = inner + (outer - inner) * i / loops
        return (r * math.sin(theta), r * math.cos(theta), 0.0), (0.0, 0.0, 1.0), (0.5, 0.5)
    _strips(q, loops, slices, point)
