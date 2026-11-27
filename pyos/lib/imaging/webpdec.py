# WebP pictures, in Python: lossless (VP8L), lossy (VP8, the key frames of
# RFC 6386) and transparency (ALPH), as the WebP container specification
# describes them.
#
#   w, h, pixels = webpdec.decode(data)    # pixels: B G R A, 4 bytes each
#
# Every pixel comes out as libwebp (the reference decoder) gives it,
# colour upsampling included (tools/test_webp.py checks that).
from imaging import vp8_tables as T


class WebPError(ValueError):
    pass


def _u16(d, i):
    return d[i] | d[i + 1] << 8


def _u24(d, i):
    return d[i] | d[i + 1] << 8 | d[i + 2] << 16


def _u32(d, i):
    return d[i] | d[i + 1] << 8 | d[i + 2] << 16 | d[i + 3] << 24


def decode(data):
    """(width, height, BGRA bytes) of a WebP file (the first frame of an animation)."""
    data = memoryview(data)
    if bytes(data[0:4]) != b"RIFF" or bytes(data[8:12]) != b"WEBP":
        raise WebPError("not a WebP file")
    chunks = _chunks(data, 12, len(data))
    alpha = None
    canvas = None
    for tag, body in chunks:
        if tag == b"VP8X":
            canvas = (_u24(body, 4) + 1, _u24(body, 7) + 1)
        elif tag == b"ANMF":                           # an animation: its first frame
            sub = _chunks(body, 16, len(body))
            chunks = sub
            break
    for tag, body in chunks:
        if tag == b"ALPH":
            alpha = body
        elif tag == b"VP8L":
            w, h, argb = _vp8l(body)
            return w, h, _argb_to_bgra(argb)
        elif tag == b"VP8 ":
            w, h, bgra = _vp8(body)
            if alpha is not None:
                _apply_alpha(bgra, w, h, alpha)
            return w, h, bgra
    raise WebPError("no picture in the WebP file" if canvas is None else "unsupported WebP")


def _chunks(d, i, end):
    out = []
    while i + 8 <= end:
        tag = bytes(d[i:i + 4])
        n = _u32(d, i + 4)
        out.append((tag, d[i + 8:i + 8 + n]))
        i += 8 + n + (n & 1)
    return out


def _argb_to_bgra(argb):
    out = bytearray(len(argb) * 4)
    o = 0
    for p in argb:
        out[o] = p & 255
        out[o + 1] = (p >> 8) & 255
        out[o + 2] = (p >> 16) & 255
        out[o + 3] = (p >> 24) & 255
        o += 4
    return out


# ======================================================================
# VP8L: lossless
# ======================================================================

class _Bits:
    """Bits, least significant first."""

    def __init__(self, d):
        self.d = d
        self.n = len(d)
        self.pos = 0          # in bits

    def read(self, n):
        if n == 0:
            return 0
        p = self.pos
        i = p >> 3
        d = self.d
        v = 0
        k = 0
        while k < n + (p & 7):
            v |= (d[i] if i < self.n else 0) << k
            i += 1
            k += 8
        self.pos = p + n
        return (v >> (p & 7)) & ((1 << n) - 1)

    def bit(self):
        p = self.pos
        self.pos = p + 1
        i = p >> 3
        return ((self.d[i] if i < self.n else 0) >> (p & 7)) & 1


class _Code:
    """A canonical prefix code, read a bit at a time (most significant code bit first)."""

    def __init__(self, lengths):
        nonzero = [s for s in range(len(lengths)) if lengths[s]]
        self.single = nonzero[0] if len(nonzero) == 1 else (0 if not nonzero else None)
        # canonical codes: by length, then by symbol
        maxlen = max(lengths) if nonzero else 0
        count = [0] * (maxlen + 2)
        for s in nonzero:
            count[lengths[s]] += 1
        code = 0
        nxt = [0] * (maxlen + 2)
        for L in range(1, maxlen + 1):
            code = (code + count[L - 1]) << 1
            nxt[L] = code
        # first[L]: the smallest code of length L; syms[L]: the symbols of length L in order
        self.first = nxt
        self.syms = [[] for _ in range(maxlen + 1)]
        for s in nonzero:
            self.syms[lengths[s]].append(s)
        self.maxlen = maxlen
        # an 8-bit lookup for short codes: index = the next 8 bits (first bit lowest)
        table = [-1] * 256
        for L in range(1, min(maxlen, 8) + 1):
            c = nxt[L]
            for s in self.syms[L]:
                rev = 0
                for k in range(L):
                    rev |= ((c >> (L - 1 - k)) & 1) << k
                step = 1 << L
                for j in range(rev, 256, step):
                    table[j] = s << 4 | L
                c += 1
        self.table = table

    def read(self, br):
        if self.single is not None:
            return self.single
        p = br.pos
        i = p >> 3
        d = br.d
        n = br.n
        v = ((d[i] if i < n else 0) | (d[i + 1] if i + 1 < n else 0) << 8) >> (p & 7)
        t = self.table[v & 255]
        if t >= 0:
            br.pos = p + (t & 15)
            return t >> 4
        code = 0
        for L in range(1, self.maxlen + 1):            # longer than 8 bits: walk
            code = code << 1 | br.bit()
            k = code - self.first[L]
            if 0 <= k < len(self.syms[L]):
                return self.syms[L][k]
        raise WebPError("bad prefix code")


_ORDER = (17, 18, 0, 1, 2, 3, 4, 5, 16, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)


def _read_code(br, size):
    lengths = [0] * size
    if br.bit():                                       # a simple code: 1 or 2 symbols
        two = br.bit()
        s0 = br.read(8 if br.bit() else 1)
        lengths[s0] = 1
        if two:
            lengths[br.read(8)] = 1
        return _Code(lengths)
    ll = [0] * 19
    for i in range(4 + br.read(4)):
        ll[_ORDER[i]] = br.read(3)
    lc = _Code(ll)
    if br.bit():
        max_symbol = 2 + br.read(2 + 2 * br.read(3))
    else:
        max_symbol = size
    prev = 8
    s = 0
    while s < size:
        if max_symbol == 0:
            break
        max_symbol -= 1
        c = lc.read(br)
        if c < 16:
            lengths[s] = c
            s += 1
            if c:
                prev = c
        else:
            if c == 16:
                rep, val = 3 + br.read(2), prev
            elif c == 17:
                rep, val = 3 + br.read(3), 0
            else:
                rep, val = 11 + br.read(7), 0
            if s + rep > size:
                raise WebPError("bad code lengths")
            for _ in range(rep):
                lengths[s] = val
                s += 1
    return _Code(lengths)


_PLANE = bytes((
    0x18, 0x07, 0x17, 0x19, 0x28, 0x06, 0x27, 0x29, 0x16, 0x1a, 0x26, 0x2a,
    0x38, 0x05, 0x37, 0x39, 0x15, 0x1b, 0x36, 0x3a, 0x25, 0x2b, 0x48, 0x04,
    0x47, 0x49, 0x14, 0x1c, 0x35, 0x3b, 0x46, 0x4a, 0x24, 0x2c, 0x58, 0x45,
    0x4b, 0x34, 0x3c, 0x03, 0x57, 0x59, 0x13, 0x1d, 0x56, 0x5a, 0x23, 0x2d,
    0x44, 0x4c, 0x55, 0x5b, 0x33, 0x3d, 0x68, 0x02, 0x67, 0x69, 0x12, 0x1e,
    0x66, 0x6a, 0x22, 0x2e, 0x54, 0x5c, 0x43, 0x4d, 0x65, 0x6b, 0x32, 0x3e,
    0x78, 0x01, 0x77, 0x79, 0x53, 0x5d, 0x11, 0x1f, 0x64, 0x6c, 0x42, 0x4e,
    0x76, 0x7a, 0x21, 0x2f, 0x75, 0x7b, 0x31, 0x3f, 0x63, 0x6d, 0x52, 0x5e,
    0x00, 0x74, 0x7c, 0x41, 0x4f, 0x10, 0x20, 0x62, 0x6e, 0x30, 0x73, 0x7d,
    0x51, 0x5f, 0x40, 0x72, 0x7e, 0x61, 0x6f, 0x50, 0x71, 0x7f, 0x60, 0x70))


def _prefix_value(br, prefix):
    if prefix < 4:
        return prefix + 1
    extra = (prefix - 2) >> 1
    return ((2 + (prefix & 1)) << extra) + br.read(extra) + 1


def _entropy_image(br, w, h, top):
    """An entropy-coded image of w x h ARGB pixels (top: the main image, which may have meta codes)."""
    cache_bits = br.read(4) if br.bit() else 0
    if cache_bits > 11:
        raise WebPError("bad colour cache")
    meta = None
    mbits = 0
    groups = 1
    if top and br.bit():
        mbits = br.read(3) + 2
        mw = (w + (1 << mbits) - 1) >> mbits
        mh = (h + (1 << mbits) - 1) >> mbits
        meta = _entropy_image(br, mw, mh, False)
        meta = [(p >> 8) & 0xFFFF for p in meta]
        groups = max(meta) + 1
        meta_w = mw
    cache_size = (1 << cache_bits) if cache_bits else 0
    codes = []
    for _ in range(groups):
        codes.append((_read_code(br, 256 + 24 + cache_size), _read_code(br, 256), _read_code(br, 256),
                      _read_code(br, 256), _read_code(br, 40)))
    total = w * h
    out = [0] * total
    cache = [0] * cache_size if cache_size else None
    shift = 32 - cache_bits
    i = 0
    x = y = 0
    g = codes[0]
    mask = (1 << mbits) - 1 if meta is not None else 0
    last_cached = 0
    while i < total:
        if meta is not None and (x & mask) == 0:
            g = codes[meta[(y >> mbits) * meta_w + (x >> mbits)]]
        s = g[0].read(br)
        if s < 256:
            r = g[1].read(br)
            b = g[2].read(br)
            a = g[3].read(br)
            out[i] = a << 24 | r << 16 | s << 8 | b
            i += 1
            x += 1
            if x == w:
                x = 0
                y += 1
        elif s < 280:
            length = _prefix_value(br, s - 256)
            code = _prefix_value(br, g[4].read(br))
            if code > 120:
                dist = code - 120
            else:
                c = _PLANE[code - 1]
                dist = (c >> 4) * w + 8 - (c & 15)
                if dist < 1:
                    dist = 1
            if dist > i or i + length > total:
                raise WebPError("bad back reference")
            for k in range(length):
                out[i + k] = out[i + k - dist]
            i += length
            x += length
            while x >= w:
                x -= w
                y += 1
            if meta is not None:
                g = codes[meta[(y >> mbits) * meta_w + (x >> mbits)]] if i < total else g
        else:
            out[i] = cache[s - 280]
            i += 1
            x += 1
            if x == w:
                x = 0
                y += 1
        if cache is not None:
            while last_cached < i:
                p = out[last_cached]
                cache[((p * 0x1e35a7bd) & 0xFFFFFFFF) >> shift] = p
                last_cached += 1
    return out


def _vp8l(d):
    if d[0] != 0x2F:
        raise WebPError("not a VP8L stream")
    v = d[1] | d[2] << 8 | d[3] << 16 | d[4] << 24
    w = (v & 0x3FFF) + 1
    h = ((v >> 14) & 0x3FFF) + 1
    br = _Bits(d[5:])
    return w, h, _image_stream(br, w, h)


def _image_stream(br, w, h):
    """The transforms, then the image, then the transforms undone."""
    transforms = []
    xsize = w
    while br.bit():
        kind = br.read(2)
        if kind in (0, 1):
            bits = br.read(3) + 2
            bw = (xsize + (1 << bits) - 1) >> bits
            bh = (h + (1 << bits) - 1) >> bits
            transforms.append((kind, bits, bw, _entropy_image(br, bw, bh, False), xsize))
        elif kind == 2:
            transforms.append((2, 0, 0, None, xsize))
        else:
            n = br.read(8) + 1
            pal = _entropy_image(br, n, 1, False)
            for k in range(1, n):                     # each entry is a delta from the one before
                a, b = pal[k], pal[k - 1]
                pal[k] = ((((a >> 24) + (b >> 24)) & 255) << 24 | ((((a >> 16) & 255) + ((b >> 16) & 255)) & 255) << 16 |
                          ((((a >> 8) & 255) + ((b >> 8) & 255)) & 255) << 8 | (((a & 255) + (b & 255)) & 255))
            bits = 3 if n <= 2 else 2 if n <= 4 else 1 if n <= 16 else 0
            transforms.append((3, bits, 0, pal, xsize))
            xsize = (xsize + (1 << bits) - 1) >> bits
    pixels = _entropy_image(br, xsize, h, True)
    for kind, bits, bw, data, tw in reversed(transforms):
        if kind == 0:
            _unpredict(pixels, tw, h, bits, bw, data)
        elif kind == 1:
            _uncolor(pixels, tw, h, bits, bw, data)
        elif kind == 2:
            for i in range(len(pixels)):
                p = pixels[i]
                g = (p >> 8) & 255
                pixels[i] = (p & 0xFF00FF00) | ((((p >> 16) & 255) + g) & 255) << 16 | (((p & 255) + g) & 255)
        else:
            pixels = _unindex(pixels, tw, h, bits, data)
    return pixels


def _add(a, b):
    return ((((a >> 24) + (b >> 24)) & 255) << 24 | ((((a >> 16) & 255) + ((b >> 16) & 255)) & 255) << 16 |
            ((((a >> 8) & 255) + ((b >> 8) & 255)) & 255) << 8 | (((a & 255) + (b & 255)) & 255))


def _avg(a, b):
    return ((((a >> 24) + (b >> 24)) >> 1) << 24 | ((((a >> 16) & 255) + ((b >> 16) & 255)) >> 1) << 16 |
            ((((a >> 8) & 255) + ((b >> 8) & 255)) >> 1) << 8 | (((a & 255) + (b & 255)) >> 1))


def _clip(v):
    return 0 if v < 0 else 255 if v > 255 else v


def _predict(mode, L, T, TL, TR):
    if mode == 0:
        return 0xFF000000
    if mode == 1:
        return L
    if mode == 2:
        return T
    if mode == 3:
        return TR
    if mode == 4:
        return TL
    if mode == 5:
        return _avg(_avg(L, TR), T)
    if mode == 6:
        return _avg(L, TL)
    if mode == 7:
        return _avg(L, T)
    if mode == 8:
        return _avg(TL, T)
    if mode == 9:
        return _avg(T, TR)
    if mode == 10:
        return _avg(_avg(L, TL), _avg(T, TR))
    if mode == 11:                                    # select
        pl = pt = 0
        for s in (24, 16, 8, 0):
            l, t, tl = (L >> s) & 255, (T >> s) & 255, (TL >> s) & 255
            p = l + t - tl
            pl += abs(p - l)
            pt += abs(p - t)
        return L if pl < pt else T
    if mode == 12:                                    # clamped add-subtract, full
        v = 0
        for s in (24, 16, 8, 0):
            v |= _clip(((L >> s) & 255) + ((T >> s) & 255) - ((TL >> s) & 255)) << s
        return v
    a = _avg(L, T)                                    # 13: clamped add-subtract, half
    v = 0
    for s in (24, 16, 8, 0):
        x = (a >> s) & 255
        d = x - ((TL >> s) & 255)
        v |= _clip(x + (d // 2 if d >= 0 else -((-d) // 2))) << s
    return v


def _unpredict(px, w, h, bits, bw, modes):
    px[0] = _add(px[0], 0xFF000000)
    for x in range(1, w):
        px[x] = _add(px[x], px[x - 1])
    for y in range(1, h):
        row = y * w
        px[row] = _add(px[row], px[row - w])
        mrow = (y >> bits) * bw
        for x in range(1, w):
            i = row + x
            mode = (modes[mrow + (x >> bits)] >> 8) & 15
            px[i] = _add(px[i], _predict(mode, px[i - 1], px[i - w], px[i - w - 1], px[i - w + 1]))


def _s8(v):
    return v - 256 if v > 127 else v


def _uncolor(px, w, h, bits, bw, codes):
    for y in range(h):
        mrow = (y >> bits) * bw
        row = y * w
        for x in range(w):
            c = codes[mrow + (x >> bits)]
            g2r, g2b, r2b = _s8(c & 255), _s8((c >> 8) & 255), _s8((c >> 16) & 255)
            p = px[row + x]
            g = _s8((p >> 8) & 255)
            r = (((p >> 16) & 255) + ((g2r * g) >> 5)) & 255
            b = ((p & 255) + ((g2b * g) >> 5) + ((r2b * _s8(r)) >> 5)) & 255
            px[row + x] = (p & 0xFF00FF00) | r << 16 | b


def _unindex(px, w, h, bits, pal):
    n = len(pal)
    out = [0] * (w * h)
    if bits == 0:
        for i in range(w * h):
            k = (px[i] >> 8) & 255
            out[i] = pal[k] if k < n else 0
        return out
    per = 1 << bits
    bpp = 8 >> bits
    mask = (1 << bpp) - 1
    pw = (w + per - 1) >> bits
    for y in range(h):
        for x in range(w):
            g = (px[y * pw + (x >> bits)] >> 8) & 255
            k = (g >> (bpp * (x & (per - 1)))) & mask
            out[y * w + x] = pal[k] if k < n else 0
    return out


# ======================================================================
# ALPH: the transparency of a lossy picture
# ======================================================================

def _apply_alpha(bgra, w, h, chunk):
    head = chunk[0]
    method, filt = head & 3, (head >> 2) & 3
    if method == 0:
        a = bytearray(chunk[1:1 + w * h])
    elif method == 1:
        argb = _image_stream(_Bits(chunk[1:]), w, h)
        a = bytearray(((p >> 8) & 255) for p in argb)
    else:
        return
    if filt:
        for y in range(h):
            row = y * w
            for x in range(w):
                i = row + x
                if y == 0:
                    pred = a[i - 1] if x else 0
                elif x == 0:
                    pred = a[i - w]
                elif filt == 1:
                    pred = a[i - 1]
                elif filt == 2:
                    pred = a[i - w]
                else:
                    pred = _clip(a[i - 1] + a[i - w] - a[i - w - 1])
                a[i] = (a[i] + pred) & 255
    for i in range(w * h):
        bgra[i * 4 + 3] = a[i]


# ======================================================================
# VP8: lossy (key frames, RFC 6386)
# ======================================================================

class _Bool:
    """The boolean entropy decoder (RFC 6386, section 7)."""

    def __init__(self, d):
        self.d = d
        self.n = len(d)
        self.value = (d[0] << 8 | d[1]) if self.n > 1 else 0
        self.pos = 2
        self.range = 255
        self.count = 0

    def get(self, prob):
        split = 1 + (((self.range - 1) * prob) >> 8)
        big = split << 8
        if self.value >= big:
            r = 1
            self.range -= split
            self.value -= big
        else:
            r = 0
            self.range = split
        while self.range < 128:
            self.value <<= 1
            self.range <<= 1
            self.count += 1
            if self.count == 8:
                self.count = 0
                if self.pos < self.n:
                    self.value |= self.d[self.pos]
                self.pos += 1
        return r

    def lit(self, n):
        v = 0
        for _ in range(n):
            v = v << 1 | self.get(128)
        return v

    def signed(self, n):
        v = self.lit(n)
        return -v if self.get(128) else v

    def opt_signed(self, n):
        return self.signed(n) if self.get(128) else 0


_B_DC, _B_TM, _B_VE, _B_HE = 0, 1, 2, 3
_YMODES4 = (0, 1, -1, 2, -2, 3, 4, 6, -3, 5, -4, -5, -6, 7, -7, 8, -8, -9)
_BANDS = (0, 1, 2, 3, 6, 4, 5, 6, 6, 6, 6, 6, 6, 6, 6, 7, 0)
_ZIGZAG = (0, 1, 4, 8, 5, 2, 3, 6, 9, 12, 13, 10, 7, 11, 14, 15)
_CAT = ((173, 148, 140), (176, 155, 140, 135), (180, 157, 141, 134, 130),
        (254, 254, 243, 230, 196, 177, 153, 140, 133, 130, 129))


def _large(br, p):
    if not br.get(p[3]):
        if not br.get(p[4]):
            return 2
        return 3 + br.get(p[5])
    if not br.get(p[6]):
        if not br.get(p[7]):
            return 5 + br.get(159)
        return 7 + 2 * br.get(165) + br.get(145)
    b1 = br.get(p[8])
    b0 = br.get(p[9 + b1])
    cat = 2 * b1 + b0
    v = 0
    for pr in _CAT[cat]:
        v += v + br.get(pr)
    return v + 3 + (8 << cat)


def _coeffs(br, probs, t, ctx, dq, n, out):
    """The tokens of one 4x4 block (from coefficient n): returns the index after the last non-zero one."""
    p = probs[t][_BANDS[n]][ctx]
    while n < 16:
        if not br.get(p[0]):
            return n
        while not br.get(p[1]):
            n += 1
            if n == 16:
                return 16
            p = probs[t][_BANDS[n]][0]
        if not br.get(p[2]):
            v = 1
            p = probs[t][_BANDS[n + 1]][1]
        else:
            v = _large(br, p)
            p = probs[t][_BANDS[n + 1]][2]
        if br.get(128):
            v = -v
        out[_ZIGZAG[n]] = v * (dq[0] if n == 0 else dq[1])
        n += 1
    return 16


def _mul1(a):
    return ((a * 20091) >> 16) + a


def _mul2(a):
    return (a * 35468) >> 16


def _idct_add(c, plane, o, stride):
    """Inverse DCT of the 16 coefficients c, added to the 4x4 pixels at plane[o]."""
    tmp = [0] * 16
    for i in range(4):
        a = c[i] + c[8 + i]
        b = c[i] - c[8 + i]
        cc = _mul2(c[4 + i]) - _mul1(c[12 + i])
        d = _mul1(c[4 + i]) + _mul2(c[12 + i])
        tmp[4 * i] = a + d
        tmp[4 * i + 1] = b + cc
        tmp[4 * i + 2] = b - cc
        tmp[4 * i + 3] = a - d
    for i in range(4):
        dc = tmp[i] + 4
        a = dc + tmp[8 + i]
        b = dc - tmp[8 + i]
        cc = _mul2(tmp[4 + i]) - _mul1(tmp[12 + i])
        d = _mul1(tmp[4 + i]) + _mul2(tmp[12 + i])
        r = o + i * stride
        plane[r] = _clip(plane[r] + ((a + d) >> 3))
        plane[r + 1] = _clip(plane[r + 1] + ((b + cc) >> 3))
        plane[r + 2] = _clip(plane[r + 2] + ((b - cc) >> 3))
        plane[r + 3] = _clip(plane[r + 3] + ((a - d) >> 3))


def _iwht(dc, blocks):
    tmp = [0] * 16
    for i in range(4):
        a0 = dc[i] + dc[12 + i]
        a1 = dc[4 + i] + dc[8 + i]
        a2 = dc[4 + i] - dc[8 + i]
        a3 = dc[i] - dc[12 + i]
        tmp[i] = a0 + a1
        tmp[8 + i] = a0 - a1
        tmp[4 + i] = a3 + a2
        tmp[12 + i] = a3 - a2
    for i in range(4):
        d = tmp[4 * i] + 3
        a0 = d + tmp[4 * i + 3]
        a1 = tmp[4 * i + 1] + tmp[4 * i + 2]
        a2 = tmp[4 * i + 1] - tmp[4 * i + 2]
        a3 = d - tmp[4 * i + 3]
        blocks[4 * i][0] = (a0 + a1) >> 3
        blocks[4 * i + 1][0] = (a3 + a2) >> 3
        blocks[4 * i + 2][0] = (a0 - a1) >> 3
        blocks[4 * i + 3][0] = (a3 - a2) >> 3


def _avg3(a, b, c):
    return (a + 2 * b + c + 2) >> 2


def _avg2(a, b):
    return (a + b + 1) >> 1


def _predict4(mode, P, o, s):
    """Predict the 4x4 block at P[o] (stride s) from its edges (sub-block modes)."""
    A, B, C, D = P[o - s], P[o - s + 1], P[o - s + 2], P[o - s + 3]
    E, F, G, H = P[o - s + 4], P[o - s + 5], P[o - s + 6], P[o - s + 7]
    X = P[o - s - 1]
    I, J, K, L = P[o - 1], P[o + s - 1], P[o + 2 * s - 1], P[o + 3 * s - 1]
    if mode == 0:                                       # DC
        v = (A + B + C + D + I + J + K + L + 4) >> 3
        rows = ((v, v, v, v),) * 4
    elif mode == 1:                                     # TM
        rows = [[_clip(t + l - X) for t in (A, B, C, D)] for l in (I, J, K, L)]
    elif mode == 2:                                     # VE
        r = (_avg3(X, A, B), _avg3(A, B, C), _avg3(B, C, D), _avg3(C, D, E))
        rows = (r, r, r, r)
    elif mode == 3:                                     # HE
        rows = [(v,) * 4 for v in (_avg3(X, I, J), _avg3(I, J, K), _avg3(J, K, L), _avg3(K, L, L))]
    elif mode == 4:                                     # RD
        rows = ((_avg3(A, X, I), _avg3(B, A, X), _avg3(C, B, A), _avg3(D, C, B)),
                (_avg3(X, I, J), _avg3(A, X, I), _avg3(B, A, X), _avg3(C, B, A)),
                (_avg3(I, J, K), _avg3(X, I, J), _avg3(A, X, I), _avg3(B, A, X)),
                (_avg3(J, K, L), _avg3(I, J, K), _avg3(X, I, J), _avg3(A, X, I)))
    elif mode == 5:                                     # VR
        rows = ((_avg2(X, A), _avg2(A, B), _avg2(B, C), _avg2(C, D)),
                (_avg3(I, X, A), _avg3(X, A, B), _avg3(A, B, C), _avg3(B, C, D)),
                (_avg3(J, I, X), _avg2(X, A), _avg2(A, B), _avg2(B, C)),
                (_avg3(K, J, I), _avg3(I, X, A), _avg3(X, A, B), _avg3(A, B, C)))
    elif mode == 6:                                     # LD
        rows = ((_avg3(A, B, C), _avg3(B, C, D), _avg3(C, D, E), _avg3(D, E, F)),
                (_avg3(B, C, D), _avg3(C, D, E), _avg3(D, E, F), _avg3(E, F, G)),
                (_avg3(C, D, E), _avg3(D, E, F), _avg3(E, F, G), _avg3(F, G, H)),
                (_avg3(D, E, F), _avg3(E, F, G), _avg3(F, G, H), _avg3(G, H, H)))
    elif mode == 7:                                     # VL
        rows = ((_avg2(A, B), _avg2(B, C), _avg2(C, D), _avg2(D, E)),
                (_avg3(A, B, C), _avg3(B, C, D), _avg3(C, D, E), _avg3(D, E, F)),
                (_avg2(B, C), _avg2(C, D), _avg2(D, E), _avg3(E, F, G)),
                (_avg3(B, C, D), _avg3(C, D, E), _avg3(D, E, F), _avg3(F, G, H)))
    elif mode == 8:                                     # HD
        rows = ((_avg2(I, X), _avg3(I, X, A), _avg3(X, A, B), _avg3(A, B, C)),
                (_avg2(J, I), _avg3(J, I, X), _avg2(I, X), _avg3(I, X, A)),
                (_avg2(K, J), _avg3(K, J, I), _avg2(J, I), _avg3(J, I, X)),
                (_avg2(L, K), _avg3(L, K, J), _avg2(K, J), _avg3(K, J, I)))
    else:                                               # HU
        rows = ((_avg2(I, J), _avg3(I, J, K), _avg2(J, K), _avg3(J, K, L)),
                (_avg2(J, K), _avg3(J, K, L), _avg2(K, L), _avg3(K, L, L)),
                (_avg2(K, L), _avg3(K, L, L), L, L),
                (L, L, L, L))
    for y in range(4):
        r = rows[y]
        k = o + y * s
        P[k] = r[0]
        P[k + 1] = r[1]
        P[k + 2] = r[2]
        P[k + 3] = r[3]


def _predict_big(mode, P, o, s, n, mb_x, mb_y):
    """16x16 (luma) or 8x8 (chroma) prediction: 0 DC, 1 TM, 2 V, 3 H."""
    if mode == 0:
        if mb_x and mb_y:
            v = (sum(P[o - s + k] for k in range(n)) + sum(P[o + k * s - 1] for k in range(n)) + n) // (2 * n)
        elif mb_y:
            v = (sum(P[o - s + k] for k in range(n)) + n // 2) // n
        elif mb_x:
            v = (sum(P[o + k * s - 1] for k in range(n)) + n // 2) // n
        else:
            v = 128
        row = bytes((v,)) * n
        for y in range(n):
            P[o + y * s:o + y * s + n] = row
    elif mode == 1:
        X = P[o - s - 1]
        top = [P[o - s + k] - X for k in range(n)]
        for y in range(n):
            l = P[o + y * s - 1]
            k0 = o + y * s
            for x in range(n):
                P[k0 + x] = _clip(top[x] + l)
    elif mode == 2:
        row = bytes(P[o - s:o - s + n])
        for y in range(n):
            P[o + y * s:o + y * s + n] = row
    else:
        for y in range(n):
            P[o + y * s:o + y * s + n] = bytes((P[o + y * s - 1],)) * n


def _vp8(d):
    if len(d) < 10:
        raise WebPError("truncated VP8")
    tag = d[0] | d[1] << 8 | d[2] << 16
    if tag & 1:
        raise WebPError("not a key frame")
    first_size = tag >> 5
    if d[3] != 0x9D or d[4] != 0x01 or d[5] != 0x2A:
        raise WebPError("bad VP8 start code")
    w = _u16(d, 6) & 0x3FFF
    h = _u16(d, 8) & 0x3FFF
    br = _Bool(d[10:10 + first_size])
    br.get(128)                                         # colour space
    br.get(128)                                         # clamping type
    # segmentation
    seg_on = br.get(128)
    seg_map = False
    seg_abs = False
    seg_q = [0, 0, 0, 0]
    seg_lf = [0, 0, 0, 0]
    seg_probs = [255, 255, 255]
    if seg_on:
        seg_map = br.get(128)
        if br.get(128):
            seg_abs = br.get(128)
            seg_q = [br.opt_signed(7) for _ in range(4)]
            seg_lf = [br.opt_signed(6) for _ in range(4)]
        if seg_map:
            seg_probs = [br.lit(8) if br.get(128) else 255 for _ in range(3)]
    # loop filter
    simple = br.get(128)
    level = br.lit(6)
    sharp = br.lit(3)
    ref_delta = [0] * 4
    mode_delta = [0] * 4
    use_delta = br.get(128)
    if use_delta and br.get(128):
        ref_delta = [br.opt_signed(6) for _ in range(4)]
        mode_delta = [br.opt_signed(6) for _ in range(4)]
    nparts = 1 << br.lit(2)
    # quantizers
    q0 = br.lit(7)
    dy1dc, dy2dc, dy2ac, duvdc, duvac = (br.opt_signed(4) for _ in range(5))

    def clipq(v, m=127):
        return 0 if v < 0 else m if v > m else v
    quants = []
    for s in range(4):
        q = (seg_q[s] if seg_abs else q0 + seg_q[s]) if seg_on else q0
        y2ac = (T.kAcTable[clipq(q + dy2ac)] * 101581) >> 16
        quants.append(((T.kDcTable[clipq(q + dy1dc)], T.kAcTable[clipq(q)]),
                       (T.kDcTable[clipq(q + dy2dc)] * 2, y2ac if y2ac >= 8 else 8),
                       (T.kDcTable[clipq(q + duvdc, 117)], T.kAcTable[clipq(q + duvac)])))
    br.get(128)                                         # refresh entropy probs
    probs = [[[[T.CoeffsProba0[((t * 8 + b) * 3 + c) * 11 + k] for k in range(11)] for c in range(3)]
              for b in range(8)] for t in range(4)]
    for t in range(4):
        for b in range(8):
            for c in range(3):
                for k in range(11):
                    if br.get(T.CoeffsUpdateProba[((t * 8 + b) * 3 + c) * 11 + k]):
                        probs[t][b][c][k] = br.lit(8)
    skip_prob = br.lit(8) if br.get(128) else None

    # the token partitions
    p = 10 + first_size
    sizes_at = p
    p += 3 * (nparts - 1)
    parts = []
    for i in range(nparts):
        n = _u24(d, sizes_at + 3 * i) if i < nparts - 1 else len(d) - p
        parts.append(_Bool(d[p:p + n]))
        p += n

    mbw, mbh = (w + 15) >> 4, (h + 15) >> 4
    # planes with a border: 1 row above, 1 column left, 4 columns right (luma top-right)
    ys = mbw * 16 + 5
    us = mbw * 8 + 1
    Y = bytearray(ys * (mbh * 16 + 1))
    U = bytearray(us * (mbh * 8 + 1))
    V = bytearray(us * (mbh * 8 + 1))
    Y[0:ys] = b"\x7f" * ys
    U[0:us] = b"\x7f" * us
    V[0:us] = b"\x7f" * us
    for r in range(1, mbh * 16 + 1):
        Y[r * ys] = 129
    for r in range(1, mbh * 8 + 1):
        U[r * us] = 129
        V[r * us] = 129
    top_modes = [0] * (mbw * 4)
    top_nz = [[0] * 9 for _ in range(mbw)]             # 4 Y, 2 U, 2 V, Y2
    finfo = []                                          # per macroblock: (limit, ilevel, hev, inner)
    for mb_y in range(mbh):
        tb = parts[mb_y & (nparts - 1)]
        left_modes = [0] * 4
        left_nz = [0] * 9
        for mb_x in range(mbw):
            seg = 0
            if seg_map:
                seg = (2 + br.get(seg_probs[2])) if br.get(seg_probs[0]) else br.get(seg_probs[1])
            skip = br.get(skip_prob) if skip_prob is not None else 0
            i4 = not br.get(145)
            bmodes = None
            if not i4:
                ymode = (_B_TM if br.get(128) else _B_HE) if br.get(156) else (_B_VE if br.get(163) else _B_DC)
                for k in range(4):
                    top_modes[mb_x * 4 + k] = ymode
                    left_modes[k] = ymode
            else:
                bmodes = [0] * 16
                for by in range(4):
                    for bx in range(4):
                        top = top_modes[mb_x * 4 + bx]
                        left = left_modes[by]
                        pr = T.kBModesProba[(top * 10 + left) * 9:(top * 10 + left) * 9 + 9]
                        i = _YMODES4[br.get(pr[0])]
                        while i > 0:
                            i = _YMODES4[2 * i + br.get(pr[i])]
                        m = -i
                        bmodes[by * 4 + bx] = m
                        top_modes[mb_x * 4 + bx] = m
                        left_modes[by] = m
            uvmode = _B_DC if not br.get(142) else (_B_VE if not br.get(114) else (_B_TM if br.get(183) else _B_HE))

            # residuals
            qy, qy2, quv = quants[seg]
            blocks = [[0] * 16 for _ in range(24)]
            tnz = top_nz[mb_x]
            nonzero = False
            if not skip:
                first = 0
                t = 3
                if not i4:
                    dc = [0] * 16
                    nz = _coeffs(tb, probs, 1, tnz[8] + left_nz[8], qy2, 0, dc)
                    tnz[8] = left_nz[8] = 1 if nz > 0 else 0
                    if nz > 1:
                        _iwht(dc, blocks)
                    else:
                        dc0 = (dc[0] + 3) >> 3
                        for k in range(16):
                            blocks[k][0] = dc0
                    nonzero = nonzero or nz > 0
                    first = 1
                    t = 0
                for by in range(4):
                    for bx in range(4):
                        nz = _coeffs(tb, probs, t, tnz[bx] + left_nz[by], qy, first, blocks[by * 4 + bx])
                        f = 1 if nz > first else 0
                        tnz[bx] = left_nz[by] = f
                        nonzero = nonzero or nz > first
                for ch in (0, 1):
                    for by in range(2):
                        for bx in range(2):
                            nz = _coeffs(tb, probs, 2, tnz[4 + ch * 2 + bx] + left_nz[4 + ch * 2 + by], quv, 0,
                                         blocks[16 + ch * 4 + by * 2 + bx])
                            f = 1 if nz > 0 else 0
                            tnz[4 + ch * 2 + bx] = left_nz[4 + ch * 2 + by] = f
                            nonzero = nonzero or nz > 0
            else:
                for k in range(8):
                    tnz[k] = left_nz[k] = 0
                if not i4:
                    tnz[8] = left_nz[8] = 0

            # reconstruction
            yo = (mb_y * 16 + 1) * ys + mb_x * 16 + 1
            if i4:
                tr = yo - ys + 16                       # the top-right 4 pixels
                if mb_y > 0 and mb_x == mbw - 1:
                    Y[tr:tr + 4] = bytes((Y[tr - 1],)) * 4
                for k in (4, 8, 12):
                    Y[tr + k * ys:tr + k * ys + 4] = Y[tr:tr + 4]
                for by in range(4):
                    for bx in range(4):
                        o = yo + by * 4 * ys + bx * 4
                        _predict4(bmodes[by * 4 + bx], Y, o, ys)
                        _idct_add(blocks[by * 4 + bx], Y, o, ys)
            else:
                _predict_big(ymode, Y, yo, ys, 16, mb_x, mb_y)
                for k in range(16):
                    _idct_add(blocks[k], Y, yo + (k >> 2) * 4 * ys + (k & 3) * 4, ys)
            uo = (mb_y * 8 + 1) * us + mb_x * 8 + 1
            for ch, P in ((0, U), (1, V)):
                _predict_big(uvmode, P, uo, us, 8, mb_x, mb_y)
                for k in range(4):
                    _idct_add(blocks[16 + ch * 4 + k], P, uo + (k >> 1) * 4 * us + (k & 1) * 4, us)

            # loop filter strength of this macroblock
            if level or seg_on:
                base = (seg_lf[seg] if seg_abs else level + seg_lf[seg]) if seg_on else level
                lv = base
                if use_delta:
                    lv += ref_delta[0]
                    if i4:
                        lv += mode_delta[0]
                lv = 0 if lv < 0 else 63 if lv > 63 else lv
                if lv:
                    il = lv
                    if sharp:
                        il >>= 2 if sharp > 4 else 1
                        if il > 9 - sharp:
                            il = 9 - sharp
                    if il < 1:
                        il = 1
                    finfo.append((2 * lv + il, il, 2 if lv >= 40 else 1 if lv >= 15 else 0, i4 or nonzero))
                else:
                    finfo.append(None)
            else:
                finfo.append(None)

    # the loop filter, over the finished picture
    if level or seg_on:
        k = 0
        for mb_y in range(mbh):
            for mb_x in range(mbw):
                f = finfo[k]
                k += 1
                if f is None:
                    continue
                limit, il, hev, inner = f
                yo = (mb_y * 16 + 1) * ys + mb_x * 16 + 1
                uo = (mb_y * 8 + 1) * us + mb_x * 8 + 1
                if simple:
                    if mb_x:
                        _simple(Y, yo, 1, ys, 16, limit + 4)
                    if inner:
                        for e in (4, 8, 12):
                            _simple(Y, yo + e, 1, ys, 16, limit)
                    if mb_y:
                        _simple(Y, yo, ys, 1, 16, limit + 4)
                    if inner:
                        for e in (4, 8, 12):
                            _simple(Y, yo + e * ys, ys, 1, 16, limit)
                else:
                    if mb_x:
                        _loop(Y, yo, 1, ys, 16, limit + 4, il, hev, True)
                        _loop(U, uo, 1, us, 8, limit + 4, il, hev, True)
                        _loop(V, uo, 1, us, 8, limit + 4, il, hev, True)
                    if inner:
                        for e in (4, 8, 12):
                            _loop(Y, yo + e, 1, ys, 16, limit, il, hev, False)
                        _loop(U, uo + 4, 1, us, 8, limit, il, hev, False)
                        _loop(V, uo + 4, 1, us, 8, limit, il, hev, False)
                    if mb_y:
                        _loop(Y, yo, ys, 1, 16, limit + 4, il, hev, True)
                        _loop(U, uo, us, 1, 8, limit + 4, il, hev, True)
                        _loop(V, uo, us, 1, 8, limit + 4, il, hev, True)
                    if inner:
                        for e in (4, 8, 12):
                            _loop(Y, yo + e * ys, ys, 1, 16, limit, il, hev, False)
                        _loop(U, uo + 4 * us, us, 1, 8, limit, il, hev, False)
                        _loop(V, uo + 4 * us, us, 1, 8, limit, il, hev, False)

    # YUV -> BGRA, with the chroma rows interpolated as libwebp's "fancy" upsampler does
    out = bytearray(w * h * 4)
    _fancy_row(out, 0, Y, ys + 1, U, V, us + 1, us + 1, w, None, 0)
    k = 1
    while 2 * k - 1 < h:
        top_c = k * us + 1
        cur_c = (k + 1) * us + 1 if k < (h + 1) >> 1 else top_c
        bottom = 2 * k if 2 * k < h else None
        _fancy_row(out, 2 * k - 1, Y, (2 * k) * ys + 1, U, V, top_c, cur_c, w,
                   bottom, (2 * k + 1) * ys + 1)
        k += 1
    return w, h, out


def _bgra(out, o, y, u, v):
    yy = (y * 19077) >> 8
    out[o] = _c8(yy + ((u * 33050) >> 8) - 17685)
    out[o + 1] = _c8(yy - ((u * 6419) >> 8) - ((v * 13320) >> 8) + 8708)
    out[o + 2] = _c8(yy + ((v * 26149) >> 8) - 14234)
    out[o + 3] = 255


def _fancy_row(out, row, Y, yt, U, V, ct, cc, w, row2, yb):
    """One row (or a pair: row and row2 = row + 1) of pixels; ct/cc: the chroma
    rows above and at these rows. u and v are packed in one number (u low,
    v high) exactly as libwebp packs them, so the rounding is the same."""
    M = 0xFFFFFFFF
    W = w * 4
    o1 = row * W
    o2 = (row2 if row2 is not None else row) * W
    tl = U[ct] | V[ct] << 16
    l = U[cc] | V[cc] << 16
    uv0 = ((3 * tl + l + 0x00020002) & M) >> 2
    _bgra(out, o1, Y[yt], uv0 & 255, uv0 >> 16)
    if row2 is not None:
        uv0 = ((3 * l + tl + 0x00020002) & M) >> 2
        _bgra(out, o2, Y[yb], uv0 & 255, uv0 >> 16)
    last = (w - 1) >> 1
    for x in range(1, last + 1):
        t = U[ct + x] | V[ct + x] << 16
        uv = U[cc + x] | V[cc + x] << 16
        avg = (tl + t + l + uv + 0x00080008) & M
        d12 = ((avg + 2 * (t + l)) & M) >> 3
        d03 = ((avg + 2 * (tl + uv)) & M) >> 3
        a = ((d12 + tl) & M) >> 1
        b = ((d03 + t) & M) >> 1
        _bgra(out, o1 + (2 * x - 1) * 4, Y[yt + 2 * x - 1], a & 255, a >> 16)
        _bgra(out, o1 + 2 * x * 4, Y[yt + 2 * x], b & 255, b >> 16)
        if row2 is not None:
            a = ((d03 + l) & M) >> 1
            b = ((d12 + uv) & M) >> 1
            _bgra(out, o2 + (2 * x - 1) * 4, Y[yb + 2 * x - 1], a & 255, a >> 16)
            _bgra(out, o2 + 2 * x * 4, Y[yb + 2 * x], b & 255, b >> 16)
        tl = t
        l = uv
    if not w & 1:
        uv0 = ((3 * tl + l + 0x00020002) & M) >> 2
        _bgra(out, o1 + (w - 1) * 4, Y[yt + w - 1], uv0 & 255, uv0 >> 16)
        if row2 is not None:
            uv0 = ((3 * l + tl + 0x00020002) & M) >> 2
            _bgra(out, o2 + (w - 1) * 4, Y[yb + w - 1], uv0 & 255, uv0 >> 16)


def _c8(v):
    return 0 if v < 0 else 255 if v >= 16384 else v >> 6


# ---- the loop filter (RFC 6386 section 15) ----

def _s1(v):
    return -128 if v < -128 else 127 if v > 127 else v


def _s2(v):
    return -16 if v < -16 else 15 if v > 15 else v


def _simple(P, o, step, along, n, thresh):
    t2 = 2 * thresh + 1
    for i in range(n):
        q = o + i * along
        p1, p0, q0, q1 = P[q - 2 * step], P[q - step], P[q], P[q + step]
        if 4 * abs(p0 - q0) + abs(p1 - q1) <= t2:
            a = 3 * (q0 - p0) + _s1(p1 - q1)
            P[q - step] = _clip(p0 + _s2((a + 3) >> 3))
            P[q] = _clip(q0 - _s2((a + 4) >> 3))


def _loop(P, o, step, along, n, thresh, ithresh, hev_t, edge):
    """The normal filter across one edge: edge=True for a macroblock edge (6 pixels), else inner (4)."""
    t2 = 2 * thresh + 1
    for i in range(n):
        q = o + i * along
        p3, p2, p1, p0 = P[q - 4 * step], P[q - 3 * step], P[q - 2 * step], P[q - step]
        q0, q1, q2, q3 = P[q], P[q + step], P[q + 2 * step], P[q + 3 * step]
        if 4 * abs(p0 - q0) + abs(p1 - q1) > t2:
            continue
        if (abs(p3 - p2) > ithresh or abs(p2 - p1) > ithresh or abs(p1 - p0) > ithresh or
                abs(q3 - q2) > ithresh or abs(q2 - q1) > ithresh or abs(q1 - q0) > ithresh):
            continue
        if abs(p1 - p0) > hev_t or abs(q1 - q0) > hev_t:      # high edge variance
            a = 3 * (q0 - p0) + _s1(p1 - q1)
            P[q - step] = _clip(p0 + _s2((a + 3) >> 3))
            P[q] = _clip(q0 - _s2((a + 4) >> 3))
        elif edge:
            a = _s1(3 * (q0 - p0) + _s1(p1 - q1))
            a1 = (27 * a + 63) >> 7
            a2 = (18 * a + 63) >> 7
            a3 = (9 * a + 63) >> 7
            P[q - 3 * step] = _clip(p2 + a3)
            P[q - 2 * step] = _clip(p1 + a2)
            P[q - step] = _clip(p0 + a1)
            P[q] = _clip(q0 - a1)
            P[q + step] = _clip(q1 - a2)
            P[q + 2 * step] = _clip(q2 - a3)
        else:
            a = 3 * (q0 - p0)
            a1 = _s2((a + 4) >> 3)
            a2 = _s2((a + 3) >> 3)
            a3 = (a1 + 1) >> 1
            P[q - 2 * step] = _clip(p1 + a3)
            P[q - step] = _clip(p0 + a2)
            P[q] = _clip(q0 - a1)
            P[q + step] = _clip(q1 - a3)
