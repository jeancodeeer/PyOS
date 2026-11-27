# CSS: parse style sheets, match selectors against the HTML tree, and work
# out each element's computed style (cascade, specificity, inheritance).
# A useful subset: the properties layout.py understands.

COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
    "yellow": (255, 255, 0), "gray": (128, 128, 128), "grey": (128, 128, 128), "silver": (192, 192, 192),
    "maroon": (128, 0, 0), "purple": (128, 0, 128), "fuchsia": (255, 0, 255), "lime": (0, 255, 0),
    "olive": (128, 128, 0), "navy": (0, 0, 128), "teal": (0, 128, 128), "aqua": (0, 255, 255),
    "orange": (255, 165, 0), "pink": (255, 192, 203), "brown": (165, 42, 42), "darkgray": (169, 169, 169),
    "darkgrey": (169, 169, 169), "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211),
    "darkblue": (0, 0, 139), "darkred": (139, 0, 0), "darkgreen": (0, 100, 0), "lightblue": (173, 216, 230),
    "lightgreen": (144, 238, 144), "gold": (255, 215, 0), "indigo": (75, 0, 130), "violet": (238, 130, 238),
    "beige": (245, 245, 220), "ivory": (255, 255, 240), "khaki": (240, 230, 140), "coral": (255, 127, 80),
    "salmon": (250, 128, 114), "tomato": (255, 99, 71), "crimson": (220, 20, 60), "steelblue": (70, 130, 180),
    "royalblue": (65, 105, 225), "dodgerblue": (30, 144, 255), "skyblue": (135, 206, 235),
    "slategray": (112, 128, 144), "dimgray": (105, 105, 105), "whitesmoke": (245, 245, 245),
    "gainsboro": (220, 220, 220), "aliceblue": (240, 248, 255), "lavender": (230, 230, 250),
    "darkslategray": (47, 79, 79), "midnightblue": (25, 25, 112), "seagreen": (46, 139, 87),
    "forestgreen": (34, 139, 34), "firebrick": (178, 34, 34), "chocolate": (210, 105, 30), "tan": (210, 180, 140),
    "wheat": (245, 222, 179), "linen": (250, 240, 230), "snow": (255, 250, 250), "honeydew": (240, 255, 240),
    "mintcream": (245, 255, 250), "azure": (240, 255, 255), "ghostwhite": (248, 248, 255),
    "lightyellow": (255, 255, 224), "lightcyan": (224, 255, 255), "cyan": (0, 255, 255),
    "magenta": (255, 0, 255), "orangered": (255, 69, 0), "darkorange": (255, 140, 0),
}

INHERITED = {"color", "font-size", "font-weight", "font-style", "text-align", "white-space", "list-style-type",
             "text-decoration", "visibility", "line-height", "text-transform", "cursor"}

UA = """
html, body, div, p, h1, h2, h3, h4, h5, h6, ul, ol, li, dl, dt, dd, pre, blockquote, form, table, header, footer,
nav, section, article, aside, main, figure, figcaption, address, hr, fieldset, details, summary, center,
legend, hgroup, menu, dir, noscript, search { display: block }
head, script, style, title, meta, link, base, template, noembed, iframe, object, embed, canvas, video,
audio, map, area, param, source, track, datalist, dialog, [hidden], input[type=hidden] { display: none }
li { display: list-item }
table { display: table; border-spacing: 2px }
tr { display: table-row } td, th { display: table-cell; padding: 2px }
th { font-weight: bold; text-align: center }
thead, tbody, tfoot { display: table-row-group }
caption { display: block; text-align: center }
body { margin: 8px; color: black; background-color: white }
p, dl, blockquote, figure, pre, ul, ol, form { margin-top: 1em; margin-bottom: 1em }
h1 { font-size: 2em; font-weight: bold; margin-top: 0.67em; margin-bottom: 0.67em }
h2 { font-size: 1.5em; font-weight: bold; margin-top: 0.83em; margin-bottom: 0.83em }
h3 { font-size: 1.17em; font-weight: bold; margin-top: 1em; margin-bottom: 1em }
h4, h5, h6 { font-weight: bold; margin-top: 1.33em; margin-bottom: 1.33em }
ul, ol, menu, dir { padding-left: 40px } dd { margin-left: 40px } blockquote { margin-left: 40px; margin-right: 40px }
ul { list-style-type: disc } ol { list-style-type: decimal } ul ul { list-style-type: circle }
b, strong, dt { font-weight: bold } i, em, cite, var, dfn, address { font-style: italic }
u, ins { text-decoration: underline } s, strike, del { text-decoration: line-through }
a { color: #0645ad; text-decoration: underline }
pre, code, kbd, samp, tt { font-family: monospace } pre { white-space: pre }
hr { border-top-width: 1px; border-color: gray; margin-top: 0.5em; margin-bottom: 0.5em }
center { text-align: center }
small, sub, sup { font-size: 0.83em } big { font-size: 1.17em }
mark { background-color: yellow }
button, input, select, textarea { display: inline-block }
img, svg { display: inline-block }
details:not([open]) > :not(summary) { display: none }
summary { display: list-item; list-style-type: disclosure-closed }
br { display: inline }
"""


def split_top(text, sep):
    """Split at `sep` where it is not inside (), [] or quotes."""
    if "(" not in text and "[" not in text and '"' not in text and "'" not in text:
        return text.split(sep)                       # the usual case, done by the C split
    out, cur, depth, quote = [], "", 0, None
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == sep and depth == 0:
            out.append(cur)
            cur = ""
            continue
        cur += ch
    out.append(cur)
    return out


def tokens(value):
    """Split a CSS value at spaces and commas, but not inside parentheses."""
    if "(" not in value:
        return value.replace(",", " ").split()
    out, cur, depth = [], "", 0
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0 and (ch.isspace() or ch == ","):
            if cur:
                out.append(cur)
            cur = ""
            continue
        cur += ch
    if cur:
        out.append(cur)
    return out


def color(value):
    try:
        return _color(value)
    except (ValueError, IndexError):
        return None


def _color(value):
    v = value.strip().lower()
    if v in COLORS:
        return COLORS[v]
    if v.startswith("#"):
        h = v[1:]
        try:
            if len(h) in (3, 4):
                return tuple(int(c * 2, 16) for c in h[:3])
            if len(h) in (6, 8):
                return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return None
    if v.startswith(("rgb(", "rgba(")):
        inner = v[v.index("(") + 1:v.rindex(")")].replace("/", " ").replace(",", " ").split()
        try:
            rgb = [int(float(x[:-1]) * 2.55) if x.endswith("%") else int(float(x)) for x in inner[:3]]
            if len(inner) > 3:
                a = float(inner[3][:-1]) / 100 if inner[3].endswith("%") else float(inner[3])
                if a < 0.05:
                    return "transparent"
                rgb = [int(c * a + 255 * (1 - a)) for c in rgb]
            return tuple(max(0, min(255, c)) for c in rgb)
        except (ValueError, IndexError):
            return None
    if v.startswith(("hsl(", "hsla(")):
        inner = v[v.index("(") + 1:v.rindex(")")].replace("/", " ").replace(",", " ").split()
        try:
            h = float(inner[0].replace("deg", "")) / 360
            s = float(inner[1].rstrip("%")) / 100
            l = float(inner[2].rstrip("%")) / 100
            return _hsl(h, s, l)
        except (ValueError, IndexError):
            return None
    if v.startswith(("oklch(", "oklab(")):
        inner = v[v.index("(") + 1:v.rindex(")")].split("/")[0].replace(",", " ").split()
        try:
            L = float(inner[0][:-1]) / 100 if inner[0].endswith("%") else float(inner[0])
            if v.startswith("oklch("):
                import math
                C = float(inner[1][:-1]) * 0.004 if inner[1].endswith("%") else float(inner[1])
                hue = float(inner[2].replace("deg", "")) if inner[2] != "none" else 0.0
                a, b = C * math.cos(math.radians(hue)), C * math.sin(math.radians(hue))
            else:
                a, b = float(inner[1]), float(inner[2])
            return _oklab(L, a, b)
        except (ValueError, IndexError):
            return None
    if v == "transparent":
        return "transparent"
    return None


def _oklab(L, a, b):
    """OKLab -> sRGB (0..255)."""
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    rgb = (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
           -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
           -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)
    out = []
    for c in rgb:
        c = max(0.0, min(1.0, c))
        c = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        out.append(int(round(c * 255)))
    return tuple(out)


def _hsl(h, s, l):
    def hue(p, q, t):
        t %= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p
    if s == 0:
        r = g = b = l
    else:
        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        r, g, b = hue(p, q, h + 1 / 3), hue(p, q, h), hue(p, q, h - 1 / 3)
    return (int(r * 255), int(g * 255), int(b * 255))


VW, VH = 1000, 700               # the viewport (the browser window), for vw and vh


def length(value, font_size=16, relative_to=None):
    """A CSS length in pixels; percentages need relative_to. None if not a length."""
    v = value.strip().lower()
    if not v:
        return None
    if v in ("0", "auto"):
        return 0 if v == "0" else None
    if v.endswith(")") and v.startswith(("calc(", "min(", "max(", "clamp(", "-webkit-calc(")):
        return _math(v, font_size, relative_to)
    try:
        if v.endswith("px"):
            return int(float(v[:-2]))
        if v.endswith("rem"):
            return int(float(v[:-3]) * 16)
        if v.endswith("em"):
            return int(float(v[:-2]) * font_size)
        if v.endswith("ex") or v.endswith("ch"):
            return int(float(v[:-2]) * 8)
        if v.endswith("pt"):
            return int(float(v[:-2]) * 4 / 3)
        if v.endswith(("vw", "dvw", "svw", "lvw")):
            return int(float(v[:-2].rstrip("dsl")) * VW / 100)
        if v.endswith(("vh", "dvh", "svh", "lvh")):
            return int(float(v[:-2].rstrip("dsl")) * VH / 100)
        if v.endswith("vmin"):
            return int(float(v[:-4]) * min(VW, VH) / 100)
        if v.endswith("vmax"):
            return int(float(v[:-4]) * max(VW, VH) / 100)
        if v.endswith("%"):
            if relative_to is None:
                return ("%", float(v[:-1]))
            return int(float(v[:-1]) * relative_to / 100)
        return int(float(v))
    except ValueError:
        return None


def _math(v, font_size, relative_to):
    """calc(), min(), max(), clamp(): worked out in pixels. A percentage with
    nothing to be a percentage of counts as a share of the viewport width."""
    base = relative_to if relative_to is not None else VW
    name = v[:v.index("(")].replace("-webkit-", "")
    inner = v[v.index("(") + 1:-1]
    if name != "calc":
        vals = [_math("calc(" + a.strip() + ")", font_size, base) for a in split_top(inner, ",")]
        vals = [x for x in vals if isinstance(x, int)]
        if not vals:
            return None
        if name == "min":
            return min(vals)
        if name == "max":
            return max(vals)
        return max(vals[0], min(vals[1], vals[2])) if len(vals) == 3 else vals[0]
    # calc: numbers and lengths with + - * / and brackets, read left to right
    toks, i, n = [], 0, len(inner)
    while i < n:
        c = inner[i]
        if c.isspace():
            i += 1
        elif c in "()*/":
            toks.append(c)
            i += 1
        elif c in "+-" and (not toks or toks[-1] in "(*/+-") and i + 1 < n and (inner[i + 1].isdigit() or inner[i + 1] == "."):
            j = i + 1
            while j < n and not inner[j].isspace() and inner[j] not in "()*/":
                j += 1
            toks.append(inner[i:j])
            i = j
        elif c in "+-":
            toks.append(c)
            i += 1
        else:
            j = i
            depth = 0
            while j < n and (depth or (not inner[j].isspace() and inner[j] not in ")*/")):
                if inner[j] == "(":
                    depth += 1
                elif inner[j] == ")":
                    depth -= 1
                j += 1
            toks.append(inner[i:j])
            i = j
    pos = [0]

    def value(t):
        if t.replace(".", "", 1).lstrip("-+").isdigit():
            return float(t)                              # a plain number (for * and /)
        if "(" in t:
            r = length(t, font_size, base)
        else:
            r = length(t, font_size, base)
        return float(r) if isinstance(r, int) else 0.0

    def atom():
        t = toks[pos[0]] if pos[0] < len(toks) else "0"
        pos[0] += 1
        if t == "(":
            r = expr()
            pos[0] += 1                                  # the ")"
            return r
        return value(t)

    def term():
        r = atom()
        while pos[0] < len(toks) and toks[pos[0]] in ("*", "/"):
            op = toks[pos[0]]
            pos[0] += 1
            b = atom()
            r = r * b if op == "*" else (r / b if b else r)
        return r

    def expr():
        r = term()
        while pos[0] < len(toks) and toks[pos[0]] in ("+", "-"):
            op = toks[pos[0]]
            pos[0] += 1
            b = term()
            r = r + b if op == "+" else r - b
        return r

    try:
        return int(expr())
    except (IndexError, ValueError, ZeroDivisionError):
        return None


def substitute(value, variables, depth=0):
    """Replace var(--name, fallback) with the variable's value."""
    while "var(" in value and depth < 8:
        i = value.find("var(")
        j, level = i + 4, 1
        while j < len(value) and level:
            if value[j] == "(":
                level += 1
            elif value[j] == ")":
                level -= 1
            j += 1
        inner = value[i + 4:j - 1]
        parts = split_top(inner, ",")
        name = parts[0].strip()
        got = variables.get(name)
        if got is None:
            got = variables.get(name.lower())
        if got is None:
            got = ",".join(parts[1:]).strip() if len(parts) > 1 else ""
        value = value[:i] + got + value[j:]
        depth += 1
    return value


# ---- parsing ----

def _strip_comments(text):
    if isinstance(text, str):
        return _strip_comments(text.encode()).decode("utf-8", "replace")
    out, i = [], 0
    while True:
        j = text.find(b"/*", i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        k = text.find(b"*/", j + 2)
        if k < 0:
            break
        i = k + 2
    return b"".join(out)


def parse_declarations(text):
    decls = []
    for part in text.split(";"):
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        name = name.strip().lower()
        value = value.strip()
        important = False
        if value.lower().endswith("!important"):
            value = value[:-10].strip()
            important = True
        if name:
            decls.extend((n, v, important) for n, v in expand(name, value))
    return decls


def _sides(values):
    if len(values) == 1:
        return values * 4
    if len(values) == 2:
        return [values[0], values[1], values[0], values[1]]
    if len(values) == 3:
        return [values[0], values[1], values[2], values[1]]
    return values[:4]


def expand(name, value):
    """Shorthands -> longhands."""
    if "var(" in value and not name.startswith("--"):
        return [(name, value)]              # expanded once the variable is known (compute)
    if name in ("margin", "padding"):
        t, r, b, l = _sides(tokens(value) or ["0"])
        return [(name + "-top", t), (name + "-right", r), (name + "-bottom", b), (name + "-left", l)]
    if name in ("border", "border-top", "border-bottom", "border-left", "border-right"):
        out = []
        sides = ("top", "right", "bottom", "left") if name == "border" else (name[7:],)
        width, col = None, None
        for word in tokens(value):
            if color(word) is not None:
                col = word
            elif word in ("thin", "medium", "thick") or length(word) is not None:
                width = {"thin": "1px", "medium": "3px", "thick": "5px"}.get(word, word)
            elif word == "none":
                width = "0"
        for side in sides:
            if width is not None:
                out.append(("border-%s-width" % side, width))
            if col is not None:
                out.append(("border-color", col))
        if "solid" in value or "dotted" in value or "dashed" in value:
            if width is None:
                for side in sides:
                    out.append(("border-%s-width" % side, "1px"))
        return out
    if name == "border-width":
        t, r, b, l = _sides(tokens(value) or ["0"])
        return [("border-top-width", t), ("border-right-width", r), ("border-bottom-width", b), ("border-left-width", l)]
    if name in ("background", "background-image"):
        for word in tokens(value):
            c = color(word)
            if c is not None:
                return [("background-color", word)]
            if "gradient(" in word:                 # a gradient: its first colour, roughly
                for inner in tokens(word[word.index("(") + 1:-1]):
                    if color(inner) not in (None, "transparent"):
                        return [("background-color", inner)]
        if name == "background-image":
            return []
        if value.strip() in ("none", "transparent"):
            return [("background-color", "transparent")]
        return []
    if name == "font":
        out = []
        for word in value.split():
            if word in ("bold", "bolder", "700", "800", "900"):
                out.append(("font-weight", "bold"))
            elif word == "italic":
                out.append(("font-style", "italic"))
            elif length(word.split("/")[0]) is not None and not word[0].isalpha():
                out.append(("font-size", word.split("/")[0]))
        return out
    if name == "list-style":
        for word in value.split():
            if word in ("none", "disc", "circle", "square", "decimal", "lower-alpha", "upper-alpha", "lower-roman",
                        "upper-roman"):
                return [("list-style-type", word)]
        return []
    if name == "text-decoration-line":
        return [("text-decoration", value)]
    if name == "gap":
        parts = tokens(value)
        return [("row-gap", parts[0]), ("column-gap", parts[-1])]
    if name == "flex":
        v = value.strip().lower()
        if v == "none":
            return [("flex-grow", "0"), ("flex-shrink", "0"), ("flex-basis", "auto")]
        if v == "auto":
            return [("flex-grow", "1"), ("flex-shrink", "1"), ("flex-basis", "auto")]
        parts = v.split()
        out, nums = [], [w for w in parts if w.replace(".", "", 1).isdigit()]
        basis = [w for w in parts if w not in nums]
        out.append(("flex-grow", nums[0] if nums else "1"))
        out.append(("flex-shrink", nums[1] if len(nums) > 1 else "1"))
        out.append(("flex-basis", basis[0] if basis else "0%"))
        return out
    if name == "flex-flow":
        out = []
        for w in value.split():
            out.append(("flex-wrap" if "wrap" in w else "flex-direction", w))
        return out
    if name == "place-items":
        return [("align-items", value.split()[0])]
    if name == "grid-column" or name == "grid-area":
        return [("grid-column", value)]
    return [(name, value)]


# pseudo-classes and pseudo-elements this browser is never in (no hover, no focus...) or
# never draws: a rule about them is dropped when the sheet is read
NEVER = ("hover", "focus", "active", "before", "after", "visited", "checked", "disabled", "target", "placeholder",
         "selection", "-", "file-selector-button", "backdrop", "host", "marker", "first-line", "first-letter",
         "cue", "part(", "slotted(", "spelling-error", "grammar-error", "view-transition", "autofill",
         "invalid", "user-invalid", "fullscreen", "modal", "popover-open", "open", "indeterminate", "read-write",
         "default", "in-range", "out-of-range", "target-text", "picture-in-picture", "playing", "paused")


class Rule:
    __slots__ = ("selector", "decls", "spec", "order", "need", "trivial", "vars")

    def __init__(self, selector, decls, spec, order):
        self.selector, self.decls, self.spec, self.order = selector, decls, spec, order
        self.vars = any(n[:2] == "--" or "var(" in v for n, v, _ in decls)   # custom properties in it
        # ".x", "p" or "#y" alone: every element the index offers for it matches, no need to check
        compounds = selector[0]
        tag, ident, classes, attrs, pseudos = compounds[0]
        self.trivial = len(compounds) == 1 and not attrs and not pseudos and \
            (bool(tag) + bool(ident) + len(classes)) <= 1
        # tags/classes/ids some ancestor must have (descendant and child combinators)
        need = []
        compounds, combs = selector
        for i in range(1, len(compounds)):
            if combs[i - 1] in (" ", ">"):
                tag, ident, classes, attrs, pseudos = compounds[i]
                if ident:
                    need.append("#" + ident)
                for c in classes:
                    need.append("." + c)
                if tag:
                    need.append(tag)
        self.need = need


def _name(s, i):
    """A class or id name starting at i, with CSS escapes ('md\\:flex'): (name, end)."""
    out, n = "", len(s)
    while i < n and s[i] not in ".#[:":
        if s[i] == "\\" and i + 1 < n:
            j = i + 1
            hexd = ""
            while j < n and len(hexd) < 6 and s[j] in "0123456789abcdefABCDEF":
                hexd += s[j]
                j += 1
            if hexd:                                   # \31 0 -> "10"
                out += chr(int(hexd, 16))
                i = j + 1 if j < n and s[j] == " " else j
                continue
            out += s[i + 1]
            i += 2
            continue
        out += s[i]
        i += 1
    return out, i


def _split_compound(s):
    """'div.a#b[x]:hover' -> (tag, id, classes, attrs, pseudos)."""
    if "[" not in s and ":" not in s and "\\" not in s:
        # the usual case (div, .a, div.a.b, #x): split by the C methods, not char by char
        tag, ident, classes = None, None, []
        i = 0
        while i < len(s) and s[i] not in ".#":
            i += 1
        if i:
            tag = s[:i].lower()
            if tag == "*":
                tag = None
        rest = s[i:]
        if "#" in rest:
            parts = rest.replace("#", ".#").split(".")
        else:
            parts = rest.split(".")
        for part in parts:
            if not part:
                continue
            if part[0] == "#":
                ident = part[1:]
            else:
                classes.append(part)
        return (tag, ident, classes, [], [])
    tag, ident, classes, attrs, pseudos = None, None, [], [], []
    i, n = 0, len(s)
    start = i
    while i < n and s[i] not in ".#[:":
        i += 1
    if i > start:
        tag = s[start:i].lower()
        if tag == "*":
            tag = None
    while i < n:
        c = s[i]
        if c in ".#":
            name, j = _name(s, i + 1)
            if c == ".":
                classes.append(name)
            else:
                ident = name
            i = j
        elif c == "[":
            j = s.find("]", i)
            if j < 0:
                j = n
            body = s[i + 1:j]
            for op in ("~=", "^=", "$=", "*=", "|=", "="):
                if op in body:
                    k, v = body.split(op, 1)
                    attrs.append((k.strip().lower(), op, v.strip().strip("\"'")))
                    break
            else:
                attrs.append((body.strip().lower(), None, None))
            i = j + 1
        elif c == ":":
            j = i + 1
            if j < n and s[j] == ":":
                j += 1
            depth = 0
            while j < n and (depth or s[j] not in ".#[:"):
                if s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    depth -= 1
                j += 1
            p = s[i:j].lstrip(":")
            k = p.find("(")
            if k > 0 and p.endswith(")"):
                name = p[:k]
                if name in ("is", "where", "matches", "-webkit-any", "not"):
                    alts = [a.strip() for a in split_top(p[k + 1:-1], ",")]
                    simple = [_split_compound(a) for a in alts if a and not any(ch in a for ch in " >+~")]
                    complex_ = []                       # '.dark *', 'nav > a': whole selectors
                    for a in alts:
                        if a and any(ch in a for ch in " >+~"):
                            try:
                                complex_.append(parse_selector(a))
                            except Exception:
                                pass
                    p = (name, simple, complex_)
            pseudos.append(p)
            i = j
        else:
            i += 1
    return (tag, ident, classes, attrs, pseudos)


def parse_selector(text):
    """'div > p.x a' -> [(compound, combinator_to_the_left), ...] right to left."""
    if not any(c in text for c in ">+~([\"'"):
        comps = [_split_compound(w) for w in text.split()]       # the usual case: descendants only
        comps.reverse()
        return comps, [" "] * len(comps)
    parts = []
    for word in split_top(" ".join(text.split()), " "):
        # a combinator glued to a compound ('a>b'), outside () and []
        buf, depth = "", 0
        for ch in word:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            if depth == 0 and ch in ">+~" and not buf.endswith("("):
                if buf:
                    parts.append(buf)
                parts.append(ch)
                buf = ""
                continue
            buf += ch
        if buf:
            parts.append(buf)
    chain, comb = [], " "
    items = []
    for p in parts:
        if p in (">", "+", "~"):
            comb = p
            continue
        items.append((p, comb))
        comb = " "
    for p, c in items:
        chain.append((_split_compound(p), c))
    chain.reverse()
    out = []
    for i, (comp, c) in enumerate(chain):
        # the combinator stored on an item says how it relates to the next one to the LEFT
        left_comb = chain[i - 1][1] if i > 0 else None
        out.append(comp)
    combs = [c for _, c in chain]      # combs[i]: relation between item i and item i+1 (to its left)
    return out, combs


def _specificity(compounds):
    a = b = c = 0
    for tag, ident, classes, attrs, pseudos in compounds:
        if ident:
            a += 1
        b += len(classes) + len(attrs) + len([p for p in pseudos if not (isinstance(p, str) and p.startswith(("before", "after")))])
        if tag:
            c += 1
    return (a, b, c)


class StyleSheet:
    def __init__(self):
        self.rules = []
        self.by_id, self.by_class, self.by_tag, self.universal = {}, {}, {}, []
        self.by_attr = {}
        self.multi = False               # a rule is indexed under more than one key
        self.order = 0

    def add(self, text, viewport_w=1000):
        # bytes: indexing a long str is slow in MicroPython (UTF-8 inside)
        if isinstance(text, str):
            text = text.encode("utf-8")
        text = _strip_comments(text)
        self._parse_block(text, viewport_w)

    def _parse_block(self, text, vw):
        i, n = 0, len(text)
        while i < n:
            brace = text.find(b"{", i)
            if brace < 0:
                break
            head = text[i:brace].strip().decode("utf-8", "replace")
            if ";" in head and head.lstrip().startswith("@") and not head.lower().startswith(("@media", "@supports", "@layer")):
                # '@import ...;' or '@charset ...;' before this block
                cut = text.find(b";", i, brace)
                i = cut + 1
                continue
            if head.startswith("@"):
                end = _match_brace(text, brace)
                inner = text[brace + 1:end]
                low = head.lower()
                if low.startswith("@media") and _media_ok(low[6:], vw):
                    self._parse_block(inner, vw)
                elif low.startswith(("@supports", "@layer", "@container", "@scope", "@document", "@starting-style")) \
                        and not low.startswith("@starting-style"):
                    self._parse_block(inner, vw)        # Tailwind 4 puts every rule inside @layer
                i = end + 1
                continue
            close = text.find(b"}", brace)
            if close < 0:
                close = n
            decls = parse_declarations(text[brace + 1:close].decode("utf-8", "replace"))
            if decls:
                for sel in split_top(head, ","):
                    sel = sel.strip()
                    if not sel or "@" in sel:
                        continue
                    try:
                        compounds, combs = parse_selector(sel)
                    except Exception:
                        continue
                    if not compounds:
                        continue
                    # pseudo-elements and states we never are in: skip
                    last_pseudos = compounds[0][4]
                    if any(isinstance(p, str) and p.startswith(NEVER) for p in last_pseudos):
                        continue
                    self.order += 1
                    rule = Rule((compounds, combs), decls, _specificity(compounds), self.order)
                    self._index(rule, compounds[0])
            i = close + 1

    def _index(self, rule, key):
        tag, ident, classes, attrs, pseudos = key
        if ident:
            self.by_id.setdefault(ident, []).append(rule)
        elif classes:
            self.by_class.setdefault(classes[0], []).append(rule)
        elif tag:
            self.by_tag.setdefault(tag, []).append(rule)
        elif attrs:
            self.by_attr.setdefault(attrs[0][0], []).append(rule)
        else:
            # ':is(.a, b, #c)' alone: index under each alternative's id, class or tag, when they all
            # have one: then it is only tried on elements that could match (not on every element)
            if "root" in pseudos:
                self.by_tag.setdefault("html", []).append(rule)
                return
            for p in pseudos:
                if isinstance(p, tuple) and p[0] in ("is", "where", "matches") and (p[1] or p[2]):
                    # every alternative, simple or not, by its rightmost part
                    alts = list(p[1]) + [sel[0][0] for sel in p[2] if sel[0]]
                    if not all(a[1] or a[2] or a[0] for a in alts):
                        continue
                    self.multi = self.multi or len(alts) > 1
                    for a in alts:
                        if a[1]:
                            self.by_id.setdefault(a[1], []).append(rule)
                        elif a[2]:
                            self.by_class.setdefault(a[2][0], []).append(rule)
                        else:
                            self.by_tag.setdefault(a[0], []).append(rule)
                    return
            self.universal.append(rule)

    def candidates(self, node):
        out = list(self.universal)
        ident = node.attrs.get("id")
        if ident and ident in self.by_id:
            out += self.by_id[ident]
        for c in node.classes():
            if c in self.by_class:
                out += self.by_class[c]
        if node.tag in self.by_tag:
            out += self.by_tag[node.tag]
        if self.by_attr:
            for name in node.attrs:
                if name in self.by_attr:
                    out += self.by_attr[name]
        if self.multi and len(out) > 1:
            seen, uniq = set(), []
            for r in out:
                if id(r) not in seen:
                    seen.add(id(r))
                    uniq.append(r)
            return uniq
        return out


def _match_brace(text, i):
    """Index of the '}' closing the '{' at i (text is bytes)."""
    depth = 0
    n = len(text)
    while i < n:
        a = text.find(b"{", i)
        b = text.find(b"}", i)
        if b < 0:
            return n
        if 0 <= a < b:
            depth += 1
            i = a + 1
        else:
            depth -= 1
            if depth == 0:
                return b
            i = b + 1
    return n


def _media_ok(query, vw):
    """Does a media query hold for this browser? A screen vw wide, light colours,
    a mouse, landscape. 'a, b' is "or"; 'and' joins conditions; 'not' turns it round."""
    q = query.strip().lower()
    if not q:
        return True
    for part in split_top(q, ","):
        p = part.strip()
        negate = p.startswith("not ")
        if negate:
            p = p[4:]
        p = p.replace("only ", "")
        ok = True
        for cond in p.replace(" and ", "\n").replace(" or ", "\n").split("\n"):
            cond = cond.strip()
            if cond.startswith("not ") or cond.startswith("not("):
                inner = cond[3:].strip()
                if _media_feature(inner.strip("() "), vw):
                    ok = False
                continue
            if cond.startswith("("):
                if not _media_feature(cond.strip("() "), vw):
                    ok = False
            elif cond in ("print", "speech", "tv", "handheld"):
                ok = False
            # "screen", "all": fine
        if ok != negate:
            return True
    return False


def _media_feature(f, vw):
    if ":" not in f:
        if any(op in f for op in ("<", ">")):          # range syntax: (width >= 600px), (400px <= width < 800px)
            return _media_range(f, vw)
        return f not in ("monochrome", "grid", "scan")    # (color), (hover)... : yes
    k, v = f.split(":", 1)
    k, v = k.strip(), v.strip()
    px = length(v) if k.endswith(("width", "height")) else None
    if k in ("max-width", "max-device-width"):
        return isinstance(px, int) and vw <= px
    if k in ("min-width", "min-device-width"):
        return isinstance(px, int) and vw >= px
    if k == "width":
        return px == vw
    if k == "max-height":
        return isinstance(px, int) and VH <= px
    if k == "min-height":
        return isinstance(px, int) and VH >= px
    if k == "prefers-color-scheme":
        return v == "light"
    if k == "prefers-reduced-motion":
        return v == "reduce"                            # nothing moves here
    if k in ("prefers-contrast", "forced-colors", "inverted-colors"):
        return v in ("no-preference", "none")
    if k in ("hover", "any-hover"):
        return v == "hover"
    if k in ("pointer", "any-pointer"):
        return v == "fine"
    if k == "orientation":
        return v == "landscape"
    if k in ("min-resolution", "min-device-pixel-ratio", "-webkit-min-device-pixel-ratio"):
        return v.startswith(("1", "96dpi", "0"))
    if k in ("max-resolution", "max-device-pixel-ratio", "-webkit-max-device-pixel-ratio"):
        return True
    if k == "display-mode":
        return v == "browser"
    return True


def _media_range(f, vw):
    w, cur, i = [], "", 0
    while i < len(f):                                  # split at <, >, <=, >=
        c = f[i]
        if c in "<>":
            if cur.strip():
                w.append(cur.strip())
            cur = ""
            op = c + ("=" if f[i + 1:i + 2] == "=" else "")
            w.append(op)
            i += len(op)
            continue
        cur += c
        i += 1
    if cur.strip():
        w.append(cur.strip())
    vals = []
    for t in w:
        if t in ("width", "height"):
            vals.append(vw if t == "width" else VH)
        elif t in ("<=", ">=", "<", ">"):
            vals.append(t)
        else:
            px = length(t)
            if not isinstance(px, int):
                return True
            vals.append(px)
    for i in range(1, len(vals) - 1, 2):
        a, op, b = vals[i - 1], vals[i], vals[i + 1]
        if not ((op == "<" and a < b) or (op == "<=" and a <= b) or (op == ">" and a > b) or (op == ">=" and a >= b)):
            return False
    return True


def _compound_matches(node, comp):
    tag, ident, classes, attrs, pseudos = comp
    if node.tag is None or node.tag == "document":
        return False
    if tag and node.tag != tag:
        return False
    if ident and node.attrs.get("id") != ident:
        return False
    if classes:
        mine = node.classes()
        for c in classes:
            if c not in mine:
                return False
    for name, op, value in attrs:
        have = node.attrs.get(name)
        if have is None:
            return False
        if op == "=" and have != value:
            return False
        if op == "~=" and value not in have.split():
            return False
        if op == "^=" and not have.startswith(value):
            return False
        if op == "$=" and not have.endswith(value):
            return False
        if op == "*=" and value not in have:
            return False
        if op == "|=" and not (have == value or have.startswith(value + "-")):
            return False
    for p in pseudos:
        if isinstance(p, tuple):
            name, alts, complex_ = p
            hit = any(_compound_matches(node, a) for a in alts) or \
                any(matches(node, sel) for sel in complex_ if sel[0])
            if name == "not":
                if hit:
                    return False
            elif not hit:
                return False
            continue
        if p in ("link", "any-link"):
            if node.tag != "a" or "href" not in node.attrs:
                return False
        elif p == "first-child":
            sib = [c for c in node.parent.children if c.tag]
            if not sib or sib[0] is not node:
                return False
        elif p == "last-child":
            sib = [c for c in node.parent.children if c.tag]
            if not sib or sib[-1] is not node:
                return False
        elif p in ("root",):
            if node.tag != "html":
                return False
        elif p.startswith(("nth-", "first-of-type", "last-of-type", "only-")) or p == "empty":
            if not _structural(node, p):
                return False
        else:
            return False
    return True


def _structural(node, p):
    """:nth-child(2n+1), :nth-of-type(3), :last-of-type, :only-child, :empty..."""
    if p == "empty":
        return not any(c.tag or c.text.strip() for c in node.children)
    sibs = [c for c in node.parent.children if c.tag] if node.parent else [node]
    if "of-type" in p:
        sibs = [c for c in sibs if c.tag == node.tag]
    if p in ("first-of-type",):
        return sibs[0] is node
    if p in ("last-of-type",):
        return sibs[-1] is node
    if p.startswith("only-"):
        return len(sibs) == 1
    k = sibs.index(node) + 1 if node in sibs else 1
    if p.startswith("nth-last-"):
        k = len(sibs) - k + 1
    arg = p[p.find("(") + 1:p.rfind(")")].strip().lower().replace(" ", "") if "(" in p else "1"
    if " of " in arg or "of" in arg and not arg.replace("of", "").strip():
        return True
    if arg == "odd":
        a, b = 2, 1
    elif arg == "even":
        a, b = 2, 0
    elif "n" in arg:
        front, _, back = arg.partition("n")
        a = -1 if front == "-" else 1 if front in ("", "+") else int(front)
        b = int(back) if back else 0
    else:
        try:
            return k == int(arg)
        except ValueError:
            return True
    if a == 0:
        return k == b
    return (k - b) % a == 0 and (k - b) // a >= 0


def matches(node, selector):
    compounds, combs = selector
    if not _compound_matches(node, compounds[0]):
        return False
    cur = node
    for i in range(1, len(compounds)):
        comb = combs[i - 1]
        comp = compounds[i]
        if comb == ">":
            cur = cur.parent
            if cur is None or not _compound_matches(cur, comp):
                return False
        elif comb in ("+", "~"):
            sibs = [c for c in cur.parent.children if c.tag] if cur.parent else []
            k = sibs.index(cur) if cur in sibs else 0
            found = None
            for s in reversed(sibs[:k]):
                if _compound_matches(s, comp):
                    found = s
                    break
                if comb == "+":
                    break
            if found is None:
                return False
            cur = found
        else:
            cur = cur.parent
            while cur is not None and not _compound_matches(cur, comp):
                cur = cur.parent
            if cur is None:
                return False
    return True


_ua = None


def ua_sheet():
    global _ua
    if _ua is None:
        _ua = StyleSheet()
        _ua.add(UA)
    return _ua


ROOT_STYLE = {"display": "block", "color": (0, 0, 0), "font-size": 16, "font-weight": "normal",
              "font-style": "normal", "text-align": "left", "white-space": "normal", "list-style-type": "disc",
              "text-decoration": "none", "visibility": "visible", "text-transform": "none"}


def _keys(node):
    out = [node.tag]
    ident = node.attrs.get("id")
    if ident:
        out.append("#" + ident)
    for c in node.classes():
        out.append("." + c)
    return out


_NO_VARS = {}
# converted values, shared by every element: pages repeat the same declarations thousands of times
_VALUES = {}
_MISSING, _SKIP, _INHERIT, _RESET, _CURRENT = object(), object(), object(), object(), object()


def _convert(name, value, fs):
    """One declaration's value as layout.py wants it (pixels, colours...), or a marker."""
    v = value.strip()
    low = v.lower()
    if low == "inherit":
        return _INHERIT
    if low in ("initial", "unset", "revert", "revert-layer"):
        return _RESET
    if name in ("color", "background-color", "border-color"):
        if low == "currentcolor":
            return _CURRENT
        c = color(v)
        return _SKIP if c is None else c
    if name in LENGTH_PROPS:
        if low == "auto":
            return "auto"
        px = length(v, fs)
        return _SKIP if px is None else px
    if name == "font-weight":
        return "bold" if low in ("bold", "bolder", "600", "700", "800", "900") else "normal"
    return low
# properties whose values are lengths (pixels)
LENGTH_PROPS = set(["width", "max-width", "min-width", "height", "text-indent", "line-height", "gap", "min-height",
                    "max-height", "border-spacing", "column-gap", "row-gap", "flex-basis"] +
                   [a + "-" + b for a in ("margin", "padding") for b in ("top", "right", "bottom", "left")] +
                   ["border-%s-width" % b for b in ("top", "right", "bottom", "left")])


def compute(root, sheets, viewport_w=1000):
    """Set node.style (a dict) for every element under root."""
    global VW
    VW = viewport_w
    ua = ua_sheet()
    stack = [(root, ROOT_STYLE)]
    above = {}                       # tags/classes/ids of the current node's ancestors -> count
    while stack:
        node, parent_style = stack.pop()
        if parent_style is None:     # leaving `node`: its keys stop being ancestors
            for k in _keys(node):
                n = above[k] - 1
                if n:
                    above[k] = n
                else:
                    del above[k]
            continue
        if node.tag is None:
            continue
        if node.tag == "document":
            node.style = dict(ROOT_STYLE)
            for c in reversed(node.children):
                stack.append((c, node.style))
            continue
        matched = []
        uses_vars = False
        for sheet_rank, sheet in ((0, ua), ) + tuple((1, s) for s in sheets):
            for rule in sheet.candidates(node):
                need = rule.need
                if need:
                    ok = True
                    for k in need:
                        if k not in above:
                            ok = False
                            break
                    if not ok:
                        continue
                if rule.trivial or matches(node, rule.selector):
                    matched.append((sheet_rank, rule.spec, rule.order, rule.decls))
                    if rule.vars:
                        uses_vars = True
        if len(matched) > 1:
            matched.sort()                      # (sheet, specificity, order): order is unique, so decls never compared
        declared = {}
        important = {}
        for _, _, _, decls in matched:
            for name, value, imp in decls:
                (important if imp else declared)[name] = value
        inline = node.attrs.get("style")
        if inline:
            if "var(" in inline or "--" in inline:
                uses_vars = True
            for name, value, imp in parse_declarations(inline):
                (important if imp else declared)[name] = value
        declared.update(important)
        _presentational(node, declared)
        style = {}
        for k in INHERITED:
            if k in parent_style:
                style[k] = parent_style[k]
        # custom properties (--name): inherited, and used through var()
        variables = parent_style.get("--", _NO_VARS)
        own = [(n, v) for n, v in declared.items() if n[:2] == "--"] if uses_vars else None
        if own:
            variables = dict(variables)
            for n, v in own:
                variables[n] = substitute(v.strip(), variables) if "var(" in v else v.strip()
        style["--"] = variables
        if uses_vars:
            fixed = {}
            for n, v in declared.items():
                if n.startswith("--"):
                    continue
                if "var(" in v:
                    for n2, v2 in expand(n, substitute(v, variables)):
                        fixed[n2] = v2
                else:
                    fixed[n] = v
            declared = fixed
        fs = parent_style.get("font-size", 16)
        if "font-size" in declared:
            v = declared["font-size"].strip().lower()
            named = {"xx-small": 9, "x-small": 10, "small": 13, "medium": 16, "large": 18, "x-large": 24,
                     "xx-large": 32, "smaller": int(fs * 0.83), "larger": int(fs * 1.2)}
            px = named.get(v)
            if px is None:
                px = length(v, fs, fs)
            if isinstance(px, int) and px > 0:
                style["font-size"] = px
        fs = style.get("font-size", fs)
        cache = _VALUES
        for name, value in declared.items():
            if name == "font-size":
                continue
            key = (name, value, fs)
            got = cache.get(key, _MISSING)
            if got is _MISSING:
                got = _convert(name, value, fs)
                if len(cache) > 20000:              # a bounded cache
                    cache.clear()
                cache[key] = got
            if got is _SKIP:
                continue
            if got is _INHERIT:
                if name in parent_style:
                    style[name] = parent_style[name]
            elif got is _RESET:
                style.pop(name, None)
            elif got is _CURRENT:
                c = style.get("color", parent_style.get("color"))
                if c is not None:
                    style[name] = c
            else:
                style[name] = got
        if style.get("background-clip") == "text" or style.get("-webkit-background-clip") == "text":
            bg = style.pop("background-color", None)        # gradient text: the gradient's colour, no box
            if isinstance(bg, tuple):
                style["color"] = bg
        fill = style.get("-webkit-text-fill-color")
        if fill and fill not in ("transparent", "currentcolor", "inherit"):
            c = color(fill)
            if isinstance(c, tuple):
                style["color"] = c
        style.setdefault("display", "inline")
        if node.attrs.get("hidden") is not None:
            style["display"] = "none"
        node.style = style
        if style["display"] != "none" and node.children:
            stack.append((node, None))
            for k in _keys(node):
                above[k] = above.get(k, 0) + 1
            for c in reversed(node.children):
                stack.append((c, style))


def _presentational(node, declared):
    """Old HTML attributes that act like CSS (bgcolor, align, width...)."""
    a = node.attrs
    if "bgcolor" in a and "background-color" not in declared:
        declared["background-color"] = a["bgcolor"]
    if node.tag == "font":
        if "color" in a:
            declared.setdefault("color", a["color"])
        if "size" in a:
            try:
                n = int(a["size"].lstrip("+"))
                declared.setdefault("font-size", "%dpx" % (10, 13, 16, 18, 24, 32, 48)[max(0, min(6, n - 1))])
            except ValueError:
                pass
    if "align" in a and node.tag in ("p", "div", "h1", "h2", "h3", "h4", "td", "th", "tr", "center"):
        declared.setdefault("text-align", a["align"].lower())
    if "width" in a and node.tag in ("table", "td", "th", "img", "hr"):
        w = a["width"]
        declared.setdefault("width", w if w.endswith("%") else w + "px")
    if "height" in a and node.tag in ("img",):
        declared.setdefault("height", a["height"] + "px" if a["height"].isdigit() else a["height"])
    if node.tag == "table" and a.get("border", "0") not in ("0", ""):
        declared.setdefault("border-top-width", "1px")
        declared.setdefault("border-bottom-width", "1px")
        declared.setdefault("border-left-width", "1px")
        declared.setdefault("border-right-width", "1px")
    if node.tag == "body" and "text" in a:
        declared.setdefault("color", a["text"])
