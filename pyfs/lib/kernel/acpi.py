# ACPI: the firmware's description of the machine, read from Python.
#
# The BIOS leaves a "Root System Description Pointer" in low memory. It
# points at a table of tables: FADT (power management registers), MADT
# (interrupt controllers and CPUs), HPET (high precision timer), MCFG (PCI
# Express config space) and the DSDT (AML bytecode). We parse just enough of
# them to power off, reset, and find the APICs and the HPET.
import _kernel
from kernel.hw import mem, peek8, peek16, peek32, peek64

tables = {}           # signature -> address of the table header
fadt = {}             # decoded fields of the FADT
cpus = []             # [(processor uid, apic id, enabled)]
ioapics = []          # [(id, address, gsi_base)]
overrides = {}        # ISA irq -> (gsi, flags)
lapic_addr = 0xFEE00000
s5 = None             # (SLP_TYPa, SLP_TYPb) for soft-off
rsdp = 0


def _checksum(addr, length):
    return sum(mem(addr, length)) & 0xFF == 0


def _find_rsdp():
    ebda = peek16(0x40E) << 4
    for start, size in ((ebda, 1024), (0xE0000, 0x20000)):
        if not start:
            continue
        for a in range(start, start + size, 16):
            if mem(a, 8) == b"RSD PTR " and _checksum(a, 20):
                return a
    return 0


def _sig(addr):
    return bytes(mem(addr, 4)).decode()


def init():
    """Find and decode the ACPI tables. Safe to call again."""
    global rsdp, lapic_addr, s5
    tables.clear()
    cpus.clear()
    ioapics.clear()
    overrides.clear()
    rsdp = _find_rsdp()
    if not rsdp:
        return False
    revision = peek8(rsdp + 15)
    if revision >= 2 and peek64(rsdp + 24):
        root, width = peek64(rsdp + 24), 8          # XSDT
    else:
        root, width = peek32(rsdp + 16), 4          # RSDT
    length = peek32(root + 4)
    for p in range(root + 36, root + length, width):
        t = peek64(p) if width == 8 else peek32(p)
        if t and _checksum(t, peek32(t + 4)):
            tables[_sig(t)] = t
    if "FACP" in tables:
        _parse_fadt(tables["FACP"])
    if "APIC" in tables:
        _parse_madt(tables["APIC"])
    s5 = _find_s5()
    return True


def _parse_fadt(t):
    length = peek32(t + 4)
    fadt.update(
        facs=peek32(t + 36), dsdt=peek32(t + 40), sci_irq=peek16(t + 46),
        smi_cmd=peek32(t + 48), acpi_enable=peek8(t + 52), acpi_disable=peek8(t + 53),
        pm1a_evt=peek32(t + 56), pm1b_evt=peek32(t + 60),
        pm1a_cnt=peek32(t + 64), pm1b_cnt=peek32(t + 68), pm_tmr=peek32(t + 76),
        century=peek8(t + 108), boot_arch=peek16(t + 109) if length > 110 else 0,
        flags=peek32(t + 112) if length > 115 else 0)
    if length >= 129:      # ACPI 2+: reset register (generic address structure)
        fadt["reset_space"] = peek8(t + 116)
        fadt["reset_addr"] = peek64(t + 120)
        fadt["reset_value"] = peek8(t + 128)
    if length >= 148 and peek64(t + 140):
        fadt["dsdt"] = peek64(t + 140)


def _parse_madt(t):
    global lapic_addr
    lapic_addr = peek32(t + 36)
    p, end = t + 44, t + peek32(t + 4)
    while p < end:
        kind, size = peek8(p), peek8(p + 1)
        if size < 2:
            break
        if kind == 0:                       # processor local APIC
            cpus.append((peek8(p + 2), peek8(p + 3), bool(peek32(p + 4) & 1)))
        elif kind == 1:                     # I/O APIC
            ioapics.append((peek8(p + 2), peek32(p + 4), peek32(p + 8)))
        elif kind == 2:                     # interrupt source override
            overrides[peek8(p + 3)] = (peek32(p + 4), peek16(p + 8))
        elif kind == 5:                     # 64-bit local APIC address
            lapic_addr = peek64(p + 4)
        p += size


def _find_s5():
    """Look for the \\_S5_ package in the DSDT: the sleep type for soft-off."""
    dsdt = fadt.get("dsdt")
    if not dsdt:
        return None
    body = bytes(mem(dsdt, peek32(dsdt + 4)))
    i = body.find(b"_S5_")
    if i < 0 or body[i + 4] != 0x12:         # PackageOp
        return None
    i += 5
    i += ((body[i] >> 6) & 3) + 1            # PkgLength
    i += 1                                   # NumElements

    def value(i):
        if body[i] == 0x0A:                  # BytePrefix
            return body[i + 1], i + 2
        if body[i] in (0x00, 0x01):          # Zero / One
            return body[i], i + 1
        return body[i], i + 1

    a, i = value(i)
    b, i = value(i)
    return a, b


def _enable():
    """Hand power management from SMM to the OS, if the firmware wants that."""
    cnt = fadt.get("pm1a_cnt")
    if not cnt or _kernel.inw(cnt) & 1:
        return
    if fadt.get("smi_cmd") and fadt.get("acpi_enable"):
        _kernel.outb(fadt["smi_cmd"], fadt["acpi_enable"])
        for _ in range(300000):
            if _kernel.inw(cnt) & 1:
                break


def poweroff():
    """ACPI soft-off (S5). Returns only if the machine is still on."""
    if not tables:
        init()
    if s5 and fadt.get("pm1a_cnt"):
        _enable()
        _kernel.outw(fadt["pm1a_cnt"], (s5[0] << 10) | (1 << 13))
        if fadt.get("pm1b_cnt"):
            _kernel.outw(fadt["pm1b_cnt"], (s5[1] << 10) | (1 << 13))
    _kernel.outw(0x604, 0x2000)              # QEMU without a DSDT match
    _kernel.outw(0xB004, 0x2000)             # Bochs / old QEMU
    _kernel.outw(0x4004, 0x3400)             # VirtualBox


def reset():
    """Restart through the FADT reset register, then PCI 0xCF9, then the 8042."""
    if not tables:
        init()
    space, addr = fadt.get("reset_space"), fadt.get("reset_addr")
    if addr:
        if space == 1:
            _kernel.outb(addr, fadt["reset_value"])
        elif space == 0:
            mem(addr, 1)[0] = fadt["reset_value"]
    _kernel.outb(0xCF9, 0x02)
    _kernel.outb(0xCF9, 0x06)
    _kernel.outb(0x64, 0xFE)


def pm_timer_ticks():
    """The ACPI power-management timer: 3.579545 MHz, 24 or 32 bits."""
    port = fadt.get("pm_tmr")
    return _kernel.inl(port) if port else 0


def summary():
    lines = ["RSDP at %#x; tables: %s" % (rsdp, " ".join(sorted(tables)))]
    lines.append("CPUs: %d   local APIC at %#x" % (len(cpus), lapic_addr))
    for i, a, b in ioapics:
        lines.append("I/O APIC %d at %#x, GSI base %d" % (i, a, b))
    if overrides:
        lines.append("IRQ overrides: " + ", ".join("%d->%d" % (k, v[0]) for k, v in sorted(overrides.items())))
    lines.append("PM1a control %#x, PM timer %#x, SCI irq %d, S5 %s" % (
        fadt.get("pm1a_cnt", 0), fadt.get("pm_tmr", 0), fadt.get("sci_irq", 0), s5))
    return "\n".join(lines)
