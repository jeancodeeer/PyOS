"""Pack pyfs/ (PyKernel) and pyos/ (SnakeyOS, the operating system on top) into
the boot archive the kernel loads as its root filesystem.

The two trees are laid over each other: pyos/lib/desktop ends up at
/lib/desktop, next to the kernel's /lib/kernel. PYKERNEL_ONLY=1 leaves SnakeyOS
out, for a bare kernel that boots to the Python prompt.

Format: b"PYFS", u32 file count, then per file: u16 name length, u32 data
length, name (utf-8, '/'-separated), data. init.py is what Rust executes.
"""
import os
import struct
import sys
from pathlib import Path


TEXT = {".py", ".txt", ".md", ".html", ".htm", ".css", ".json", ".pem", ".csv", ".svg", ""}


def pack(src: Path, out: Path, os_tree: Path = None) -> int:
    if not (src / "init.py").is_file():
        sys.exit(f"{src}/init.py is missing")
    trees = [src]
    os_tree = os_tree or src.parent / "pyos"
    if os_tree.is_dir() and not os.environ.get("PYKERNEL_ONLY"):
        trees.append(os_tree)
    # PYOS_EXTRA=dir[:dir...]: more trees on top (e.g. build/extra from tools/doom.py)
    for extra in filter(None, os.environ.get("PYOS_EXTRA", "").split(os.pathsep)):
        if Path(extra).is_dir():
            trees.append(Path(extra))
    entries = {}                                     # path in the image -> file on disk
    for tree in trees:
        for p in tree.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts and p.name != "README.md":
                entries[p.relative_to(tree).as_posix()] = p
    blob = bytearray(b"PYFS" + struct.pack("<I", len(entries)))
    for rel in sorted(entries):
        p = entries[rel]
        name = rel.encode()
        data = p.read_bytes()
        if p.suffix in TEXT:                      # only text: fonts, sounds and images stay byte for byte
            data = data.replace(b"\r\n", b"\n")
        blob += struct.pack("<HI", len(name), len(data)) + name + data
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    return len(entries)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    n = pack(root / "pyfs", root / "build" / "pyfs.img")
    print(f"pyfs.img: {n} files")
