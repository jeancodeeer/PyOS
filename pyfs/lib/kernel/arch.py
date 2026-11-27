# Which machine this is, and the few things that differ on ARM64.
#
# PyKernel runs on PCs (x86_64, BIOS + Multiboot) and on ARM64 machines with
# UEFI firmware (QEMU's virt, servers, Raspberry Pi 4/5 with UEFI). On ARM64
# there is no VGA, PS/2, PIT, CMOS clock or ISA ports: the screen is the
# UEFI framebuffer, keyboards and mice are USB, the tick is the generic
# timer (started by rust/arm64), the clock comes from UEFI at boot, power
# off and reset are PSCI calls. PCI works as on PCs (rust/arm64/cpu.rs keeps
# ports 0xCF8/0xCFC and I/O BARs working).
import _kernel

_info = _kernel.info()
ARM = _info.get("arch", 0) == 1
NAME = "aarch64" if ARM else "x86_64"


def info(key, default=0):
    return _info.get(key, default)


def cpu_name():
    """'ARM Cortex-A72' and the like, from MIDR_EL1."""
    midr = _kernel.cr(8)                   # rust/arm64/cpu.rs: MIDR_EL1
    implementer, part = (midr >> 24) & 0xFF, (midr >> 4) & 0xFFF
    parts = {0xD03: "Cortex-A53", 0xD04: "Cortex-A35", 0xD05: "Cortex-A55", 0xD07: "Cortex-A57",
             0xD08: "Cortex-A72", 0xD09: "Cortex-A73", 0xD0A: "Cortex-A75", 0xD0B: "Cortex-A76",
             0xD0C: "Neoverse-N1", 0xD0D: "Cortex-A77", 0xD40: "Neoverse-V1", 0xD41: "Cortex-A78",
             0xD44: "Cortex-X1", 0xD46: "Cortex-A510", 0xD47: "Cortex-A710", 0xD49: "Neoverse-N2",
             0xD4F: "Neoverse-V2", 0xD80: "Cortex-A520", 0xD81: "Cortex-A720"}
    vendor = {0x41: "ARM", 0x61: "Apple", 0x51: "Qualcomm", 0x48: "HiSilicon", 0x43: "Cavium"}.get(implementer, "ARM64")
    return "%s %s" % (vendor, parts.get(part, "core %#x" % part)) if midr else "ARM64"


# ---- PSCI: power off and reset through the firmware ----

def _psci(function):
    """Call PSCI `function` with HVC or SMC (as ACPI's FADT says): a few
    instructions written into memory and called."""
    conduit = info("psci")
    if not conduit:
        return False
    hvc_or_smc = 0xD4000002 if conduit == 2 else 0xD4000003        # hvc #0 / smc #0
    code = bytearray(b"".join(w.to_bytes(4, "little") for w in (
        0xD2800000 | ((function & 0xFFFF) << 5),                    # movz w0, #lo
        0x72A00000 | (((function >> 16) & 0xFFFF) << 5),            # movk w0, #hi, lsl 16
        hvc_or_smc,
        0xD65F03C0)))                                               # ret
    import uctypes
    _kernel.call(uctypes.addressof(code))
    return True


def poweroff():
    return _psci(0x84000008)          # SYSTEM_OFF


def reset():
    return _psci(0x84000009)          # SYSTEM_RESET


def memory_map():
    """(base, length, 1) for the RAM UEFI left free (kernel/mm.py's memory_map())."""
    from kernel.hw import peek32, peek64
    p, end, step = info("mmap"), info("mmap") + info("mmap_size"), info("mmap_desc")
    while step and p + step <= end:
        kind = peek32(p)
        if kind in (1, 3, 4, 7):
            yield peek64(p + 8), peek64(p + 24) * 4096, 1
        p += step


def pci_vector(bus, dev, fn):
    """The GIC interrupt of a PCI function's INTx line on QEMU's virt (SPIs 3..6,
    swizzled by slot), or None."""
    from kernel import pci
    pin = pci.read32(bus, dev, fn, 0x3C) >> 8 & 0xFF
    if not pin:
        return None
    return 32 + 3 + ((dev + pin - 1) % 4)


def fast(fn, name):
    """`fn` (a @micropython.viper function), or on ARM64, where MicroPython has no
    native code emitter, its C version _fast.<name> (mpy/modfast.c)."""
    if not ARM:
        return fn
    try:
        import _fast
        return getattr(_fast, name)
    except (ImportError, AttributeError):
        return fn
