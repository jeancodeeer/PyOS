// _gfx: pixel primitives for the Python graphics stack (pygame).
//
// Mechanism only, no policy: every function works on a caller-supplied
// buffer of 32-bit pixels (0xAARRGGBB, little endian: B G R A in memory --
// the same layout as a 32 bpp linear framebuffer), width w and height h.
// Everything is clipped to the buffer. The pygame module in /lib/pygame is
// the Python that decides what to draw.

#include <string.h>
#include <math.h>
#include "py/runtime.h"
#include "py/obj.h"

#define ARG_INT(i) mp_obj_get_int(args[i])

typedef struct {
    uint32_t *px;
    int w, h;
} surf_t;

static surf_t get_surf(mp_obj_t buf, mp_obj_t w, mp_obj_t h, mp_uint_t flags) {
    mp_buffer_info_t info;
    mp_get_buffer_raise(buf, &info, flags);
    surf_t s = { (uint32_t *)info.buf, mp_obj_get_int(w), mp_obj_get_int(h) };
    if (s.w < 0 || s.h < 0 || (size_t)s.w * s.h * 4 > info.len) {
        mp_raise_ValueError(MP_ERROR_TEXT("buffer too small for surface"));
    }
    return s;
}

static inline void put(surf_t *s, int x, int y, uint32_t c) {
    if ((unsigned)x < (unsigned)s->w && (unsigned)y < (unsigned)s->h) {
        s->px[y * s->w + x] = c;
    }
}

static void hline(surf_t *s, int x0, int x1, int y, uint32_t c) {
    if ((unsigned)y >= (unsigned)s->h) {
        return;
    }
    if (x0 > x1) {
        int t = x0; x0 = x1; x1 = t;
    }
    if (x0 < 0) {
        x0 = 0;
    }
    if (x1 >= s->w) {
        x1 = s->w - 1;
    }
    uint32_t *p = s->px + y * s->w;
    for (int x = x0; x <= x1; x++) {
        p[x] = c;
    }
}

// fill(buf, w, h, x, y, rw, rh, color)
static mp_obj_t gfx_fill(size_t n_args, const mp_obj_t *args) {
    surf_t s = get_surf(args[0], args[1], args[2], MP_BUFFER_WRITE);
    int x = ARG_INT(3), y = ARG_INT(4), rw = ARG_INT(5), rh = ARG_INT(6);
    uint32_t c = mp_obj_get_int_truncated(args[7]);
    int x1 = x + rw, y1 = y + rh;
    if (x < 0) x = 0;
    if (y < 0) y = 0;
    if (x1 > s.w) x1 = s.w;
    if (y1 > s.h) y1 = s.h;
    for (int j = y; j < y1; j++) {
        uint32_t *p = s.px + j * s.w;
        for (int i = x; i < x1; i++) {
            p[i] = c;
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_fill_obj, 8, 8, gfx_fill);

#define BLIT_KEY   1      // skip pixels equal to `key`
#define BLIT_SRCA  2      // blend with the source pixel's alpha
#define BLIT_SURFA 4      // blend with `alpha` (0..255)

static inline uint32_t blend(uint32_t d, uint32_t s, uint32_t a) {
    uint32_t rb = (((s & 0xFF00FF) * a + (d & 0xFF00FF) * (255 - a)) >> 8) & 0xFF00FF;
    uint32_t g = (((s & 0x00FF00) * a + (d & 0x00FF00) * (255 - a)) >> 8) & 0x00FF00;
    return (d & 0xFF000000) | rb | g;
}

// blit(dst, dw, dh, dx, dy, src, sw, sh, sx, sy, cw, ch, flags, key, alpha)
static mp_obj_t gfx_blit(size_t n_args, const mp_obj_t *args) {
    surf_t d = get_surf(args[0], args[1], args[2], MP_BUFFER_WRITE);
    int dx = ARG_INT(3), dy = ARG_INT(4);
    surf_t s = get_surf(args[5], args[6], args[7], MP_BUFFER_READ);
    int sx = ARG_INT(8), sy = ARG_INT(9), cw = ARG_INT(10), ch = ARG_INT(11);
    int flags = ARG_INT(12);
    uint32_t key = mp_obj_get_int_truncated(args[13]) & 0xFFFFFF;
    uint32_t alpha = ARG_INT(14) & 0xFF;
    // clip against the source, then the destination
    if (sx < 0) { cw += sx; dx -= sx; sx = 0; }
    if (sy < 0) { ch += sy; dy -= sy; sy = 0; }
    if (sx + cw > s.w) cw = s.w - sx;
    if (sy + ch > s.h) ch = s.h - sy;
    if (dx < 0) { cw += dx; sx -= dx; dx = 0; }
    if (dy < 0) { ch += dy; sy -= dy; dy = 0; }
    if (dx + cw > d.w) cw = d.w - dx;
    if (dy + ch > d.h) ch = d.h - dy;
    if (cw <= 0 || ch <= 0) {
        return mp_const_none;
    }
    for (int j = 0; j < ch; j++) {
        uint32_t *dp = d.px + (dy + j) * d.w + dx;
        const uint32_t *sp = s.px + (sy + j) * s.w + sx;
        if (!flags) {
            memmove(dp, sp, cw * 4);
            continue;
        }
        for (int i = 0; i < cw; i++) {
            uint32_t p = sp[i];
            if ((flags & BLIT_KEY) && (p & 0xFFFFFF) == key) {
                continue;
            }
            uint32_t a = 255;
            if (flags & BLIT_SRCA) {
                a = p >> 24;
            }
            if (flags & BLIT_SURFA) {
                a = a * alpha / 255;
            }
            dp[i] = a == 255 ? (p | 0xFF000000) : a == 0 ? dp[i] : blend(dp[i], p, a);
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_blit_obj, 15, 15, gfx_blit);

static void line(surf_t *s, int x0, int y0, int x1, int y1, uint32_t c) {
    int dx = x1 > x0 ? x1 - x0 : x0 - x1, sx = x0 < x1 ? 1 : -1;
    int dy = y1 > y0 ? y0 - y1 : y1 - y0, sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;
    for (int n = 0; n < 100000; n++) {
        put(s, x0, y0, c);
        if (x0 == x1 && y0 == y1) {
            break;
        }
        int e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
    }
}

// line(buf, w, h, x0, y0, x1, y1, color, width)
static mp_obj_t gfx_line(size_t n_args, const mp_obj_t *args) {
    surf_t s = get_surf(args[0], args[1], args[2], MP_BUFFER_WRITE);
    int x0 = ARG_INT(3), y0 = ARG_INT(4), x1 = ARG_INT(5), y1 = ARG_INT(6);
    uint32_t c = mp_obj_get_int_truncated(args[7]);
    int width = n_args > 8 ? ARG_INT(8) : 1;
    int steep = (y1 > y0 ? y1 - y0 : y0 - y1) > (x1 > x0 ? x1 - x0 : x0 - x1);
    for (int k = 0; k < (width < 1 ? 1 : width); k++) {
        int o = k - (width - 1) / 2;
        if (steep) {
            line(&s, x0 + o, y0, x1 + o, y1, c);
        } else {
            line(&s, x0, y0 + o, x1, y1 + o, c);
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_line_obj, 8, 9, gfx_line);

// ellipse(buf, w, h, x, y, ew, eh, color, width): inside the box x,y,ew,eh;
// width 0 fills it. circle() is an ellipse in a square box.
static mp_obj_t gfx_ellipse(size_t n_args, const mp_obj_t *args) {
    surf_t s = get_surf(args[0], args[1], args[2], MP_BUFFER_WRITE);
    int bx = ARG_INT(3), by = ARG_INT(4), ew = ARG_INT(5), eh = ARG_INT(6);
    uint32_t c = mp_obj_get_int_truncated(args[7]);
    int width = ARG_INT(8);
    if (ew <= 0 || eh <= 0) {
        return mp_const_none;
    }
    double rx = ew / 2.0, ry = eh / 2.0, cx = bx + rx, cy = by + ry;
    double irx = rx - width, iry = ry - width;
    for (int j = 0; j < eh; j++) {
        double dy = by + j + 0.5 - cy;
        double hw = rx * sqrt(1.0 - dy * dy / (ry * ry));
        int l = (int)floor(cx - hw + 0.5), r = (int)floor(cx + hw - 0.5);
        if (r < l) {
            continue;
        }
        if (width <= 0 || irx <= 0 || iry <= 0 || dy * dy >= iry * iry) {
            hline(&s, l, r, by + j, c);
            continue;
        }
        double ihw = irx * sqrt(1.0 - dy * dy / (iry * iry));
        int il = (int)floor(cx - ihw + 0.5), ir = (int)floor(cx + ihw - 0.5);
        hline(&s, l, il - 1, by + j, c);
        hline(&s, ir + 1, r, by + j, c);
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_ellipse_obj, 9, 9, gfx_ellipse);

// polygon(buf, w, h, points, color): filled, even-odd scanline fill.
static mp_obj_t gfx_polygon(size_t n_args, const mp_obj_t *args) {
    surf_t s = get_surf(args[0], args[1], args[2], MP_BUFFER_WRITE);
    size_t n;
    mp_obj_t *items;
    mp_obj_get_array(args[3], &n, &items);
    uint32_t c = mp_obj_get_int_truncated(args[4]);
    if (n < 3 || n > 1024) {
        return mp_const_none;
    }
    int *xs = m_new(int, n), *ys = m_new(int, n), *cross = m_new(int, n);
    int ymin = 1 << 30, ymax = -(1 << 30);
    for (size_t i = 0; i < n; i++) {
        mp_obj_t *pt;
        mp_obj_get_array_fixed_n(items[i], 2, &pt);
        xs[i] = mp_obj_get_int(pt[0]);
        ys[i] = mp_obj_get_int(pt[1]);
        if (ys[i] < ymin) ymin = ys[i];
        if (ys[i] > ymax) ymax = ys[i];
    }
    if (ymin < 0) ymin = 0;
    if (ymax >= s.h) ymax = s.h - 1;
    for (int y = ymin; y <= ymax; y++) {
        int k = 0;
        for (size_t i = 0; i < n; i++) {
            size_t j = (i + 1) % n;
            int y0 = ys[i], y1 = ys[j];
            if (y0 == y1) {
                continue;
            }
            if ((y >= y0 && y < y1) || (y >= y1 && y < y0)) {
                cross[k++] = xs[i] + (int)((long)(y - y0) * (xs[j] - xs[i]) / (y1 - y0));
            }
        }
        for (int a = 1; a < k; a++) {               // insertion sort: k is small
            int v = cross[a], b = a - 1;
            while (b >= 0 && cross[b] > v) {
                cross[b + 1] = cross[b];
                b--;
            }
            cross[b + 1] = v;
        }
        for (int a = 0; a + 1 < k; a += 2) {
            hline(&s, cross[a], cross[a + 1], y, c);
        }
    }
    m_del(int, xs, n);
    m_del(int, ys, n);
    m_del(int, cross, n);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_polygon_obj, 5, 5, gfx_polygon);

// scale(src, sw, sh, dst, dw, dh): nearest neighbour.
static mp_obj_t gfx_scale(size_t n_args, const mp_obj_t *args) {
    surf_t s = get_surf(args[0], args[1], args[2], MP_BUFFER_READ);
    surf_t d = get_surf(args[3], args[4], args[5], MP_BUFFER_WRITE);
    if (!s.w || !s.h) {
        return mp_const_none;
    }
    for (int y = 0; y < d.h; y++) {
        const uint32_t *row = s.px + (long)y * s.h / d.h * s.w;
        uint32_t *out = d.px + y * d.w;
        for (int x = 0; x < d.w; x++) {
            out[x] = row[(long)x * s.w / d.w];
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_scale_obj, 6, 6, gfx_scale);

// flip(src, w, h, dst, xflip, yflip)
static mp_obj_t gfx_flip(size_t n_args, const mp_obj_t *args) {
    surf_t s = get_surf(args[0], args[1], args[2], MP_BUFFER_READ);
    surf_t d = get_surf(args[3], args[1], args[2], MP_BUFFER_WRITE);
    int fx = mp_obj_is_true(args[4]), fy = mp_obj_is_true(args[5]);
    for (int y = 0; y < s.h; y++) {
        const uint32_t *row = s.px + (fy ? s.h - 1 - y : y) * s.w;
        uint32_t *out = d.px + y * d.w;
        for (int x = 0; x < s.w; x++) {
            out[x] = row[fx ? s.w - 1 - x : x];
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_flip_obj, 6, 6, gfx_flip);

// rotate(src, sw, sh, dst, dw, dh, cos*65536, sin*65536, fill): turn
// counter-clockwise about the centres (inverse mapping, nearest neighbour).
static mp_obj_t gfx_rotate(size_t n_args, const mp_obj_t *args) {
    surf_t s = get_surf(args[0], args[1], args[2], MP_BUFFER_READ);
    surf_t d = get_surf(args[3], args[4], args[5], MP_BUFFER_WRITE);
    long ca = ARG_INT(6), sa = ARG_INT(7);
    uint32_t fill = mp_obj_get_int_truncated(args[8]);
    long scx = s.w * 32768L, scy = s.h * 32768L;     // centres in 16.16
    for (int y = 0; y < d.h; y++) {
        long ry = 2 * y + 1 - d.h;                      // doubled, from the centre
        uint32_t *out = d.px + y * d.w;
        for (int x = 0; x < d.w; x++) {
            long rx = 2 * x + 1 - d.w;
            long ux = (rx * ca - ry * sa) / 2 + scx;    // 16.16 source position
            long uy = (rx * sa + ry * ca) / 2 + scy;
            long ix = ux >> 16, iy = uy >> 16;
            out[x] = (ux >= 0 && uy >= 0 && ix < s.w && iy < s.h) ? s.px[iy * s.w + ix] : fill;
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_rotate_obj, 9, 9, gfx_rotate);

// text(buf, w, h, x, y, font, chars, color, sx, sy, bg): `font` is 256
// glyphs of 16 rows x 8 bits; `chars` are code page 437 bytes. bg < 0
// leaves the background alone.
static mp_obj_t gfx_text(size_t n_args, const mp_obj_t *args) {
    surf_t s = get_surf(args[0], args[1], args[2], MP_BUFFER_WRITE);
    int x0 = ARG_INT(3), y0 = ARG_INT(4);
    mp_buffer_info_t font, chars;
    mp_get_buffer_raise(args[5], &font, MP_BUFFER_READ);
    mp_get_buffer_raise(args[6], &chars, MP_BUFFER_READ);
    if (font.len < 256 * 16) {
        mp_raise_ValueError(MP_ERROR_TEXT("font must be 4096 bytes"));
    }
    uint32_t fg = mp_obj_get_int_truncated(args[7]);
    int sx = ARG_INT(8), sy = ARG_INT(9);
    mp_int_t bg = mp_obj_get_int(args[10]);
    const uint8_t *glyphs = font.buf, *str = chars.buf;
    for (size_t k = 0; k < chars.len; k++) {
        const uint8_t *g = glyphs + str[k] * 16;
        int cx = x0 + (int)k * 8 * sx;
        for (int r = 0; r < 16 * sy; r++) {
            uint8_t bits = g[r / sy];
            int py = y0 + r;
            if ((unsigned)py >= (unsigned)s.h) {
                continue;
            }
            for (int c = 0; c < 8 * sx; c++) {
                int px = cx + c;
                if ((unsigned)px >= (unsigned)s.w) {
                    continue;
                }
                if (bits & (0x80 >> (c / sx))) {
                    s.px[py * s.w + px] = fg;
                } else if (bg >= 0) {
                    s.px[py * s.w + px] = (uint32_t)bg;
                }
            }
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_text_obj, 11, 11, gfx_text);

// get_at(buf, w, h, x, y) / set_at(buf, w, h, x, y, color)
static mp_obj_t gfx_get_at(size_t n_args, const mp_obj_t *args) {
    surf_t s = get_surf(args[0], args[1], args[2], MP_BUFFER_READ);
    int x = ARG_INT(3), y = ARG_INT(4);
    if ((unsigned)x >= (unsigned)s.w || (unsigned)y >= (unsigned)s.h) {
        mp_raise_msg(&mp_type_IndexError, MP_ERROR_TEXT("pixel index out of range"));
    }
    return mp_obj_new_int_from_uint(s.px[y * s.w + x]);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_get_at_obj, 5, 5, gfx_get_at);

static mp_obj_t gfx_set_at(size_t n_args, const mp_obj_t *args) {
    surf_t s = get_surf(args[0], args[1], args[2], MP_BUFFER_WRITE);
    put(&s, ARG_INT(3), ARG_INT(4), mp_obj_get_int_truncated(args[5]));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_set_at_obj, 6, 6, gfx_set_at);

// present(fb, pitch_bytes, src, w, h, x, y, rw, rh): copy a rectangle of a
// w x h surface to the same place in a 32 bpp framebuffer.
static mp_obj_t gfx_present(size_t n_args, const mp_obj_t *args) {
    mp_buffer_info_t fb;
    mp_get_buffer_raise(args[0], &fb, MP_BUFFER_WRITE);
    int pitch = ARG_INT(1);
    surf_t s = get_surf(args[2], args[3], args[4], MP_BUFFER_READ);
    int x = ARG_INT(5), y = ARG_INT(6), rw = ARG_INT(7), rh = ARG_INT(8);
    if (x < 0) { rw += x; x = 0; }
    if (y < 0) { rh += y; y = 0; }
    if (x + rw > s.w) rw = s.w - x;
    if (y + rh > s.h) rh = s.h - y;
    if (rw <= 0 || rh <= 0 || (size_t)(y + rh - 1) * pitch + (x + rw) * 4 > fb.len) {
        return mp_const_none;
    }
    for (int j = y; j < y + rh; j++) {
        memcpy((uint8_t *)fb.buf + (size_t)j * pitch + x * 4, s.px + j * s.w + x, rw * 4);
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_present_obj, 9, 9, gfx_present);

static const mp_rom_map_elem_t gfx_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__gfx) },
    { MP_ROM_QSTR(MP_QSTR_fill), MP_ROM_PTR(&gfx_fill_obj) },
    { MP_ROM_QSTR(MP_QSTR_blit), MP_ROM_PTR(&gfx_blit_obj) },
    { MP_ROM_QSTR(MP_QSTR_line), MP_ROM_PTR(&gfx_line_obj) },
    { MP_ROM_QSTR(MP_QSTR_ellipse), MP_ROM_PTR(&gfx_ellipse_obj) },
    { MP_ROM_QSTR(MP_QSTR_polygon), MP_ROM_PTR(&gfx_polygon_obj) },
    { MP_ROM_QSTR(MP_QSTR_scale), MP_ROM_PTR(&gfx_scale_obj) },
    { MP_ROM_QSTR(MP_QSTR_flip), MP_ROM_PTR(&gfx_flip_obj) },
    { MP_ROM_QSTR(MP_QSTR_rotate), MP_ROM_PTR(&gfx_rotate_obj) },
    { MP_ROM_QSTR(MP_QSTR_text), MP_ROM_PTR(&gfx_text_obj) },
    { MP_ROM_QSTR(MP_QSTR_get_at), MP_ROM_PTR(&gfx_get_at_obj) },
    { MP_ROM_QSTR(MP_QSTR_set_at), MP_ROM_PTR(&gfx_set_at_obj) },
    { MP_ROM_QSTR(MP_QSTR_present), MP_ROM_PTR(&gfx_present_obj) },
};
static MP_DEFINE_CONST_DICT(gfx_globals, gfx_globals_table);

const mp_obj_module_t mp_module_gfx = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&gfx_globals,
};
MP_REGISTER_MODULE(MP_QSTR__gfx, mp_module_gfx);
