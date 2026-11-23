# TLS 1.3 client (RFC 8446), in Python, with the standard `ssl` API:
#
#   import socket, ssl
#   s = ssl.create_default_context().wrap_socket(socket.socket(), server_hostname="example.com")
#   s.connect(("example.com", 443))
#
# Cipher: TLS_CHACHA20_POLY1305_SHA256. Key exchange: X25519. The server's
# certificate chain is checked against /etc/ssl/certs.pem (RSA and ECDSA
# P-256/P-384 signatures), with the host name and the validity dates.
import struct
import hashlib
import socket as _socket
import crypto
from crypto import chacha, x25519, x509

CERT_NONE, CERT_OPTIONAL, CERT_REQUIRED = 0, 1, 2
PROTOCOL_TLS_CLIENT = 16
HAS_SNI = True
OPENSSL_VERSION = "PyKernel TLS 1.3 (Python)"

CHANGE_CIPHER_SPEC, ALERT, HANDSHAKE, APPLICATION_DATA = 20, 21, 22, 23
CLIENT_HELLO, SERVER_HELLO, NEW_SESSION_TICKET, ENCRYPTED_EXTENSIONS = 1, 2, 4, 8
CERTIFICATE, CERTIFICATE_VERIFY, FINISHED, KEY_UPDATE = 11, 15, 20, 24
TLS_CHACHA20_POLY1305_SHA256 = 0x1303
HRR_RANDOM = bytes.fromhex("cf21ad74e59a6111be1d8c021e65b891c2a211167abb8c5e079e09e2c8a8339c")


class SSLError(OSError):
    pass


class SSLCertVerificationError(SSLError):
    pass


def _u8(b):
    return bytes([len(b)]) + b


def _u16(b):
    return struct.pack("!H", len(b)) + b


def _u24(b):
    return struct.pack("!I", len(b))[1:] + b


def _ext(kind, body):
    return struct.pack("!H", kind) + _u16(body)


def _expand_label(secret, label, context, length):
    info = struct.pack("!H", length) + _u8(b"tls13 " + label) + _u8(context)
    return crypto.hkdf_expand("sha256", secret, info, length)


def _sha(data):
    return hashlib.sha256(data).digest()


class _Keys:
    def __init__(self, secret):
        self.secret = secret
        self.key = _expand_label(secret, b"key", b"", 32)
        self.iv = _expand_label(secret, b"iv", b"", 12)
        self.seq = 0

    def nonce(self):
        n = bytes(4) + struct.pack("!Q", self.seq)
        self.seq += 1
        return bytes(a ^ b for a, b in zip(self.iv, n))


def _now_text():
    try:
        import time
        t = time.gmtime()
        return "%04d%02d%02d%02d%02d%02d" % t[:6]
    except Exception:
        return None


class SSLSocket:
    def __init__(self, sock, server_hostname=None, verify=CERT_REQUIRED, alpn=None, roots=None):
        self.roots = roots
        self.sock = sock
        self.host = server_hostname
        self.verify = verify
        self.alpn = alpn
        self.selected_alpn = None
        self._buf = b""            # raw bytes from the socket
        self._plain = b""          # decrypted application data
        self._read_keys = self._write_keys = None
        self._closed = False
        self._eof = False
        self.peer_chain = []
        if getattr(sock, "_conn", None) is not None:
            self.do_handshake()

    # -- socket-like API --
    def connect(self, address):
        if self.host is None:
            self.host = address[0]
        self.sock.connect(address)
        self.do_handshake()

    def settimeout(self, t):
        self.sock.settimeout(t)

    def setblocking(self, flag):
        self.sock.setblocking(flag)

    def fileno(self):
        return self.sock.fileno()

    def getpeercert(self, binary_form=False):
        if not self.peer_chain:
            return None
        leaf = self.peer_chain[0]
        if binary_form:
            return leaf.der
        return {"subject": ((("commonName", leaf.subject.get("CN", "")),),),
                "issuer": ((("commonName", leaf.issuer.get("CN", "")),),),
                "subjectAltName": tuple(("DNS", n) for n in leaf.dns_names),
                "notBefore": leaf.not_before, "notAfter": leaf.not_after}

    def version(self):
        return "TLSv1.3"

    def cipher(self):
        return ("TLS_CHACHA20_POLY1305_SHA256", "TLSv1.3", 256)

    def selected_alpn_protocol(self):
        return self.selected_alpn

    def send(self, data):
        data = bytes(data)
        for i in range(0, len(data), 16000):
            self._send_record(APPLICATION_DATA, data[i:i + 16000])
        return len(data)

    write = send
    sendall = send

    def recv(self, n=4096):
        while not self._plain and not self._eof:
            kind, body = self._read_record()
            if kind is None:
                self._eof = True
            elif kind == APPLICATION_DATA:
                self._plain += body
            elif kind == HANDSHAKE:
                self._post_handshake(body)
            elif kind == ALERT:
                if body[1] == 0:          # close_notify
                    self._eof = True
                else:
                    raise SSLError("TLS alert %d" % body[1])
        out, self._plain = self._plain[:n], self._plain[n:]
        return out

    read = recv

    def recv_into(self, buf, n=0):
        data = self.recv(n or len(buf))
        buf[:len(data)] = data
        return len(data)

    def readinto(self, buf):
        return self.recv_into(buf)

    def makefile(self, mode="rb", buffering=None, **kw):
        return _socket.SocketFile(self)

    def close(self):
        if not self._closed and self._write_keys:
            try:
                self._send_record(ALERT, b"\x01\x00")
            except OSError:
                pass
        self._closed = True
        self.sock.close()

    def unwrap(self):
        return self.sock

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- records --
    def _raw(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(16384)
            if not chunk:
                return None
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _read_record(self):
        header = self._raw(5)
        if header is None:
            return None, b""
        kind, _, length = struct.unpack("!BHH", header)
        body = self._raw(length)
        if body is None:
            raise SSLError("connection closed inside a record")
        if kind == CHANGE_CIPHER_SPEC:
            return self._read_record()
        if self._read_keys and kind == APPLICATION_DATA:
            k = self._read_keys
            plain = chacha.open_(k.key, k.nonce(), body, header)
            i = len(plain) - 1
            while i >= 0 and plain[i] == 0:
                i -= 1
            return plain[i], plain[:i]
        if kind == ALERT:
            raise SSLError("TLS alert %d from server" % body[1])
        return kind, body

    def _send_record(self, kind, payload):
        if self._write_keys:
            k = self._write_keys
            inner = payload + bytes([kind])
            header = struct.pack("!BHH", APPLICATION_DATA, 0x0303, len(inner) + 16)
            self.sock.sendall(header + chacha.seal(k.key, k.nonce(), inner, header))
        else:
            self.sock.sendall(struct.pack("!BHH", kind, 0x0301 if kind == HANDSHAKE else 0x0303, len(payload)) + payload)

    def _messages(self):
        """Yield whole handshake messages, across record boundaries."""
        pending = b""
        while True:
            while len(pending) >= 4:
                length = int.from_bytes(pending[1:4], "big")
                if len(pending) < 4 + length:
                    break
                msg, pending = pending[:4 + length], pending[4 + length:]
                yield msg
            kind, body = self._read_record()
            if kind is None:
                raise SSLError("connection closed during the handshake")
            if kind == ALERT:
                raise SSLError("TLS alert %d" % body[1])
            if kind != HANDSHAKE:
                raise SSLError("unexpected record %d in the handshake" % kind)
            pending += body

    # -- the handshake --
    def _client_hello(self, public):
        exts = b""
        if self.host and not self.host.replace(".", "").isdigit():
            name = self.host.encode()
            exts += _ext(0, _u16(b"\x00" + _u16(name)))                       # server_name
        exts += _ext(10, _u16(struct.pack("!H", 0x001D)))                       # groups: x25519
        algs = (0x0403, 0x0804, 0x0503, 0x0805, 0x0806, 0x0401, 0x0501, 0x0601)
        exts += _ext(13, _u16(b"".join(struct.pack("!H", a) for a in algs)))  # signature_algorithms
        exts += _ext(43, _u8(b"\x03\x04"))                                     # supported_versions
        exts += _ext(45, _u8(b"\x01"))                                         # psk modes (for tickets)
        exts += _ext(51, _u16(struct.pack("!H", 0x001D) + _u16(public)))      # key_share
        if self.alpn:
            exts += _ext(16, _u16(b"".join(_u8(p.encode()) for p in self.alpn)))
        body = (b"\x03\x03" + crypto.random_bytes(32) + _u8(crypto.random_bytes(32)) +
                _u16(struct.pack("!H", TLS_CHACHA20_POLY1305_SHA256)) + b"\x01\x00" + _u16(exts))
        return bytes([CLIENT_HELLO]) + _u24(body)

    def do_handshake(self):
        """Run the handshake (30 s at most if the socket has no timeout)."""
        saved = self.sock.gettimeout()
        if saved is None:
            self.sock.settimeout(30)
        try:
            self._handshake()
        finally:
            self.sock.settimeout(saved)

    def _handshake(self):
        private, public = x25519.keypair(crypto.random_bytes)
        hello = self._client_hello(public)
        self._send_record(HANDSHAKE, hello)
        transcript = hello
        messages = self._messages()

        sh = next(messages)
        if sh[0] != SERVER_HELLO:
            raise SSLError("expected ServerHello")
        transcript += sh
        server_public = self._parse_server_hello(sh[4:])
        shared = x25519.scalarmult(private, server_public)

        zero = bytes(32)
        early = crypto.hkdf_extract("sha256", b"", zero)
        derived = _expand_label(early, b"derived", _sha(b""), 32)
        hs = crypto.hkdf_extract("sha256", derived, shared)
        th = _sha(transcript)
        c_hs = _expand_label(hs, b"c hs traffic", th, 32)
        s_hs = _expand_label(hs, b"s hs traffic", th, 32)
        self._read_keys = _Keys(s_hs)

        chain, cert_transcript = [], None
        while True:
            msg = next(messages)
            kind = msg[0]
            if kind == ENCRYPTED_EXTENSIONS:
                self._parse_ee(msg[4:])
            elif kind == CERTIFICATE:
                chain = self._parse_certificate(msg[4:])
                cert_transcript = transcript + msg
            elif kind == CERTIFICATE_VERIFY:
                self._check_cert_verify(chain, msg[4:], _sha(cert_transcript))
            elif kind == FINISHED:
                finished_key = _expand_label(s_hs, b"finished", b"", 32)
                if crypto.hmac("sha256", finished_key, _sha(transcript)) != msg[4:]:
                    raise SSLError("server Finished does not verify")
                transcript += msg
                break
            else:
                raise SSLError("unexpected handshake message %d" % kind)
            transcript += msg

        if self.verify != CERT_NONE:
            if not chain:
                raise SSLCertVerificationError("server sent no certificate")
            try:
                x509.verify_chain(chain, self.host, _now_text(), self.roots)
            except ValueError as e:
                raise SSLCertVerificationError("certificate verify failed: %s" % e)
        self.peer_chain = chain

        master = crypto.hkdf_extract("sha256", _expand_label(hs, b"derived", _sha(b""), 32), zero)
        th = _sha(transcript)
        c_ap = _expand_label(master, b"c ap traffic", th, 32)
        s_ap = _expand_label(master, b"s ap traffic", th, 32)

        self._write_keys = _Keys(c_hs)
        finished_key = _expand_label(c_hs, b"finished", b"", 32)
        self._send_record(HANDSHAKE, bytes([FINISHED]) + _u24(crypto.hmac("sha256", finished_key, th)))
        self._write_keys = _Keys(c_ap)
        self._read_keys = _Keys(s_ap)

    def _parse_server_hello(self, b):
        random = b[2:34]
        if random == HRR_RANDOM:
            raise SSLError("server asked to retry with another group (X25519 unsupported)")
        i = 34
        i += 1 + b[i]                          # session id
        suite = struct.unpack_from("!H", b, i)[0]
        if suite != TLS_CHACHA20_POLY1305_SHA256:
            raise SSLError("server chose cipher %#x" % suite)
        i += 3
        end = i + 2 + struct.unpack_from("!H", b, i)[0]
        i += 2
        key, version = None, None
        while i < end:
            kind, length = struct.unpack_from("!HH", b, i)
            body = b[i + 4:i + 4 + length]
            if kind == 43:
                version = struct.unpack("!H", body)[0]
            elif kind == 51:
                key = body[4:4 + struct.unpack_from("!H", body, 2)[0]]
            i += 4 + length
        if version != 0x0304:
            raise SSLError("server does not speak TLS 1.3")
        if not key:
            raise SSLError("no key share from server")
        return key

    def _parse_ee(self, b):
        i, end = 2, 2 + struct.unpack_from("!H", b)[0]
        while i < end:
            kind, length = struct.unpack_from("!HH", b, i)
            if kind == 16:
                body = b[i + 4:i + 4 + length]
                self.selected_alpn = body[3:3 + body[2]].decode()
            i += 4 + length

    def _parse_certificate(self, b):
        i = 1 + b[0]                           # request context
        end = i + 3 + int.from_bytes(b[i:i + 3], "big")
        i += 3
        chain = []
        while i < end:
            n = int.from_bytes(b[i:i + 3], "big")
            der = b[i + 3:i + 3 + n]
            i += 3 + n
            i += 2 + struct.unpack_from("!H", b, i)[0]       # extensions
            try:
                chain.append(x509.Certificate(der))
            except Exception as e:
                if not chain:
                    raise SSLError("cannot read the server certificate: %r" % e)
        return chain

    def _check_cert_verify(self, chain, b, th):
        if self.verify == CERT_NONE:
            return
        alg = struct.unpack_from("!H", b)[0]
        sig = b[4:4 + struct.unpack_from("!H", b, 2)[0]]
        content = b" " * 64 + b"TLS 1.3, server CertificateVerify\x00" + th
        key = chain[0].key
        from crypto import ec, rsa
        ok = False
        if alg in (0x0403, 0x0503) and key[0] == "ec":
            hashname = "sha256" if alg == 0x0403 else "sha384"
            r, s = x509.decode_ecdsa_sig(sig)
            ok = ec.verify(key[1], key[2], crypto.digest(hashname, content), r, s)
        elif alg in (0x0804, 0x0805, 0x0806) and key[0] == "rsa":
            hashname = {0x0804: "sha256", 0x0805: "sha384", 0x0806: "sha512"}[alg]
            ok = rsa.verify_pss(key[1], key[2], hashname, crypto.digest(hashname, content), sig)
        if not ok:
            raise SSLCertVerificationError("CertificateVerify signature is wrong (alg %#x)" % alg)

    def _post_handshake(self, body):
        i = 0
        while i + 4 <= len(body):
            kind = body[i]
            length = int.from_bytes(body[i + 1:i + 4], "big")
            if kind == KEY_UPDATE:
                k = self._read_keys
                self._read_keys = _Keys(_expand_label(k.secret, b"traffic upd", b"", 32))
                if body[i + 4] == 1:           # update_requested
                    self._send_record(HANDSHAKE, bytes([KEY_UPDATE, 0, 0, 1, 0]))
                    w = self._write_keys
                    self._write_keys = _Keys(_expand_label(w.secret, b"traffic upd", b"", 32))
            i += 4 + length                    # NewSessionTicket: ignored


class SSLContext:
    def __init__(self, protocol=PROTOCOL_TLS_CLIENT):
        self.verify_mode = CERT_REQUIRED
        self.check_hostname = True
        self._alpn = None
        self._roots = {}

    def load_verify_locations(self, cafile=None, capath=None, cadata=None):
        if cafile:
            with open(cafile) as f:
                cadata = f.read()
        if cadata:
            for k, v in x509.parse_roots(cadata if isinstance(cadata, str) else cadata.decode()).items():
                self._roots.setdefault(k, []).extend(v)

    def load_default_certs(self, purpose=None):
        x509.roots()

    def set_alpn_protocols(self, protocols):
        self._alpn = list(protocols)

    def wrap_socket(self, sock, server_side=False, do_handshake_on_connect=True, server_hostname=None):
        if server_side:
            raise SSLError("TLS server mode is not implemented")
        return SSLSocket(sock, server_hostname if self.check_hostname or server_hostname else None,
                         self.verify_mode, self._alpn, self._roots)


def create_default_context(purpose=None, cafile=None, capath=None, cadata=None):
    ctx = SSLContext()
    if cafile or cadata:
        ctx.load_verify_locations(cafile, capath, cadata)
    return ctx


def _create_unverified_context(*a, **kw):
    ctx = SSLContext()
    ctx.verify_mode = CERT_NONE
    ctx.check_hostname = False
    return ctx


def wrap_socket(sock, server_hostname=None, cert_reqs=CERT_REQUIRED, **kw):
    return SSLSocket(sock, server_hostname, cert_reqs)
