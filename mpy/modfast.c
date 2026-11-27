// _fast: C versions of the system's @micropython.viper functions, for CPUs
// MicroPython has no native code emitter for (ARM64). Same arguments, same
// results; Python picks them with kernel.arch.fast(fn, name).
// A "pointer" argument is a buffer (bytes, bytearray, array) or an address.
#include <stdint.h>
#include <string.h>
#include "py/runtime.h"
#include "py/obj.h"

static void *P(mp_obj_t o) {
    if (mp_obj_is_int(o)) {
        return (void *)(uintptr_t)mp_obj_get_int_truncated(o);
    }
    mp_buffer_info_t b;
    mp_get_buffer_raise(o, &b, MP_BUFFER_READ);
    return b.buf;
}
#define I(o) ((intptr_t)mp_obj_get_int_truncated(o))
static inline uint8_t clamp8(intptr_t v) {
    return v < 0 ? 0 : (v > 255 ? 255 : (uint8_t)v);
}

// ---- pygame/font.py ----
static mp_obj_t f_font_put(size_t n, const mp_obj_t *a) {
    uint8_t *dst = P(a[0]);
    intptr_t dw = I(a[1]), dh = I(a[2]), dx = I(a[3]), dy = I(a[4]);
    const uint8_t *src = P(a[5]);
    intptr_t sw = I(a[6]), sx = I(a[7]), sy = I(a[8]), w = I(a[9]), h = I(a[10]);
    uint8_t b = I(a[11]), g = I(a[12]), r = I(a[13]);
    for (intptr_t row = 0; row < h; row++) {
        intptr_t y = dy + row;
        if (y < 0 || y >= dh) {
            continue;
        }
        const uint8_t *s = src + (sy + row) * sw + sx;
        for (intptr_t col = 0; col < w; col++) {
            intptr_t x = dx + col;
            if (x < 0 || x >= dw) {
                continue;
            }
            uint8_t al = s[col];
            if (al) {
                uint8_t *o = dst + (y * dw + x) * 4;
                if (al > o[3]) {
                    o[0] = b;
                    o[1] = g;
                    o[2] = r;
                    o[3] = al;
                }
            }
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(f_font_put_obj, 14, 14, f_font_put);

static mp_obj_t f_font_unrle(size_t n, const mp_obj_t *a) {
    const uint8_t *src = P(a[0]);
    intptr_t i = I(a[1]), end = I(a[2]);
    uint8_t *dst = P(a[3]);
    intptr_t o = 0;
    while (i < end) {
        uint8_t b = src[i];
        if (b == 0) {
            o += src[i + 1];
            i += 2;
        } else {
            dst[o++] = b;
            i++;
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(f_font_unrle_obj, 4, 4, f_font_unrle);

// ---- kernel/sound.py ----
static mp_obj_t f_sound_widen(size_t n, const mp_obj_t *a) {
    const uint8_t *src = P(a[0]);
    intptr_t frames = I(a[1]);
    uint8_t *dst = P(a[2]);
    intptr_t channels = I(a[3]), bits = I(a[4]);
    intptr_t i = 0, o = 0;
    for (intptr_t k = 0; k < frames; k++, o += 4) {
        if (bits == 8) {
            uint8_t hi = src[i++] - 128;
            dst[o] = 0;
            dst[o + 1] = hi;
            if (channels == 2) {
                hi = src[i++] - 128;
            }
            dst[o + 2] = 0;
            dst[o + 3] = hi;
        } else {
            dst[o] = src[i];
            dst[o + 1] = src[i + 1];
            if (channels == 2) {
                i += 2;
            }
            dst[o + 2] = src[i];
            dst[o + 3] = src[i + 1];
            i += 2;
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(f_sound_widen_obj, 5, 5, f_sound_widen);

static mp_obj_t f_sound_stretch(size_t n, const mp_obj_t *a) {
    const uint32_t *src = P(a[0]);
    uint32_t *dst = P(a[2]);
    intptr_t out_n = I(a[3]), rate = I(a[4]), target = I(a[5]);
    for (intptr_t k = 0; k < out_n; k++) {
        dst[k] = src[k * rate / target];
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(f_sound_stretch_obj, 6, 6, f_sound_stretch);

// ---- crypto/chacha.py ----
#define ROTL(v, c) (((v) << (c)) | ((v) >> (32 - (c))))
static mp_obj_t f_chacha_rounds(mp_obj_t xo, mp_obj_t so, mp_obj_t qro) {
    uint32_t *x = P(xo);
    const uint32_t *s = P(so);
    const uint8_t *qr = P(qro);
    for (int i = 0; i < 16; i++) {
        x[i] = s[i];
    }
    for (int r = 0; r < 10; r++) {
        for (int q = 0; q < 8; q++) {
            int ia = qr[4 * q], ib = qr[4 * q + 1], ic = qr[4 * q + 2], id = qr[4 * q + 3];
            uint32_t xa = x[ia], xb = x[ib], xc = x[ic], xd = x[id];
            xa += xb; xd ^= xa; xd = ROTL(xd, 16);
            xc += xd; xb ^= xc; xb = ROTL(xb, 12);
            xa += xb; xd ^= xa; xd = ROTL(xd, 8);
            xc += xd; xb ^= xc; xb = ROTL(xb, 7);
            x[ia] = xa; x[ib] = xb; x[ic] = xc; x[id] = xd;
        }
    }
    for (int i = 0; i < 16; i++) {
        x[i] += s[i];
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_3(f_chacha_rounds_obj, f_chacha_rounds);

static mp_obj_t f_chacha_xor(size_t n, const mp_obj_t *a) {
    uint8_t *out = P(a[0]);
    const uint8_t *data = P(a[1]), *ks = P(a[2]);
    intptr_t off = I(a[3]), len = I(a[4]);
    for (intptr_t i = 0; i < len; i++) {
        out[off + i] = data[off + i] ^ ks[i];
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(f_chacha_xor_obj, 5, 5, f_chacha_xor);

// ---- imaging/jpeg.py (stb_image's integer IDCT) ----
#define IDCT_1D(s0, s1, s2, s3, s4, s5, s6, s7) \
    int64_t p2 = s2, p3 = s6, p1 = (p2 + p3) * 2217; \
    int64_t t2 = p1 + p3 * -7567, t3 = p1 + p2 * 3135; \
    p2 = s0; p3 = s4; \
    int64_t t0 = (p2 + p3) * 4096, t1 = (p2 - p3) * 4096; \
    int64_t x0 = t0 + t3, x3 = t0 - t3, x1 = t1 + t2, x2 = t1 - t2; \
    t0 = s7; t1 = s5; t2 = s3; t3 = s1; \
    p3 = t0 + t2; int64_t p4 = t1 + t3; p1 = t0 + t3; p2 = t1 + t2; \
    int64_t p5 = (p3 + p4) * 4816; \
    t0 *= 1223; t1 *= 8410; t2 *= 12586; t3 *= 6149; \
    p1 = p5 + p1 * -3685; p2 = p5 + p2 * -10497; p3 *= -8034; p4 *= -1597; \
    t3 += p1 + p4; t2 += p2 + p3; t1 += p2 + p4; t0 += p1 + p3;

static mp_obj_t f_jpeg_idct(size_t n, const mp_obj_t *a) {
    int32_t *tmp = P(a[0]);
    uint8_t *out = P(a[1]);
    intptr_t stride = I(a[2]), off = I(a[3]);
    for (int i = 0; i < 8; i++) {
        IDCT_1D(tmp[i], tmp[8 + i], tmp[16 + i], tmp[24 + i], tmp[32 + i], tmp[40 + i], tmp[48 + i], tmp[56 + i])
        x0 += 512; x1 += 512; x2 += 512; x3 += 512;
        tmp[i] = (x0 + t3) >> 10;
        tmp[56 + i] = (x0 - t3) >> 10;
        tmp[8 + i] = (x1 + t2) >> 10;
        tmp[48 + i] = (x1 - t2) >> 10;
        tmp[16 + i] = (x2 + t1) >> 10;
        tmp[40 + i] = (x2 - t1) >> 10;
        tmp[24 + i] = (x3 + t0) >> 10;
        tmp[32 + i] = (x3 - t0) >> 10;
    }
    for (int r = 0; r < 8; r++) {
        int32_t *t = tmp + r * 8;
        IDCT_1D(t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7])
        int64_t bias = 65536 + (128 << 17);
        x0 += bias; x1 += bias; x2 += bias; x3 += bias;
        uint8_t *o = out + off + r * stride;
        o[0] = clamp8((x0 + t3) >> 17);
        o[7] = clamp8((x0 - t3) >> 17);
        o[1] = clamp8((x1 + t2) >> 17);
        o[6] = clamp8((x1 - t2) >> 17);
        o[2] = clamp8((x2 + t1) >> 17);
        o[5] = clamp8((x2 - t1) >> 17);
        o[3] = clamp8((x3 + t0) >> 17);
        o[4] = clamp8((x3 - t0) >> 17);
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(f_jpeg_idct_obj, 4, 4, f_jpeg_idct);

static mp_obj_t f_jpeg_ycc(size_t n, const mp_obj_t *a) {
    uint8_t *dst = P(a[0]);
    const uint8_t *y = P(a[1]), *cb = P(a[2]), *cr = P(a[3]);
    intptr_t w = I(a[4]), h = I(a[5]), ys = I(a[6]), cs = I(a[7]), hs = I(a[8]), vs = I(a[9]);
    for (intptr_t row = 0; row < h; row++) {
        const uint8_t *yr = y + row * ys;
        intptr_t co = (row >> vs) * cs;
        uint8_t *d = dst + row * w * 4;
        for (intptr_t col = 0; col < w; col++, d += 4) {
            intptr_t yy = (intptr_t)yr[col] << 16;
            intptr_t b = (intptr_t)cb[co + (col >> hs)] - 128, r = (intptr_t)cr[co + (col >> hs)] - 128;
            d[0] = clamp8((yy + b * 116130 + 32768) >> 16);
            d[1] = clamp8((yy - b * 22554 - r * 46802 + 32768) >> 16);
            d[2] = clamp8((yy + r * 91881 + 32768) >> 16);
            d[3] = 255;
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(f_jpeg_ycc_obj, 10, 10, f_jpeg_ycc);

static mp_obj_t f_jpeg_gray(size_t n, const mp_obj_t *a) {
    uint8_t *dst = P(a[0]);
    const uint8_t *y = P(a[1]);
    intptr_t w = I(a[2]), h = I(a[3]), ys = I(a[4]);
    for (intptr_t row = 0; row < h; row++) {
        uint8_t *d = dst + row * w * 4;
        for (intptr_t col = 0; col < w; col++, d += 4) {
            d[0] = d[1] = d[2] = y[row * ys + col];
            d[3] = 255;
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(f_jpeg_gray_obj, 5, 5, f_jpeg_gray);

// ---- OpenGL/raster.py (the simple ones) ----
static mp_obj_t f_fill32(mp_obj_t bo, mp_obj_t no, mp_obj_t vo) {
    uint32_t *b = P(bo);
    intptr_t count = I(no);
    uint32_t v = (uint32_t)I(vo);
    for (intptr_t i = 0; i < count; i++) {
        b[i] = v;
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_3(f_fill32_obj, f_fill32);

static mp_obj_t f_rgb_to_rgba(mp_obj_t so, mp_obj_t d_o, mp_obj_t no) {
    const uint8_t *s = P(so);
    uint8_t *d = P(d_o);
    intptr_t count = I(no);
    for (intptr_t i = 0; i < count; i++) {
        d[i * 4] = s[i * 3];
        d[i * 4 + 1] = s[i * 3 + 1];
        d[i * 4 + 2] = s[i * 3 + 2];
        d[i * 4 + 3] = 255;
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_3(f_rgb_to_rgba_obj, f_rgb_to_rgba);


// floor division, as Python's // (C's / rounds towards zero)
static inline int64_t fdiv(int64_t a, int64_t b) {
    int64_t q = a / b;
    return (q * b != a && ((a < 0) != (b < 0))) ? q - 1 : q;
}
#define S32(v) ((int64_t)(int32_t)(uint32_t)(v))

static mp_obj_t f_triangles(size_t n_args, const mp_obj_t *a) {
    uint8_t *color = P(a[0]);
    uint32_t *depth = P(a[1]);
    int64_t width = I(a[2]);
    const uint32_t *verts = P(a[3]), *tris = P(a[4]);
    int64_t count = I(a[5]);
    const uint8_t *tex = mp_obj_is_int(a[6]) && I(a[6]) == 0 ? NULL : P(a[6]);
    int64_t tw = I(a[7]), th = I(a[8]);
    const uint32_t *state = P(a[9]);
    int64_t flags = state[0], cull = state[1], ccw = state[2];
    int64_t cx0 = S32(state[3]), cx1 = S32(state[4]), cy0 = S32(state[5]), cy1 = S32(state[6]);
    int test = flags & 1, write = flags & 2, textured = (flags & 4) && tex, modulate = flags & 8;
    int lequal = flags & 16, blend = flags & 32;
    int64_t tmask = tw - 1, hmask = th - 1;
    for (int64_t n = 0; n < count; n++) {
        int64_t i0 = (int64_t)tris[n * 3] * 10, i1 = (int64_t)tris[n * 3 + 1] * 10, i2 = (int64_t)tris[n * 3 + 2] * 10;
        int64_t X0 = S32(verts[i0]), Y0 = S32(verts[i0 + 1]);
        int64_t X1 = S32(verts[i1]), Y1 = S32(verts[i1 + 1]);
        int64_t X2 = S32(verts[i2]), Y2 = S32(verts[i2 + 1]);
        int64_t den = (X1 - X0) * (Y2 - Y0) - (X2 - X0) * (Y1 - Y0);
        if (den == 0) {
            continue;
        }
        int64_t neg = den < 0, front = neg == ccw;
        if (cull == 3 || (cull == 1 && !front) || (cull == 2 && front)) {
            continue;
        }
        if (den < 0) {
            int64_t t = i1; i1 = i2; i2 = t;
            t = X1; X1 = X2; X2 = t;
            t = Y1; Y1 = Y2; Y2 = t;
            den = -den;
        }
        int64_t minx = X0 < X1 ? X0 : X1; minx = minx < X2 ? minx : X2;
        int64_t maxx = X0 > X1 ? X0 : X1; maxx = maxx > X2 ? maxx : X2;
        int64_t miny = Y0 < Y1 ? Y0 : Y1; miny = miny < Y2 ? miny : Y2;
        int64_t maxy = Y0 > Y1 ? Y0 : Y1; maxy = maxy > Y2 ? maxy : Y2;
        minx >>= 4; maxx >>= 4; miny >>= 4; maxy >>= 4;
        if (minx < cx0) minx = cx0;
        if (maxx > cx1) maxx = cx1;
        if (miny < cy0) miny = cy0;
        if (maxy > cy1) maxy = cy1;
        if (minx > maxx || miny > maxy) {
            continue;
        }
        int64_t px = minx * 16 + 8, py = miny * 16 + 8;
        int64_t e0 = (py - Y0) * (X1 - X0) - (px - X0) * (Y1 - Y0), e0x = (Y0 - Y1) * 16, e0y = (X1 - X0) * 16;
        int64_t e1 = (py - Y1) * (X2 - X1) - (px - X1) * (Y2 - Y1), e1x = (Y1 - Y2) * 16, e1y = (X2 - X1) * 16;
        int64_t e2 = (py - Y2) * (X0 - X2) - (px - X2) * (Y0 - Y2), e2x = (Y2 - Y0) * 16, e2y = (X0 - X2) * 16;
        int64_t ay = Y2 - Y0, by = Y1 - Y0, bx = X1 - X0, cx = X2 - X0, ox = px - X0, oy = py - Y0;
        int64_t st0[10], sx0[10], sy0[10];
        for (int k = 2; k < 10; k++) {
            if (k == 8) {
                continue;
            }
            int64_t f0 = S32(verts[i0 + k]);
            int64_t d1 = S32(verts[i1 + k]) - f0, d2 = S32(verts[i2 + k]) - f0;
            int64_t scale = k == 2 ? 4096 : 256;
            int64_t sx = fdiv((d1 * ay - d2 * by) * 16 * scale, den);
            int64_t sy = fdiv((d2 * bx - d1 * cx) * 16 * scale, den);
            st0[k] = f0 * scale + fdiv(sx * ox + sy * oy, 16);
            sx0[k] = sx;
            sy0[k] = sy;
        }
        int64_t alpha = verts[i0 + 8];
        int64_t z0 = st0[2], r0 = st0[3], g0 = st0[4], b0 = st0[5], u0 = st0[6], v0 = st0[7], q0 = st0[9];
        for (int64_t y = miny; y <= maxy; y++) {
            int64_t ea = e0, eb = e1, ec = e2, z = z0, r = r0, g = g0, bl = b0, u = u0, v = v0, q = q0;
            int seen = 0;
            for (int64_t x = minx; x <= maxx; x++) {
                if ((ea | eb | ec) >= 0) {
                    seen = 1;
                    int64_t o = y * width + x;
                    int64_t zz = z >> 12;
                    if (!test || zz < (int64_t)depth[o] || (lequal && zz == (int64_t)depth[o])) {
                        if (write) {
                            depth[o] = (uint32_t)zz;
                        }
                        int64_t cr = r >> 16, cg = g >> 16, cb = bl >> 16;
                        if (textured) {
                            int64_t qq = q > 0 ? q : 1;
                            int64_t t = ((fdiv(v << 8, qq) & hmask) * tw + (fdiv(u << 8, qq) & tmask)) * 4;
                            if (modulate) {
                                cr = (cr * tex[t] + 128) >> 8;
                                cg = (cg * tex[t + 1] + 128) >> 8;
                                cb = (cb * tex[t + 2] + 128) >> 8;
                            } else {
                                cr = tex[t];
                                cg = tex[t + 1];
                                cb = tex[t + 2];
                            }
                        }
                        cr = cr > 255 ? 255 : (cr < 0 ? 0 : cr);
                        cg = cg > 255 ? 255 : (cg < 0 ? 0 : cg);
                        cb = cb > 255 ? 255 : (cb < 0 ? 0 : cb);
                        uint8_t *c4 = color + o * 4;
                        if (blend) {
                            int64_t na = 255 - alpha;
                            cb = (cb * alpha + c4[0] * na) >> 8;
                            cg = (cg * alpha + c4[1] * na) >> 8;
                            cr = (cr * alpha + c4[2] * na) >> 8;
                        }
                        c4[0] = cb;
                        c4[1] = cg;
                        c4[2] = cr;
                        c4[3] = 255;
                    }
                } else if (seen) {
                    break;
                }
                ea += e0x; eb += e1x; ec += e2x;
                z += sx0[2]; r += sx0[3]; g += sx0[4]; bl += sx0[5]; u += sx0[6]; v += sx0[7]; q += sx0[9];
            }
            e0 += e0y; e1 += e1y; e2 += e2y;
            z0 += sy0[2]; r0 += sy0[3]; g0 += sy0[4]; b0 += sy0[5]; u0 += sy0[6]; v0 += sy0[7]; q0 += sy0[9];
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(f_triangles_obj, 10, 10, f_triangles);

static mp_obj_t f_line(size_t n_args, const mp_obj_t *a) {
    uint8_t *color = P(a[0]);
    uint32_t *depth = P(a[1]);
    int64_t width = I(a[2]), height = I(a[3]), x = I(a[4]), y = I(a[5]), z = I(a[6]);
    int64_t dx = I(a[7]), dy = I(a[8]), n = I(a[9]), zstep = I(a[10]), bgr = I(a[11]), flags = I(a[12]);
    uint8_t cb = bgr & 255, cg = (bgr >> 8) & 255, cr = (bgr >> 16) & 255;
    for (int64_t i = 0; i <= n; i++, x += dx, y += dy, z += zstep) {
        int64_t px = x >> 16, py = y >> 16;
        if (px >= 0 && px < width && py >= 0 && py < height) {
            int64_t o = py * width + px, zz = z >> 16;
            if (!(flags & 1) || zz <= (int64_t)depth[o]) {
                if (flags & 2) {
                    depth[o] = (uint32_t)zz;
                }
                color[o * 4] = cb;
                color[o * 4 + 1] = cg;
                color[o * 4 + 2] = cr;
                color[o * 4 + 3] = 255;
            }
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(f_line_obj, 13, 13, f_line);

static const mp_rom_map_elem_t fast_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__fast) },
    { MP_ROM_QSTR(MP_QSTR_font_put), MP_ROM_PTR(&f_font_put_obj) },
    { MP_ROM_QSTR(MP_QSTR_font_unrle), MP_ROM_PTR(&f_font_unrle_obj) },
    { MP_ROM_QSTR(MP_QSTR_sound_widen), MP_ROM_PTR(&f_sound_widen_obj) },
    { MP_ROM_QSTR(MP_QSTR_sound_stretch), MP_ROM_PTR(&f_sound_stretch_obj) },
    { MP_ROM_QSTR(MP_QSTR_chacha_rounds), MP_ROM_PTR(&f_chacha_rounds_obj) },
    { MP_ROM_QSTR(MP_QSTR_chacha_xor), MP_ROM_PTR(&f_chacha_xor_obj) },
    { MP_ROM_QSTR(MP_QSTR_jpeg_idct), MP_ROM_PTR(&f_jpeg_idct_obj) },
    { MP_ROM_QSTR(MP_QSTR_jpeg_ycc), MP_ROM_PTR(&f_jpeg_ycc_obj) },
    { MP_ROM_QSTR(MP_QSTR_jpeg_gray), MP_ROM_PTR(&f_jpeg_gray_obj) },
    { MP_ROM_QSTR(MP_QSTR_fill32), MP_ROM_PTR(&f_fill32_obj) },
    { MP_ROM_QSTR(MP_QSTR_triangles), MP_ROM_PTR(&f_triangles_obj) },
    { MP_ROM_QSTR(MP_QSTR_line), MP_ROM_PTR(&f_line_obj) },
    { MP_ROM_QSTR(MP_QSTR_rgb_to_rgba), MP_ROM_PTR(&f_rgb_to_rgba_obj) },
};
static MP_DEFINE_CONST_DICT(fast_globals, fast_globals_table);

const mp_obj_module_t mp_module_fast = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&fast_globals,
};
MP_REGISTER_MODULE(MP_QSTR__fast, mp_module_fast);
