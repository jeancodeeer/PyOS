# The OpenGL machine: everything OpenGL remembers (matrices, colours,
# lights, textures...) and the way from glVertex calls to pixels.
#
#   vertex --(modelview)--> eye space --(lighting)--> colour
#          --(projection)--> clip space --(clipping, divide by w)-->
#          --(viewport)--> window --(raster.py)--> pixels
#
# One Context draws into one pygame Surface. pygame.display.set_mode(size,
# OPENGL) makes one for the screen; Context(surface) makes one for any
# surface (a window on the SnakeyOS desktop, for example).
import array
import math
import micropython
from OpenGL import raster

DEPTH_MAX = 1 << 18            # depth buffer values go from 0 (near) to this (far)
current = None                 # the context the gl* functions use


def identity():
    return [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def multiply(a, b):
    """a x b for 4x4 matrices stored column by column (as OpenGL does)."""
    out = [0.0] * 16
    for c in range(4):
        for r in range(4):
            out[c * 4 + r] = (a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] +
                              a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3])
    return out


def transform(m, x, y, z, w=1.0):
    return (m[0] * x + m[4] * y + m[8] * z + m[12] * w,
            m[1] * x + m[5] * y + m[9] * z + m[13] * w,
            m[2] * x + m[6] * y + m[10] * z + m[14] * w,
            m[3] * x + m[7] * y + m[11] * z + m[15] * w)


def normalize(x, y, z):
    n = math.sqrt(x * x + y * y + z * z)
    return (x / n, y / n, z / n) if n else (0.0, 0.0, 1.0)


class Light:
    def __init__(self, n):
        self.on = False
        self.ambient = (0.0, 0.0, 0.0, 1.0)
        self.diffuse = (1.0, 1.0, 1.0, 1.0) if n == 0 else (0.0, 0.0, 0.0, 1.0)
        self.specular = (1.0, 1.0, 1.0, 1.0) if n == 0 else (0.0, 0.0, 0.0, 1.0)
        self.position = (0.0, 0.0, 1.0, 0.0)          # in eye space: a light from the viewer


class Material:
    def __init__(self):
        self.ambient = (0.2, 0.2, 0.2, 1.0)
        self.diffuse = (0.8, 0.8, 0.8, 1.0)
        self.specular = (0.0, 0.0, 0.0, 1.0)
        self.emission = (0.0, 0.0, 0.0, 1.0)
        self.shininess = 0.0


class Shader:
    """OpenGL's fixed-function lighting, ready for the vertices of one glEnd:
    what does not change from vertex to vertex is worked out once here."""

    def __init__(self, ctx):
        mat = ctx.material
        self.tracks = None
        if "color_material" in ctx.enabled:
            self.tracks = ctx.color_material[1]           # which material colour follows glColor
        self.mat = mat
        self.global_ambient = ctx.light_ambient
        self.lights = []
        for L in ctx.lights:
            if L.on:
                x, y, z, w = L.position
                if w:
                    x, y, z = x / w, y / w, z / w
                else:
                    x, y, z = normalize(x, y, z)
                self.lights.append((bool(w), x, y, z, L.ambient, L.diffuse, L.specular))
        self.shiny = mat.shininess if mat.specular[0] + mat.specular[1] + mat.specular[2] > 0 else 0

    @micropython.native
    def color(self, ex, ey, ez, nx, ny, nz, col):
        ln = math.sqrt(nx * nx + ny * ny + nz * nz)
        if ln:
            nx, ny, nz = nx / ln, ny / ln, nz / ln
        mat = self.mat
        what = self.tracks
        dif = col if what == "ambient_and_diffuse" or what == "diffuse" else mat.diffuse
        amb = col if what == "ambient_and_diffuse" or what == "ambient" else mat.ambient
        ga = self.global_ambient
        em = mat.emission
        r = em[0] + ga[0] * amb[0]
        g = em[1] + ga[1] * amb[1]
        b = em[2] + ga[2] * amb[2]
        shiny = self.shiny
        for point, lx, ly, lz, la, ld, ls in self.lights:
            if point:                                     # towards the light from this vertex
                lx, ly, lz = lx - ex, ly - ey, lz - ez
                d = math.sqrt(lx * lx + ly * ly + lz * lz)
                if d:
                    lx, ly, lz = lx / d, ly / d, lz / d
            r += la[0] * amb[0]
            g += la[1] * amb[1]
            b += la[2] * amb[2]
            d = nx * lx + ny * ly + nz * lz
            if d > 0:
                r += d * ld[0] * dif[0]
                g += d * ld[1] * dif[1]
                b += d * ld[2] * dif[2]
                if shiny > 0:
                    hx, hy, hz = lx, ly, lz + 1.0          # half way between light and viewer
                    sp = (nx * hx + ny * hy + nz * hz) / math.sqrt(hx * hx + hy * hy + hz * hz)
                    if sp > 0:
                        sp = sp ** shiny
                        spec = mat.specular
                        r += sp * ls[0] * spec[0]
                        g += sp * ls[1] * spec[1]
                        b += sp * ls[2] * spec[2]
        return (r, g, b, dif[3])


class Texture:
    def __init__(self):
        self.w = self.h = 1
        self.pixels = bytearray(b"\xff\xff\xff\xff")      # RGBA


class Context:
    def __init__(self, surface):
        self.surface = surface
        self.w, self.h = surface.get_width(), surface.get_height()
        self.depth = bytearray(4 * self.w * self.h)            # one 32-bit number per pixel
        self.viewport = (0, 0, self.w, self.h)
        self.matrices = {"modelview": [identity()], "projection": [identity()], "texture": [identity()]}
        self.mode = "modelview"
        self.clear_color = (0, 0, 0)
        self.clear_depth = 1.0
        self.enabled = set()
        self.color = (1.0, 1.0, 1.0, 1.0)
        self.normal = (0.0, 0.0, 1.0)
        self.texcoord = (0.0, 0.0)
        self.lights = [Light(i) for i in range(8)]
        self.material = Material()
        self.back_material = self.material
        self.color_material = ("front_and_back", "ambient_and_diffuse")
        self.light_ambient = (0.2, 0.2, 0.2, 1.0)
        self.flat = False
        self.cull = "back"
        self.front_ccw = True
        self.depth_func_lequal = False
        self.depth_write = True
        self.polygon_line = False
        self.line_width = 1
        self.point_size = 1
        self.textures = {0: Texture()}
        self.texture = 0
        self.next_texture = 1
        self.modulate = True
        self.prim = None               # the primitive being built between glBegin and glEnd
        self.verts = []
        self.lists = {}
        self.next_list = 1
        self.recording = None          # (list number, calls, also run them?)
        self.error = 0
        self.state = array.array("i", [0] * 8)

    def retarget(self, surface):
        """Draw into another Surface from now on (a window that changed size)."""
        self.surface = surface
        self.w, self.h = surface.get_width(), surface.get_height()
        self.depth = bytearray(4 * self.w * self.h)

    # ---- matrices ----
    def top(self):
        return self.matrices[self.mode][-1]

    def set_top(self, m):
        self.matrices[self.mode][-1] = m

    def mult(self, m):
        self.set_top(multiply(self.top(), m))

    def modelview(self):
        return self.matrices["modelview"][-1]

    def projection(self):
        return self.matrices["projection"][-1]

    # ---- glVertex: only remembered; glEnd does the work for all of them ----
    def vertex(self, x, y, z=0.0, w=1.0):
        self.verts.append((x, y, z, w, self.color, self.normal, self.texcoord))

    @micropython.native
    def process(self, raw):
        """Every vertex of a glBegin/glEnd: clip space, colour, texture
        coordinates and window position (None when it is outside the view,
        so the triangle must be clipped)."""
        m = self.modelview()
        p = self.projection()
        m0, m1, m2, m3, m4, m5, m6, m7 = m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7]
        m8, m9, m10, m11, m12, m13, m14, m15 = m[8], m[9], m[10], m[11], m[12], m[13], m[14], m[15]
        p0, p1, p2, p3, p4, p5, p6, p7 = p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7]
        p8, p9, p10, p11, p12, p13, p14, p15 = p[8], p[9], p[10], p[11], p[12], p[13], p[14], p[15]
        lighting = "lighting" in self.enabled
        if lighting:
            shade = Shader(self)
        vx, vy, vw, vh = self.viewport
        hw, hh, hd = vw * 0.5, vh * 0.5, DEPTH_MAX * 0.5
        top = self.h - vy
        out = []
        for x, y, z, w, col, n, t in raw:
            ex = m0 * x + m4 * y + m8 * z + m12 * w
            ey = m1 * x + m5 * y + m9 * z + m13 * w
            ez = m2 * x + m6 * y + m10 * z + m14 * w
            ew = m3 * x + m7 * y + m11 * z + m15 * w
            if lighting:
                n0, n1, n2 = n
                col = shade.color(ex, ey, ez, m0 * n0 + m4 * n1 + m8 * n2, m1 * n0 + m5 * n1 + m9 * n2,
                                  m2 * n0 + m6 * n1 + m10 * n2, col)
            cx = p0 * ex + p4 * ey + p8 * ez + p12 * ew
            cy = p1 * ex + p5 * ey + p9 * ez + p13 * ew
            cz = p2 * ex + p6 * ey + p10 * ez + p14 * ew
            cw = p3 * ex + p7 * ey + p11 * ez + p15 * ew
            if -cw <= cx <= cw and -cw <= cy <= cw and -cw <= cz <= cw and cw > 0:
                iw = 1.0 / cw
                win = (vx + (cx * iw + 1.0) * hw, top - (cy * iw + 1.0) * hh, (cz * iw + 1.0) * hd)
            else:
                win = None
            out.append(((cx, cy, cz, cw), col, t, win))
        return out

    # ---- glEnd: from vertices to primitives ----
    def end(self):
        kind = self.prim
        v = self.process(self.verts)
        self.verts, self.prim = [], None
        if kind == "points":
            for a in v:
                self.point(a)
        elif kind == "lines":
            for i in range(0, len(v) - 1, 2):
                self.line(v[i], v[i + 1])
        elif kind in ("line_strip", "line_loop"):
            for i in range(len(v) - 1):
                self.line(v[i], v[i + 1])
            if kind == "line_loop" and len(v) > 2:
                self.line(v[-1], v[0])
        elif kind in _TRIANGLES:
            self.fill(v, _TRIANGLES[kind](len(v)))

    def fill(self, v, corners):
        """Draw triangles: corners are (a, b, c, vertex that gives a flat colour)."""
        if self.polygon_line:                                  # glPolygonMode(GL_LINE)
            for a, b, c, last in corners:
                for p, q in ((a, b), (b, c), (c, a)):
                    self.line(v[p], v[q])
            return
        tex = self.textures.get(self.texture) if "texture_2d" in self.enabled else None
        tw, th = (tex.w, tex.h) if tex is not None else (1, 1)
        verts = array.array("i")
        tris = array.array("i")
        near_w = 1e30                                          # the nearest vertex, for the texture
        for vert in v:
            w = vert[0][3]
            if 0 < w < near_w:
                near_w = w
        if near_w == 1e30:
            near_w = 1.0
        number = [-1] * len(v)                                 # each vertex is packed once
        for a, b, c, last in corners:
            va, vb, vc = v[a], v[b], v[c]
            if self.flat:                                      # GL_FLAT: one colour per triangle
                col = v[last][1]
                va, vb, vc = (va[0], col, va[2], va[3]), (vb[0], col, vb[2], vb[3]), (vc[0], col, vc[2], vc[3])
            if va[3] is None or vb[3] is None or vc[3] is None:
                poly = self.clip([va, vb, vc])                 # partly outside: cut it
                if poly:
                    first = len(verts) // raster.VERTEX
                    for p in poly:
                        _pack(verts, p, tw, th, near_w)
                    for k in range(1, len(poly) - 1):
                        tris.append(first)
                        tris.append(first + k)
                        tris.append(first + k + 1)
                continue
            for i, vert in ((a, va), (b, vb), (c, vc)):
                if self.flat:
                    tris.append(len(verts) // raster.VERTEX)
                    _pack(verts, vert, tw, th, near_w)
                else:
                    if number[i] < 0:
                        number[i] = len(verts) // raster.VERTEX
                        _pack(verts, vert, tw, th, near_w)
                    tris.append(number[i])
        if not tris:
            return
        flags = 0
        if "depth_test" in self.enabled:
            flags = raster.DEPTH_TEST | (raster.DEPTH_WRITE if self.depth_write else 0)
            if self.depth_func_lequal:
                flags |= raster.LEQUAL
        if tex is not None:
            flags |= raster.TEXTURE | (raster.MODULATE if self.modulate else 0)
        if "blend" in self.enabled:
            flags |= raster.BLEND
        vx, vy, vw, vh = self.viewport
        top = self.h - vy - vh
        cull = {"back": 1, "front": 2, "front_and_back": 3}[self.cull] if "cull_face" in self.enabled else 0
        st = self.state
        st[0], st[1], st[2] = flags, cull, 1 if self.front_ccw else 0
        st[3], st[4] = max(0, vx), min(self.w, vx + vw) - 1
        st[5], st[6] = max(0, top), min(self.h, top + vh) - 1
        t = tex or self.textures[0]
        raster.triangles(self.surface._buf, self.depth, self.w, verts, tris, len(tris) // 3,
                         t.pixels, t.w, t.h, st)

    # ---- clipping: keep the part in front of the camera and inside the view ----
    def clip(self, poly):
        """Cut a polygon by the 6 planes of the view volume (-w <= x, y, z <= w)."""
        for axis in (2, 0, 1):
            for sign in (1, -1):
                out = []
                n = len(poly)
                for i in range(n):
                    a, b = poly[i], poly[(i + 1) % n]
                    da = a[0][3] - sign * a[0][axis]          # >= 0 means inside
                    db = b[0][3] - sign * b[0][axis]
                    if da >= 0:
                        out.append(a)
                    if (da >= 0) != (db >= 0):
                        out.append(_mix(a, b, da / (da - db)))
                poly = out
                if len(poly) < 3:
                    return []
        return [(p[0], p[1], p[2], self.window(p[0])) for p in poly]

    def window(self, clip):
        """Clip space -> window pixels (y down) and depth units."""
        x, y, z, w = clip
        if w <= 0:
            w = 1e-9
        vx, vy, vw, vh = self.viewport
        return (vx + (x / w + 1.0) * 0.5 * vw, self.h - (vy + (y / w + 1.0) * 0.5 * vh),
                (z / w + 1.0) * 0.5 * DEPTH_MAX)

    def raster_line(self, a, b):
        x0, y0, z0 = a[3]
        x1, y1, z1 = b[3]
        n = int(max(abs(x1 - x0), abs(y1 - y0))) or 1
        col = a[1]
        r = max(0, min(255, int(col[0] * 255)))
        g = max(0, min(255, int(col[1] * 255)))
        bl = max(0, min(255, int(col[2] * 255)))
        flags = (1 | (2 if self.depth_write else 0)) if "depth_test" in self.enabled else 0
        for k in range(self.line_width):
            off = k - self.line_width // 2
            ox, oy = (off, 0) if abs(y1 - y0) > abs(x1 - x0) else (0, off)
            raster.line(self.surface._buf, self.depth, self.w, self.h,
                        int((x0 + ox) * 65536), int((y0 + oy) * 65536), int(z0 * 65536),
                        int((x1 - x0) * 65536 / n), int((y1 - y0) * 65536 / n), n,
                        int((z1 - z0) * 65536 / n), (r << 16) | (g << 8) | bl, flags)

    def line(self, a, b):
        if a[3] is None or b[3] is None:
            ends = self.clip_line(a, b)
            if not ends:
                return
            a = (ends[0][0], ends[0][1], ends[0][2], self.window(ends[0][0]))
            b = (ends[1][0], ends[1][1], ends[1][2], self.window(ends[1][0]))
        self.raster_line(a, b)

    def clip_line(self, a, b):
        for axis in (2, 0, 1):
            for sign in (1, -1):
                da = a[0][3] - sign * a[0][axis]
                db = b[0][3] - sign * b[0][axis]
                if da < 0 and db < 0:
                    return None
                if da < 0:
                    a = _mix(a, b, da / (da - db))
                elif db < 0:
                    b = _mix(a, b, da / (da - db))
        return a, b

    def point(self, v):
        if v[3] is None:
            return
        sx, sy, sz = v[3]
        size = max(1, int(self.point_size))
        col = v[1]
        rgb = (max(0, min(255, int(col[0] * 255))), max(0, min(255, int(col[1] * 255))),
               max(0, min(255, int(col[2] * 255))))
        self.surface.fill(rgb, (int(sx) - size // 2, int(sy) - size // 2, size, size))

    # ---- clearing ----
    def clear(self, color, depth):
        if color:
            r, g, b = (max(0, min(255, int(c * 255))) for c in self.clear_color[:3])
            vx, vy, vw, vh = self.viewport
            if (vx, vy, vw, vh) == (0, 0, self.w, self.h):
                raster.fill32(self.surface._buf, self.w * self.h, 0xFF000000 | (r << 16) | (g << 8) | b)
            else:
                self.surface.fill((r, g, b), (vx, self.h - vy - vh, vw, vh))
        if depth:
            raster.fill32(self.depth, self.w * self.h, int(self.clear_depth * DEPTH_MAX))


@micropython.native
def _pack(out, v, tw, th, near_w):
    """A vertex as the 10 whole numbers raster.triangles wants (see raster.py)."""
    x, y, z = v[3]
    c = v[1]
    t = v[2]
    w = v[0][3]
    q = near_w / w if w > 0 else 1.0               # 1 for the nearest vertex, less further away
    out.append(int(x * 16))
    out.append(int(y * 16))
    out.append(int(z))
    out.append(int(c[0] * 65280))                  # 0-255, x256
    out.append(int(c[1] * 65280))
    out.append(int(c[2] * 65280))
    out.append(int(t[0] * tw * 256 * q))
    out.append(int(t[1] * th * 256 * q))
    a = int(c[3] * 255)
    out.append(0 if a < 0 else 255 if a > 255 else a)
    out.append(int(q * 65536))


# how each kind of primitive is cut into triangles: (a, b, c, vertex with the flat colour)
def _tri_list(n):
    return [(i, i + 1, i + 2, i + 2) for i in range(0, n - 2, 3)]


def _tri_strip(n):
    return [((i + 1, i, i + 2, i + 2) if i % 2 else (i, i + 1, i + 2, i + 2)) for i in range(n - 2)]


def _tri_fan(n):
    return [(0, i, i + 1, i + 1) for i in range(1, n - 1)]


def _polygon(n):
    return [(0, i, i + 1, n - 1) for i in range(1, n - 1)]


def _quads(n):
    out = []
    for i in range(0, n - 3, 4):
        out.append((i, i + 1, i + 2, i + 3))
        out.append((i, i + 2, i + 3, i + 3))
    return out


def _quad_strip(n):
    out = []
    for i in range(0, n - 3, 2):
        out.append((i, i + 1, i + 3, i + 3))
        out.append((i, i + 3, i + 2, i + 3))
    return out


_TRIANGLES = {"triangles": _tri_list, "triangle_strip": _tri_strip, "triangle_fan": _tri_fan,
              "polygon": _polygon, "quads": _quads, "quad_strip": _quad_strip}


def _mix(a, b, t):
    """The vertex a fraction t of the way from a to b (clip position, colour, texture)."""
    pa, pb = a[0], b[0]
    ca, cb = a[1], b[1]
    ta, tb = a[2], b[2]
    return (tuple(pa[i] + (pb[i] - pa[i]) * t for i in range(4)),
            tuple(ca[i] + (cb[i] - ca[i]) * t for i in range(4)),
            (ta[0] + (tb[0] - ta[0]) * t, ta[1] + (tb[1] - ta[1]) * t), None)


def make_current(ctx):
    global current
    current = ctx
    return ctx


def attach(surface):
    """Give a pygame Surface (the screen, a window) its own OpenGL context."""
    return make_current(Context(surface))
