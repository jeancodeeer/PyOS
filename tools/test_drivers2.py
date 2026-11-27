"""Driver checks: the printer port and the print spooler, Intel HD Audio and
virtio disks. Boots PyKernel + SnakeyOS in QEMU with those devices added.

    python tools/test_drivers2.py      (tools/test_drivers.py: NVMe, USB, AC97, RTL8139)
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402
from run import make_disk, host_path  # noqa: E402

check = T.check
BUILD = ROOT / "build"


def main():
    subprocess.run([sys.executable, str(ROOT / "tools" / "build.py"), "--fs"], check=True, capture_output=True)
    printed = BUILD / "printer-out.prn"
    printed.write_bytes(b"")
    vdisk = BUILD / "virtio-disk.img"
    with open(vdisk, "wb") as f:
        f.truncate(8 << 20)                                   # an empty 8 MiB disk
    os.environ["PYKERNEL_PRINTER"] = str(printed)
    os.environ["PYKERNEL_QEMU"] = ("-device intel-hda -device hda-duplex,audiodev=snd0 "
                                   "-drive file=%s,format=raw,if=virtio" % host_path(vdisk))
    m = T.Machine(make_disk(BUILD / "test-disk.img"))
    try:
        m.until(T.PROMPT, 90)
        # ---- the parallel port ----
        out = m.cmd("from kernel import lpt; [p.name for p in lpt.ports]", 20)
        check("lpt: LPT1 found", "'LPT1'" in out, out)
        m.cmd("open('/dev/lp0', 'wb').write(b'HOLA IMPRESORA\\n')", 20)
        out = m.cmd("from kernel import drivers; drivers.legacy()", 20)
        check("lpt: listed by lsdrv", "LPT1 parallel" in out, out)
        # ---- the spooler: to the printer and to a PDF file ----
        m.cmd("from pyos import printing", 20)
        m.cmd("j1 = printing.print_text('Primera linea\\nSegunda (con parentesis)', 'Prueba', 'LPT1')", 20)
        m.cmd("j2 = printing.print_text('Texto en PDF: año, canción', 'Carta', 'PDF')", 20)
        m.cmd("import pygame; s = pygame.Surface((300, 200)); s.fill((255, 255, 255)); "
              "s.fill((200, 0, 0), (10, 10, 50, 50))", 20)
        m.cmd("j3 = printing.submit('PDF', 'Dibujo', [s], 100)", 20)
        m.cmd("import time; exec('for _ in range(200):\\n    if all(j.state in (\\'hecho\\', \\'error\\') "
              "for j in (j1, j2, j3)): break\\n    time.sleep_ms(50)')", 30)
        out = m.cmd("(j1.state, j2.state, j2.result, j3.state, j3.result)", 20)
        check("spooler: three jobs done", out.count("'hecho'") == 3, out)
        out = m.cmd("open(j2.result, 'rb').read(8), open(j3.result, 'rb').read()[-6:]", 20)
        check("spooler: the PDF files are PDFs", "%PDF-1.4" in out and "%%EOF" in out, out)
        # ---- Intel HD Audio ----
        out = m.cmd("from kernel import hda, sound; c = hda.probe(); (c.name, c.dac, len(c.pins), c.steps)", 30)
        check("hda: codec found, a DAC and an output pin", "'HD Audio'" in out and "Error" not in out, out)
        m.cmd("sound.card = c; sound.beep(440, 300)", 20)
        m.cmd("time.sleep_ms(150)", 10)
        out = m.cmd("(sound.busy(), c.current())", 10)
        check("hda: playing a tone (the stream moves)", out.strip().splitlines()[-1].startswith("(True"), out)
        m.cmd("time.sleep_ms(1200)", 10)
        out = m.cmd("[sound._on_tick() for _ in range(3)]; sound.busy()", 10)
        check("hda: ... and it stops at the end", "False" in out, out)
        # ---- virtio-blk ----
        out = m.cmd("from kernel import virtio_blk; d = virtio_blk.disks(); d", 20)
        check("virtio-blk: one 8 MiB disk", "virtio-blk 8 MiB" in out, out)
        m.cmd("b = bytearray(b'PyKernel' * 192); d[0].writeblocks(100, b)", 20)
        out = m.cmd("r = bytearray(1536); d[0].readblocks(100, r); r == b", 20)
        check("virtio-blk: write 3 sectors and read them back", "True" in out, out)
        m.cmd("import os; os.VfsFat.mkfs(d[0]); os.mount(os.VfsFat(d[0]), '/vd')", 30)
        m.cmd("f = open('/vd/hola.txt', 'w'); f.write('desde virtio'); f.close()", 20)
        out = m.cmd("os.listdir('/vd'), open('/vd/hola.txt').read()", 20)
        check("virtio-blk: a FAT file system on it", "'hola.txt'" in out and "desde virtio" in out, out)
    finally:
        m.close()
    data = printed.read_bytes()
    check("lpt: the printer received the bytes", data.startswith(b"HOLA IMPRESORA\n"), data[:40])
    check("lpt: ... and the spooler's job as a PDF", b"%PDF-1.4" in data and b"%%EOF" in data, data[-40:])
    pdf = data[data.find(b"%PDF"):]
    try:
        text = subprocess.run(["pdftotext", "-", "-"], input=pdf, capture_output=True).stdout.decode()
        check("lpt: the PDF has the text", "Segunda (con parentesis)" in text, text)
    except FileNotFoundError:
        pass
    print("%d/%d passed" % (sum(T.CHECKS), len(T.CHECKS)))
    return all(T.CHECKS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
