# MP3 (MPEG-1/2/2.5 audio layer III) in Python: a port of minimp3's
# decoder. The tables are in media/mp3_tables.py.
#
#   dec = MP3()
#   pcm, used = dec.decode(data)    # 16-bit samples (interleaved), bytes of data consumed
#   rate, channels = dec.format()
#
# Slower than real time on most machines: the music player decodes ahead.
import struct
from media import mp3_tables as T

_POW43 = T.g_pow43
_TABS = T.tabs


def _mono(h):
    return (h[3] & 0xC0) == 0xC0


def _ms(h):
    return (h[3] & 0xE0) == 0x60


def _free(h):
    return (h[2] & 0xF0) == 0


def _crc(h):
    return not (h[1] & 1)


def _pad_bit(h):
    return h[2] & 2


def _mpeg1(h):
    return h[1] & 8


def _not25(h):
    return h[1] & 0x10


def _i_stereo(h):
    return h[3] & 0x10


def _ms_stereo(h):
    return h[3] & 0x20


def _layer(h):
    return (h[1] >> 1) & 3


def _bitrate_i(h):
    return h[2] >> 4


def _sr_i(h):
    return (h[2] >> 2) & 3


def _my_sr(h):
    return _sr_i(h) + (((h[1] >> 3) & 1) + ((h[1] >> 4) & 1)) * 3


def _is_576(h):
    return (h[1] & 14) == 2


def _is_l1(h):
    return (h[1] & 6) == 6


def _valid(h):
    return (h[0] == 0xFF and ((h[1] & 0xF0) == 0xF0 or (h[1] & 0xFE) == 0xE2) and _layer(h) != 0 and
            _bitrate_i(h) != 15 and _sr_i(h) != 3)


def _compare(h1, h2):
    return (_valid(h2) and ((h1[1] ^ h2[1]) & 0xFE) == 0 and ((h1[2] ^ h2[2]) & 0x0C) == 0 and
            not (_free(h1) ^ _free(h2)))


def _kbps(h):
    return 2 * T.halfrate[(1 if _mpeg1(h) else 0) * 45 + (_layer(h) - 1) * 15 + _bitrate_i(h)]


def _hz(h):
    return (44100, 48000, 32000)[_sr_i(h)] >> (0 if _mpeg1(h) else 1) >> (0 if _not25(h) else 1)


def _samples(h):
    return 384 if _is_l1(h) else (1152 >> (1 if _is_576(h) else 0))


def _frame_bytes(h, free_size):
    n = _samples(h) * _kbps(h) * 125 // _hz(h)
    if _is_l1(h):
        n &= ~3
    return n if n else free_size


def _padding(h):
    return (4 if _is_l1(h) else 1) if _pad_bit(h) else 0


class _Bits:
    """Bits, most significant first; reading past the end gives zeros."""

    def __init__(self, data, nbytes):
        self.buf = bytes(data[:nbytes]) + bytes(8)
        self.pos = 0
        self.limit = nbytes * 8

    def get(self, n):
        p = self.pos
        self.pos = p + n
        if self.pos > self.limit:
            return 0
        return self.peek_at(p, n)

    def peek_at(self, p, n):
        if n == 0:
            return 0
        b = self.buf
        i = p >> 3
        v = b[i] << 24 | b[i + 1] << 16 | b[i + 2] << 8 | b[i + 3]
        v = (v << 8 | b[i + 4]) >> (8 - (p & 7))         # 32 bits from p
        return (v >> (32 - n)) & ((1 << n) - 1)


class _Gr:
    __slots__ = ("sfbtab", "part_23_length", "big_values", "scalefac_compress", "global_gain", "block_type",
                 "mixed_block_flag", "n_long_sfb", "n_short_sfb", "table_select", "region_count",
                 "subblock_gain", "preflag", "scalefac_scale", "count1_table", "scfsi")


def _read_side_info(bs, grs, h):
    gr_count = 1 if _mono(h) else 2
    sr = _my_sr(h)
    sr -= 1 if sr else 0
    scfsi = 0
    if _mpeg1(h):
        gr_count *= 2
        main_data_begin = bs.get(9)
        scfsi = bs.get(7 + gr_count)
    else:
        main_data_begin = bs.get(8 + gr_count) >> gr_count
    part23 = 0
    for _ in range(gr_count):
        gr = _Gr()
        if _mono(h):
            scfsi <<= 4
        gr.part_23_length = bs.get(12)
        part23 += gr.part_23_length
        gr.big_values = bs.get(9)
        if gr.big_values > 288:
            return -1
        gr.global_gain = bs.get(8)
        gr.scalefac_compress = bs.get(4 if _mpeg1(h) else 9)
        gr.sfbtab = T.g_scf_long[sr * 23:sr * 23 + 23]
        gr.n_long_sfb = 22
        gr.n_short_sfb = 0
        gr.subblock_gain = [0, 0, 0]
        if bs.get(1):
            gr.block_type = bs.get(2)
            if not gr.block_type:
                return -1
            gr.mixed_block_flag = bs.get(1)
            gr.region_count = [7, 255, 0]
            if gr.block_type == 2:
                scfsi &= 0x0F0F
                if not gr.mixed_block_flag:
                    gr.region_count[0] = 8
                    gr.sfbtab = T.g_scf_short[sr * 40:sr * 40 + 40]
                    gr.n_long_sfb = 0
                    gr.n_short_sfb = 39
                else:
                    gr.sfbtab = T.g_scf_mixed[sr * 40:sr * 40 + 40]
                    gr.n_long_sfb = 8 if _mpeg1(h) else 6
                    gr.n_short_sfb = 30
            tables = bs.get(10) << 5
            gr.subblock_gain = [bs.get(3), bs.get(3), bs.get(3)]
        else:
            gr.block_type = 0
            gr.mixed_block_flag = 0
            tables = bs.get(15)
            gr.region_count = [bs.get(4), bs.get(3), 255]
        gr.table_select = [tables >> 10, (tables >> 5) & 31, tables & 31]
        gr.preflag = bs.get(1) if _mpeg1(h) else (1 if gr.scalefac_compress >= 500 else 0)
        gr.scalefac_scale = bs.get(1)
        gr.count1_table = bs.get(1)
        gr.scfsi = (scfsi >> 12) & 15
        scfsi <<= 4
        grs.append(gr)
    if part23 + bs.pos > bs.limit + main_data_begin * 8:
        return -1
    return main_data_begin


def _read_scalefactors(scf, ist_pos, scf_size, scf_count, bs, scfsi):
    o = 0
    i = 0
    while i < 4 and scf_count[i]:
        cnt = scf_count[i]
        if scfsi & 8:
            for k in range(cnt):
                scf[o + k] = ist_pos[o + k]
        else:
            bits = scf_size[i]
            if not bits:
                for k in range(cnt):
                    scf[o + k] = 0
                    ist_pos[o + k] = 0
            else:
                max_scf = (1 << bits) - 1 if scfsi < 0 else -1
                for k in range(cnt):
                    s = bs.get(bits)
                    ist_pos[o + k] = 255 if s == max_scf else s
                    scf[o + k] = s
        o += cnt
        i += 1
        scfsi *= 2
    scf[o] = scf[o + 1] = scf[o + 2] = 0


def _ldexp_q2(y, e):
    while True:
        k = e if e < 120 else 120
        y *= T.g_expfrac[k & 3] * ((1 << 30) >> (k >> 2))
        e -= k
        if e <= 0:
            return y


_MAX_SCFI = 44            # ((255 - 4 - 210) + 3) & ~3


def _decode_scalefactors(h, ist_pos, bs, gr, scf, ch):
    row = (1 if gr.n_short_sfb else 0) + (0 if gr.n_long_sfb else 1)
    part = T.g_scf_partitions[row * 28:row * 28 + 28]
    scf_size = [0, 0, 0, 0]
    iscf = [0] * 43
    shift = gr.scalefac_scale + 1
    scfsi = gr.scfsi
    if _mpeg1(h):
        p = T.g_scfc_decode[gr.scalefac_compress]
        scf_size[0] = scf_size[1] = p >> 2
        scf_size[2] = scf_size[3] = p & 3
        counts = part
    else:
        ist = 1 if (_i_stereo(h) and ch) else 0
        sfc = gr.scalefac_compress >> ist
        k = ist * 12
        while sfc >= 0:
            modprod = 1
            for i in (3, 2, 1, 0):
                scf_size[i] = sfc // modprod % T.g_mod[k + i]
                modprod *= T.g_mod[k + i]
            sfc -= modprod
            k += 4
        counts = part[k:]
        scfsi = -16
    _read_scalefactors(iscf, ist_pos, scf_size, counts, bs, scfsi)
    if gr.n_short_sfb:
        sh = 3 - shift
        for i in range(0, gr.n_short_sfb, 3):
            iscf[gr.n_long_sfb + i] += gr.subblock_gain[0] << sh
            iscf[gr.n_long_sfb + i + 1] += gr.subblock_gain[1] << sh
            iscf[gr.n_long_sfb + i + 2] += gr.subblock_gain[2] << sh
    elif gr.preflag:
        for i in range(10):
            iscf[11 + i] += T.g_preamp[i]
    gain_exp = gr.global_gain - 4 - 210 - (2 if _ms(h) else 0)
    gain = _ldexp_q2(float(1 << (_MAX_SCFI // 4)), _MAX_SCFI - gain_exp)
    for i in range(gr.n_long_sfb + gr.n_short_sfb):
        scf[i] = _ldexp_q2(gain, iscf[i] << shift)


def _pow43(x):
    if x < 129:
        return _POW43[16 + x]
    mult = 256
    if x < 1024:
        mult = 16
        x <<= 3
    sign = 2 * x & 64
    frac = ((x & 63) - sign) / ((x & ~63) + sign)
    return _POW43[16 + ((x + sign) >> 6)] * (1.0 + frac * ((4.0 / 3) + frac * (2.0 / 9))) * mult


def _huffman(dst, d0, bs, gr, scf, limit):
    """The spectrum of one granule and channel into dst[d0:d0 + 576]."""
    pos = bs.pos
    peek = bs.peek_at
    big = gr.big_values
    sfb = gr.sfbtab
    si = 0                 # next band in sfb
    fi = 0                 # next scale factor
    d = d0
    ireg = 0
    one = 0.0
    while big > 0:
        tab = gr.table_select[ireg]
        sfb_cnt = gr.region_count[ireg]
        ireg += 1
        base = T.tabindex[tab]
        linbits = T.g_linbits[tab]
        while True:
            np = sfb[si] // 2
            si += 1
            pairs = big if big < np else np
            one = scf[fi]
            fi += 1
            while pairs > 0:
                w = 5
                leaf = _TABS[base + peek(pos, w)]
                while leaf < 0:
                    pos += w
                    w = leaf & 7
                    leaf = _TABS[base + peek(pos, w) - (leaf >> 3)]
                pos += leaf >> 8
                for _ in range(2):
                    lsb = leaf & 15
                    if lsb == 15 and linbits:
                        lsb += peek(pos, linbits)
                        pos += linbits
                        v = one * _pow43(lsb)
                        dst[d] = -v if peek(pos, 1) else v
                    else:
                        dst[d] = _POW43[16 + lsb - 16 * peek(pos, 1)] * one
                    if lsb:
                        pos += 1
                    d += 1
                    leaf >>= 4
                pairs -= 1
            big -= np
            if big <= 0:
                break
            sfb_cnt -= 1
            if sfb_cnt < 0:
                break
    cb = T.tab33 if gr.count1_table else T.tab32
    np = 1 - big
    while True:
        leaf = cb[peek(pos, 4)]
        if not (leaf & 8):
            n = leaf & 3
            leaf = cb[(leaf >> 3) + (peek(pos, 4 + n) & ((1 << n) - 1))]
        pos += leaf & 7
        if pos > limit:
            break
        np -= 1
        if not np:
            np = sfb[si] // 2
            si += 1
            if not np:
                break
            one = scf[fi]
            fi += 1
        for s in (0, 1):
            if leaf & (128 >> s):
                dst[d + s] = -one if peek(pos, 1) else one
                pos += 1
        np -= 1
        if not np:
            np = sfb[si] // 2
            si += 1
            if not np:
                break
            one = scf[fi]
            fi += 1
        for s in (2, 3):
            if leaf & (128 >> s):
                dst[d + s] = -one if peek(pos, 1) else one
                pos += 1
        d += 4
    bs.pos = limit


def _midside(g, o, n):
    for i in range(o, o + n):
        a = g[i]
        b = g[i + 576]
        g[i] = a + b
        g[i + 576] = a - b


def _stereo_top_band(g, sfb, nbands, mb):
    mb[0] = mb[1] = mb[2] = -1
    r = 576
    for i in range(nbands):
        for k in range(0, sfb[i], 2):
            if g[r + k] != 0 or g[r + k + 1] != 0:
                mb[i % 3] = i
                break
        r += sfb[i]


def _stereo_process(g, ist_pos, sfb, h, mb, mpeg2_sh):
    mpeg1 = _mpeg1(h)
    max_pos = 7 if mpeg1 else 64
    o = 0
    i = 0
    while sfb[i]:
        ipos = ist_pos[i]
        if i > mb[i % 3] and ipos < max_pos:
            s = 1.41421356 if _ms_stereo(h) else 1.0
            if mpeg1:
                kl = T.g_pan[2 * ipos]
                kr = T.g_pan[2 * ipos + 1]
            else:
                kl = 1.0
                kr = _ldexp_q2(1.0, ((ipos + 1) >> 1) << mpeg2_sh)
                if ipos & 1:
                    kl = kr
                    kr = 1.0
            kl *= s
            kr *= s
            for k in range(o, o + sfb[i]):
                g[k + 576] = g[k] * kr
                g[k] = g[k] * kl
        elif _ms_stereo(h):
            _midside(g, o, sfb[i])
        o += sfb[i]
        i += 1


def _intensity(g, ist_pos, grs, h):
    gr = grs[0]
    n_sfb = gr.n_long_sfb + gr.n_short_sfb
    max_blocks = 3 if gr.n_short_sfb else 1
    mb = [0, 0, 0]
    _stereo_top_band(g, gr.sfbtab, n_sfb, mb)
    if gr.n_long_sfb:
        mb[0] = mb[1] = mb[2] = max(mb)
    for i in range(max_blocks):
        default = 3 if _mpeg1(h) else 0
        itop = n_sfb - max_blocks + i
        prev = itop - max_blocks
        ist_pos[itop] = default if mb[i] >= prev else ist_pos[prev]
    _stereo_process(g, ist_pos, gr.sfbtab, h, mb, grs[1].scalefac_compress & 1)


def _reorder(g, o, sfb, si):
    out = []
    src = o
    while sfb[si]:
        n = sfb[si]
        for i in range(n):
            out.append(g[src + i])
            out.append(g[src + i + n])
            out.append(g[src + i + 2 * n])
        src += 3 * n
        si += 3
    g[o:o + len(out)] = out


def _antialias(g, o, nbands):
    aa0, aa1 = T.g_aa[0:8], T.g_aa[8:16]
    while nbands > 0:
        for i in range(8):
            u = g[o + 18 + i]
            d = g[o + 17 - i]
            g[o + 18 + i] = u * aa0[i] - d * aa1[i]
            g[o + 17 - i] = u * aa1[i] + d * aa0[i]
        nbands -= 1
        o += 18


def _dct3_9(y):
    s0, s2, s4, s6, s8 = y[0], y[2], y[4], y[6], y[8]
    t0 = s0 + s6 * 0.5
    s0 -= s6
    t4 = (s4 + s2) * 0.93969262
    t2 = (s8 + s2) * 0.76604444
    s6 = (s4 - s8) * 0.17364818
    s4 += s8 - s2
    s2 = s0 - s4 * 0.5
    y[4] = s4 + s0
    s8 = t0 - t2 + s6
    s0 = t0 - t4 + t2
    s4 = t0 + t4 - s6
    s1, s3, s5, s7 = y[1], y[3], y[5], y[7]
    s3 *= 0.86602540
    t0 = (s5 + s1) * 0.98480775
    t4 = (s5 - s7) * 0.34202014
    t2 = (s1 + s7) * 0.64278761
    s1 = (s1 - s5 - s7) * 0.86602540
    s5 = t0 - s3 - t2
    s7 = t4 - s3 - t0
    s3 = t4 + s3 - t2
    y[0] = s4 - s7
    y[1] = s2 + s1
    y[2] = s0 - s3
    y[3] = s8 + s5
    y[5] = s8 - s5
    y[6] = s0 + s3
    y[7] = s2 - s1
    y[8] = s4 + s7


def _imdct36(g, o, ov, oo, win, nbands):
    tw = T.g_twid9
    for _ in range(nbands):
        co = [0.0] * 9
        si = [0.0] * 9
        co[0] = -g[o]
        si[0] = g[o + 17]
        for i in range(4):
            si[8 - 2 * i] = g[o + 4 * i + 1] - g[o + 4 * i + 2]
            co[1 + 2 * i] = g[o + 4 * i + 1] + g[o + 4 * i + 2]
            si[7 - 2 * i] = g[o + 4 * i + 4] - g[o + 4 * i + 3]
            co[2 + 2 * i] = -(g[o + 4 * i + 3] + g[o + 4 * i + 4])
        _dct3_9(co)
        _dct3_9(si)
        si[1] = -si[1]
        si[3] = -si[3]
        si[5] = -si[5]
        si[7] = -si[7]
        for i in range(9):
            ovl = ov[oo + i]
            s = co[i] * tw[9 + i] + si[i] * tw[i]
            ov[oo + i] = co[i] * tw[i] - si[i] * tw[9 + i]
            g[o + i] = ovl * win[i] - s * win[9 + i]
            g[o + 17 - i] = ovl * win[9 + i] + s * win[i]
        o += 18
        oo += 9


def _idct3(x0, x1, x2):
    m1 = x1 * 0.86602540
    a1 = x0 - x2 * 0.5
    return [a1 + m1, x0 + x2, a1 - m1]


def _imdct12(x, xo, dst, do, ov, oo):
    tw = T.g_twid3
    co = _idct3(-x[xo], x[xo + 6] + x[xo + 3], x[xo + 12] + x[xo + 9])
    si = _idct3(x[xo + 15], x[xo + 12] - x[xo + 9], x[xo + 6] - x[xo + 3])
    si[1] = -si[1]
    for i in range(3):
        ovl = ov[oo + i]
        s = co[i] * tw[3 + i] + si[i] * tw[i]
        ov[oo + i] = co[i] * tw[i] - si[i] * tw[3 + i]
        dst[do + i] = ovl * tw[2 - i] - s * tw[5 - i]
        dst[do + 5 - i] = ovl * tw[5 - i] + s * tw[2 - i]


def _imdct_short(g, o, ov, oo, nbands):
    for _ in range(nbands):
        tmp = g[o:o + 18]
        g[o:o + 6] = ov[oo:oo + 6]
        _imdct12(tmp, 0, g, o + 6, ov, oo + 6)
        _imdct12(tmp, 1, g, o + 12, ov, oo + 6)
        _imdct12(tmp, 2, ov, oo, ov, oo + 6)
        o += 18
        oo += 9


def _change_sign(g, o):
    o += 18
    for _ in range(16):
        for i in range(1, 18, 2):
            g[o + i] = -g[o + i]
        o += 36


def _imdct_gr(g, o, ov, oo, block_type, n_long):
    if n_long:
        _imdct36(g, o, ov, oo, T.g_mdct_window[0:18], n_long)
        o += 18 * n_long
        oo += 9 * n_long
    if block_type == 2:
        _imdct_short(g, o, ov, oo, 32 - n_long)
    else:
        w = T.g_mdct_window[18:36] if block_type == 3 else T.g_mdct_window[0:18]
        _imdct36(g, o, ov, oo, w, 32 - n_long)


def _dct_ii(g, o, n):
    sec = T.g_sec
    for k in range(n):
        y = o + k
        t = [[0.0] * 8 for _ in range(4)]
        for i in range(8):
            x0 = g[y + i * 18]
            x1 = g[y + (15 - i) * 18]
            x2 = g[y + (16 + i) * 18]
            x3 = g[y + (31 - i) * 18]
            t0 = x0 + x3
            t1 = x1 + x2
            t2 = (x1 - x2) * sec[3 * i]
            t3 = (x0 - x3) * sec[3 * i + 1]
            t[0][i] = t0 + t1
            t[1][i] = (t0 - t1) * sec[3 * i + 2]
            t[2][i] = t3 + t2
            t[3][i] = (t3 - t2) * sec[3 * i + 2]
        for x in t:
            x0, x1, x2, x3, x4, x5, x6, x7 = x
            xt = x0 - x7
            x0 += x7
            x7 = x1 - x6
            x1 += x6
            x6 = x2 - x5
            x2 += x5
            x5 = x3 - x4
            x3 += x4
            x4 = x0 - x3
            x0 += x3
            x3 = x1 - x2
            x1 += x2
            x[0] = x0 + x1
            x[4] = (x0 - x1) * 0.70710677
            x5 = x5 + x6
            x6 = (x6 + x7) * 0.70710677
            x7 = x7 + xt
            x3 = (x3 + x4) * 0.70710677
            x5 -= x7 * 0.198912367
            x7 += x5 * 0.382683432
            x5 -= x7 * 0.198912367
            x0 = xt - x6
            xt += x6
            x[1] = (xt + x7) * 0.50979561
            x[2] = (x4 + x3) * 0.54119611
            x[3] = (x0 - x5) * 0.60134488
            x[5] = (x0 + x5) * 0.89997619
            x[6] = (x4 - x3) * 1.30656302
            x[7] = (xt - x7) * 2.56291556
        for i in range(7):
            g[y] = t[0][i]
            g[y + 18] = t[2][i] + t[3][i] + t[3][i + 1]
            g[y + 36] = t[1][i] + t[1][i + 1]
            g[y + 54] = t[2][i + 1] + t[3][i] + t[3][i + 1]
            y += 72
        g[y] = t[0][7]
        g[y + 18] = t[2][7] + t[3][7]
        g[y + 36] = t[1][7]
        g[y + 54] = t[3][7]


def _scale(s):
    if s >= 32766.5:
        return 32767
    if s <= -32767.5:
        return -32768
    v = int(s + 0.5)
    return v - 1 if v < 0 else v


def _synth_pair(pcm, po, nch, z, zo):
    a = (z[zo + 14 * 64] - z[zo]) * 29
    a += (z[zo + 64] + z[zo + 13 * 64]) * 213
    a += (z[zo + 12 * 64] - z[zo + 2 * 64]) * 459
    a += (z[zo + 3 * 64] + z[zo + 11 * 64]) * 2037
    a += (z[zo + 10 * 64] - z[zo + 4 * 64]) * 5153
    a += (z[zo + 5 * 64] + z[zo + 9 * 64]) * 6574
    a += (z[zo + 8 * 64] - z[zo + 6 * 64]) * 37489
    a += z[zo + 7 * 64] * 75038
    pcm[po] = _scale(a)
    zo += 2
    a = z[zo + 14 * 64] * 104
    a += z[zo + 12 * 64] * 1567
    a += z[zo + 10 * 64] * 9727
    a += z[zo + 8 * 64] * 64019
    a += z[zo + 6 * 64] * -9975
    a += z[zo + 4 * 64] * -45
    a += z[zo + 2 * 64] * 146
    a += z[zo] * -5
    pcm[po + 16 * nch] = _scale(a)


def _synth(g, xl, pcm, dl, nch, L, lo):
    xr = xl + 576 * (nch - 1)
    dr = dl + (nch - 1)
    z = lo + 15 * 64
    L[z + 60] = g[xl + 288]
    L[z + 61] = g[xr + 288]
    L[z + 62] = g[xl]
    L[z + 63] = g[xr]
    L[z + 124] = g[xl + 1 + 288]
    L[z + 125] = g[xr + 1 + 288]
    L[z + 126] = g[xl + 1]
    L[z + 127] = g[xr + 1]
    _synth_pair(pcm, dr, nch, L, lo + 61)
    _synth_pair(pcm, dr + 32 * nch, nch, L, lo + 60 + 64 + 1)
    _synth_pair(pcm, dl, nch, L, lo + 60)
    _synth_pair(pcm, dl + 32 * nch, nch, L, lo + 60 + 64)
    win = T.g_win
    w = 0
    for i in range(14, -1, -1):
        L[z + 4 * i] = g[xl + 18 * (31 - i)]
        L[z + 4 * i + 1] = g[xr + 18 * (31 - i)]
        L[z + 4 * i + 2] = g[xl + 1 + 18 * (31 - i)]
        L[z + 4 * i + 3] = g[xr + 1 + 18 * (31 - i)]
        L[z + 4 * (i + 16)] = g[xl + 1 + 18 * (1 + i)]
        L[z + 4 * (i + 16) + 1] = g[xr + 1 + 18 * (1 + i)]
        L[z + 4 * (i - 16) + 2] = g[xl + 18 * (1 + i)]
        L[z + 4 * (i - 16) + 3] = g[xr + 18 * (1 + i)]
        a = [0.0, 0.0, 0.0, 0.0]
        b = [0.0, 0.0, 0.0, 0.0]
        for k in range(8):
            w0 = win[w]
            w1 = win[w + 1]
            w += 2
            vz = z + 4 * i - k * 64
            vy = z + 4 * i - (15 - k) * 64
            for j in range(4):
                zz = L[vz + j]
                yy = L[vy + j]
                if k == 0:
                    b[j] = zz * w1 + yy * w0
                    a[j] = zz * w0 - yy * w1
                elif k & 1:
                    b[j] += zz * w1 + yy * w0
                    a[j] += yy * w1 - zz * w0
                else:
                    b[j] += zz * w1 + yy * w0
                    a[j] += zz * w0 - yy * w1
        pcm[dr + (15 - i) * nch] = _scale(a[1])
        pcm[dr + (17 + i) * nch] = _scale(b[1])
        pcm[dl + (15 - i) * nch] = _scale(a[0])
        pcm[dl + (17 + i) * nch] = _scale(b[0])
        pcm[dr + (47 - i) * nch] = _scale(a[3])
        pcm[dr + (49 + i) * nch] = _scale(b[3])
        pcm[dl + (47 - i) * nch] = _scale(a[2])
        pcm[dl + (49 + i) * nch] = _scale(b[2])


class MP3:
    """An MP3 decoder: give it data a frame (or more) at a time."""

    def __init__(self):
        self.header = None
        self.free_format = 0
        self.reserv = b""
        self.overlap = [[0.0] * 288, [0.0] * 288]
        self.qmf = [0.0] * (15 * 64)
        self.rate = 44100
        self.channels = 2

    def format(self):
        return self.rate, self.channels

    def close(self):
        pass

    def _find(self, d, n):
        for i in range(n - 4):
            h = d[i:i + 4]
            if not _valid(h):
                continue
            fb = _frame_bytes(h, self.free_format)
            fp = fb + _padding(h)
            if fb and i + fp <= n and self._match(d, i, n, fb):
                return i, fp
            if i == 0 and fp == n:
                return i, fp
        return n, 0

    def _match(self, d, i0, n, fb):
        h = d[i0:i0 + 4]
        i = i0
        for k in range(10):
            hi = d[i:i + 4]
            i += _frame_bytes(hi, fb) + _padding(hi)
            if i + 4 > n:
                return k > 0
            nxt = d[i:i + 4]
            if nxt == b"\x00\x00\x00\x00" or (n - i == 128 and nxt[:3] == b"TAG"):
                return k > 0
            if not _compare(h, nxt):
                return False
        return True

    def decode(self, data):
        """(pcm, bytes used): the first frame in data, as 16-bit samples."""
        d = bytes(data)
        n = len(d)
        i = 0
        size = 0
        if n > 4 and self.header is not None and _compare(self.header, d):
            size = _frame_bytes(d, self.free_format) + _padding(d)
            if size != n and (size + 4 > n or not _compare(d, d[size:size + 4])):
                size = 0
        if not size:
            self.__init__()
            i, size = self._find(d, n)
            if not size or i + size > n:
                return b"", i
        h = d[i:i + 4]
        self.header = h
        nch = 1 if _mono(h) else 2
        self.channels = nch
        self.rate = _hz(h)
        if _layer(h) != 1:                           # layers I and II: not supported, skipped quietly
            return b"", i + size
        bs = _Bits(d[i + 4:], size - 4)
        if _crc(h):
            bs.get(16)
        grs = []
        mdb = _read_side_info(bs, grs, h)
        if mdb < 0 or bs.pos > bs.limit:
            self.__init__()
            return b"", i + size
        # the bit reservoir: main data starts mdb bytes back, in earlier frames
        frame_main = d[i + 4 + bs.pos // 8:i + size]
        have = min(len(self.reserv), mdb)
        main = self.reserv[len(self.reserv) - have:] + frame_main
        ok = len(self.reserv) >= mdb
        mbs = _Bits(main, len(main))
        ngr = 2 if _mpeg1(h) else 1
        pcm = [0] * (576 * nch * ngr)
        if ok:
            scf = [0.0] * 40
            ist = [[0] * 43, [0] * 43]                 # kept across the granules (scfsi reuses them)
            for igr in range(ngr):
                g = [0.0] * 1152
                gi = grs[igr * nch:igr * nch + nch]
                for ch in range(nch):
                    limit = mbs.pos + gi[ch].part_23_length
                    _decode_scalefactors(h, ist[ch], mbs, gi[ch], scf, ch)
                    _huffman(g, 576 * ch, mbs, gi[ch], scf, limit)
                if nch == 2 and _i_stereo(h):
                    _intensity(g, ist[1], gi, h)
                elif nch == 2 and _ms(h):
                    _midside(g, 0, 576)
                for ch in range(nch):
                    gr = gi[ch]
                    aa = 31
                    n_long = (2 if gr.mixed_block_flag else 0) << (1 if _my_sr(h) == 2 else 0)
                    if gr.n_short_sfb:
                        aa = n_long - 1
                        _reorder(g, 576 * ch + n_long * 18, gr.sfbtab, gr.n_long_sfb)
                    _antialias(g, 576 * ch, aa)
                    _imdct_gr(g, 576 * ch, self.overlap[ch], 0, gr.block_type, n_long)
                    _change_sign(g, 576 * ch)
                self._synth_granule(g, nch, pcm, igr * 576 * nch)
        # keep up to 511 bytes after the data used, for the next frames
        used = (mbs.pos + 7) // 8
        rest = main[used:]
        self.reserv = rest[-511:] if len(rest) > 511 else rest
        if not ok:
            return b"", i + size
        return struct.pack("<%dh" % len(pcm), *pcm), i + size

    def _synth_granule(self, g, nch, pcm, po):
        for ch in range(nch):
            _dct_ii(g, 576 * ch, 18)
        L = self.qmf[:] + [0.0] * (64 * 18) + [0.0] * 64
        for i in range(0, 18, 2):
            _synth(g, i, pcm, po + 32 * nch * i, nch, L, i * 64)
        if nch == 1:
            for i in range(0, 15 * 64, 2):
                self.qmf[i] = L[18 * 64 + i]
        else:
            self.qmf = L[18 * 64:18 * 64 + 15 * 64]
