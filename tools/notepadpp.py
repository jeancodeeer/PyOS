"""Notepad++ for PyWin: fetch the official portable build and make a disk with it.

    python tools/notepadpp.py                 # -> build/notepadpp-disk.img
    python tools/run.py --disk build/notepadpp-disk.img   (or QDISK=... in the tests)

Then, in SnakeyOS: open /disk/pywin/npp/notepad++.exe (double click in Archivos,
or the PyWin app). Notepad++ (https://notepad-plus-plus.org) is free
software under the GNU GPL v3, by Don Ho and its contributors; it is not
kept in this repository.

The program is about 9 MiB, too big for the boot image, so it goes on a FAT16
disk with 32 KiB clusters (the IDE driver then reads it in big DMA pieces).
Needs mtools and dosfstools (mkfs.fat, mmd, mcopy).
"""
import io
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "8.9.9.1"
URL = "https://github.com/notepad-plus-plus/notepad-plus-plus/releases/download/v%s/npp.%s.portable.x64.zip"
DISK = ROOT / "build" / "notepadpp-disk.img"
SIZE_MB = 256


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else VERSION
    for tool in ("mkfs.fat", "mmd", "mcopy"):
        if not shutil.which(tool):
            sys.exit("%s is missing: install dosfstools and mtools" % tool)
    print("downloading Notepad++ %s..." % version)
    data = urllib.request.urlopen(URL % (version, version), timeout=300).read()
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "npp"
        zipfile.ZipFile(io.BytesIO(data)).extractall(folder)
        if not (folder / "notepad++.exe").is_file():
            sys.exit("the zip has no notepad++.exe")
        DISK.parent.mkdir(exist_ok=True)
        DISK.unlink(missing_ok=True)
        with open(DISK, "wb") as f:
            f.truncate(SIZE_MB << 20)
        subprocess.run(["mkfs.fat", "-F", "16", "-s", "64", "-n", "PYOS", str(DISK)], check=True,
                       capture_output=True)
        subprocess.run(["mmd", "-i", str(DISK), "::/pywin"], check=True)
        subprocess.run(["mcopy", "-s", "-i", str(DISK), str(folder), "::/pywin/npp"], check=True)
    print("ready: %s  (Notepad++ at /disk/pywin/npp/notepad++.exe)" % DISK)


if __name__ == "__main__":
    main()
