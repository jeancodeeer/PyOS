"""Make the system sounds in pyos/share/sounds (small 22 kHz mono WAV files).

    python tools/mksounds.py
"""
import math
import struct
import wave
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "pyos" / "share" / "sounds"
RATE = 22050


def note(freq, secs, vol=0.35, decay=3.0):
    n = int(RATE * secs)
    return [vol * math.exp(-decay * i / n) * (math.sin(2 * math.pi * freq * i / RATE) +
                                               0.3 * math.sin(4 * math.pi * freq * i / RATE)) for i in range(n)]


def mix(*parts):
    """parts: (start seconds, samples)."""
    length = max(int(s * RATE) + len(p) for s, p in parts)
    out = [0.0] * length
    for start, p in parts:
        o = int(start * RATE)
        for i, v in enumerate(p):
            out[o + i] += v
    return out


def save(name, samples):
    with wave.open(str(OUT / name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, v)) * 32000)) for v in samples))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    save("arranque.wav", mix((0.0, note(523.25, 1.2)), (0.12, note(659.25, 1.1)), (0.24, note(783.99, 1.0)),
                             (0.36, note(1046.5, 1.2, 0.25))))
    save("aviso.wav", mix((0.0, note(880, 0.25)), (0.1, note(1318.5, 0.35))))
    save("clic.wav", note(1500, 0.03, 0.25, 8))
    save("error.wav", mix((0.0, note(330, 0.3)), (0.15, note(247, 0.4))))
    print("sounds in", OUT)


if __name__ == "__main__":
    main()
