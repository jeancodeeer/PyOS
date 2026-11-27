"""Make a bootable CD/USB image (GRUB) for running SnakeyOS on a real PC.

    python tools/iso.py            # -> build/snakeyos.iso (PyKernel + SnakeyOS)
    python tools/iso.py --boot     # ...and boot it in QEMU to check
    python tools/iso.py --arch aarch64   # -> build/snakeyos-arm64.iso (UEFI, ARM64)

The ARM64 image is a UEFI one: BOOTAA64.EFI (boot/aarch64-efi) with
kernel.elf and pyfs.img on a FAT boot partition (El Torito and, for USB
sticks, a GPT partition too).

PYKERNEL_ONLY=1 makes build/pykernel.iso, the kernel without SnakeyOS.
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

GRUB_CFG = """set timeout=2
set timeout_style=hidden
set default=0
menuentry "%s" {
    multiboot /boot/kernel.bin
    module /boot/pyfs.img
    boot
}
menuentry "%s (consola de texto)" {
    multiboot /boot/kernel.bin console
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
    title = "PyKernel" if kernel_only else "SnakeyOS (PyKernel)"
    (tree / "boot" / "grub" / "grub.cfg").write_text(GRUB_CFG % (title, title), newline="\n")
    iso = ROOT / "build" / ("pykernel.iso" if kernel_only else "snakeyos.iso")
    cmd = ["grub-mkrescue", "-o", host_path(iso), host_path(tree)]
    if uses_wsl():
        cmd = ["wsl", "-e"] + cmd
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"{iso.name}: {iso.stat().st_size >> 10} KiB")
    return iso


def build_iso_arm64() -> Path:
    out = ROOT / "build" / "aarch64"
    kernel, loader = out / "kernel.elf", out / "BOOTAA64.EFI"
    if not kernel.is_file() or not loader.is_file():
        sys.exit("build/aarch64 is missing: run  python tools/build.py --arch aarch64")
    mkfs.pack(ROOT / "pyfs", ROOT / "build" / "pyfs.img")
    tree = ROOT / "build" / "iso-arm64"
    shutil.rmtree(tree, ignore_errors=True)
    tree.mkdir(parents=True)
    efi = tree / "efi.img"
    need = kernel.stat().st_size + loader.stat().st_size + (ROOT / "build" / "pyfs.img").stat().st_size
    mib = need // (1 << 20) + 8
    with open(efi, "wb") as f:
        f.truncate(mib << 20)
    run = lambda *c: subprocess.run(list(c), check=True, capture_output=True)
    run("mformat", "-i", str(efi), "-v", "SNAKEYOS", "::")   # FAT16: what the size calls for (UEFI is strict)
    run("mmd", "-i", str(efi), "::/EFI", "::/EFI/BOOT", "::/snakeyos")
    run("mcopy", "-i", str(efi), str(loader), "::/EFI/BOOT/BOOTAA64.EFI")
    run("mcopy", "-i", str(efi), str(kernel), "::/snakeyos/kernel.elf")
    run("mcopy", "-i", str(efi), str(ROOT / "build" / "pyfs.img"), "::/snakeyos/pyfs.img")
    iso = ROOT / "build" / "snakeyos-arm64.iso"
    run("xorriso", "-as", "mkisofs", "-o", str(iso), "-R", "-J", "-V", "SNAKEYOS_ARM64",
        "-e", "efi.img", "-no-emul-boot", "-append_partition", "2", "0xef", str(efi), str(tree))
    print(f"{iso.name}: {iso.stat().st_size >> 10} KiB")
    return iso


if __name__ == "__main__":
    if "--arch" in sys.argv and sys.argv[sys.argv.index("--arch") + 1] == "aarch64":
        build_iso_arm64()
        sys.exit(0)
    iso = build_iso()
    if "--boot" in sys.argv:
        qemu = ["wsl", "-e", "qemu-system-x86_64"] if uses_wsl() else ["qemu-system-x86_64"]
        sys.exit(subprocess.call(qemu + ["-m", "256", "-cdrom", host_path(iso), "-boot", "d", "-nographic"]))
