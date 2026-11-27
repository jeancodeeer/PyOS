# The kernel's command line: the words after the kernel's name in the boot
# loader (GRUB: "multiboot /boot/kernel.bin console"; QEMU: -append console).
#
#   cmdline.text()          "console"
#   cmdline.has("console")  True: start in the text console, not the desktop
import _kernel
from kernel.hw import peek8, peek32

_text = None


def text():
    global _text
    if _text is None:
        _text = ""
        mbi = _kernel.info().get("multiboot")
        if mbi and peek32(mbi) & 4:                  # multiboot flag 2: there is a command line
            p = peek32(mbi + 16)
            out = bytearray()
            while len(out) < 512:
                b = peek8(p + len(out))
                if not b:
                    break
                out.append(b)
            _text = out.decode("utf-8", "replace")
    return _text


def has(word):
    return word in text().split()
