"""Build PyKernel: MicroPython VM (WSL gcc) -> Rust kernel -> flat image -> boot archive.

    python tools/build.py            # everything
    python tools/build.py --fs       # only repack pyfs/ (after editing Python)
    python tools/build.py --arch aarch64   # ARM64: build/aarch64/kernel.elf + BOOTAA64.EFI
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import mkfs  # noqa: E402


def wsl_path(p: Path) -> str:
    p = p.resolve()
    return f"/mnt/{p.drive[0].lower()}{p.as_posix()[2:]}"


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def apply_patches():
    """Apply mpy/patches/*.patch to the MicroPython checkout (once each)."""
    vendor = ROOT / "vendor" / "micropython"
    for patch in sorted((ROOT / "mpy" / "patches").glob("*.patch")):
        applied = subprocess.run(["git", "-C", str(vendor), "apply", "--reverse", "--check", str(patch)],
                                 capture_output=True).returncode == 0
        if not applied:
            run(["git", "-C", str(vendor), "apply", str(patch)])


def build_arm64():
    """ARM64: the VM with aarch64-linux-gnu-gcc, the kernel as a position-independent
    ELF, and the UEFI loader (boot/aarch64-efi)."""
    apply_patches()
    run(["make", "-C", "mpy", "-j8", "ARCH=aarch64"], cwd=ROOT)
    run(["cargo", "build", "--release", "--target", "aarch64-unknown-none"], cwd=ROOT)
    run(["cargo", "build", "--release", "--target", "aarch64-unknown-uefi"], cwd=ROOT / "boot" / "aarch64-efi")
    out = ROOT / "build" / "aarch64"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "target" / "aarch64-unknown-none" / "release" / "pykernel", out / "kernel.elf")
    shutil.copy(ROOT / "boot" / "aarch64-efi" / "target" / "aarch64-unknown-uefi" / "release" / "bootaa64.efi",
                out / "BOOTAA64.EFI")
    print(f"kernel.elf: {(out / 'kernel.elf').stat().st_size} bytes, BOOTAA64.EFI: {(out / 'BOOTAA64.EFI').stat().st_size} bytes")


def build_vm():
    if not (ROOT / "vendor" / "micropython" / "py").is_dir():
        # MicroPython v1.25.0 is a git submodule: fetch it the first time
        run(["git", "submodule", "update", "--init", "--depth", "1", "vendor/micropython"], cwd=ROOT)
    apply_patches()
    make = ["make", "-C", "mpy", "-j8"]
    if sys.platform == "win32":
        make = ["wsl", "--cd", wsl_path(ROOT), "-e"] + make
    run(make, cwd=ROOT)


def build_kernel():
    run(["cargo", "build", "--release"], cwd=ROOT)
    elf = ROOT / "target" / "x86_64-unknown-none" / "release" / "pykernel"
    sysroot = Path(subprocess.check_output(["rustc", "--print", "sysroot"], text=True).strip())
    objcopy = next(iter(sysroot.glob("lib/rustlib/*/bin/rust-objcopy*")), None) or shutil.which("llvm-objcopy")
    if not objcopy:
        sys.exit("rust-objcopy not found (rustup component add llvm-tools)")
    out = ROOT / "build" / "kernel.bin"
    run([str(objcopy), "-O", "binary", str(elf), str(out)])
    print(f"kernel.bin: {out.stat().st_size} bytes")


def build_fs():
    n = mkfs.pack(ROOT / "pyfs", ROOT / "build" / "pyfs.img")
    print(f"pyfs.img: {n} files")


if __name__ == "__main__":
    if "--arch" in sys.argv and sys.argv[sys.argv.index("--arch") + 1] == "aarch64":
        build_arm64()
        build_fs()
        sys.exit(0)
    if "--fs" not in sys.argv:
        build_vm()
        build_kernel()
    build_fs()
