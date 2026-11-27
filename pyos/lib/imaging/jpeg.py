# Baseline JPEG decoder: Huffman decoding in Python, the inverse DCT and the
# colour conversion compiled by MicroPython's viper emitter.
# Supports 8-bit baseline (SOF0/SOF1), grayscale or YCbCr, any subsampling,
# restart markers. Progressive JPEGs raise ValueError.
import micropython
from kernel import arch as _arch   # ARM64: C versions of the viper functions
from array import array
import pygame

ZIGZAG = bytes((0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6,
                7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38,
                31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63))


@micropython.viper
def _idct(blk: ptr32, out: ptr8, stride: int, off: int):
    """Integer inverse DCT of 64 coefficients (stb_image style), writes 8x8 bytes."""
    tmp = blk
    for i in range(8):
        s0 = int(tmp[i]); s1 = int(tmp[8 + i]); s2 = int(tmp[16 + i]); s3 = int(tmp[24 + i])
        s4 = int(tmp[32 + i]); s5 = int(tmp[40 + i]); s6 = int(tmp[48 + i]); s7 = int(tmp[56 + i])
        if s0 & 0x80000000:
            s0 -= 0x100000000
        if s1 & 0x80000000:
            s1 -= 0x100000000
        if s2 & 0x80000000:
            s2 -= 0x100000000
        if s3 & 0x80000000:
            s3 -= 0x100000000
        if s4 & 0x80000000:
            s4 -= 0x100000000
        if s5 & 0x80000000:
            s5 -= 0x100000000
        if s6 & 0x80000000:
            s6 -= 0x100000000
        if s7 & 0x80000000:
            s7 -= 0x100000000
        p2 = s2; p3 = s6
        p1 = (p2 + p3) * 2217
        t2 = p1 + p3 * (-7567)
        t3 = p1 + p2 * 3135
        p2 = s0; p3 = s4
        t0 = (p2 + p3) * 4096
        t1 = (p2 - p3) * 4096
        x0 = t0 + t3; x3 = t0 - t3; x1 = t1 + t2; x2 = t1 - t2
        t0 = s7; t1 = s5; t2 = s3; t3 = s1
        p3 = t0 + t2; p4 = t1 + t3; p1 = t0 + t3; p2 = t1 + t2
        p5 = (p3 + p4) * 4816
        t0 = t0 * 1223; t1 = t1 * 8410; t2 = t2 * 12586; t3 = t3 * 6149
        p1 = p5 + p1 * (-3685); p2 = p5 + p2 * (-10497); p3 = p3 * (-8034); p4 = p4 * (-1597)
        t3 += p1 + p4; t2 += p2 + p3; t1 += p2 + p4; t0 += p1 + p3
        x0 += 512; x1 += 512; x2 += 512; x3 += 512
        tmp[i] = (x0 + t3) >> 10
        tmp[56 + i] = (x0 - t3) >> 10
        tmp[8 + i] = (x1 + t2) >> 10
        tmp[48 + i] = (x1 - t2) >> 10
        tmp[16 + i] = (x2 + t1) >> 10
        tmp[40 + i] = (x2 - t1) >> 10
        tmp[24 + i] = (x3 + t0) >> 10
        tmp[32 + i] = (x3 - t0) >> 10
    for r in range(8):
        b = r * 8
        s0 = int(tmp[b]); s1 = int(tmp[b + 1]); s2 = int(tmp[b + 2]); s3 = int(tmp[b + 3])
        s4 = int(tmp[b + 4]); s5 = int(tmp[b + 5]); s6 = int(tmp[b + 6]); s7 = int(tmp[b + 7])
        if s0 & 0x80000000:
            s0 -= 0x100000000
        if s1 & 0x80000000:
            s1 -= 0x100000000
        if s2 & 0x80000000:
            s2 -= 0x100000000
        if s3 & 0x80000000:
            s3 -= 0x100000000
        if s4 & 0x80000000:
            s4 -= 0x100000000
        if s5 & 0x80000000:
            s5 -= 0x100000000
        if s6 & 0x80000000:
            s6 -= 0x100000000
        if s7 & 0x80000000:
            s7 -= 0x100000000
        p2 = s2; p3 = s6
        p1 = (p2 + p3) * 2217
        t2 = p1 + p3 * (-7567)
        t3 = p1 + p2 * 3135
        p2 = s0; p3 = s4
        t0 = (p2 + p3) * 4096
        t1 = (p2 - p3) * 4096
        x0 = t0 + t3; x3 = t0 - t3; x1 = t1 + t2; x2 = t1 - t2
        t0 = s7; t1 = s5; t2 = s3; t3 = s1
        p3 = t0 + t2; p4 = t1 + t3; p1 = t0 + t3; p2 = t1 + t2
        p5 = (p3 + p4) * 4816
        t0 = t0 * 1223; t1 = t1 * 8410; t2 = t2 * 12586; t3 = t3 * 6149
        p1 = p5 + p1 * (-3685); p2 = p5 + p2 * (-10497); p3 = p3 * (-8034); p4 = p4 * (-1597)
        t3 += p1 + p4; t2 += p2 + p3; t1 += p2 + p4; t0 += p1 + p3
        bias = 65536 + (128 << 17)
        x0 += bias; x1 += bias; x2 += bias; x3 += bias
        vals0 = (x0 + t3) >> 17
        vals7 = (x0 - t3) >> 17
        vals1 = (x1 + t2) >> 17
        vals6 = (x1 - t2) >> 17
        vals2 = (x2 + t1) >> 17
        vals5 = (x2 - t1) >> 17
        vals3 = (x3 + t0) >> 17
        vals4 = (x3 - t0) >> 17
        o = off + r * stride
        out[o] = 0 if vals0 < 0 else (255 if vals0 > 255 else vals0)
        out[o + 1] = 0 if vals1 < 0 else (255 if vals1 > 255 else vals1)
        out[o + 2] = 0 if vals2 < 0 else (255 if vals2 > 255 else vals2)
        out[o + 3] = 0 if vals3 < 0 else (255 if vals3 > 255 else vals3)
        out[o + 4] = 0 if vals4 < 0 else (255 if vals4 > 255 else vals4)
        out[o + 5] = 0 if vals5 < 0 else (255 if vals5 > 255 else vals5)
        out[o + 6] = 0 if vals6 < 0 else (255 if vals6 > 255 else vals6)
        out[o + 7] = 0 if vals7 < 0 else (255 if vals7 > 255 else vals7)
_idct = _arch.fast(_idct, 'jpeg_idct')


@micropython.viper
def _ycc(dst: ptr8, y: ptr8, cb: ptr8, cr: ptr8, w: int, h: int, ystride: int, cstride: int, hs: int, vs: int):
    """YCbCr planes -> BGRA pixels. hs/vs: chroma subsampling shifts."""
    for row in range(h):
        yo = row * ystride
        co = (row >> vs) * cstride
        d = row * w * 4
        for col in range(w):
            yy = int(y[yo + col]) << 16
            b = int(cb[co + (col >> hs)]) - 128
            r = int(cr[co + (col >> hs)]) - 128
            R = (yy + r * 91881 + 32768) >> 16
            G = (yy - b * 22554 - r * 46802 + 32768) >> 16
            B = (yy + b * 116130 + 32768) >> 16
            dst[d] = 0 if B < 0 else (255 if B > 255 else B)
            dst[d + 1] = 0 if G < 0 else (255 if G > 255 else G)
            dst[d + 2] = 0 if R < 0 else (255 if R > 255 else R)
            dst[d + 3] = 255
            d += 4
_ycc = _arch.fast(_ycc, 'jpeg_ycc')


@micropython.viper
def _gray(dst: ptr8, y: ptr8, w: int, h: int, ystride: int):
    for row in range(h):
        yo = row * ystride
        d = row * w * 4
        for col in range(w):
            v = y[yo + col]
            dst[d] = v
            dst[d + 1] = v
            dst[d + 2] = v
            dst[d + 3] = 255
            d += 4
_gray = _arch.fast(_gray, 'jpeg_gray')


class _Bits:
    def __init__(self, data, pos):
        self.data, self.pos = data, pos
        self.acc, self.n = 0, 0

    def fill(self):
        data = self.data
        while self.n <= 24:
            b = 0
            if self.pos < len(data):
                b = data[self.pos]
                if b == 0xFF:
                    nxt = data[self.pos + 1] if self.pos + 1 < len(data) else 0
                    if nxt == 0:
                        self.pos += 2
                    else:
                        b = 0                 # a marker: feed zeros
                else:
                    self.pos += 1
            self.acc = (self.acc << 8) | b
            self.n += 8

    def bits(self, k):
        if not k:
            return 0
        if self.n < k:
            self.fill()
        self.n -= k
        v = (self.acc >> self.n) & ((1 << k) - 1)
        self.acc &= (1 << self.n) - 1
        return v

    def huff(self, table):
        lookup, maxlen = table
        code = 0
        for length in range(1, maxlen + 1):
            code = (code << 1) | self.bits(1)
            v = lookup.get((length << 16) | code)
            if v is not None:
                return v
        raise ValueError("bad Huffman code")

    def restart(self):
        self.acc = self.n = 0
        data = self.data
        while self.pos + 1 < len(data) and not (data[self.pos] == 0xFF and 0xD0 <= data[self.pos + 1] <= 0xD7):
            self.pos += 1
        self.pos += 2


def _extend(v, k):
    return v - (1 << k) + 1 if k and v < (1 << (k - 1)) else v


def decode(data):
    data = bytes(data)
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    qt, ht, comps = {}, {}, []
    w = h = 0
    restart = 0
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        length = (data[i] << 8) | data[i + 1]
        seg = data[i + 2:i + length]
        if marker == 0xDB:                                   # quantisation tables
            j = 0
            while j < len(seg):
                pq, tq = seg[j] >> 4, seg[j] & 15
                if pq:
                    qt[tq] = [(seg[j + 1 + 2 * k] << 8) | seg[j + 2 + 2 * k] for k in range(64)]
                    j += 129
                else:
                    qt[tq] = list(seg[j + 1:j + 65])
                    j += 65
        elif marker == 0xC4:                                 # Huffman tables
            j = 0
            while j < len(seg):
                tc, th = seg[j] >> 4, seg[j] & 15
                counts = seg[j + 1:j + 17]
                symbols = seg[j + 17:j + 17 + sum(counts)]
                lookup, code, k = {}, 0, 0
                for length in range(1, 17):
                    for _ in range(counts[length - 1]):
                        lookup[(length << 16) | code] = symbols[k]
                        code += 1
                        k += 1
                    code <<= 1
                maxlen = max([n + 1 for n in range(16) if counts[n]] or [1])
                ht[(tc, th)] = (lookup, maxlen)
                j += 17 + sum(counts)
        elif marker in (0xC0, 0xC1):
            h, w = (seg[1] << 8) | seg[2], (seg[3] << 8) | seg[4]
            for k in range(seg[5]):
                c = seg[6 + 3 * k:9 + 3 * k]
                comps.append({"id": c[0], "h": c[1] >> 4, "v": c[1] & 15, "q": c[2]})
        elif marker in (0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            raise ValueError("progressive or lossless JPEG is not supported")
        elif marker == 0xDD:
            restart = (seg[0] << 8) | seg[1]
        elif marker == 0xDA:                                 # start of scan
            n = seg[0]
            for k in range(n):
                cid, tables = seg[1 + 2 * k], seg[2 + 2 * k]
                for c in comps:
                    if c["id"] == cid:
                        c["dc"], c["ac"] = ht[(0, tables >> 4)], ht[(1, tables & 15)]
            return _scan(data, i + length, w, h, comps, qt, restart)
        elif marker == 0xD9:
            break
        i += length
    raise ValueError("JPEG without image data")


def _scan(data, pos, w, h, comps, qt, restart):
    hmax = max(c["h"] for c in comps)
    vmax = max(c["v"] for c in comps)
    mcux, mcuy = 8 * hmax, 8 * vmax
    mx, my = (w + mcux - 1) // mcux, (h + mcuy - 1) // mcuy
    for c in comps:
        c["stride"] = mx * c["h"] * 8
        c["plane"] = bytearray(c["stride"] * my * c["v"] * 8)
        c["pred"] = 0
        q = qt[c["q"]]
        c["qz"] = [0] * 64
        for k in range(64):
            c["qz"][ZIGZAG[k]] = q[k]
    bits = _Bits(data, pos)
    blk = array("i", [0] * 64)
    zz = ZIGZAG
    count = 0
    for by in range(my):
        for bx in range(mx):
            if restart and count and count % restart == 0:
                bits.restart()
                for c in comps:
                    c["pred"] = 0
            count += 1
            for c in comps:
                q = c["qz"]
                for v in range(c["v"]):
                    for u in range(c["h"]):
                        for k in range(64):
                            blk[k] = 0
                        t = bits.huff(c["dc"])
                        diff = _extend(bits.bits(t), t)
                        c["pred"] += diff
                        blk[0] = c["pred"] * q[0]
                        k = 1
                        while k < 64:
                            rs = bits.huff(c["ac"])
                            r, s = rs >> 4, rs & 15
                            if s == 0:
                                if r != 15:
                                    break
                                k += 16
                                continue
                            k += r
                            if k > 63:
                                break
                            z = zz[k]
                            blk[z] = _extend(bits.bits(s), s) * q[z]
                            k += 1
                        x0 = (bx * c["h"] + u) * 8
                        y0 = (by * c["v"] + v) * 8
                        _idct(blk, c["plane"], c["stride"], y0 * c["stride"] + x0)
    surf = pygame.Surface((w, h))
    if len(comps) == 1:
        _gray(surf._buf, comps[0]["plane"], w, h, comps[0]["stride"])
    else:
        y, cb, cr = comps[0], comps[1], comps[2]
        hs = {1: 0, 2: 1, 4: 2}.get(hmax // cb["h"], 0)
        vs = {1: 0, 2: 1, 4: 2}.get(vmax // cb["v"], 0)
        _ycc(surf._buf, y["plane"], cb["plane"], cr["plane"], w, h, y["stride"], cb["stride"], hs, vs)
    return surf


def load(path):
    with open(path, "rb") as f:
        return decode(f.read())
