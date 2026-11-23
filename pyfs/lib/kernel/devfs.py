# /dev and /proc: filesystems whose files are made up on the spot.
#
#   cat('/proc/meminfo')        open('/dev/urandom','rb').read(16)
#   ls('/proc')                 one directory per process, plus system files
#
# Both are ordinary objects mounted through MicroPython's VFS layer, like
# the RAM filesystem in /init.py: ilistdir, stat and open are all they need.
import io
import os
import vfs
import _kernel

S_IFDIR, S_IFREG, S_IFCHR = 0x4000, 0x8000, 0x2000


class _Device(io.IOBase):
    """A character device: read(n) and write(data) call the given functions."""

    def __init__(self, reader=None, writer=None, text=False):
        self.reader, self.writer, self.text = reader, writer, text

    def read(self, n=-1):
        data = self.reader(4096 if n is None or n < 0 else n) if self.reader else b""
        return data.decode() if self.text else data

    def readinto(self, buf):
        data = self.reader(len(buf)) if self.reader else b""
        buf[:len(data)] = data
        return len(data)

    def readline(self):
        return self.read()

    def write(self, data):
        if self.writer:
            self.writer(data.encode() if isinstance(data, str) else bytes(data))
        return len(data)

    def flush(self):
        pass

    def close(self):
        pass

    def ioctl(self, op, arg):
        return 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


class _SynthFS:
    """Base: a tree of {name: subtree or callable}; callables make the file."""

    def tree(self):
        return {}

    def _find(self, path):
        node = self.tree()
        for part in [p for p in path.split("/") if p]:
            if not isinstance(node, dict) or part not in node:
                raise OSError(2)                      # ENOENT
            node = node[part]
            if callable(node) and not isinstance(node, dict) and getattr(node, "is_dir", False):
                node = node()
        return node

    def mount(self, readonly, mkfs):
        pass

    def umount(self):
        pass

    def chdir(self, path):
        if not isinstance(self._find(path), dict):
            raise OSError(20)
        self.cwd = path

    def getcwd(self):
        return getattr(self, "cwd", "/")

    def ilistdir(self, path):
        node = self._find(path)
        if not isinstance(node, dict):
            raise OSError(20)                         # ENOTDIR
        out = []
        for name, child in node.items():
            is_dir = isinstance(child, dict) or getattr(child, "is_dir", False)
            out.append((name, S_IFDIR if is_dir else S_IFREG, 0, 0))
        return iter(out)

    def stat(self, path):
        node = self._find(path)
        if isinstance(node, dict):
            return (S_IFDIR, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        return (S_IFREG, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    def statvfs(self, path):
        return (512, 512, 0, 0, 0, 0, 0, 0, 0, 255)

    def mkdir(self, path):
        raise OSError(1)                              # EPERM

    rmdir = remove = mkdir

    def rename(self, a, b):
        raise OSError(1)


def _dir(fn):
    fn.is_dir = True
    return fn


# ---- /dev ----

class DevFS(_SynthFS):
    def __init__(self):
        self.extra = {}            # drivers add devices here: devfs.dev.add('name', reader, writer)

    def add(self, name, reader=None, writer=None):
        self.extra[name] = (reader, writer)

    def tree(self):
        t = {name: _devfile(name) for name in ("null", "zero", "random", "urandom", "console", "tty", "kmsg", "serial")}
        for name in self.extra:
            t[name] = _devfile(name)
        from kernel import ata
        if ata.disk is not None:
            t["sda"] = _devfile("sda")
        return t

    def open(self, path, mode="r"):
        name = path.strip("/")
        text = "b" not in mode
        if name == "null":
            return _Device(lambda n: b"", lambda d: None, text)
        if name == "zero":
            return _Device(lambda n: bytes(n), lambda d: None, text)
        if name in ("random", "urandom"):
            from crypto import random_bytes
            return _Device(random_bytes, lambda d: None, text)
        if name in ("console", "tty"):
            import sys
            return _Device(lambda n: sys.stdin.read(1).encode(), lambda d: sys.stdout.write(d.decode("utf-8", "replace")), text)
        if name == "serial":
            return _Device(None, _kernel.serial_write, text)
        if name == "kmsg":
            from kernel import log
            return io.StringIO("\n".join(log.lines()) + "\n") if text else io.BytesIO(("\n".join(log.lines()) + "\n").encode())
        if name == "sda":
            return BlockDevice(__import__("kernel.ata").ata.disk, mode)
        if name in self.extra:
            r, w = self.extra[name]
            return _Device(r, w, text)
        raise OSError(2)


def _devfile(name):
    return lambda: name


class BlockDevice(io.IOBase):
    """A disk as one big file: seek anywhere, read and write bytes."""

    def __init__(self, disk, mode):
        self.disk, self.pos, self.mode = disk, 0, mode
        self.size = disk.ioctl(4, 0) * 512

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def tell(self):
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        first, last = self.pos // 512, (self.pos + n + 511) // 512
        buf = bytearray((last - first) * 512)
        self.disk.readblocks(first, buf)
        off = self.pos - first * 512
        self.pos += n
        return bytes(buf[off:off + n])

    def write(self, data):
        if "w" not in self.mode and "+" not in self.mode and "a" not in self.mode:
            raise OSError(9)                          # EBADF
        first, last = self.pos // 512, (self.pos + len(data) + 511) // 512
        buf = bytearray((last - first) * 512)
        self.disk.readblocks(first, buf)
        off = self.pos - first * 512
        buf[off:off + len(data)] = data
        self.disk.writeblocks(first, buf)
        self.pos += len(data)
        return len(data)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


# ---- /proc ----

def _meminfo():
    from kernel import mm
    import gc
    s = mm.stats()
    return ("MemTotal:   %8d kB\nMemFree:    %8d kB\nHeapTotal:  %8d kB\nHeapFree:   %8d kB\n"
            "HeapUsed:   %8d kB\nSpaces:     %8d\nSpaceMem:   %8d kB\n" % (
                s["total"] >> 10, s["free"] >> 10, s["heap"] >> 10, gc.mem_free() >> 10, gc.mem_alloc() >> 10,
                s["spaces"], s["space_bytes"] >> 10))


def _cpuinfo():
    from kernel import shell, timer
    feats = _kernel.cpuid(1)
    return "processor\t: 0\nmodel name\t: %s\nflags\t\t: edx=%08x ecx=%08x\ntsc kHz\t\t: %d\n" % (
        shell.cpu_name(), feats[3], feats[2], timer.tsc_per_ms)


def _uptime():
    from kernel import timer
    return "%.2f\n" % (timer.ms() / 1000)


def _version():
    from kernel import VERSION
    import sys
    return "PyKernel %s (MicroPython %s) x86_64\n" % (VERSION, ".".join(str(v) for v in sys.implementation[1][:3]))


def _mounts():
    return "ramfs / \nprocfs /proc\ndevfs /dev\n" + ("fat /disk\n" if _exists("/disk") else "")


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _interrupts():
    from kernel import pic
    rows = []
    for line in range(16):
        n = _kernel.irq_count(pic.vector(line))
        if n:
            rows.append("%3d: %10d" % (line, n))
    return "\n".join(rows) + "\n"


def _net_dev():
    from kernel import net
    return net.summary() + "\n"


def _net_tcp():
    from kernel import net
    return (net.connections() or "") + "\n"


def _pci():
    from kernel import pci
    return "".join("%02x:%02x.%d %04x:%04x class %02x%02x\n" % row for row in pci.scan())


def _proc_status(p):
    return lambda: p.status_text()


class ProcFS(_SynthFS):
    def tree(self):
        t = {
            "meminfo": _meminfo, "cpuinfo": _cpuinfo, "uptime": _uptime, "version": _version,
            "mounts": _mounts, "interrupts": _interrupts, "pci": _pci,
            "net": {"dev": _net_dev, "tcp": _net_tcp},
        }
        try:
            from kernel import proc
            for p in proc.table.values():
                t[str(p.pid)] = {"status": _proc_status(p), "cmdline": (lambda p=p: " ".join(p.argv) + "\n"),
                                 "environ": (lambda p=p: "".join("%s=%s\n" % kv for kv in p.env.items()))}
            t["self"] = t.get(str(proc.current().pid), {})
        except Exception:
            pass
        return t

    def open(self, path, mode="r"):
        if "w" in mode or "a" in mode:
            raise OSError(30)                         # EROFS
        node = self._find(path)
        if isinstance(node, dict):
            raise OSError(21)                         # EISDIR
        text = node()
        return io.StringIO(text) if "b" not in mode else io.BytesIO(text.encode())


dev = DevFS()
proc_fs = ProcFS()


def install():
    for fs, where in ((dev, "/dev"), (proc_fs, "/proc")):
        try:
            vfs.mount(fs, where)
        except OSError:
            pass
