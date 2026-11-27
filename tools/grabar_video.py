"""Record a video of SnakeyOS: from the boot to the guided tour of every app.

    python tools/doom.py                 # optional: DOOM for the PyWin part
    python tools/grabar_video.py         # -> build/pyos-demo.mp4

QEMU runs with its monitor on a socket of its own; a thread takes a
picture of the screen ("screendump") several times a second and hands it
to ffmpeg, which makes an H.264 video at 25 frames per second. Meanwhile
this script types at the PyKernel console like a person would, then runs
tour() (pyos/lib/pyos/tour.py): the robot inside SnakeyOS does the rest.
"""
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402
from run import qemu_command, make_disk, host_path  # noqa: E402

W, H = 1024, 768
OUT = ROOT / "build" / ("pyos-prueba.mp4" if "--only" in sys.argv else "pyos-demo.mp4")
CONSOLE = ["cpus", "lsdrv", "ifconfig", "ping('10.0.2.2', 2)", "mounts", "procs", "ls('/share/pywin')"]


class Recorder:
    """Pictures of the QEMU screen -> ffmpeg."""

    def __init__(self, sock_path, out, fps=6):
        self.sock_path, self.out, self.fps = sock_path, out, fps
        self.running = True
        self.frames = 0
        self.tmp = Path(tempfile.mkdtemp())
        self.ffmpeg = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-use_wallclock_as_timestamps", "1",
             "-c:v", "ppm", "-i", "-", "-vf", "fps=25", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
            stdin=subprocess.PIPE)
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def connect(self):
        for _ in range(100):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(self.sock_path)
                s.settimeout(10)
                self.sock = s
                self.read_prompt()
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("no QEMU monitor")

    def read_prompt(self):
        buf = b""
        while not buf.endswith(b"(qemu) "):
            chunk = self.sock.recv(4096)
            if not chunk:
                raise EOFError
            buf += chunk

    def frame(self, ppm: Path) -> bytes:
        """The screen as a 1024x768 PPM; text mode (720x400) is scaled and centred."""
        from PIL import Image
        img = Image.open(ppm).convert("RGB")
        if img.size != (W, H):
            scale = min(W / img.width, H / img.height)
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.BICUBIC)
            canvas = Image.new("RGB", (W, H))
            canvas.paste(img, ((W - img.width) // 2, (H - img.height) // 2))
            img = canvas
        header = b"P6\n%d %d\n255\n" % (W, H)
        return header + img.tobytes()

    def loop(self):
        self.connect()
        ppm = self.tmp / "s.ppm"
        period = 1.0 / self.fps
        while self.running:
            start = time.time()
            try:
                self.sock.sendall(b"screendump " + host_path(ppm).encode() + b"\n")
                self.read_prompt()
                self.ffmpeg.stdin.write(self.frame(ppm))
                self.frames += 1
            except (OSError, EOFError, ValueError):
                if not self.running:
                    break
                time.sleep(0.2)
            time.sleep(max(0.0, period - (time.time() - start)))

    def start(self):
        self.thread.start()

    def stop(self):
        self.running = False
        self.thread.join(15)
        self.ffmpeg.stdin.close()
        self.ffmpeg.wait()


class Machine(T.Machine):
    def __init__(self, disk, monitor):
        cmd = qemu_command(["-display", "none", "-serial", "stdio", "-monitor", "unix:%s,server,nowait" % monitor],
                           memory="768", disk=disk)
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.q = queue.Queue()
        self.log = bytearray()
        threading.Thread(target=self._pump, daemon=True).start()

    def type_line(self, line, delay=0.07):
        """Type like a person: one key at a time, so it shows on the screen."""
        for ch in line:
            self.send(ch.encode())
            time.sleep(delay)
        time.sleep(0.3)
        self.send(b"\r")


def main():
    env = dict(os.environ)
    extra = ROOT / "build" / "extra"
    if extra.is_dir():
        env["PYOS_EXTRA"] = str(extra)
    subprocess.run([sys.executable, str(ROOT / "tools" / "build.py"), "--fs"], check=True, env=env,
                   capture_output=True)
    disk = make_disk(ROOT / "build" / "video-disk.img", fresh=True)
    monitor = str(Path(tempfile.mkdtemp()) / "monitor.sock")
    m = Machine(disk, monitor)
    rec = Recorder(monitor, OUT)
    rec.start()
    try:
        m.until(T.PROMPT, 120)
        time.sleep(2.5)
        only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
        for line in ([] if only else CONSOLE):
            m.type_line(line)
            m.until(T.PROMPT, 60)
            time.sleep(2.2)
        if only:                                    # a quick try of some steps of the tour
            m.send(("tour(only=%r)\r" % only).encode())
        else:
            m.type_line("tour()")
        m.until(T.PROMPT, 3600)                     # the desktop ends with the tour
        time.sleep(3)
        m.type_line("log.lines()[-3:] and 'fin'")
        m.until(T.PROMPT, 30)
        time.sleep(2)
    finally:
        rec.stop()
        errors = [l for l in m.log.decode(errors="replace").splitlines() if "tour:" in l or "error" in l.lower()]
        m.close()
    print("video: %s (%d imagenes)" % (OUT, rec.frames))
    if errors:
        print("avisos:\n  " + "\n  ".join(errors[-12:]))


if __name__ == "__main__":
    main()
