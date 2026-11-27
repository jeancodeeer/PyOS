# JavaScript regular expressions in Python: a backtracking matcher.
# MicroPython's re has no lookaround, counted repetition, backreferences or
# named groups, so JavaScript's syntax gets its own engine here.
#
#   rx = compile(pattern, flags)       raises RegexError
#   m = rx.exec(s, start)               (start, end, [s1, e1, s2, e2, ...]) or None


try:
    RecursionError
except NameError:                   # MicroPython
    RecursionError = RuntimeError

class RegexError(ValueError):
    pass


_DIGITS = "0123456789"
_WORD = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
_SPACE = " \t\n\r\x0b\x0c\xa0﻿            " \
         "    　"
_LINE = "\n\r  "


# ---- the pattern as a tree ----
# nodes: ("char", c) ("str", text) ("any",) ("class", items, negated) ("bol",) ("eol",) ("wordb", neg)
#        ("group", index or None, node) ("alt", [nodes]) ("seq", [nodes]) ("rep", node, min, max, greedy)
#        ("look", ahead, neg, node) ("backref", index or name) ("empty",)

class _Parser:
    def __init__(self, src, flags):
        self.s = src
        self.i = 0
        self.n = len(src)
        self.ngroups = 0
        self.names = {}
        self.unicode = "u" in flags or "v" in flags
        self.backref_names = []

    def error(self, msg):
        raise RegexError("Invalid regular expression: /%s/: %s" % (self.s, msg))

    def peek(self):
        return self.s[self.i] if self.i < self.n else ""

    def parse(self):
        node = self.alternation()
        if self.i < self.n:
            self.error("Unmatched ')'")
        return node

    def alternation(self):
        alts = [self.sequence()]
        while self.peek() == "|":
            self.i += 1
            alts.append(self.sequence())
        return alts[0] if len(alts) == 1 else ("alt", alts)

    def sequence(self):
        items = []
        while self.i < self.n and self.s[self.i] not in "|)":
            atom = self.atom()
            if atom is None:
                continue
            atom = self.quantifier(atom)
            items.append(atom)
        # join runs of plain characters
        out = []
        for it in items:
            if it[0] == "char" and out and out[-1][0] in ("char", "str"):
                prev = out.pop()
                out.append(("str", (prev[1]) + it[1]))
            else:
                out.append(it)
        if not out:
            return ("empty",)
        return out[0] if len(out) == 1 else ("seq", out)

    def quantifier(self, atom):
        c = self.peek()
        if c == "*":
            lo, hi = 0, -1
        elif c == "+":
            lo, hi = 1, -1
        elif c == "?":
            lo, hi = 0, 1
        elif c == "{":
            j = self.s.find("}", self.i)
            body = self.s[self.i + 1:j] if j > 0 else ""
            parts = body.split(",")
            ok = j > 0 and 1 <= len(parts) <= 2 and parts[0].isdigit() and (len(parts) == 1 or parts[1] == "" or
                                                                             parts[1].isdigit())
            if not ok:
                if self.unicode:
                    self.error("Incomplete quantifier")
                return atom                      # a literal {
            lo = int(parts[0])
            hi = lo if len(parts) == 1 else (-1 if parts[1] == "" else int(parts[1]))
            if hi != -1 and hi < lo:
                self.error("numbers out of order in {} quantifier")
            self.i = j
        else:
            return atom
        self.i += 1
        greedy = True
        if self.peek() == "?":
            greedy = False
            self.i += 1
        if atom[0] in ("bol", "eol", "wordb") or (atom[0] == "look" and self.unicode):
            self.error("Nothing to repeat")
        if atom[0] == "str":                     # only the last character repeats
            return ("seq", [("str", atom[1][:-1]), ("rep", ("char", atom[1][-1]), lo, hi, greedy)])
        return ("rep", atom, lo, hi, greedy)

    def atom(self):
        s = self.s
        c = s[self.i]
        self.i += 1
        if c == ".":
            return ("any",)
        if c == "^":
            return ("bol",)
        if c == "$":
            return ("eol",)
        if c == "(":
            return self.group()
        if c == "[":
            return self.char_class()
        if c == "\\":
            return self.escape(False)
        if c in "*+?":
            self.error("Nothing to repeat")
        if c == ")":
            self.error("Unmatched ')'")
        if c == "{" and self.unicode:
            self.error("Lone quantifier brackets")
        if c == "\ud83d" and False:
            pass
        return ("char", c)

    def group(self):
        s = self.s
        if s.startswith("?:", self.i):
            self.i += 2
            node = self.alternation()
            self.close()
            return ("group", None, node)
        if s.startswith("?=", self.i) or s.startswith("?!", self.i):
            neg = s[self.i + 1] == "!"
            self.i += 2
            node = self.alternation()
            self.close()
            return ("look", True, neg, node)
        if s.startswith("?<=", self.i) or s.startswith("?<!", self.i):
            neg = s[self.i + 2] == "!"
            self.i += 3
            node = self.alternation()
            self.close()
            return ("look", False, neg, node)
        name = None
        if s.startswith("?<", self.i):
            j = s.find(">", self.i)
            if j < 0:
                self.error("Invalid capture group name")
            name = s[self.i + 2:j]
            self.i = j + 1
        elif self.peek() == "?":
            # (?i:...) modifiers: not supported; treat as a non-capturing group
            j = self.i + 1
            while j < self.n and s[j] in "imsx-":
                j += 1
            if j < self.n and s[j] == ":":
                self.i = j + 1
                node = self.alternation()
                self.close()
                return ("group", None, node)
            self.error("Invalid group")
        self.ngroups += 1
        idx = self.ngroups
        if name is not None:
            if name in self.names:
                self.error("Duplicate capture group name")
            self.names[name] = idx
        node = self.alternation()
        self.close()
        return ("group", idx, node)

    def close(self):
        if self.peek() != ")":
            self.error("Unterminated group")
        self.i += 1

    def class_escape_items(self, c):
        """\\d \\w \\s and the negated ones as class items."""
        if c == "d":
            return [("set", _DIGITS)]
        if c == "D":
            return [("nset", _DIGITS)]
        if c == "w":
            return [("set", _WORD)]
        if c == "W":
            return [("nset", _WORD)]
        if c == "s":
            return [("set", _SPACE)]
        if c == "S":
            return [("nset", _SPACE)]
        return None

    def escape(self, in_class):
        s = self.s
        if self.i >= self.n:
            self.error("\\ at end of pattern")
        c = s[self.i]
        self.i += 1
        items = self.class_escape_items(c)
        if items is not None:
            return ("class", items, False) if not in_class else items
        if not in_class:
            if c == "b":
                return ("wordb", False)
            if c == "B":
                return ("wordb", True)
            if c in "123456789":
                j = self.i
                while j < self.n and s[j].isdigit():
                    j += 1
                num = int(s[self.i - 1:j])
                self.i = j
                return ("backref", num)
            if c == "k" and self.peek() == "<":
                j = s.find(">", self.i)
                if j < 0:
                    self.error("Invalid named reference")
                name = s[self.i + 1:j]
                self.i = j + 1
                return ("backref", name)
        if c in "pP" and self.unicode and self.peek() == "{":
            j = s.find("}", self.i)
            prop = s[self.i + 1:j]
            self.i = j + 1
            item = ("prop", prop, c == "P")
            return [item] if in_class else ("class", [item], False)
        ch = self.char_escape(c, in_class)
        return ch if in_class else ("char", ch)

    def char_escape(self, c, in_class):
        s = self.s
        if c == "n":
            return "\n"
        if c == "r":
            return "\r"
        if c == "t":
            return "\t"
        if c == "v":
            return "\x0b"
        if c == "f":
            return "\x0c"
        if c == "b" and in_class:
            return "\b"
        if c == "0" and not (self.peek().isdigit()):
            return "\0"
        if c in "01234567" and not self.unicode:
            j = self.i
            while j < self.n and j < self.i + 2 and s[j] in "01234567":
                j += 1
            v = int(s[self.i - 1:j], 8)
            self.i = j
            return chr(v)
        if c == "x":
            h = s[self.i:self.i + 2]
            if len(h) == 2 and all(x in "0123456789abcdefABCDEF" for x in h):
                self.i += 2
                return chr(int(h, 16))
            return "x"
        if c == "u":
            if self.peek() == "{" and self.unicode:
                j = s.find("}", self.i)
                cp = int(s[self.i + 1:j], 16)
                self.i = j + 1
                return chr(cp)
            h = s[self.i:self.i + 4]
            if len(h) == 4 and all(x in "0123456789abcdefABCDEF" for x in h):
                self.i += 4
                cp = int(h, 16)
                if 0xD800 <= cp < 0xDC00 and s.startswith("\\u", self.i):
                    h2 = s[self.i + 2:self.i + 6]
                    if len(h2) == 4 and all(x in "0123456789abcdefABCDEF" for x in h2):
                        lo = int(h2, 16)
                        if 0xDC00 <= lo < 0xE000:
                            self.i += 6
                            return chr(0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00))
                try:
                    return chr(cp)
                except ValueError:
                    return "�"
            return "u"
        if c == "c":
            x = self.peek()
            if x and ("a" <= x.lower() <= "z"):
                self.i += 1
                return chr(ord(x) % 32)
            return "\\"
        return c

    def char_class(self):
        s = self.s
        neg = False
        if self.peek() == "^":
            neg = True
            self.i += 1
        items = []
        first = True
        while True:
            if self.i >= self.n:
                self.error("Unterminated character class")
            c = s[self.i]
            if c == "]" and not (first and False):
                self.i += 1
                break
            first = False
            lo = self.class_atom()
            if isinstance(lo, list):
                items.extend(lo)
                continue
            if self.peek() == "-" and self.i + 1 < self.n and s[self.i + 1] != "]":
                self.i += 1
                hi = self.class_atom()
                if isinstance(hi, list):
                    items.append(("set", lo))
                    items.append(("set", "-"))
                    items.extend(hi)
                    continue
                if ord(hi) < ord(lo):
                    self.error("Range out of order in character class")
                items.append(("range", lo, hi))
            else:
                items.append(("set", lo))
        return ("class", items, neg)

    def class_atom(self):
        c = self.s[self.i]
        self.i += 1
        if c == "\\":
            return self.escape(True)
        return c


# ---- matching ----

class _St:
    __slots__ = ("s", "n", "caps", "steps")


class _Chars:
    """A string as a list of characters: [i] in O(1) (MicroPython walks UTF-8 for str[i])."""
    __slots__ = ("c",)

    def __init__(self, s):
        self.c = list(s)

    def __getitem__(self, k):
        if type(k) is int:
            return self.c[k]
        return "".join(self.c[k])

    def __len__(self):
        return len(self.c)

    def startswith(self, p, i=0):
        n = len(p)
        return "".join(self.c[i:i + n]) == p


class _Bytes:
    __slots__ = ("b",)

    def __init__(self, s):
        self.b = s.encode()

    def __getitem__(self, k):
        if type(k) is int:
            return chr(self.b[k])
        return self.b[k].decode()

    def __len__(self):
        return len(self.b)

    def startswith(self, p, i=0):
        return self.b.startswith(p.encode(), i)


_LAST = [None, None]


def _fast(s):
    """A view of s with O(1) indexing (kept for the next call on the same string)."""
    if len(s) < 64:
        return s
    if _LAST[0] is s:
        return _LAST[1]
    v = _Bytes(s) if len(s.encode()) == len(s) else _Chars(s)
    _LAST[0] = s
    _LAST[1] = v
    return v


def _is_word(s, i):
    return 0 <= i < len(s) and s[i] in _WORD


def _prop_test(prop, ch):
    p = prop.split("=")[-1]
    if p in ("L", "Letter", "Alphabetic", "Alpha"):
        return ch.isalpha()
    if p in ("Lu", "Uppercase_Letter", "Uppercase"):
        return ch.isupper()
    if p in ("Ll", "Lowercase_Letter", "Lowercase"):
        return ch.islower()
    if p in ("N", "Nd", "Number", "Decimal_Number", "digit"):
        return ch.isdigit()
    if p in ("White_Space", "space"):
        return ch in _SPACE
    if p in ("P", "Punctuation"):
        return not ch.isalpha() and not ch.isdigit() and not ch.isspace() and ord(ch) < 0x3000 and \
            ch in "!\"#%&'()*,-./:;?@[\\]_{}¡§«¶·»¿"
    if p in ("Emoji", "Extended_Pictographic", "Emoji_Presentation"):
        return ord(ch) >= 0x1F000 or 0x2600 <= ord(ch) <= 0x27BF
    if p in ("Script=Latin", "Latin"):
        return ch.isalpha() and ord(ch) < 0x250
    return False


def _class_test(items, neg, icase):
    singles = []
    ranges = []
    others = []
    for it in items:
        if it[0] == "set":
            singles.append(it[1])
        elif it[0] == "range":
            ranges.append((it[1], it[2]))
        else:
            others.append(it)
    chars = "".join(singles)
    if icase:
        chars = chars + chars.lower() + chars.upper()

    def test(ch):
        r = ch in chars
        if not r:
            for lo, hi in ranges:
                if lo <= ch <= hi or icase and (lo <= ch.lower() <= hi or lo <= ch.upper() <= hi):
                    r = True
                    break
        if not r:
            for it in others:
                if it[0] == "nset":
                    if ch not in it[1]:
                        r = True
                        break
                elif it[0] == "prop":
                    if _prop_test(it[1], ch) != it[2]:
                        r = True
                        break
        return r != neg
    return test


class Regex:
    def __init__(self, pattern, flags):
        for f in flags:
            if f not in "gimsuyd" and f != "v":
                raise RegexError("Invalid regular expression flags '%s'" % flags)
        if len(set(flags)) != len(flags):
            raise RegexError("Invalid regular expression flags '%s'" % flags)
        self.pattern = pattern
        self.flags = flags
        self.icase = "i" in flags
        self.multiline = "m" in flags
        self.dotall = "s" in flags
        p = _Parser(pattern, flags)
        tree = p.parse()
        self.ngroups = p.ngroups
        self.names = p.names
        self.matcher = self.comp(tree)
        # a literal start lets the search jump (no flags that change letters)
        self.prefix = None
        t = tree
        if t[0] == "seq":
            t = t[1][0]
        if t[0] in ("str", "char") and not self.icase:
            self.prefix = t[1]
        self.literal = tree[1] if tree[0] in ("str", "char") and not self.icase else None
        self.anchored = tree[0] == "bol" or (tree[0] == "seq" and tree[1][0][0] == "bol") and not self.multiline

    # a matcher: f(st, i, k) -> bool, where k(st, j) -> bool goes on from j
    def comp(self, node):
        kind = node[0]
        icase = self.icase
        if kind == "char" or kind == "str":
            text = node[1]
            n = len(text)
            if icase:
                low = text.lower()

                def m(st, i, k):
                    if st.s[i:i + n].lower() == low:
                        return k(st, i + n)
                    return False
            else:
                def m(st, i, k):
                    if st.s.startswith(text, i):
                        return k(st, i + n)
                    return False
            return m
        if kind == "empty":
            return lambda st, i, k: k(st, i)
        if kind in ("any", "class"):
            test = self.single_test(node)

            def m(st, i, k):
                if i < st.n and test(st.s[i]):
                    return k(st, i + 1)
                return False
            return m
        if kind == "bol":
            if self.multiline:
                return lambda st, i, k: (i == 0 or st.s[i - 1] in _LINE) and k(st, i)
            return lambda st, i, k: i == 0 and k(st, i)
        if kind == "eol":
            if self.multiline:
                return lambda st, i, k: (i == st.n or st.s[i] in _LINE) and k(st, i)
            return lambda st, i, k: i == st.n and k(st, i)
        if kind == "wordb":
            neg = node[1]

            def m(st, i, k):
                b = _is_word(st.s, i - 1) != _is_word(st.s, i)
                return b != neg and k(st, i)
            return m
        if kind == "seq":
            ms = [self.comp(x) for x in node[1]]
            return _seq(ms)
        if kind == "alt":
            ms = [self.comp(x) for x in node[1]]

            def m(st, i, k):
                for f in ms:
                    if f(st, i, k):
                        return True
                return False
            return m
        if kind == "group":
            inner = self.comp(node[2])
            idx = node[1]
            if idx is None:
                return inner
            a = 2 * idx
            b = a + 1

            def m(st, i, k):
                caps = st.caps
                old_a, old_b = caps[a], caps[b]

                def close(st2, j):
                    ca, cb = caps[a], caps[b]
                    caps[a] = i
                    caps[b] = j
                    if k(st2, j):
                        return True
                    caps[a], caps[b] = ca, cb
                    return False
                if inner(st, i, close):
                    return True
                caps[a], caps[b] = old_a, old_b
                return False
            return m
        if kind == "rep":
            return self.comp_rep(node)
        if kind == "look":
            ahead, neg, sub = node[1], node[2], node[3]
            inner = self.comp(sub)
            if ahead:
                def m(st, i, k):
                    saved = list(st.caps)
                    ok = inner(st, i, lambda st2, j: True)
                    if neg:
                        st.caps[:] = saved
                        return (not ok) and k(st, i)
                    if not ok:
                        return False
                    if k(st, i):
                        return True
                    st.caps[:] = saved
                    return False
                return m

            def m(st, i, k):
                saved = list(st.caps)
                ok = False
                for j in range(i, -1, -1):
                    if inner(st, j, lambda st2, e: e == i):
                        ok = True
                        break
                if neg:
                    st.caps[:] = saved
                    return (not ok) and k(st, i)
                if not ok:
                    return False
                if k(st, i):
                    return True
                st.caps[:] = saved
                return False
            return m
        if kind == "backref":
            ref = node[1]
            regex = self

            def m(st, i, k):
                idx = regex.names.get(ref) if type(ref) is str else ref
                if idx is None or idx > regex.ngroups:
                    return k(st, i)
                a = st.caps[2 * idx]
                b = st.caps[2 * idx + 1]
                if a < 0 or b < 0:
                    return k(st, i)
                sub = st.s[a:b]
                n = len(sub)
                part = st.s[i:i + n]
                if part == sub or (icase and part.lower() == sub.lower()):
                    return k(st, i + n)
                return False
            return m
        raise RegexError("bad node %r" % (kind,))

    def single_test(self, node):
        if node[0] == "any":
            if self.dotall:
                return lambda ch: True
            return lambda ch: ch not in _LINE
        if node[0] == "char":
            c = node[1]
            if self.icase:
                lc = c.lower()
                return lambda ch: ch == c or ch.lower() == lc
            return lambda ch: ch == c
        return _class_test(node[1], node[2], self.icase)

    def comp_rep(self, node):
        sub, lo, hi, greedy = node[1], node[2], node[3], node[4]
        if sub[0] in ("any", "class", "char"):
            test = self.single_test(sub)

            def m(st, i, k):
                s = st.s
                n = st.n
                limit = n if hi < 0 else min(n, i + hi)
                if greedy:
                    j = i
                    while j < limit and test(s[j]):
                        j += 1
                    if j - i < lo:
                        return False
                    stop = i + lo
                    while j >= stop:
                        if k(st, j):
                            return True
                        j -= 1
                    return False
                j = i
                while j < i + lo:
                    if j >= n or not test(s[j]):
                        return False
                    j += 1
                while True:
                    if k(st, j):
                        return True
                    if j >= limit or not test(s[j]):
                        return False
                    j += 1
            return m
        body = self.comp(sub)
        groups = []
        _group_indexes(sub, groups)

        def m(st, i, k):
            def rep(st2, j, count):
                if count < lo:
                    return body(st2, j, lambda st3, e: rep(st3, e, count + 1))
                if hi >= 0 and count >= hi:
                    return k(st2, j)
                if greedy:
                    saved = [st2.caps[x] for x in groups]
                    if body(st2, j, lambda st3, e: e != j and rep(st3, e, count + 1)):
                        return True
                    for x in range(len(groups)):
                        st2.caps[groups[x]] = saved[x]
                    return k(st2, j)
                if k(st2, j):
                    return True
                return body(st2, j, lambda st3, e: e != j and rep(st3, e, count + 1))
            return rep(st, i, 0)
        return m

    def exec(self, s, start=0, sticky=False):
        n = len(s)
        if start > n:
            return None
        if self.literal is not None and not sticky:
            fs = _fast(s)
            j = fs.b.find(self.literal.encode(), start) if type(fs) is _Bytes else s.find(self.literal, start)
            if j < 0:
                return None
            return (j, j + len(self.literal), [-1, -1] * self.ngroups)
        st = _St()
        fs = _fast(s)
        st.s = fs
        st.n = n
        find = fs.b.find if type(fs) is _Bytes else None
        found = [0]

        def done(st2, j):
            found[0] = j
            return True
        nc = 2 * (self.ngroups + 1)
        i = start
        m = self.matcher
        prefix = self.prefix
        while i <= n:
            if prefix is not None and not sticky:
                i = find(prefix.encode(), i) if find is not None else s.find(prefix, i)
                if i < 0:
                    return None
            st.caps = [-1] * nc
            try:
                ok = m(st, i, done)
            except RecursionError:
                ok = False
            if ok:
                return (i, found[0], st.caps[2:])
            if sticky or self.anchored:
                return None
            i += 1
        return None


def _seq(ms):
    if len(ms) == 1:
        return ms[0]
    if len(ms) == 2:
        a, b = ms

        def m2(st, i, k):
            return a(st, i, lambda st2, j: b(st2, j, k))
        return m2
    head = ms[0]
    tail = _seq(ms[1:])

    def m(st, i, k):
        return head(st, i, lambda st2, j: tail(st2, j, k))
    return m


def _group_indexes(node, out):
    if type(node) is not tuple:
        return
    if node[0] == "group" and node[1] is not None:
        out.append(2 * node[1])
        out.append(2 * node[1] + 1)
    for x in node[1:]:
        if type(x) is tuple:
            _group_indexes(x, out)
        elif type(x) is list:
            for y in x:
                _group_indexes(y, out)


_CACHE = {}


def compile(pattern, flags=""):
    key = (pattern, flags)
    r = _CACHE.get(key)
    if r is None:
        r = Regex(pattern, flags)
        if len(_CACHE) > 500:
            _CACHE.clear()
        _CACHE[key] = r
    return r
