# Cryptography for TLS, in Python: hashes, MACs, ciphers, key exchange and
# signatures. Nothing here is constant-time; it is written to be read.
#
#   crypto.sha256, crypto.sha384, crypto.sha512     hash constructors
#   crypto.hmac(hashname, key, data), crypto.hkdf_*  key derivation
#   crypto.chacha, crypto.x25519, crypto.ec, crypto.rsa
import hashlib
import _kernel

sha256 = hashlib.sha256


def random_bytes(n):
    """Random bytes from RDRAND when the CPU has it, mixed with the TSC."""
    out = bytearray()
    seed = hashlib.sha256(_kernel.rdtsc().to_bytes(8, "little") + _rdrand_bytes(32))
    counter = 0
    while len(out) < n:
        h = hashlib.sha256(seed.digest() + counter.to_bytes(4, "little") +
                           _kernel.rdtsc().to_bytes(8, "little") + _rdrand_bytes(8))
        out += h.digest()
        counter += 1
    return bytes(out[:n])


_RDRAND = None


def _rdrand_bytes(n):
    global _RDRAND
    if _RDRAND is None:
        _RDRAND = bool(_kernel.cpuid(1)[2] & (1 << 30))
        if _RDRAND:
            from kernel.hw import dma_buffer
            # rdrand rax; jnc retry; ret     (48 0F C7 F0 73 FA C3)
            global _code, _code_addr
            _code, view, _code_addr = dma_buffer(16, 16)
            view[:7] = b"\x48\x0f\xc7\xf0\x73\xfa\xc3"
    if not _RDRAND:
        return b""
    out = b""
    while len(out) < n:
        out += _kernel.call(_code_addr).to_bytes(8, "little")
    return out[:n]


# ---- SHA-512 / SHA-384 (hashlib only has SHA-256 here) ----

_K512 = [
    0x428a2f98d728ae22, 0x7137449123ef65cd, 0xb5c0fbcfec4d3b2f, 0xe9b5dba58189dbbc, 0x3956c25bf348b538,
    0x59f111f1b605d019, 0x923f82a4af194f9b, 0xab1c5ed5da6d8118, 0xd807aa98a3030242, 0x12835b0145706fbe,
    0x243185be4ee4b28c, 0x550c7dc3d5ffb4e2, 0x72be5d74f27b896f, 0x80deb1fe3b1696b1, 0x9bdc06a725c71235,
    0xc19bf174cf692694, 0xe49b69c19ef14ad2, 0xefbe4786384f25e3, 0x0fc19dc68b8cd5b5, 0x240ca1cc77ac9c65,
    0x2de92c6f592b0275, 0x4a7484aa6ea6e483, 0x5cb0a9dcbd41fbd4, 0x76f988da831153b5, 0x983e5152ee66dfab,
    0xa831c66d2db43210, 0xb00327c898fb213f, 0xbf597fc7beef0ee4, 0xc6e00bf33da88fc2, 0xd5a79147930aa725,
    0x06ca6351e003826f, 0x142929670a0e6e70, 0x27b70a8546d22ffc, 0x2e1b21385c26c926, 0x4d2c6dfc5ac42aed,
    0x53380d139d95b3df, 0x650a73548baf63de, 0x766a0abb3c77b2a8, 0x81c2c92e47edaee6, 0x92722c851482353b,
    0xa2bfe8a14cf10364, 0xa81a664bbc423001, 0xc24b8b70d0f89791, 0xc76c51a30654be30, 0xd192e819d6ef5218,
    0xd69906245565a910, 0xf40e35855771202a, 0x106aa07032bbd1b8, 0x19a4c116b8d2d0c8, 0x1e376c085141ab53,
    0x2748774cdf8eeb99, 0x34b0bcb5e19b48a8, 0x391c0cb3c5c95a63, 0x4ed8aa4ae3418acb, 0x5b9cca4f7763e373,
    0x682e6ff3d6b2b8a3, 0x748f82ee5defb2fc, 0x78a5636f43172f60, 0x84c87814a1f0ab72, 0x8cc702081a6439ec,
    0x90befffa23631e28, 0xa4506cebde82bde9, 0xbef9a3f7b2c67915, 0xc67178f2e372532b, 0xca273eceea26619c,
    0xd186b8c721c0c207, 0xeada7dd6cde0eb1e, 0xf57d4f7fee6ed178, 0x06f067aa72176fba, 0x0a637dc5a2c898a6,
    0x113f9804bef90dae, 0x1b710b35131c471b, 0x28db77f523047d84, 0x32caab7b40c72493, 0x3c9ebe0a15c9bebc,
    0x431d67c49c100d4c, 0x4cc5d4becb3e42b6, 0x597f299cfc657e2a, 0x5fcb6fab3ad6faec, 0x6c44198c4a475817]
_M64 = (1 << 64) - 1


def _ror(x, n):
    return ((x >> n) | (x << (64 - n))) & _M64


class _SHA512:
    digest_size, block_size = 64, 128
    IV = [0x6a09e667f3bcc908, 0xbb67ae8584caa73b, 0x3c6ef372fe94f82b, 0xa54ff53a5f1d36f1,
          0x510e527fade682d1, 0x9b05688c2b3e6c1f, 0x1f83d9abfb41bd6b, 0x5be0cd19137e2179]

    def __init__(self, data=b""):
        self.h = list(self.IV)
        self.buf = b""
        self.length = 0
        self.update(data)

    def copy(self):
        c = self.__class__()
        c.h, c.buf, c.length = list(self.h), self.buf, self.length
        return c

    def update(self, data):
        data = self.buf + bytes(data)
        self.length += len(data) - len(self.buf)
        n = len(data) // 128 * 128
        for i in range(0, n, 128):
            self._block(data[i:i + 128])
        self.buf = data[n:]

    def _block(self, block):
        w = [int.from_bytes(block[i:i + 8], "big") for i in range(0, 128, 8)]
        for t in range(16, 80):
            a, b = w[t - 15], w[t - 2]
            s0 = _ror(a, 1) ^ _ror(a, 8) ^ (a >> 7)
            s1 = _ror(b, 19) ^ _ror(b, 61) ^ (b >> 6)
            w.append((w[t - 16] + s0 + w[t - 7] + s1) & _M64)
        a, b, c, d, e, f, g, h = self.h
        for t in range(80):
            t1 = (h + (_ror(e, 14) ^ _ror(e, 18) ^ _ror(e, 41)) + ((e & f) ^ (~e & g)) + _K512[t] + w[t]) & _M64
            t2 = ((_ror(a, 28) ^ _ror(a, 34) ^ _ror(a, 39)) + ((a & b) ^ (a & c) ^ (b & c))) & _M64
            h, g, f, e, d, c, b, a = g, f, e, (d + t1) & _M64, c, b, a, (t1 + t2) & _M64
        self.h = [(x + y) & _M64 for x, y in zip(self.h, (a, b, c, d, e, f, g, h))]

    def digest(self):
        c = self.copy()
        bits = c.length * 8
        pad = b"\x80" + bytes((111 - c.length) % 128) + bits.to_bytes(16, "big")
        c.update(pad)
        return b"".join(x.to_bytes(8, "big") for x in c.h)[:self.digest_size]

    def hexdigest(self):
        return self.digest().hex()


class _SHA384(_SHA512):
    digest_size = 48
    IV = [0xcbbb9d5dc1059ed8, 0x629a292a367cd507, 0x9159015a3070dd17, 0x152fecd8f70e5939,
          0x67332667ffc00b31, 0x8eb44a8768581511, 0xdb0c2e0d64f98fa7, 0x47b5481dbefa4fa4]


sha512 = _SHA512
sha384 = _SHA384


class _SHA256:
    """hashlib.sha256 with copy() (MicroPython's has none): keeps the data."""
    digest_size, block_size = 32, 64

    def __init__(self, data=b""):
        self.data = bytearray(data)

    def update(self, data):
        self.data += data

    def copy(self):
        return _SHA256(self.data)

    def digest(self):
        return hashlib.sha256(self.data).digest()

    def hexdigest(self):
        return self.digest().hex()


HASHES = {"sha256": _SHA256, "sha384": _SHA384, "sha512": _SHA512}


def digest(name, data):
    if name == "sha256":
        return hashlib.sha256(data).digest()
    return HASHES[name](data).digest()


def hmac(name, key, data):
    h = HASHES[name]
    block = h.block_size
    if len(key) > block:
        key = digest(name, key)
    key = bytes(key) + bytes(block - len(key))
    inner = digest(name, bytes(b ^ 0x36 for b in key) + bytes(data))
    return digest(name, bytes(b ^ 0x5C for b in key) + inner)


def hkdf_extract(name, salt, ikm):
    return hmac(name, salt or bytes(HASHES[name].digest_size), ikm)


def hkdf_expand(name, prk, info, length):
    out, t, i = b"", b"", 1
    while len(out) < length:
        t = hmac(name, prk, t + info + bytes([i]))
        out += t
        i += 1
    return out[:length]


def bit_length(n):
    """int.bit_length(), which MicroPython does not have."""
    if n < 0:
        n = -n
    if not n:
        return 0
    h = "%x" % n
    return (len(h) - 1) * 4 + (4 if h[0] >= "8" else 3 if h[0] >= "4" else 2 if h[0] >= "2" else 1)
