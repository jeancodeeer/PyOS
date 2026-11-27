# AAC (AAC-LC, ISO 14496-3) in Python: the audio of MP4 videos and of
# YouTube. Long and short windows, M/S and intensity stereo, perceptual
# noise substitution, TNS, sine and KBD windows. HE-AAC streams play
# their AAC-LC core (without the extra high band).
#
#   dec = AAC(config)              # the AudioSpecificConfig from the MP4 (esds)
#   pcm = dec.decode(frame)        # one raw frame -> 16-bit samples, interleaved
#   rate, channels = dec.format()
import math
import struct
from media import aac_tables as T

ONLY_LONG, LONG_START, EIGHT_SHORT, LONG_STOP = 0, 1, 2, 3
ZERO_HCB, NOISE_HCB, INTENSITY_HCB2, INTENSITY_HCB = 0, 13, 14, 15


class AACError(ValueError):
    pass


class _Bits:
    """Bits, most significant first."""

    def __init__(self, data):
        self.d = bytes(data) + bytes(8)
        self.pos = 0
        self.n = len(data) * 8

    def get(self, k):
        if k == 0:
            return 0
        p = self.pos
        self.pos = p + k
        d = self.d
        i = p >> 3
        v = 0
        need = k + (p & 7)
        while need > 0:
            v = v << 8 | d[i]
            i += 1
            need -= 8
        return (v >> -need) & ((1 << k) - 1)

    def bit(self):
        p = self.pos
        self.pos = p + 1
        return (self.d[p >> 3] >> (7 - (p & 7))) & 1

    def align(self):
        self.pos = (self.pos + 7) & ~7


def _huff(br, info, table):
    """One symbol of a canonical Huffman code (Helix's layout: counts per length, then symbols)."""
    maxbits, count, off = info
    code = 0
    first = 0
    idx = off
    for L in range(maxbits):
        code = code << 1 | br.bit()
        c = count[L]
        if code - first < c:
            return table[idx + code - first]
        idx += c
        first = (first + c) << 1
    raise AACError("bad Huffman code")


def _sx(v, bits):
    """Sign-extend the low `bits` bits of v."""
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def _escape(br):
    n = 4
    while br.bit():
        n += 1
    return (1 << n) + br.get(n)


def _spectral(br, cb, n, out, o):
    """n values of codebook cb into out[o:]."""
    info = T.SPEC_INFO[cb - 1]
    tab = T.SPEC
    end = o + n
    if cb <= 4:                                       # quads
        while o < end:
            v = _huff(br, info, tab)
            vals = [_sx(v >> 9, 3), _sx(v >> 6, 3), _sx(v >> 3, 3), _sx(v, 3)]
            if (v >> 12) & 7:                         # unsigned book: sign bits follow
                for k in range(4):
                    if vals[k] and br.bit():
                        vals[k] = -vals[k]
            out[o:o + 4] = vals
            o += 4
    elif cb <= 10:                                    # pairs
        while o < end:
            v = _huff(br, info, tab)
            y, z = _sx(v >> 5, 5), _sx(v, 5)
            if (v >> 10) & 3:
                if y and br.bit():
                    y = -y
                if z and br.bit():
                    z = -z
            out[o] = y
            out[o + 1] = z
            o += 2
    else:                                             # 11: pairs with escapes
        while o < end:
            v = _huff(br, info, tab)
            y, z = _sx(v >> 6, 6), _sx(v, 6)
            ns = (v >> 12) & 3
            sy = sz = 0
            if ns:
                if y:
                    sy = br.bit()
                if z:
                    sz = br.bit()
            if y == 16:
                y = _escape(br)
            if z == 16:
                z = _escape(br)
            out[o] = -y if sy else y
            out[o + 1] = -z if sz else z
            o += 2


# 2^(x/4) and |q|^(4/3), cached
_POW43 = [i ** (4.0 / 3.0) for i in range(8192 + 1)]


def _pow43(q):
    if q < 0:
        return -_POW43[-q] if -q <= 8192 else -((-q) ** (4.0 / 3.0))
    return _POW43[q] if q <= 8192 else q ** (4.0 / 3.0)


# ---- windows ----

def _bessel_i0(x):
    s = 1.0
    t = 1.0
    k = 1
    while True:
        t *= (x / 2.0 / k) ** 2
        s += t
        if t < 1e-12 * s:
            return s
        k += 1


def _kbd(n, alpha):
    """The Kaiser-Bessel-derived window of length n (rising half: n/2 values)."""
    half = n // 2
    w = [_bessel_i0(math.pi * alpha * math.sqrt(1.0 - (2.0 * k / half - 1.0) ** 2)) for k in range(half + 1)]
    total = sum(w)
    out = []
    acc = 0.0
    for k in range(half):
        acc += w[k]
        out.append(math.sqrt(acc / total))
    return out


def _sine(n):
    return [math.sin(math.pi / n * (k + 0.5)) for k in range(n // 2)]


_WIN = {}


def _window(shape, n):
    key = (shape, n)
    w = _WIN.get(key)
    if w is None:
        w = _kbd(n, 4.0 if n == 2048 else 6.0) if shape else _sine(n)
        _WIN[key] = w
    return w


# ---- the IMDCT, through a DCT-IV done with a complex FFT ----

_TW = {}


def _twiddles(M):
    t = _TW.get(M)
    if t is None:
        H = M // 2
        pre = [(math.cos(-math.pi * (n + 0.25) / M), math.sin(-math.pi * (n + 0.25) / M)) for n in range(H)]
        post = [(math.cos(-math.pi * k / M), math.sin(-math.pi * k / M)) for k in range(H)]
        rev = [0] * H
        bits = H.bit_length() - 1
        for i in range(H):
            r = 0
            for b in range(bits):
                if i >> b & 1:
                    r |= 1 << (bits - 1 - b)
            rev[i] = r
        roots = [(math.cos(-2 * math.pi * k / H), math.sin(-2 * math.pi * k / H)) for k in range(H // 2)]
        t = (pre, post, rev, roots)
        _TW[M] = t
    return t


def _imdct(X, M):
    """2M output samples from M spectral values (scaled by 1/M, as the standard says)."""
    pre, post, rev, roots = _twiddles(M)
    H = M // 2
    re = [0.0] * H
    im = [0.0] * H
    for n in range(H):
        a = X[2 * n]
        b = X[M - 1 - 2 * n]
        c, s = pre[n]
        r = rev[n]
        re[r] = a * c - b * s
        im[r] = a * s + b * c
    size = 2
    while size <= H:
        half = size >> 1
        step = H // size
        for start in range(0, H, size):
            for k in range(half):
                wr, wi = roots[k * step]
                i = start + k
                j = i + half
                xr = re[j] * wr - im[j] * wi
                xi = re[j] * wi + im[j] * wr
                re[j] = re[i] - xr
                im[j] = im[i] - xi
                re[i] += xr
                im[i] += xi
        size <<= 1
    y = [0.0] * M
    for k in range(H):
        c, s = post[k]
        a = re[k] * c - im[k] * s
        b = re[k] * s + im[k] * c
        y[2 * k] = a
        y[M - 1 - 2 * k] = -b
    out = [0.0] * (2 * M)
    sc = 1.0 / M
    for n in range(H):
        out[n] = y[H + n] * sc
        out[M - 1 - n] = -y[H + n] * sc
        out[M + n] = -y[H - 1 - n] * sc
        out[2 * M - 1 - n] = -y[H - 1 - n] * sc
    return out


# ---- TNS ----

def _tns_coefs(order, res, compress, raw):
    bits = res + 3
    iq = ((1 << (bits - 1)) - 0.5) / (math.pi / 2.0)
    iqm = ((1 << (bits - 1)) + 0.5) / (math.pi / 2.0)
    k = []
    for c in raw:
        c = _sx(c, bits - compress)
        k.append(math.sin(c / (iq if c >= 0 else iqm)))
    a = [1.0]
    for m in range(1, order + 1):
        b = a + [0.0]
        for i in range(1, m):
            b[i] = a[i] + k[m - 1] * a[m - i]
        b[m] = k[m - 1]
        a = b
    return a


class _ICS:
    __slots__ = ("seq", "shape", "max_sfb", "groups", "group_len", "cb", "sf", "spec", "num_swb", "swb", "tns")


class AAC:
    def __init__(self, config=b"\x12\x10"):
        c = bytes(config)
        if len(c) < 2:
            raise AACError("AAC config too short")
        profile = c[0] >> 3
        self.sr_index = ((c[0] & 7) << 1) | (c[1] >> 7)
        chans = (c[1] >> 3) & 15
        if profile == 5 or profile == 29:             # HE-AAC: the core is AAC-LC
            pass
        self.rate = T.sampRateTab[self.sr_index] if self.sr_index < 12 else 44100
        self.channels = chans if chans else 2
        si = self.sr_index if self.sr_index < 12 else 4
        o = T.sfBandTabLongOffset[si]
        self.swb_long = T.sfBandTabLong[o:o + T.sfBandTotalLong[si] + 1]
        o = T.sfBandTabShortOffset[si]
        self.swb_short = T.sfBandTabShort[o:o + T.sfBandTotalShort[si] + 1]
        self.tns_max_long = T.tnsMaxBandsLong[si]
        self.tns_max_short = T.tnsMaxBandsShort[si]
        self.overlap = []
        self.prev_shape = []
        self.seed = 0x1F2E3D4C

    def format(self):
        return self.rate, self.channels

    def close(self):
        pass

    # ---- one channel's data ----
    def _ics_info(self, br, ics):
        br.bit()                                      # reserved
        ics.seq = br.get(2)
        ics.shape = br.bit()
        if ics.seq == EIGHT_SHORT:
            ics.max_sfb = br.get(4)
            grouping = br.get(7)
            ics.group_len = [1]
            for w in range(1, 8):
                if grouping >> (7 - w) & 1:
                    ics.group_len[-1] += 1
                else:
                    ics.group_len.append(1)
            ics.groups = len(ics.group_len)
            ics.swb = self.swb_short
            ics.num_swb = len(self.swb_short) - 1
        else:
            ics.max_sfb = br.get(6)
            if br.bit():
                raise AACError("AAC Main prediction is not supported")
            ics.groups = 1
            ics.group_len = [1]
            ics.swb = self.swb_long
            ics.num_swb = len(self.swb_long) - 1
        if ics.max_sfb > ics.num_swb:
            raise AACError("bad max_sfb")

    def _ics(self, br, common, ics):
        gain = br.get(8)
        if not common:
            ics = _ICS()
            self._ics_info(br, ics)
        else:                                         # a copy of the shared window info
            info = ics
            ics = _ICS()
            for k in ("seq", "shape", "max_sfb", "groups", "group_len", "num_swb", "swb"):
                setattr(ics, k, getattr(info, k))
        short = ics.seq == EIGHT_SHORT
        # section data: the codebook of every band
        cb = []
        bits = 3 if short else 5
        esc = (1 << bits) - 1
        for g in range(ics.groups):
            row = [0] * ics.max_sfb
            k = 0
            while k < ics.max_sfb:
                book = br.get(4)
                n = 0
                while True:
                    inc = br.get(bits)
                    n += inc
                    if inc != esc:
                        break
                if k + n > ics.max_sfb:
                    raise AACError("bad section")
                for i in range(k, k + n):
                    row[i] = book
                k += n
            cb.append(row)
        ics.cb = cb
        # scale factors
        sf = []
        g_gain = gain
        noise = gain - 90
        is_pos = 0
        first_noise = True
        for g in range(ics.groups):
            row = [0] * ics.max_sfb
            for b in range(ics.max_sfb):
                c = cb[g][b]
                if c == ZERO_HCB:
                    continue
                if c == INTENSITY_HCB or c == INTENSITY_HCB2:
                    is_pos += _huff(br, T.SF_INFO, T.SF)
                    row[b] = is_pos
                elif c == NOISE_HCB:
                    if first_noise:
                        first_noise = False
                        noise += br.get(9) - 256
                    else:
                        noise += _huff(br, T.SF_INFO, T.SF)
                    row[b] = noise
                else:
                    g_gain += _huff(br, T.SF_INFO, T.SF)
                    row[b] = g_gain
            sf.append(row)
        ics.sf = sf
        # pulses
        pulses = None
        if br.bit():
            if short:
                raise AACError("pulse data in a short window")
            n = br.get(2) + 1
            start = br.get(6)
            pulses = (start, [(br.get(5), br.get(4)) for _ in range(n)])
        # TNS
        ics.tns = None
        if br.bit():
            ics.tns = []
            for w in range(8 if short else 1):
                nf = br.get(1 if short else 2)
                filters = []
                if nf:
                    res = br.bit()
                    for _ in range(nf):
                        length = br.get(4 if short else 6)
                        order = br.get(3 if short else 5)
                        if order:
                            direction = br.bit()
                            compress = br.bit()
                            raw = [br.get(res + 3 - compress) for _ in range(order)]
                            filters.append((length, order, direction, _tns_coefs(order, res, compress, raw)))
                        else:
                            filters.append((length, 0, 0, None))
                ics.tns.append(filters)
        if br.bit():
            raise AACError("gain control is not supported")
        # spectral data, then dequantized and put in window order
        q = [0] * 1024
        swb = ics.swb
        if not short:
            for b in range(ics.max_sfb):
                c = cb[0][b]
                if c and c < NOISE_HCB:
                    _spectral(br, c, swb[b + 1] - swb[b], q, swb[b])
            if pulses:
                start, pl = pulses
                k = swb[start]
                for off, amp in pl:
                    k += off
                    if k < 1024:
                        q[k] += amp if q[k] >= 0 else -amp
            spec = [0.0] * 1024
            for b in range(ics.max_sfb):
                c = cb[0][b]
                if not c or c >= NOISE_HCB:
                    continue
                scale = 2.0 ** (0.25 * (sf[0][b] - 100))
                for k in range(swb[b], swb[b + 1]):
                    if q[k]:
                        spec[k] = _pow43(q[k]) * scale
        else:
            spec = [0.0] * 1024
            win = 0
            for g in range(ics.groups):
                glen = ics.group_len[g]
                # the data of a group is band by band, each band window by window
                for b in range(ics.max_sfb):
                    c = cb[g][b]
                    width = swb[b + 1] - swb[b]
                    if c and c < NOISE_HCB:
                        vals = [0] * (width * glen)
                        _spectral(br, c, width * glen, vals, 0)
                        scale = 2.0 ** (0.25 * (sf[g][b] - 100))
                        for wi in range(glen):
                            base = (win + wi) * 128 + swb[b]
                            for k in range(width):
                                v = vals[wi * width + k]
                                if v:
                                    spec[base + k] = _pow43(v) * scale
                win += glen
        ics.spec = spec
        return ics

    def _noise(self, ics):
        """Perceptual noise substitution: noise of the coded energy where the bands say so."""
        win = 0
        swb = ics.swb
        for g in range(ics.groups):
            for wi in range(ics.group_len[g]):
                base = (win + wi) * 128 if ics.seq == EIGHT_SHORT else 0
                for b in range(ics.max_sfb):
                    if ics.cb[g][b] != NOISE_HCB:
                        continue
                    lo, hi = base + swb[b], base + swb[b + 1]
                    energy = 0.0
                    for k in range(lo, hi):
                        self.seed = (self.seed * 1664525 + 1013904223) & 0xFFFFFFFF
                        v = float(self.seed - (1 << 32) if self.seed >> 31 else self.seed)
                        ics.spec[k] = v
                        energy += v * v
                    scale = 2.0 ** (0.25 * ics.sf[g][b]) / math.sqrt(energy) if energy else 0.0
                    for k in range(lo, hi):
                        ics.spec[k] *= scale
            win += ics.group_len[g]

    def _tns(self, ics):
        if not ics.tns:
            return
        short = ics.seq == EIGHT_SHORT
        tmax = self.tns_max_short if short else self.tns_max_long
        swb = ics.swb
        for w, filters in enumerate(ics.tns):
            base = w * 128 if short else 0
            bottom = ics.num_swb
            for length, order, direction, lpc in filters:
                top = bottom
                bottom = max(top - length, 0)
                if not order:
                    continue
                start = swb[min(bottom, tmax, ics.max_sfb)]
                end = swb[min(top, tmax, ics.max_sfb)]
                size = end - start
                if size <= 0:
                    continue
                s = ics.spec
                if direction:
                    pos, inc = base + end - 1, -1
                else:
                    pos, inc = base + start, 1
                state = [0.0] * order
                for _ in range(size):
                    y = s[pos]
                    for i in range(order):
                        y -= lpc[i + 1] * state[i]
                    for i in range(order - 1, 0, -1):
                        state[i] = state[i - 1]
                    state[0] = y
                    s[pos] = y
                    pos += inc

    def _filterbank(self, ics, ch):
        while len(self.overlap) <= ch:
            self.overlap.append([0.0] * 1024)
            self.prev_shape.append(0)
        prev = self.prev_shape[ch]
        ov = self.overlap[ch]
        spec = ics.spec
        long_prev = _window(prev, 2048)
        long_cur = _window(ics.shape, 2048)
        short_prev = _window(prev, 256)
        short_cur = _window(ics.shape, 256)
        out = [0.0] * 1024
        if ics.seq != EIGHT_SHORT:
            x = _imdct(spec, 1024)
            # the first half, windowed, plus the overlap
            if ics.seq == LONG_STOP:
                for n in range(448):
                    out[n] = ov[n]
                for n in range(128):
                    out[448 + n] = x[448 + n] * short_prev[n] + ov[448 + n]
                for n in range(576, 1024):
                    out[n] = x[n] + ov[n]
            else:
                for n in range(1024):
                    out[n] = x[n] * long_prev[n] + ov[n]
            # the second half becomes the next overlap
            if ics.seq == LONG_START:
                for n in range(448):
                    ov[n] = x[1024 + n]
                for n in range(128):
                    ov[448 + n] = x[1472 + n] * short_cur[127 - n]
                for n in range(576, 1024):
                    ov[n] = 0.0
            else:
                for n in range(1024):
                    ov[n] = x[1024 + n] * long_cur[1023 - n]
        else:
            buf = [0.0] * 2048
            for w in range(8):
                x = _imdct(spec[w * 128:(w + 1) * 128], 128)
                wl = short_prev if w == 0 else short_cur
                base = 448 + w * 128
                for n in range(128):
                    buf[base + n] += x[n] * wl[n]
                    buf[base + 128 + n] += x[128 + n] * short_cur[127 - n]
            for n in range(1024):
                out[n] = ov[n] + buf[n]
            for n in range(1024):
                ov[n] = buf[1024 + n]
        self.prev_shape[ch] = ics.shape
        return out

    # ---- a frame ----
    def decode(self, frame):
        """One raw AAC frame -> bytes of 16-bit PCM, channels interleaved."""
        br = _Bits(frame)
        outs = []
        while br.pos + 3 <= br.n:
            kind = br.get(3)
            if kind == 7:                             # END
                break
            if kind in (0, 3):                        # single channel (or LFE)
                br.get(4)
                ics = self._ics(br, False, None)
                self._noise(ics)
                self._tns(ics)
                outs.append(self._filterbank(ics, len(outs)))
            elif kind == 1:                           # channel pair
                br.get(4)
                common = br.bit()
                info = None
                ms = 0
                ms_used = None
                if common:
                    info = _ICS()
                    self._ics_info(br, info)
                    ms = br.get(2)
                    if ms == 1:
                        ms_used = [[br.bit() for _ in range(info.max_sfb)] for _ in range(info.groups)]
                left = self._ics(br, common, info)
                right = self._ics(br, common, info if common else None)
                if common:
                    self._stereo(left, right, ms, ms_used)
                self._noise(left)
                self._noise(right)
                self._tns(left)
                self._tns(right)
                outs.append(self._filterbank(left, len(outs)))
                outs.append(self._filterbank(right, len(outs)))
            elif kind == 4:                           # data stream: skipped
                br.get(4)
                align = br.bit()
                n = br.get(8)
                if n == 255:
                    n += br.get(8)
                if align:
                    br.align()
                br.pos += 8 * n
            elif kind == 6:                           # fill (and SBR data): skipped
                n = br.get(4)
                if n == 15:
                    n += br.get(8) - 1
                br.pos += 8 * n
            else:
                raise AACError("unsupported AAC element %d" % kind)
        if not outs:
            return b""
        self.channels = len(outs)
        pcm = []
        for i in range(1024):
            for o in outs:
                v = o[i]
                v = int(v + 0.5) if v >= 0 else int(v - 0.5)
                pcm.append(32767 if v > 32767 else -32768 if v < -32768 else v)
        return struct.pack("<%dh" % len(pcm), *pcm)

    def _stereo(self, left, right, ms, ms_used):
        """M/S and intensity stereo (on the dequantized spectra)."""
        swb = left.swb
        win = 0
        for g in range(left.groups):
            for wi in range(left.group_len[g]):
                base = (win + wi) * 128 if left.seq == EIGHT_SHORT else 0
                for b in range(left.max_sfb):
                    rc = right.cb[g][b]
                    lo, hi = base + swb[b], base + swb[b + 1]
                    used = ms == 2 or (ms == 1 and ms_used[g][b])
                    if rc == INTENSITY_HCB or rc == INTENSITY_HCB2:
                        sign = 1.0 if rc == INTENSITY_HCB else -1.0
                        if ms == 1 and ms_used[g][b]:
                            sign = -sign
                        scale = sign * 2.0 ** (-0.25 * right.sf[g][b])
                        for k in range(lo, hi):
                            right.spec[k] = left.spec[k] * scale
                    elif used and rc != NOISE_HCB and left.cb[g][b] != NOISE_HCB:
                        for k in range(lo, hi):
                            m = left.spec[k]
                            s = right.spec[k]
                            left.spec[k] = m + s
                            right.spec[k] = m - s
            win += left.group_len[g]
