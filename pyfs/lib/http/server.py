# A small HTTP server: serve a folder, or answer with your own function.
#
#   from http import server
#   server.serve('/disk/www', 80)            # in the background
#   server.serve(handler=lambda req: (200, 'text/plain', b'hola'))
import os
import socket
from kernel import thread

TYPES = {"html": "text/html", "htm": "text/html", "txt": "text/plain", "css": "text/css", "js": "text/javascript",
         "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "bmp": "image/bmp",
         "json": "application/json", "py": "text/plain", "svg": "image/svg+xml"}
servers = []


class Request:
    def __init__(self, method, path, headers, body, peer):
        self.method, self.path, self.headers, self.body, self.peer = method, path, headers, body, peer


def _read_request(conn):
    data = b""
    while b"\r\n\r\n" not in data and len(data) < 65536:
        chunk = conn.recv(4096)
        if not chunk:
            return None
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    parts = lines[0].split()
    if len(parts) < 2:
        return None
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    want = int(headers.get("content-length", "0") or 0)
    while len(body) < want:
        chunk = conn.recv(4096)
        if not chunk:
            break
        body += chunk
    return Request(parts[0], parts[1], headers, body, None)


def _files(root):
    def handler(req):
        from urllib.parse import unquote
        path = unquote(req.path.split("?")[0])
        if ".." in path:
            return 403, "text/plain", b"forbidden"
        full = root.rstrip("/") + path
        try:
            if os.stat(full)[0] & 0x4000:
                if not full.endswith("/"):
                    full += "/"
                try:
                    os.stat(full + "index.html")
                    full += "index.html"
                except OSError:
                    names = sorted(os.listdir(full))
                    items = "".join('<li><a href="%s%s">%s</a></li>' % (path.rstrip("/") + "/", n, n) for n in names)
                    return 200, "text/html", ("<h1>%s</h1><ul>%s</ul>" % (path, items)).encode()
            with open(full, "rb") as f:
                body = f.read()
            return 200, TYPES.get(full.rsplit(".", 1)[-1].lower(), "application/octet-stream"), body
        except OSError:
            return 404, "text/html", b"<h1>404</h1><p>no existe</p>"
    return handler


def _serve(sock, handler, log):
    from http.client import responses
    while True:
        conn, peer = sock.accept()
        try:
            req = _read_request(conn)
            if req is None:
                continue
            req.peer = peer
            status, ctype, body = handler(req)
            if isinstance(body, str):
                body = body.encode()
            head = "HTTP/1.0 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nServer: PyKernel\r\nConnection: close\r\n\r\n" % (
                status, responses.get(status, "OK"), ctype, len(body))
            conn.sendall(head.encode() + body)
            log.append("%s %s %s %d" % (peer[0], req.method, req.path, status))
            del log[:-100]
        except Exception as e:
            log.append("error: %r" % e)
        finally:
            conn.close()


def serve(root="/", port=80, handler=None):
    """Start serving in a background thread; returns the request log (a list)."""
    sock = socket.socket()
    sock.bind(("", port))
    sock.listen(8)
    log = []
    thread.start(_serve, sock, handler or _files(root), log, name="http:%d" % port)
    servers.append((port, root, log))
    return log
