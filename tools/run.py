"""Boot PyKernel in QEMU.

    python tools/run.py              # console in this terminal (serial); Ctrl-A X quits
    python tools/run.py --screen     # the emulated PC screen + PS/2 keyboard (a window)
    python tools/run.py --curses     # the screen inside this terminal (text mode only)
    python tools/run.py --no-bridge  # without the network bridge on COM2

Uses a Windows QEMU if one is on PATH, otherwise the one inside WSL.
COM2 is connected to tools/jeancode_bridge.py, which runs here and makes the
HTTPS requests of JeanCode when the machine has no network card.
Its log (method and host only, never keys) is build/bridge.log.
Edit files under pyfs/ (PyKernel) or pyos/ (SnakeyOS) and run again: the boot
archive is repacked each time.
build/disk.img is the machine's hard disk (/disk inside); it keeps its contents.
"""
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import mkfs  # noqa: E402

DISK_MIB = 32


def wsl_path(p: Path) -> str:
    p = p.resolve()
    return f"/mnt/{p.drive[0].lower()}{p.as_posix()[2:]}"


def uses_wsl() -> bool:
    return sys.platform == "win32" and not shutil.which("qemu-system-x86_64")


def host_path(p: Path) -> str:
    """A path as the QEMU process will see it."""
    return wsl_path(p) if uses_wsl() else str(p)


def accel_options():
    """Hardware acceleration for QEMU, when this computer has it: the virtual
    machine then runs at nearly the real CPU's speed instead of being emulated
    instruction by instruction (10 to 50 times slower). Each -accel is tried in
    turn, so a machine without it still boots with plain emulation (tcg).
    PYKERNEL_ACCEL=tcg turns it off; =kvm, =whpx or =hvf picks one."""
    choice = os.environ.get("PYKERNEL_ACCEL", "auto").lower()
    if choice not in ("auto", ""):
        return ["-accel", choice] + ([] if choice == "tcg" else ["-accel", "tcg"])
    if uses_wsl() or sys.platform.startswith("linux"):
        kvm = os.path.exists("/dev/kvm") and os.access("/dev/kvm", os.R_OK | os.W_OK)
        if uses_wsl():
            kvm = subprocess.run(["wsl", "-e", "test", "-w", "/dev/kvm"], capture_output=True).returncode == 0
        return ["-accel", "kvm", "-cpu", "host", "-accel", "tcg"] if kvm else []
    if sys.platform == "win32":
        return ["-accel", "whpx,kernel-irqchip=off", "-accel", "tcg"]
    if sys.platform == "darwin":
        return ["-accel", "hvf", "-accel", "tcg"]
    return []


def make_disk(path: Path, fresh=False):
    if fresh or not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.truncate(DISK_MIB << 20)
    return path


def qemu_command(extra, memory=None, disk=None):
    kernel, fs = ROOT / "build" / "kernel.bin", ROOT / "build" / "pyfs.img"
    if not kernel.is_file():
        sys.exit("build/kernel.bin is missing: run  python tools/build.py")
    base = ["wsl", "-e", "qemu-system-x86_64"] if uses_wsl() else [shutil.which("qemu-system-x86_64") or "qemu-system-x86_64"]
    memory = memory or os.environ.get("PYKERNEL_RAM", "2048")       # MiB; like a modest real PC
    cmd = base + ["-m", memory, "-no-reboot", "-kernel", host_path(kernel), "-initrd", host_path(fs)]
    cmd += accel_options()
    # the kernel's command line. Without a screen (tests, the serial console) SnakeyOS
    # starts in the text console; with one, it boots into the desktop
    headless = "-display" in extra and extra[extra.index("-display") + 1] == "none"
    append = os.environ.get("PYKERNEL_APPEND", "console" if headless else "")
    if append:
        cmd += ["-append", append]
    # a network card on QEMU's built-in NAT: DHCP gives 10.0.2.15, the host is 10.0.2.2
    cmd += ["-nic", os.environ.get("PYKERNEL_NIC", "user,model=virtio-net-pci")]
    # an AC'97 sound card; PYKERNEL_AUDIO=pa (or sdl, alsa, coreaudio, dsound) to hear it
    audio = os.environ.get("PYKERNEL_AUDIO", "none")
    cmd += ["-audiodev", "%s,id=snd0" % audio, "-device", "AC97,audiodev=snd0"]
    if os.environ.get("PYKERNEL_USB"):          # a USB controller with a stick: PYKERNEL_USB=path/to/stick.img
        cmd += ["-device", "qemu-xhci,id=xhci", "-drive", "if=none,id=usbstick,format=raw,file=" + os.environ["PYKERNEL_USB"],
                "-device", "usb-storage,bus=xhci.0,drive=usbstick"]
    # a printer on LPT1: what PyKernel prints goes to this file (PYKERNEL_PRINTER=out.prn)
    if os.environ.get("PYKERNEL_PRINTER"):
        cmd += ["-parallel", "file:" + host_path(Path(os.environ["PYKERNEL_PRINTER"]))]
    if disk:
        cmd += ["-drive", f"file={host_path(disk)},format=raw,if=ide,index=0,media=disk"]
    # more QEMU options, e.g. PYKERNEL_QEMU="-device intel-hda -device hda-duplex"
    cmd += os.environ.get("PYKERNEL_QEMU", "").split()
    return cmd + extra


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def bridge_serial(port):
    """COM2 as a TCP server that the bridge connects to (WSL forwards localhost to Windows)."""
    return ["-serial", f"tcp:127.0.0.1:{port},server=on,wait=off"]


def start_bridge(port, log_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "pyos" / "lib"))      # jeancode lives in SnakeyOS
    log = open(log_path, "ab")
    return subprocess.Popen([sys.executable, str(ROOT / "tools" / "jeancode_bridge.py"),
                             "--connect", f"127.0.0.1:{port}", "--wait", "120"],
                            env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL)


def window_display():
    """A real window if this QEMU has one (WSL needs the qemu-system-gui package)."""
    if not uses_wsl():
        return []
    out = subprocess.run(["wsl", "-e", "qemu-system-x86_64", "-display", "help"],
                         capture_output=True, text=True).stdout.split()
    for name in ("gtk", "sdl"):
        if name in out:
            return ["-display", name]
    print("this QEMU has no window display (in WSL: apt install qemu-system-gui); using curses")
    return ["-display", "curses"]


if __name__ == "__main__":
    mkfs.pack(ROOT / "pyfs", ROOT / "build" / "pyfs.img")
    # --disk other.img: boot with that disk at /disk (e.g. build/notepadpp-disk.img)
    chosen = sys.argv[sys.argv.index("--disk") + 1] if "--disk" in sys.argv[:-1] else None
    disk = Path(chosen) if chosen else make_disk(ROOT / "build" / "disk.img")
    port = None if "--no-bridge" in sys.argv else free_port()
    com2 = bridge_serial(port) if port else []
    if "--screen" in sys.argv:
        cmd = qemu_command(window_display() + ["-serial", "vc"] + com2, disk=disk)
    elif "--curses" in sys.argv:
        cmd = qemu_command(["-display", "curses", "-serial", "vc"] + com2, disk=disk)
    else:
        cmd = qemu_command(["-display", "none", "-serial", "mon:stdio"] + com2, disk=disk)
    qemu = subprocess.Popen(cmd)
    bridge = start_bridge(port, ROOT / "build" / "bridge.log") if port else None
    try:
        code = qemu.wait()
    except KeyboardInterrupt:
        code = qemu.wait()
    finally:
        if bridge:
            bridge.kill()
    sys.exit(code)
