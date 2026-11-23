# urllib.request.urlopen on top of http.client: follows redirects.
from http import client
from urllib.parse import urlsplit, urljoin


class URLError(OSError):
    pass


class HTTPError(URLError):
    def __init__(self, url, code, msg, hdrs, fp):
        super().__init__("HTTP Error %d: %s" % (code, msg))
        self.url, self.code, self.status, self.reason, self.headers, self.fp = url, code, code, msg, hdrs, fp

    def read(self):
        return self.fp.read() if self.fp else b""


class Request:
    def __init__(self, url, data=None, headers=None, method=None):
        self.full_url = url
        self.data = data
        self.headers = dict(headers or {})
        self.method = method or ("POST" if data is not None else "GET")

    def add_header(self, k, v):
        self.headers[k] = v

    def get_method(self):
        return self.method


def urlopen(url, data=None, timeout=30, context=None, max_redirects=8):
    req = url if isinstance(url, Request) else Request(url, data)
    target, method, body = req.full_url, req.method, req.data
    for _ in range(max_redirects + 1):
        u = urlsplit(target)
        if u.scheme == "https":
            conn = client.HTTPSConnection(u.hostname, u.port, timeout, context)
        elif u.scheme == "http":
            conn = client.HTTPConnection(u.hostname, u.port, timeout)
        elif u.scheme == "file":
            import io
            with open(u.path, "rb") as f:
                return io.BytesIO(f.read())
        else:
            raise URLError("unknown url type: %s" % u.scheme)
        path = (u.path or "/") + ("?" + u.query if u.query else "")
        try:
            conn.request(method, path, body, req.headers)
            r = conn.getresponse()
        except OSError as e:
            conn.close()
            raise URLError(str(e))
        r.url = target
        if r.status in (301, 302, 303, 307, 308) and r.getheader("location"):
            target = urljoin(target, r.getheader("location"))
            if r.status == 303 or (r.status in (301, 302) and method == "POST"):
                method, body = "GET", None
            conn.close()
            continue
        if r.status >= 400:
            r.read()
            r._body.seek(0)
            conn.close()
            raise HTTPError(target, r.status, r.reason, r.headers, r._body)
        r.read(0)                  # whole body in memory: the socket can go
        conn.close()
        r.geturl = lambda t=target: t
        return r
    raise URLError("too many redirects")
