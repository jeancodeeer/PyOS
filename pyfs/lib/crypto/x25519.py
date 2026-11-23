# X25519 key agreement (RFC 7748): the Montgomery ladder on Curve25519,
# with Python's big integers doing the field arithmetic modulo 2^255 - 19.
_P = (1 << 255) - 19
_A24 = 121665


def _decode_scalar(k):
    k = bytearray(k)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    return int.from_bytes(k, "little")


def scalarmult(k, u):
    k = _decode_scalar(k)
    x1 = int.from_bytes(u, "little") & ((1 << 255) - 1)
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    p = _P
    for t in range(254, -1, -1):
        bit = (k >> t) & 1
        swap ^= bit
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = bit
        a = x2 + z2
        aa = a * a % p
        b = x2 - z2
        bb = b * b % p
        e = aa - bb
        c = x3 + z3
        d = x3 - z3
        da = d * a % p
        cb = c * b % p
        x3 = (da + cb) ** 2 % p
        z3 = x1 * (da - cb) ** 2 % p
        x2 = aa * bb % p
        z2 = e * (aa + _A24 * e) % p
    if swap:
        x2, z2 = x3, z3
    return (x2 * pow(z2, p - 2, p) % p).to_bytes(32, "little")


BASE = (9).to_bytes(32, "little")


def keypair(random_bytes):
    private = random_bytes(32)
    return private, scalarmult(private, BASE)
