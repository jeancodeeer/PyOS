//! _aes: AES-GCM, the cipher every TLS 1.3 server must accept (and most
//! TLS 1.2 servers prefer). In Rust because it runs over every byte of
//! every web page: in Python it would be far too slow.
//!
//!   _aes.gcm_seal(key, nonce, plaintext, aad) -> ciphertext + 16-byte tag
//!   _aes.gcm_open(key, nonce, sealed, aad)    -> plaintext, or None if the tag is wrong
//!   _aes.encrypt_block(key, block16)          -> block16 (plain AES, for tests)
//!
//! key: 16 or 32 bytes (AES-128 / AES-256). nonce: 12 bytes.
//! AES follows FIPS-197 (with the S-box and T-tables); GCM follows NIST
//! SP 800-38D, with GHASH done 4 bits at a time (Shoup's tables).

use crate::py::{self, args, bytes, fun, Fun, FunFixed, FunVar, Fn2, Obj};

const SBOX: [u8; 256] = [
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
];

const fn xtime(x: u8) -> u8 {
    (x << 1) ^ if x & 0x80 != 0 { 0x1b } else { 0 }
}

/// T-tables: one lookup does SubBytes, ShiftRows' byte and MixColumns' column.
const TE: [[u32; 256]; 4] = {
    let mut te = [[0u32; 256]; 4];
    let mut i = 0;
    while i < 256 {
        let s = SBOX[i];
        let s2 = xtime(s);
        let s3 = s2 ^ s;
        let t = (s2 as u32) << 24 | (s as u32) << 16 | (s as u32) << 8 | s3 as u32;
        te[0][i] = t;
        te[1][i] = t.rotate_right(8);
        te[2][i] = t.rotate_right(16);
        te[3][i] = t.rotate_right(24);
        i += 1;
    }
    te
};

fn get32(p: &[u8]) -> u32 {
    u32::from_be_bytes([p[0], p[1], p[2], p[3]])
}

fn sub_word(t: u32) -> u32 {
    let b = t.to_be_bytes();
    u32::from_be_bytes([SBOX[b[0] as usize], SBOX[b[1] as usize], SBOX[b[2] as usize], SBOX[b[3] as usize]])
}

struct Key {
    rk: [u32; 60],
    rounds: usize,
}

impl Key {
    fn new(key: &[u8]) -> Key {
        const RCON: [u8; 10] = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36];
        let nk = key.len() / 4;
        let rounds = nk + 6;
        let mut rk = [0u32; 60];
        for i in 0..nk {
            rk[i] = get32(&key[4 * i..]);
        }
        for i in nk..4 * (rounds + 1) {
            let mut t = rk[i - 1];
            if i % nk == 0 {
                t = sub_word(t.rotate_left(8)) ^ (RCON[i / nk - 1] as u32) << 24;
            } else if nk > 6 && i % nk == 4 {
                t = sub_word(t);
            }
            rk[i] = rk[i - nk] ^ t;
        }
        Key { rk, rounds }
    }

    fn encrypt(&self, input: &[u8; 16]) -> [u8; 16] {
        let rk = &self.rk;
        let mut s = [get32(&input[0..]) ^ rk[0], get32(&input[4..]) ^ rk[1], get32(&input[8..]) ^ rk[2],
                     get32(&input[12..]) ^ rk[3]];
        let b = |v: u32, n: u32| ((v >> n) & 0xff) as usize;
        for r in 1..self.rounds {
            let k = &rk[4 * r..];
            let mut t = [0u32; 4];
            for c in 0..4 {
                t[c] = TE[0][b(s[c], 24)] ^ TE[1][b(s[(c + 1) % 4], 16)] ^ TE[2][b(s[(c + 2) % 4], 8)]
                    ^ TE[3][b(s[(c + 3) % 4], 0)] ^ k[c];
            }
            s = t;
        }
        let k = &rk[4 * self.rounds..];            // the last round has no MixColumns
        let mut out = [0u8; 16];
        for c in 0..4 {
            let o = u32::from_be_bytes([SBOX[b(s[c], 24)], SBOX[b(s[(c + 1) % 4], 16)], SBOX[b(s[(c + 2) % 4], 8)],
                                        SBOX[b(s[(c + 3) % 4], 0)]]) ^ k[c];
            out[4 * c..4 * c + 4].copy_from_slice(&o.to_be_bytes());
        }
        out
    }
}

// ---- GHASH: multiplication in GF(2^128), 4 bits at a time ----

const LAST4: [u64; 16] = [0x0000, 0x1c20, 0x3840, 0x2460, 0x7080, 0x6ca0, 0x48c0, 0x54e0,
                          0xe100, 0xfd20, 0xd940, 0xc560, 0x9180, 0x8da0, 0xa9c0, 0xb5e0];

struct Ghash {
    hl: [u64; 16],
    hh: [u64; 16],
}

impl Ghash {
    fn new(h: &[u8; 16]) -> Ghash {
        let mut g = Ghash { hl: [0; 16], hh: [0; 16] };
        let mut vh = u64::from_be_bytes(h[0..8].try_into().unwrap());
        let mut vl = u64::from_be_bytes(h[8..16].try_into().unwrap());
        g.hl[8] = vl;
        g.hh[8] = vh;
        let mut i = 4;
        while i > 0 {
            let t = (vl & 1) * 0xe100_0000;
            vl = (vh << 63) | (vl >> 1);
            vh = (vh >> 1) ^ (t << 32);
            g.hl[i] = vl;
            g.hh[i] = vh;
            i >>= 1;
        }
        let mut i = 2;
        while i <= 8 {
            for j in 1..i {
                g.hh[i + j] = g.hh[i] ^ g.hh[j];
                g.hl[i + j] = g.hl[i] ^ g.hl[j];
            }
            i *= 2;
        }
        g
    }

    fn mult(&self, x: &mut [u8; 16]) {
        let lo = (x[15] & 0xf) as usize;
        let (mut zh, mut zl) = (self.hh[lo], self.hl[lo]);
        let step = |zh: &mut u64, zl: &mut u64, n: usize, g: &Ghash| {
            let rem = (*zl & 0xf) as usize;
            *zl = (*zh << 60) | (*zl >> 4);
            *zh = (*zh >> 4) ^ (LAST4[rem] << 48) ^ g.hh[n];
            *zl ^= g.hl[n];
        };
        for i in (0..16).rev() {
            let lo = (x[i] & 0xf) as usize;
            let hi = (x[i] >> 4) as usize;
            if i != 15 {
                step(&mut zh, &mut zl, lo, self);
            }
            step(&mut zh, &mut zl, hi, self);
        }
        x[0..8].copy_from_slice(&zh.to_be_bytes());
        x[8..16].copy_from_slice(&zl.to_be_bytes());
    }

    fn update(&self, y: &mut [u8; 16], data: &[u8]) {
        for chunk in data.chunks(16) {
            for (a, b) in y.iter_mut().zip(chunk) {
                *a ^= b;
            }
            self.mult(y);
        }
    }
}

// ---- GCM ----

fn inc32(ctr: &mut [u8; 16]) {
    for i in (12..16).rev() {
        ctr[i] = ctr[i].wrapping_add(1);
        if ctr[i] != 0 {
            break;
        }
    }
}

/// Encrypt (or decrypt: the same thing in counter mode) `input` into `out`,
/// and return the tag.
fn gcm(key: &[u8], nonce: &[u8], aad: &[u8], input: &[u8], out: &mut [u8], encrypting: bool) -> [u8; 16] {
    let k = Key::new(key);
    let g = Ghash::new(&k.encrypt(&[0; 16]));
    let mut j0 = [0u8; 16];
    j0[..12].copy_from_slice(nonce);
    j0[15] = 1;
    let mut ctr = j0;
    let mut y = [0u8; 16];
    g.update(&mut y, aad);
    for (off, chunk) in input.chunks(16).enumerate() {
        inc32(&mut ctr);
        let ks = k.encrypt(&ctr);
        let o = &mut out[off * 16..off * 16 + chunk.len()];
        for i in 0..chunk.len() {
            o[i] = chunk[i] ^ ks[i];
        }
        // the tag covers the ciphertext
        let c: &[u8] = if encrypting { o } else { chunk };
        for i in 0..c.len() {
            y[i] ^= c[i];
        }
        g.mult(&mut y);
    }
    let mut lens = [0u8; 16];
    lens[..8].copy_from_slice(&(aad.len() as u64 * 8).to_be_bytes());
    lens[8..].copy_from_slice(&(input.len() as u64 * 8).to_be_bytes());
    g.update(&mut y, &lens);
    let ks = k.encrypt(&j0);
    let mut tag = [0u8; 16];
    for i in 0..16 {
        tag[i] = y[i] ^ ks[i];
    }
    tag
}

fn key_and_nonce(key: Obj, nonce: Obj) -> (&'static [u8], &'static [u8]) {
    let (k, n) = (bytes(key), bytes(nonce));
    if (k.len() != 16 && k.len() != 32) || n.len() != 12 {
        py::value_error(b"AES-GCM: key of 16 or 32 bytes, nonce of 12\0");
    }
    (k, n)
}

unsafe extern "C" fn gcm_seal(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let (k, nonce) = key_and_nonce(a[0], a[1]);
    let (plain, aad) = (bytes(a[2]), bytes(a[3]));
    py::new_bytes_with(plain.len() + 16, |out| {
        let (body, tag) = out.split_at_mut(plain.len());
        tag.copy_from_slice(&gcm(k, nonce, aad, plain, body, true));
    })
}

unsafe extern "C" fn gcm_open(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let (k, nonce) = key_and_nonce(a[0], a[1]);
    let (sealed, aad) = (bytes(a[2]), bytes(a[3]));
    if sealed.len() < 16 {
        return py::none();
    }
    let (body, want) = sealed.split_at(sealed.len() - 16);
    py::new_bytes_or_none(body.len(), |out| {
        let tag = gcm(k, nonce, aad, body, out, false);
        let mut diff = 0u8;                        // all 16 bytes, whatever the first ones say
        for i in 0..16 {
            diff |= tag[i] ^ want[i];
        }
        diff == 0
    })
}

unsafe extern "C" fn encrypt_block(key: Obj, block: Obj) -> Obj {
    let (k, b) = (bytes(key), bytes(block));
    if (k.len() != 16 && k.len() != 32) || b.len() != 16 {
        py::value_error(b"AES: key of 16 or 32 bytes, block of 16\0");
    }
    py::new_bytes(&Key::new(k).encrypt(b.try_into().unwrap()))
}

static GCM_SEAL: FunVar = Fun::var(4, 4, gcm_seal);
static GCM_OPEN: FunVar = Fun::var(4, 4, gcm_open);
static ENCRYPT_BLOCK: FunFixed<Fn2> = Fun::f2(encrypt_block);

pub fn register() {
    py::define("_aes", &[("gcm_seal", fun(&GCM_SEAL)), ("gcm_open", fun(&GCM_OPEN)),
                         ("encrypt_block", fun(&ENCRYPT_BLOCK))]);
}
