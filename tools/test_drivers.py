"""Driver checks: boot PyKernel in QEMU with each device and use it.

    python tools/test_drivers.py

NVMe disk, USB controller with a keyboard, a mouse and a stick, AC'97 sound
(QEMU records what the card plays into a WAV file) and the RTL8139 card.
"""
import queue
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402
from run import qemu_command  # noqa: E402

WORK = Path(tempfile.mkdtemp())


class Machine(T.Machine):
    """Like test.Machine, without the IDE disk and with extra QEMU options."""

    def __init__(self, extra, env_nic=None):
        import os
        if env_nic:
            os.environ["PYKERNEL_NIC"] = env_nic
        cmd = qemu_command(["-display", "none", "-serial", "mon:stdio"] + extra, disk=None)
        os.environ.pop("PYKERNEL_NIC", None)
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.q = queue.Queue()
        self.log = bytearray()
        threading.Thread(target=self._pump, daemon=True).start()


def blank(name, mib):
    path = WORK / name
    with open(path, "wb") as f:
        f.truncate(mib << 20)
    return path


def fat_stick():
    path = blank("stick.img", 16)
    if shutil.which("mformat") and shutil.which("mcopy"):
        subprocess.run(["mformat", "-i", str(path), "::"], check=True, capture_output=True)
        note = WORK / "leeme.txt"
        note.write_text("hola desde el pendrive\n")
        subprocess.run(["mcopy", "-i", str(path), str(note), "::LEEME.TXT"], check=True, capture_output=True)
        return path
    return None


def nvme(check):
    img = blank("nvme.img", 32)
    m = Machine(["-drive", "file=%s,if=none,id=nv,format=raw" % img, "-device", "nvme,serial=pyk,drive=nv"])
    try:
        boot = m.until(T.PROMPT, 60).decode(errors="replace")
        check("NVMe: the blank disk is formatted and mounted at /disk", "mounted at /disk" in boot, boot[-400:])
        out = m.cmd("write('/disk/n.txt', 'nvme ' * 300); ata.disk.flush(); ata.disk, len(open('/disk/n.txt').read())")
        check("NVMe: write and read back a file", "<NVMe" in out and "1500)" in out, out)
    finally:
        m.close()
    check("NVMe: the data is really on the disk image", b"nvme nvme" in img.read_bytes())


def usb(check):
    stick = fat_stick()
    extra = ["-device", "qemu-xhci,id=xhci", "-device", "usb-kbd,bus=xhci.0", "-device", "usb-mouse,bus=xhci.0"]
    if stick:
        extra += ["-drive", "if=none,id=st,file=%s,format=raw" % stick, "-device", "usb-storage,bus=xhci.0,drive=st"]
    m = Machine(extra)
    try:
        m.until(T.PROMPT, 60)
        out = m.cmd("from kernel import usb, mouse; [d.kind for d in usb.devices]")
        check("USB: keyboard, mouse (and stick) found at boot", "'keyboard'" in out and "'mouse'" in out
              and ("'storage'" in out or not stick), out)
        if stick:
            out = m.cmd("cat('/usb/LEEME.TXT')")
            check("USB: a file on the stick is read", "hola desde el pendrive" in out, out)
        m.press("shift-u", "s", "b", "o", "k")
        time.sleep(1)
        out = m.cmd("", 10)
        check("USB: the keyboard types (with Shift)", "Usbok" in out, out)
        x0 = m.cmd("mouse.x")
        m.monitor("mouse_move 25 15", pause=0.6)
        time.sleep(0.5)
        out = m.cmd("mouse.x - %s" % x0.strip().splitlines()[-1].strip(), 10)
        check("USB: the mouse moves the pointer", out.strip().splitlines()[-1].strip() not in ("0", ""), out)
    finally:
        m.close()


def sound(check):
    wav = WORK / "audio.wav"
    import os
    os.environ["PYKERNEL_AUDIO"] = "wav,path=%s" % wav
    m = Machine([])
    os.environ.pop("PYKERNEL_AUDIO")
    try:
        m.until(T.PROMPT, 60)
        out = m.cmd("from kernel import sound; sound.card is not None")
        check("sound: the AC'97 card is found", "True" in out, out)
        m.cmd("play('/share/sounds/arranque.wav'); import time; time.sleep(3)", 20)
    finally:
        m.close()
    data = wav.read_bytes()[44:] if wav.is_file() else b""
    n = len(data) // 2
    loud = sum(1 for v in struct.unpack("<%dh" % n, data[:2 * n]) if abs(v) > 1000) if n else 0
    check("sound: QEMU heard the startup chime", loud > 5000, loud)


def rtl8139(check):
    m = Machine([], env_nic="user,model=rtl8139")
    try:
        m.until(T.PROMPT, 60)
        out = m.cmd("from kernel import net; net.up(); net.nic.name, net.ping('10.0.2.2') is not None", 30)
        check("RTL8139: DHCP and ping", "('rtl8139', True)" in out, out)
    finally:
        m.close()


def main():
    subprocess.run([sys.executable, str(ROOT / "tools" / "build.py"), "--fs"], check=True, capture_output=True)
    for part in (nvme, usb, sound, rtl8139):
        try:
            part(T.check)
        except TimeoutError as e:
            T.check("%s: no timeout" % part.__name__, False, str(e)[-800:])
    print("\n%d/%d driver checks passed" % (sum(T.CHECKS), len(T.CHECKS)))
    sys.exit(0 if all(T.CHECKS) else 1)


if __name__ == "__main__":
    main()
