# HTTP/1.1 client, on the kernel's own sockets and TLS (CPython-like API).
#
#   c = http.client.HTTPSConnection("example.com")
#   c.request("GET", "/")
#   r = c.getresponse(); r.status, r.read()
import io
import socket

HTTP_PORT, HTTPS_PORT = 80, 443
USER_AGENT = "PyKernel/0.2 (Python; bare metal)"


class HTTPException(Exception):
    pass


class HTTPMessage:
    """Response headers: case-insensitive lookup, repeated names kept."""

    def __init__(self, items):
        self._items = items

    def get(self, name, default=None):
        name = name.lower()
        for k, v in self._items:
            if k.lower() == name:
                return v
        return default

    def get_all(self, name):
        name = name.lower()
        return [v for k, v in self._items if k.lower() == name]

    def items(self):
        return list(self._items)

    def keys(self):
        return [k for k, _ in self._items]

    def __getitem__(self, name):
        return self.get(name)

    def __contains__(self, name):
        return self.get(name) is not None

    def __iter__(self):
        return iter(self.keys())


class HTTPResponse:
    def __init__(self, sock, method):
        self.fp = sock.makefile("rb")
        self.method = method
        line = self.fp.readline().decode("latin-1").rstrip("\r\n")
        if not line:
            raise HTTPException("server closed the connection without a response")
        parts = line.split(" ", 2)
        self.version = 11 if parts[0] == "HTTP/1.1" else 10
        self.status = int(parts[1])
        self.reason = parts[2] if len(parts) > 2 else ""
        items = []
        while True:
            h = self.fp.readline().decode("latin-1").rstrip("\r\n")
            if not h:
                break
            if ":" in h:
                k, v = h.split(":", 1)
                items.append((k.strip(), v.strip()))
        self.headers = self.msg = HTTPMessage(items)
        self.chunked = (self.headers.get("transfer-encoding") or "").lower() == "chunked"
        length = self.headers.get("content-length")
        self.length = int(length) if length is not None and not self.chunked else None
        if method == "HEAD" or self.status in (204, 304) or 100 <= self.status < 200:
            self.length = 0
        self._body = None
        self.closed = False

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def getheaders(self):
        return self.headers.items()

    def _read_raw(self):
        if self.chunked:
            out = bytearray()
            while True:
                size = int(self.fp.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.fp.readline().strip():
                        pass
                    break
                out += self.fp.read(size)
                self.fp.readline()
            return bytes(out)
        if self.length is not None:
            return self.fp.read(self.length)
        return self.fp.read()

    def read(self, amt=None):
        if self._body is None:
            body = self._read_raw()
            enc = (self.headers.get("content-encoding") or "").lower()
            if enc in ("gzip", "deflate"):
                import deflate
                fmt = deflate.GZIP if enc == "gzip" else deflate.AUTO
                body = deflate.DeflateIO(io.BytesIO(body), fmt).read()
            self._body = io.BytesIO(body)
        return self._body.read() if amt is None else self._body.read(amt)

    def readline(self):
        self.read(0)
        return self._body.readline()

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class HTTPConnection:
    default_port = HTTP_PORT

    def __init__(self, host, port=None, timeout=30):
        if port is None and ":" in host:
            host, port = host.rsplit(":", 1)
        self.host, self.port = host, int(port or self.default_port)
        self.timeout = timeout
        self.sock = None

    def connect(self):
        self.sock = socket.socket()
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))

    def request(self, method, url, body=None, headers=None):
        if self.sock is None:
            self.connect()
        headers = dict(headers or {})
        lower = {k.lower() for k in headers}
        host = self.host if self.port == self.default_port else "%s:%d" % (self.host, self.port)
        lines = ["%s %s HTTP/1.1" % (method, url or "/")]
        if "host" not in lower:
            lines.append("Host: " + host)
        if "user-agent" not in lower:
            lines.append("User-Agent: " + USER_AGENT)
        if "accept-encoding" not in lower:
            lines.append("Accept-Encoding: gzip")
        if "connection" not in lower:
            lines.append("Connection: close")
        if isinstance(body, str):
            body = body.encode()
        if body is not None and "content-length" not in lower:
            lines.append("Content-Length: %d" % len(body))
        for k, v in headers.items():
            lines.append("%s: %s" % (k, v))
        data = ("\r\n".join(lines) + "\r\n\r\n").encode()
        self.sock.sendall(data + (body or b""))
        self._method = method

    def getresponse(self):
        return HTTPResponse(self.sock, self._method)

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None


class HTTPSConnection(HTTPConnection):
    default_port = HTTPS_PORT

    def __init__(self, host, port=None, timeout=30, context=None):
        HTTPConnection.__init__(self, host, port, timeout)
        self.context = context

    def connect(self):
        import ssl
        ctx = self.context or ssl.create_default_context()
        raw = socket.socket()
        raw.settimeout(self.timeout)
        self.sock = ctx.wrap_socket(raw, server_hostname=self.host)
        self.sock.connect((self.host, self.port))


responses = {200: "OK", 201: "Created", 204: "No Content", 301: "Moved Permanently", 302: "Found",
             304: "Not Modified", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
             404: "Not Found", 405: "Method Not Allowed", 500: "Internal Server Error"}
