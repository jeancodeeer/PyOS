# pygame.math: Vector2 and Vector3, the parts games use most.
import math as _m


class Vector2:
    __slots__ = ("x", "y")

    def __init__(self, x=0.0, y=None):
        if y is None:
            if isinstance(x, (tuple, list, Vector2)):
                x, y = x[0], x[1]
            else:
                y = x
        self.x, self.y = float(x), float(y)

    def __getitem__(self, i):
        return (self.x, self.y)[i]

    def __setitem__(self, i, v):
        if i == 0:
            self.x = float(v)
        else:
            self.y = float(v)

    def __len__(self):
        return 2

    def __iter__(self):
        return iter((self.x, self.y))

    def __repr__(self):
        return "Vector2(%g, %g)" % (self.x, self.y)

    def __eq__(self, o):
        return tuple(self) == tuple(o)

    def __add__(self, o):
        return Vector2(self.x + o[0], self.y + o[1])

    __radd__ = __add__

    def __sub__(self, o):
        return Vector2(self.x - o[0], self.y - o[1])

    def __rsub__(self, o):
        return Vector2(o[0] - self.x, o[1] - self.y)

    def __mul__(self, k):
        if isinstance(k, (int, float)):
            return Vector2(self.x * k, self.y * k)
        return self.x * k[0] + self.y * k[1]          # vector * vector: dot product

    __rmul__ = __mul__

    def __truediv__(self, k):
        return Vector2(self.x / k, self.y / k)

    def __neg__(self):
        return Vector2(-self.x, -self.y)

    def __bool__(self):
        return bool(self.x or self.y)

    def copy(self):
        return Vector2(self.x, self.y)

    def update(self, x=0.0, y=None):
        v = Vector2(x, y)
        self.x, self.y = v.x, v.y

    def dot(self, o):
        return self.x * o[0] + self.y * o[1]

    def cross(self, o):
        return self.x * o[1] - self.y * o[0]

    def length(self):
        return _m.sqrt(self.x * self.x + self.y * self.y)

    magnitude = length

    def length_squared(self):
        return self.x * self.x + self.y * self.y

    def normalize(self):
        n = self.length()
        if not n:
            raise ValueError("can't normalize a vector of length zero")
        return Vector2(self.x / n, self.y / n)

    def normalize_ip(self):
        self.update(self.normalize())

    def scale_to_length(self, n):
        self.update(self.normalize() * n)

    def distance_to(self, o):
        return _m.sqrt((self.x - o[0]) ** 2 + (self.y - o[1]) ** 2)

    def distance_squared_to(self, o):
        return (self.x - o[0]) ** 2 + (self.y - o[1]) ** 2

    def rotate(self, degrees):
        a = _m.radians(degrees)
        c, s = _m.cos(a), _m.sin(a)
        return Vector2(self.x * c - self.y * s, self.x * s + self.y * c)

    def rotate_ip(self, degrees):
        self.update(self.rotate(degrees))

    def angle_to(self, o):
        return _m.degrees(_m.atan2(o[1], o[0]) - _m.atan2(self.y, self.x))

    def as_polar(self):
        return self.length(), _m.degrees(_m.atan2(self.y, self.x))

    def lerp(self, o, t):
        return Vector2(self.x + (o[0] - self.x) * t, self.y + (o[1] - self.y) * t)

    def reflect(self, normal):
        n = Vector2(normal).normalize()
        return self - n * (2 * self.dot(n))


class Vector3:
    __slots__ = ("x", "y", "z")

    def __init__(self, x=0.0, y=None, z=None):
        if y is None:
            if isinstance(x, (tuple, list, Vector3)):
                x, y, z = x[0], x[1], x[2]
            else:
                y = z = x
        self.x, self.y, self.z = float(x), float(y), float(z)

    def __getitem__(self, i):
        return (self.x, self.y, self.z)[i]

    def __iter__(self):
        return iter((self.x, self.y, self.z))

    def __repr__(self):
        return "Vector3(%g, %g, %g)" % (self.x, self.y, self.z)

    def __add__(self, o):
        return Vector3(self.x + o[0], self.y + o[1], self.z + o[2])

    def __sub__(self, o):
        return Vector3(self.x - o[0], self.y - o[1], self.z - o[2])

    def __mul__(self, k):
        if isinstance(k, (int, float)):
            return Vector3(self.x * k, self.y * k, self.z * k)
        return self.x * k[0] + self.y * k[1] + self.z * k[2]

    __rmul__ = __mul__

    def length(self):
        return _m.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    def normalize(self):
        n = self.length()
        return Vector3(self.x / n, self.y / n, self.z / n)

    def cross(self, o):
        return Vector3(self.y * o[2] - self.z * o[1], self.z * o[0] - self.x * o[2], self.x * o[1] - self.y * o[0])


def clamp(value, low, high):
    return max(low, min(high, value))


def lerp(a, b, t):
    return a + (b - a) * t
