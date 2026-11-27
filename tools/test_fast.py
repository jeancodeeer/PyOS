"""mpy/modfast.c (the C versions ARM64 uses for the @micropython.viper functions)
gives the same results as the viper originals. Runs on the PC build, where both exist.

    python tools/test_fast.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402

check = T.check

PROGRAM = r'''
import _fast, random, array, uctypes
from pygame import font as F
from kernel import sound as S
from crypto import chacha as C
import sys
sys.path.append("/lib")
random.seed(7)
def rb(n):
    return bytearray(random.getrandbits(8) for _ in range(n))
ok = {}
# font
src = rb(64 * 64); a = bytearray(100 * 80 * 4); b = bytearray(a)
for t in range(20):
    args = (100, 80, random.randint(-10, 90), random.randint(-10, 70), src, 64, random.randint(0, 20),
            random.randint(0, 20), random.randint(1, 40), random.randint(1, 40), 10, 200, 30)
    F._put(a, *args); _fast.font_put(b, *args)
ok["font_put"] = a == b
packed = bytearray(); raw = bytearray()
for t in range(300):
    if random.random() < 0.3:
        k = random.randint(1, 200); packed += bytes((0, k)); raw += bytes(k)
    else:
        v = random.randint(1, 255); packed.append(v); raw.append(v)
d1 = bytearray(len(raw)); d2 = bytearray(len(raw))
F._unrle(packed, 0, len(packed), d1); _fast.font_unrle(packed, 0, len(packed), d2)
ok["font_unrle"] = d1 == d2 == raw
# sound
for ch in (1, 2):
    for bits in (8, 16):
        data = rb(400); n = len(data) // (ch * bits // 8)
        o1 = bytearray(n * 4); o2 = bytearray(n * 4)
        S._widen(data, n, o1, ch, bits); _fast.sound_widen(data, n, o2, ch, bits)
        ok["sound_widen_%d_%d" % (ch, bits)] = o1 == o2
data = rb(4000); o1 = bytearray(1500 * 4); o2 = bytearray(1500 * 4)
S._stretch(data, 1000, o1, 1500, 44100, 66150); _fast.sound_stretch(data, 1000, o2, 1500, 44100, 66150)
ok["sound_stretch"] = o1 == o2
# chacha
st = array.array("I", [random.getrandbits(32) for _ in range(16)])
x1 = array.array("I", [0] * 16); x2 = array.array("I", [0] * 16)
C._rounds(x1, st, C._QR); _fast.chacha_rounds(x2, st, C._QR)
ok["chacha_rounds"] = x1 == x2
data = rb(200); ks = rb(64); o1 = bytearray(200); o2 = bytearray(200)
C._xor(o1, data, ks, 64, 64); _fast.chacha_xor(o2, data, ks, 64, 64)
ok["chacha_xor"] = o1 == o2
# jpeg
from imaging import jpeg as J
for t in range(10):
    blk1 = array.array("i", [random.randint(-600, 600) if random.random() < 0.3 else 0 for _ in range(64)])
    blk2 = array.array("i", blk1)
    p1 = bytearray(16 * 16); p2 = bytearray(16 * 16)
    J._idct(blk1, p1, 16, 17); _fast.jpeg_idct(blk2, p2, 16, 17)
    ok.setdefault("jpeg_idct", True)
    ok["jpeg_idct"] = ok["jpeg_idct"] and p1 == p2 and blk1 == blk2
y = rb(40 * 30); cb = rb(20 * 15); cr = rb(20 * 15)
o1 = bytearray(40 * 30 * 4); o2 = bytearray(40 * 30 * 4)
J._ycc(o1, y, cb, cr, 40, 30, 40, 20, 1, 1); _fast.jpeg_ycc(o2, y, cb, cr, 40, 30, 40, 20, 1, 1)
ok["jpeg_ycc"] = o1 == o2
o1 = bytearray(40 * 30 * 4); o2 = bytearray(40 * 30 * 4)
J._gray(o1, y, 40, 30, 40); _fast.jpeg_gray(o2, y, 40, 30, 40)
ok["jpeg_gray"] = o1 == o2
# OpenGL
from OpenGL import raster as R
W, H = 64, 48
for flags in (0, 1 | 2, 1 | 2 | 4, 1 | 2 | 4 | 8, 32 | 1 | 16):
    vl = []
    for v in range(9):
        vl.extend([random.randint(-100, W * 16 + 100), random.randint(-100, H * 16 + 100), random.randint(0, 1 << 20),
                      random.randint(0, 255 * 256), random.randint(0, 255 * 256), random.randint(0, 255 * 256),
                      random.randint(0, 1 << 20), random.randint(0, 1 << 20), random.randint(0, 255), random.randint(30000, 70000)])
    verts = array.array("i", vl)
    tris = array.array("i", [0, 1, 2, 3, 4, 5, 6, 7, 8, 2, 4, 6])
    state = array.array("i", [flags, random.randint(0, 2), random.randint(0, 1), 0, W - 1, 0, H - 1, 0])
    tex = rb(16 * 16 * 4)
    c1 = rb(W * H * 4); c2 = bytearray(c1); z1 = rb(W * H * 4); z2 = bytearray(z1)
    R.triangles(c1, z1, W, verts, tris, 4, tex, 16, 16, state)
    _fast.triangles(c2, z2, W, verts, tris, 4, tex, 16, 16, state)
    ok["triangles_%d" % flags] = c1 == c2 and z1 == z2
c1 = rb(W * H * 4); c2 = bytearray(c1); z1 = rb(W * H * 4); z2 = bytearray(z1)
R.line(c1, z1, W, H, 3 << 16, 5 << 16, 100 << 16, 40000, 25000, 60, 1000, 0x123456, 3)
_fast.line(c2, z2, W, H, 3 << 16, 5 << 16, 100 << 16, 40000, 25000, 60, 1000, 0x123456, 3)
ok["line"] = c1 == c2 and z1 == z2
b1 = bytearray(400); b2 = bytearray(400)
R.fill32(b1, 100, 0xFF102030); _fast.fill32(b2, 100, 0xFF102030)
ok["fill32"] = b1 == b2
s3 = rb(300); o1 = bytearray(400); o2 = bytearray(400)
R.rgb_to_rgba(s3, o1, 100); _fast.rgb_to_rgba(s3, o2, 100)
ok["rgb_to_rgba"] = o1 == o2
for k in sorted(ok):
    print("FAST", k, ok[k])
print("FAST done")
'''


def main():
    import os
    import mkfs
    extra = ROOT / "build" / "extra-fast"
    (extra / "lib").mkdir(parents=True, exist_ok=True)
    (extra / "lib" / "fasttest.py").write_text(PROGRAM)       # in the boot image: no typing it in
    os.environ["PYOS_EXTRA"] = str(extra)
    mkfs.pack(ROOT / "pyfs", ROOT / "build" / "pyfs.img")
    m = T.Machine(None)
    try:
        m.until(T.PROMPT, 120)
        out = m.cmd("import fasttest", 600)
        names = [line.split()[1] for line in out.splitlines() if line.startswith("FAST ") and line.split()[1] != "done"]
        check("all the C versions ran", "FAST done" in out, out[-1500:])
        for name in names:
            check("_fast.%s == viper" % name, ("FAST %s True" % name) in out, "")
    finally:
        m.close()
        del os.environ["PYOS_EXTRA"]
        mkfs.pack(ROOT / "pyfs", ROOT / "build" / "pyfs.img")
    print("%d/%d passed" % (sum(T.CHECKS), len(T.CHECKS)))
    return all(T.CHECKS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
