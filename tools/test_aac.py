"""media/aac.py (the AAC-LC decoder in Python) against ffmpeg's decoder: AAC
made by ffmpeg's encoder with its tools on and off (M/S, intensity, PNS, TNS),
mono and stereo, two rates. Each must match ffmpeg to a high SNR.

    python tools/test_aac.py      # needs ffmpeg
"""
import array
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pyos" / "lib"))
from media.aac import AAC  # noqa: E402

KINDS = [("stereo 128k", ["-b:a", "128k"]),
         ("mono", ["-ac", "1", "-b:a", "64k"]),
         ("no tools", ["-b:a", "128k", "-aac_ms", "0", "-aac_is", "0", "-aac_pns", "0", "-aac_tns", "0"]),
         ("ms", ["-b:a", "96k", "-aac_ms", "1", "-aac_is", "0", "-aac_pns", "0"]),
         ("is", ["-b:a", "48k", "-aac_is", "1"]),
         ("pns", ["-b:a", "48k", "-aac_pns", "1"]),
         ("tns", ["-b:a", "128k", "-aac_tns", "1"]),
         ("22050", ["-ar", "22050", "-b:a", "64k"]),
         ("48000 low", ["-ar", "48000", "-b:a", "32k"]),
         ("short windows", ["-b:a", "128k"]),
         ("short is+pns", ["-b:a", "40k", "-aac_is", "1", "-aac_pns", "1", "-aac_tns", "1"])]


def run(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def adts_frames(data):
    pos = 0
    config = None
    while pos + 7 <= len(data):
        if data[pos] != 0xFF or (data[pos + 1] & 0xF6) != 0xF0:
            raise ValueError("lost ADTS sync")
        prot = data[pos + 1] & 1
        prof = (data[pos + 2] >> 6) + 1
        sri = (data[pos + 2] >> 2) & 15
        ch = ((data[pos + 2] & 1) << 2) | (data[pos + 3] >> 6)
        n = ((data[pos + 3] & 3) << 11) | (data[pos + 4] << 3) | (data[pos + 5] >> 5)
        h = 7 if prot else 9
        if config is None:
            config = bytes([(prof << 3) | (sri >> 1), ((sri & 1) << 7) | (ch << 3)])
        yield config, data[pos + h:pos + n]
        pos += n


def main():
    ok = 0
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        run("ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-f", "lavfi", "-i",
            "anoisesrc=d=2:c=pink:a=0.2", "-f", "lavfi", "-i", "sine=frequency=3000:duration=2", "-filter_complex",
            "[0][1]amix=inputs=2[m];[m][2]join=inputs=2:channel_layout=stereo,volume=0.8", str(d / "src.wav"))
        run("ffmpeg", "-y", "-f", "lavfi", "-i",
            "aevalsrc=exprs='if(lt(mod(t\\,0.25)\\,0.01)\\,sin(2*PI*900*t)*0.9\\,0.01*sin(2*PI*200*t))|0.5*sin(2*PI*300*t)*lt(mod(t\\,0.4)\\,0.02)':d=2",
            str(d / "clicks.wav"))
        for name, opts in KINDS:
            aac = d / "x.aac"
            src = "clicks.wav" if name.startswith("short") else "src.wav"
            run("ffmpeg", "-y", "-i", str(d / src), *opts, "-c:a", "aac", "-f", "adts", str(aac))
            run("ffmpeg", "-y", "-i", str(aac), "-f", "s16le", str(d / "ref.raw"))
            ref = array.array("h", (d / "ref.raw").read_bytes())
            dec = None
            out = bytearray()
            for config, frame in adts_frames(aac.read_bytes()):
                if dec is None:
                    dec = AAC(config)
                out += dec.decode(frame)
            mine = array.array("h", bytes(out))
            n = min(len(ref), len(mine))
            # ffmpeg drops the first frame (the encoder's priming): line up by searching
            best = None
            ch = dec.channels
            for skip in (0, 1024 * ch, 2048 * ch):
                m = min(len(ref), len(mine) - skip)
                if m <= 0:
                    continue
                sig = sum(ref[i] * ref[i] for i in range(m)) or 1
                err = sum((mine[skip + i] - ref[i]) ** 2 for i in range(m)) or 1
                snr = 10 * math.log10(sig / err)
                if best is None or snr > best[0]:
                    best = (snr, skip)
            snr = best[0]
            good = snr > 60
            ok += good
            print("%-12s %s  SNR %.1f dB  (%d vs %d samples, skip %d)" % (name, "ok " if good else "BAD", snr, len(mine), len(ref), best[1]))
    print("%d/%d" % (ok, len(KINDS)))
    return ok == len(KINDS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
