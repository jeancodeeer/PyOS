//! _fast: the system's @micropython.viper functions for CPUs MicroPython has
//! no native code emitter for (ARM64). Same arguments, same results;
//! Python picks them with kernel.arch.fast(fn, name).
//! tools/test_fast.py checks every one against its viper original.
//! A "pointer" argument is a buffer (bytes, bytearray, array) or an address.

use crate::py::{self, args, fun, int as I, ptr as P, Fun, FunFixed, FunVar, Fn3, Obj};

#[inline]
fn clamp8(v: i64) -> u8 {
    v.clamp(0, 255) as u8
}

/// Python's // (rounds down; Rust's / rounds towards zero).
#[inline]
fn fdiv(a: i64, b: i64) -> i64 {
    let q = a / b;
    if q * b != a && ((a < 0) != (b < 0)) { q - 1 } else { q }
}

#[inline]
fn s32(v: u32) -> i64 {
    v as i32 as i64
}

// ---- pygame/font.py ----

unsafe extern "C" fn font_put(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let dst: *mut u8 = P(a[0]);
    let (dw, dh, dx, dy) = (I(a[1]) as i64, I(a[2]) as i64, I(a[3]) as i64, I(a[4]) as i64);
    let src: *const u8 = P(a[5]);
    let (sw, sx, sy, w, h) = (I(a[6]) as i64, I(a[7]) as i64, I(a[8]) as i64, I(a[9]) as i64, I(a[10]) as i64);
    let (b, g, r) = (I(a[11]) as u8, I(a[12]) as u8, I(a[13]) as u8);
    for row in 0..h {
        let y = dy + row;
        if y < 0 || y >= dh {
            continue;
        }
        let s = src.offset(((sy + row) * sw + sx) as isize);
        for col in 0..w {
            let x = dx + col;
            if x < 0 || x >= dw {
                continue;
            }
            let al = *s.offset(col as isize);
            if al != 0 {
                let o = dst.offset(((y * dw + x) * 4) as isize);
                if al > *o.add(3) {
                    *o = b;
                    *o.add(1) = g;
                    *o.add(2) = r;
                    *o.add(3) = al;
                }
            }
        }
    }
    py::none()
}

unsafe extern "C" fn font_unrle(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let src: *const u8 = P(a[0]);
    let (mut i, end) = (I(a[1]), I(a[2]));
    let dst: *mut u8 = P(a[3]);
    let mut o = 0isize;
    while i < end {
        let b = *src.offset(i);
        if b == 0 {
            o += *src.offset(i + 1) as isize;
            i += 2;
        } else {
            *dst.offset(o) = b;
            o += 1;
            i += 1;
        }
    }
    py::none()
}

// ---- kernel/sound.py ----

unsafe extern "C" fn sound_widen(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let src: *const u8 = P(a[0]);
    let frames = I(a[1]);
    let dst: *mut u8 = P(a[2]);
    let (channels, bits) = (I(a[3]), I(a[4]));
    let (mut i, mut o) = (0isize, 0isize);
    for _ in 0..frames {
        if bits == 8 {
            let mut hi = (*src.offset(i)).wrapping_sub(128);
            i += 1;
            *dst.offset(o) = 0;
            *dst.offset(o + 1) = hi;
            if channels == 2 {
                hi = (*src.offset(i)).wrapping_sub(128);
                i += 1;
            }
            *dst.offset(o + 2) = 0;
            *dst.offset(o + 3) = hi;
        } else {
            *dst.offset(o) = *src.offset(i);
            *dst.offset(o + 1) = *src.offset(i + 1);
            if channels == 2 {
                i += 2;
            }
            *dst.offset(o + 2) = *src.offset(i);
            *dst.offset(o + 3) = *src.offset(i + 1);
            i += 2;
        }
        o += 4;
    }
    py::none()
}

unsafe extern "C" fn sound_stretch(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let src: *const u32 = P(a[0]);
    let dst: *mut u32 = P(a[2]);
    let (out_n, rate, target) = (I(a[3]) as i64, I(a[4]) as i64, I(a[5]) as i64);
    for k in 0..out_n {
        *dst.offset(k as isize) = *src.offset((k * rate / target) as isize);
    }
    py::none()
}

// ---- crypto/chacha.py ----

unsafe extern "C" fn chacha_rounds(xo: Obj, so: Obj, qro: Obj) -> Obj {
    let x: *mut u32 = P(xo);
    let s: *const u32 = P(so);
    let qr: *const u8 = P(qro);
    let x = core::slice::from_raw_parts_mut(x, 16);
    let s = core::slice::from_raw_parts(s, 16);
    let qr = core::slice::from_raw_parts(qr, 32);
    x.copy_from_slice(s);
    for _ in 0..10 {
        for q in 0..8 {
            let (ia, ib, ic, id) = (qr[4 * q] as usize, qr[4 * q + 1] as usize, qr[4 * q + 2] as usize, qr[4 * q + 3] as usize);
            let (mut xa, mut xb, mut xc, mut xd) = (x[ia], x[ib], x[ic], x[id]);
            xa = xa.wrapping_add(xb); xd ^= xa; xd = xd.rotate_left(16);
            xc = xc.wrapping_add(xd); xb ^= xc; xb = xb.rotate_left(12);
            xa = xa.wrapping_add(xb); xd ^= xa; xd = xd.rotate_left(8);
            xc = xc.wrapping_add(xd); xb ^= xc; xb = xb.rotate_left(7);
            x[ia] = xa; x[ib] = xb; x[ic] = xc; x[id] = xd;
        }
    }
    for i in 0..16 {
        x[i] = x[i].wrapping_add(s[i]);
    }
    py::none()
}

unsafe extern "C" fn chacha_xor(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let out: *mut u8 = P(a[0]);
    let (data, ks): (*const u8, *const u8) = (P(a[1]), P(a[2]));
    let (off, len) = (I(a[3]), I(a[4]));
    for i in 0..len {
        *out.offset(off + i) = *data.offset(off + i) ^ *ks.offset(i);
    }
    py::none()
}

// ---- imaging/jpeg.py (stb_image's integer IDCT) ----

/// One 8-point IDCT: (x0..x3, t0..t3) as stb_image's STBI__IDCT_1D.
#[inline]
fn idct_1d(s: [i64; 8]) -> ([i64; 4], [i64; 4]) {
    let (mut p2, mut p3) = (s[2], s[6]);
    let mut p1 = (p2 + p3) * 2217;
    let mut t2 = p1 + p3 * -7567;
    let mut t3 = p1 + p2 * 3135;
    p2 = s[0];
    p3 = s[4];
    let mut t0 = (p2 + p3) * 4096;
    let mut t1 = (p2 - p3) * 4096;
    let x = [t0 + t3, t1 + t2, t1 - t2, t0 - t3];
    t0 = s[7];
    t1 = s[5];
    t2 = s[3];
    t3 = s[1];
    p3 = t0 + t2;
    let mut p4 = t1 + t3;
    p1 = t0 + t3;
    p2 = t1 + t2;
    let p5 = (p3 + p4) * 4816;
    t0 *= 1223;
    t1 *= 8410;
    t2 *= 12586;
    t3 *= 6149;
    p1 = p5 + p1 * -3685;
    p2 = p5 + p2 * -10497;
    p3 *= -8034;
    p4 *= -1597;
    t3 += p1 + p4;
    t2 += p2 + p3;
    t1 += p2 + p4;
    t0 += p1 + p3;
    (x, [t0, t1, t2, t3])
}

unsafe extern "C" fn jpeg_idct(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let tmp = core::slice::from_raw_parts_mut(P::<i32>(a[0]), 64);
    let out: *mut u8 = P(a[1]);
    let (stride, off) = (I(a[2]), I(a[3]));
    for i in 0..8 {
        let col = [0, 8, 16, 24, 32, 40, 48, 56].map(|k| tmp[k + i] as i64);
        let (mut x, t) = idct_1d(col);
        for v in x.iter_mut() {
            *v += 512;
        }
        tmp[i] = ((x[0] + t[3]) >> 10) as i32;
        tmp[56 + i] = ((x[0] - t[3]) >> 10) as i32;
        tmp[8 + i] = ((x[1] + t[2]) >> 10) as i32;
        tmp[48 + i] = ((x[1] - t[2]) >> 10) as i32;
        tmp[16 + i] = ((x[2] + t[1]) >> 10) as i32;
        tmp[40 + i] = ((x[2] - t[1]) >> 10) as i32;
        tmp[24 + i] = ((x[3] + t[0]) >> 10) as i32;
        tmp[32 + i] = ((x[3] - t[0]) >> 10) as i32;
    }
    for r in 0..8 {
        let row = [0, 1, 2, 3, 4, 5, 6, 7].map(|k| tmp[r * 8 + k] as i64);
        let (mut x, t) = idct_1d(row);
        let bias = 65536 + (128 << 17);
        for v in x.iter_mut() {
            *v += bias;
        }
        let o = out.offset(off + r as isize * stride);
        *o = clamp8((x[0] + t[3]) >> 17);
        *o.add(7) = clamp8((x[0] - t[3]) >> 17);
        *o.add(1) = clamp8((x[1] + t[2]) >> 17);
        *o.add(6) = clamp8((x[1] - t[2]) >> 17);
        *o.add(2) = clamp8((x[2] + t[1]) >> 17);
        *o.add(5) = clamp8((x[2] - t[1]) >> 17);
        *o.add(3) = clamp8((x[3] + t[0]) >> 17);
        *o.add(4) = clamp8((x[3] - t[0]) >> 17);
    }
    py::none()
}

unsafe extern "C" fn jpeg_ycc(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let dst: *mut u8 = P(a[0]);
    let (y, cb, cr): (*const u8, *const u8, *const u8) = (P(a[1]), P(a[2]), P(a[3]));
    let (w, h, ys, cs, hs, vs) = (I(a[4]), I(a[5]), I(a[6]), I(a[7]), I(a[8]), I(a[9]));
    for row in 0..h {
        let yr = y.offset(row * ys);
        let co = (row >> vs) * cs;
        let mut d = dst.offset(row * w * 4);
        for col in 0..w {
            let yy = (*yr.offset(col) as i64) << 16;
            let b = *cb.offset(co + (col >> hs)) as i64 - 128;
            let r = *cr.offset(co + (col >> hs)) as i64 - 128;
            *d = clamp8((yy + b * 116130 + 32768) >> 16);
            *d.add(1) = clamp8((yy - b * 22554 - r * 46802 + 32768) >> 16);
            *d.add(2) = clamp8((yy + r * 91881 + 32768) >> 16);
            *d.add(3) = 255;
            d = d.add(4);
        }
    }
    py::none()
}

unsafe extern "C" fn jpeg_gray(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let dst: *mut u8 = P(a[0]);
    let y: *const u8 = P(a[1]);
    let (w, h, ys) = (I(a[2]), I(a[3]), I(a[4]));
    for row in 0..h {
        let mut d = dst.offset(row * w * 4);
        for col in 0..w {
            let v = *y.offset(row * ys + col);
            *d = v;
            *d.add(1) = v;
            *d.add(2) = v;
            *d.add(3) = 255;
            d = d.add(4);
        }
    }
    py::none()
}

// ---- OpenGL/raster.py ----

unsafe extern "C" fn fill32(bo: Obj, no: Obj, vo: Obj) -> Obj {
    let b: *mut u32 = P(bo);
    let v = I(vo) as u32;
    for i in 0..I(no) {
        *b.offset(i) = v;
    }
    py::none()
}

unsafe extern "C" fn rgb_to_rgba(so: Obj, d_o: Obj, no: Obj) -> Obj {
    let (s, d): (*const u8, *mut u8) = (P(so), P(d_o));
    for i in 0..I(no) {
        *d.offset(i * 4) = *s.offset(i * 3);
        *d.offset(i * 4 + 1) = *s.offset(i * 3 + 1);
        *d.offset(i * 4 + 2) = *s.offset(i * 3 + 2);
        *d.offset(i * 4 + 3) = 255;
    }
    py::none()
}

unsafe extern "C" fn triangles(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let color: *mut u8 = P(a[0]);
    let depth: *mut u32 = P(a[1]);
    let width = I(a[2]) as i64;
    let (verts, tris): (*const u32, *const u32) = (P(a[3]), P(a[4]));
    let count = I(a[5]) as i64;
    let tex: *const u8 = P(a[6]);
    let (tw, th) = (I(a[7]) as i64, I(a[8]) as i64);
    let state: *const u32 = P(a[9]);
    let st = |k: usize| *state.add(k);
    let (flags, cull, ccw) = (st(0) as i64, st(1) as i64, st(2) as i64);
    let (cx0, cx1, cy0, cy1) = (s32(st(3)), s32(st(4)), s32(st(5)), s32(st(6)));
    let (test, write, textured, modulate) = (flags & 1 != 0, flags & 2 != 0, flags & 4 != 0 && !tex.is_null(), flags & 8 != 0);
    let (lequal, blend) = (flags & 16 != 0, flags & 32 != 0);
    let (tmask, hmask) = (tw - 1, th - 1);
    let v = |i: i64| *verts.offset(i as isize);
    for t in 0..count {
        let mut i0 = *tris.offset((t * 3) as isize) as i64 * 10;
        let mut i1 = *tris.offset((t * 3 + 1) as isize) as i64 * 10;
        let mut i2 = *tris.offset((t * 3 + 2) as isize) as i64 * 10;
        let _ = &mut i0;
        let (x0, y0) = (s32(v(i0)), s32(v(i0 + 1)));
        let (mut x1, mut y1) = (s32(v(i1)), s32(v(i1 + 1)));
        let (mut x2, mut y2) = (s32(v(i2)), s32(v(i2 + 1)));
        let mut den = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0);
        if den == 0 {
            continue;
        }
        let front = (den < 0) as i64 == ccw;
        if cull == 3 || (cull == 1 && !front) || (cull == 2 && front) {
            continue;
        }
        if den < 0 {
            core::mem::swap(&mut i1, &mut i2);
            core::mem::swap(&mut x1, &mut x2);
            core::mem::swap(&mut y1, &mut y2);
            den = -den;
        }
        let mut minx = x0.min(x1).min(x2) >> 4;
        let mut maxx = x0.max(x1).max(x2) >> 4;
        let mut miny = y0.min(y1).min(y2) >> 4;
        let mut maxy = y0.max(y1).max(y2) >> 4;
        minx = minx.max(cx0);
        maxx = maxx.min(cx1);
        miny = miny.max(cy0);
        maxy = maxy.min(cy1);
        if minx > maxx || miny > maxy {
            continue;
        }
        let (px, py_) = (minx * 16 + 8, miny * 16 + 8);
        let (mut e0, e0x, e0y) = ((py_ - y0) * (x1 - x0) - (px - x0) * (y1 - y0), (y0 - y1) * 16, (x1 - x0) * 16);
        let (mut e1, e1x, e1y) = ((py_ - y1) * (x2 - x1) - (px - x1) * (y2 - y1), (y1 - y2) * 16, (x2 - x1) * 16);
        let (mut e2, e2x, e2y) = ((py_ - y2) * (x0 - x2) - (px - x2) * (y0 - y2), (y2 - y0) * 16, (x0 - x2) * 16);
        let (ay, by, bx, cx, ox, oy) = (y2 - y0, y1 - y0, x1 - x0, x2 - x0, px - x0, py_ - y0);
        let (mut st0, mut sx0, mut sy0) = ([0i64; 10], [0i64; 10], [0i64; 10]);
        for k in 2..10 {
            if k == 8 {
                continue;
            }
            let f0 = s32(v(i0 + k));
            let (d1, d2) = (s32(v(i1 + k)) - f0, s32(v(i2 + k)) - f0);
            let scale = if k == 2 { 4096 } else { 256 };
            let sx = fdiv((d1 * ay - d2 * by) * 16 * scale, den);
            let sy = fdiv((d2 * bx - d1 * cx) * 16 * scale, den);
            st0[k as usize] = f0 * scale + fdiv(sx * ox + sy * oy, 16);
            sx0[k as usize] = sx;
            sy0[k as usize] = sy;
        }
        let alpha = v(i0 + 8) as i64;
        let mut rowv = st0;
        for y in miny..=maxy {
            let (mut ea, mut eb, mut ec) = (e0, e1, e2);
            let mut c = rowv;
            let mut seen = false;
            for x in minx..=maxx {
                if (ea | eb | ec) >= 0 {
                    seen = true;
                    let o = (y * width + x) as isize;
                    let zz = c[2] >> 12;
                    let dz = *depth.offset(o) as i64;
                    if !test || zz < dz || (lequal && zz == dz) {
                        if write {
                            *depth.offset(o) = zz as u32;
                        }
                        let (mut cr, mut cg, mut cb) = (c[3] >> 16, c[4] >> 16, c[5] >> 16);
                        if textured {
                            let qq = if c[9] > 0 { c[9] } else { 1 };
                            let t = ((fdiv(c[7] << 8, qq) & hmask) * tw + (fdiv(c[6] << 8, qq) & tmask)) * 4;
                            let tx = |k: i64| *tex.offset((t + k) as isize) as i64;
                            if modulate {
                                cr = (cr * tx(0) + 128) >> 8;
                                cg = (cg * tx(1) + 128) >> 8;
                                cb = (cb * tx(2) + 128) >> 8;
                            } else {
                                cr = tx(0);
                                cg = tx(1);
                                cb = tx(2);
                            }
                        }
                        cr = cr.clamp(0, 255);
                        cg = cg.clamp(0, 255);
                        cb = cb.clamp(0, 255);
                        let c4 = color.offset(o * 4);
                        if blend {
                            let na = 255 - alpha;
                            cb = (cb * alpha + *c4 as i64 * na) >> 8;
                            cg = (cg * alpha + *c4.add(1) as i64 * na) >> 8;
                            cr = (cr * alpha + *c4.add(2) as i64 * na) >> 8;
                        }
                        *c4 = cb as u8;
                        *c4.add(1) = cg as u8;
                        *c4.add(2) = cr as u8;
                        *c4.add(3) = 255;
                    }
                } else if seen {
                    break;
                }
                ea += e0x;
                eb += e1x;
                ec += e2x;
                for k in [2usize, 3, 4, 5, 6, 7, 9] {
                    c[k] += sx0[k];
                }
            }
            e0 += e0y;
            e1 += e1y;
            e2 += e2y;
            for k in [2usize, 3, 4, 5, 6, 7, 9] {
                rowv[k] += sy0[k];
            }
        }
    }
    py::none()
}

unsafe extern "C" fn line(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let color: *mut u8 = P(a[0]);
    let depth: *mut u32 = P(a[1]);
    let v: [i64; 11] = core::array::from_fn(|k| I(a[k + 2]) as i64);
    let (width, height, mut x, mut y, mut z, dx, dy, steps, zstep, bgr, flags) =
        (v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10]);
    let (cb, cg, cr) = (bgr as u8, (bgr >> 8) as u8, (bgr >> 16) as u8);
    for _ in 0..=steps {
        let (px, py_) = (x >> 16, y >> 16);
        if px >= 0 && px < width && py_ >= 0 && py_ < height {
            let o = (py_ * width + px) as isize;
            let zz = z >> 16;
            if flags & 1 == 0 || zz <= *depth.offset(o) as i64 {
                if flags & 2 != 0 {
                    *depth.offset(o) = zz as u32;
                }
                let c4 = color.offset(o * 4);
                *c4 = cb;
                *c4.add(1) = cg;
                *c4.add(2) = cr;
                *c4.add(3) = 255;
            }
        }
        x += dx;
        y += dy;
        z += zstep;
    }
    py::none()
}

static FONT_PUT: FunVar = Fun::var(14, 14, font_put);
static FONT_UNRLE: FunVar = Fun::var(4, 4, font_unrle);
static SOUND_WIDEN: FunVar = Fun::var(5, 5, sound_widen);
static SOUND_STRETCH: FunVar = Fun::var(6, 6, sound_stretch);
static CHACHA_ROUNDS: FunFixed<Fn3> = Fun::f3(chacha_rounds);
static CHACHA_XOR: FunVar = Fun::var(5, 5, chacha_xor);
static JPEG_IDCT: FunVar = Fun::var(4, 4, jpeg_idct);
static JPEG_YCC: FunVar = Fun::var(10, 10, jpeg_ycc);
static JPEG_GRAY: FunVar = Fun::var(5, 5, jpeg_gray);
static FILL32: FunFixed<Fn3> = Fun::f3(fill32);
static RGB_TO_RGBA: FunFixed<Fn3> = Fun::f3(rgb_to_rgba);
static TRIANGLES: FunVar = Fun::var(10, 10, triangles);
static LINE: FunVar = Fun::var(13, 13, line);

/// `import _fast` (called once per Python session, from main.rs).
pub fn register() {
    py::define("_fast", &[
        ("font_put", fun(&FONT_PUT)), ("font_unrle", fun(&FONT_UNRLE)), ("sound_widen", fun(&SOUND_WIDEN)),
        ("sound_stretch", fun(&SOUND_STRETCH)), ("chacha_rounds", fun(&CHACHA_ROUNDS)), ("chacha_xor", fun(&CHACHA_XOR)),
        ("jpeg_idct", fun(&JPEG_IDCT)), ("jpeg_ycc", fun(&JPEG_YCC)), ("jpeg_gray", fun(&JPEG_GRAY)), ("fill32", fun(&FILL32)),
        ("rgb_to_rgba", fun(&RGB_TO_RGBA)), ("triangles", fun(&TRIANGLES)), ("line", fun(&LINE)),
    ]);
}
