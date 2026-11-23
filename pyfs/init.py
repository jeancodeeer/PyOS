# PyKernel stage 1 -- the first Python the machine runs.
#
# The Rust layer finds this file in the boot archive and executes it in
# __main__. Its job: turn the boot archive into a mounted root filesystem
# (a RAM filesystem implemented right here, in Python), then hand over to
# the kernel package in /lib/kernel.

import sys, io, uctypes, vfs, _kernel


class RamFile(io.IOBase):
    """A writable file living in the Python heap."""

    def __init__(self, fs_dir, name, data, text, append):
        self._dir, self._name, self._text = fs_dir, name, text
        self._buf = bytearray(data)
        self._pos = len(self._buf) if append else 0
        self._open = True

    def write(self, data):
        if isinstance(data, str):
            data = data.encode()
        end = self._pos + len(data)
        if end > len(self._buf):
            self._buf.extend(bytes(end - len(self._buf)))
        self._buf[self._pos:end] = data
        self._pos = end
        return len(data)

    def readinto(self, buf):
        chunk = self._buf[self._pos:self._pos + len(buf)]
        buf[:len(chunk)] = chunk
        self._pos += len(chunk)
        return len(chunk)

    def read(self, n=-1):
        end = len(self._buf) if n is None or n < 0 else self._pos + n
        chunk = bytes(self._buf[self._pos:end])
        self._pos += len(chunk)
        return str(chunk, "utf8") if self._text else chunk

    def seek(self, off, whence=0):
        base = (0, self._pos, len(self._buf))[whence]
        self._pos = max(0, min(len(self._buf), base + off))
        return self._pos

    def tell(self):
        return self._pos

    def flush(self):
        self._dir[self._name] = bytes(self._buf)

    def close(self):
        if self._open:
            self._open = False
            self.flush()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class RamFS:
    """Root filesystem: directories are dicts, files are bytes."""

    def __init__(self, tree=None):
        self.tree = {} if tree is None else tree
        self.cwd = "/"

    # -- path handling --
    def _parts(self, path):
        if not path.startswith("/"):
            path = self.cwd.rstrip("/") + "/" + path
        out = []
        for p in path.split("/"):
            if p == "..":
                if out:
                    out.pop()
            elif p and p != ".":
                out.append(p)
        return out

    def _node(self, parts):
        node = self.tree
        for p in parts:
            if not isinstance(node, dict) or p not in node:
                raise OSError(2)  # ENOENT
            node = node[p]
        return node

    def _parent(self, path):
        parts = self._parts(path)
        if not parts:
            raise OSError(22)  # EINVAL
        parent = self._node(parts[:-1])
        if not isinstance(parent, dict):
            raise OSError(20)  # ENOTDIR
        return parent, parts[-1]

    # -- VFS protocol --
    def mount(self, readonly, mkfs):
        pass

    def umount(self):
        pass

    def chdir(self, path):
        parts = self._parts(path)
        if not isinstance(self._node(parts), dict):
            raise OSError(20)
        self.cwd = "/" + "/".join(parts)

    def getcwd(self):
        return self.cwd

    def stat(self, path):
        node = self._node(self._parts(path))
        if isinstance(node, dict):
            return (0x4000, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        return (0x8000, 0, 0, 0, 0, 0, len(node), 0, 0, 0)

    def statvfs(self, path):
        import gc
        return (16, 16, (gc.mem_free() + gc.mem_alloc()) // 16, gc.mem_free() // 16,
                gc.mem_free() // 16, 0, 0, 0, 0, 255)

    def ilistdir(self, path):
        node = self._node(self._parts(path))
        if not isinstance(node, dict):
            raise OSError(20)
        for name in sorted(node):
            child = node[name]
            if isinstance(child, dict):
                yield (name, 0x4000, 0, 0)
            else:
                yield (name, 0x8000, 0, len(child))

    def mkdir(self, path):
        parent, name = self._parent(path)
        if name in parent:
            raise OSError(17)  # EEXIST
        parent[name] = {}

    def rmdir(self, path):
        parent, name = self._parent(path)
        node = parent.get(name)
        if not isinstance(node, dict):
            raise OSError(2 if node is None else 20)
        if node:
            raise OSError(39)  # ENOTEMPTY
        del parent[name]

    def remove(self, path):
        parent, name = self._parent(path)
        node = parent.get(name)
        if node is None:
            raise OSError(2)
        if isinstance(node, dict):
            raise OSError(21)  # EISDIR
        del parent[name]

    def rename(self, old, new):
        op, on = self._parent(old)
        if on not in op:
            raise OSError(2)
        np, nn = self._parent(new)
        np[nn] = op.pop(on)

    def open(self, path, mode="r"):
        parent, name = self._parent(path)
        node = parent.get(name)
        if isinstance(node, dict):
            raise OSError(21)
        text = "b" not in mode
        if "w" in mode or "a" in mode or "+" in mode:
            if node is None or "w" in mode:
                node = parent[name] = b""
            return RamFile(parent, name, node, text, "a" in mode)
        if node is None:
            raise OSError(2)
        return io.StringIO(str(node, "utf8")) if text else io.BytesIO(node)


def _unpack(tree):
    """Copy the boot archive (format: tools/mkfs.py) into the RAM tree."""
    info = _kernel.info()
    size = info["initrd_end"] - info["initrd_start"]
    if size < 8:
        return 0
    img = uctypes.bytearray_at(info["initrd_start"], size)
    if bytes(img[0:4]) != b"PYFS":
        return 0
    count = int.from_bytes(img[4:8], "little")
    pos = 8
    for _ in range(count):
        nlen = int.from_bytes(img[pos:pos + 2], "little")
        dlen = int.from_bytes(img[pos + 2:pos + 6], "little")
        name = str(img[pos + 6:pos + 6 + nlen], "utf8")
        pos += 6 + nlen
        node = tree
        parts = name.split("/")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = bytes(img[pos:pos + dlen])
        pos += dlen
    return count


rootfs = RamFS()
_unpack(rootfs.tree)
rootfs.tree.setdefault("disk", {})     # mount point for the hard disk
vfs.mount(rootfs, "/")
sys.path[:] = ["", "/lib"]

try:
    import kernel.boot
    kernel.boot.main()
    from kernel.shell import *
except Exception as e:
    print("PyKernel: boot failed; you are in the bare console.")
    sys.print_exception(e)
