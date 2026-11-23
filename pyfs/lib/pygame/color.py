# pygame.Color and colour conversion.

THECOLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 255, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255), "gray": (190, 190, 190),
    "grey": (190, 190, 190), "darkgray": (169, 169, 169), "lightgray": (211, 211, 211),
    "orange": (255, 165, 0), "purple": (160, 32, 240), "pink": (255, 192, 203),
    "brown": (165, 42, 42), "navy": (0, 0, 128), "darkgreen": (0, 100, 0),
    "darkblue": (0, 0, 139), "darkred": (139, 0, 0), "gold": (255, 215, 0),
    "silver": (192, 192, 192), "skyblue": (135, 206, 235), "violet": (238, 130, 238),
    "lime": (0, 255, 0), "maroon": (176, 48, 96), "olive": (128, 128, 0),
    "teal": (0, 128, 128), "coral": (255, 127, 80), "salmon": (250, 128, 114),
    "beige": (245, 245, 220), "tan": (210, 180, 140), "khaki": (240, 230, 140),
    "indigo": (75, 0, 130), "turquoise": (64, 224, 208), "crimson": (220, 20, 60),
}


def rgba(c):
    """Any pygame colour -> (r, g, b, a)."""
    if isinstance(c, Color):
        return c.r, c.g, c.b, c.a
    if isinstance(c, str):
        name = c.lower().replace(" ", "")
        if name.startswith("#") or name.startswith("0x"):
            h = name[1:] if name[0] == "#" else name[2:]
            v = int(h, 16)
            if len(h) == 8:
                return v >> 24, (v >> 16) & 255, (v >> 8) & 255, v & 255
            return v >> 16, (v >> 8) & 255, v & 255, 255
        if name not in THECOLORS:
            raise ValueError("invalid color name %r" % c)
        return THECOLORS[name] + (255,)
    if isinstance(c, int):
        return (c >> 16) & 255, (c >> 8) & 255, c & 255, (c >> 24) & 255 or 255
    if len(c) == 3:
        return int(c[0]), int(c[1]), int(c[2]), 255
    return int(c[0]), int(c[1]), int(c[2]), int(c[3])


def pixel(c):
    """Any pygame colour -> the 0xAARRGGBB pixel value."""
    if isinstance(c, int) and not isinstance(c, bool):
        return c & 0xFFFFFFFF
    r, g, b, a = rgba(c)
    return (a << 24) | (r << 16) | (g << 8) | b


def from_pixel(p):
    return Color((p >> 16) & 255, (p >> 8) & 255, p & 255, p >> 24)


class Color:
    def __init__(self, r=0, g=None, b=None, a=255):
        if g is None:
            r, g, b, a = rgba(r)
        self.r, self.g, self.b, self.a = int(r), int(g), int(b), int(a)

    def __len__(self):
        return 4

    def __getitem__(self, i):
        return (self.r, self.g, self.b, self.a)[i]

    def __iter__(self):
        return iter((self.r, self.g, self.b, self.a))

    def __eq__(self, other):
        try:
            return tuple(self) == rgba(other)
        except (TypeError, ValueError):
            return False

    def __repr__(self):
        return "Color(%d, %d, %d, %d)" % (self.r, self.g, self.b, self.a)

    def __int__(self):
        return pixel(self)

    def normalize(self):
        return (self.r / 255, self.g / 255, self.b / 255, self.a / 255)

    def lerp(self, other, t):
        o = rgba(other)
        return Color(*(int(a + (b - a) * t) for a, b in zip(self, o)))

    def grayscale(self):
        v = int(0.299 * self.r + 0.587 * self.g + 0.114 * self.b)
        return Color(v, v, v, self.a)

    rgb = property(lambda s: (s.r, s.g, s.b))
