# Processes: programs with a PID, a parent, arguments, environment, a
# working directory, an owner, open files, signals and an exit code.
#
#   pid = proc.spawn('/bin/hello.py', ['hello', 'world'])
#   proc.wait(pid)            -> exit status
#   proc.kill(pid, proc.SIGTERM)
#
# Each process runs in its own preemptive thread with its own globals: a
# program sees `__name__ == '__main__'`, `sys.argv` and `os.environ` of its
# own (through proc.current()). It also gets a private mm.AddressSpace for
# memory it asks for with proc.current().alloc(). What it does NOT get is
# hardware isolation: every process is Python in the same VM, at ring 0.
import sys
import _thread
import _kernel
from kernel import thread, timer, log

SIGHUP, SIGINT, SIGKILL, SIGUSR1, SIGUSR2, SIGTERM, SIGCHLD, SIGCONT, SIGSTOP = 1, 2, 9, 10, 12, 15, 17, 18, 19
NAMES = {1: "SIGHUP", 2: "SIGINT", 9: "SIGKILL", 10: "SIGUSR1", 12: "SIGUSR2", 15: "SIGTERM", 17: "SIGCHLD",
         18: "SIGCONT", 19: "SIGSTOP"}
RUNNING, SLEEPING, STOPPED, ZOMBIE = "R", "S", "T", "Z"

table = {}            # pid -> Process
_by_thread = {}       # thread id -> Process
_next_pid = 1


class Exit(BaseException):
    """Raised by proc.exit(code) to end the current process."""


class Process:
    def __init__(self, name, argv, env, cwd, uid, parent):
        global _next_pid
        self.pid = _next_pid
        _next_pid += 1
        self.name, self.argv = name, list(argv)
        self.env = dict(env)
        self.cwd = cwd
        self.uid = uid
        self.ppid = parent.pid if parent else 0
        self.state = RUNNING
        self.status = None
        self.started = timer.ms()
        self.tid = None
        self.handlers = {}
        self.pending = []
        self.fds = {0: sys.stdin, 1: sys.stdout, 2: sys.stderr}
        self.space = None
        self.children_done = []
        self.globals = {}
        table[self.pid] = self

    # -- memory --
    def alloc(self, size):
        """Private memory for this process: returns its virtual address."""
        from kernel import mm
        if self.space is None:
            self.space = mm.AddressSpace(self.name)
            self.brk = mm.USER_BASE
        addr = self.brk
        self.space.map(addr, size)
        self.brk += (size + mm.PAGE - 1) & ~(mm.PAGE - 1)
        return addr

    # -- files --
    def open(self, path, mode="r"):
        f = open(path, mode)
        fd = 3
        while fd in self.fds:
            fd += 1
        self.fds[fd] = f
        return fd

    def close(self, fd):
        f = self.fds.pop(fd, None)
        if f is not None and fd > 2:
            f.close()

    def status_text(self):
        from kernel import users
        return ("Name:\t%s\nState:\t%s\nPid:\t%d\nPPid:\t%d\nUid:\t%d (%s)\nThread:\t%s\nUptime:\t%d ms\n"
                "Cwd:\t%s\nFds:\t%s\nMemory:\t%d kB\n" % (
                    self.name, self.state, self.pid, self.ppid, self.uid, users.name_of(self.uid), self.tid,
                    timer.ms() - self.started, self.cwd, " ".join(str(k) for k in sorted(self.fds)),
                    (self.space.resident() >> 10) if self.space else 0))

    def __repr__(self):
        return "<Process %d %s %s>" % (self.pid, self.name, self.state)


def _init_process():
    p = Process("init", ["init"], {"PATH": "/bin:/disk/bin", "HOME": "/", "USER": "root", "SHELL": "python"},
                "/", 0, None)
    p.tid = 0
    _by_thread[0] = p
    return p


init = _init_process()


def current():
    """The process the calling thread belongs to (the console is init/shell)."""
    return _by_thread.get(_thread.get_ident(), init)


def _find_program(path):
    if "/" in path:
        return path
    for d in current().env.get("PATH", "/bin").split(":"):
        for candidate in (d + "/" + path, d + "/" + path + ".py"):
            try:
                open(candidate).close()
                return candidate
            except OSError:
                pass
    raise OSError(2, "command not found: " + path)


def spawn(program, argv=None, env=None, cwd=None, source=None, name=None, fn=None, uid=None):
    """Start a process. `program` is a path (searched in $PATH), or pass
    `fn` (a Python function) or `source` (code text). Returns the PID."""
    parent = current()
    path = None
    if fn is None and source is None:
        path = _find_program(program)
        with open(path) as f:
            source = f.read()
    argv = list(argv) if argv else [program or getattr(fn, "__name__", "?")]
    p = Process(name or (path or program or "process").rsplit("/", 1)[-1], argv,
                env if env is not None else parent.env, cwd or parent.cwd,
                parent.uid if uid is None else uid, parent)

    def body():
        me = _thread.get_ident()
        p.tid = me
        _by_thread[me] = p
        code = 0
        try:
            if fn is not None:
                r = fn(*argv[1:])
                code = r if isinstance(r, int) else 0
            else:
                p.globals.update(__name__="__main__", __file__=path or "<string>")
                exec(compile(source, path or "<string>", "exec"), p.globals)
        except Exit as e:
            code = e.args[0] if e.args else 0
        except SystemExit as e:
            code = e.args[0] if e.args and isinstance(e.args[0], int) else (0 if not e.args else 1)
        except KeyboardInterrupt:
            code = 128 + SIGINT
        except Exception as e:
            from kernel import errors
            errors.show(e, "process %d (%s) crashed:" % (p.pid, p.name))
            code = 1
        finally:
            _finish(p, code)

    thread.start(body, name="%s[%d]" % (p.name, p.pid))
    deadline = timer.ms() + 1000
    while p.tid is None and timer.ms() < deadline:
        _kernel.wait()
    return p.pid


def _finish(p, code):
    if p.status is None:
        p.status = code
    p.state = ZOMBIE
    _by_thread.pop(p.tid, None)
    for fd in list(p.fds):
        if fd > 2:
            try:
                p.close(fd)
            except Exception:
                pass
    if p.space is not None:
        p.space.destroy()
        p.space = None
    parent = table.get(p.ppid)
    if parent is not None:
        parent.children_done.append(p.pid)
        _deliver(parent, SIGCHLD)
    for child in table.values():          # orphans go to init
        if child.ppid == p.pid:
            child.ppid = init.pid
    if parent is None or parent is init and SIGCHLD not in init.handlers:
        pass                              # reaped by wait() or by ps listing later


def exit(code=0):
    raise Exit(code)


def wait(pid=None, timeout_ms=None):
    """Wait for a child to end; returns its exit status and removes it."""
    me = current()
    deadline = None if timeout_ms is None else timer.ms() + timeout_ms
    while True:
        candidates = [p for p in table.values() if p.ppid == me.pid and (pid is None or p.pid == pid)]
        if pid is not None and pid in table and table[pid].ppid != me.pid and table[pid].state == ZOMBIE:
            candidates = [table[pid]]
        if not candidates:
            raise OSError(10, "no such child")             # ECHILD
        for p in candidates:
            if p.state == ZOMBIE:
                del table[p.pid]
                return p.status
        if deadline is not None and timer.ms() > deadline:
            return None
        _kernel.wait()


def _deliver(p, sig):
    handler = p.handlers.get(sig)
    if handler is None or handler == 0:            # SIG_DFL
        return False
    if handler == 1:                               # SIG_IGN
        return True
    import micropython
    try:
        micropython.schedule(lambda _: handler(sig, None), None)
    except RuntimeError:
        p.pending.append(sig)
    return True


def kill(pid, sig=SIGTERM):
    p = table.get(pid)
    if p is None or p.state == ZOMBIE:
        raise OSError(3, "no such process")         # ESRCH
    if p is init:
        raise OSError(1, "init cannot be signalled")
    if sig == SIGKILL:
        p.status = 128 + sig
        thread.kill(p.tid)
        return
    if sig == SIGSTOP:
        p.state = STOPPED
        return
    if sig == SIGCONT:
        p.state = RUNNING
        return
    if _deliver(p, sig):
        return
    if sig in (SIGTERM, SIGHUP, SIGINT, SIGUSR1, SIGUSR2):
        p.status = 128 + sig
        if sig == SIGINT:
            thread.interrupt(p.tid)
        else:
            thread.kill(p.tid)


def signal(sig, handler):
    """Install handler(sig, frame) for the current process; returns the old one."""
    if sig in (SIGKILL, SIGSTOP):
        raise ValueError("SIGKILL and SIGSTOP cannot be caught")
    p = current()
    old = p.handlers.get(sig, 0)
    p.handlers[sig] = handler
    return old


def listing():
    from kernel import users
    rows = ["  PID  PPID USER     S   TIME  COMMAND"]
    for p in sorted(table.values(), key=lambda p: p.pid):
        secs = (timer.ms() - p.started) // 1000
        rows.append("%5d %5d %-8s %s %3d:%02d  %s" % (p.pid, p.ppid, users.name_of(p.uid)[:8], p.state,
                                                    secs // 60, secs % 60, " ".join(p.argv)))
    return "\n".join(rows)
