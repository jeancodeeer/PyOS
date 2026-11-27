"""Boot the ARM64 ISO in QEMU for a while, then save the screen and the serial log.
    python tools/arm_shot.py SECONDS [keys...]   -> build/arm.png, build/arm.log"""
import os, socket, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
secs = int(sys.argv[1]) if len(sys.argv) > 1 else 60
mon = os.path.join(ROOT, "build", "mon.sock")
if os.path.exists(mon):
    os.remove(mon)
p = subprocess.Popen([os.path.join(ROOT, "tools", "run_arm64.sh"), os.path.join(ROOT, "build", "snakeyos-arm64.iso"),
                      "-display", "none", "-serial", "file:" + os.path.join(ROOT, "build", "arm.log"), "-no-reboot",
                      "-monitor", "unix:%s,server,nowait" % mon], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(secs)
s = socket.socket(socket.AF_UNIX)
s.connect(mon)
time.sleep(0.5)
s.recv(65536)
for k in sys.argv[2:]:
    if k.startswith("!"):                       # a monitor command: !mouse_move 10 10
        s.send((k[1:] + "\n").encode())
    elif k.startswith("@"):                     # a pause: @5 (seconds)
        time.sleep(float(k[1:]))
    else:
        s.send(("sendkey %s\n" % k).encode())
    time.sleep(0.3)
if sys.argv[2:]:
    time.sleep(5)
ppm = os.path.join(ROOT, "build", "arm.ppm")
s.send(("screendump %s\n" % ppm).encode())
time.sleep(2)
p.kill()
from PIL import Image
Image.open(ppm).save(os.path.join(ROOT, "build", "arm.png"))
print("ok")
