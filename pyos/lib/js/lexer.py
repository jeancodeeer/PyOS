# JavaScript tokens. The parser asks for them one at a time, and says when a
# regular expression may start (a '/' there is not a division), and when a
# template literal goes on after a '}'.
#
# A token: (kind, value, start, end, newline_before)
#   kind: "name" (identifiers and keywords), "priv" (#name), "num", "str",
#         "tmpl" (value: (cooked, raw, tail)), "regex" (value: (pattern, flags)), "p" (punctuation), "eof"

PUNCT = (">>>=", "...", "===", "!==", "**=", "<<=", ">>=", ">>>", "&&=", "||=", "??=",
         "=>", "==", "!=", "<=", ">=", "&&", "||", "??", "?.", "++", "--", "+=", "-=", "*=", "/=", "%=",
         "&=", "|=", "^=", "**", "<<", ">>",
         "{", "}", "(", ")", "[", "]", ";", ",", "<", ">", "+", "-", "*", "/", "%", "&", "|", "^", "!", "~",
         "?", ":", "=", ".", "@")
_BY_FIRST = {}
for _p in PUNCT:
    _BY_FIRST.setdefault(_p[0], []).append(_p)
for _k in _BY_FIRST:
    _BY_FIRST[_k].sort(key=lambda s: -len(s))

LINE_ENDS = "\n\r  "
SPACES = " \t\x0b\x0c\xa0﻿              　"


class JSSyntaxError(Exception):
    def __init__(self, msg, pos=0, src=None):
        Exception.__init__(self, msg)
        self.msg = msg
        self.pos = pos
        self.src = src

    def where(self):
        if self.src is None:
            return ""
        line = self.src.count("\n", 0, self.pos) + 1
        col = self.pos - (self.src.rfind("\n", 0, self.pos) + 1) + 1
        return "line %d, column %d" % (line, col)


def _id_start(c):
    return c.isalpha() or c == "$" or c == "_" or (c > "\x7f" and not c.isspace() and c not in "  ")


def _id_part(c):
    return c.isalpha() or c.isdigit() or c == "$" or c == "_" or c == "‌" or c == "‍" or \
        (c > "\x7f" and not c.isspace() and c not in "  ")


_HEX = "0123456789abcdefABCDEF"


class Lexer:
    def __init__(self, src):
        self.s = src
        self.n = len(src)
        self.i = 0

    def error(self, msg, pos=None):
        raise JSSyntaxError(msg, self.i if pos is None else pos, self.s)

    # ---- white space and comments; True if a line ended ----
    def skip(self):
        s = self.s
        n = self.n
        i = self.i
        nl = False
        while i < n:
            c = s[i]
            if c == " " or c == "\t":
                i += 1
            elif c == "\n" or c == "\r" or c == " " or c == " ":
                nl = True
                i += 1
            elif c == "/" and i + 1 < n:
                d = s[i + 1]
                if d == "/":
                    j = i + 2
                    while j < n and s[j] not in LINE_ENDS:
                        j += 1
                    i = j
                elif d == "*":
                    j = s.find("*/", i + 2)
                    if j < 0:
                        self.i = i
                        self.error("unterminated comment")
                    if not nl:
                        for k in range(i + 2, j):
                            if s[k] in LINE_ENDS:
                                nl = True
                                break
                    i = j + 2
                else:
                    break
            elif c in SPACES:
                i += 1
            elif c == "<" and s.startswith("<!--", i):          # HTML comments, of old scripts
                j = i
                while j < n and s[j] not in LINE_ENDS:
                    j += 1
                i = j
            elif c == "-" and nl and s.startswith("-->", i):
                j = i
                while j < n and s[j] not in LINE_ENDS:
                    j += 1
                i = j
            else:
                break
        self.i = i
        return nl

    def token(self, regex_ok):
        nl = self.skip()
        s = self.s
        i = self.i
        if i >= self.n:
            return ("eof", None, i, i, nl)
        c = s[i]
        if _id_start(c) or c == "\\":
            name, j = self._ident(i)
            self.i = j
            return ("name", name, i, j, nl)
        if c == "#" and i + 1 < self.n and (_id_start(s[i + 1]) or s[i + 1] == "\\"):
            name, j = self._ident(i + 1)
            self.i = j
            return ("priv", "#" + name, i, j, nl)
        if c.isdigit() or (c == "." and i + 1 < self.n and s[i + 1].isdigit()):
            v, j = self._number(i)
            self.i = j
            return ("num", v, i, j, nl)
        if c == '"' or c == "'":
            v, j = self._string(i)
            self.i = j
            return ("str", v, i, j, nl)
        if c == "`":
            v, j = self._template(i + 1)
            self.i = j
            return ("tmpl", v, i, j, nl)
        if c == "/" and regex_ok:
            v, j = self._regex(i)
            self.i = j
            return ("regex", v, i, j, nl)
        if c == "#" and i == 0 and s.startswith("#!"):          # a hashbang line
            j = i
            while j < self.n and s[j] not in LINE_ENDS:
                j += 1
            self.i = j
            return self.token(regex_ok)
        for p in _BY_FIRST.get(c, ()):
            if s.startswith(p, i):
                if p == "?." and i + 2 < self.n and s[i + 2].isdigit():
                    continue                                    # a ? .5 : b
                self.i = i + len(p)
                return ("p", p, i, i + len(p), nl)
        self.error("unexpected character %r" % c)

    def _ident(self, i):
        s = self.s
        n = self.n
        out = []
        j = i
        while j < n:
            c = s[j]
            if _id_part(c):
                k = j + 1
                while k < n and (s[k].isalpha() or s[k].isdigit() or s[k] == "_" or s[k] == "$"):
                    k += 1
                out.append(s[j:k])
                j = k
            elif c == "\\":
                if j + 1 >= n or s[j + 1] != "u":
                    self.error("bad escape in a name", j)
                cp, j = self._unicode_escape(j + 2)
                out.append(chr(cp))
            else:
                break
        return "".join(out), j

    def _unicode_escape(self, j):
        s = self.s
        if j < self.n and s[j] == "{":
            k = s.find("}", j)
            if k < 0:
                self.error("bad \\u{} escape", j)
            try:
                return int(s[j + 1:k], 16), k + 1
            except ValueError:
                self.error("bad \\u{} escape", j)
        h = s[j:j + 4]
        if len(h) < 4 or any(ch not in _HEX for ch in h):
            self.error("bad \\u escape", j)
        return int(h, 16), j + 4

    def _number(self, i):
        s = self.s
        n = self.n
        if s[i] == "0" and i + 1 < n and s[i + 1] in "xXoObB":
            base = {"x": 16, "o": 8, "b": 2}[s[i + 1].lower()]
            j = i + 2
            while j < n and (s[j] in _HEX or s[j] == "_"):
                j += 1
            digits = s[i + 2:j].replace("_", "")
            if j < n and s[j] == "n":
                j += 1
            try:
                return int(digits, base), j
            except ValueError:
                self.error("bad number", i)
        j = i
        while j < n and (s[j].isdigit() or s[j] == "_"):
            j += 1
        if s[i] == "0" and j - i > 1 and s[i:j].isdigit() and all(ch in "01234567" for ch in s[i:j]):
            return int(s[i:j], 8), j                            # legacy octal: 017
        is_float = False
        if j < n and s[j] == "n":
            return int(s[i:j].replace("_", "")), j + 1          # BigInt: as a number
        if j < n and s[j] == ".":
            is_float = True
            j += 1
            while j < n and (s[j].isdigit() or s[j] == "_"):
                j += 1
        if j < n and s[j] in "eE":
            k = j + 1
            if k < n and s[k] in "+-":
                k += 1
            if k < n and s[k].isdigit():
                is_float = True
                j = k
                while j < n and s[j].isdigit():
                    j += 1
        text = s[i:j].replace("_", "")
        if j < n and _id_start(s[j]):
            self.error("a name right after a number", j)
        if is_float:
            v = float(text)
            if -9007199254740992.0 < v < 9007199254740992.0 and v == int(v):
                return int(v), j
            return v, j
        v = int(text)
        return (v if v < 9007199254740992 else float(v)), j

    def _escape(self, j, template=False):
        """One escape after a backslash at j-1: (text, next index), or (None, next) when bad in a template."""
        s = self.s
        c = s[j]
        if c == "n":
            return "\n", j + 1
        if c == "t":
            return "\t", j + 1
        if c == "r":
            return "\r", j + 1
        if c == "b":
            return "\b", j + 1
        if c == "f":
            return "\f", j + 1
        if c == "v":
            return "\v", j + 1
        if c == "x":
            h = s[j + 1:j + 3]
            if len(h) < 2 or any(ch not in _HEX for ch in h):
                if template:
                    return None, j + 1
                self.error("bad \\x escape", j)
            return chr(int(h, 16)), j + 3
        if c == "u":
            try:
                cp, k = self._unicode_escape(j + 1)
            except JSSyntaxError:
                if template:
                    return None, j + 1
                raise
            if 0xD800 <= cp < 0xDC00 and s.startswith("\\u", k):        # a surrogate pair
                try:
                    lo, k2 = self._unicode_escape(k + 2)
                    if 0xDC00 <= lo < 0xE000:
                        return chr(0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)), k2
                except JSSyntaxError:
                    pass
            try:
                return chr(cp), k
            except ValueError:
                return "�", k
        if c == "\r":
            return "", j + 2 if s.startswith("\r\n", j) else j + 1
        if c in "\n  ":
            return "", j + 1
        if c in "01234567":
            if c == "0" and not (j + 1 < self.n and s[j + 1].isdigit()):
                return "\0", j + 1
            if template:
                return None, j + 1
            k = j
            while k < self.n and k < j + 3 and s[k] in "01234567":
                k += 1
            v = int(s[j:k], 8)
            if v > 255:
                k -= 1
                v = int(s[j:k], 8)
            return chr(v), k
        return c, j + 1

    def _string(self, i):
        s = self.s
        q = s[i]
        j = i + 1
        n = self.n
        out = []
        while True:
            k = j
            while k < n and s[k] != q and s[k] != "\\" and s[k] != "\n" and s[k] != "\r":
                k += 1
            out.append(s[j:k])
            if k >= n or s[k] in "\n\r":
                self.error("unterminated string", i)
            if s[k] == q:
                return "".join(out), k + 1
            t, j = self._escape(k + 1)
            out.append(t)

    def _template(self, j):
        """A template chunk from j to `${` or the closing backquote: ((cooked, raw, tail), next)."""
        s = self.s
        n = self.n
        out = []
        start = j
        bad = False
        while True:
            k = j
            while k < n and s[k] != "`" and s[k] != "\\" and s[k] != "$":
                k += 1
            out.append(s[j:k])
            if k >= n:
                self.error("unterminated template", start)
            c = s[k]
            if c == "`":
                raw = s[start:k].replace("\r\n", "\n").replace("\r", "\n")
                cooked = None if bad else "".join(out).replace("\r\n", "\n").replace("\r", "\n")
                return (cooked, raw, True), k + 1
            if c == "$":
                if k + 1 < n and s[k + 1] == "{":
                    raw = s[start:k].replace("\r\n", "\n").replace("\r", "\n")
                    cooked = None if bad else "".join(out).replace("\r\n", "\n").replace("\r", "\n")
                    return (cooked, raw, False), k + 2
                out.append("$")
                j = k + 1
                continue
            t, j = self._escape(k + 1, True)
            if t is None:
                bad = True
            else:
                out.append(t)

    def template_continue(self):
        """After the '}' of a ${...}: the next chunk of the template."""
        v, j = self._template(self.i)
        start = self.i
        self.i = j
        return ("tmpl", v, start, j, False)

    def _regex(self, i):
        s = self.s
        n = self.n
        j = i + 1
        in_class = False
        while True:
            if j >= n or s[j] in LINE_ENDS:
                self.error("unterminated regular expression", i)
            c = s[j]
            if c == "\\":
                j += 2
                continue
            if c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                break
            j += 1
        pattern = s[i + 1:j]
        j += 1
        k = j
        while k < n and _id_part(s[k]):
            k += 1
        return (pattern, s[j:k]), k
