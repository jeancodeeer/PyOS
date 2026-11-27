# ChaCha20-Poly1305 (RFC 8439): the AEAD cipher TLS 1.3 uses here.
#
# The ChaCha20 block function is compiled to machine code by MicroPython's
# viper emitter (32-bit unsigned arithmetic on raw arrays); Poly1305 uses
# Python's big integers.
import struct
from kernel import arch as _arch   # ARM64: C versions of the viper functions
import micropython
from array import array

_SIGMA = (0x61707865, 0x3320646e, 0x79622d32, 0x6b206574)


_QR = bytes((0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15,
             0, 5, 10, 15, 1, 6, 11, 12, 2, 7, 8, 13, 3, 4, 9, 14))


@micropython.viper
def _rounds(x: ptr32, s: ptr32, qr: ptr8):
    for i in range(16):
        x[i] = s[i]
    for _ in range(10):
        for q in range(8):
            a = qr[4 * q]
            b = qr[4 * q + 1]
            c = qr[4 * q + 2]
            d = qr[4 * q + 3]
            m = uint(0xFFFFFFFF)                 # viper integers are 64-bit: wrap by hand
            xa = (uint(x[a]) + uint(x[b])) & m
            xd = uint(x[d]) ^ xa
            xd = ((xd << 16) | (xd >> 16)) & m
            xc = (uint(x[c]) + xd) & m
            xb = uint(x[b]) ^ xc
            xb = ((xb << 12) | (xb >> 20)) & m
            xa = (xa + xb) & m
            xd = xd ^ xa
            xd = ((xd << 8) | (xd >> 24)) & m
            xc = (xc + xd) & m
            xb = xb ^ xc
            xb = ((xb << 7) | (xb >> 25)) & m
            x[a] = xa
            x[b] = xb
            x[c] = xc
            x[d] = xd
    for i in range(16):
        x[i] = uint(x[i]) + uint(s[i])
_rounds = _arch.fast(_rounds, 'chacha_rounds')


@micropython.viper
def _xor(out: ptr8, data: ptr8, ks: ptr8, off: int, n: int):
    for i in range(n):
        out[off + i] = data[off + i] ^ ks[i]
_xor = _arch.fast(_xor, 'chacha_xor')


def chacha20(key, counter, nonce, data):
    state = array("I", _SIGMA + struct.unpack("<8I", key) + (counter,) + struct.unpack("<3I", nonce))
    block = array("I", [0] * 16)
    out = bytearray(len(data))
    data = bytes(data)
    for off in range(0, len(data), 64):
        _rounds(block, state, _QR)
        n = min(64, len(data) - off)
        _xor(out, data, block, off, n)
        state[12] = (state[12] + 1) & 0xFFFFFFFF
    return bytes(out)


_P1305 = (1 << 130) - 5


def poly1305(key, msg):
    r = int.from_bytes(key[:16], "little") & 0x0ffffffc0ffffffc0ffffffc0fffffff
    s = int.from_bytes(key[16:32], "little")
    acc = 0
    msg = bytes(msg)
    for i in range(0, len(msg), 16):
        block = msg[i:i + 16] + b"\x01"
        acc = (acc + int.from_bytes(block, "little")) * r % _P1305
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _pad16(n):
    return bytes(-n % 16)


def _mac_data(aad, ct):
    return aad + _pad16(len(aad)) + ct + _pad16(len(ct)) + struct.pack("<QQ", len(aad), len(ct))


def seal(key, nonce, plaintext, aad=b""):
    otk = chacha20(key, 0, nonce, bytes(32))
    ct = chacha20(key, 1, nonce, plaintext)
    return ct + poly1305(otk, _mac_data(aad, ct))


def open_(key, nonce, sealed, aad=b""):
    ct, tag = sealed[:-16], sealed[-16:]
    otk = chacha20(key, 0, nonce, bytes(32))
    if poly1305(otk, _mac_data(aad, ct)) != tag:
        raise ValueError("bad record MAC")
    return chacha20(key, 1, nonce, ct)
