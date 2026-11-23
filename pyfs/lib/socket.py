# The standard `socket` module, on top of the kernel's own TCP/IP stack
# (/lib/kernel/net.py). Enough of CPython's API for HTTP clients and servers.
from kernel import net

AF_INET = 2
SOCK_STREAM, SOCK_DGRAM = 1, 2
IPPROTO_TCP, IPPROTO_UDP = 6, 17
SOL_SOCKET, SO_REUSEADDR, TCP_NODELAY = 1, 2, 1
SHUT_RD, SHUT_WR, SHUT_RDWR = 0, 1, 2
error = OSError


class timeout(OSError):
    pass


def _ensure_up():
    if net.nic is None or not net.ip:
        net.up()


def gethostbyname(name):
    _ensure_up()
    return net.ntoa(net.resolve(name))


def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return [(AF_INET, type or SOCK_STREAM, proto, "", (gethostbyname(host), int(port)))]


def gethostname():
    return net.hostname


class socket:
    def __init__(self, family=AF_INET, type=SOCK_STREAM, proto=0):
        self.family, self.type = family, type
        self._conn = self._listener = self._udp = None
        self._timeout = None
        self._bound = 0
        self._peer = None

    # -- common --
    def settimeout(self, seconds):
        self._timeout = None if seconds is None else int(seconds * 1000)

    def gettimeout(self):
        return None if self._timeout is None else self._timeout / 1000

    def setblocking(self, flag):
        self._timeout = None if flag else 0

    def setsockopt(self, *args):
        pass

    def fileno(self):
        return id(self) & 0xFFFF

    def bind(self, address):
        self._bound = int(address[1])
        if self.type == SOCK_DGRAM:
            _ensure_up()
            self._udp = net.UDPEndpoint(self._bound)

    def getsockname(self):
        port = (self._conn.lport if self._conn else self._udp.port if self._udp else self._bound)
        return (net.ntoa(net.ip), port)

    def getpeername(self):
        return self._peer

    def close(self):
        for part in (self._conn, self._listener, self._udp):
            if part is not None:
                part.close()
        self._conn = self._listener = self._udp = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        pass

    # -- TCP --
    def connect(self, address):
        _ensure_up()
        host, port = address
        rip = net.resolve(host)
        if self.type == SOCK_DGRAM:
            self._udp = self._udp or net.UDPEndpoint(self._bound)
            self._peer = (net.ntoa(rip), int(port))
            return
        self._conn = net.TCPConn(self._bound or net.ephemeral_port(), rip, int(port))
        self._peer = (net.ntoa(rip), int(port))
        try:
            self._conn.connect(10000 if self._timeout is None else max(self._timeout, 1))
        except OSError as e:
            self._conn = None
            if e.args and e.args[0] == 110:
                raise timeout("timed out")
            raise

    def listen(self, backlog=5):
        _ensure_up()
        self._listener = net.TCPListener(self._bound or 80, backlog)

    def accept(self):
        try:
            conn = self._listener.accept(self._timeout)
        except OSError as e:
            raise timeout("timed out") if e.args and e.args[0] == 110 else e
        s = socket(AF_INET, SOCK_STREAM)
        s._conn = conn
        s._peer = (net.ntoa(conn.rip), conn.rport)
        return s, s._peer

    def send(self, data):
        if self._udp is not None:
            return self.sendto(data, self._peer)
        if self._conn is None:
            raise OSError(107, "not connected")
        return self._conn.send(bytes(data))

    write = send

    def sendall(self, data):
        self.send(data)

    def recv(self, n=4096):
        if self._udp is not None:
            return self.recvfrom(n)[0]
        if self._conn is None:
            raise OSError(107, "not connected")
        try:
            return self._conn.recv(n, self._timeout)
        except OSError as e:
            if e.args and e.args[0] == 110:
                raise timeout("timed out")
            raise

    read = recv

    def recv_into(self, buf, n=0):
        data = self.recv(n or len(buf))
        buf[:len(data)] = data
        return len(data)

    def readinto(self, buf):
        return self.recv_into(buf)

    def shutdown(self, how=SHUT_RDWR):
        if self._conn is not None and how != SHUT_RD:
            self._conn.close()

    # -- UDP --
    def sendto(self, data, address):
        _ensure_up()
        self._udp = self._udp or net.UDPEndpoint(self._bound)
        return self._udp.sendto(bytes(data), net.resolve(address[0]), int(address[1]))

    def recvfrom(self, n=4096):
        try:
            data, addr = self._udp.recvfrom(self._timeout)
        except OSError as e:
            raise timeout("timed out") if e.args and e.args[0] == 110 else e
        return data[:n], addr

    def makefile(self, mode="rb", buffering=None, **kw):
        return SocketFile(self)


class SocketFile:
    """A buffered file object over a socket (readline for HTTP)."""

    def __init__(self, sock):
        self.sock, self.buf = sock, bytearray()

    def _fill(self):
        chunk = self.sock.recv(4096)
        self.buf += chunk
        return bool(chunk)

    def readline(self, limit=-1):
        while b"\n" not in self.buf and self._fill():
            pass
        i = self.buf.find(b"\n")
        i = len(self.buf) if i < 0 else i + 1
        line = bytes(self.buf[:i])
        self.buf = self.buf[i:]
        return line

    def read(self, n=-1):
        if n is None or n < 0:
            while self._fill():
                pass
            n = len(self.buf)
        while len(self.buf) < n and self._fill():
            pass
        out = bytes(self.buf[:n])
        self.buf = self.buf[n:]
        return out

    def write(self, data):
        self.sock.sendall(data)
        return len(data)

    def flush(self):
        pass

    def close(self):
        pass
