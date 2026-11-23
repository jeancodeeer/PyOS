# pygame.Rect: an integer rectangle with the full pygame interface.


def _rect_args(args):
    """Rect(x, y, w, h) / Rect((x, y), (w, h)) / Rect((x, y, w, h)) / Rect(obj)."""
    if len(args) == 4:
        return args
    if len(args) == 2:
        return args[0][0], args[0][1], args[1][0], args[1][1]
    if len(args) == 1:
        a = args[0]
        if isinstance(a, Rect):
            return a.x, a.y, a.w, a.h
        if hasattr(a, "rect"):
            r = a.rect
            return _rect_args((r() if callable(r) else r,))
        if len(a) == 4:
            return a
        if len(a) == 2:
            return a[0][0], a[0][1], a[1][0], a[1][1]
    raise TypeError("Argument must be rect style object")


class Rect:
    def __init__(self, *args):
        x, y, w, h = _rect_args(args)
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)

    # -- sequence protocol --
    def __len__(self):
        return 4

    def __getitem__(self, i):
        return (self.x, self.y, self.w, self.h)[i]

    def __setitem__(self, i, v):
        v = int(v)
        if i == 0:
            self.x = v
        elif i == 1:
            self.y = v
        elif i == 2:
            self.w = v
        elif i == 3:
            self.h = v
        else:
            raise IndexError(i)

    def __iter__(self):
        return iter((self.x, self.y, self.w, self.h))

    def __eq__(self, other):
        try:
            return tuple(self) == tuple(_rect_args((other,)))
        except (TypeError, IndexError):
            return False

    def __ne__(self, other):
        return not self == other

    def __bool__(self):
        return self.w != 0 and self.h != 0

    def __hash__(self):
        return hash((self.x, self.y, self.w, self.h))

    def __repr__(self):
        return "<rect(%d, %d, %d, %d)>" % (self.x, self.y, self.w, self.h)

    # -- virtual attributes --
    width = property(lambda s: s.w, lambda s, v: setattr(s, "w", int(v)))
    height = property(lambda s: s.h, lambda s, v: setattr(s, "h", int(v)))
    left = property(lambda s: s.x, lambda s, v: setattr(s, "x", int(v)))
    top = property(lambda s: s.y, lambda s, v: setattr(s, "y", int(v)))
    right = property(lambda s: s.x + s.w, lambda s, v: setattr(s, "x", int(v) - s.w))
    bottom = property(lambda s: s.y + s.h, lambda s, v: setattr(s, "y", int(v) - s.h))
    centerx = property(lambda s: s.x + s.w // 2, lambda s, v: setattr(s, "x", int(v) - s.w // 2))
    centery = property(lambda s: s.y + s.h // 2, lambda s, v: setattr(s, "y", int(v) - s.h // 2))

    def _get2(a, b):
        return property(lambda s: (getattr(s, a), getattr(s, b)),
                        lambda s, v: (setattr(s, a, v[0]), setattr(s, b, v[1])))

    size = _get2("w", "h")
    topleft = _get2("left", "top")
    topright = _get2("right", "top")
    bottomleft = _get2("left", "bottom")
    bottomright = _get2("right", "bottom")
    center = _get2("centerx", "centery")
    midtop = _get2("centerx", "top")
    midbottom = _get2("centerx", "bottom")
    midleft = _get2("left", "centery")
    midright = _get2("right", "centery")
    del _get2

    # -- methods --
    def copy(self):
        return Rect(self.x, self.y, self.w, self.h)

    def move(self, *d):
        dx, dy = d if len(d) == 2 else d[0]
        return Rect(self.x + dx, self.y + dy, self.w, self.h)

    def move_ip(self, *d):
        dx, dy = d if len(d) == 2 else d[0]
        self.x += int(dx)
        self.y += int(dy)

    def inflate(self, *d):
        dx, dy = d if len(d) == 2 else d[0]
        return Rect(self.x - dx // 2, self.y - dy // 2, self.w + dx, self.h + dy)

    def inflate_ip(self, *d):
        r = self.inflate(*d)
        self.x, self.y, self.w, self.h = r.x, r.y, r.w, r.h

    def update(self, *args):
        self.x, self.y, self.w, self.h = (int(v) for v in _rect_args(args))

    def clamp(self, other):
        r = self.copy()
        r.clamp_ip(other)
        return r

    def clamp_ip(self, other):
        o = Rect(other)
        if self.w >= o.w:
            self.x = o.x + o.w // 2 - self.w // 2
        else:
            self.x = max(o.x, min(self.x, o.right - self.w))
        if self.h >= o.h:
            self.y = o.y + o.h // 2 - self.h // 2
        else:
            self.y = max(o.y, min(self.y, o.bottom - self.h))

    def clip(self, other):
        o = Rect(other)
        x0, y0 = max(self.x, o.x), max(self.y, o.y)
        x1, y1 = min(self.right, o.right), min(self.bottom, o.bottom)
        if x1 <= x0 or y1 <= y0:
            return Rect(self.x, self.y, 0, 0)
        return Rect(x0, y0, x1 - x0, y1 - y0)

    def union(self, other):
        o = Rect(other)
        x0, y0 = min(self.x, o.x), min(self.y, o.y)
        return Rect(x0, y0, max(self.right, o.right) - x0, max(self.bottom, o.bottom) - y0)

    def union_ip(self, other):
        self.update(self.union(other))

    def unionall(self, rects):
        r = self.copy()
        for o in rects:
            r = r.union(o)
        return r

    def normalize(self):
        if self.w < 0:
            self.x += self.w
            self.w = -self.w
        if self.h < 0:
            self.y += self.h
            self.h = -self.h

    def contains(self, other):
        o = Rect(other)
        return self.x <= o.x and self.y <= o.y and o.right <= self.right and o.bottom <= self.bottom

    def collidepoint(self, *p):
        x, y = p if len(p) == 2 else p[0]
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h

    def colliderect(self, *args):
        o = Rect(*args)
        return (self.x < o.x + o.w and o.x < self.x + self.w and
                self.y < o.y + o.h and o.y < self.y + self.h and
                self.w > 0 and self.h > 0 and o.w > 0 and o.h > 0)

    def collidelist(self, rects):
        for i, r in enumerate(rects):
            if self.colliderect(r):
                return i
        return -1

    def collidelistall(self, rects):
        return [i for i, r in enumerate(rects) if self.colliderect(r)]

    def collidedict(self, d, values=False):
        for k, v in d.items():
            if self.colliderect(v if values else k):
                return (k, v)
        return None

    def fit(self, other):
        o = Rect(other)
        scale = min(o.w / self.w, o.h / self.h) if self.w and self.h else 0
        r = Rect(0, 0, int(self.w * scale), int(self.h * scale))
        r.center = o.center
        return r

    def scale_by(self, x, y=None):
        y = x if y is None else y
        r = Rect(0, 0, int(self.w * x), int(self.h * y))
        r.center = self.center
        return r


FRect = Rect
