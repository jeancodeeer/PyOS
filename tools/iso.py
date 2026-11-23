"""Make a bootable CD/USB image (GRUB) for running PyOS on a real PC.

    python tools/iso.py            # -> build/pyos.iso (PyKernel + PyOS)
    python tools/iso.py --boot     # ...and boot it in QEMU to check

PYKERNEL_ONLY=1 makes build/pykernel.iso, the kernel without PyOS.
Write the .iso to a USB stick with any image writer (Rufus in
"DD image" mode, balenaEtcher, dd) and boot it in legacy BIOS / CSM mode.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import mkfs  # noqa: E402
from run import host_path, uses_wsl  # noqa: E402

GRUB_CFG = """set timeout=0
set default=0
menuentry "%s" {
    multiboot /boot/kernel.bin
    module /boot/pyfs.img
    boot
}
"""


def build_iso() -> Path:
    kernel = ROOT / "build" / "kernel.bin"
    if not kernel.is_file():
        sys.exit("build/kernel.bin is missing: run  python tools/build.py")
    mkfs.pack(ROOT / "pyfs", ROOT / "build" / "pyfs.img")
    tree = ROOT / "build" / "iso"
    shutil.rmtree(tree, ignore_errors=True)
    (tree / "boot" / "grub").mkdir(parents=True)
    shutil.copy(kernel, tree / "boot" / "kernel.bin")
    shutil.copy(ROOT / "build" / "pyfs.img", tree / "boot" / "pyfs.img")
    kernel_only = bool(os.environ.get("PYKERNEL_ONLY"))
    title = "PyKernel" if kernel_only else "PyOS (PyKernel)"
    (tree / "boot" / "grub" / "grub.cfg").write_text(GRUB_CFG % title, newline="\n")
    iso = ROOT / "build" / ("pykernel.iso" if kernel_only else "pyos.iso")
    cmd = ["grub-mkrescue", "-o", host_path(iso), host_path(tree)]
    if uses_wsl():
        cmd = ["wsl", "-e"] + cmd
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"{iso.name}: {iso.stat().st_size >> 10} KiB")
    return iso


if __name__ == "__main__":
    iso = build_iso()
    if "--boot" in sys.argv:
        qemu = ["wsl", "-e", "qemu-system-x86_64"] if uses_wsl() else ["qemu-system-x86_64"]
        sys.exit(subprocess.call(qemu + ["-m", "256", "-cdrom", host_path(iso), "-boot", "d", "-nographic"]))
