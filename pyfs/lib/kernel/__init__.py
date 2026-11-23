# The PyKernel kernel package. Each module is one subsystem:
#
#   hw        raw memory / port helpers on top of the Rust primitives
#   irq       interrupt vector registry
#   pic       8259 interrupt controller driver
#   timer     PIT system tick
#   console   VGA text console with a small ANSI terminal
#   keyboard  PS/2 keyboard driver
#   serial    COM1 input driver
#   mm        physical frame allocator and page tables
#   thread    preemptive threads (on Rust's context switch)
#   sched     cooperative background tasks (generators)
#   ata       IDE disk driver; FAT filesystem mounted at /disk
#   rtc       CMOS clock
#   pci       PCI bus enumeration
#   shell     the commands available at the >>> prompt
#   boot      brings all of the above up, in order

VERSION = "0.2.0"
