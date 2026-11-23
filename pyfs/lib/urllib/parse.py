# URL parsing (the parts of CPython's urllib.parse that programs use most).


class SplitResult:
    def __init__(self, scheme, netloc, path, query, fragment):
        self.scheme, self.netloc, self.path, self.query, self.fragment = scheme, netloc, path, query, fragment
        host = netloc.rsplit("@", 1)[-1]
        if host.startswith("["):
            self.hostname, _, rest = host[1:].partition("]")
            port = rest[1:] if rest.startswith(":") else ""
        else:
            self.hostname, _, port = host.partition(":")
        self.hostname = self.hostname.lower() or None
        self.port = int(port) if port.isdigit() else None

    def geturl(self):
        return urlunsplit(self)

    def __iter__(self):
        return iter((self.scheme, self.netloc, self.path, self.query, self.fragment))

    def __repr__(self):
        return "SplitResult(scheme=%r, netloc=%r, path=%r, query=%r, fragment=%r)" % tuple(self)


def urlsplit(url, scheme=""):
    fragment = query = ""
    if "#" in url:
        url, fragment = url.split("#", 1)
    if "?" in url:
        url, query = url.split("?", 1)
    i = url.find(":")
    if i > 0 and url[:i].replace("+", "").replace("-", "").replace(".", "").isalpha() and url[i + 1:i + 3] == "//" or \
            (i > 0 and url[:i].lower() in ("http", "https", "file", "ftp", "about", "data", "mailto")):
        scheme, url = url[:i].lower(), url[i + 1:]
    netloc = ""
    if url.startswith("//"):
        rest = url[2:]
        j = rest.find("/")
        netloc, url = (rest, "") if j < 0 else (rest[:j], rest[j:])
    return SplitResult(scheme, netloc, url, query, fragment)


urlparse = urlsplit


def urlunsplit(parts):
    scheme, netloc, path, query, fragment = tuple(parts)
    url = path
    if netloc:
        url = "//" + netloc + (url if not url or url.startswith("/") else "/" + url)
    if scheme:
        url = scheme + ":" + url
    if query:
        url += "?" + query
    if fragment:
        url += "#" + fragment
    return url


def _normpath(path):
    out = []
    for seg in path.split("/"):
        if seg == "..":
            if len(out) > 1:
                out.pop()
        elif seg != ".":
            out.append(seg)
    res = "/".join(out)
    if path.endswith(("/.", "/..")):
        res += "/"
    return res


def urljoin(base, url):
    if not base:
        return url
    if not url:
        return base
    u = urlsplit(url)
    if u.scheme and u.scheme not in ("http", "https", "file"):
        return url
    b = urlsplit(base)
    if u.scheme:
        return urlunsplit((u.scheme, u.netloc, _normpath(u.path or "/"), u.query, u.fragment))
    if url.startswith("//"):
        return b.scheme + ":" + url
    if u.netloc:
        return urlunsplit((b.scheme, u.netloc, u.path, u.query, u.fragment))
    if not u.path:
        return urlunsplit((b.scheme, b.netloc, b.path, u.query or b.query, u.fragment))
    if u.path.startswith("/"):
        path = u.path
    else:
        path = b.path[:b.path.rfind("/") + 1] + u.path if "/" in b.path else "/" + u.path
    return urlunsplit((b.scheme, b.netloc, _normpath(path), u.query, u.fragment))


_SAFE = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-~")


def quote(s, safe="/"):
    if isinstance(s, str):
        s = s.encode()
    ok = _SAFE | set(safe.encode())
    return "".join(chr(b) if b in ok else "%%%02X" % b for b in s)


def quote_plus(s, safe=""):
    return quote(s, safe + " ").replace(" ", "+")


def unquote(s):
    out, i = bytearray(), 0
    b = s.encode()
    while i < len(b):
        if b[i] == 0x25 and i + 3 <= len(b):
            try:
                out.append(int(b[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out.append(b[i])
        i += 1
    return out.decode("utf-8")


def unquote_plus(s):
    return unquote(s.replace("+", " "))


def urlencode(query, doseq=False):
    items = query.items() if hasattr(query, "items") else query
    return "&".join(quote_plus(str(k)) + "=" + quote_plus(str(v)) for k, v in items)


def parse_qsl(qs):
    out = []
    for part in qs.split("&"):
        if part:
            k, _, v = part.partition("=")
            out.append((unquote_plus(k), unquote_plus(v)))
    return out


def parse_qs(qs):
    d = {}
    for k, v in parse_qsl(qs):
        d.setdefault(k, []).append(v)
    return d
