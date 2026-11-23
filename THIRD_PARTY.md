# Third-party code

| COMPONENT | WHERE | LICENSE |
|---|---|---|
| [MicroPython](https://github.com/micropython/micropython) v1.25.0 (the Python VM, compiler, FAT driver, libm) | `vendor/micropython` (git submodule), plus the patch in `mpy/patches/` | MIT — see [`pyfs/licenses/MicroPython.txt`](pyfs/licenses/MicroPython.txt), which also ships inside the kernel image and the ISO (`/licenses`) |
| [GRUB](https://www.gnu.org/software/grub/) (boot loader, only inside the released ISO, not in this repository) | added by `grub-mkrescue` when `tools/iso.py` builds the ISO | GPL-3.0-or-later; source at gnu.org |
| [DejaVu fonts](https://dejavu-fonts.github.io/) (Sans, Sans Mono), drawn into glyph atlases by `tools/mkfont.py` | `pyos/share/fonts/*.pkf` | Bitstream Vera / DejaVu licence (free to use and redistribute) — see [`pyfs/licenses/DejaVu.txt`](pyfs/licenses/DejaVu.txt) |
| Mozilla's root certificates, via [certifi](https://github.com/certifi/python-certifi) | `pyfs/etc/ssl/certs.pem` | MPL-2.0 |
| [JeanCode](https://github.com/jeancodeeer/JeanCode) pygame client | `pyfs/lib/jeancode` | MIT, also mine |

`pyfs/lib/pygame` is an independent implementation of the pygame 2 *API* written for this kernel; it contains no code from [pygame](https://github.com/pygame/pygame) (LGPL) or SDL. "pygame" is the name of that project, used here only to say which API this follows.
