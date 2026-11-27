// media: audio and video decoding in machine code, for the PyOS players.
//
// Decoding a video in Python would be thousands of times too slow, so the
// work that touches every pixel and every sample is done here, by three
// open-source decoders compiled into the kernel (see mpy/media/):
//
//   media.H264()   H.264 video, Baseline profile (h264bsd, Apache 2.0, from Android)
//   media.AAC(cfg) AAC-LC / HE-AAC audio (Helix, RealNetworks RPSL)
//   media.MP3()    MP3 audio (minimp3, public domain)
//
// Everything else (reading MP4 files, timing, the window) is Python:
// pyos/lib/media/.
//
// The decoders allocate memory with malloc(). It comes from an "arena", a
// piece of RAM outside the Python heap that Python hands over first with
// media.arena(address, size): the garbage collector never moves or frees it.
#include <string.h>
#include "py/runtime.h"
#include "py/obj.h"
#include "py/objstr.h"

// ---- memory: malloc / free over the arena (see arena.c) ----

void arena_set(uintptr_t addr, size_t size);
int arena_ready(void);
size_t arena_free_bytes(void);
void *malloc(size_t n);
void free(void *p);
void *calloc(size_t n, size_t size);
void *realloc(void *p, size_t n);

// the little C library the decoders need and the kernel does not have
int abs(int x) {
    return x < 0 ? -x : x;
}

static void need_arena(void) {
    if (!arena_ready()) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("media: call media.arena() first"));
    }
}

// arena(address, size): RAM for the decoders (once, at start)
static mp_obj_t media_arena(mp_obj_t addr, mp_obj_t size) {
    if (!arena_ready()) {
        arena_set((uintptr_t)mp_obj_get_int_truncated(addr), (size_t)mp_obj_get_int_truncated(size));
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(media_arena_obj, media_arena);

// arena_free() -> bytes free in the arena
static mp_obj_t media_arena_free(void) {
    return mp_obj_new_int_from_uint(arena_free_bytes());
}
static MP_DEFINE_CONST_FUN_OBJ_0(media_arena_free_obj, media_arena_free);

// ---- colours: YUV 4:2:0 (what video decoders give) -> the screen's B G R A ----

static inline uint8_t clamp8(int v) {
    return v < 0 ? 0 : (v > 255 ? 255 : (uint8_t)v);
}

// Converts and scales (nearest neighbour) a w x h picture into a dw x dh
// part of a 32-bit buffer of width stride, at (dx, dy).
static void yuv420_to_bgra(const uint8_t *y, const uint8_t *u, const uint8_t *v, int w, int h, int ystride,
                           int cstride, uint32_t *dst, int stride, int dx, int dy, int dw, int dh) {
    for (int j = 0; j < dh; j++) {
        int sy = j * h / dh;
        const uint8_t *yr = y + sy * ystride;
        const uint8_t *ur = u + (sy >> 1) * cstride;
        const uint8_t *vr = v + (sy >> 1) * cstride;
        uint32_t *out = dst + (dy + j) * stride + dx;
        int step = (w << 16) / dw, sx = 0;
        for (int i = 0; i < dw; i++, sx += step) {
            int x = sx >> 16;
            int c = (yr[x] - 16) * 298;
            int d = ur[x >> 1] - 128, e = vr[x >> 1] - 128;
            int r = (c + 409 * e + 128) >> 8;
            int g = (c - 100 * d - 208 * e + 128) >> 8;
            int b = (c + 516 * d + 128) >> 8;
            out[i] = 0xFF000000u | (clamp8(r) << 16) | (clamp8(g) << 8) | clamp8(b);
        }
    }
}

// ---- H.264 ----

#include "media/h264bsd/h264bsd_decoder.h"

typedef struct {
    mp_obj_base_t base;
    storage_t *dec;
    uint8_t *pic;                // the last picture ready (YUV 4:2:0, inside the decoder)
    int width, height;
    int pictures;
    int last;                    // what the decoder said last (H264BSD_...), for diagnostics
} h264_obj_t;

static const mp_obj_type_t h264_type;

static mp_obj_t h264_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw, const mp_obj_t *args) {
    need_arena();
    h264_obj_t *self = mp_obj_malloc(h264_obj_t, type);
    self->dec = h264bsdAlloc();
    if (!self->dec || h264bsdInit(self->dec, 0) != 0) {           // 0: HANTRO_OK
        mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("media: no memory for the H.264 decoder"));
    }
    self->pic = NULL;
    self->width = self->height = self->pictures = 0;
    return MP_OBJ_FROM_PTR(self);
}

// decode(annexb_bytes) -> how many pictures became ready. The input is
// Annex B: NAL units, each after 00 00 00 01 (the MP4 reader converts).
static mp_obj_t h264_decode(mp_obj_t self_in, mp_obj_t data) {
    h264_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_buffer_info_t b;
    mp_get_buffer_raise(data, &b, MP_BUFFER_READ);
    uint8_t *p = b.buf;
    uint32_t left = b.len;
    int ready = 0, again = 0;
    while (left > 0 && self->dec) {
        uint32_t used = 0;
        uint32_t r = h264bsdDecode(self->dec, p, left, 0, &used);
        self->last = r;
        if (r == H264BSD_PIC_RDY) {
            uint32_t id, idr, errs;
            uint8_t *pic = h264bsdNextOutputPicture(self->dec, &id, &idr, &errs);
            if (pic) {
                self->pic = pic;
                self->width = h264bsdPicWidth(self->dec) * 16;
                self->height = h264bsdPicHeight(self->dec) * 16;
                self->pictures++;
                ready++;
            }
        } else if (r == H264BSD_ERROR || r == H264BSD_PARAM_SET_ERROR || r == H264BSD_MEMALLOC_ERROR) {
            if (r == H264BSD_MEMALLOC_ERROR) {
                mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("media: H.264 out of memory"));
            }
            if (used == 0) {
                break;
            }
        }
        if (used > left) {
            break;
        }
        if (used == 0) {
            // "headers ready" or a picture finished early: the decoder wants the
            // same data again (it remembers where it was); anything else is the end
            if ((r != H264BSD_HDRS_RDY && r != H264BSD_PIC_RDY) || ++again > 4) {
                break;
            }
            continue;
        }
        again = 0;
        p += used;
        left -= used;
    }
    return MP_OBJ_NEW_SMALL_INT(ready);
}
static MP_DEFINE_CONST_FUN_OBJ_2(h264_decode_obj, h264_decode);

// size() -> (width, height) of the pictures (multiples of 16; crop with crop())
static mp_obj_t h264_status(mp_obj_t self_in) {
    h264_obj_t *self = MP_OBJ_TO_PTR(self_in);
    return MP_OBJ_NEW_SMALL_INT(self->last);
}
static MP_DEFINE_CONST_FUN_OBJ_1(h264_status_obj, h264_status);

static mp_obj_t h264_size(mp_obj_t self_in) {
    h264_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_obj_t t[2] = { MP_OBJ_NEW_SMALL_INT(self->width), MP_OBJ_NEW_SMALL_INT(self->height) };
    return mp_obj_new_tuple(2, t);
}
static MP_DEFINE_CONST_FUN_OBJ_1(h264_size_obj, h264_size);

// crop() -> (x, y, w, h): the part of the picture that is really the video
static mp_obj_t h264_crop(mp_obj_t self_in) {
    h264_obj_t *self = MP_OBJ_TO_PTR(self_in);
    u32 flag = 0, left = 0, w = self->width, top = 0, h = self->height;
    if (self->dec && self->width) {
        h264bsdCroppingParams(self->dec, &flag, &left, &w, &top, &h);
    }
    if (!flag) {
        left = top = 0;
        w = self->width;
        h = self->height;
    }
    mp_obj_t t[4] = { MP_OBJ_NEW_SMALL_INT(left), MP_OBJ_NEW_SMALL_INT(top), MP_OBJ_NEW_SMALL_INT(w),
                      MP_OBJ_NEW_SMALL_INT(h) };
    return mp_obj_new_tuple(4, t);
}
static MP_DEFINE_CONST_FUN_OBJ_1(h264_crop_obj, h264_crop);

// draw(buffer, stride, dst_height, x, y, w, h): the last picture, scaled
// into that rectangle of a 32-bit pixel buffer (a pygame Surface's)
static mp_obj_t h264_draw(size_t n_args, const mp_obj_t *args) {
    h264_obj_t *self = MP_OBJ_TO_PTR(args[0]);
    if (!self->pic) {
        return mp_const_false;
    }
    mp_buffer_info_t b;
    mp_get_buffer_raise(args[1], &b, MP_BUFFER_WRITE);
    int stride = mp_obj_get_int(args[2]), bh = mp_obj_get_int(args[3]);
    int x = mp_obj_get_int(args[4]), y = mp_obj_get_int(args[5]);
    int w = mp_obj_get_int(args[6]), h = mp_obj_get_int(args[7]);
    if (x < 0 || y < 0 || w <= 0 || h <= 0 || x + w > stride || y + h > bh || (size_t)stride * bh * 4 > b.len) {
        mp_raise_ValueError(MP_ERROR_TEXT("media: rectangle outside the buffer"));
    }
    u32 flag = 0, cl = 0, cw = self->width, ct = 0, ch = self->height;
    h264bsdCroppingParams(self->dec, &flag, &cl, &cw, &ct, &ch);
    if (!flag) {
        cl = ct = 0;
        cw = self->width;
        ch = self->height;
    }
    int W = self->width, H = self->height;
    const uint8_t *Y = self->pic, *U = Y + W * H, *V = U + (W / 2) * (H / 2);
    yuv420_to_bgra(Y + ct * W + cl, U + (ct / 2) * (W / 2) + cl / 2, V + (ct / 2) * (W / 2) + cl / 2,
                   cw, ch, W, W / 2, (uint32_t *)b.buf, stride, x, y, w, h);
    return mp_const_true;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(h264_draw_obj, 8, 8, h264_draw);

static mp_obj_t h264_close(mp_obj_t self_in) {
    h264_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->dec) {
        h264bsdShutdown(self->dec);
        h264bsdFree(self->dec);
        self->dec = NULL;
        self->pic = NULL;
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(h264_close_obj, h264_close);

static const mp_rom_map_elem_t h264_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_decode), MP_ROM_PTR(&h264_decode_obj) },
    { MP_ROM_QSTR(MP_QSTR_size), MP_ROM_PTR(&h264_size_obj) },
    { MP_ROM_QSTR(MP_QSTR_status), MP_ROM_PTR(&h264_status_obj) },
    { MP_ROM_QSTR(MP_QSTR_crop), MP_ROM_PTR(&h264_crop_obj) },
    { MP_ROM_QSTR(MP_QSTR_draw), MP_ROM_PTR(&h264_draw_obj) },
    { MP_ROM_QSTR(MP_QSTR_close), MP_ROM_PTR(&h264_close_obj) },
};
static MP_DEFINE_CONST_DICT(h264_locals, h264_locals_table);
static MP_DEFINE_CONST_OBJ_TYPE(h264_type, MP_QSTR_H264, MP_TYPE_FLAG_NONE, make_new, h264_make_new,
                                locals_dict, &h264_locals);

// ---- AAC ----

#include "media/aac/aacdec.h"

typedef struct {
    mp_obj_base_t base;
    HAACDecoder dec;
    int rate, channels;
    int16_t *pcm;                // 2048 samples x 2 channels (HE-AAC doubles the samples)
} aac_obj_t;

static const int aac_rates[] = { 96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350 };

// AAC(config): config = the AudioSpecificConfig bytes of the MP4 (esds)
static mp_obj_t aac_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw, const mp_obj_t *args) {
    mp_arg_check_num(n_args, n_kw, 1, 1, false);
    need_arena();
    mp_buffer_info_t b;
    mp_get_buffer_raise(args[0], &b, MP_BUFFER_READ);
    const uint8_t *c = b.buf;
    if (b.len < 2) {
        mp_raise_ValueError(MP_ERROR_TEXT("media: AAC config too short"));
    }
    int profile = c[0] >> 3, index = ((c[0] & 7) << 1) | (c[1] >> 7), chans = (c[1] >> 3) & 15;
    aac_obj_t *self = mp_obj_malloc(aac_obj_t, type);
    self->dec = AACInitDecoder();
    self->pcm = malloc(2048 * 2 * sizeof(int16_t));
    if (!self->dec || !self->pcm) {
        mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("media: no memory for the AAC decoder"));
    }
    self->rate = index < 13 ? aac_rates[index] : 44100;
    self->channels = chans ? chans : 2;
    AACFrameInfo info;
    memset(&info, 0, sizeof(info));
    info.nChans = self->channels;
    info.sampRateCore = self->rate;
    info.profile = profile == 2 ? AAC_PROFILE_LC : AAC_PROFILE_LC;
    AACSetRawBlockParams(self->dec, 0, &info);
    return MP_OBJ_FROM_PTR(self);
}

// decode(frame) -> bytes of 16-bit PCM (interleaved), for one raw AAC frame
static mp_obj_t aac_decode(mp_obj_t self_in, mp_obj_t data) {
    aac_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_buffer_info_t b;
    mp_get_buffer_raise(data, &b, MP_BUFFER_READ);
    if (!self->dec) {
        return mp_const_empty_bytes;
    }
    unsigned char *p = b.buf;
    int left = b.len;
    int err = AACDecode(self->dec, &p, &left, self->pcm);
    if (err) {
        return mp_const_empty_bytes;                     // a damaged frame: silence
    }
    AACFrameInfo info;
    AACGetLastFrameInfo(self->dec, &info);
    self->rate = info.sampRateOut ? info.sampRateOut : self->rate;
    self->channels = info.nChans ? info.nChans : self->channels;
    return mp_obj_new_bytes((const byte *)self->pcm, info.outputSamps * sizeof(int16_t));
}
static MP_DEFINE_CONST_FUN_OBJ_2(aac_decode_obj, aac_decode);

// format() -> (sample rate, channels) of the sound decoded so far
static mp_obj_t aac_format(mp_obj_t self_in) {
    aac_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_obj_t t[2] = { MP_OBJ_NEW_SMALL_INT(self->rate), MP_OBJ_NEW_SMALL_INT(self->channels) };
    return mp_obj_new_tuple(2, t);
}
static MP_DEFINE_CONST_FUN_OBJ_1(aac_format_obj, aac_format);

static mp_obj_t aac_close(mp_obj_t self_in) {
    aac_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->dec) {
        AACFreeDecoder(self->dec);
        free(self->pcm);
        self->dec = NULL;
        self->pcm = NULL;
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(aac_close_obj, aac_close);

static const mp_rom_map_elem_t aac_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_decode), MP_ROM_PTR(&aac_decode_obj) },
    { MP_ROM_QSTR(MP_QSTR_format), MP_ROM_PTR(&aac_format_obj) },
    { MP_ROM_QSTR(MP_QSTR_close), MP_ROM_PTR(&aac_close_obj) },
};
static MP_DEFINE_CONST_DICT(aac_locals, aac_locals_table);
static MP_DEFINE_CONST_OBJ_TYPE(aac_type, MP_QSTR_AAC, MP_TYPE_FLAG_NONE, make_new, aac_make_new,
                                locals_dict, &aac_locals);

// ---- MP3 ----

#define MINIMP3_IMPLEMENTATION
#define MINIMP3_NO_SIMD
#include "media/mp3/minimp3.h"

typedef struct {
    mp_obj_base_t base;
    mp3dec_t *dec;
    int16_t *pcm;
    int rate, channels;
} mp3_obj_t;

static mp_obj_t mp3_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw, const mp_obj_t *args) {
    need_arena();
    mp3_obj_t *self = mp_obj_malloc(mp3_obj_t, type);
    self->dec = malloc(sizeof(mp3dec_t));
    self->pcm = malloc(MINIMP3_MAX_SAMPLES_PER_FRAME * sizeof(int16_t));
    if (!self->dec || !self->pcm) {
        mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("media: no memory for the MP3 decoder"));
    }
    mp3dec_init(self->dec);
    self->rate = 44100;
    self->channels = 2;
    return MP_OBJ_FROM_PTR(self);
}

// decode(data) -> (pcm bytes, bytes used): the first frame found in data
static mp_obj_t mp3_decode(mp_obj_t self_in, mp_obj_t data) {
    mp3_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_buffer_info_t b;
    mp_get_buffer_raise(data, &b, MP_BUFFER_READ);
    mp3dec_frame_info_t info;
    int samples = mp3dec_decode_frame(self->dec, b.buf, b.len, self->pcm, &info);
    if (info.hz) {
        self->rate = info.hz;
        self->channels = info.channels;
    }
    mp_obj_t t[2] = { mp_obj_new_bytes((const byte *)self->pcm, samples * info.channels * sizeof(int16_t)),
                      MP_OBJ_NEW_SMALL_INT(info.frame_bytes) };
    return mp_obj_new_tuple(2, t);
}
static MP_DEFINE_CONST_FUN_OBJ_2(mp3_decode_obj, mp3_decode);

static mp_obj_t mp3_format(mp_obj_t self_in) {
    mp3_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_obj_t t[2] = { MP_OBJ_NEW_SMALL_INT(self->rate), MP_OBJ_NEW_SMALL_INT(self->channels) };
    return mp_obj_new_tuple(2, t);
}
static MP_DEFINE_CONST_FUN_OBJ_1(mp3_format_obj, mp3_format);

static mp_obj_t mp3_close(mp_obj_t self_in) {
    mp3_obj_t *self = MP_OBJ_TO_PTR(self_in);
    free(self->dec);
    free(self->pcm);
    self->dec = NULL;
    self->pcm = NULL;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(mp3_close_obj, mp3_close);

static const mp_rom_map_elem_t mp3_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_decode), MP_ROM_PTR(&mp3_decode_obj) },
    { MP_ROM_QSTR(MP_QSTR_format), MP_ROM_PTR(&mp3_format_obj) },
    { MP_ROM_QSTR(MP_QSTR_close), MP_ROM_PTR(&mp3_close_obj) },
};
static MP_DEFINE_CONST_DICT(mp3_locals, mp3_locals_table);
static MP_DEFINE_CONST_OBJ_TYPE(mp3_type, MP_QSTR_MP3, MP_TYPE_FLAG_NONE, make_new, mp3_make_new,
                                locals_dict, &mp3_locals);

// ---- the module ----

// ---- WebP pictures (libwebp's decoder: lossy, lossless and with transparency) ----

#include "media/webp/src/webp/decode.h"

// webp(data) -> (width, height, pixels): 4 bytes a pixel, B G R A (the screen's order)
static mp_obj_t media_webp(mp_obj_t data) {
    need_arena();
    mp_buffer_info_t in;
    mp_get_buffer_raise(data, &in, MP_BUFFER_READ);
    int w = 0, h = 0;
    if (!WebPGetInfo(in.buf, in.len, &w, &h) || w <= 0 || h <= 0 || (size_t)w * (size_t)h > (16u << 20)) {
        mp_raise_ValueError(MP_ERROR_TEXT("not a WebP picture (or too big)"));
    }
    uint8_t *px = WebPDecodeBGRA(in.buf, in.len, &w, &h);
    if (!px) {
        mp_raise_ValueError(MP_ERROR_TEXT("damaged WebP picture"));
    }
    mp_obj_t pixels = mp_obj_new_bytes(px, (size_t)w * (size_t)h * 4);
    WebPFree(px);
    mp_obj_t items[3] = { mp_obj_new_int(w), mp_obj_new_int(h), pixels };
    return mp_obj_new_tuple(3, items);
}
static MP_DEFINE_CONST_FUN_OBJ_1(media_webp_obj, media_webp);

static const mp_rom_map_elem_t media_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__media) },
    { MP_ROM_QSTR(MP_QSTR_arena), MP_ROM_PTR(&media_arena_obj) },
    { MP_ROM_QSTR(MP_QSTR_arena_free), MP_ROM_PTR(&media_arena_free_obj) },
    { MP_ROM_QSTR(MP_QSTR_H264), MP_ROM_PTR(&h264_type) },
    { MP_ROM_QSTR(MP_QSTR_AAC), MP_ROM_PTR(&aac_type) },
    { MP_ROM_QSTR(MP_QSTR_MP3), MP_ROM_PTR(&mp3_type) },
    { MP_ROM_QSTR(MP_QSTR_webp), MP_ROM_PTR(&media_webp_obj) },
};
static MP_DEFINE_CONST_DICT(media_globals, media_globals_table);

const mp_obj_module_t mp_module_media = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&media_globals,
};
MP_REGISTER_MODULE(MP_QSTR__media, mp_module_media);
