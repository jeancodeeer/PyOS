# H.264 (ITU-T H.264 / MPEG-4 AVC) in Python: the video of MP4 files and of
# YouTube (format 18). Constrained Baseline and Baseline streams: CAVLC, I and P
# slices, several reference frames (long-term too), explicit weighted
# prediction, the deblocking filter, POC types 0, 1 and 2.
#
#   dec = H264()
#   dec.decode(annexb)            # NAL units after 00 00 01 (SPS, PPS, slices) -> pictures ready
#   dec.size(), dec.crop()        # (w, h) in macroblocks * 16; (x, y, w, h) of the real picture
#   dec.draw(buf, stride, height, x, y, w, h)    # the last picture, scaled into a 32-bit BGRA buffer
from media import h264_tables as T

P_SLICE, B_SLICE, I_SLICE, SP_SLICE, SI_SLICE = 0, 1, 2, 3, 4

ZIGZAG = (0, 1, 4, 8, 5, 2, 3, 6, 9, 12, 13, 10, 7, 11, 14, 15)
BLK_X = (0, 1, 0, 1, 2, 3, 2, 3, 0, 1, 0, 1, 2, 3, 2, 3)        # 4x4 block index -> x, y (in blocks)
BLK_Y = (0, 0, 1, 1, 0, 0, 1, 1, 2, 2, 3, 3, 2, 2, 3, 3)
CBP_INTRA = (47, 31, 15, 0, 23, 27, 29, 30, 7, 11, 13, 14, 39, 43, 45, 46, 16, 3, 5, 10, 12, 19, 21, 26, 28, 35,
             37, 42, 44, 1, 2, 4, 8, 17, 18, 20, 24, 6, 9, 22, 25, 32, 33, 34, 36, 40, 38, 41)
CBP_INTER = (0, 16, 1, 2, 4, 8, 32, 3, 5, 10, 12, 15, 47, 7, 11, 13, 14, 6, 9, 31, 35, 37, 42, 44, 33, 34, 36, 40,
             39, 43, 45, 46, 17, 18, 20, 24, 19, 21, 26, 28, 23, 27, 29, 30, 22, 25, 38, 41)
ALPHA = (0,) * 16 + (4, 4, 5, 6, 7, 8, 9, 10, 12, 13, 15, 17, 20, 22, 25, 28, 32, 36, 40, 45, 50, 56, 63, 71, 80, 90,
                     101, 113, 127, 144, 162, 182, 203, 226, 255, 255)
BETA = (0,) * 16 + (2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14,
                    15, 15, 16, 16, 17, 17, 18, 18)
TC0 = ((0, 0, 0),) * 17 + ((0, 0, 1), (0, 0, 1), (0, 0, 1), (0, 0, 1), (0, 1, 1), (0, 1, 1), (1, 1, 1),
                           (1, 1, 1), (1, 1, 1), (1, 1, 1), (1, 1, 2), (1, 1, 2), (1, 1, 2), (1, 1, 2), (1, 2, 3),
                           (1, 2, 3), (2, 2, 3), (2, 2, 4), (2, 3, 4), (2, 3, 4), (3, 3, 5), (3, 4, 6), (3, 4, 6),
                           (4, 5, 7), (4, 5, 8), (4, 6, 9), (5, 7, 10), (6, 8, 11), (6, 8, 13), (7, 10, 14),
                           (8, 11, 16), (9, 12, 18), (10, 13, 20), (11, 15, 23), (13, 17, 25))


def _dq_tables():
    v = ((10, 16, 13), (11, 18, 14), (13, 20, 16), (14, 23, 18), (16, 25, 20), (18, 29, 23))
    out = []
    for m in range(6):
        row = []
        for pos in range(16):
            r, c = pos >> 2, pos & 3
            row.append(v[m][0] if not (r & 1) and not (c & 1) else v[m][1] if (r & 1) and (c & 1) else v[m][2])
        out.append(row)
    return out


DQ = _dq_tables()                     # DQ[qp % 6][raster position]
CLIP = bytes(min(max(i - 512, 0), 255) for i in range(1536))      # CLIP[v + 512]


class H264Error(ValueError):
    pass


# ---- bits ----

class _Bits:
    def __init__(self, rbsp):
        self.d = rbsp + b"\0\0\0\0\0\0\0\0"
        self.p = 0
        n = len(rbsp)
        while n and rbsp[n - 1] == 0:              # the stop bit: the last 1
            n -= 1
        stop = 0
        if n:
            b = rbsp[n - 1]
            k = 0
            while not (b >> k) & 1:
                k += 1
            stop = n * 8 - 1 - k
        self.stop = stop

    def u(self, n):
        if n == 0:
            return 0
        if n > 24:
            hi = self.u(n - 16)
            return hi << 16 | self.u(16)
        p = self.p
        d = self.d
        i = p >> 3
        v = d[i] << 24 | d[i + 1] << 16 | d[i + 2] << 8 | d[i + 3]
        self.p = p + n
        return (v >> (32 - (p & 7) - n)) & ((1 << n) - 1)

    def peek16(self):
        p = self.p
        d = self.d
        i = p >> 3
        v = d[i] << 24 | d[i + 1] << 16 | d[i + 2] << 8
        return (v >> (16 - (p & 7))) & 0xFFFF

    def bit(self):
        p = self.p
        self.p = p + 1
        return (self.d[p >> 3] >> (7 - (p & 7))) & 1

    def ue(self):
        z = 0
        while not self.bit():
            z += 1
            if z > 31:
                raise H264Error("bad Exp-Golomb code")
        return (1 << z) - 1 + self.u(z)

    def se(self):
        k = self.ue()
        return (k + 1) >> 1 if k & 1 else -(k >> 1)

    def more(self):
        return self.p < self.stop


def _unescape(nal):
    """The RBSP of a NAL unit: without the emulation prevention bytes (00 00 03)."""
    if nal.find(b"\x00\x00\x03") < 0:
        return nal
    return nal.replace(b"\x00\x00\x03", b"\x00\x00")


def nal_units(data):
    """The NAL units of an Annex B stream."""
    data = bytes(data)
    n = len(data)
    i = data.find(b"\x00\x00\x01")
    while 0 <= i < n:
        start = i + 3
        j = data.find(b"\x00\x00\x01", start)
        end = n if j < 0 else j
        k = end
        while k > start and data[k - 1] == 0:     # trailing zeros (and the 00 of 00 00 00 01)
            k -= 1
        if k > start:
            yield data[start:k]
        i = j


# ---- CAVLC (as in h264bsd) ----

def _coeff_token(bits, nc):
    if nc == -1:
        v = T.coeffTokenMinus1_0[bits >> 13]
        return v if v else T.coeffTokenMinus1_1[bits >> 8]
    if nc < 2:
        if bits >= 0x8000:
            return 1
        if bits >= 0x0C00:
            return T.coeffToken0_0[bits >> 10]
        if bits >= 0x0100:
            return T.coeffToken0_1[bits >> 6]
        if bits >= 0x0020:
            return T.coeffToken0_2[(bits >> 2) - 8]
        return T.coeffToken0_3[bits]
    if nc < 4:
        if bits >= 0x8000:
            return 0x0002 if bits & 0x4000 else 0x0822
        if bits >= 0x1000:
            return T.coeffToken2_0[bits >> 10]
        if bits >= 0x0200:
            return T.coeffToken2_1[bits >> 7]
        return T.coeffToken2_2[bits >> 2]
    if nc < 8:
        v = T.coeffToken4_0[bits >> 10]
        return v if v else T.coeffToken4_1[bits >> 6]
    return T.coeffToken8[bits >> 10]


_TZ = (None, None, T.totalZeros_2, T.totalZeros_3, T.totalZeros_4, T.totalZeros_5, T.totalZeros_6,
       T.totalZeros_7, T.totalZeros_8, T.totalZeros_9, T.totalZeros_10, T.totalZeros_11, T.totalZeros_12,
       T.totalZeros_13, T.totalZeros_14)
_TZ_SHIFT = (0, 0, 3, 3, 4, 4, 3, 3, 3, 3, 4, 5, 5, 6, 7)


def _total_zeros(bits9, total, chroma_dc):
    if chroma_dc:
        b = bits9 >> 6
        if b > 3:
            return 0x01
        if total == 3:
            return 0x11
        if b > 1:
            return 0x12
        if total == 2:
            return 0x22
        return 0x23 if b else 0x33
    if total == 1:
        v = T.totalZeros_1_0[bits9 >> 4]
        return v if v else T.totalZeros_1_1[bits9]
    if total == 15:
        return 0x11 if bits9 >> 8 else 0x01
    return _TZ[total][bits9 >> _TZ_SHIFT[total]]


_RB = (None, T.runBefore_1, T.runBefore_2, T.runBefore_3, T.runBefore_4, T.runBefore_5, T.runBefore_6)
_RB_SHIFT = (0, 10, 9, 9, 8, 8, 8)


def _run_before(bits11, zl):
    if zl <= 6:
        return _RB[zl][bits11 >> _RB_SHIFT[zl]]
    if bits11 >= 0x100:
        v = ((7 - (bits11 >> 8)) << 4) + 3
    elif bits11 >= 0x80:
        v = 0x74
    elif bits11 >= 0x40:
        v = 0x85
    elif bits11 >= 0x20:
        v = 0x96
    elif bits11 >= 0x10:
        v = 0xA7
    elif bits11 >= 0x8:
        v = 0xB8
    elif bits11 >= 0x4:
        v = 0xC9
    elif bits11 >= 0x2:
        v = 0xDA
    elif bits11:
        v = 0xEB
    else:
        return 0
    return 0 if (v >> 4) > zl else v


def _residual_block(br, nc, maxc):
    """One CAVLC block -> (total_coeff, levels in scan order (maxc of them) or None)."""
    tok = _coeff_token(br.peek16(), nc)
    if not tok:
        raise H264Error("bad coeff_token")
    br.p += tok & 31
    total = (tok >> 11) & 31
    if total == 0:
        return 0, None
    if total > maxc:
        raise H264Error("too many coefficients")
    t1 = (tok >> 5) & 63
    level = []
    if t1:
        b = br.u(t1)
        m = 1 << (t1 - 1)
        while m:
            level.append(-1 if b & m else 1)
            m >>= 1
    suffix = 1 if total > 10 and t1 < 3 else 0
    for i in range(t1, total):
        bits = br.peek16()
        if not bits:
            raise H264Error("bad level_prefix")
        prefix = 0
        while not (bits & 0x8000):
            bits <<= 1
            prefix += 1
        br.p += prefix + 1
        if prefix < 14:
            n = suffix
        elif prefix == 14:
            n = suffix if suffix else 4
        else:
            if not suffix:
                suffix = 1
            n = 12
        if suffix:
            prefix <<= suffix
        if n:
            prefix += br.u(n)
        code = prefix
        if i == t1 and t1 < 3:
            code += 2
        lv = (code + 2) >> 1
        if suffix == 0:
            suffix = 1
        if lv > (3 << (suffix - 1)) and suffix < 6:
            suffix += 1
        level.append(-lv if code & 1 else lv)
    if total < maxc:
        p = br.p
        d = br.d
        i = p >> 3
        b9 = ((d[i] << 8 | d[i + 1]) >> (7 - (p & 7))) & 0x1FF
        z = _total_zeros(b9, total, maxc == 4)
        if not z:
            raise H264Error("bad total_zeros")
        br.p += z & 15
        zl = z >> 4
    else:
        zl = 0
    out = [0] * maxc
    pos = zl + total - 1
    if pos >= maxc:
        raise H264Error("bad total_zeros")
    # level[0] is the highest frequency; the runs are taken from it down
    for i in range(total - 1):
        out[pos] = level[i]
        if zl > 0:
            p = br.p
            d = br.d
            k = p >> 3
            b11 = ((d[k] << 16 | d[k + 1] << 8 | d[k + 2]) >> (13 - (p & 7))) & 0x7FF
            r = _run_before(b11, zl)
            if not r:
                raise H264Error("bad run_before")
            br.p += r & 15
            run = r >> 4
            zl -= run
            pos -= run + 1
        else:
            pos -= 1
    out[pos] = level[total - 1]
    return total, out


# ---- transforms ----

def _idct_add(c, plane, off, stride):
    """The inverse 4x4 transform of c (16 values, raster order), added to the samples."""
    t = [0] * 16
    for i in range(0, 16, 4):
        d0, d1, d2, d3 = c[i], c[i + 1], c[i + 2], c[i + 3]
        e = d0 + d2
        f = d0 - d2
        g = (d1 >> 1) - d3
        h = d1 + (d3 >> 1)
        t[i] = e + h
        t[i + 1] = f + g
        t[i + 2] = f - g
        t[i + 3] = e - h
    for j in range(4):
        d0, d1, d2, d3 = t[j], t[4 + j], t[8 + j], t[12 + j]
        e = d0 + d2
        f = d0 - d2
        g = (d1 >> 1) - d3
        h = d1 + (d3 >> 1)
        o = off + j
        plane[o] = CLIP[plane[o] + ((e + h + 32) >> 6) + 512]
        o += stride
        plane[o] = CLIP[plane[o] + ((f + g + 32) >> 6) + 512]
        o += stride
        plane[o] = CLIP[plane[o] + ((f - g + 32) >> 6) + 512]
        o += stride
        plane[o] = CLIP[plane[o] + ((e - h + 32) >> 6) + 512]


def _dc_add(dc, plane, off, stride):
    v = (dc + 32) >> 6
    if v:
        for r in range(4):
            o = off + r * stride
            plane[o] = CLIP[plane[o] + v + 512]
            plane[o + 1] = CLIP[plane[o + 1] + v + 512]
            plane[o + 2] = CLIP[plane[o + 2] + v + 512]
            plane[o + 3] = CLIP[plane[o + 3] + v + 512]


def _add_block(c, plane, off, stride):
    for k in range(1, 16):
        if c[k]:
            _idct_add(c, plane, off, stride)
            return
    if c[0]:
        _dc_add(c[0], plane, off, stride)


def _dequant(levels, start, qp):
    """Levels in scan order (from scan position `start`) -> dequantized coefficients, raster order."""
    q = DQ[qp % 6]
    sh = qp // 6
    c = [0] * 16
    for k in range(len(levels)):
        v = levels[k]
        if v:
            pos = ZIGZAG[k + start]
            c[pos] = (v * q[pos]) << sh
    return c


# ---- intra prediction ----

def _pred4x4(Y, W, o, mode, left, top, tl, tr):
    """Predict the 4x4 block at Y[o] (stride W). left/top/tl/tr: which neighbours exist."""
    if top:
        t = [Y[o - W + k] for k in range(4)]
        if tr:
            t += [Y[o - W + 4 + k] for k in range(4)]
        else:
            t += [t[3]] * 4
    if left:
        L = [Y[o + k * W - 1] for k in range(4)]
    D = Y[o - W - 1] if tl else 0
    if mode == 0:                                   # vertical
        if not top:
            raise H264Error("intra 4x4: vertical without the samples above")
        for y in range(4):
            r = o + y * W
            Y[r] = t[0]
            Y[r + 1] = t[1]
            Y[r + 2] = t[2]
            Y[r + 3] = t[3]
        return
    if mode == 1:                                   # horizontal
        if not left:
            raise H264Error("intra 4x4: horizontal without the samples on the left")
        for y in range(4):
            r = o + y * W
            v = L[y]
            Y[r] = v
            Y[r + 1] = v
            Y[r + 2] = v
            Y[r + 3] = v
        return
    if mode == 2:                                   # DC
        if top and left:
            v = (t[0] + t[1] + t[2] + t[3] + L[0] + L[1] + L[2] + L[3] + 4) >> 3
        elif left:
            v = (L[0] + L[1] + L[2] + L[3] + 2) >> 2
        elif top:
            v = (t[0] + t[1] + t[2] + t[3] + 2) >> 2
        else:
            v = 128
        for y in range(4):
            r = o + y * W
            Y[r] = v
            Y[r + 1] = v
            Y[r + 2] = v
            Y[r + 3] = v
        return
    p = [0] * 16
    if mode == 3:                                   # diagonal down left
        for y in range(4):
            for x in range(4):
                if x == 3 and y == 3:
                    p[15] = (t[6] + 3 * t[7] + 2) >> 2
                else:
                    p[y * 4 + x] = (t[x + y] + 2 * t[x + y + 1] + t[x + y + 2] + 2) >> 2
    elif mode == 7:                                 # vertical left
        for y in range(4):
            for x in range(4):
                i = x + (y >> 1)
                if y & 1:
                    p[y * 4 + x] = (t[i] + 2 * t[i + 1] + t[i + 2] + 2) >> 2
                else:
                    p[y * 4 + x] = (t[i] + t[i + 1] + 1) >> 1
    elif mode == 8:                                 # horizontal up
        for y in range(4):
            for x in range(4):
                z = x + 2 * y
                if z > 5:
                    v = L[3]
                elif z == 5:
                    v = (L[2] + 3 * L[3] + 2) >> 2
                else:
                    i = y + (x >> 1)
                    if z & 1:
                        v = (L[i] + 2 * L[i + 1] + L[i + 2] + 2) >> 2
                    else:
                        v = (L[i] + L[i + 1] + 1) >> 1
                p[y * 4 + x] = v
    else:
        # the modes that use the corner: e[k] for k = -1..3 along the left (e[-1] is the corner),
        # then the top. edge(i): i < 0 -> left sample -i-1 ... written out per mode.
        def T_(x):                                  # p[x, -1], x = -1..3
            return D if x < 0 else t[x]

        def L_(y):                                  # p[-1, y], y = -1..3
            return D if y < 0 else L[y]
        if mode == 4:                               # diagonal down right
            for y in range(4):
                for x in range(4):
                    if x > y:
                        v = (T_(x - y - 2) + 2 * T_(x - y - 1) + T_(x - y) + 2) >> 2
                    elif x < y:
                        v = (L_(y - x - 2) + 2 * L_(y - x - 1) + L_(y - x) + 2) >> 2
                    else:
                        v = (T_(0) + 2 * D + L_(0) + 2) >> 2
                    p[y * 4 + x] = v
        elif mode == 5:                             # vertical right
            for y in range(4):
                for x in range(4):
                    z = 2 * x - y
                    if z >= 0 and not z & 1:
                        i = x - (y >> 1)
                        v = (T_(i - 1) + T_(i) + 1) >> 1
                    elif z >= 0:
                        i = x - (y >> 1)
                        v = (T_(i - 2) + 2 * T_(i - 1) + T_(i) + 2) >> 2
                    elif z == -1:
                        v = (L_(0) + 2 * D + T_(0) + 2) >> 2
                    else:
                        v = (L_(y - 1) + 2 * L_(y - 2) + L_(y - 3) + 2) >> 2
                    p[y * 4 + x] = v
        elif mode == 6:                             # horizontal down
            for y in range(4):
                for x in range(4):
                    z = 2 * y - x
                    if z >= 0 and not z & 1:
                        i = y - (x >> 1)
                        v = (L_(i - 1) + L_(i) + 1) >> 1
                    elif z >= 0:
                        i = y - (x >> 1)
                        v = (L_(i - 2) + 2 * L_(i - 1) + L_(i) + 2) >> 2
                    elif z == -1:
                        v = (L_(0) + 2 * D + T_(0) + 2) >> 2
                    else:
                        v = (T_(x - 1) + 2 * T_(x - 2) + T_(x - 3) + 2) >> 2
                    p[y * 4 + x] = v
        else:
            raise H264Error("bad intra 4x4 mode")
    for y in range(4):
        r = o + y * W
        k = y * 4
        Y[r] = p[k]
        Y[r + 1] = p[k + 1]
        Y[r + 2] = p[k + 2]
        Y[r + 3] = p[k + 3]


def _pred_square(P, W, o, n, mode, left, top, tl, plane_k):
    """16x16 luma (n=16) or 8x8 chroma (n=8) prediction. Modes: 0 V, 1 H, 2 DC, 3 plane
    (the chroma numbers are mapped by the caller). For chroma, DC is done per 4x4 by the caller."""
    if mode == 0:
        if not top:
            raise H264Error("intra: vertical without the samples above")
        row = P[o - W:o - W + n]
        for y in range(n):
            r = o + y * W
            P[r:r + n] = row
    elif mode == 1:
        if not left:
            raise H264Error("intra: horizontal without the samples on the left")
        for y in range(n):
            r = o + y * W
            P[r:r + n] = bytes([P[r - 1]]) * n
    elif mode == 2:
        s = 0
        if top:
            s += sum(P[o - W:o - W + n])
        if left:
            for y in range(n):
                s += P[o + y * W - 1]
        if top and left:
            v = (s + n) // (2 * n)
        elif top or left:
            v = (s + n // 2) // n
        else:
            v = 128
        row = bytes([v]) * n
        for y in range(n):
            r = o + y * W
            P[r:r + n] = row
    else:
        if not (top and left and tl):
            raise H264Error("intra: plane without all the neighbours")
        h = n >> 1
        H = 0
        V = 0
        for k in range(h):
            H += (k + 1) * (P[o - W + h + k] - P[o - W + h - 2 - k])
            V += (k + 1) * (P[o + (h + k) * W - 1] - P[o + (h - 2 - k) * W - 1])
        a = 16 * (P[o + (n - 1) * W - 1] + P[o - W + n - 1])
        b = (plane_k * H + 32) >> 6
        c = (plane_k * V + 32) >> 6
        for y in range(n):
            r = o + y * W
            base = a + c * (y - h + 1) - b * (h - 1) + 16
            for x in range(n):
                v = base >> 5
                P[r + x] = 0 if v < 0 else 255 if v > 255 else v
                base += b


def _pred_chroma_dc(P, W, o, left, top):
    """Chroma DC: each 4x4 block of the 8x8 from its own neighbours."""
    for by in range(2):
        for bx in range(2):
            bo = o + by * 4 * W + bx * 4
            t0 = o - W + bx * 4                     # the samples above and left of the macroblock
            l0 = o + by * 4 * W - 1
            st = sum(P[t0:t0 + 4]) if top else 0
            sl = (P[l0] + P[l0 + W] + P[l0 + 2 * W] + P[l0 + 3 * W]) if left else 0
            if bx == by:                            # (0,0) and (1,1)
                if top and left:
                    v = (st + sl + 4) >> 3
                elif left:
                    v = (sl + 2) >> 2
                elif top:
                    v = (st + 2) >> 2
                else:
                    v = 128
            elif bx:                                # top right: the top first
                v = (st + 2) >> 2 if top else (sl + 2) >> 2 if left else 128
            else:                                   # bottom left: the left first
                v = (sl + 2) >> 2 if left else (st + 2) >> 2 if top else 128
            row = bytes([v]) * 4
            for y in range(4):
                r = bo + y * W
                P[r:r + 4] = row


# ---- motion compensation ----

def _fetch(plane, W, H, x, y, w, h):
    """A w*h patch of a plane, the coordinates clamped to its edges."""
    out = bytearray(w * h)
    if x >= 0 and y >= 0 and x + w <= W and y + h <= H:
        o = y * W + x
        k = 0
        for r in range(h):
            out[k:k + w] = plane[o:o + w]
            o += W
            k += w
        return out
    xs = [0 if x + c < 0 else W - 1 if x + c >= W else x + c for c in range(w)]
    k = 0
    for r in range(h):
        yy = y + r
        o = (0 if yy < 0 else H - 1 if yy >= H else yy) * W
        for c in range(w):
            out[k] = plane[o + xs[c]]
            k += 1
    return out


def _half_h(p, PW, w, h, r0):
    """Horizontal half samples (b), clipped, for rows r0.. of the block (patch with 2 samples of margin)."""
    out = bytearray(w * h)
    k = 0
    for r in range(h):
        i = (r + r0 + 2) * PW
        for c in range(w):
            j = i + c
            v = (p[j] + p[j + 5] - 5 * (p[j + 1] + p[j + 4]) + 20 * (p[j + 2] + p[j + 3]) + 16) >> 5
            out[k] = 0 if v < 0 else 255 if v > 255 else v
            k += 1
    return out


def _half_v(p, PW, w, h, c0):
    out = bytearray(w * h)
    k = 0
    P2 = PW * 2
    P3 = PW * 3
    P4 = PW * 4
    P5 = PW * 5
    for r in range(h):
        i = r * PW + c0 + 2
        for c in range(w):
            j = i + c
            v = (p[j] + p[j + P5] - 5 * (p[j + PW] + p[j + P4]) + 20 * (p[j + P2] + p[j + P3]) + 16) >> 5
            out[k] = 0 if v < 0 else 255 if v > 255 else v
            k += 1
    return out


def _center(p, PW, w, h):
    b1 = [0] * (w * (h + 5))
    k = 0
    for r in range(h + 5):
        i = r * PW
        for c in range(w):
            j = i + c
            b1[k] = p[j] + p[j + 5] - 5 * (p[j + 1] + p[j + 4]) + 20 * (p[j + 2] + p[j + 3])
            k += 1
    out = bytearray(w * h)
    k = 0
    w2, w3, w4, w5 = 2 * w, 3 * w, 4 * w, 5 * w
    for r in range(h):
        for c in range(w):
            j = r * w + c
            v = (b1[j] + b1[j + w5] - 5 * (b1[j + w] + b1[j + w4]) + 20 * (b1[j + w2] + b1[j + w3]) + 512) >> 10
            out[k] = 0 if v < 0 else 255 if v > 255 else v
            k += 1
    return out


def _avg(a, b):
    return bytearray((a[i] + b[i] + 1) >> 1 for i in range(len(a)))


def _full(p, PW, w, h, dx, dy):
    """The full samples of the block, moved by (dx, dy), out of a patch with 2 samples of margin."""
    out = bytearray(w * h)
    k = 0
    for r in range(h):
        i = (r + 2 + dy) * PW + 2 + dx
        out[k:k + w] = p[i:i + w]
        k += w
    return out


def _mc_luma(ref, W, H, x, y, w, h, mx, my):
    xf = mx & 3
    yf = my & 3
    x += mx >> 2
    y += my >> 2
    if not xf and not yf:
        return _fetch(ref, W, H, x, y, w, h)
    PW = w + 5
    p = _fetch(ref, W, H, x - 2, y - 2, PW, h + 5)
    if not yf:
        b = _half_h(p, PW, w, h, 0)
        return b if xf == 2 else _avg(_full(p, PW, w, h, xf >> 1, 0), b)
    if not xf:
        v = _half_v(p, PW, w, h, 0)
        return v if yf == 2 else _avg(_full(p, PW, w, h, 0, yf >> 1), v)
    if xf == 2:
        j = _center(p, PW, w, h)
        return j if yf == 2 else _avg(j, _half_h(p, PW, w, h, yf >> 1))
    if yf == 2:
        return _avg(_center(p, PW, w, h), _half_v(p, PW, w, h, xf >> 1))
    return _avg(_half_h(p, PW, w, h, yf >> 1), _half_v(p, PW, w, h, xf >> 1))


def _mc_chroma(ref, W, H, x, y, w, h, mx, my):
    xf = mx & 7
    yf = my & 7
    x += mx >> 3
    y += my >> 3
    if not xf and not yf:
        return _fetch(ref, W, H, x, y, w, h)
    PW = w + 1
    p = _fetch(ref, W, H, x, y, PW, h + 1)
    a = (8 - xf) * (8 - yf)
    b = xf * (8 - yf)
    c = (8 - xf) * yf
    d = xf * yf
    out = bytearray(w * h)
    k = 0
    for r in range(h):
        i = r * PW
        for col in range(w):
            j = i + col
            out[k] = (a * p[j] + b * p[j + 1] + c * p[j + PW] + d * p[j + PW + 1] + 32) >> 6
            k += 1
    return out


def _put(plane, W, o, w, h, src, wt):
    """Write a predicted block (weighted when wt = (log_wd, weight, offset))."""
    if wt is not None:
        lwd, wgt, off = wt
        if lwd >= 1:
            rnd = 1 << (lwd - 1)
            src = bytearray(min(max(((v * wgt + rnd) >> lwd) + off, 0), 255) for v in src)
        else:
            src = bytearray(min(max(v * wgt + off, 0), 255) for v in src)
    k = 0
    for r in range(h):
        plane[o:o + w] = src[k:k + w]
        o += W
        k += w


# ---- parameter sets ----

class SPS:
    pass


class PPS:
    pass


def _skip_scaling_list(br, size):
    last = 8
    nxt = 8
    for _ in range(size):
        if nxt:
            nxt = (last + br.se() + 256) % 256
        last = nxt if nxt else last


def _parse_hrd(br):
    n = br.ue() + 1
    br.u(8)
    for _ in range(n):
        br.ue()
        br.ue()
        br.bit()
    br.u(20)


def _parse_sps(br):
    s = SPS()
    s.profile = br.u(8)
    br.u(8)
    s.level = br.u(8)
    s.id = br.ue()
    s.chroma_format = 1
    if s.profile in (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135):
        s.chroma_format = br.ue()
        if s.chroma_format == 3:
            br.bit()
        if br.ue() or br.ue():
            raise H264Error("only 8-bit video is supported")
        br.bit()
        if br.bit():
            for i in range(8 if s.chroma_format != 3 else 12):
                if br.bit():
                    _skip_scaling_list(br, 16 if i < 6 else 64)
    s.log2_max_frame_num = br.ue() + 4
    s.poc_type = br.ue()
    if s.poc_type == 0:
        s.log2_max_poc_lsb = br.ue() + 4
    elif s.poc_type == 1:
        s.delta_pic_order_always_zero = br.bit()
        s.offset_for_non_ref_pic = br.se()
        s.offset_for_top_to_bottom = br.se()
        s.poc_cycle = [br.se() for _ in range(br.ue())]
    s.num_ref_frames = br.ue()
    s.gaps_allowed = br.bit()
    s.mb_width = br.ue() + 1
    s.mb_height = br.ue() + 1
    s.frame_mbs_only = br.bit()
    if not s.frame_mbs_only:
        br.bit()
    br.bit()
    s.crop = (0, 0, 0, 0)
    if br.bit():
        s.crop = (br.ue(), br.ue(), br.ue(), br.ue())       # left, right, top, bottom (in 2 samples)
    s.reorder = 0
    if br.bit():
        try:
            _parse_vui(br, s)
        except Exception:
            pass
    return s


def _parse_vui(br, s):
    if br.bit():
        if br.u(8) == 255:
            br.u(32)
    if br.bit():
        br.bit()
    if br.bit():
        br.u(4)
        if br.bit():
            br.u(24)
    if br.bit():
        br.ue()
        br.ue()
    if br.bit():
        br.u(32)
        br.u(32)
        br.bit()
    nal = br.bit()
    if nal:
        _parse_hrd(br)
    vcl = br.bit()
    if vcl:
        _parse_hrd(br)
    if nal or vcl:
        br.bit()
    br.bit()
    if br.bit():
        br.bit()
        br.ue()
        br.ue()
        br.ue()
        br.ue()
        s.reorder = br.ue()
        br.ue()


def _parse_pps(br, spss):
    p = PPS()
    p.id = br.ue()
    p.sps_id = br.ue()
    p.cabac = br.bit()
    p.bottom_field_pic_order = br.bit()
    p.slice_groups = br.ue() + 1
    if p.slice_groups > 1:
        raise H264Error("slice groups (FMO) are not supported")
    p.num_ref_idx = (br.ue() + 1, br.ue() + 1)
    p.weighted_pred = br.bit()
    p.weighted_bipred = br.u(2)
    p.init_qp = 26 + br.se()
    br.se()
    p.chroma_qp_offset = br.se()
    p.deblocking_control = br.bit()
    p.constrained_intra = br.bit()
    p.redundant_pic_cnt = br.bit()
    p.transform_8x8 = br.bit() if br.more() else 0       # High profile
    return p


# ---- pictures ----

class Picture:
    __slots__ = ("y", "u", "v", "poc", "frame_num", "wrap", "long", "ref", "lt_idx", "id", "mmco5", "out")

    def __init__(self, W, H):
        self.y = bytearray(W * H)
        self.u = bytearray(W * H // 4)
        self.v = bytearray(W * H // 4)
        self.reset()

    def reset(self):
        self.poc = 0
        self.frame_num = 0
        self.wrap = 0
        self.long = False
        self.ref = False                # used for reference (short or long)
        self.lt_idx = 0
        self.mmco5 = False
        self.out = False                # waiting to be shown


class Slice:
    pass


class H264:
    def __init__(self):
        self.sps = {}
        self.pps = {}
        self.active = None              # the SPS of the pictures
        self.W = self.H = 0
        self.cur = None                 # the picture being decoded
        self.dpb = []                   # reference pictures
        self.queue = []                 # decoded, waiting to be output (POC order)
        self.free = []
        self.pic = None                 # the last picture output
        self.pictures = 0
        self.last = 0                   # 0 ok, 1 error in the last call
        self.error = None
        self.on_picture = None          # a hook: called with each picture output (tests)
        self.ids = 0
        self.prev = None                # the previous slice header (to see where pictures begin)
        # POC state
        self.prev_poc_msb = 0
        self.prev_poc_lsb = 0
        self.prev_frame_num = 0
        self.prev_frame_num_offset = 0
        self.prev_ref_frame_num = 0
        self.max_lt_idx = -1

    # ---- the interface the player uses ----
    def size(self):
        return self.W, self.H

    def status(self):
        return self.last

    def crop(self):
        s = self.active
        if not s or not self.W:
            return 0, 0, self.W, self.H
        l, r, t, b = s.crop
        return 2 * l, 2 * t, self.W - 2 * (l + r), self.H - 2 * (t + b)

    def close(self):
        self.dpb = []
        self.queue = []
        self.free = []
        self.cur = None
        self.pic = None

    def decode(self, data):
        """Annex B bytes (one access unit, or more) -> how many pictures became ready."""
        before = self.pictures
        self.last = 0
        for nal in nal_units(data):
            try:
                self._nal(nal)
            except H264Error as e:
                self.last = 1
                self.error = str(e)
            except (IndexError, KeyError, NameError, TypeError, ValueError) as e:
                self.last = 1
                self.error = "damaged data (%s)" % e
        if self.cur is not None:
            self._finish()
        return self.pictures - before

    # ---- NAL units ----
    def _nal(self, nal):
        kind = nal[0] & 31
        ref_idc = (nal[0] >> 5) & 3
        if kind == 7:
            s = _parse_sps(_Bits(_unescape(nal[1:])))
            self.sps[s.id] = s
        elif kind == 8:
            p = _parse_pps(_Bits(_unescape(nal[1:])), self.sps)
            self.pps[p.id] = p
        elif kind in (1, 5):
            self._slice(_Bits(_unescape(nal[1:])), kind == 5, ref_idc)
        elif kind == 11 and self.cur is not None:          # end of stream
            self._finish()

    # ---- the slice header ----
    def _slice(self, br, idr, ref_idc):
        sh = Slice()
        sh.idr = idr
        sh.ref_idc = ref_idc
        sh.first_mb = br.ue()
        t = br.ue()
        sh.type = t % 5
        pid = br.ue()
        pps = self.pps.get(pid)
        if pps is None:
            raise H264Error("slice without its PPS")
        sps = self.sps.get(pps.sps_id)
        if sps is None:
            raise H264Error("slice without its SPS")
        if pps.cabac:
            raise H264Error("CABAC (Main/High profile) is not supported: SnakeyOS plays H.264 Baseline")
        if pps.transform_8x8:
            raise H264Error("8x8 transforms (High profile) are not supported: SnakeyOS plays H.264 Baseline")
        if sh.type in (B_SLICE, SP_SLICE, SI_SLICE):
            raise H264Error("B, SP and SI slices are not supported: SnakeyOS plays H.264 Baseline")
        if not sps.frame_mbs_only:
            raise H264Error("interlaced H.264 is not supported")
        if sps.chroma_format != 1:
            raise H264Error("only 4:2:0 H.264 is supported")
        sh.pps = pps
        sh.sps = sps
        sh.frame_num = br.u(sps.log2_max_frame_num)
        sh.idr_id = br.ue() if idr else 0
        sh.poc_lsb = 0
        sh.delta_bottom = 0
        sh.delta = [0, 0]
        if sps.poc_type == 0:
            sh.poc_lsb = br.u(sps.log2_max_poc_lsb)
            if pps.bottom_field_pic_order:
                sh.delta_bottom = br.se()
        elif sps.poc_type == 1 and not sps.delta_pic_order_always_zero:
            sh.delta[0] = br.se()
            if pps.bottom_field_pic_order:
                sh.delta[1] = br.se()
        if pps.redundant_pic_cnt:
            if br.ue():
                return                          # a redundant slice: the primary one is enough
        sh.num_ref = pps.num_ref_idx[0]
        if sh.type == P_SLICE:
            if br.bit():
                sh.num_ref = br.ue() + 1
        sh.reorder = []
        if sh.type != I_SLICE and br.bit():
            while True:
                op = br.ue()
                if op == 3:
                    break
                if op > 3:
                    raise H264Error("bad ref_pic_list_modification")
                sh.reorder.append((op, br.ue()))
        sh.weights = None
        if pps.weighted_pred and sh.type == P_SLICE:
            lwd = br.ue()
            cwd = br.ue()
            ws = []
            for _ in range(sh.num_ref):
                lw = (lwd, 1 << lwd, 0)
                if br.bit():
                    lw = (lwd, br.se(), br.se())
                cw = ((cwd, 1 << cwd, 0), (cwd, 1 << cwd, 0))
                if br.bit():
                    cw = ((cwd, br.se(), br.se()), (cwd, br.se(), br.se()))
                ws.append((lw, cw[0], cw[1]))
            sh.weights = ws
        sh.long_term_ref = False
        sh.mmco = None
        if ref_idc:
            if idr:
                br.bit()
                sh.long_term_ref = br.bit()
            elif br.bit():
                sh.mmco = []
                while True:
                    op = br.ue()
                    if op == 0:
                        break
                    a = b = 0
                    if op in (1, 3):
                        a = br.ue()
                    if op == 2:
                        a = br.ue()
                    if op in (3, 6):
                        b = br.ue()
                    if op == 4:
                        a = br.ue()
                    sh.mmco.append((op, a, b))
        sh.qp = pps.init_qp + br.se()
        sh.deblock = 0
        sh.alpha = sh.beta = 0
        if pps.deblocking_control:
            sh.deblock = br.ue()
            if sh.deblock != 1:
                sh.alpha = br.se() * 2
                sh.beta = br.se() * 2
        # a new picture?
        p = self.prev
        if self.cur is not None and (sh.first_mb == 0 or p is None or p.frame_num != sh.frame_num or
                                     p.idr != sh.idr or p.poc_lsb != sh.poc_lsb or p.idr_id != sh.idr_id or
                                     p.pps is not sh.pps or (p.ref_idc == 0) != (ref_idc == 0)):
            self._finish()
        if self.cur is None:
            self._start(sh)
        self.prev = sh
        self.slice_num += 1
        sh.num = self.slice_num
        self.slices.append(sh)
        if sh.type == P_SLICE:
            self._ref_list(sh)
        self._slice_data(br, sh)

    # ---- a picture: start, references, end ----
    def _start(self, sh):
        sps = sh.sps
        W = sps.mb_width * 16
        H = sps.mb_height * 16
        if sps is not self.active or W != self.W or H != self.H:
            if W * H > 1920 * 1088:
                raise H264Error("the video is too big (%dx%d)" % (W, H))
            self.active = sps
            if W != self.W or H != self.H:
                self.W, self.H = W, H
                self.free = []
                self.dpb = [p for p in self.dpb if len(p.y) == W * H]
        mbw, mbh = sps.mb_width, sps.mb_height
        if sh.idr:
            self._flush_output()
            for p in list(self.dpb):
                self._unref(p)
        elif sps.gaps_allowed and sh.frame_num != self.prev_ref_frame_num and \
                sh.frame_num != (self.prev_ref_frame_num + 1) % (1 << sps.log2_max_frame_num):
            self._fill_gap(sh)
        pic = self._new_picture()
        self.ids += 1
        pic.id = self.ids
        pic.frame_num = sh.frame_num
        pic.poc = self._poc(sh)
        self.cur = pic
        self.cur_sh = sh
        self.slice_num = -1
        self.slices = []
        n = mbw * mbh
        W4 = mbw * 4
        self.mbw, self.mbh, self.W4 = mbw, mbh, W4
        self.mb_slice = [-1] * n
        self.mb_intra = bytearray(n)
        self.mb_qp = bytearray(n)
        self.mb_qpc = bytearray(n)
        n4 = n * 16
        self.nz = bytearray(n4)
        self.nzc = (bytearray(n * 4), bytearray(n * 4))
        self.ipm = bytearray(n4)
        self.mvx = [0] * n4
        self.mvy = [0] * n4
        self.refi = [-1] * n4
        self.refp = [0] * n4

    def _new_picture(self):
        while self.free:
            p = self.free.pop()
            if len(p.y) == self.W * self.H and not p.ref and not p.out and p is not self.pic:
                p.reset()
                return p
        return Picture(self.W, self.H)

    def _release(self, p):
        if not p.ref and not p.out and p is not self.pic and p is not self.cur and p not in self.free:
            self.free.append(p)

    def _poc(self, sh):
        sps = sh.sps
        max_fn = 1 << sps.log2_max_frame_num
        if sps.poc_type == 0:
            if sh.idr:
                self.prev_poc_msb = self.prev_poc_lsb = 0
            max_lsb = 1 << sps.log2_max_poc_lsb
            lsb, plsb, pmsb = sh.poc_lsb, self.prev_poc_lsb, self.prev_poc_msb
            if lsb < plsb and plsb - lsb >= max_lsb // 2:
                msb = pmsb + max_lsb
            elif lsb > plsb and lsb - plsb > max_lsb // 2:
                msb = pmsb - max_lsb
            else:
                msb = pmsb
            sh.poc_msb = msb
            top = msb + lsb
            return min(top, top + sh.delta_bottom)
        if sh.idr:
            offset = 0
        elif self.prev_frame_num > sh.frame_num:
            offset = self.prev_frame_num_offset + max_fn
        else:
            offset = self.prev_frame_num_offset
        sh.frame_num_offset = offset
        if sps.poc_type == 2:
            if sh.idr:
                return 0
            return 2 * (offset + sh.frame_num) - (0 if sh.ref_idc else 1)
        cyc = sps.poc_cycle
        absn = offset + sh.frame_num if cyc else 0
        if sh.ref_idc == 0 and absn > 0:
            absn -= 1
        expected = 0
        if absn > 0:
            n = len(cyc)
            cnt, inc = (absn - 1) // n, (absn - 1) % n
            expected = cnt * sum(cyc) + sum(cyc[:inc + 1])
        if sh.ref_idc == 0:
            expected += sps.offset_for_non_ref_pic
        top = expected + sh.delta[0]
        bottom = top + sps.offset_for_top_to_bottom + sh.delta[1]
        return min(top, bottom)

    def _fill_gap(self, sh):
        """Frames missing from frame_num (allowed by the SPS): 'non-existing' references."""
        sps = sh.sps
        max_fn = 1 << sps.log2_max_frame_num
        fn = (self.prev_ref_frame_num + 1) % max_fn
        src = self.dpb[-1] if self.dpb else None
        guard = 0
        while fn != sh.frame_num and guard < max_fn:
            guard += 1
            p = self._new_picture()
            if src is not None:
                p.y[:] = src.y
                p.u[:] = src.u
                p.v[:] = src.v
            self.ids += 1
            p.id = self.ids
            p.frame_num = fn
            self._sliding_window(sps)
            p.ref = True
            self.dpb.append(p)
            self.prev_ref_frame_num = fn
            self.prev_frame_num = fn
            fn = (fn + 1) % max_fn

    def _sliding_window(self, sps):
        short = [p for p in self.dpb if p.ref and not p.long]
        longs = [p for p in self.dpb if p.ref and p.long]
        if short and len(short) + len(longs) >= max(sps.num_ref_frames, 1):
            fn = self.cur_sh.frame_num if self.cur is not None else 0
            max_fn = 1 << sps.log2_max_frame_num
            for p in short:
                p.wrap = p.frame_num - max_fn if p.frame_num > fn else p.frame_num
            old = min(short, key=lambda p: p.wrap)
            self._unref(old)

    def _unref(self, p):
        p.ref = False
        p.long = False
        if p in self.dpb:
            self.dpb.remove(p)
        self._release(p)

    def _ref_list(self, sh):
        sps = sh.sps
        max_fn = 1 << sps.log2_max_frame_num
        fn = sh.frame_num
        short = []
        longs = []
        for p in self.dpb:
            if not p.ref:
                continue
            if p.long:
                longs.append(p)
            else:
                p.wrap = p.frame_num - max_fn if p.frame_num > fn else p.frame_num
                short.append(p)
        short.sort(key=lambda p: -p.wrap)
        longs.sort(key=lambda p: p.lt_idx)
        lst = short + longs
        n = sh.num_ref
        if sh.reorder:
            pred = fn
            idx = 0
            for op, val in sh.reorder:
                if op < 2:
                    if op == 0:
                        nowrap = pred - (val + 1)
                        if nowrap < 0:
                            nowrap += max_fn
                    else:
                        nowrap = pred + (val + 1)
                        if nowrap >= max_fn:
                            nowrap -= max_fn
                    pred = nowrap
                    num = nowrap - max_fn if nowrap > fn else nowrap
                    pic = None
                    for p in short:
                        if p.wrap == num:
                            pic = p
                    if pic is None:
                        raise H264Error("reference list modification: no such picture")
                else:
                    pic = None
                    for p in longs:
                        if p.lt_idx == val:
                            pic = p
                    if pic is None:
                        raise H264Error("reference list modification: no such long-term picture")
                while len(lst) < n:
                    lst.append(None)
                lst = lst[:idx] + [pic] + [q for q in lst[idx:] if q is not pic]
                idx += 1
        lst = lst[:n]
        if not lst:
            if self.dpb:
                lst = [self.dpb[-1]]
            else:
                raise H264Error("a P slice without reference pictures")
        for i in range(len(lst)):
            if lst[i] is None:
                lst[i] = lst[0]
        while len(lst) < n:
            lst.append(lst[-1])
        sh.refs = lst

    def _mark(self, sh):
        """Reference marking (8.2.5), after the picture is decoded."""
        cur = self.cur
        sps = sh.sps
        if sh.idr:
            for p in list(self.dpb):
                self._unref(p)
            cur.ref = True
            if sh.long_term_ref:
                cur.long = True
                cur.lt_idx = 0
                self.max_lt_idx = 0
            else:
                self.max_lt_idx = -1
            self.dpb.append(cur)
            return
        cur.ref = True
        if sh.mmco is not None:
            max_fn = 1 << sps.log2_max_frame_num
            fn = sh.frame_num
            for p in self.dpb:
                if not p.long:
                    p.wrap = p.frame_num - max_fn if p.frame_num > fn else p.frame_num
            for op, a, b in sh.mmco:
                if op == 1 or op == 3:
                    num = fn - (a + 1)
                    pic = None
                    for p in self.dpb:
                        if p.ref and not p.long and p.wrap == num:
                            pic = p
                    if pic is None:
                        continue
                    if op == 1:
                        self._unref(pic)
                    else:
                        for p in list(self.dpb):
                            if p.long and p.lt_idx == b:
                                self._unref(p)
                        pic.long = True
                        pic.lt_idx = b
                elif op == 2:
                    for p in list(self.dpb):
                        if p.long and p.lt_idx == a:
                            self._unref(p)
                elif op == 4:
                    self.max_lt_idx = a - 1
                    for p in list(self.dpb):
                        if p.long and p.lt_idx > a - 1:
                            self._unref(p)
                elif op == 5:
                    for p in list(self.dpb):
                        self._unref(p)
                    self.max_lt_idx = -1
                    cur.mmco5 = True
                elif op == 6:
                    for p in list(self.dpb):
                        if p.long and p.lt_idx == b:
                            self._unref(p)
                    cur.long = True
                    cur.lt_idx = b
        else:
            self._sliding_window(sps)
        self.dpb.append(cur)

    def _finish(self):
        cur = self.cur
        sh = self.cur_sh
        self._deblock()
        if cur.poc is None:
            cur.poc = 0
        last = self.prev
        if sh.ref_idc:
            self._mark(sh)
        if cur.mmco5:
            self._flush_output()
            cur.poc = 0
            cur.frame_num = 0
        # POC state for the next picture
        sps = sh.sps
        if sh.ref_idc:
            if cur.mmco5:
                self.prev_poc_msb = 0
                self.prev_poc_lsb = 0
            elif sps.poc_type == 0:
                self.prev_poc_msb = getattr(sh, "poc_msb", 0)
                self.prev_poc_lsb = sh.poc_lsb
            self.prev_ref_frame_num = 0 if cur.mmco5 else sh.frame_num
        self.prev_frame_num_offset = 0 if cur.mmco5 else getattr(sh, "frame_num_offset", 0)
        self.prev_frame_num = 0 if cur.mmco5 else sh.frame_num
        # output, in POC order
        cur.out = True
        q = self.queue
        k = len(q)
        while k > 0 and q[k - 1].poc > cur.poc:
            k -= 1
        q.insert(k, cur)
        self.cur = None
        self.prev = None
        reorder = self.active.reorder if self.active else 0
        while len(q) > reorder:
            self._output(q.pop(0))
        del last

    def _flush_output(self):
        q = self.queue
        while q:
            self._output(q.pop(0))

    def _output(self, p):
        p.out = False
        old = self.pic
        self.pic = p
        self.pictures += 1
        if old is not None and old is not p:
            self._release(old)
        if self.on_picture:
            self.on_picture(p)

    # ---- slice data ----
    def _slice_data(self, br, sh):
        mbw = self.mbw
        n = mbw * self.mbh
        mb = sh.first_mb
        if mb >= n:
            raise H264Error("first_mb_in_slice outside the picture")
        self.qp = sh.qp
        self.sh = sh
        P = sh.type == P_SLICE
        cur = self.cur
        self.chroma_off = sh.pps.chroma_qp_offset
        while mb < n:
            if P:
                skip = br.ue()
                if skip > n - mb:
                    raise H264Error("mb_skip_run outside the picture")
                for _ in range(skip):
                    self._skip_mb(mb)
                    mb += 1
                if skip and not br.more():
                    break
                if mb >= n:
                    break
            self._macroblock(br, mb, P)
            mb += 1
            if not br.more():
                break
        del cur

    def _setup_mb(self, mb):
        self.mb = mb
        self.mbx = mb % self.mbw
        self.mby = mb // self.mbw
        self.mb_slice[mb] = self.sh.num
        self.done = 0

    def _avail(self, mb):
        return mb >= 0 and self.mb_slice[mb] == self.sh.num

    def _avail_intra(self, mb):
        return mb >= 0 and self.mb_slice[mb] == self.sh.num and \
            (self.mb_intra[mb] or not self.sh.pps.constrained_intra)

    def _nb_mb(self, dx, dy):
        """The macroblock next to the current one (dx, dy in -1..1) or -1."""
        x = self.mbx + dx
        y = self.mby + dy
        if x < 0 or y < 0 or x >= self.mbw:
            return -1
        return y * self.mbw + x

    def _store_qp(self, mb, qp):
        self.mb_qp[mb] = qp
        self.mb_qpc[mb] = T.QPC[min(max(qp + self.chroma_off, 0), 51)]

    # ---- P_Skip ----
    def _skip_mb(self, mb):
        self._setup_mb(mb)
        A = self._nb(-1, 0)
        B = self._nb(0, -1)
        if A is None or B is None or (A[0] == 0 and A[1] == 0 and A[2] == 0) or \
                (B[0] == 0 and B[1] == 0 and B[2] == 0):
            mx = my = 0
        else:
            mx, my = self._mvpred(0, 0, 4, 0, 0)
        self.mb_intra[mb] = 0
        self._store_qp(mb, self.qp)
        self._fill_motion(0, 0, 4, 4, 0, mx, my)
        self._clear_coeffs(mb)
        self._inter_pred([(0, 0, 4, 4, 0, mx, my)])

    def _clear_coeffs(self, mb):
        W4 = self.W4
        o = self.mby * 4 * W4 + self.mbx * 4
        nz = self.nz
        ipm = self.ipm
        for r in range(4):
            k = o + r * W4
            for c in range(4):
                nz[k + c] = 0
                ipm[k + c] = 2
        W2 = self.mbw * 2
        o = self.mby * 2 * W2 + self.mbx * 2
        for t in self.nzc:
            t[o] = t[o + 1] = t[o + W2] = t[o + W2 + 1] = 0

    # ---- motion vectors ----
    def _nb(self, x, y):
        """(ref, mvx, mvy) of the 4x4 block at (x, y) (in blocks, from the macroblock's corner), or None."""
        gx = self.mbx * 4 + x
        gy = self.mby * 4 + y
        if gx < 0 or gy < 0 or gx >= self.W4:
            return None
        if 0 <= x < 4 and 0 <= y < 4:
            if not (self.done >> (y * 4 + x)) & 1:
                return None
        else:
            mb = (gy >> 2) * self.mbw + (gx >> 2)
            if self.mb_slice[mb] != self.sh.num or (x >= 4 and y >= 0):
                return None
        i = gy * self.W4 + gx
        return self.refi[i], self.mvx[i], self.mvy[i]

    def _mvpred(self, x, y, w, ref, shape):
        """The predicted motion vector of a partition (8.4.1.3). shape: 0 median, 1/2 the top/bottom
        of 16x8, 3/4 the left/right of 8x16."""
        A = self._nb(x - 1, y)
        B = self._nb(x, y - 1)
        C = self._nb(x + w, y - 1)
        if C is None:
            C = self._nb(x - 1, y - 1)
        if shape:
            N = B if shape == 1 else A if shape in (2, 3) else C
            if N is not None and N[0] == ref:
                return N[1], N[2]
        if B is None and C is None and A is not None:
            B = C = A
        NA = (-1, 0, 0)
        if A is None:
            A = NA
        if B is None:
            B = NA
        if C is None:
            C = NA
        m = (A[0] == ref) + (B[0] == ref) + (C[0] == ref)
        if m == 1:
            N = A if A[0] == ref else B if B[0] == ref else C
            return N[1], N[2]
        ax, bx, cx = A[1], B[1], C[1]
        ay, by, cy = A[2], B[2], C[2]
        return (ax + bx + cx - min(ax, bx, cx) - max(ax, bx, cx),
                ay + by + cy - min(ay, by, cy) - max(ay, by, cy))

    def _fill_motion(self, x, y, w, h, ref, mx, my):
        W4 = self.W4
        o = (self.mby * 4 + y) * W4 + self.mbx * 4 + x
        rp = self.sh.refs[ref].id if ref >= 0 else 0
        mvx, mvy, refi, refp = self.mvx, self.mvy, self.refi, self.refp
        for r in range(h):
            k = o + r * W4
            for c in range(w):
                mvx[k + c] = mx
                mvy[k + c] = my
                refi[k + c] = ref
                refp[k + c] = rp
                self.done |= 1 << ((y + r) * 4 + x + c)

    def _inter_pred(self, parts):
        sh = self.sh
        W, H = self.W, self.H
        cur = self.cur
        px = self.mbx * 16
        py = self.mby * 16
        Wc, Hc = W >> 1, H >> 1
        for x, y, w, h, ref, mx, my in parts:
            pic = sh.refs[ref]
            wt = sh.weights[ref] if sh.weights else None
            lx = px + x * 4
            ly = py + y * 4
            blk = _mc_luma(pic.y, W, H, lx, ly, w * 4, h * 4, mx, my)
            _put(cur.y, W, ly * W + lx, w * 4, h * 4, blk, wt[0] if wt else None)
            cx = lx >> 1
            cy = ly >> 1
            o = cy * Wc + cx
            blk = _mc_chroma(pic.u, Wc, Hc, cx, cy, w * 2, h * 2, mx, my)
            _put(cur.u, Wc, o, w * 2, h * 2, blk, wt[1] if wt else None)
            blk = _mc_chroma(pic.v, Wc, Hc, cx, cy, w * 2, h * 2, mx, my)
            _put(cur.v, Wc, o, w * 2, h * 2, blk, wt[2] if wt else None)

    def _ref_idx(self, br):
        n = self.sh.num_ref
        if n <= 1:
            return 0
        if n == 2:
            return 1 - br.bit()
        r = br.ue()
        if r >= n:
            raise H264Error("ref_idx out of range")
        return r

    # ---- a coded macroblock ----
    def _macroblock(self, br, mb, P):
        self._setup_mb(mb)
        t = br.ue()
        if P:
            if t < 5:
                self._inter_mb(br, mb, t)
                return
            t -= 5
        if t > 25:
            raise H264Error("bad mb_type")
        self._intra_mb(br, mb, t)

    def _inter_mb(self, br, mb, t):
        self.mb_intra[mb] = 0
        parts = []
        if t < 3:
            if t == 0:
                shapes = ((0, 0, 4, 4, 0),)
            elif t == 1:
                shapes = ((0, 0, 4, 2, 1), (0, 2, 4, 2, 2))
            else:
                shapes = ((0, 0, 2, 4, 3), (2, 0, 2, 4, 4))
            refs = [self._ref_idx(br) for _ in shapes]
            for k in range(len(shapes)):
                x, y, w, h, shape = shapes[k]
                dx = br.se()
                dy = br.se()
                px, py = self._mvpred(x, y, w, refs[k], shape)
                mx, my = px + dx, py + dy
                self._fill_motion(x, y, w, h, refs[k], mx, my)
                parts.append((x, y, w, h, refs[k], mx, my))
        else:
            subs = [br.ue() for _ in range(4)]
            for s in subs:
                if s > 3:
                    raise H264Error("bad sub_mb_type")
            refs = [0, 0, 0, 0] if t == 4 else [self._ref_idx(br) for _ in range(4)]
            for i in range(4):
                bx = (i & 1) * 2
                by = (i >> 1) * 2
                s = subs[i]
                if s == 0:
                    sp = ((0, 0, 2, 2),)
                elif s == 1:
                    sp = ((0, 0, 2, 1), (0, 1, 2, 1))
                elif s == 2:
                    sp = ((0, 0, 1, 2), (1, 0, 1, 2))
                else:
                    sp = ((0, 0, 1, 1), (1, 0, 1, 1), (0, 1, 1, 1), (1, 1, 1, 1))
                for x, y, w, h in sp:
                    dx = br.se()
                    dy = br.se()
                    px, py = self._mvpred(bx + x, by + y, w, refs[i], 0)
                    mx, my = px + dx, py + dy
                    self._fill_motion(bx + x, by + y, w, h, refs[i], mx, my)
                    parts.append((bx + x, by + y, w, h, refs[i], mx, my))
        cbp = br.ue()
        if cbp > 47:
            raise H264Error("bad coded_block_pattern")
        cbp = CBP_INTER[cbp]
        W4 = self.W4
        o = self.mby * 4 * W4 + self.mbx * 4
        for r in range(4):
            for c in range(4):
                self.ipm[o + r * W4 + c] = 2
        self._inter_pred(parts)
        if cbp:
            self.qp = (self.qp + br.se() + 52) % 52
        self._store_qp(mb, self.qp)
        self._residual(br, mb, cbp, False, None)

    def _intra_mb(self, br, mb, t):
        self.mb_intra[mb] = 1
        W4 = self.W4
        o4 = self.mby * 4 * W4 + self.mbx * 4
        # intra MBs have no motion
        for r in range(4):
            k = o4 + r * W4
            for c in range(4):
                self.refi[k + c] = -1
                self.mvx[k + c] = 0
                self.mvy[k + c] = 0
                self.refp[k + c] = 0
        if t == 25:
            self._pcm(br, mb)
            return
        if t == 0:                                  # I_NxN (4x4)
            modes = [0] * 16
            A_ok = self._avail_intra(self._nb_mb(-1, 0))
            B_ok = self._avail_intra(self._nb_mb(0, -1))
            ipm = self.ipm
            for blk in range(16):
                bx, by = BLK_X[blk], BLK_Y[blk]
                i = o4 + by * W4 + bx
                a_ok = bx > 0 or A_ok
                b_ok = by > 0 or B_ok
                if a_ok and b_ok:
                    pred = min(ipm[i - 1], ipm[i - W4])
                else:
                    pred = 2
                if br.bit():
                    m = pred
                else:
                    r = br.u(3)
                    m = r if r < pred else r + 1
                ipm[i] = m
                modes[blk] = m
            cmode = br.ue()
            cbp = br.ue()
            if cbp > 47:
                raise H264Error("bad coded_block_pattern")
            cbp = CBP_INTRA[cbp]
            if cbp:
                self.qp = (self.qp + br.se() + 52) % 52
            self._store_qp(mb, self.qp)
            self._residual(br, mb, cbp, False, modes)
            self._pred_chroma(cmode)
            self._add_chroma()
        else:                                       # I_16x16
            t -= 1
            mode = t % 4
            cbp = ((t // 4) % 3) << 4 | (15 if t >= 12 else 0)
            for r in range(4):
                k = o4 + r * W4
                for c in range(4):
                    self.ipm[k + c] = 2
            cmode = br.ue()
            self.qp = (self.qp + br.se() + 52) % 52
            self._store_qp(mb, self.qp)
            left = self._avail_intra(self._nb_mb(-1, 0))
            top = self._avail_intra(self._nb_mb(0, -1))
            tl = self._avail_intra(self._nb_mb(-1, -1))
            Y = self.cur.y
            W = self.W
            o = self.mby * 16 * W + self.mbx * 16
            _pred_square(Y, W, o, 16, mode, left, top, tl, 5)
            self._residual(br, mb, cbp, True, None)
            self._pred_chroma(cmode)
            self._add_chroma()

    def _pcm(self, br, mb):
        br.p = (br.p + 7) & ~7
        d = br.d
        i = br.p >> 3
        W = self.W
        Y = self.cur.y
        o = self.mby * 16 * W + self.mbx * 16
        for r in range(16):
            Y[o + r * W:o + r * W + 16] = d[i:i + 16]
            i += 16
        Wc = W >> 1
        o = self.mby * 8 * Wc + self.mbx * 8
        for plane in (self.cur.u, self.cur.v):
            for r in range(8):
                plane[o + r * Wc:o + r * Wc + 8] = d[i:i + 8]
                i += 8
        br.p = i * 8
        W4 = self.W4
        o4 = self.mby * 4 * W4 + self.mbx * 4
        for r in range(4):
            for c in range(4):
                self.nz[o4 + r * W4 + c] = 16
                self.ipm[o4 + r * W4 + c] = 2
        W2 = self.mbw * 2
        o2 = self.mby * 2 * W2 + self.mbx * 2
        for t in self.nzc:
            t[o2] = t[o2 + 1] = t[o2 + W2] = t[o2 + W2 + 1] = 16
        self.mb_qp[mb] = 0                          # the deblocking takes I_PCM as qp 0
        self.mb_qpc[mb] = T.QPC[min(max(self.chroma_off, 0), 51)]

    # ---- residual ----
    def _nc(self, table, W, gx, gy, mbs_per_row, size):
        """nC of a block: from the counts of the blocks on its left and above."""
        sh_num = self.sh.num
        ms = self.mb_slice
        na = nb = -1
        if gx > 0:
            mb = (gy // size) * mbs_per_row + (gx - 1) // size
            if ms[mb] == sh_num:
                na = table[gy * W + gx - 1]
        if gy > 0:
            mb = ((gy - 1) // size) * mbs_per_row + gx // size
            if ms[mb] == sh_num:
                nb = table[(gy - 1) * W + gx]
        if na >= 0 and nb >= 0:
            return (na + nb + 1) >> 1
        if na >= 0:
            return na
        if nb >= 0:
            return nb
        return 0

    def _residual(self, br, mb, cbp, i16, modes):
        """Parse the coefficients and, for luma, rebuild the samples (the prediction is already
        there, except for intra 4x4, predicted block by block here)."""
        qp = self.qp
        W4 = self.W4
        mbw = self.mbw
        gx0 = self.mbx * 4
        gy0 = self.mby * 4
        nz = self.nz
        Y = self.cur.y
        W = self.W
        o = self.mby * 16 * W + self.mbx * 16
        dc = None
        if i16:
            total, lv = _residual_block(br, self._nc(nz, W4, gx0, gy0, mbw, 4), 16)
            dc = [0] * 16
            if total:
                c = [0] * 16
                for k in range(16):
                    c[ZIGZAG[k]] = lv[k]
                # inverse Hadamard, then dequantization
                t = [0] * 16
                for i in range(0, 16, 4):
                    a, b, cc, d = c[i], c[i + 1], c[i + 2], c[i + 3]
                    t[i] = a + b + cc + d
                    t[i + 1] = a + b - cc - d
                    t[i + 2] = a - b - cc + d
                    t[i + 3] = a - b + cc - d
                q = DQ[qp % 6][0] * 16
                sh = qp // 6
                for j in range(4):
                    a, b, cc, d = t[j], t[4 + j], t[8 + j], t[12 + j]
                    f = (a + b + cc + d, a + b - cc - d, a - b - cc + d, a - b + cc - d)
                    for i in range(4):
                        if qp >= 36:
                            v = (f[i] * q) << (sh - 6)
                        else:
                            v = (f[i] * q + (1 << (5 - sh))) >> (6 - sh)
                        dc[i * 4 + j] = v
        # luma blocks, in decoding order
        left = top = tl = False
        if modes is not None:
            A_mb = self._nb_mb(-1, 0)
            B_mb = self._nb_mb(0, -1)
            C_mb = self._nb_mb(1, -1)
            D_mb = self._nb_mb(-1, -1)
            A_ok = self._avail_intra(A_mb)
            B_ok = self._avail_intra(B_mb)
            C_ok = self._avail_intra(C_mb)
            D_ok = self._avail_intra(D_mb)
            done = 0
        for blk in range(16):
            bx, by = BLK_X[blk], BLK_Y[blk]
            gx, gy = gx0 + bx, gy0 + by
            if cbp & (1 << (blk >> 2)):
                total, lv = _residual_block(br, self._nc(nz, W4, gx, gy, mbw, 4), 15 if i16 else 16)
            else:
                total, lv = 0, None
            nz[gy * W4 + gx] = total
            bo = o + by * 4 * W + bx * 4
            if modes is not None:
                left = bx > 0 or A_ok
                top = by > 0 or B_ok
                if bx > 0 and by > 0:
                    tl = True
                elif by > 0:
                    tl = A_ok
                elif bx > 0:
                    tl = B_ok
                else:
                    tl = D_ok
                if by == 0:
                    tr = C_ok if bx == 3 else B_ok
                elif bx == 3:
                    tr = False
                else:
                    tr = bool((done >> ((by - 1) * 4 + bx + 1)) & 1)
                _pred4x4(Y, W, bo, modes[blk], left, top, tl, tr)
                done |= 1 << (by * 4 + bx)
            if i16:
                c = _dequant(lv, 1, qp) if lv else [0] * 16
                c[0] = dc[by * 4 + bx]
                _add_block(c, Y, bo, W)
            elif lv:
                _add_block(_dequant(lv, 0, qp), Y, bo, W)
        # chroma
        self.chroma = None
        ccbp = cbp >> 4
        if ccbp:
            qpc = self.mb_qpc[mb]
            dcs = []
            for comp in range(2):
                total, lv = _residual_block(br, -1, 4)
                d = [0, 0, 0, 0]
                if total:
                    c0, c1, c2, c3 = lv
                    f = (c0 + c1 + c2 + c3, c0 - c1 + c2 - c3, c0 + c1 - c2 - c3, c0 - c1 - c2 + c3)
                    q = DQ[qpc % 6][0] * 16
                    sh = qpc // 6
                    d = [((f[k] * q) << sh) >> 5 for k in range(4)]
                dcs.append(d)
            acs = [[None] * 4, [None] * 4]
            W2 = mbw * 2
            cx0 = self.mbx * 2
            cy0 = self.mby * 2
            for comp in range(2):
                tab = self.nzc[comp]
                for b in range(4):
                    bx, by = b & 1, b >> 1
                    gx, gy = cx0 + bx, cy0 + by
                    if ccbp & 2:
                        total, lv = _residual_block(br, self._nc(tab, W2, gx, gy, mbw, 2), 15)
                    else:
                        total, lv = 0, None
                    tab[gy * W2 + gx] = total
                    acs[comp][b] = lv
            self.chroma = (qpc, dcs, acs)
        else:
            W2 = mbw * 2
            o2 = self.mby * 2 * W2 + self.mbx * 2
            for t in self.nzc:
                t[o2] = t[o2 + 1] = t[o2 + W2] = t[o2 + W2 + 1] = 0
        if modes is None and not self.mb_intra[mb]:
            self._add_chroma()

    def _pred_chroma(self, cmode):
        if cmode > 3:
            raise H264Error("bad intra_chroma_pred_mode")
        left = self._avail_intra(self._nb_mb(-1, 0))
        top = self._avail_intra(self._nb_mb(0, -1))
        tl = self._avail_intra(self._nb_mb(-1, -1))
        Wc = self.W >> 1
        o = self.mby * 8 * Wc + self.mbx * 8
        for plane in (self.cur.u, self.cur.v):
            if cmode == 0:
                _pred_chroma_dc(plane, Wc, o, left, top)
            else:
                _pred_square(plane, Wc, o, 8, (1, 0, 3)[cmode - 1], left, top, tl, 34)

    def _add_chroma(self):
        ch = self.chroma
        if ch is None:
            return
        qpc, dcs, acs = ch
        Wc = self.W >> 1
        o = self.mby * 8 * Wc + self.mbx * 8
        planes = (self.cur.u, self.cur.v)
        for comp in range(2):
            plane = planes[comp]
            for b in range(4):
                lv = acs[comp][b]
                c = _dequant(lv, 1, qpc) if lv else [0] * 16
                c[0] = dcs[comp][b]
                _add_block(c, plane, o + (b >> 1) * 4 * Wc + (b & 1) * 4, Wc)

    # ---- the deblocking filter (8.7) ----
    def _deblock(self):
        mbw, mbh = self.mbw, self.mbh
        W = self.W
        Wc = W >> 1
        W4 = self.W4
        cur = self.cur
        Y, U, V = cur.y, cur.u, cur.v
        ms = self.mb_slice
        intra = self.mb_intra
        nz = self.nz
        mvx, mvy, refp = self.mvx, self.mvy, self.refp
        qps = self.mb_qp
        qpcs = self.mb_qpc
        slices = self.slices
        for mb in range(mbw * mbh):
            sn = ms[mb]
            if sn < 0:
                continue
            sh = slices[sn]
            if sh.deblock == 1:
                continue
            mx, my = mb % mbw, mb // mbw
            offa, offb = sh.alpha, sh.beta
            for vert in (1, 0):
                if vert:
                    nmb = mb - 1 if mx > 0 else -1
                else:
                    nmb = mb - mbw if my > 0 else -1
                if nmb >= 0 and (ms[nmb] < 0 or (sh.deblock == 2 and ms[nmb] != sn)):
                    nmb = -1
                for e in range(4):
                    if e == 0 and nmb < 0:
                        continue
                    pmb = nmb if e == 0 else mb
                    # boundary strengths of the 4 segments
                    bs = [0, 0, 0, 0]
                    any_bs = False
                    for k in range(4):
                        if vert:
                            qi = (my * 4 + k) * W4 + mx * 4 + e
                            pi = qi - 1
                        else:
                            qi = (my * 4 + e) * W4 + mx * 4 + k
                            pi = qi - W4
                        if intra[mb] or intra[pmb]:
                            s = 4 if e == 0 else 3
                        elif nz[qi] or nz[pi]:
                            s = 2
                        elif refp[qi] != refp[pi] or abs(mvx[qi] - mvx[pi]) >= 4 or abs(mvy[qi] - mvy[pi]) >= 4:
                            s = 1
                        else:
                            s = 0
                        bs[k] = s
                        if s:
                            any_bs = True
                    if not any_bs:
                        continue
                    # luma
                    qav = (qps[mb] + qps[pmb] + 1) >> 1
                    ia = min(max(qav + offa, 0), 51)
                    ib = min(max(qav + offb, 0), 51)
                    alpha, beta = ALPHA[ia], BETA[ib]
                    if alpha and beta:
                        if vert:
                            base = my * 16 * W + mx * 16 + e * 4
                            _filter(Y, base, 1, W, 16, bs, alpha, beta, TC0[ia], False)
                        else:
                            base = (my * 16 + e * 4) * W + mx * 16
                            _filter(Y, base, W, 1, 16, bs, alpha, beta, TC0[ia], False)
                    # chroma: the edges 0 and 2 of luma
                    if e & 1:
                        continue
                    qav = (qpcs[mb] + qpcs[pmb] + 1) >> 1
                    ia = min(max(qav + offa, 0), 51)
                    ib = min(max(qav + offb, 0), 51)
                    alpha, beta = ALPHA[ia], BETA[ib]
                    if not (alpha and beta):
                        continue
                    if vert:
                        base = my * 8 * Wc + mx * 8 + e * 2
                        _filter(U, base, 1, Wc, 8, bs, alpha, beta, TC0[ia], True)
                        _filter(V, base, 1, Wc, 8, bs, alpha, beta, TC0[ia], True)
                    else:
                        base = (my * 8 + e * 2) * Wc + mx * 8
                        _filter(U, base, Wc, 1, 8, bs, alpha, beta, TC0[ia], True)
                        _filter(V, base, Wc, 1, 8, bs, alpha, beta, TC0[ia], True)

    # ---- drawing ----
    def draw(self, buf, stride, bh, x, y, w, h):
        """The last picture, scaled into the rectangle (x, y, w, h) of a 32-bit BGRA buffer."""
        p = self.pic
        if p is None:
            return False
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > stride or y + h > bh or stride * bh * 4 > len(buf):
            raise ValueError("media: rectangle outside the buffer")
        cx, cy, cw, ch = self.crop()
        W = self.W
        Wc = W >> 1
        Yp, Up, Vp = p.y, p.u, p.v
        mv = memoryview(buf)
        sx = [cx + i * cw // w for i in range(w)]
        sxc = [v >> 1 for v in sx]
        row = bytearray(w * 4)
        for j in range(h):
            sy = cy + j * ch // h
            yo = sy * W
            co = (sy >> 1) * Wc
            k = 0
            for i in range(w):
                c = _YT[Yp[yo + sx[i]]]
                u = Up[co + sxc[i]]
                v = Vp[co + sxc[i]]
                row[k] = CLIP[((c + _UB[u] + 128) >> 8) + 512]
                row[k + 1] = CLIP[((c + _UG[u] + _VG[v] + 128) >> 8) + 512]
                row[k + 2] = CLIP[((c + _VR[v] + 128) >> 8) + 512]
                row[k + 3] = 255
                k += 4
            d = ((y + j) * stride + x) * 4
            mv[d:d + w * 4] = row
        return True


_YT = [(i - 16) * 298 for i in range(256)]
_UB = [516 * (i - 128) for i in range(256)]
_UG = [-100 * (i - 128) for i in range(256)]
_VG = [-208 * (i - 128) for i in range(256)]
_VR = [409 * (i - 128) for i in range(256)]


def _filter(P, base, across, along, n, bs, alpha, beta, tc0s, chroma):
    """Filter one edge: n lines of samples starting at P[base] (q0), p0 at base - across."""
    seg = n >> 2
    for i in range(n):
        s = bs[i // seg]
        if not s:
            continue
        q = base + i * along
        p0 = P[q - across]
        q0 = P[q]
        if abs(p0 - q0) >= alpha:
            continue
        p1 = P[q - 2 * across]
        q1 = P[q + across]
        if abs(p1 - p0) >= beta or abs(q1 - q0) >= beta:
            continue
        if chroma:
            if s < 4:
                tc = tc0s[s - 1] + 1
                d = ((((q0 - p0) << 2) + (p1 - q1) + 4) >> 3)
                d = -tc if d < -tc else tc if d > tc else d
                P[q - across] = CLIP[p0 + d + 512]
                P[q] = CLIP[q0 - d + 512]
            else:
                P[q - across] = (2 * p1 + p0 + q1 + 2) >> 2
                P[q] = (2 * q1 + q0 + p1 + 2) >> 2
            continue
        p2 = P[q - 3 * across]
        q2 = P[q + 2 * across]
        ap = abs(p2 - p0)
        aq = abs(q2 - q0)
        if s < 4:
            t0 = tc0s[s - 1]
            tc = t0 + (ap < beta) + (aq < beta)
            d = ((((q0 - p0) << 2) + (p1 - q1) + 4) >> 3)
            d = -tc if d < -tc else tc if d > tc else d
            P[q - across] = CLIP[p0 + d + 512]
            P[q] = CLIP[q0 - d + 512]
            if ap < beta:
                v = (p2 + ((p0 + q0 + 1) >> 1) - (p1 << 1)) >> 1
                P[q - 2 * across] = p1 + (-t0 if v < -t0 else t0 if v > t0 else v)
            if aq < beta:
                v = (q2 + ((p0 + q0 + 1) >> 1) - (q1 << 1)) >> 1
                P[q + across] = q1 + (-t0 if v < -t0 else t0 if v > t0 else v)
        else:
            strong = abs(p0 - q0) < ((alpha >> 2) + 2)
            if ap < beta and strong:
                p3 = P[q - 4 * across]
                P[q - across] = (p2 + 2 * p1 + 2 * p0 + 2 * q0 + q1 + 4) >> 3
                P[q - 2 * across] = (p2 + p1 + p0 + q0 + 2) >> 2
                P[q - 3 * across] = (2 * p3 + 3 * p2 + p1 + p0 + q0 + 4) >> 3
            else:
                P[q - across] = (2 * p1 + p0 + q1 + 2) >> 2
            if aq < beta and strong:
                q3 = P[q + 3 * across]
                P[q] = (p1 + 2 * p0 + 2 * q0 + 2 * q1 + q2 + 4) >> 3
                P[q + across] = (p0 + q0 + q1 + q2 + 2) >> 2
                P[q + 2 * across] = (2 * q3 + 3 * q2 + q1 + q0 + p0 + 4) >> 3
            else:
                P[q] = (2 * q1 + q0 + p1 + 2) >> 2
