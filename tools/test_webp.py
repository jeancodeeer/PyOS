"""imaging/webpdec.py (the WebP decoder in Python) gives every pixel exactly as
libwebp (through Pillow) does: lossless, lossy, transparency, palettes.

    python tools/test_webp.py      # needs Pillow with WebP
"""
import io
import math
import random
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pyos" / "lib"))
from PIL import Image, ImageDraw
from imaging import webpdec as webp

def make(w, h, seed, alpha=False, palette=False):
    random.seed(seed)
    im = Image.new("RGBA", (w, h), (30, 80, 160, 255))
    d = ImageDraw.Draw(im)
    for _ in range(25):
        x0, y0 = random.randint(0, w), random.randint(0, h)
        c = tuple(random.randint(0, 255) for _ in range(3)) + ((random.randint(0, 255),) if alpha else (255,))
        d.ellipse((x0, y0, x0 + random.randint(5, w // 2), y0 + random.randint(5, h // 2)), fill=c)
    d.text((5, 5), "SnakeyOS", fill=(255, 255, 0, 255))
    if palette:
        im = im.convert("RGB").quantize(colors=random.choice((2, 4, 13, 60))).convert("RGBA")
    return im

def check(im, **kw):
    buf = io.BytesIO(); im.save(buf, "WEBP", **kw); data = buf.getvalue()
    ref = Image.open(io.BytesIO(data)).convert("RGBA")
    t = time.time()
    w, h, px = webp.decode(data)
    dt = time.time() - t
    mine = Image.frombuffer("RGBA", (w, h), bytes(px), "raw", "BGRA", 0, 1)
    a, b = ref.tobytes(), mine.tobytes()
    diff = sum((x - y) ** 2 for x, y in zip(a, b)) / len(a)
    psnr = 99 if diff == 0 else 10 * math.log10(255 ** 2 / diff)
    maxd = max(abs(x - y) for x, y in zip(a, b))
    return (w, h) == ref.size, round(psnr, 1), maxd, round(dt, 2)

results = []
for name, im, kw in [
    ("lossless", make(97, 61, 1), dict(lossless=True)),
    ("lossless alpha", make(120, 90, 2, alpha=True), dict(lossless=True)),
    ("lossless palette", make(64, 50, 3, palette=True), dict(lossless=True)),
    ("lossless big", make(300, 200, 4), dict(lossless=True, method=6)),
    ("lossy", make(97, 61, 5).convert("RGB"), dict(quality=80)),
    ("lossy q20", make(200, 150, 6).convert("RGB"), dict(quality=20)),
    ("lossy q95", make(130, 70, 7).convert("RGB"), dict(quality=95, method=6)),
    ("lossy alpha", make(120, 90, 8, alpha=True), dict(quality=75)),
    ("lossy simple", make(80, 48, 9).convert("RGB"), dict(quality=50, method=0)),
]:
    results.append((name, check(im, **kw)))
for q in (20, 60, 95):
    results.append(("grey q%d" % q, check(make(160, 96, 11 + q).convert("L").convert("RGB"), quality=q)))
ok = 0
for name, (size_ok, psnr, maxd, dt) in results:
    good = size_ok and maxd == 0
    ok += good
    print("%s  %-18s %s" % ("PASS" if good else "FAIL", name, "identical" if good else "max difference %d" % maxd))
print("%d/%d passed" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
