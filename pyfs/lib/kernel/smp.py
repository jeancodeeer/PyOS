# The other CPU cores: wake them with INIT-SIPI-SIPI and see them answer.
#
# At power-on only one core runs (the bootstrap processor). The others wait
# for an inter-processor interrupt. We write a few bytes of 16-bit machine
# code at 0x8000, send each core INIT and then "start at 0x8000" twice; the
# code increments a counter and halts. Python itself keeps running on core
# 0 only (MicroPython has one interpreter lock), so the cores are woken,
# counted and parked: this is the first step of multiprocessing, in Python.
import time
from kernel import acpi, apic
from kernel.hw import mem, peek16, poke16

TRAMPOLINE = 0x8000
COUNTER = 0x7FF0
#   cli; xor ax,ax; mov ds,ax; lock inc word [0x7FF0]; hlt; jmp hlt
CODE = bytes((0xFA, 0x31, 0xC0, 0x8E, 0xD8, 0xF0, 0xFF, 0x06, COUNTER & 0xFF, COUNTER >> 8, 0xF4, 0xEB, 0xFD))
started = []


def _wait_us(us):
    t = time.ticks_us()
    while time.ticks_us() - t < us:
        pass


def start_aps():
    """Wake every other core listed in the ACPI MADT. Returns how many answered."""
    if not acpi.tables:
        acpi.init()
    me = apic.lapic_id()
    mem(TRAMPOLINE, len(CODE))[:] = CODE
    poke16(COUNTER, 0)
    started.clear()
    for uid, apic_id, enabled in acpi.cpus:
        if apic_id == me or not enabled:
            continue
        before = peek16(COUNTER)
        apic.send_ipi(apic_id, 0x4500)                       # INIT
        _wait_us(10000)
        for _ in range(2):
            apic.send_ipi(apic_id, 0x4600 | (TRAMPOLINE >> 12))   # STARTUP at 0x8000
            _wait_us(200)
        deadline = time.ticks_ms() + 200
        while peek16(COUNTER) == before and time.ticks_ms() < deadline:
            pass
        if peek16(COUNTER) != before:
            started.append(apic_id)
    return len(started)


def summary():
    if not acpi.tables:
        acpi.init()
    n = len([c for c in acpi.cpus if c[2]])
    return "CPU cores in the firmware tables: %d (this one: APIC id %d); woken and parked: %s" % (
        n, apic.lapic_id(), ", ".join(str(a) for a in started) or "none yet (cpus('start'))")
