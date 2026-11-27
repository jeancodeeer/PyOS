"""media/h264.py (the H.264 decoder in Python) against ffmpeg's decoder: Baseline
streams made by x264 with different tools (I only, P frames, several reference
frames, slices, weighted prediction, no deblocking, odd sizes with cropping).
H.264 decoding is exact, so every picture must be identical.

    python tools/test_h264.py      # needs ffmpeg with libx264
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pyos" / "lib"))
from media.h264 import H264, nal_units  # noqa: E402

SRC = "testsrc2=size=%s:rate=10:duration=%s"
KINDS = [("intra", "96x64", "0.3", "keyint=1"),
         ("p frames", "96x64", "1", "ref=1"),
         ("refs 3", "128x96", "1", "ref=3"),
         ("slices", "96x64", "0.5", "slices=3"),
         ("no deblock", "96x64", "0.5", "no-deblock=1"),
         ("crop 100x58", "100x58", "0.5", "ref=2"),
         ("weightp", "96x64", "1", "weightp=1:ref=2"),
         ("fade", "96x64", "1.5", "weightp=2:ref=3"),
         ("low qp", "64x48", "0.5", "qp=4"),
         ("high qp", "64x48", "0.5", "qp=48"),
         ("moving", "160x96", "1.5", "ref=4:me=umh:subme=7")]


def run(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def access_units(data):
    """Split an Annex B stream at its access unit delimiters."""
    au = b""
    for nal in nal_units(data):
        if nal[0] & 31 == 9 and au:
            yield au
            au = b""
        au += b"\x00\x00\x00\x01" + nal
    if au:
        yield au


def main(only=None):
    ok = 0
    kinds = [k for k in KINDS if not only or k[0] in only]
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for name, size, dur, params in kinds:
            src = d / "x.264"
            extra = []
            if "weightp" not in params and name != "fade":
                extra = ["-profile:v", "baseline"]
            run("ffmpeg", "-y", "-f", "lavfi", "-i", (SRC % (size, dur)) + ",noise=alls=20:allf=t" +
                (",fade=t=out:st=0.2:d=1.2" if name == "fade" else ""), *extra,
                "-pix_fmt", "yuv420p", "-c:v", "libx264", "-x264-params", "aud=1:" + params +
                (":cabac=0:bframes=0:8x8dct=0" if extra == [] else ""), "-f", "h264", str(src))
            ref = run("ffmpeg", "-v", "error", "-i", str(src), "-f", "rawvideo", "-pix_fmt", "yuv420p", "-")
            dec = H264()
            frames = []
            dec.on_picture = lambda p: frames.append(p)
            out = bytearray()
            errors = []
            data = src.read_bytes()
            for au in access_units(data):
                frames.clear()
                dec.decode(au)
                if dec.last:
                    errors.append(dec.error)
                cx, cy, cw, ch = dec.crop()
                W = dec.W
                for p in frames:
                    for plane, pw, x0, y0, w, h in ((p.y, W, cx, cy, cw, ch),
                                                    (p.u, W // 2, cx // 2, cy // 2, cw // 2, ch // 2),
                                                    (p.v, W // 2, cx // 2, cy // 2, cw // 2, ch // 2)):
                        for r in range(h):
                            o = (y0 + r) * pw + x0
                            out += plane[o:o + w]
            good = bytes(out) == ref and not errors
            ok += good
            diff = ""
            if not good:
                n = min(len(out), len(ref))
                first = next((i for i in range(n) if out[i] != ref[i]), n)
                fsize = cw * ch * 3 // 2 if dec.W else 1
                diff = " first difference at byte %d (frame %d), %d vs %d bytes %s" % (
                    first, first // max(fsize, 1), len(out), len(ref), errors[:1])
            print("%-12s %s%s" % (name, "ok " if good else "BAD", diff))
    print("%d/%d" % (ok, len(kinds)))
    return ok == len(kinds)


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1:]) else 1)
