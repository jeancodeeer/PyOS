//! _gfx: the pixel loops behind pygame (pyfs/lib/pygame). A surface is a
//! buffer of 32-bit pixels (B, G, R, A in memory) with a width and a height;
//! Python keeps the objects, Rust only moves pixels.

use crate::py::{self, args, buffer, fun, int, Fun, FunVar, Obj};

// In Rust, not libm's: on PCs the kernel's Rust code uses soft floating point,
// which does not call C's float functions the same way.
fn floor(x: f64) -> f64 {
    let t = x as i64 as f64;
    if t > x { t - 1.0 } else { t }
}

fn sqrt(x: f64) -> f64 {
    if x <= 0.0 {
        return 0.0;
    }
    let mut r = if x > 1.0 { x / 2.0 } else { 1.0 };
    for _ in 0..40 {
        let next = 0.5 * (r + x / r);
        if next == r {
            break;
        }
        r = next;
    }
    r
}

struct Surf {
    px: *mut u32,
    w: i64,
    h: i64,
}

impl Surf {
    fn new(buf: Obj, w: Obj, h: Obj) -> Surf {
        let (p, len) = buffer(buf);
        let (w, h) = (int(w) as i64, int(h) as i64);
        if w < 0 || h < 0 || (w * h * 4) as usize > len {
            py::value_error(b"buffer too small for surface\0");
        }
        Surf { px: p as *mut u32, w, h }
    }
    #[inline]
    fn at(&self, x: i64, y: i64) -> *mut u32 {
        unsafe { self.px.offset((y * self.w + x) as isize) }
    }
    #[inline]
    fn put(&self, x: i64, y: i64, c: u32) {
        if x >= 0 && x < self.w && y >= 0 && y < self.h {
            unsafe { *self.at(x, y) = c };
        }
    }
    fn hline(&self, mut x0: i64, mut x1: i64, y: i64, c: u32) {
        if y < 0 || y >= self.h {
            return;
        }
        if x0 > x1 {
            core::mem::swap(&mut x0, &mut x1);
        }
        let (x0, x1) = (x0.max(0), x1.min(self.w - 1));
        for x in x0..=x1 {
            unsafe { *self.at(x, y) = c };
        }
    }
    fn line(&self, mut x0: i64, mut y0: i64, x1: i64, y1: i64, c: u32) {
        let (dx, sx) = ((x1 - x0).abs(), if x0 < x1 { 1 } else { -1 });
        let (dy, sy) = (-(y1 - y0).abs(), if y0 < y1 { 1 } else { -1 });
        let mut err = dx + dy;
        for _ in 0..100_000 {
            self.put(x0, y0, c);
            if x0 == x1 && y0 == y1 {
                break;
            }
            let e2 = 2 * err;
            if e2 >= dy {
                err += dy;
                x0 += sx;
            }
            if e2 <= dx {
                err += dx;
                y0 += sy;
            }
        }
    }
}

fn i(o: Obj) -> i64 {
    int(o) as i64
}
fn color(o: Obj) -> u32 {
    int(o) as u32
}

unsafe extern "C" fn fill(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let s = Surf::new(a[0], a[1], a[2]);
    let (x, y, rw, rh, c) = (i(a[3]), i(a[4]), i(a[5]), i(a[6]), color(a[7]));
    let (x1, y1) = ((x + rw).min(s.w), (y + rh).min(s.h));
    for j in y.max(0)..y1 {
        for k in x.max(0)..x1 {
            *s.at(k, j) = c;
        }
    }
    py::none()
}

const BLIT_KEY: i64 = 1;      // skip pixels equal to `key`
const BLIT_SRCA: i64 = 2;     // blend with the source pixel's alpha
const BLIT_SURFA: i64 = 4;    // blend with `alpha` (0..255)

#[inline]
fn blend(d: u32, s: u32, a: u32) -> u32 {
    let rb = (((s & 0xFF00FF).wrapping_mul(a) + (d & 0xFF00FF).wrapping_mul(255 - a)) >> 8) & 0xFF00FF;
    let g = (((s & 0x00FF00).wrapping_mul(a) + (d & 0x00FF00).wrapping_mul(255 - a)) >> 8) & 0x00FF00;
    (d & 0xFF000000) | rb | g
}

unsafe extern "C" fn blit(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let d = Surf::new(a[0], a[1], a[2]);
    let (mut dx, mut dy) = (i(a[3]), i(a[4]));
    let s = Surf::new(a[5], a[6], a[7]);
    let (mut sx, mut sy, mut cw, mut ch) = (i(a[8]), i(a[9]), i(a[10]), i(a[11]));
    let flags = i(a[12]);
    let key = color(a[13]) & 0xFFFFFF;
    let alpha = (i(a[14]) & 0xFF) as u32;
    if sx < 0 { cw += sx; dx -= sx; sx = 0; }
    if sy < 0 { ch += sy; dy -= sy; sy = 0; }
    if sx + cw > s.w { cw = s.w - sx; }
    if sy + ch > s.h { ch = s.h - sy; }
    if dx < 0 { cw += dx; sx -= dx; dx = 0; }
    if dy < 0 { ch += dy; sy -= dy; dy = 0; }
    if dx + cw > d.w { cw = d.w - dx; }
    if dy + ch > d.h { ch = d.h - dy; }
    if cw <= 0 || ch <= 0 {
        return py::none();
    }
    for j in 0..ch {
        let dp = d.at(dx, dy + j);
        let sp = s.at(sx, sy + j);
        if flags == 0 {
            core::ptr::copy(sp, dp, cw as usize);
            continue;
        }
        for k in 0..cw as isize {
            let p = *sp.offset(k);
            if flags & BLIT_KEY != 0 && p & 0xFFFFFF == key {
                continue;
            }
            let mut al = 255;
            if flags & BLIT_SRCA != 0 {
                al = p >> 24;
            }
            if flags & BLIT_SURFA != 0 {
                al = al * alpha / 255;
            }
            let q = dp.offset(k);
            *q = if al == 255 { p | 0xFF000000 } else if al == 0 { *q } else { blend(*q, p, al) };
        }
    }
    py::none()
}

unsafe extern "C" fn line(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let s = Surf::new(a[0], a[1], a[2]);
    let (x0, y0, x1, y1, c) = (i(a[3]), i(a[4]), i(a[5]), i(a[6]), color(a[7]));
    let width = if n > 8 { i(a[8]) } else { 1 };
    let steep = (y1 - y0).abs() > (x1 - x0).abs();
    for k in 0..width.max(1) {
        let o = k - (width - 1) / 2;
        if steep {
            s.line(x0 + o, y0, x1 + o, y1, c);
        } else {
            s.line(x0, y0 + o, x1, y1 + o, c);
        }
    }
    py::none()
}

unsafe extern "C" fn ellipse(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let s = Surf::new(a[0], a[1], a[2]);
    let (bx, by, ew, eh, c, width) = (i(a[3]), i(a[4]), i(a[5]), i(a[6]), color(a[7]), i(a[8]));
    if ew <= 0 || eh <= 0 {
        return py::none();
    }
    let (rx, ry) = (ew as f64 / 2.0, eh as f64 / 2.0);
    let (cx, cy) = (bx as f64 + rx, by as f64 + ry);
    let (irx, iry) = (rx - width as f64, ry - width as f64);
    for j in 0..eh {
        let dy = (by + j) as f64 + 0.5 - cy;
        let hw = rx * sqrt(1.0 - dy * dy / (ry * ry));
        let (l, r) = (floor(cx - hw + 0.5) as i64, floor(cx + hw - 0.5) as i64);
        if r < l {
            continue;
        }
        if width <= 0 || irx <= 0.0 || iry <= 0.0 || dy * dy >= iry * iry {
            s.hline(l, r, by + j, c);
            continue;
        }
        let ihw = irx * sqrt(1.0 - dy * dy / (iry * iry));
        let (il, ir) = (floor(cx - ihw + 0.5) as i64, floor(cx + ihw - 0.5) as i64);
        s.hline(l, il - 1, by + j, c);
        s.hline(ir + 1, r, by + j, c);
    }
    py::none()
}

unsafe extern "C" fn polygon(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let s = Surf::new(a[0], a[1], a[2]);
    let pts = py::items(a[3]);
    let c = color(a[4]);
    let count = pts.len();
    if !(3..=1024).contains(&count) {
        return py::none();
    }
    let mut xs = [0i64; 1024];
    let mut ys = [0i64; 1024];
    let (mut ymin, mut ymax) = (i64::MAX, i64::MIN);
    for (k, p) in pts.iter().enumerate() {
        let xy = py::items(*p);
        if xy.len() != 2 {
            py::value_error(b"points must be (x, y) pairs\0");
        }
        xs[k] = i(xy[0]);
        ys[k] = i(xy[1]);
        ymin = ymin.min(ys[k]);
        ymax = ymax.max(ys[k]);
    }
    let mut cross = [0i64; 1024];
    for y in ymin.max(0)..=ymax.min(s.h - 1) {
        let mut k = 0;
        for p in 0..count {
            let q = (p + 1) % count;
            let (y0, y1) = (ys[p], ys[q]);
            if y0 == y1 {
                continue;
            }
            if (y >= y0 && y < y1) || (y >= y1 && y < y0) {
                cross[k] = xs[p] + (y - y0) * (xs[q] - xs[p]) / (y1 - y0);
                k += 1;
            }
        }
        cross[..k].sort_unstable();
        for pair in cross[..k].chunks_exact(2) {
            s.hline(pair[0], pair[1], y, c);
        }
    }
    py::none()
}

unsafe extern "C" fn scale(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let s = Surf::new(a[0], a[1], a[2]);
    let d = Surf::new(a[3], a[4], a[5]);
    if s.w == 0 || s.h == 0 {
        return py::none();
    }
    for y in 0..d.h {
        let sy = y * s.h / d.h;
        for x in 0..d.w {
            *d.at(x, y) = *s.at(x * s.w / d.w, sy);
        }
    }
    py::none()
}

unsafe extern "C" fn flip(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let s = Surf::new(a[0], a[1], a[2]);
    let d = Surf::new(a[3], a[1], a[2]);
    let (fx, fy) = (py::truthy(a[4]), py::truthy(a[5]));
    for y in 0..s.h {
        let sy = if fy { s.h - 1 - y } else { y };
        for x in 0..s.w {
            *d.at(x, y) = *s.at(if fx { s.w - 1 - x } else { x }, sy);
        }
    }
    py::none()
}

unsafe extern "C" fn rotate(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let s = Surf::new(a[0], a[1], a[2]);
    let d = Surf::new(a[3], a[4], a[5]);
    let (ca, sa, fillc) = (i(a[6]), i(a[7]), color(a[8]));
    let (scx, scy) = (s.w * 32768, s.h * 32768);         // centres in 16.16
    for y in 0..d.h {
        let ry = 2 * y + 1 - d.h;                           // doubled, from the centre
        for x in 0..d.w {
            let rx = 2 * x + 1 - d.w;
            let ux = (rx * ca - ry * sa) / 2 + scx;         // 16.16 source position
            let uy = (rx * sa + ry * ca) / 2 + scy;
            let (ix, iy) = (ux >> 16, uy >> 16);
            *d.at(x, y) = if ux >= 0 && uy >= 0 && ix < s.w && iy < s.h { *s.at(ix, iy) } else { fillc };
        }
    }
    py::none()
}

unsafe extern "C" fn text(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let s = Surf::new(a[0], a[1], a[2]);
    let (x0, y0) = (i(a[3]), i(a[4]));
    let font = py::bytes(a[5]);
    let chars = py::bytes(a[6]);
    if font.len() < 256 * 16 {
        py::value_error(b"font must be 4096 bytes\0");
    }
    let (fg, sx, sy, bg) = (color(a[7]), i(a[8]), i(a[9]), i(a[10]));
    for (k, &ch) in chars.iter().enumerate() {
        let g = &font[ch as usize * 16..ch as usize * 16 + 16];
        let cx = x0 + k as i64 * 8 * sx;
        for r in 0..16 * sy {
            let bits = g[(r / sy) as usize];
            let py_ = y0 + r;
            if py_ < 0 || py_ >= s.h {
                continue;
            }
            for c in 0..8 * sx {
                let px = cx + c;
                if px < 0 || px >= s.w {
                    continue;
                }
                if bits & (0x80 >> (c / sx)) != 0 {
                    *s.at(px, py_) = fg;
                } else if bg >= 0 {
                    *s.at(px, py_) = bg as u32;
                }
            }
        }
    }
    py::none()
}

unsafe extern "C" fn get_at(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let s = Surf::new(a[0], a[1], a[2]);
    let (x, y) = (i(a[3]), i(a[4]));
    if x < 0 || x >= s.w || y < 0 || y >= s.h {
        py::index_error(b"pixel index out of range\0");
    }
    py::new_uint(*s.at(x, y) as u64)
}

unsafe extern "C" fn set_at(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let s = Surf::new(a[0], a[1], a[2]);
    s.put(i(a[3]), i(a[4]), color(a[5]));
    py::none()
}

unsafe extern "C" fn present(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let (fb, fb_len) = buffer(a[0]);
    let pitch = i(a[1]);
    let s = Surf::new(a[2], a[3], a[4]);
    let (mut x, mut y, mut rw, mut rh) = (i(a[5]), i(a[6]), i(a[7]), i(a[8]));
    if x < 0 { rw += x; x = 0; }
    if y < 0 { rh += y; y = 0; }
    if x + rw > s.w { rw = s.w - x; }
    if y + rh > s.h { rh = s.h - y; }
    if rw <= 0 || rh <= 0 || ((y + rh - 1) * pitch + (x + rw) * 4) as usize > fb_len {
        return py::none();
    }
    for j in y..y + rh {
        core::ptr::copy_nonoverlapping(s.at(x, j) as *const u8, fb.offset((j * pitch + x * 4) as isize), (rw * 4) as usize);
    }
    py::none()
}

static FILL: FunVar = Fun::var(8, 8, fill);
static BLIT: FunVar = Fun::var(15, 15, blit);
static LINE: FunVar = Fun::var(8, 9, line);
static ELLIPSE: FunVar = Fun::var(9, 9, ellipse);
static POLYGON: FunVar = Fun::var(5, 5, polygon);
static SCALE: FunVar = Fun::var(6, 6, scale);
static FLIP: FunVar = Fun::var(6, 6, flip);
static ROTATE: FunVar = Fun::var(9, 9, rotate);
static TEXT: FunVar = Fun::var(11, 11, text);
static GET_AT: FunVar = Fun::var(5, 5, get_at);
static SET_AT: FunVar = Fun::var(6, 6, set_at);
static PRESENT: FunVar = Fun::var(9, 9, present);

pub fn register() {
    py::define("_gfx", &[
        ("fill", fun(&FILL)), ("blit", fun(&BLIT)), ("line", fun(&LINE)), ("ellipse", fun(&ELLIPSE)),
        ("polygon", fun(&POLYGON)), ("scale", fun(&SCALE)), ("flip", fun(&FLIP)), ("rotate", fun(&ROTATE)),
        ("text", fun(&TEXT)), ("get_at", fun(&GET_AT)), ("set_at", fun(&SET_AT)), ("present", fun(&PRESENT)),
    ]);
}
