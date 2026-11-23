"""DOOM for PyWin: build a Windows x64 doom.exe and fetch the shareware game.

    python tools/doom.py              # -> build/extra/share/pywin/doom/
    PYOS_EXTRA=build/extra python tools/build.py --fs

doom.exe is built from doomgeneric (https://github.com/ozkl/doomgeneric),
id Software's DOOM source released under the GNU GPL v2, with its Win32
port; it needs MinGW (x86_64-w64-mingw32-gcc). The game data, doom1.wad,
is the shareware episode id Software let everyone copy, taken from the
Internet Archive item "DoomsharewareEpisode" (DOOM v1.9 shareware).
Neither file is kept in this repository.
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
OUT = ROOT / "build" / "extra" / "share" / "pywin" / "doom"
SOURCE = "https://github.com/ozkl/doomgeneric.git"
SHAREWARE = "https://archive.org/download/DoomsharewareEpisode/DoomV1.9sw1995idSoftwareInc.action.zip"


def build_exe(work: Path):
    subprocess.run(["git", "clone", "-q", "--depth", "1", SOURCE, str(work / "src")], check=True)
    src = work / "src" / "doomgeneric"
    win = src / "doomgeneric_win.c"
    win.write_text(win.read_text().replace("<Windows.h>", "<windows.h>"))    # MinGW's header is lower case
    subprocess.run(["make", "-f", "Makefile.win", "CC=x86_64-w64-mingw32-gcc", "-j8",
                    "CFLAGS=-O2 -s -DSNDSERV -D_DEFAULT_SOURCE -w"], cwd=src, check=True, capture_output=True)
    shutil.copy(src / "doomgeneric.exe", OUT / "doom.exe")
    shutil.copy(work / "src" / "LICENSE", OUT / "LICENSE-doomgeneric.txt")


def fetch_wad():
    data = urllib.request.urlopen(SHAREWARE, timeout=300).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        (OUT / "doom1.wad").write_bytes(z.read("DOOM1.WAD"))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        if not (OUT / "doom.exe").is_file():
            build_exe(Path(tmp))
    if not (OUT / "doom1.wad").is_file():
        fetch_wad()
    print("listo:", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    sys.exit(main())
