# Contributing to PyKernel

Issues and pull requests are welcome — especially **reports from real hardware** (use the *Hardware report* issue template) and drivers the kernel does not have yet (network card, AHCI/NVMe, USB, sound).

## Where to start reading

Open these in order; each one is short.

| FILE | WHAT YOU LEARN |
|---|---|
| `pyfs/lib/kernel/boot.py` | the whole bring-up order of the kernel, in ~60 lines of Python |
| `pyfs/lib/kernel/pic.py`, `timer.py` | what programming an interrupt controller and a timer chip really looks like |
| `pyfs/lib/kernel/keyboard.py` | scancodes → characters, layouts, dead keys |
| `pyfs/lib/kernel/ata.py` | a complete IDE disk driver: one class, sectors in and out with port I/O |
| `pyfs/lib/kernel/mm.py` | physical frames and x86_64 page tables, walked and edited from Python |
| `pyfs/lib/kernel/repl.py`, `lineedit.py` | the `>>>` console itself |
| `rust/interrupts.rs`, `rust/sched.rs` | the little that must not be Python: the IDT and the context switch |

## Changing things

- **Python** (`pyfs/`): edit and run `python tools/run.py` again — no compile step. Inside the system, `edit('/lib/kernel/keyboard.py')` works too, but `/lib` lives in RAM and is rebuilt from the boot image at every boot: new modules you want to keep go in `/disk/lib` (on the import path), and lasting changes to the kernel go in `pyfs/` on the host.
- **Rust or C** (`rust/`, `mpy/`): `python tools/build.py`.
- **Tests**: `python tools/test.py` boots QEMU headless and runs 89 checks (keyboard on every layout, screen, disk and power-cycle, threads, the console, pygame drawing). Please keep it green; add a check for what you add.

Write code that someone reading it for the first time can follow: the point of this kernel is that its source is the documentation.
