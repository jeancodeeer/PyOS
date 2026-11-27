# Commands available at the >>> prompt.
#
# Each command is an ordinary Python function wrapped in Command, which also
# lets you use it DOS-style:
#
#   ls                         run it (typing just the name)
#   ls['/lib']                 run it with arguments, same as ls('/lib')
#   ls > '/disk/out.txt'       save its output to a file   (>> appends)
#   ls['/lib'] | find['boot']  feed its output to more / find / sort
#   help(ls)                   show how to use it
#
# Add your own with @command("summary", "usage") and they appear in `help`.
import builtins, gc, os, sys
import _kernel
from kernel import (VERSION, ata, console, editor, errors, history as hist, hw, irq, keyboard, lineedit,
                    log, mm, pci, pic, rtc, sched, status, thread, timer)

_commands = {}
_builtin_help = builtins.help
ALIAS_FILE = "/disk/aliases.py"


class _Done:
    """What a redirected or piped command evaluates to: prints nothing."""

    def __repr__(self):
        return ""


DONE = _Done()


def capture(fn, *args, **kwargs):
    """Run fn and return everything it printed, as text."""
    chunks = []
    old = _kernel.stdout_hook(chunks.append)
    try:
        fn(*args, **kwargs)
    finally:
        _kernel.stdout_hook(old)
    return str(b"".join(chunks), "utf8")


class Command:
    def __init__(self, fn, summary="", usage="", args=(), name=None):
        self.fn = fn
        self.name = name or fn.__name__
        self.summary = summary
        self.usage = usage
        self.args = args

    def __call__(self, *args, **kwargs):
        return self.fn(*(self.args + args), **kwargs)

    def __getitem__(self, args):
        if not isinstance(args, tuple):
            args = (args,)
        return Command(self.fn, self.summary, self.usage, self.args + args, self.name)

    def __repr__(self):
        result = self()
        return "" if result is None else repr(result)

    def _redirect(self, path, mode):
        text = capture(self)
        with open(path, mode) as f:
            f.write(text)
        return DONE

    def __gt__(self, path):
        return self._redirect(path, "w")

    def __rshift__(self, path):
        return self._redirect(path, "a")

    def __or__(self, other):
        text = capture(self)
        if not isinstance(other, Command):
            raise TypeError("can only pipe into a command, e.g.  ls | more")
        other(text=text)
        return DONE


def command(summary, usage=""):
    """Register a console command. The operating system on top of the
    kernel (SnakeyOS) adds its own commands this way from /etc/init.d."""
    def wrap(fn):
        cmd = Command(fn, summary, usage)
        _commands[cmd.name] = cmd
        if "__all__" in globals() and cmd.name not in __all__:
            __all__.append(cmd.name)        # registered after start-up: export it too
            globals()[cmd.name] = cmd       # MicroPython's import * copies module names, not __all__
        return cmd
    return wrap


def _register(name, cmd):
    """Make a command available at the prompt right away."""
    import __main__
    _commands[name] = cmd
    __main__.__dict__[name] = cmd


# ---- help ----

@command("list commands, or help(cmd) for one of them")
def help(*args):
    if args:
        target = args[0]
        if isinstance(target, Command):
            print("%s: %s" % (target.name, target.summary))
            if target.usage:
                print(target.usage)
            print("Also:  %s['arg']   %s > 'file'   %s >> 'file'   %s | more   %s | find['text']" % (
                (target.name,) * 5))
            return
        return _builtin_help(*args)
    print("PyKernel %s commands (type the name, or name['arg'] / name('arg')):" % VERSION)
    for name in sorted(_commands):
        print("  %-9s %s" % (name, _commands[name].summary))
    print("help(ls) explains one command. The kernel itself is Python: /lib/kernel.")


# ---- files ----

def _isdir(path):
    try:
        return bool(os.stat(path.rstrip("/") or "/")[0] & 0x4000)
    except OSError:
        return False


def _join(a, b):
    return b if b.startswith("/") else a.rstrip("/") + "/" + b


@command("list a directory", "ls  or  ls('/lib')")
def ls(path="."):
    print(" Directory of", os.getcwd() if path == "." else path)
    files = total = 0
    for name, kind, _, size in os.ilistdir(path):
        if kind & 0x4000:
            print("  %-10s %s" % ("<DIR>", name))
        else:
            print("  %10d %s" % (size, name))
            files += 1
            total += size
    print("  %d file(s), %d bytes" % (files, total))


@command("print a file", "cat('/autoexec.py')")
def cat(path=None):
    if path is None:
        print("usage: cat('path')")
        return
    with open(path) as f:
        while True:
            chunk = f.read(1024)
            if not chunk:
                break
            sys.stdout.write(chunk)


@command("show text a screen at a time", "more('/file')   or   ls | more     (space: next page, q: stop)")
def more(path=None, text=None):
    if text is None:
        if path is None:
            print("usage: more('path')  or  something | more")
            return
        with open(path) as f:
            text = f.read()
    height = console.ROWS - (console.current.top if console.current else 0) - 1
    lines = text.rstrip("\n").split("\n")
    for i, line in enumerate(lines):
        print(line)
        if (i + 1) % height == 0 and i + 1 < len(lines):
            sys.stdout.write("\x1b[7m-- more (%d%%) --\x1b[0m" % ((i + 1) * 100 // len(lines)))
            key = sys.stdin.read(1)
            sys.stdout.write("\r\x1b[K")
            if key in ("q", "Q", "\x03", "\x1b"):
                return


@command("search for text in files or piped output",
         "find('text', '/lib')   find('text', '/x.py')   ls | find['py']")
def find(pattern=None, path=".", text=None):
    if pattern is None:
        print("usage: find('text', path)")
        return
    if text is not None:
        for line in text.split("\n"):
            if pattern in line:
                print(line)
        return
    hits = 0
    for file in ([path] if not _isdir(path) else _walk(path)):
        try:
            with open(file) as f:
                for n, line in enumerate(f.read().split("\n"), 1):
                    if pattern in line:
                        print("%s:%d: %s" % (file, n, line.strip()))
                        hits += 1
        except Exception:                    # unreadable or binary file
            pass
    print("%d match(es)" % hits)


@command("sort piped lines", "ls | sort     ls | sort[True]  (reverse)")
def sort(reverse=False, text=None):
    if text is None:
        print("usage: something | sort")
        return
    for line in sorted(text.rstrip("\n").split("\n"), reverse=reverse):
        print(line)


def _walk(path):
    for name, kind, _, _ in os.ilistdir(path):
        full = _join(path, name)
        if kind & 0x4000:
            yield from _walk(full)
        else:
            yield full


@command("show a directory tree", "tree  or  tree('/lib')")
def tree(path=".", _prefix=""):
    if not _prefix:
        print(os.getcwd() if path == "." else path)
    entries = sorted(os.ilistdir(path), key=lambda e: (not e[1] & 0x4000, e[0]))
    for i, (name, kind, _, size) in enumerate(entries):
        last = i == len(entries) - 1
        if kind & 0x4000:
            print(_prefix + ("└── " if last else "├── ") + name + "/")
            tree(_join(path, name), _prefix + ("    " if last else "│   "))
        else:
            print(_prefix + ("└── " if last else "├── ") + "%s (%d)" % (name, size))


@command("copy a file", "copy('/a.py', '/disk/')   copy('/a.py', '/b.py')")
def copy(src=None, dst=None):
    if src is None or dst is None:
        print("usage: copy('from', 'to')")
        return
    if _isdir(dst):
        dst = _join(dst, src.rstrip("/").split("/")[-1])
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        while True:
            chunk = fin.read(4096)
            if not chunk:
                break
            fout.write(chunk)
    print("1 file copied to", dst)


@command("move or rename a file", "move('/a.py', '/disk/a.py')")
def move(src=None, dst=None):
    if src is None or dst is None:
        print("usage: move('from', 'to')")
        return
    if _isdir(dst):
        dst = _join(dst, src.rstrip("/").split("/")[-1])
    try:
        os.rename(src, dst)
    except OSError:                          # across filesystems: copy, then delete
        capture(copy, src, dst)
        os.remove(src)
    print("moved to", dst)


@command("change directory", "cd('/lib')")
def cd(path="/"):
    os.chdir(path)
    print(os.getcwd())


@command("print the current directory")
def pwd():
    print(os.getcwd())


@command("create a directory", "mkdir('/tmp')")
def mkdir(path=None):
    if path is None:
        print("usage: mkdir('path')")
    else:
        os.mkdir(path)


@command("delete a file or empty directory", "rm('/x.py')")
def rm(path=None):
    if path is None:
        print("usage: rm('path')")
    elif _isdir(path):
        os.rmdir(path)
    else:
        os.remove(path)


@command("write text to a file", "write('/x.py', 'print(1)')")
def write(path=None, text=""):
    if path is None:
        print("usage: write('path', 'text')")
        return
    with open(path, "w") as f:
        f.write(text)


@command("full-screen text editor",
         "edit('/disk/notes.py')\n"
         "  Ctrl+S save   Ctrl+Q quit   Ctrl+F find   Ctrl+G go to line\n"
         "  Ctrl+K cut line   Ctrl+U paste   (Ctrl+O / Ctrl+X / Ctrl+W also save / quit / find)")
def edit(path=None):
    if path is None:
        print("usage: edit('path')")
        return
    editor.Editor(path).run()


@command("run a Python file in this console", "run('/x.py')")
def run(path=None):
    if path is None:
        print("usage: run('path')")
        return
    import __main__
    with open(path) as f:
        source = f.read()
    try:
        exec(compile(source, path, "exec"), __main__.__dict__)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        errors.show(e, "%s failed:" % path)


# ---- system ----

@command("memory report")
def mem():
    info = _kernel.info()
    gc.collect()
    used, free = gc.mem_alloc(), gc.mem_free()
    print("RAM total     %8d KiB" % (mm.total_ram >> 10))
    print("kernel image  %8d KiB  at %#x" % ((info["kernel_end"] - info["kernel_start"]) >> 10, info["kernel_start"]))
    print("python heap   %8d KiB  (%d KiB used, %d KiB free)" % ((used + free) >> 10, used >> 10, free >> 10))
    print("free frames   %8d KiB  (mm.grow_heap(16) moves 16 MiB into the heap)" % (mm.free_bytes() >> 10))


@command("interrupt counters and handlers")
def irqs():
    for vector in range(256):
        n = irq.count(vector)
        fn = irq.handlers.get(vector)
        if n or fn:
            label = "irq %d" % (vector - pic.BASE) if pic.BASE <= vector < pic.BASE + 16 else ""
            print("  vector %3d %-7s %10d  %s" % (vector, label, n, getattr(fn, "__name__", "") if fn else "-"))
    if _kernel.irq_dropped():
        print("  dropped:", _kernel.irq_dropped())


@command("threads and background tasks")
def ps():
    print("   id  name              state    cpu-ticks  switches")
    for i, name, state, ticks, switches in thread.info():
        print("  %3d  %-16s  %-7s %10d %9d" % (i, name, state, ticks, switches))
    for t in sched.tasks:
        print("  t%-2d  %-16s  task    steps=%d" % (t.id, t.name, t.steps))


@command("stop a thread (ids from ps), or a task with kill('t3')", "kill(2)   kill('t3')")
def kill(tid=None):
    if tid is None:
        print("usage: kill(thread_id)  or  kill('t<task id>')")
    elif isinstance(tid, str) and tid.startswith("t"):
        if not sched.kill(int(tid[1:])):
            print("no task", tid)
    else:
        thread.kill(tid)


@command("kernel log: Rust boot messages and Python log entries", "dmesg   dmesg('warn')")
def dmesg(level="debug"):
    for line in log.lines(level):
        print(line)


@command("console command history (saved on the disk)", "history   history(50)")
def history(count=20):
    entries = _kernel.history()[:count]
    for n, entry in enumerate(reversed(entries), len(_kernel.history()) - len(entries) + 1):
        print("%4d  %s" % (n, entry.replace("\n", "\n      ")))


@command("keyboard layout: us, es, latam", "kbd('es')")
def kbd(name=None):
    if name is not None:
        if name not in keyboard.LAYOUTS:
            print("layouts:", ", ".join(sorted(keyboard.LAYOUTS)))
            return
        keyboard.layout(name)
    print("keyboard:", keyboard.current)


@command("list key bindings", "keys    (add with keyboard.bind('f2', fn))")
def keys():
    for name in keyboard.bindings():
        fn = keyboard._bindings[name]
        print("  %-14s %s" % (name, getattr(fn, "__name__", "?")))


@command("make a short name for a command (saved on the disk)",
         "alias('ll', 'ls', '/lib')   alias('ll')  removes it   alias  lists them")
def alias(name=None, target=None, *args):
    if name is None:
        for n, (t, a) in sorted(_aliases.items()):
            print("  %-9s %s%s" % (n, t, ("[%s]" % ", ".join(repr(x) for x in a)) if a else ""))
        return
    if target is None:
        if _aliases.pop(name, None) is not None:
            _commands.pop(name, None)
            _save_aliases()
        return
    base = _commands.get(target)
    if base is None:
        print("no command", target)
        return
    _aliases[name] = (target, args)
    _register(name, Command(base.fn, "alias for %s" % target, base.usage, base.args + args, name))
    _save_aliases()


_aliases = {}


def _save_aliases():
    try:
        with open(ALIAS_FILE, "w") as f:
            for name, (target, args) in sorted(_aliases.items()):
                f.write("alias(%r, %r%s)\n" % (name, target, "".join(", %r" % a for a in args)))
    except OSError:
        pass                                 # no disk: aliases last until reboot


def load_aliases():
    try:
        with open(ALIAS_FILE) as f:
            source = f.read()
    except OSError:
        return 0
    exec(source, {"alias": alias.fn})
    return len(_aliases)


@command("list PCI devices")
def lspci():
    for bus, dev, fn, vendor, device, cls, sub in pci.scan():
        print("  %02x:%02x.%d  %04x:%04x  %s (%02x%02x)" % (bus, dev, fn, vendor, device, pci.CLASSES.get(cls, "other"), cls, sub))


@command("date and time from the hardware clock")
def date():
    print("%04d-%02d-%02d %02d:%02d:%02d" % rtc.now())


@command("time since boot")
def uptime():
    s = timer.ms() // 1000
    print("up %d:%02d:%02d  (%d ticks at %d Hz)" % (s // 3600, s % 3600 // 60, s % 60, timer.ticks(), timer.HZ))


@command("clear the screen (or Ctrl+L)")
def cls():
    if console.current:
        console.current.clear()
    _kernel.serial_write(b"\x1b[2J\x1b[H")


@command("version information")
def ver():
    print("PyKernel %s on %s; MicroPython %s" % (VERSION, cpu_name(), ".".join(str(v) for v in sys.implementation[1][:3])))


@command("restart the machine (Ctrl-D restarts only the Python world)")
def reboot():
    from kernel import acpi
    acpi.reset()


@command("power off (ACPI S5 from the firmware tables)")
def poweroff():
    from kernel import acpi
    acpi.poweroff()
    print("power-off not supported here; halting")
    _kernel.irq_disable()
    _kernel.hlt()


@command("firmware tables: CPUs, interrupt controllers, power registers")
def acpi():
    from kernel import acpi as a
    if not a.tables:
        a.init()
    print(a.summary())


@command("local APIC, I/O APIC and HPET registers")
def apic():
    from kernel import apic as a
    print(a.summary())


@command("network card, address and counters")
def ifconfig():
    from kernel import net
    print(net.summary())


@command("send ICMP echo requests", "ping('10.0.2.2')   ping('example.com', 4)")
def ping(host=None, count=4):
    from kernel import net
    if host is None:
        print("usage: ping('host')")
        return
    if net.nic is None or not net.ip:
        net.up()
    addr = net.ntoa(net.resolve(host))
    print("PING %s (%s): 32 data bytes" % (host, addr))
    got = []
    for seq in range(1, count + 1):
        rtt = net.ping(addr, seq)
        if rtt is None:
            print("request %d timed out" % seq)
        else:
            got.append(rtt)
            print("reply from %s: seq=%d time=%d ms" % (addr, seq, rtt))
    print("%d sent, %d received%s" % (count, len(got), ", avg %d ms" % (sum(got) // len(got)) if got else ""))


@command("open TCP connections and listening ports")
def netstat():
    from kernel import net
    print(net.connections() or "no sockets")


@command("look a host name up in DNS", "nslookup('example.com')")
def nslookup(name=None):
    from kernel import net
    if name is None:
        print("usage: nslookup('name')")
        return
    if net.nic is None or not net.ip:
        net.up()
    print("%s -> %s" % (name, net.ntoa(net.resolve(name))))


@command("download a URL to a file (HTTP and HTTPS)", "wget('https://example.com/')   wget(url, '/disk/page.html')")
def wget(url=None, path=None):
    if url is None:
        print("usage: wget('http://host/path', 'file')")
        return
    from urllib import request
    import time
    t = time.ticks_ms()
    r = request.urlopen(url)
    data = r.read()
    if path is None:
        name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        path = name if "." in name and "/" not in name else "index.html"
    with open(path, "wb") as f:
        f.write(data)
    ms = max(1, time.ticks_ms() - t)
    print("%s: %d bytes in %d ms (%d KiB/s) -> %s" % (r.status, len(data), ms, len(data) * 1000 // ms >> 10, path))


@command("print what a URL returns", "curl('http://10.0.2.2:8000/')")
def curl(url=None, text=None):
    if url is None:
        print("usage: curl('http://host/path')")
        return
    from urllib import request
    print(request.urlopen(url).read().decode("utf-8", "replace"))


@command("processes: PID, parent, owner, state, command line")
def procs():
    from kernel import proc
    print(proc.listing())


@command("start a program as a new process", "start('/bin/hello.py', 'arg1')   start('top')")
def start(program=None, *args):
    from kernel import proc
    if program is None:
        print("usage: start('/path/program.py', args...)")
        return
    pid = proc.spawn(program, [program] + [str(a) for a in args])
    print("started pid", pid)


@command("send a signal to a process", "pkill(5)   pkill(5, 9)   (15 TERM, 9 KILL, 2 INT, 19 STOP, 18 CONT)")
def pkill(pid=None, sig=15):
    from kernel import proc
    if pid is None:
        print("usage: pkill(pid, signal=15)")
        return
    proc.kill(pid, sig)


@command("who you are logged in as")
def whoami():
    from kernel import users
    print(users.whoami())


@command("create a user account (root only)", "useradd('ana', 'secret')")
def useradd(name=None, password=""):
    from kernel import users
    if name is None:
        print("usage: useradd('name', 'password')")
        return
    users.require_root()
    print("user %s created, uid %d" % (name, users.useradd(name, password)))


@command("change a password", "passwd('ana', 'new secret')")
def passwd(name=None, password=None):
    from kernel import users
    name = name or users.whoami()
    if name != users.whoami():
        users.require_root()
    if password is None:
        from kernel import lineedit
        password = input("new password for %s: " % name)
    users.passwd(name, password)
    print("password updated")


@command("switch user", "su('ana')   su('root')")
def su(name="root", password=None):
    from kernel import users
    if password is None and users.accounts().get(name, {}).get("hash") and not users.is_root():
        password = input("password: ")
    if users.is_root():
        users.accounts()[name]                      # root may become anyone
        a = users.accounts()[name]
        from kernel import proc
        p = proc.current()
        p.uid = a["uid"]
        p.env.update(USER=name, HOME=a["home"])
        users.current_uid = a["uid"]
    else:
        users.login(name, password or "")
    print("now", name)


@command("boot services: list, or service('name', 'start'|'stop'|'restart')", "services   service('web', 'restart')")
def services():
    from kernel import services as sv
    sv.discover()
    print(sv.status())


@command("start, stop or restart a boot service", "service('web', 'stop')")
def service(name=None, action="status"):
    from kernel import services as sv
    sv.discover()
    if name is None:
        print(sv.status())
        return
    getattr(sv, action)(name) if action != "status" else print(sv.status())


@command("packages: pkg('install', name), pkg('remove', name), pkg('list'), pkg('search', text)",
         "pkg('install', 'pystone')   pkg('install', 'github:user/repo')")
def pkg(action="list", name=None):
    from kernel import pkg as p
    if action == "install":
        for f in p.install(name):
            print("  +", f)
    elif action == "remove":
        for f in p.remove(name):
            print("  -", f)
    elif action == "search":
        for n, v, d in p.search(name or ""):
            print("%-24s %-8s %s" % (n, v, d[:40]))
    else:
        for n, e in sorted(p.installed().items()):
            print("%-24s %-8s %s" % (n, e["version"], e["source"]))


@command("CPU cores: list them, or cpus('start') to wake the others", "cpus   cpus('start')")
def cpus(action=None):
    from kernel import smp
    if action == "start":
        print("woke %d core(s)" % smp.start_aps())
    print(smp.summary())


@command("serve a folder over HTTP in the background", "serve('/disk/www', 8080)")
def serve(root="/", port=80):
    from http import server
    server.serve(root, port)
    from kernel import net
    print("serving %s at http://%s:%d/" % (root, net.ntoa(net.ip), port))


@command("set the clock from the network (NTP)", "ntpdate   ntpdate('time.google.com')")
def ntpdate(server=None):
    from kernel import ntp
    delta = ntp.sync([server] if server else None)
    import time
    print("clock corrected by %+d s: %04d-%02d-%02d %02d:%02d:%02d UTC" % ((delta,) + time.gmtime()[:6]))


@command("devices and the driver that handles each one")
def lsdrv():
    from kernel import drivers
    for where, ids, cls, drv in drivers.table():
        print("  %s  %s  %-10s %s" % (where, ids, cls, ("%-11s %s" % (drv, drivers.WHAT.get(drv, ""))) if drv else "-"))
    for where, what, drv in drivers.legacy():
        print("  %-21s %-10s %-11s %s" % (where, what, drv, drivers.WHAT.get(drv, "")))
    try:
        from kernel import usb
        for d in usb.devices:
            print("  usb       ", d)
    except Exception:
        pass


@command("play a tone, a melody or a WAV file", "beep   beep(440, 500)   play('/share/sounds/arranque.wav')")
def beep(freq=880, ms=150):
    from kernel import sound
    if not sound.card and not sound.init():
        print("no sound card (QEMU: -device AC97)")
        return
    sound.beep(freq, ms)


@command("play a WAV file on the sound card", "play('/share/sounds/arranque.wav')")
def play(path=None):
    from kernel import sound
    if path is None:
        print("usage: play('file.wav')")
        return
    if not sound.card and not sound.init():
        print("no sound card (QEMU: -device AC97)")
        return
    sound.play_wav(path)


@command("mounted filesystems")
def mounts():
    print(open("/proc/mounts").read(), end="")


def cpu_name():
    from kernel.arch import ARM
    if ARM:
        from kernel import arch
        return arch.cpu_name()
    if _kernel.cpuid(0x80000000)[0] < 0x80000004:
        return "x86_64"
    raw = b"".join(reg.to_bytes(4, "little") for leaf in (0x80000002, 0x80000003, 0x80000004) for reg in _kernel.cpuid(leaf))
    return str(raw.rstrip(b"\x00"), "utf8").strip()


# Names handed to the console by `from kernel.shell import *`.
__all__ = list(_commands) + ["ata", "console", "editor", "errors", "lineedit", "hw", "irq", "keyboard", "log", "mm",
                             "pci", "pic", "rtc", "sched", "status", "thread", "timer",
                             "command", "capture"]
