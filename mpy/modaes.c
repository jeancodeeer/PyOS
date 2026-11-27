// _aes: AES-GCM, the cipher every TLS 1.3 server must accept (and most
// TLS 1.2 servers prefer). In C because it runs over every byte of every
// web page: in Python it would be far too slow.
//
//   _aes.gcm_seal(key, nonce, plaintext, aad) -> ciphertext + 16-byte tag
//   _aes.gcm_open(key, nonce, sealed, aad)    -> plaintext, or None if the tag is wrong
//
// key: 16 or 32 bytes (AES-128 / AES-256). nonce: 12 bytes.
// AES follows FIPS-197 (byte-oriented, with the S-box); GCM follows
// NIST SP 800-38D, with GHASH done 4 bits at a time (Shoup's tables).
#include <stdint.h>
#include <string.h>
#include "py/runtime.h"
#include "py/obj.h"
#include "py/objstr.h"

// ---- AES ----

static const uint8_t SBOX[256] = {
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
};

// T-tables: one table lookup does SubBytes, ShiftRows' byte and MixColumns' column
static uint32_t TE[4][256];
static int tables_ready;

static inline uint8_t xtime(uint8_t x) {
    return (uint8_t)((x << 1) ^ ((x & 0x80) ? 0x1b : 0));
}

static void make_tables(void) {
    for (int i = 0; i < 256; i++) {
        uint8_t s = SBOX[i], s2 = xtime(s), s3 = s2 ^ s;
        uint32_t t = ((uint32_t)s2 << 24) | ((uint32_t)s << 16) | ((uint32_t)s << 8) | s3;
        TE[0][i] = t;
        TE[1][i] = (t >> 8) | (t << 24);
        TE[2][i] = (t >> 16) | (t << 16);
        TE[3][i] = (t >> 24) | (t << 8);
    }
    tables_ready = 1;
}

typedef struct {
    uint32_t rk[60];       // round keys, as big-endian words
    int rounds;            // 10 (AES-128) or 14 (AES-256)
} aes_key_t;

static inline uint32_t get32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

static inline void put32(uint8_t *p, uint32_t v) {
    p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = v;
}

static void aes_setkey(aes_key_t *k, const uint8_t *key, int len) {
    static const uint8_t RCON[10] = { 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36 };
    int nk = len / 4;
    k->rounds = nk + 6;
    int total = 4 * (k->rounds + 1);
    for (int i = 0; i < nk; i++) {
        k->rk[i] = get32(key + 4 * i);
    }
    for (int i = nk; i < total; i++) {
        uint32_t t = k->rk[i - 1];
        if (i % nk == 0) {
            t = ((uint32_t)SBOX[(t >> 16) & 0xff] << 24) | ((uint32_t)SBOX[(t >> 8) & 0xff] << 16) |
                ((uint32_t)SBOX[t & 0xff] << 8) | SBOX[t >> 24];
            t ^= (uint32_t)RCON[i / nk - 1] << 24;
        } else if (nk > 6 && i % nk == 4) {
            t = ((uint32_t)SBOX[t >> 24] << 24) | ((uint32_t)SBOX[(t >> 16) & 0xff] << 16) |
                ((uint32_t)SBOX[(t >> 8) & 0xff] << 8) | SBOX[t & 0xff];
        }
        k->rk[i] = k->rk[i - nk] ^ t;
    }
}

static void aes_encrypt(const aes_key_t *k, const uint8_t in[16], uint8_t out[16]) {
    const uint32_t *rk = k->rk;
    uint32_t s0 = get32(in) ^ rk[0], s1 = get32(in + 4) ^ rk[1];
    uint32_t s2 = get32(in + 8) ^ rk[2], s3 = get32(in + 12) ^ rk[3];
    for (int r = 1; r < k->rounds; r++) {
        rk += 4;
        uint32_t t0 = TE[0][s0 >> 24] ^ TE[1][(s1 >> 16) & 0xff] ^ TE[2][(s2 >> 8) & 0xff] ^ TE[3][s3 & 0xff] ^ rk[0];
        uint32_t t1 = TE[0][s1 >> 24] ^ TE[1][(s2 >> 16) & 0xff] ^ TE[2][(s3 >> 8) & 0xff] ^ TE[3][s0 & 0xff] ^ rk[1];
        uint32_t t2 = TE[0][s2 >> 24] ^ TE[1][(s3 >> 16) & 0xff] ^ TE[2][(s0 >> 8) & 0xff] ^ TE[3][s1 & 0xff] ^ rk[2];
        uint32_t t3 = TE[0][s3 >> 24] ^ TE[1][(s0 >> 16) & 0xff] ^ TE[2][(s1 >> 8) & 0xff] ^ TE[3][s2 & 0xff] ^ rk[3];
        s0 = t0; s1 = t1; s2 = t2; s3 = t3;
    }
    rk += 4;                                   // the last round has no MixColumns
    uint32_t o0 = ((uint32_t)SBOX[s0 >> 24] << 24) | ((uint32_t)SBOX[(s1 >> 16) & 0xff] << 16) |
                  ((uint32_t)SBOX[(s2 >> 8) & 0xff] << 8) | SBOX[s3 & 0xff];
    uint32_t o1 = ((uint32_t)SBOX[s1 >> 24] << 24) | ((uint32_t)SBOX[(s2 >> 16) & 0xff] << 16) |
                  ((uint32_t)SBOX[(s3 >> 8) & 0xff] << 8) | SBOX[s0 & 0xff];
    uint32_t o2 = ((uint32_t)SBOX[s2 >> 24] << 24) | ((uint32_t)SBOX[(s3 >> 16) & 0xff] << 16) |
                  ((uint32_t)SBOX[(s0 >> 8) & 0xff] << 8) | SBOX[s1 & 0xff];
    uint32_t o3 = ((uint32_t)SBOX[s3 >> 24] << 24) | ((uint32_t)SBOX[(s0 >> 16) & 0xff] << 16) |
                  ((uint32_t)SBOX[(s1 >> 8) & 0xff] << 8) | SBOX[s2 & 0xff];
    put32(out, o0 ^ rk[0]);
    put32(out + 4, o1 ^ rk[1]);
    put32(out + 8, o2 ^ rk[2]);
    put32(out + 12, o3 ^ rk[3]);
}

// ---- GHASH: multiplication in GF(2^128), 4 bits at a time ----

typedef struct {
    uint64_t hl[16], hh[16];   // multiples of H for each 4-bit value
} ghash_t;

static const uint64_t LAST4[16] = {
    0x0000, 0x1c20, 0x3840, 0x2460, 0x7080, 0x6ca0, 0x48c0, 0x54e0,
    0xe100, 0xfd20, 0xd940, 0xc560, 0x9180, 0x8da0, 0xa9c0, 0xb5e0,
};

static void ghash_init(ghash_t *g, const uint8_t h[16]) {
    uint64_t vh = ((uint64_t)get32(h) << 32) | get32(h + 4);
    uint64_t vl = ((uint64_t)get32(h + 8) << 32) | get32(h + 12);
    g->hl[8] = vl;
    g->hh[8] = vh;
    g->hh[0] = g->hl[0] = 0;
    for (int i = 4; i > 0; i >>= 1) {
        uint32_t t = (vl & 1) * 0xe1000000u;
        vl = (vh << 63) | (vl >> 1);
        vh = (vh >> 1) ^ ((uint64_t)t << 32);
        g->hl[i] = vl;
        g->hh[i] = vh;
    }
    for (int i = 2; i <= 8; i *= 2) {
        for (int j = 1; j < i; j++) {
            g->hh[i + j] = g->hh[i] ^ g->hh[j];
            g->hl[i + j] = g->hl[i] ^ g->hl[j];
        }
    }
}

static void ghash_mult(const ghash_t *g, uint8_t x[16]) {
    uint8_t lo = x[15] & 0xf;
    uint64_t zh = g->hh[lo], zl = g->hl[lo];
    for (int i = 15; i >= 0; i--) {
        lo = x[i] & 0xf;
        uint8_t hi = (x[i] >> 4) & 0xf;
        if (i != 15) {
            uint8_t rem = (uint8_t)(zl & 0xf);
            zl = (zh << 60) | (zl >> 4);
            zh = zh >> 4;
            zh ^= LAST4[rem] << 48;
            zh ^= g->hh[lo];
            zl ^= g->hl[lo];
        }
        uint8_t rem = (uint8_t)(zl & 0xf);
        zl = (zh << 60) | (zl >> 4);
        zh = zh >> 4;
        zh ^= LAST4[rem] << 48;
        zh ^= g->hh[hi];
        zl ^= g->hl[hi];
    }
    put32(x, zh >> 32);
    put32(x + 4, (uint32_t)zh);
    put32(x + 8, zl >> 32);
    put32(x + 12, (uint32_t)zl);
}

static void ghash_update(const ghash_t *g, uint8_t y[16], const uint8_t *data, size_t n) {
    while (n) {
        size_t take = n < 16 ? n : 16;
        for (size_t i = 0; i < take; i++) {
            y[i] ^= data[i];
        }
        ghash_mult(g, y);
        data += take;
        n -= take;
    }
}

// ---- GCM ----

static inline void inc32(uint8_t ctr[16]) {
    for (int i = 15; i >= 12; i--) {
        if (++ctr[i]) {
            break;
        }
    }
}

// Encrypts (or decrypts: the same thing in counter mode) and computes the tag.
// Returns the tag in `tag`; `out` gets the transformed text.
static void gcm(const uint8_t *key, size_t keylen, const uint8_t nonce[12], const uint8_t *aad, size_t aadlen,
                const uint8_t *in, size_t n, uint8_t *out, int encrypting, uint8_t tag[16]) {
    if (!tables_ready) {
        make_tables();
    }
    aes_key_t k;
    aes_setkey(&k, key, (int)keylen);
    uint8_t h[16] = { 0 };
    aes_encrypt(&k, h, h);
    ghash_t g;
    ghash_init(&g, h);
    uint8_t j0[16], ctr[16], ks[16], y[16] = { 0 };
    memcpy(j0, nonce, 12);
    j0[12] = j0[13] = j0[14] = 0;
    j0[15] = 1;
    memcpy(ctr, j0, 16);
    ghash_update(&g, y, aad, aadlen);
    for (size_t off = 0; off < n; off += 16) {
        size_t take = n - off < 16 ? n - off : 16;
        inc32(ctr);
        aes_encrypt(&k, ctr, ks);
        uint8_t block[16] = { 0 };
        if (!encrypting) {                       // the tag covers the ciphertext
            memcpy(block, in + off, take);
            for (size_t i = 0; i < take; i++) {
                y[i] ^= block[i];
            }
            ghash_mult(&g, y);
        }
        for (size_t i = 0; i < take; i++) {
            out[off + i] = in[off + i] ^ ks[i];
        }
        if (encrypting) {
            for (size_t i = 0; i < take; i++) {
                y[i] ^= out[off + i];
            }
            ghash_mult(&g, y);
        }
    }
    uint8_t lens[16];
    uint64_t abits = (uint64_t)aadlen * 8, cbits = (uint64_t)n * 8;
    put32(lens, abits >> 32);
    put32(lens + 4, (uint32_t)abits);
    put32(lens + 8, cbits >> 32);
    put32(lens + 12, (uint32_t)cbits);
    ghash_update(&g, y, lens, 16);
    aes_encrypt(&k, j0, ks);
    for (int i = 0; i < 16; i++) {
        tag[i] = y[i] ^ ks[i];
    }
}

static void get_args(mp_obj_t key, mp_obj_t nonce, mp_buffer_info_t *kb, mp_buffer_info_t *nb) {
    mp_get_buffer_raise(key, kb, MP_BUFFER_READ);
    mp_get_buffer_raise(nonce, nb, MP_BUFFER_READ);
    if ((kb->len != 16 && kb->len != 32) || nb->len != 12) {
        mp_raise_ValueError(MP_ERROR_TEXT("AES-GCM: key of 16 or 32 bytes, nonce of 12"));
    }
}

// gcm_seal(key, nonce, plaintext, aad) -> ciphertext + tag
static mp_obj_t aes_gcm_seal(size_t n_args, const mp_obj_t *args) {
    mp_buffer_info_t kb, nb, pb, ab;
    get_args(args[0], args[1], &kb, &nb);
    mp_get_buffer_raise(args[2], &pb, MP_BUFFER_READ);
    mp_get_buffer_raise(args[3], &ab, MP_BUFFER_READ);
    vstr_t out;
    vstr_init_len(&out, pb.len + 16);
    uint8_t *o = (uint8_t *)out.buf;
    gcm(kb.buf, kb.len, nb.buf, ab.buf, ab.len, pb.buf, pb.len, o, 1, o + pb.len);
    return mp_obj_new_bytes_from_vstr(&out);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(aes_gcm_seal_obj, 4, 4, aes_gcm_seal);

// gcm_open(key, nonce, sealed, aad) -> plaintext, or None when the tag does not match
static mp_obj_t aes_gcm_open(size_t n_args, const mp_obj_t *args) {
    mp_buffer_info_t kb, nb, sb, ab;
    get_args(args[0], args[1], &kb, &nb);
    mp_get_buffer_raise(args[2], &sb, MP_BUFFER_READ);
    mp_get_buffer_raise(args[3], &ab, MP_BUFFER_READ);
    if (sb.len < 16) {
        return mp_const_none;
    }
    size_t n = sb.len - 16;
    vstr_t out;
    vstr_init_len(&out, n);
    uint8_t tag[16];
    gcm(kb.buf, kb.len, nb.buf, ab.buf, ab.len, sb.buf, n, (uint8_t *)out.buf, 0, tag);
    uint8_t diff = 0;                            // compare all 16 bytes, whatever the first ones say
    for (int i = 0; i < 16; i++) {
        diff |= tag[i] ^ ((const uint8_t *)sb.buf)[n + i];
    }
    if (diff) {
        vstr_clear(&out);
        return mp_const_none;
    }
    return mp_obj_new_bytes_from_vstr(&out);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(aes_gcm_open_obj, 4, 4, aes_gcm_open);

// encrypt_block(key, block16) -> block16 (plain AES, for tests)
static mp_obj_t aes_encrypt_block(mp_obj_t key, mp_obj_t block) {
    mp_buffer_info_t kb, bb;
    mp_get_buffer_raise(key, &kb, MP_BUFFER_READ);
    mp_get_buffer_raise(block, &bb, MP_BUFFER_READ);
    if ((kb.len != 16 && kb.len != 32) || bb.len != 16) {
        mp_raise_ValueError(MP_ERROR_TEXT("AES: key of 16 or 32 bytes, block of 16"));
    }
    if (!tables_ready) {
        make_tables();
    }
    aes_key_t k;
    aes_setkey(&k, kb.buf, (int)kb.len);
    uint8_t out[16];
    aes_encrypt(&k, bb.buf, out);
    return mp_obj_new_bytes(out, 16);
}
static MP_DEFINE_CONST_FUN_OBJ_2(aes_encrypt_block_obj, aes_encrypt_block);

static const mp_rom_map_elem_t aes_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__aes) },
    { MP_ROM_QSTR(MP_QSTR_gcm_seal), MP_ROM_PTR(&aes_gcm_seal_obj) },
    { MP_ROM_QSTR(MP_QSTR_gcm_open), MP_ROM_PTR(&aes_gcm_open_obj) },
    { MP_ROM_QSTR(MP_QSTR_encrypt_block), MP_ROM_PTR(&aes_encrypt_block_obj) },
};
static MP_DEFINE_CONST_DICT(aes_globals, aes_globals_table);

const mp_obj_module_t mp_module_aes = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&aes_globals,
};

MP_REGISTER_MODULE(MP_QSTR__aes, mp_module_aes);
