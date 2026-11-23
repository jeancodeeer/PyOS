# ECDSA signature verification on the NIST curves P-256 and P-384, with
# points in Jacobian coordinates and Python's big integers.
from crypto import bit_length

CURVES = {
    "P-256": dict(
        p=0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff,
        a=-3,
        b=0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b,
        n=0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551,
        gx=0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
        gy=0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5, size=32),
    "P-384": dict(
        p=0xfffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffeffffffff0000000000000000ffffffff,
        a=-3,
        b=0xb3312fa7e23ee7e4988e056be3f82d19181d9c6efe8141120314088f5013875ac656398d8a2ed19d2a85c8edd3ec2aef,
        n=0xffffffffffffffffffffffffffffffffffffffffffffffffc7634d81f4372ddf581a0db248b0a77aecec196accc52973,
        gx=0xaa87ca22be8b05378eb1c71ef320ad746e1d3b628ba79b9859f741e082542a385502f25dbf55296c3a545e3872760ab7,
        gy=0x3617de4a96262c6f5d9e98bf9292dc29f8f41dbd289a147ce9da3113b5f0b8c00a60b1ce1d7e819d7a431d7c90ea0e5f, size=48),
}
OIDS = {"1.2.840.10045.3.1.7": "P-256", "1.3.132.0.34": "P-384"}


def _double(P, c):
    x, y, z = P
    if not y:
        return (0, 1, 0)
    p = c["p"]
    ysq = y * y % p
    s = 4 * x * ysq % p
    zz = z * z % p
    m = 3 * (x - zz) * (x + zz) % p          # a = -3
    nx = (m * m - 2 * s) % p
    ny = (m * (s - nx) - 8 * ysq * ysq) % p
    nz = 2 * y * z % p
    return (nx, ny, nz)


def _add(P, Q, c):
    if not P[2]:
        return Q
    if not Q[2]:
        return P
    p = c["p"]
    x1, y1, z1 = P
    x2, y2, z2 = Q
    z1z1, z2z2 = z1 * z1 % p, z2 * z2 % p
    u1, u2 = x1 * z2z2 % p, x2 * z1z1 % p
    s1, s2 = y1 * z2 * z2z2 % p, y2 * z1 * z1z1 % p
    if u1 == u2:
        return _double(P, c) if s1 == s2 else (0, 1, 0)
    h, r = (u2 - u1) % p, (s2 - s1) % p
    hh = h * h % p
    hhh = h * hh % p
    v = u1 * hh % p
    nx = (r * r - hhh - 2 * v) % p
    ny = (r * (v - nx) - s1 * hhh) % p
    nz = h * z1 * z2 % p
    return (nx, ny, nz)


def _mul2(k1, P, k2, Q, c):
    """k1*P + k2*Q (Shamir's trick)."""
    PQ = _add(P, Q, c)
    R = (0, 1, 0)
    for i in range(max(bit_length(k1), bit_length(k2)) - 1, -1, -1):
        R = _double(R, c)
        b1, b2 = (k1 >> i) & 1, (k2 >> i) & 1
        if b1 and b2:
            R = _add(R, PQ, c)
        elif b1:
            R = _add(R, P, c)
        elif b2:
            R = _add(R, Q, c)
    return R


def _affine(P, c):
    p = c["p"]
    zi = pow(P[2], p - 2, p)
    return P[0] * zi * zi % p, P[1] * zi * zi * zi % p


def decode_point(curve, data):
    c = CURVES[curve]
    if data[0] != 4:
        raise ValueError("only uncompressed points")
    size = c["size"]
    return int.from_bytes(data[1:1 + size], "big"), int.from_bytes(data[1 + size:], "big")


def verify(curve, public, digest, r, s):
    """public: (x, y). digest: bytes of the message hash."""
    c = CURVES[curve]
    n = c["n"]
    if not (0 < r < n and 0 < s < n):
        return False
    e = int.from_bytes(digest, "big")
    if len(digest) * 8 > bit_length(n):
        e >>= len(digest) * 8 - bit_length(n)
    w = pow(s, n - 2, n)
    u1, u2 = e * w % n, r * w % n
    R = _mul2(u1, (c["gx"], c["gy"], 1), u2, (public[0], public[1], 1), c)
    if not R[2]:
        return False
    return _affine(R, c)[0] % n == r
