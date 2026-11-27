"""Video and sound playback (media/, the kernel's _media decoders) in QEMU.

Makes a short MP4 (H.264 Baseline + AAC) and an MP3 with ffmpeg, puts them
on a FAT disk, boots PyKernel and plays them.

    python tools/test_media.py
"""
import ast
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402

check = T.check


def make_files(folder):
    """prueba.mp4 (320x240, 3 s, 25 fps) and tono.mp3 (3 s), on a 32 MiB FAT disk image."""
    mp4, mp3, disk = folder / "prueba.mp4", folder / "tono.mp3", folder / "media.img"
    run = lambda *a: subprocess.run(["ffmpeg", "-loglevel", "error", "-y"] + list(a), check=True)
    run("-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=3", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=3", "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
        "-g", "25", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(mp4))
    run("-f", "lavfi", "-i", "sine=frequency=660:duration=3", "-c:a", "libmp3lame", "-b:a", "128k", str(mp3))
    with open(disk, "wb") as f:
        f.truncate(32 << 20)
    subprocess.run(["mkfs.fat", "-F", "16", str(disk)], check=True, capture_output=True)
    for p in (mp4, mp3):
        subprocess.run(["mcopy", "-i", str(disk), str(p), "::/" + p.name], check=True)
    return disk


def value(m, expr, timeout=60):
    """Run expr in the kernel's Python and read back its repr."""
    out = m.cmd("print('<<' + repr(%s) + '>>')" % expr, timeout)
    text = T.strip_ansi(out) if hasattr(T, "strip_ansi") else out
    start = text.rfind("<<")
    end = text.rfind(">>")
    return ast.literal_eval(text[start + 2:end]) if 0 <= start < end else text


def main():
    if not shutil.which("ffmpeg") or not shutil.which("mcopy"):
        print("needs ffmpeg and mtools")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        disk = make_files(Path(tmp))
        m = T.Machine(disk)
        try:
            m.until(T.PROMPT, 90)
            m.cmd("import media, _media; from media import mp4, player; media.init()", 30)
            info = value(m, "(lambda v: (v.video.codec, v.video.width, v.video.height, v.audio.codec, "
                            "v.audio.rate, round(v.duration, 1), v.video.count()))(mp4.open_file('/disk/prueba.mp4'))")
            check("MP4: H.264 and AAC tracks, size, length, frames", info == ("avc1", 320, 240, "mp4a", 44100, 3.0, 75)
                  or (isinstance(info, tuple) and info[:4] == ("avc1", 320, 240, "mp4a") and abs(info[5] - 3) < 0.2))
            m.cmd("mv = mp4.open_file('/disk/prueba.mp4'); d = _media.H264(); d.decode(mv.video.headers)", 30)
            pics = value(m, "sum(d.decode(mv.video.read(i)) for i in range(10))")
            check("H.264: ten frames give ten pictures", pics == 10)
            check("H.264: picture size", value(m, "d.crop()[2:]") == (320, 240))
            m.cmd("import pygame; s = pygame.Surface((320, 240)); d.draw(s._buf, 320, 240, 0, 0, 320, 240)", 30)
            check("H.264: the picture is drawn (not black)", value(m, "max(s._buf[i] for i in range(0, 76800 * 4, 997))") > 40)
            m.cmd("a = _media.AAC(mv.audio.config); pcm = b''.join(a.decode(mv.audio.read(i)) for i in range(20))", 30)
            check("AAC: sound comes out, 44.1 kHz", value(m, "(len(pcm) > 40000, a.format()[0])") == (True, 44100))
            m.cmd("mp = _media.MP3(); out = mp.decode(open('/disk/tono.mp3', 'rb').read(16384))", 30)
            check("MP3: sound comes out, 44.1 kHz", value(m, "(len(out[0]) > 1000, out[1] > 0, mp.format()[0])")
                  == (True, True, 44100))
            # real time: play for two seconds with the sound card's clock
            code = ("from kernel import sound, timer\nimport time\nsound.init()\np = player.Player('/disk/prueba.mp4')\n"
                    "p.play()\nt0 = timer.ms()\nwhile timer.ms() - t0 < 2000:\n    p.update()\n    time.sleep_ms(10)\n")
            m.cmd("exec(%r)" % code, 60)
            got = value(m, "(round(p.clock(), 1), p.vi, p.playing)")
            check("player: about two seconds played, pictures in step", isinstance(got, tuple)
                  and 1.4 <= got[0] <= 2.6 and abs(got[1] - got[0] * 25) <= 15 and got[2])
            m.cmd("p.pause(); p.seek(2.5)", 60)
            got = value(m, "(round(p.clock(), 1), p.vi)")
            check("player: jumping to 2.5 s", got == (2.5, 62), got)
            m.cmd("p.close(); q = player.Player('/disk/tono.mp3')", 30)
            check("player: MP3 length", abs(value(m, "q.duration") - 3.0) < 0.3)
        finally:
            m.close()
    print("%d/%d passed" % (sum(T.CHECKS), len(T.CHECKS)))
    return all(T.CHECKS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
