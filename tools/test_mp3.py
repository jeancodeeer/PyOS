"""media/mp3.py (the MP3 decoder in Python) against ffmpeg's decoder: several
kinds of MP3 (CBR, VBR, mono, joint stereo, MPEG-2, MPEG-2.5, 320 kbit/s),
made by ffmpeg from the same sound. The two must agree to within rounding
(ffmpeg drops the encoder's delay, so the start is lined up first).

    python tools/test_mp3.py      # needs ffmpeg with libmp3lame
"""
import array
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pyos" / "lib"))
from media.mp3 import MP3  # noqa: E402

KINDS = [("cbr 128k", ["-b:a", "128k"]), ("vbr", ["-q:a", "4"]), ("mono", ["-ac", "1", "-b:a", "64k"]),
         ("joint stereo", ["-b:a", "96k", "-joint_stereo", "1"]), ("mpeg-2", ["-ar", "22050", "-b:a", "48k"]),
         ("mpeg-2.5", ["-ar", "8000", "-b:a", "16k"]), ("320k", ["-b:a", "320k"])]


def run(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    ok = 0
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        run("ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-f", "lavfi", "-i",
            "anoisesrc=d=2:c=pink:a=0.2", "-filter_complex",
            "[0][1]amix=inputs=2,asplit=2[a][b];[a][b]join=inputs=2:channel_layout=stereo,volume=0.8", str(d / "src.wav"))
        for name, opts in KINDS:
            mp3 = d / "x.mp3"
            run("ffmpeg", "-y", "-i", str(d / "src.wav"), *opts, "-c:a", "libmp3lame", str(mp3))
            run("ffmpeg", "-y", "-i", str(mp3), "-f", "s16le", str(d / "ref.raw"))
            ref = array.array("h", (d / "ref.raw").read_bytes())
            data = mp3.read_bytes()
            dec = MP3()
            out = bytearray()
            pos = 0
            while pos < len(data):
                pcm, used = dec.decode(data[pos:pos + 4000])
                if not used:
                    break
                pos += used
                out += pcm
            mine = array.array("h", bytes(out))
            ch = dec.channels
            # line up: ffmpeg skips the encoder delay at the start
            best = None
            for skip in range(0, 3000 * ch, ch):
                n = min(len(ref), len(mine) - skip, 20000)
                if n <= 0:
                    break
                e = sum(abs(mine[skip + i] - ref[i]) for i in range(0, n, 7))
                if best is None or e < best[0]:
                    best = (e, skip)
            skip = best[1]
            n = min(len(ref), len(mine) - skip)
            err = sum((mine[skip + i] - ref[i]) ** 2 for i in range(n)) / n
            sig = sum(r * r for r in ref[:n]) / n
            snr = 99.0 if err == 0 else 10 * math.log10(sig / err)
            good = snr > 60
            ok += good
            print("%s  %-13s SNR %.1f dB against ffmpeg" % ("PASS" if good else "FAIL", name, snr))
    print("%d/%d passed" % (ok, len(KINDS)))
    return ok == len(KINDS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
