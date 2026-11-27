# SVG pictures: the logos and icons of web pages, drawn into a Surface.
#
#   surf = svg.render_text(b"<svg ...>...</svg>", w, h, color=(0, 0, 0))   a .svg file
#   surf = svg.render_node(node, w, h, color)                                an <svg> already in a page
#
# What it draws: path (every command, arcs included), rect, circle, ellipse,
# line, polyline, polygon; <g> and <svg> inside <svg> with transform,
# <use> of a <symbol> or any element with an id; fill, stroke, stroke-width,
# fill-rule, opacity, currentColor, style="..." and the first colour of a
# gradient. Text, filters, masks and clip paths are left out.
#
# How: every shape becomes polygons (curves cut into short lines), and the
# polygons are filled one pixel row at a time, four sub-rows per pixel for
# soft edges. Lines (strokes) are filled as thin quadrilaterals.
import math

_NUM_CHARS = "0123456789.-+eE"


# ---- reading numbers and paths ----

def _numbers(s):
    """'10,20.5-3e2 .5.5' -> [10.0, 20.5, -300.0, 0.5, 0.5]"""
    out, cur, i, n = [], "", 0, len(s)
    while i < n:
        c = s[i]
        if c in "0123456789":
            cur += c
        elif c == ".":
            if "." in cur and "e" not in cur.lower():
                out.append(float(cur))
                cur = "."
            else:
                cur += c
        elif c in "-+":
            if cur and cur[-1] not in "eE":
                out.append(float(cur))
                cur = c
            else:
                cur += c
        elif c in "eE" and cur:
            cur += c
        else:
            if cur and cur not in "-+.":
                out.append(float(cur))
            cur = ""
        i += 1
    if cur and cur not in "-+.":
        out.append(float(cur))
    return out


def _path_tokens(d):
    """Split a path's d into (command, [numbers])."""
    out, cmd, buf = [], None, ""
    for c in d:
        if c.isalpha() and c not in "eE":
            if cmd is not None:
                out.append((cmd, _numbers(buf)))
            cmd, buf = c, ""
        else:
            buf += c
    if cmd is not None:
        out.append((cmd, _numbers(buf)))
    return out


def _arc(x1, y1, rx, ry, phi, large, sweep, x2, y2):
    """Points along an elliptical arc (SVG's endpoint form), without the first one."""
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    rx, ry = abs(rx), abs(ry)
    cp, sp = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x1 + x2) / 2
    cy = sp * cxp + cp * cyp + (y1 + y2) / 2

    def angle(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    steps = max(4, int(abs(dt) / (math.pi / 10)))
    pts = []
    for k in range(1, steps + 1):
        t = t1 + dt * k / steps
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        pts.append((cp * ex - sp * ey + cx, sp * ex + cp * ey + cy))
    return pts


def path_polys(d):
    """A path's d -> a list of polylines [(x, y), ...] (one per subpath) and whether each is closed."""
    polys, cur = [], []
    x = y = sx = sy = 0.0
    lcx = lcy = None                 # the last control point (for S and T)
    last = ""

    def bez(p0, p1, p2, p3, n=10):
        out = []
        for k in range(1, n + 1):
            t = k / n
            mt = 1 - t
            a, b, c, e = mt * mt * mt, 3 * mt * mt * t, 3 * mt * t * t, t * t * t
            out.append((a * p0[0] + b * p1[0] + c * p2[0] + e * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + e * p3[1]))
        return out

    for cmd, nums in _path_tokens(d):
        rel = cmd.islower()
        c = cmd.upper()
        if c == "Z":
            if cur:
                polys.append((cur, True))
            cur = []
            x, y = sx, sy
            last = c
            continue
        size = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}.get(c, 0)
        if not size:
            continue
        i = 0
        first = True
        while i + size <= len(nums):
            a = nums[i:i + size]
            i += size
            ox, oy = (x, y) if rel else (0.0, 0.0)
            if c == "M" and first:
                if cur:
                    polys.append((cur, False))
                x, y = a[0] + ox, a[1] + oy
                sx, sy = x, y
                cur = [(x, y)]
                lcx = None
            elif c in ("M", "L"):
                x, y = a[0] + ox, a[1] + oy
                cur.append((x, y))
                lcx = None
            elif c == "H":
                x = a[0] + (x if rel else 0)
                cur.append((x, y))
                lcx = None
            elif c == "V":
                y = a[0] + (y if rel else 0)
                cur.append((x, y))
                lcx = None
            elif c == "C":
                p1, p2, p3 = (a[0] + ox, a[1] + oy), (a[2] + ox, a[3] + oy), (a[4] + ox, a[5] + oy)
                cur += bez((x, y), p1, p2, p3)
                lcx, lcy = p2
                x, y = p3
            elif c == "S":
                p1 = (2 * x - lcx, 2 * y - lcy) if lcx is not None and last in ("C", "S") else (x, y)
                p2, p3 = (a[0] + ox, a[1] + oy), (a[2] + ox, a[3] + oy)
                cur += bez((x, y), p1, p2, p3)
                lcx, lcy = p2
                x, y = p3
            elif c in ("Q", "T"):
                if c == "Q":
                    q = (a[0] + ox, a[1] + oy)
                    end = (a[2] + ox, a[3] + oy)
                else:
                    q = (2 * x - lcx, 2 * y - lcy) if lcx is not None and last in ("Q", "T") else (x, y)
                    end = (a[0] + ox, a[1] + oy)
                p1 = (x + 2 / 3 * (q[0] - x), y + 2 / 3 * (q[1] - y))
                p2 = (end[0] + 2 / 3 * (q[0] - end[0]), end[1] + 2 / 3 * (q[1] - end[1]))
                cur += bez((x, y), p1, p2, end, 8)
                lcx, lcy = q
                x, y = end
            elif c == "A":
                end = (a[5] + ox, a[6] + oy)
                cur += _arc(x, y, a[0], a[1], a[2], int(a[3]), int(a[4]), end[0], end[1])
                x, y = end
                lcx = None
            last = c
            first = False
            if c == "M":
                c = "L"                       # more pairs after M are lines
        last = c
    if cur:
        polys.append((cur, False))
    return polys


# ---- transforms (a b c d e f, as SVG's matrix) ----

def _mul(m, n):
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2, a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _transform(text):
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for part in text.replace(")", ")\n").split("\n"):
        if "(" not in part:
            continue
        name, args = part.split("(", 1)
        name = name.strip().strip(",").strip()
        v = _numbers(args)
        if name == "translate" and v:
            n = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale" and v:
            n = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "matrix" and len(v) == 6:
            n = tuple(v)
        elif name == "rotate" and v:
            r = math.radians(v[0])
            n = (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0)
            if len(v) == 3:
                n = _mul(_mul((1, 0, 0, 1, v[1], v[2]), n), (1, 0, 0, 1, -v[1], -v[2]))
        elif name == "skewX" and v:
            n = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewY" and v:
            n = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = _mul(m, n)
    return m


# ---- filling ----

class Canvas:
    """w x h pixels of B G R A, with polygon filling (soft edges)."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.buf = bytearray(w * h * 4)

    def fill(self, polys, color, alpha=1.0, evenodd=False):
        """polys: lists of (x, y) in pixels, all filled together (holes work)."""
        edges = []
        top, bottom = self.h, 0
        for pts in polys:
            n = len(pts)
            if n < 3:
                continue
            for i in range(n):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % n]
                if y0 == y1:
                    continue
                d = 1
                if y0 > y1:
                    x0, y0, x1, y1, d = x1, y1, x0, y0, -1
                edges.append((y0, y1, x0, (x1 - x0) / (y1 - y0), d))
                top = min(top, int(y0))
                bottom = max(bottom, int(y1) + 1)
        if not edges:
            return
        top, bottom = max(0, top), min(self.h, bottom)
        w = self.w
        r, g, b = color
        buf = self.buf
        SUB = 4
        for py in range(top, bottom):
            cover = [0] * (w + 1)
            for s in range(SUB):
                yy = py + (s + 0.5) / SUB
                xs = []
                for y0, y1, x0, k, d in edges:
                    if y0 <= yy < y1:
                        xs.append((x0 + (yy - y0) * k, d))
                if len(xs) < 2:
                    continue
                xs.sort()
                wind = 0
                for i in range(len(xs) - 1):
                    wind = (wind + 1) if evenodd else (wind + xs[i][1])
                    inside = (wind % 2 == 1) if evenodd else (wind != 0)
                    if not inside:
                        continue
                    a = xs[i][0]
                    z = xs[i + 1][0]
                    ia, iz = int(a + 0.5), int(z + 0.5)
                    if ia < 0:
                        ia = 0
                    if iz > w:
                        iz = w
                    for px in range(ia, iz):
                        cover[px] += 1
            row = py * w * 4
            for px in range(w):
                c = cover[px]
                if not c:
                    continue
                a = alpha * c / SUB
                o = row + px * 4
                old_a = buf[o + 3] / 255.0
                out_a = a + old_a * (1 - a)
                if out_a <= 0:
                    continue
                buf[o] = int((b * a + buf[o] * old_a * (1 - a)) / out_a)
                buf[o + 1] = int((g * a + buf[o + 1] * old_a * (1 - a)) / out_a)
                buf[o + 2] = int((r * a + buf[o + 2] * old_a * (1 - a)) / out_a)
                buf[o + 3] = int(out_a * 255)


def _stroke_polys(pts, width, closed):
    """A polyline drawn width wide: a quadrilateral per segment and a small disc per corner."""
    out = []
    hw = width / 2.0
    seq = pts + [pts[0]] if closed and len(pts) > 2 else pts
    for i in range(len(seq) - 1):
        (x0, y0), (x1, y1) = seq[i], seq[i + 1]
        dx, dy = x1 - x0, y1 - y0
        ln = math.sqrt(dx * dx + dy * dy)
        if ln < 1e-6:
            continue
        nx, ny = -dy / ln * hw, dx / ln * hw
        out.append([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)])
    if hw >= 0.8:
        for (x, y) in seq:
            out.append([(x + hw * math.cos(k * math.pi / 4), y + hw * math.sin(k * math.pi / 4)) for k in range(8)])
    for i, poly in enumerate(out):                     # all turning the same way, so overlaps add up
        area = sum(poly[j][0] * poly[(j + 1) % len(poly)][1] - poly[(j + 1) % len(poly)][0] * poly[j][1]
                   for j in range(len(poly)))
        if area < 0:
            out[i] = poly[::-1]
    return out


# ---- the picture ----

def _attrs_of(node):
    """Attributes plus style="..." (style wins), names in lower case."""
    a = {k.lower(): v for k, v in node.attrs.items()}
    st = a.get("style")
    if st:
        for part in st.split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                a[k.strip().lower()] = v.strip()
    return a


class Painter:
    def __init__(self, root, w, h, color):
        self.canvas = Canvas(w, h)
        self.color = color
        self.ids = {}
        self.gradients = {}
        stack = [root]
        while stack:
            n = stack.pop()
            if n.tag:
                ident = n.attrs.get("id")
                if ident:
                    self.ids[ident] = n
                if n.tag in ("lineargradient", "radialgradient"):
                    for c in n.children:
                        if c.tag == "stop":
                            ca = _attrs_of(c)
                            col = ca.get("stop-color")
                            if col:
                                self.gradients[ident] = col
                                break
            stack.extend(n.children)

    def paint(self, root, w, h):
        a = _attrs_of(root)
        vb = _numbers(a.get("viewbox", ""))
        if len(vb) == 4 and vb[2] > 0 and vb[3] > 0:
            s = min(w / vb[2], h / vb[3])
            ox = (w - vb[2] * s) / 2 - vb[0] * s
            oy = (h - vb[3] * s) / 2 - vb[1] * s
            m = (s, 0, 0, s, ox, oy)
        else:
            sw, sh = _size(a.get("width")), _size(a.get("height"))
            m = (w / sw if sw else 1, 0, 0, h / sh if sh else 1, 0, 0)
        inherited = {"fill": "black", "stroke": "none", "stroke-width": "1", "fill-rule": "nonzero", "opacity": "1",
                     "fill-opacity": "1", "stroke-opacity": "1", "color": None}
        for k in ("fill", "stroke", "stroke-width", "fill-rule", "fill-opacity", "stroke-opacity", "color", "opacity"):
            if k in a:                                   # what the <svg> itself says, its shapes inherit
                inherited[k] = a[k]
        self.walk(root, m, inherited, 0)
        return self.canvas

    def colour(self, value, props):
        from browser import css
        v = (value or "").strip()
        if not v or v == "none" or v == "transparent":
            return None
        if v.lower() == "currentcolor":
            c = props.get("color")
            return css.color(c) if isinstance(c, str) and css.color(c) else self.color
        if v.startswith("url("):
            ident = v[v.find("#") + 1:v.rfind(")")].strip("'\" ")
            v = self.gradients.get(ident)
            if v is None:
                return self.color
        c = css.color(v)
        return c if isinstance(c, tuple) else None

    def walk(self, node, m, props, depth):
        if depth > 24:
            return
        for c in node.children:
            if c.tag is None or c.tag in ("defs", "symbol", "mask", "clippath", "lineargradient", "radialgradient",
                                          "title", "desc", "style", "metadata", "filter", "pattern", "marker",
                                          "text", "foreignobject", "script"):
                continue
            a = _attrs_of(c)
            if a.get("display") == "none" or a.get("visibility") == "hidden":
                continue
            p = dict(props)
            for k in ("fill", "stroke", "stroke-width", "fill-rule", "fill-opacity", "stroke-opacity", "color"):
                if k in a:
                    p[k] = a[k]
            p["opacity"] = str(_float(props.get("opacity"), 1) * _float(a.get("opacity"), 1))
            mm = _mul(m, _transform(a["transform"])) if "transform" in a else m
            if c.tag in ("g", "a", "svg", "switch"):
                if c.tag == "svg" and ("x" in a or "y" in a):
                    mm = _mul(mm, (1, 0, 0, 1, _float(a.get("x")), _float(a.get("y"))))
                self.walk(c, mm, p, depth + 1)
            elif c.tag == "use":
                ref = (a.get("href") or a.get("xlink:href") or "").lstrip("#")
                target = self.ids.get(ref)
                if target is not None:
                    mm = _mul(mm, (1, 0, 0, 1, _float(a.get("x")), _float(a.get("y"))))
                    holder = type("Holder", (), {})()
                    holder.children = target.children if target.tag in ("symbol", "g", "svg") else [target]
                    self.walk(holder, mm, p, depth + 1)
            else:
                self.shape(c, a, mm, p)

    def shape(self, node, a, m, p):
        t = node.tag
        polys = []
        if t == "path":
            polys = path_polys(a.get("d", ""))
        elif t == "rect":
            x, y, w, h = _float(a.get("x")), _float(a.get("y")), _float(a.get("width")), _float(a.get("height"))
            if w <= 0 or h <= 0:
                return
            rx = min(_float(a.get("rx", a.get("ry"))), w / 2)
            ry = min(_float(a.get("ry", a.get("rx"))), h / 2)
            if rx > 0:
                pts = []
                for cx, cy, a0 in ((x + w - rx, y + ry, -90), (x + w - rx, y + h - ry, 0), (x + rx, y + h - ry, 90),
                                   (x + rx, y + ry, 180)):
                    for k in range(5):
                        ang = math.radians(a0 + k * 22.5)
                        pts.append((cx + rx * math.cos(ang), cy + ry * math.sin(ang)))
                polys = [(pts, True)]
            else:
                polys = [([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)]
        elif t in ("circle", "ellipse"):
            cx, cy = _float(a.get("cx")), _float(a.get("cy"))
            rx = _float(a.get("r")) if t == "circle" else _float(a.get("rx"))
            ry = _float(a.get("r")) if t == "circle" else _float(a.get("ry"))
            if rx <= 0 or ry <= 0:
                return
            n = 32
            polys = [([(cx + rx * math.cos(2 * math.pi * k / n), cy + ry * math.sin(2 * math.pi * k / n))
                       for k in range(n)], True)]
        elif t == "line":
            polys = [([(_float(a.get("x1")), _float(a.get("y1"))), (_float(a.get("x2")), _float(a.get("y2")))], False)]
            p = dict(p)
            p["fill"] = "none"
        elif t in ("polyline", "polygon"):
            v = _numbers(a.get("points", ""))
            pts = [(v[i], v[i + 1]) for i in range(0, len(v) - 1, 2)]
            polys = [(pts, t == "polygon")]
        if not polys:
            return
        aa, bb, cc, dd, ee, ff = m
        scale = math.sqrt(abs(aa * dd - bb * cc)) or 1
        moved = [([(aa * x + cc * y + ee, bb * x + dd * y + ff) for x, y in pts], closed) for pts, closed in polys]
        op = _float(p.get("opacity"), 1)
        fill = self.colour(p.get("fill"), p)
        if fill is not None:
            self.canvas.fill([pts for pts, _ in moved], fill, op * _float(p.get("fill-opacity"), 1),
                             p.get("fill-rule") == "evenodd")
        stroke = self.colour(p.get("stroke"), p)
        if stroke is not None:
            width = max(0.6, _float(p.get("stroke-width"), 1) * scale)
            quads = []
            for pts, closed in moved:
                quads += _stroke_polys(pts, width, closed)
            self.canvas.fill(quads, stroke, op * _float(p.get("stroke-opacity"), 1))


def _float(v, default=0.0):
    if v is None:
        return default
    try:
        return float(str(v).strip().rstrip("px").rstrip("%") or default)
    except ValueError:
        return default


def _size(v):
    if not v or "%" in v:
        return 0
    try:
        return float(v.strip().rstrip("px"))
    except ValueError:
        return 0


def intrinsic_size(node, default=(24, 24)):
    """The size an <svg> asks for: width/height, or its viewBox."""
    a = _attrs_of(node)
    w, h = _size(a.get("width")), _size(a.get("height"))
    vb = _numbers(a.get("viewbox", ""))
    if len(vb) == 4 and vb[2] > 0 and vb[3] > 0:
        if w and not h:
            h = w * vb[3] / vb[2]
        elif h and not w:
            w = h * vb[2] / vb[3]
        elif not w:
            w, h = vb[2], vb[3]
    return (int(w) or default[0], int(h) or default[1])


def _surface(canvas):
    import pygame
    if hasattr(pygame.Surface, "_buf") or _pykernel():
        return pygame.Surface((canvas.w, canvas.h), pygame.SRCALPHA, _buf=canvas.buf)
    return pygame.image.frombuffer(bytes(canvas.buf), (canvas.w, canvas.h), "BGRA").convert_alpha() \
        if pygame.display.get_init() and pygame.display.get_surface() else \
        pygame.image.frombuffer(bytes(canvas.buf), (canvas.w, canvas.h), "BGRA")


def _pykernel():
    try:
        import _kernel  # noqa: F401
        return True
    except ImportError:
        return False


def render_node(node, w, h, color=(0, 0, 0)):
    """An <svg> element (from the page's tree) drawn w x h."""
    w, h = max(1, min(int(w), 1600)), max(1, min(int(h), 1600))
    painter = Painter(node, w, h, color)
    return _surface(painter.paint(node, w, h))


def render_text(data, w=None, h=None, color=(0, 0, 0)):
    """A .svg file's bytes drawn w x h (its own size when not given)."""
    from browser import html
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    doc = html.parse(data)
    root = doc.find("svg")
    if root is None:
        raise ValueError("not an SVG picture")
    if not w or not h:
        iw, ih = intrinsic_size(root, (150, 150))
        w, h = w or iw, h or ih
        if w > 1200:
            w, h = 1200, int(h * 1200 / w)
    return render_node(root, w, h, color)
