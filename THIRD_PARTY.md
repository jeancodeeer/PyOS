# Third-party code

| COMPONENT | WHERE | LICENSE |
|---|---|---|
| [MicroPython](https://github.com/micropython/micropython) v1.25.0 (the Python VM, compiler, FAT driver, libm) | `vendor/micropython` (git submodule), plus the patch in `mpy/patches/` | MIT — see [`pyfs/licenses/MicroPython.txt`](pyfs/licenses/MicroPython.txt), which also ships inside the kernel image and the ISO (`/licenses`) |
| [GRUB](https://www.gnu.org/software/grub/) (boot loader, only inside the released ISO, not in this repository) | added by `grub-mkrescue` when `tools/iso.py` builds the ISO | GPL-3.0-or-later; source at gnu.org |
| [DejaVu fonts](https://dejavu-fonts.github.io/) (Sans, Sans Mono), drawn into glyph atlases by `tools/mkfont.py` | `pyos/share/fonts/*.pkf` | Bitstream Vera / DejaVu licence (free to use and redistribute) — see [`pyfs/licenses/DejaVu.txt`](pyfs/licenses/DejaVu.txt) |
| Mozilla's root certificates, via [certifi](https://github.com/certifi/python-certifi) | `pyfs/etc/ssl/certs.pem` | MPL-2.0 |
| [h264bsd](https://github.com/oneam/h264bsd) (H.264 Baseline video decoder, commit 42bcb5d7) | `mpy/media/h264bsd`, built into the kernel by `mpy/modmedia.c` | Apache-2.0 — see [`mpy/media/h264bsd/LICENSE.md`](mpy/media/h264bsd/LICENSE.md) |
| Helix AAC decoder (RealNetworks), as kept in [ESP8266Audio](https://github.com/earlephilhower/ESP8266Audio) `src/libhelix-aac` (commit 0c7c67a9) | `mpy/media/aac` | RealNetworks Public Source License 1.0 (RPSL) — see the licence block in each file and [`mpy/media/aac/README-helix.txt`](mpy/media/aac/README-helix.txt); the source must stay available with the binary |
| [minimp3](https://github.com/lieff/minimp3) (MP3 decoder, commit 48e3a085) | `mpy/media/mp3/minimp3.h` | CC0-1.0 — see [`mpy/media/mp3/LICENSE`](mpy/media/mp3/LICENSE) |
| [libwebp](https://chromium.googlesource.com/webm/libwebp) (WebP picture decoder only: `src/dec`, `src/dsp`, `src/utils`; commit d05ff79d) | `mpy/media/webp`, built into the kernel by `mpy/modmedia.c` | BSD-3-Clause, with Google's patent grant — see [`mpy/media/webp/LICENSE`](mpy/media/webp/LICENSE) and [`mpy/media/webp/PATENTS`](mpy/media/webp/PATENTS) |
| [QuickJS](https://bellard.org/quickjs/) (JavaScript engine, ES2023; version 2026-06-04, commit 25197744) | `mpy/js/quickjs`, built into the kernel by `mpy/modjs.c` (with `mpy/js/shim.c`) | MIT — see [`mpy/js/quickjs/LICENSE`](mpy/js/quickjs/LICENSE). Changed: `Atomics` is left out (no OS threads here), marked `PyKernel` in `quickjs.c` |
| [JeanCode](https://github.com/jeancodeeer/JeanCode) pygame client | `pyfs/lib/jeancode` | MIT, also mine |

`pyfs/lib/pygame` is an independent implementation of the pygame 2 *API* written for this kernel; it contains no code from [pygame](https://github.com/pygame/pygame) (LGPL) or SDL. "pygame" is the name of that project, used here only to say which API this follows.
