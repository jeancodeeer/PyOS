# TLS client, in Python, with the standard `ssl` API:
#
#   import socket, ssl
#   s = ssl.create_default_context().wrap_socket(socket.socket(), server_hostname="example.com")
#   s.connect(("example.com", 443))
#
# TLS 1.3 (RFC 8446) first, TLS 1.2 (RFC 5246) for servers that do not speak 1.3.
# Ciphers: AES-128-GCM (from the kernel's _aes module, in C) and
# ChaCha20-Poly1305. Key exchange: X25519, or P-256 when the server asks for it.
# TLS 1.2 only with ECDHE (forward secrecy) and AEAD ciphers: no RSA key
# transport, no CBC. The server's certificate chain is checked against
# /etc/ssl/certs.pem (RSA and ECDSA P-256/P-384 signatures), with the host
# name and the validity dates.
import struct
import hashlib
import socket as _socket
import crypto
from crypto import chacha, x25519, x509
try:
    import _aes                       # AES-GCM in C (PyKernel's kernel)
except ImportError:
    _aes = None

CERT_NONE, CERT_OPTIONAL, CERT_REQUIRED = 0, 1, 2
PROTOCOL_TLS_CLIENT = 16
HAS_SNI = True
OPENSSL_VERSION = "PyKernel TLS 1.3/1.2 (Python)"

CHANGE_CIPHER_SPEC, ALERT, HANDSHAKE, APPLICATION_DATA = 20, 21, 22, 23
CLIENT_HELLO, SERVER_HELLO, NEW_SESSION_TICKET, ENCRYPTED_EXTENSIONS = 1, 2, 4, 8
CERTIFICATE, CERTIFICATE_VERIFY, FINISHED, KEY_UPDATE = 11, 15, 20, 24
SERVER_KEY_EXCHANGE, CERTIFICATE_REQUEST, SERVER_HELLO_DONE, CLIENT_KEY_EXCHANGE = 12, 13, 14, 16
TLS_AES_128_GCM_SHA256 = 0x1301
TLS_CHACHA20_POLY1305_SHA256 = 0x1303
# TLS 1.2 suites: ECDHE, signed with ECDSA or RSA, AES-128-GCM or ChaCha20-Poly1305
ECDHE_ECDSA_AES128_GCM, ECDHE_RSA_AES128_GCM = 0xC02B, 0xC02F
ECDHE_ECDSA_CHACHA20, ECDHE_RSA_CHACHA20 = 0xCCA9, 0xCCA8
X25519, SECP256R1 = 0x001D, 0x0017
SUITE_NAMES = {TLS_AES_128_GCM_SHA256: "TLS_AES_128_GCM_SHA256",
               TLS_CHACHA20_POLY1305_SHA256: "TLS_CHACHA20_POLY1305_SHA256",
               ECDHE_ECDSA_AES128_GCM: "ECDHE-ECDSA-AES128-GCM-SHA256",
               ECDHE_RSA_AES128_GCM: "ECDHE-RSA-AES128-GCM-SHA256",
               ECDHE_ECDSA_CHACHA20: "ECDHE-ECDSA-CHACHA20-POLY1305",
               ECDHE_RSA_CHACHA20: "ECDHE-RSA-CHACHA20-POLY1305"}
AES_SUITES = (TLS_AES_128_GCM_SHA256, ECDHE_ECDSA_AES128_GCM, ECDHE_RSA_AES128_GCM)
TLS13_SUITES = (TLS_AES_128_GCM_SHA256, TLS_CHACHA20_POLY1305_SHA256)
TLS12_SUITES = (ECDHE_ECDSA_AES128_GCM, ECDHE_RSA_AES128_GCM, ECDHE_ECDSA_CHACHA20, ECDHE_RSA_CHACHA20)
DOWNGRADE = b"DOWNGRD\x01"          # the end of a TLS 1.3 server's random when it falls back to 1.2
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


def _seal(aes, key, nonce, data, aad):
    if aes:
        return _aes.gcm_seal(key, nonce, data, aad)
    return chacha.seal(key, nonce, data, aad)


def _open(aes, key, nonce, data, aad):
    if aes:
        out = _aes.gcm_open(key, nonce, data, aad)
        if out is None:
            raise SSLError("bad record MAC")
        return out
    try:
        return chacha.open_(key, nonce, data, aad)
    except ValueError:
        raise SSLError("bad record MAC")


class _Keys:
    """One direction of a TLS 1.3 connection: key and IV derived from a traffic secret."""

    def __init__(self, secret, aes=False):
        self.secret = secret
        self.aes = aes
        self.key = _expand_label(secret, b"key", b"", 16 if aes else 32)
        self.iv = _expand_label(secret, b"iv", b"", 12)
        self.seq = 0

    def nonce(self):
        n = bytes(4) + struct.pack("!Q", self.seq)
        self.seq += 1
        return bytes(a ^ b for a, b in zip(self.iv, n))

    def again(self, secret):
        return _Keys(secret, self.aes)


class _Keys12:
    """One direction of a TLS 1.2 connection (AES-GCM: 4 fixed bytes of nonce,
    8 sent with each record; ChaCha20: the IV xor the record number)."""

    def __init__(self, aes, key, iv):
        self.aes, self.key, self.iv, self.seq = aes, key, iv, 0

    def seal(self, kind, payload):
        seq = struct.pack("!Q", self.seq)
        self.seq += 1
        aad = seq + struct.pack("!BHH", kind, 0x0303, len(payload))
        if self.aes:
            return seq + _aes.gcm_seal(self.key, self.iv + seq, payload, aad)
        nonce = bytes(a ^ b for a, b in zip(self.iv, bytes(4) + seq))
        return chacha.seal(self.key, nonce, payload, aad)

    def open(self, kind, body):
        seq = struct.pack("!Q", self.seq)
        self.seq += 1
        if self.aes:
            nonce, body = self.iv + body[:8], body[8:]
        else:
            nonce = bytes(a ^ b for a, b in zip(self.iv, bytes(4) + seq))
        aad = seq + struct.pack("!BHH", kind, 0x0303, len(body) - 16)
        return _open(self.aes, self.key, nonce, body, aad)


def _prf(secret, label, seed, n):
    """TLS 1.2's pseudo-random function (P_SHA256)."""
    seed = label + seed
    out, a = b"", seed
    while len(out) < n:
        a = crypto.hmac("sha256", secret, a)
        out += crypto.hmac("sha256", secret, a + seed)
    return out[:n]


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
        self._pending_read = None      # TLS 1.2: the server's keys, used after its ChangeCipherSpec
        self._tls12 = False
        self._suite = None
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
        return "TLSv1.2" if self._tls12 else "TLSv1.3"

    def cipher(self):
        return (SUITE_NAMES.get(self._suite, "?"), self.version(), 128 if self._suite in AES_SUITES else 256)

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
            if self._pending_read is not None:          # TLS 1.2: from here on the server encrypts
                self._read_keys, self._pending_read = self._pending_read, None
            return self._read_record()
        if self._read_keys and self._tls12:
            return kind, self._read_keys.open(kind, body)
        if self._read_keys and kind == APPLICATION_DATA:
            k = self._read_keys
            plain = _open(k.aes, k.key, k.nonce(), body, header)
            i = len(plain) - 1
            while i >= 0 and plain[i] == 0:
                i -= 1
            return plain[i], plain[:i]
        if kind == ALERT:
            raise SSLError("TLS alert %d from server" % body[1])
        return kind, body

    def _send_record(self, kind, payload):
        if self._write_keys and self._tls12:
            body = self._write_keys.seal(kind, payload)
            self.sock.sendall(struct.pack("!BHH", kind, 0x0303, len(body)) + body)
        elif self._write_keys:
            k = self._write_keys
            inner = payload + bytes([kind])
            header = struct.pack("!BHH", APPLICATION_DATA, 0x0303, len(inner) + 16)
            self.sock.sendall(header + _seal(k.aes, k.key, k.nonce(), inner, header))
        else:
            # 0x0301 only on the ClientHello (old servers expect it); everything after it says TLS 1.2
            first = kind == HANDSHAKE and payload[:1] == bytes([CLIENT_HELLO])
            self.sock.sendall(struct.pack("!BHH", kind, 0x0301 if first else 0x0303, len(payload)) + payload)

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
    def _client_hello(self, shares, cookie=None):
        """shares: [(group, public key)]. The same random and session id in both
        hellos when the server asks for a retry."""
        exts = b""
        if self.host and not self.host.replace(".", "").isdigit():
            name = self.host.encode()
            exts += _ext(0, _u16(b"\x00" + _u16(name)))                       # server_name
        exts += _ext(10, _u16(struct.pack("!HH", X25519, SECP256R1)))          # groups
        exts += _ext(11, b"\x01\x00")                                         # point formats: uncompressed
        algs = (0x0403, 0x0804, 0x0503, 0x0805, 0x0806, 0x0401, 0x0501, 0x0601)
        exts += _ext(13, _u16(b"".join(struct.pack("!H", a) for a in algs)))  # signature_algorithms
        exts += _ext(23, b"")                                                  # extended master secret (1.2)
        exts += _ext(43, _u8(b"\x03\x04\x03\x03"))                             # versions: 1.3, 1.2
        exts += _ext(45, _u8(b"\x01"))                                         # psk modes (for tickets)
        exts += _ext(51, _u16(b"".join(struct.pack("!H", g) + _u16(k) for g, k in shares)))   # key_share
        exts += _ext(0xFF01, b"\x00")                                          # secure renegotiation (1.2)
        if cookie:
            exts += _ext(44, cookie)
        if self.alpn:
            exts += _ext(16, _u16(b"".join(_u8(p.encode()) for p in self.alpn)))
        suites = TLS13_SUITES + TLS12_SUITES
        if _aes is None:                                  # no AES here: ChaCha20 only
            suites = tuple(x for x in suites if x not in AES_SUITES)
        body = (b"\x03\x03" + self._random + _u8(self._sid) +
                _u16(b"".join(struct.pack("!H", x) for x in suites)) + b"\x01\x00" + _u16(exts))
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
        self._random = crypto.random_bytes(32)
        self._sid = crypto.random_bytes(32)
        private, public = x25519.keypair(crypto.random_bytes)
        hello = self._client_hello([(X25519, public)])
        self._send_record(HANDSHAKE, hello)
        transcript = hello
        messages = self._messages()

        sh = next(messages)
        if sh[0] != SERVER_HELLO:
            raise SSLError("expected ServerHello")
        info = self._parse_server_hello(sh[4:])
        if info["hrr"]:
            # HelloRetryRequest: the server wants another group (P-256). The
            # transcript starts again from a hash of the first hello.
            if info["group"] != SECP256R1:
                raise SSLError("server wants key exchange group %#x" % info["group"])
            from crypto import ec
            ec_private, ec_public = ec.ecdh_keypair(crypto.random_bytes)
            transcript = bytes([254, 0, 0, 32]) + _sha(hello) + sh
            hello = self._client_hello([(SECP256R1, ec_public)], info.get("cookie"))
            self._send_record(HANDSHAKE, hello)
            transcript += hello
            sh = next(messages)
            info = self._parse_server_hello(sh[4:])
            if info["hrr"] or info["version"] != 0x0304:
                raise SSLError("second ServerHello is not TLS 1.3")
            transcript += sh
            shared = ec.ecdh_shared(ec_private, info["key"])
        else:
            transcript += sh
            if info["version"] != 0x0304:
                return self._handshake12(messages, transcript, info, private, public)
            if info["group"] != X25519:
                raise SSLError("server answered with key exchange group %#x" % info["group"])
            shared = x25519.scalarmult(private, info["key"])
        self._suite = info["suite"]
        aes = self._suite in AES_SUITES

        zero = bytes(32)
        early = crypto.hkdf_extract("sha256", b"", zero)
        derived = _expand_label(early, b"derived", _sha(b""), 32)
        hs = crypto.hkdf_extract("sha256", derived, shared)
        th = _sha(transcript)
        c_hs = _expand_label(hs, b"c hs traffic", th, 32)
        s_hs = _expand_label(hs, b"s hs traffic", th, 32)
        self._read_keys = _Keys(s_hs, aes)

        chain, cert_transcript, proven = [], None, False
        while True:
            msg = next(messages)
            kind = msg[0]
            if kind == ENCRYPTED_EXTENSIONS:
                self._parse_ee(msg[4:])
            elif kind == CERTIFICATE:
                chain = self._parse_certificate(msg[4:])
                cert_transcript = transcript + msg
            elif kind == CERTIFICATE_VERIFY:
                if not chain:
                    raise SSLError("CertificateVerify before any certificate")
                self._check_cert_verify(chain, msg[4:], _sha(cert_transcript))
                proven = True
            elif kind == FINISHED:
                finished_key = _expand_label(s_hs, b"finished", b"", 32)
                if crypto.hmac("sha256", finished_key, _sha(transcript)) != msg[4:]:
                    raise SSLError("server Finished does not verify")
                transcript += msg
                break
            elif kind == CERTIFICATE_REQUEST:
                self._cert_requested = True
            else:
                raise SSLError("unexpected handshake message %d" % kind)
            transcript += msg

        self._check_chain(chain, proven)

        master = crypto.hkdf_extract("sha256", _expand_label(hs, b"derived", _sha(b""), 32), zero)
        th = _sha(transcript)
        c_ap = _expand_label(master, b"c ap traffic", th, 32)
        s_ap = _expand_label(master, b"s ap traffic", th, 32)

        self._write_keys = _Keys(c_hs, aes)
        if getattr(self, "_cert_requested", False):        # asked for a client certificate: we have none
            empty = bytes([CERTIFICATE]) + _u24(b"\x00" + _u24(b""))
            self._send_record(HANDSHAKE, empty)
            transcript += empty
            th = _sha(transcript)
        finished_key = _expand_label(c_hs, b"finished", b"", 32)
        self._send_record(HANDSHAKE, bytes([FINISHED]) + _u24(crypto.hmac("sha256", finished_key, th)))
        self._write_keys = _Keys(c_ap, aes)
        self._read_keys = _Keys(s_ap, aes)

    def _check_chain(self, chain, proven):
        if self.verify != CERT_NONE:
            if not chain:
                raise SSLCertVerificationError("server sent no certificate")
            # Safety: without a signature from the server it never proved it has
            # the certificate's private key: anyone can copy a public certificate.
            if not proven:
                raise SSLCertVerificationError("server did not prove it owns its certificate")
            try:
                x509.verify_chain(chain, self.host, _now_text(), self.roots)
            except ValueError as e:
                raise SSLCertVerificationError("certificate verify failed: %s" % e)
        self.peer_chain = chain

    # -- TLS 1.2 (for servers without 1.3) --
    def _handshake12(self, messages, transcript, info, x_private, x_public):
        self._suite = suite = info["suite"]
        aes = suite in AES_SUITES
        server_random = info["random"]
        chain, ske, cert_requested = [], None, False
        while True:
            msg = next(messages)
            transcript += msg
            kind = msg[0]
            if kind == CERTIFICATE:
                chain = self._parse_certificate12(msg[4:])
            elif kind == SERVER_KEY_EXCHANGE:
                ske = msg[4:]
            elif kind == CERTIFICATE_REQUEST:
                cert_requested = True
            elif kind == SERVER_HELLO_DONE:
                break
            # anything else (certificate status...) is not needed
        if ske is None or ske[0] != 3:
            raise SSLError("TLS 1.2 server without an ECDHE key exchange")
        group = struct.unpack_from("!H", ske, 1)[0]
        n = ske[3]
        point, params = ske[4:4 + n], ske[:4 + n]
        alg = struct.unpack_from("!H", ske, 4 + n)[0]
        sig = ske[8 + n:8 + n + struct.unpack_from("!H", ske, 6 + n)[0]]
        proven = False
        if self.verify != CERT_NONE:
            if not chain:
                raise SSLCertVerificationError("server sent no certificate")
            self._check_signature(chain[0].key, alg, self._random + server_random + params, sig)
            proven = True
        self._check_chain(chain, proven)
        if group == X25519:
            shared, mine = x25519.scalarmult(x_private, point), x_public
        elif group == SECP256R1:
            from crypto import ec
            d, mine = ec.ecdh_keypair(crypto.random_bytes)
            shared = ec.ecdh_shared(d, point)
        else:
            raise SSLError("server chose key exchange group %#x" % group)
        if cert_requested:
            empty = bytes([CERTIFICATE]) + _u24(_u24(b""))
            self._send_record(HANDSHAKE, empty)
            transcript += empty
        cke = bytes([CLIENT_KEY_EXCHANGE]) + _u24(_u8(mine))
        self._send_record(HANDSHAKE, cke)
        transcript += cke
        if info["ems"]:
            master = _prf(shared, b"extended master secret", _sha(transcript), 48)
        else:
            master = _prf(shared, b"master secret", self._random + server_random, 48)
        klen, ivlen = (16, 4) if aes else (32, 12)
        kb = _prf(master, b"key expansion", server_random + self._random, 2 * (klen + ivlen))
        ckey, skey = kb[:klen], kb[klen:2 * klen]
        civ, siv = kb[2 * klen:2 * klen + ivlen], kb[2 * klen + ivlen:]
        self.sock.sendall(b"\x14\x03\x03\x00\x01\x01")              # ChangeCipherSpec
        self._tls12 = True
        self._write_keys = _Keys12(aes, ckey, civ)
        fin = bytes([FINISHED]) + _u24(_prf(master, b"client finished", _sha(transcript), 12))
        self._send_record(HANDSHAKE, fin)
        transcript += fin
        self._pending_read = _Keys12(aes, skey, siv)
        msg = next(messages)
        while msg[0] == NEW_SESSION_TICKET:
            transcript += msg
            msg = next(messages)
        if msg[0] != FINISHED or msg[4:] != _prf(master, b"server finished", _sha(transcript), 12):
            raise SSLError("server Finished does not verify")
        if self._read_keys is None:
            raise SSLError("server Finished arrived unencrypted")

    def _parse_certificate12(self, b):
        end = 3 + int.from_bytes(b[0:3], "big")
        i, chain = 3, []
        while i < end:
            n = int.from_bytes(b[i:i + 3], "big")
            der = b[i + 3:i + 3 + n]
            i += 3 + n
            try:
                chain.append(x509.Certificate(der))
            except Exception as e:
                if not chain:
                    raise SSLError("cannot read the server certificate: %r" % e)
        return chain

    def _parse_server_hello(self, b):
        info = {"random": b[2:34], "hrr": b[2:34] == HRR_RANDOM, "version": struct.unpack_from("!H", b)[0],
                "ems": False, "group": None, "key": None}
        i = 34
        i += 1 + b[i]                          # session id
        info["suite"] = struct.unpack_from("!H", b, i)[0]
        i += 3                                 # suite, compression
        end = i + 2 + struct.unpack_from("!H", b, i)[0] if i + 2 <= len(b) else i
        i += 2
        while i < end:
            kind, length = struct.unpack_from("!HH", b, i)
            body = b[i + 4:i + 4 + length]
            if kind == 43:
                info["version"] = struct.unpack("!H", body)[0]
            elif kind == 51:
                info["group"] = struct.unpack_from("!H", body)[0]
                if not info["hrr"]:
                    info["key"] = body[4:4 + struct.unpack_from("!H", body, 2)[0]]
            elif kind == 44:
                info["cookie"] = body
            elif kind == 23:
                info["ems"] = True
            elif kind == 16 and len(body) > 3:
                self.selected_alpn = body[3:3 + body[2]].decode()
            i += 4 + length
        if info["hrr"]:
            return info
        if info["version"] == 0x0304:
            if info["suite"] not in TLS13_SUITES:
                raise SSLError("server chose cipher %#x" % info["suite"])
            if not info["key"]:
                raise SSLError("no key share from server")
        elif info["version"] == 0x0303:
            if info["random"][-8:] == DOWNGRADE:
                raise SSLError("a TLS 1.3 server answered with 1.2: someone is in the middle")
            if info["suite"] not in TLS12_SUITES:
                raise SSLError("server chose cipher %#x" % info["suite"])
        else:
            raise SSLError("server speaks neither TLS 1.3 nor 1.2")
        return info

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
        if alg in (0x0401, 0x0501, 0x0601):
            raise SSLCertVerificationError("PKCS#1 v1.5 signatures are not allowed in TLS 1.3")
        self._check_signature(chain[0].key, alg, content, sig)

    def _check_signature(self, key, alg, content, sig):
        from crypto import ec, rsa
        ok = False
        if alg in (0x0403, 0x0503) and key[0] == "ec":
            hashname = "sha256" if alg == 0x0403 else "sha384"
            r, s = x509.decode_ecdsa_sig(sig)
            ok = ec.verify(key[1], key[2], crypto.digest(hashname, content), r, s)
        elif alg in (0x0804, 0x0805, 0x0806) and key[0] == "rsa":
            hashname = {0x0804: "sha256", 0x0805: "sha384", 0x0806: "sha512"}[alg]
            ok = rsa.verify_pss(key[1], key[2], hashname, crypto.digest(hashname, content), sig)
        elif alg in (0x0401, 0x0501, 0x0601) and key[0] == "rsa":
            hashname = {0x0401: "sha256", 0x0501: "sha384", 0x0601: "sha512"}[alg]
            ok = rsa.verify_pkcs1(key[1], key[2], hashname, crypto.digest(hashname, content), sig)
        if not ok:
            raise SSLCertVerificationError("the server's signature is wrong (alg %#x)" % alg)

    def _post_handshake(self, body):
        i = 0
        while i + 4 <= len(body):
            kind = body[i]
            length = int.from_bytes(body[i + 1:i + 4], "big")
            if kind == KEY_UPDATE:
                k = self._read_keys
                self._read_keys = k.again(_expand_label(k.secret, b"traffic upd", b"", 32))
                if body[i + 4] == 1:           # update_requested
                    self._send_record(HANDSHAKE, bytes([KEY_UPDATE, 0, 0, 1, 0]))
                    w = self._write_keys
                    self._write_keys = w.again(_expand_label(w.secret, b"traffic upd", b"", 32))
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
