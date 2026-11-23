# HTML parser: text -> a tree of Nodes. Forgiving: unclosed tags close
# themselves the way browsers do, unknown tags are kept, entities decoded.

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
        "track", "wbr"}
RAW = {"script", "style", "textarea", "title", "xmp"}
# opening one of these closes an open element of the listed kinds
AUTO_CLOSE = {
    "p": {"p"}, "li": {"li"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"}, "tr": {"tr", "td", "th"},
    "td": {"td", "th"}, "th": {"td", "th"}, "option": {"option"}, "thead": {"tbody", "thead"},
    "tbody": {"tbody", "thead", "tr", "td", "th"}, "tfoot": {"tbody"},
}
BLOCKS_CLOSE_P = {"address", "article", "aside", "blockquote", "div", "dl", "fieldset", "figure", "footer", "form",
                  "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "nav", "ol", "pre", "section",
                  "table", "ul"}
ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": "\xa0", "copy": "\xa9",
            "reg": "\xae", "trade": "™", "hellip": "…", "mdash": "—", "ndash": "–",
            "laquo": "\xab", "raquo": "\xbb", "lsquo": "‘", "rsquo": "’", "ldquo": "“",
            "rdquo": "”", "bull": "•", "middot": "\xb7", "deg": "\xb0", "euro": "€",
            "pound": "\xa3", "yen": "\xa5", "cent": "\xa2", "times": "\xd7", "divide": "\xf7", "para": "\xb6",
            "sect": "\xa7", "iexcl": "\xa1", "iquest": "\xbf", "aacute": "\xe1", "eacute": "\xe9",
            "iacute": "\xed", "oacute": "\xf3", "uacute": "\xfa", "ntilde": "\xf1", "Aacute": "\xc1",
            "Eacute": "\xc9", "Iacute": "\xcd", "Oacute": "\xd3", "Uacute": "\xda", "Ntilde": "\xd1",
            "uuml": "\xfc", "Uuml": "\xdc", "ouml": "\xf6", "auml": "\xe4", "ccedil": "\xe7", "larr": "←",
            "rarr": "→", "uarr": "↑", "darr": "↓", "shy": "", "zwj": "", "zwnj": "", "thinsp": " ",
            "ensp": " ", "emsp": " "}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "text", "style", "box", "_cls")

    def __init__(self, tag, attrs=None, parent=None, text=None):
        self.tag = tag                 # None for text nodes
        self.attrs = attrs or {}
        self.children = []
        self.parent = parent
        self.text = text
        self.style = None
        self.box = None
        self._cls = None

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    def classes(self):
        c = self._cls
        if c is None:
            c = self._cls = self.attrs.get("class", "").split()
        return c

    def iter(self, tag=None):
        stack = [self]
        while stack:
            n = stack.pop()
            if n.tag is not None and (tag is None or n.tag == tag):
                yield n
            stack.extend(reversed(n.children))

    def find(self, tag):
        for n in self.iter(tag):
            return n
        return None

    def text_content(self):
        if self.tag is None:
            return self.text
        return "".join(c.text_content() for c in self.children)

    def __repr__(self):
        return "<%s>" % self.tag if self.tag else "<text %r>" % (self.text or "")[:20]


def unescape(s):
    if "&" not in s:
        return s
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c != "&":
            j = s.find("&", i)
            if j < 0:
                j = n
            out.append(s[i:j])
            i = j
            continue
        j = s.find(";", i, i + 12)
        if j < 0:
            out.append("&")
            i += 1
            continue
        name = s[i + 1:j]
        if name.startswith("#"):
            try:
                code = int(name[2:], 16) if name[1:2] in ("x", "X") else int(name[1:])
                out.append(chr(code) if 0 < code < 0x110000 else "?")
            except ValueError:
                out.append(s[i:j + 1])
        elif name in ENTITIES:
            out.append(ENTITIES[name])
        else:
            out.append(s[i:j + 1])
        i = j + 1
    return "".join(out)


def _parse_attrs(s):
    """Attributes from the inside of a tag (bytes) -> {name: str}."""
    attrs, i, n = {}, 0, len(s)
    SP = b" \t\r\n"
    while i < n:
        while i < n and (s[i] in SP or s[i] == 47):        # spaces and '/'
            i += 1
        start = i
        while i < n and s[i] not in SP and s[i] not in b"=/>":
            i += 1
        name = s[start:i].lower().decode("utf-8", "replace")
        if not name:
            i += 1
            continue
        while i < n and s[i] in SP:
            i += 1
        value = ""
        if i < n and s[i] == 61:                            # '='
            i += 1
            while i < n and s[i] in SP:
                i += 1
            if i < n and s[i] in b"\"'":
                q = s[i:i + 1]
                j = s.find(q, i + 1)
                if j < 0:
                    j = n
                value = s[i + 1:j].decode("utf-8", "replace")
                i = j + 1
            else:
                start = i
                while i < n and s[i] not in SP and s[i] != 62:
                    i += 1
                value = s[start:i].decode("utf-8", "replace")
        attrs[name] = unescape(value)
    return attrs


def _tag_end(text, lt):
    """Index of the '>' that ends the tag at lt; quotes may contain '>'."""
    gt = text.find(b">", lt)
    if gt < 0:
        return -1
    if text.find(b'"', lt, gt) < 0 and text.find(b"'", lt, gt) < 0:
        return gt                              # the common case: no quotes before '>'
    i, n, quote = lt + 1, len(text), 0
    while i < n:
        c = text[i]
        if quote:
            if c == quote:
                quote = 0
        elif c == 34 or c == 39:               # " or '
            p = text[i - 1]
            if p == 61 or p in b" \t\r\n":
                quote = c
        elif c == 62:
            return i
        i += 1
    return -1


def _dec(b):
    return b.decode("utf-8", "replace")


def parse(text):
    """HTML text -> the root Node (tag 'document').

    Works on bytes: MicroPython stores str as UTF-8, so indexing a str is
    slow; bytes index in constant time. Pieces are decoded as they are cut."""
    if isinstance(text, str):
        text = text.encode("utf-8")
    root = Node("document")
    html = Node("html", {}, root)
    root.children.append(html)
    stack = [root, html]
    i, n = 0, len(text)
    lower = None

    def current():
        return stack[-1]

    def add_text(s):
        if not s:
            return
        parent = current()
        if parent.children and parent.children[-1].tag is None:
            parent.children[-1].text += s
        else:
            parent.children.append(Node(None, None, parent, s))

    def close(tag):
        for k in range(len(stack) - 1, 0, -1):
            if stack[k].tag == tag:
                del stack[k:]
                return True
            if stack[k].tag in ("table", "body", "html") and tag not in ("table", "body", "html"):
                return False
        return False

    while i < n:
        lt = text.find(b"<", i)
        if lt < 0:
            add_text(unescape(_dec(text[i:])))
            break
        if lt > i:
            add_text(unescape(_dec(text[i:lt])))
        if text.startswith(b"<!--", lt):
            end = text.find(b"-->", lt + 4)
            i = n if end < 0 else end + 3
            continue
        nxt = text[lt + 1] if lt + 1 < n else 0
        if nxt == 33 or nxt == 63:                 # <! or <?
            end = text.find(b">", lt)
            i = n if end < 0 else end + 1
            continue
        end = _tag_end(text, lt)
        if end < 0:
            add_text(unescape(_dec(text[lt:])))
            break
        inside = text[lt + 1:end]
        i = end + 1
        first = inside[0] if inside else 0
        if not (65 <= first <= 90 or 97 <= first <= 122 or first == 47):
            add_text("<")
            i = lt + 1
            continue
        if first == 47:                            # closing tag
            rest = inside[1:].strip()
            tag = _dec(rest.split()[0].lower()) if rest else ""
            if tag == "p" and not any(s.tag == "p" for s in stack):
                current().children.append(Node("p", {}, current()))
            elif tag in ("html", "body", "head"):
                pass
            else:
                close(tag)
            continue
        parts = inside.split(None, 1)
        tag = _dec(parts[0].lower().rstrip(b"/"))
        attrs = _parse_attrs(parts[1]) if len(parts) > 1 else {}
        if tag == "html":
            html.attrs.update(attrs)
            continue
        if tag in ("head", "body"):
            node = Node(tag, attrs, html)
            html.children.append(node)
            del stack[2:]
            stack.append(node)
            continue
        closes = AUTO_CLOSE.get(tag)
        if closes:
            for k in range(len(stack) - 1, 0, -1):
                t = stack[k].tag
                if t in closes:
                    del stack[k:]
                    break
                if t in ("ul", "ol", "table", "div", "body", "dl", "select"):
                    break
        if tag in BLOCKS_CLOSE_P and any(s.tag == "p" for s in stack):
            close("p")
        parent = current()
        node = Node(tag, attrs, parent)
        parent.children.append(node)
        if tag in RAW:
            if lower is None:
                lower = text.lower()
            j = lower.find(b"</" + tag.encode(), i)
            if j < 0:
                j = n
            raw = _dec(text[i:j])
            node.children.append(Node(None, None, node, raw if tag in ("script", "style") else unescape(raw)))
            k = text.find(b">", j)
            i = n if k < 0 else k + 1
            continue
        if tag not in VOID and not inside.endswith(b"/"):
            stack.append(node)
    return root
