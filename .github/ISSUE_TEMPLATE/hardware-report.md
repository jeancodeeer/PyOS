---
name: Hardware report
about: You booted PyKernel on a real PC (or another emulator). Tell us what happened.
title: "[hardware] <machine model>"
labels: hardware
---

> ⚠️ PyKernel runs everything in ring 0 and its disk driver writes to the first IDE/ATA disk it finds. Boot it from USB/CD on a machine **with no disk you care about**, or with the disks disconnected.

**Machine** (model, CPU, RAM, BIOS or UEFI-CSM):

**How you booted it** (USB written with …, CD, Ventoy, VirtualBox …):

**What you saw** (a photo of the screen is perfect):

- [ ] GRUB menu appeared
- [ ] PyKernel banner and `>>>`
- [ ] keyboard works
- [ ] `lspci` lists devices
- [ ] `run('/lib/pygame/examples/bounce.py')` shows graphics

**Anything else** (error text, where it stopped):
