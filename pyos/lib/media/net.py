# A file on the web that can be read like a file on the disk: seek() and
# read() ask the server only for the bytes needed (HTTP "Range"), 256 KiB
# at a time, and keep the last pieces. So a video starts playing at once
# and jumping to the middle does not download the beginning.
#
#   f = HttpFile("https://example.com/video.mp4")
#   f.seek(1000); f.read(64)
BLOCK = 256 << 10
KEEP = 24                                # blocks kept in memory (6 MiB)


class HttpFile:
    def __init__(self, url, headers=None):
        self.url = url
        self.headers = dict(headers or {})
        self.pos = 0
        self.blocks = {}                 # block number -> bytes
        self.order = []
        self.size = None
        first = self._get(0)             # also learns the size
        if self.size is None:
            self.size = len(first)

    def _get(self, n):
        if n in self.blocks:
            return self.blocks[n]
        from urllib import request
        start = n * BLOCK
        h = dict(self.headers)
        h["Range"] = "bytes=%d-%d" % (start, start + BLOCK - 1)
        h.setdefault("User-Agent", "SnakeyOS-Navegador/1.0")
        r = request.urlopen(request.Request(self.url, None, h), timeout=30)
        data = r.read()
        if getattr(r, "status", 200) == 200 and start:   # the server ignores Range: it sent everything
            data = data[start:start + BLOCK]
        rng = r.getheader("content-range") if hasattr(r, "getheader") else None
        if rng and "/" in rng and self.size is None:
            total = rng.rsplit("/", 1)[1].strip()
            if total.isdigit():
                self.size = int(total)
        self.url = r.geturl() if hasattr(r, "geturl") else self.url   # after redirects
        self.blocks[n] = data
        self.order.append(n)
        while len(self.order) > KEEP:
            self.blocks.pop(self.order.pop(0), None)
        return data

    def seek(self, pos, whence=0):
        self.pos = pos if whence == 0 else (self.pos + pos if whence == 1 else (self.size or 0) + pos)
        return self.pos

    def tell(self):
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = (self.size or self.pos) - self.pos
        out = []
        while n > 0 and (self.size is None or self.pos < self.size):
            b, off = divmod(self.pos, BLOCK)
            data = self._get(b)
            piece = data[off:off + n]
            if not piece:
                break
            out.append(piece)
            self.pos += len(piece)
            n -= len(piece)
        return b"".join(out)

    def close(self):
        self.blocks, self.order = {}, []
