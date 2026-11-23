# RSA signature verification: PKCS#1 v1.5 and PSS (RFC 8017).
from crypto import digest, HASHES, bit_length

_DIGEST_INFO = {
    "sha256": bytes.fromhex("3031300d060960864801650304020105000420"),
    "sha384": bytes.fromhex("3041300d060960864801650304020205000430"),
    "sha512": bytes.fromhex("3051300d060960864801650304020305000440"),
}


def _em(n, e, signature):
    k = (bit_length(n) + 7) // 8
    s = int.from_bytes(signature, "big")
    if s >= n:
        return None, k
    return pow(s, e, n).to_bytes(k, "big"), k


def verify_pkcs1(n, e, hashname, message_digest, signature):
    em, k = _em(n, e, signature)
    if em is None:
        return False
    t = _DIGEST_INFO[hashname] + message_digest
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return em == expected


def _mgf1(hashname, seed, length):
    out, i = b"", 0
    while len(out) < length:
        out += digest(hashname, seed + i.to_bytes(4, "big"))
        i += 1
    return out[:length]


def verify_pss(n, e, hashname, message_digest, signature):
    em, k = _em(n, e, signature)
    if em is None:
        return False
    hlen = HASHES[hashname].digest_size
    embits = bit_length(n) - 1
    emlen = (embits + 7) // 8
    em = em[-emlen:]
    if em[-1] != 0xBC:
        return False
    masked, h = em[:emlen - hlen - 1], em[emlen - hlen - 1:-1]
    db = bytearray(a ^ b for a, b in zip(masked, _mgf1(hashname, h, len(masked))))
    db[0] &= 0xFF >> (8 * emlen - embits)
    i = 0
    while i < len(db) and db[i] == 0:
        i += 1
    if i >= len(db) or db[i] != 1:
        return False
    salt = bytes(db[i + 1:])
    return digest(hashname, bytes(8) + message_digest + salt) == h
