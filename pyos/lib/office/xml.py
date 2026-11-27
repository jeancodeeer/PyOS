# A very small XML reader and the escaping helpers, enough for the XML
# inside Office files (MicroPython has no xml module).
#
#   for kind, name, attrs, text in xml.events(b"<a x='1'>hi</a>"):
#       ("start", "a", {"x": "1"}, None), ("text", None, None, "hi"), ("end", "a", None, None)
#
# Names keep their prefix ("w:p", "a:t"): Office always uses the same ones.

ENTITIES = {"lt": "<", "gt": ">", "amp": "&", "quot": '"', "apos": "'"}


def escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def unescape(text):
    if "&" not in text:
        return text
    out, i = [], 0
    while i < len(text):
        j = text.find("&", i)
        k = text.find(";", j) if j >= 0 else -1
        if j < 0 or k < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        name = text[j + 1:k]
        if name.startswith("#x"):
            out.append(chr(int(name[2:], 16)))
        elif name.startswith("#"):
            out.append(chr(int(name[1:])))
        else:
            out.append(ENTITIES.get(name, "&" + name + ";"))
        i = k + 1
    return "".join(out)


def _attrs(inside):
    """'a="1" b=\'2\'' -> {"a": "1", "b": "2"}"""
    out = {}
    i, n = 0, len(inside)
    while i < n:
        while i < n and inside[i] in " \t\r\n":
            i += 1
        eq = inside.find("=", i)
        if eq < 0:
            break
        name = inside[i:eq].strip()
        q = eq + 1
        while q < n and inside[q] in " \t\r\n":
            q += 1
        if q >= n:
            break
        quote = inside[q]
        end = inside.find(quote, q + 1)
        if end < 0:
            break
        out[name] = unescape(inside[q + 1:end])
        i = end + 1
    return out


def events(data):
    """Go through an XML document: ("start"|"end"|"text", name, attrs, text)."""
    text = data.decode() if isinstance(data, (bytes, bytearray)) else data
    i, n = 0, len(text)
    while i < n:
        lt = text.find("<", i)
        if lt < 0:
            break
        if lt > i:
            yield ("text", None, None, unescape(text[i:lt]))
        if text.startswith("<?", lt) or text.startswith("<!--", lt) or text.startswith("<!", lt):
            close = "?>" if text.startswith("<?", lt) else ("-->" if text.startswith("<!--", lt) else ">")
            gt = text.find(close, lt)
            i = (gt + len(close)) if gt >= 0 else n
            continue
        gt = text.find(">", lt)
        if gt < 0:
            break
        tag = text[lt + 1:gt]
        i = gt + 1
        if tag.startswith("/"):
            yield ("end", tag[1:].strip(), None, None)
            continue
        empty = tag.endswith("/")
        if empty:
            tag = tag[:-1]
        sp = 0
        while sp < len(tag) and tag[sp] not in " \t\r\n":
            sp += 1
        name = tag[:sp]
        yield ("start", name, _attrs(tag[sp:]), None)
        if empty:
            yield ("end", name, None, None)
