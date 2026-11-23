"""Boot PyKernel headless in QEMU and exercise it.

Console I/O goes through the serial port; the QEMU monitor (multiplexed on
the same stream) is used to press keys on the emulated PS/2 keyboard and to
photograph the emulated screen.

    python tools/test.py
"""
import ast
import queue
import struct
import subprocess
import sys
import threading
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import mkfs  # noqa: E402
from run import host_path, make_disk, qemu_command  # noqa: E402

PROMPT = b">>> "
PROMPT_COLOUR = "\x1b[1;35m"


class Machine:
    def __init__(self, disk):
        cmd = qemu_command(["-display", "none", "-serial", "mon:stdio"], disk=disk)
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.q = queue.Queue()
        self.log = bytearray()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while True:
            b = self.proc.stdout.read(1)
            if not b:
                break
            self.q.put(b)

    def send(self, data: bytes):
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def until(self, marker: bytes, timeout=20.0) -> bytes:
        buf = bytearray()
        end = time.time() + timeout
        while marker not in buf:
            try:
                b = self.q.get(timeout=max(0.01, end - time.time()))
            except queue.Empty:
                raise TimeoutError(f"waiting for {marker!r}; got:\n{buf.decode(errors='replace')}")
            buf += b
            self.log += b
        return bytes(buf)

    def cmd(self, line: str, timeout=20.0) -> str:
        self.send(line.encode() + b"\r")
        out = self.until(PROMPT, timeout).decode(errors="replace")[: -len(PROMPT)]
        if out.endswith(PROMPT_COLOUR):         # the prompt is coloured, as in CPython 3.13
            out = out[: -len(PROMPT_COLOUR)]
        return out

    def monitor(self, *commands, pause=0.25):
        """Run QEMU monitor commands (Ctrl-A c switches the multiplexer)."""
        self.send(b"\x01c")
        self.until(b"(qemu)", 10)
        for c in commands:
            self.send(c.encode() + b"\r")
            time.sleep(pause)
        self.send(b"\x01c")
        time.sleep(0.2)

    def press(self, *keys):
        self.monitor(*("sendkey " + k for k in keys))

    def close(self):
        self.proc.kill()
        self.proc.wait()


def ppm_to_png(ppm: Path, png: Path):
    data = ppm.read_bytes()
    fields, pos = [], 0
    while len(fields) < 4:                      # P6, width, height, maxval
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        fields.append(data[pos:end])
        pos = end + 1
    w, h = int(fields[1]), int(fields[2])
    rows = b"".join(b"\x00" + data[pos + y * w * 3: pos + (y + 1) * w * 3] for y in range(h))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    png.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n      {detail!r}"))


def first_boot(m):
    boot = m.until(PROMPT, 60).decode(errors="replace")
    check("boots to a Python prompt", "PyKernel" in boot and "Python is the operating system" in boot, boot)
    check("blank disk is formatted and mounted", "mounted at /disk" in boot, boot)

    check("evaluates Python", "1267650600228229401496703205376" in m.cmd("2**100"))
    out = m.cmd("import math; 0.5 + 0.25, math.sqrt(2), math.sin(math.pi / 2), 10 / 4")
    check("floating point and math", "0.75" in out and "1.41421356" in out and "1.0" in out and "2.5" in out, out)
    out = m.cmd("ls('/lib/kernel')")
    check("root filesystem (Python RamFS) is mounted", "boot.py" in out and "console.py" in out, out)
    check("bare command names work (DOS style)", "python heap" in m.cmd("mem"), "")
    check("port I/O from Python (CMOS clock)", "20" in m.cmd("date"))
    out = m.cmd("lspci")
    check("PCI enumeration from Python", "8086:" in out, out)

    out = m.cmd("mm.translate(0xB8000), any('PyKernel' in r for r in console.current.text())")
    check("page-table walk + VGA console driver", "753664" in out and "True" in out, out)

    out = m.cmd("a = mm.alloc_frame(); mm.map_page(0x700000000000, a); "
                "hw.poke64(0x700000000000, 0xC0FFEE); hex(hw.peek64(a)), mm.translate(0x700000000000) == a")
    check("Python maps a new page and uses it", "0xc0ffee" in out and "True" in out, out)

    out = m.cmd("hw.peek64(0x700000100000)")
    check("CPU fault becomes a Python exception", "CPU fault 14" in out, out)
    check("... and the system survives it", "42" in m.cmd("6*7"))

    m.cmd("write('/t.py', 'import micropython\\n@micropython.viper\\ndef total(n: int) -> int:\\n"
          "    s = 0\\n    for i in range(n):\\n        s += i\\n    return s\\n')")
    out = m.cmd("run('/t.py'); total(1000000)", 60)
    check("files are writable; viper compiles Python to machine code", "499999500000" in out, out)

    m.cmd("write('/task.py', 'beats = 0\\ndef heart():\\n    global beats\\n    while True:\\n"
          "        beats += 1\\n        yield 20\\n')")
    m.cmd("run('/task.py'); t = sched.spawn(heart)")
    out = m.cmd("import time; time.sleep(0.5); beats, timer.ticks() > 20")
    beats = out.strip().splitlines()[-1] if out.strip() else ""
    check("timer interrupts drive background Python tasks", "True" in beats and not beats.startswith("(0,"), out)
    m.cmd("sched.kill(t.id)")

    m.send(b"while True: pass\r\r")
    time.sleep(1.0)
    m.send(b"\x03")
    out = m.until(PROMPT, 20).decode(errors="replace")
    check("Ctrl-C interrupts running Python (serial IRQ driver)", "KeyboardInterrupt" in out, out)

    out = m.cmd("mm.grow_heap(16); import gc; gc.mem_free() > 40 << 20")
    check("Python grows its own heap from free frames", "True" in out, out)

    # Preemptive threads: two that never yield, plus the console thread.
    m.cmd("write('/th.py', 'count = [0, 0]\\ndef spin(i):\\n    while True:\\n        count[i] += 1\\n')")
    m.cmd("run('/th.py'); thread.start(spin, 0); thread.start(spin, 1)")
    out = m.cmd("exec('for _ in range(300000): pass'); (count[0] > 1000, count[1] > 1000, len(_kernel.threads()))", 120)
    check("threads that never yield are preempted; console stays live", "(True, True, 3)" in out, out)
    out = m.cmd("ps")
    check("ps lists the threads", out.count("spin") == 2 and "main" in out, out)

    m.cmd("write('/sl.py', 'import time\\nnaps = [0]\\ndef napper():\\n    for _ in range(5):\\n"
          "        time.sleep_ms(50)\\n        naps[0] += 1\\n')")
    m.cmd("run('/sl.py'); thread.start(napper)")
    out = m.cmd("time.sleep(2); (naps[0], len(_kernel.threads()))", 60)
    check("a thread can sleep, finish and free its slot", "(5, 3)" in out, out)

    m.cmd("write('/lk.py', 'lock = thread.Lock()\\ntotal = [0]\\ndef add(n):\\n    for _ in range(n):\\n"
          "        with lock:\\n            total[0] += 1\\n')")
    m.cmd("run('/lk.py'); thread.start(add, 20000); thread.start(add, 20000)")
    out = m.cmd("exec('while len(_kernel.threads()) > 3: time.sleep_ms(50)'); total[0]", 180)
    check("locks keep a shared counter exact across threads", "40000" in out, out)

    m.cmd("write('/gc.py', 'def churn():\\n    while True:\\n        x = [bytearray(64) for _ in range(40)]\\n')")
    m.cmd("run('/gc.py'); thread.start(churn)")
    out = m.cmd("d = [str(i) * 8 for i in range(3000)]; x = [gc.collect() for _ in range(8)]; "
                "(d[2999], sum(len(v) for v in d))", 180)
    check("garbage collection is safe with threads running", "'29992999299929992999299929992999', 87120" in out, out)

    out = m.cmd("thread.start(lambda: 1 / 0, name='boom')")     # it may report before the prompt
    out += m.cmd("time.sleep_ms(500); 6 * 7", 60)
    check("an exception in a thread is reported, system carries on", "ZeroDivisionError" in out and "42" in out, out)

    out = m.cmd("exec('for i in range(100):\\n    thread.start(lambda: None)\\n    time.sleep_ms(20)'); len(_kernel.threads())", 120)
    check("100 short-lived threads come and go", out.strip().endswith("4"), out)

    # Real keyboard: type  k=6*7 <Enter>  then  K="Hi" <Enter>  on the PS/2 keyboard.
    m.cmd("cls")
    m.press("k", "equal", "6", "shift-8", "7", "ret")
    m.until(PROMPT, 20)
    m.press("shift-k", "equal", "shift-apostrophe", "shift-h", "i", "shift-apostrophe", "ret")
    m.until(PROMPT, 20)
    out = m.cmd("k, K")
    check("PS/2 keyboard driver types into the console", "(42, 'Hi')" in out, out)

    shot = ROOT / "build" / "screen.ppm"
    shot.unlink(missing_ok=True)
    m.monitor("screendump " + host_path(shot), pause=1.0)
    ok = shot.is_file() and shot.stat().st_size > 1000
    if ok:
        ppm_to_png(shot, ROOT / "build" / "screen.png")
    check("emulated screen captured (build/screen.png)", ok)

    terminal_features(m)
    keyboard_layouts(m)
    unicode_and_errors(m)
    disk_and_threads(m)
    interrupted_disk_work(m)
    line_editor(m)
    full_screen_editor(m)
    pygame_graphics(m)
    cpython_console(m)

    m.cmd("write('/disk/note.txt', 'written before power-off')")
    m.cmd("mkdir('/disk/lib'); write('/disk/lib/mymod.py', 'ANSWER = 6 * 7\\n')")
    m.cmd("write('/disk/autoexec.py', 'print(\"autoexec from disk ran\")\\n')")
    out = m.cmd("ata.disk.flush(); ls('/disk')")
    check("files can be written to the hard disk", "note.txt" in out, out)

    m.send(b"\x04")
    out = m.until(PROMPT, 60).decode(errors="replace")
    check("Ctrl-D soft-reboots the Python world", "Python is the operating system" in out, out)
    out = m.cmd("6*7, len(_kernel.threads())")
    check("... threads are gone and it works again afterwards", "(42, 1)" in out, out)


def terminal_features(m):
    m.send(b"uptim\t")
    time.sleep(0.5)
    m.send(b"\r")
    out = m.until(PROMPT, 20).decode(errors="replace")
    check("Tab completes names at the prompt", "up 0:" in out, out)

    out = m.cmd("c = console.current; c.write(b'\\x1b[91m'); a1 = c.attr; c.write(b'\\x1b[38;5;21m'); "
                "a2 = c.attr; c.write(b'\\x1b[0m'); (a1, a2)")
    check("bright and 256-colour ANSI codes", "(12, 9)" in out, out)
    out = m.cmd("c.write(b'\\x1b7'); p = (c.x, c.y); c.write(b'\\x1b[5;10H'); c.write(b'\\x1b8'); (c.x, c.y) == p")
    check("cursor save/restore (ESC 7 / ESC 8)", "True" in out, out)

    out = m.cmd("time.sleep_ms(1200); console.current.text()[0]")
    check("status bar shows time, uptime, memory, threads",
          "PyKernel" in out and "up " in out and "threads" in out, out)

    m.cmd("seen = []; keyboard.bind('f9', lambda: seen.append(console.current.offset))")
    m.cmd("exec(\"for i in range(60): print('line', i)\")")
    m.press("pgup", "f9", "pgdn", "f9")
    time.sleep(0.5)
    out = m.cmd("seen")
    check("PgUp/PgDn scroll back through earlier output; F-key bindings", "[23, 0]" in out, out)

    m.press("caps_lock")
    out = m.cmd("keyboard.caps, keyboard.leds")
    m.press("caps_lock")
    check("Caps Lock state and keyboard LEDs", "(True, 6)" in out, out)

    m.cmd("kbd('es')")
    m.press("s", "shift-0", "shift-2", "semicolon", "apostrophe", "a", "shift-2", "ret")
    m.until(PROMPT, 20)
    m.press("t", "shift-0", "shift-2", "alt_r-2", "shift-2", "ret")
    m.until(PROMPT, 20)
    out = m.cmd("s == 'ñá', t == '@', any('ñá' in r for r in console.current.text())")
    m.cmd("kbd('us')")
    check("Spanish layout: n-tilde, dead-key accents, AltGr, shown on screen", "(True, True, True)" in out, out)

    m.press("ctrl-l")
    m.until(PROMPT, 20)
    # (kept under 80 columns, so the line editor does not scroll it sideways)
    out = m.cmd("t = console.current.text(); 'kbd(' in str(t[2:]), t[1][4:7]")
    check("Ctrl+L clears the screen", out.strip().endswith("(False, 't =')"), out)

    out = m.cmd("write('/u.txt', 'alpha\\nbeta\\ngamma\\n'); copy('/u.txt', '/disk/')")
    check("copy", "copied" in out, out)
    out = m.cmd("find('beta', '/disk/u.txt')")
    check("find in files", "/disk/u.txt:2: beta" in out, out)
    m.cmd("ls['/lib/kernel'] > '/disk/ls.txt'")
    out = m.cmd("cat('/disk/ls.txt')")
    check("redirect output to a file (>)", "boot.py" in out and "Directory of /lib/kernel" in out, out)
    out = m.cmd("ls['/lib/kernel'] | find['boot']")
    check("pipe into find", "boot.py" in out and "console.py" not in out, out)
    out = m.cmd("cat['/u.txt'] | sort[True]")
    check("pipe into sort", 0 <= out.find("gamma") < out.find("beta") < out.find("alpha"), out)
    out = m.cmd("tree('/lib')")
    check("tree", "kernel/" in out and ("├── " in out or "└── " in out), out)
    out = m.cmd("move('/disk/u.txt', '/disk/v.txt'); ls('/disk')")
    listing = out.split("Directory of /disk")[-1]
    check("move", "v.txt" in listing and "u.txt" not in listing, out)
    out = m.cmd("help(copy)")
    check("help(command) shows usage", "copy: copy a file" in out and "copy('/a.py'" in out, out)

    m.cmd("alias('lk', 'ls', '/lib/kernel')")
    out = m.cmd("lk")
    check("aliases", "boot.py" in out, out)

    m.cmd("write('/bad.py', 'x = 1\\ndef f():\\n    return 1 / 0\\nf()\\n')")
    out = m.cmd("run('/bad.py')")
    check("errors show the failing source line", "ZeroDivisionError" in out and "> return 1 / 0" in out, out)

    m.cmd("victim = thread.start(spin, 0, name='victim')")
    out = m.cmd("time.sleep_ms(100); kill(victim); time.sleep_ms(200); victim in [t[0] for t in _kernel.threads()]")
    check("kill stops a thread that never yields", out.strip().endswith("False"), out)
    m.cmd("v2 = thread.start(spin, 1, name='v2')")
    out = m.cmd("time.sleep_ms(100); thread.interrupt(v2); time.sleep_ms(300); v2 in [t[0] for t in _kernel.threads()]")
    check("Ctrl-C for one thread (thread.interrupt)", "(v2) interrupted" in out and out.strip().endswith("False"), out)

    out = m.cmd("dmesg")
    check("dmesg shows Rust and Python log", "rust layer up" in out and "drivers up" in out, out)
    m.cmd("marker_7731 = 1")
    out = m.cmd("history(3)")
    check("history command", "marker_7731" in out, out)


# QEMU key names for PC scancodes (set 1)
QEMU_KEYS = {0x29: "grave_accent", 0x0C: "minus", 0x0D: "equal", 0x1A: "bracket_left",
             0x1B: "bracket_right", 0x27: "semicolon", 0x28: "apostrophe", 0x2B: "backslash",
             0x33: "comma", 0x34: "dot", 0x35: "slash", 0x56: "less", 0x39: "spc"}
QEMU_KEYS.update({0x02 + i: "1234567890"[i] for i in range(10)})
QEMU_KEYS.update({0x10 + i: "qwertyuiop"[i] for i in range(10)})
QEMU_KEYS.update({0x1E + i: "asdfghjkl"[i] for i in range(9)})
QEMU_KEYS.update({0x2C + i: "zxcvbnm"[i] for i in range(7)})


def generated_layouts():
    ns = {}
    exec((ROOT / "pyfs" / "lib" / "kernel" / "layouts.py").read_text(encoding="utf-8"), ns)
    return ns["LAYOUTS"]


def keyboard_layouts(m):
    """Press every key of every layout (normal, Shift, AltGr) on the emulated
    keyboard and compare what the driver produces with the X11-derived table."""
    for name, table in generated_layouts().items():
        presses, expected = [], []
        for code in sorted(table):
            if code == 0x39 or code not in QEMU_KEYS:
                continue
            key = QEMU_KEYS[code]
            normal, shifted, altgr, _ = table[code]
            for prefix, ch in (("", normal), ("shift-", shifted or normal), ("alt_r-", altgr)):
                if not ch:
                    continue
                presses.append(prefix + key)
                if ch.startswith("dead:"):
                    presses.append("spc")           # a dead key then space types the accent
                    ch = ch[5:]
                expected.append((prefix + key, ch))
        m.cmd("keyboard.layout(%r); keyboard.capture = []" % name)
        for i in range(0, len(presses), 40):
            m.monitor(*("sendkey %s 10" % k for k in presses[i:i + 40]), pause=0.03)
        time.sleep(1.0)
        out = m.cmd("[ord(c) for c in ''.join(keyboard.capture)]", 30)
        m.cmd("keyboard.capture = None; keyboard.layout('us')")
        try:
            got = [chr(n) for n in ast.literal_eval(out.strip().splitlines()[-1])]
        except (ValueError, SyntaxError, IndexError):
            got = []
        want = [ch for _, ch in expected]
        bad = [(k, w, g) for (k, w), g in zip(expected, got + [""] * len(want)) if w != g]
        check("layout %s: all %d key/level combinations match X11" % (name, len(want)),
              not bad and len(got) == len(want), (bad[:8], len(got), len(want)))

    # composing accents and Caps Lock on non-ASCII letters
    m.cmd("keyboard.layout('es'); keyboard.capture = []")
    m.press("apostrophe", "e", "shift-apostrophe", "u", "bracket_left", "a",
            "shift-bracket_left", "o", "alt_r-semicolon", "n", "caps_lock", "semicolon",
            "shift-semicolon", "caps_lock")
    time.sleep(0.5)
    out = m.cmd("[ord(c) for c in ''.join(keyboard.capture)]")
    m.cmd("keyboard.capture = None; keyboard.layout('latam'); keyboard.capture = []")
    m.press("bracket_left", "a", "alt_r-apostrophe", "e", "alt_r-2")
    time.sleep(0.5)
    out2 = m.cmd("[ord(c) for c in ''.join(keyboard.capture)]")
    m.cmd("keyboard.capture = None; keyboard.layout('us')")
    want = [ord(c) for c in "\u00e9\u00fc\u00e0\u00f4\u00f1\u00d1\u00f1"]
    want2 = [ord(c) for c in "\u00e1\u00ea@"]
    check("dead-key accents and Caps Lock on \u00f1 (es), accents and AltGr (latam)",
          str(want) in out and str(want2) in out2, (out, out2))
    out = m.cmd("_kernel.irq_lost(), _kernel.irq_dropped()")
    check("no keyboard bytes lost (interrupt-time FIFO)", out.strip().endswith("(0, 0)"), out)


def unicode_and_errors(m):
    # the line editor handles multi-byte characters as one character
    m.send('u = "\u00f1x'.encode() + b"\x7f" + '\u00f1"'.encode() + b"\r")
    m.until(PROMPT, 20)
    m.send('v = "\u00f1\u00e1'.encode() + b"\x1b[D" + b"x" + b"\x1b[F" + b'"\r')
    m.until(PROMPT, 20)
    out = m.cmd("u == '\u00f1\u00f1', v == '\u00f1x\u00e1', len(v), "
                "any(r.startswith('>' * 3 + ' v = \"\u00f1x\u00e1\"') for r in console.current.text())")
    check("typing, Backspace and arrows over accented letters (screen stays aligned)",
          "(True, True, 3, True)" in out, out)

    out = m.cmd("[1, 2][5]")
    check("errors at the prompt show the line that failed", "IndexError" in out and "> [1, 2][5]" in out, out)
    m.cmd("write('/e.py', 'def g():\\n    return {}[\"key\"]\\n')")
    out = m.cmd("run('/e.py'); g()")
    check("... and lines inside files called from the prompt",
          "KeyError" in out and "> return {}[\"key\"]" in out and "> run('/e.py'); g()" in out, out)


def disk_and_threads(m):
    m.cmd("write('/w.py', 'def writer(tag, n):\\n    for i in range(n):\\n        with open(\"/disk/w%s%d.txt\" % (tag, i), \"w\") as f:\\n"
          "            f.write(tag * 3000)\\n')")
    m.cmd("run('/w.py'); thread.start(writer, 'a', 12); thread.start(writer, 'b', 12)")
    out = m.cmd("exec('while len(_kernel.threads()) > 4: time.sleep_ms(50)'); "
                "all(open('/disk/w%s%d.txt' % (t, i)).read() == t * 3000 for t in 'ab' for i in range(12))", 300)
    check("two threads writing to the disk at once (FAT lock)", out.strip().endswith("True"), out)


def interrupted_disk_work(m):
    # A masked region runs to the end even if the thread is killed inside it.
    m.cmd("write('/mk.py', 'marks = []\\ndef guarded():\\n    _kernel.thread_mask(True)\\n"
          "    t = time.ticks_ms()\\n    while time.ticks_ms() - t < 400:\\n        pass\\n"
          "    marks.append(\"finished\")\\n    _kernel.thread_mask(False)\\n    marks.append(\"after\")\\n')")
    m.cmd("run('/mk.py')")
    out = m.cmd("g = thread.start(guarded, name='guarded'); time.sleep_ms(100); kill(g); time.sleep_ms(800); "
                "marks, g in [t[0] for t in _kernel.threads()]")
    check("kill waits for the end of a masked region", "(['finished'], False)" in out, out)

    # Kill threads in the middle of writing files, over and over: every file
    # is either complete or empty, and the filesystem keeps working.
    m.cmd("write('/kw.py', 'def kw(tag):\\n    i = 0\\n    while True:\\n"
          "        with open(\"/disk/k%s%d.txt\" % (tag, i % 4), \"w\") as f:\\n"
          "            f.write(str(i % 10) * 9000)\\n        i += 1\\n')")
    m.cmd("run('/kw.py')")
    for n, delay in enumerate((350, 620, 910, 1270)):
        m.cmd("v = thread.start(kw, %d, name='kw'); time.sleep_ms(%d); kill(v); time.sleep_ms(300)" % (n, delay), 60)
    out = m.cmd("import os; names = [n for n in os.listdir('/disk') if n.startswith('k')]; "
                "bad = [n for n in names if open('/disk/' + n).read() not in ('', open('/disk/' + n).read()[:1] * 9000)]; "
                "write('/disk/after.txt', 'still fine'); (len(names) >= 4, bad, open('/disk/after.txt').read(), "
                "len(_kernel.threads()))", 120)
    check("killing threads mid-write never leaves a half-written file", "(True, [], 'still fine'" in out, out)

    # An interrupt handler (a key binding) that uses the disk while the console
    # thread is busy with the disk: it waits its turn instead of failing.
    m.cmd("write('/f5.py', 'hits = []\\ndef on_f5():\\n    with open(\"/disk/f5.txt\", \"a\") as f:\\n"
          "        f.write(\"k\")\\n    hits.append(1)\\n')")
    m.cmd("run('/f5.py'); keyboard.bind('f5', on_f5)")
    m.send(b"exec('for i in range(60): write(\"/disk/busy%d.txt\" % (i % 3), \"z\" * 6000)')\r")
    time.sleep(0.5)
    m.press("f5", "f5", "f5", "f5")
    out = m.until(PROMPT, 120).decode(errors="replace")
    out += m.cmd("time.sleep_ms(500); len(hits), open('/disk/f5.txt').read()")
    check("disk use from an interrupt handler waits for the console's disk work (no EBUSY)",
          "(4, 'kkkk')" in out and "failed" not in out and "Errno 16" not in out, out)
    m.cmd("keyboard.unbind('f5')")


def line_editor(m):
    out = m.cmd("s = 'abc'  # note; x = None if s else 1")
    check("line editor colours strings, comments and keywords",
          "\x1b[92m'abc'" in out and "\x1b[90m# note" in out, out)
    out = m.cmd("y = None if 1 else 2")
    check("... keywords and numbers", "\x1b[96mif" in out and "\x1b[95m1" in out, out)

    m.cmd("print('found' + '_it')")
    m.cmd("1 + 1")
    m.send(b"\x12found' +\r")                   # Ctrl-R, type part of the line, Enter
    out = m.until(b"found_it\r\n", 20).decode(errors="replace")   # (the prompt is redrawn first)
    m.until(PROMPT, 20)
    check("Ctrl-R finds an earlier line and runs it", "(search)" in out and "found_it" in out, out)

    m.cmd("21 * 2")
    m.send(b"\x1b[A\r")                          # Up arrow, Enter
    out = m.until(PROMPT, 20).decode(errors="replace")
    check("Up arrow recalls the previous line", "42" in out, out)

    m.send(b"def af():\r")
    m.until(b"... ", 10)
    m.send(b"return 5\r")                        # indented automatically
    m.until(b"... ", 10)
    m.send(b"\r")
    m.until(PROMPT, 10)
    out = m.cmd("af()")
    check("blocks are indented automatically", "5" in out and "Error" not in out, out)


def full_screen_editor(m):
    m.cmd("marker_before_edit = 1")
    m.send(b"edit('/disk/ed.py')\r")
    m.until(b"new file", 20)
    # def g():  / (auto-indent) return 41 / (Backspace dedents) print(...) / junk  ^K cuts it
    m.send(b"def g():\rreturn 41\r\x7fprint(g() + 1)\rjunk = 1\x0b")
    m.send(b"\x06return\r")                      # Ctrl-F: find
    out = m.until(b"Ln 2/", 20).decode(errors="replace")
    m.send(b"\x13")                              # Ctrl-S
    out += m.until(b"saved 3 lines", 20).decode(errors="replace")
    m.send(b"\x11")                              # Ctrl-Q
    out += m.until(PROMPT, 20).decode(errors="replace")
    check("full-screen editor: type, auto-indent, cut, find, save", "\x1b[96mdef" in out, out)
    out = m.cmd("run('/disk/ed.py'); 'junk' in open('/disk/ed.py').read()")
    check("... the saved file runs", "42" in out and "False" in out, out)
    out = m.cmd("any('marker_before_edit' in r for r in console.current.text())")
    check("... and the screen is restored afterwards", "True" in out, out)

    m.send(b"edit('/disk/ed.py')\r")
    m.until(b"Ln 1/3", 20)
    m.send(b"zzz\x11")
    m.until(b"unsaved changes", 20)
    m.send(b"\x11")
    m.until(PROMPT, 20)
    out = m.cmd("'zzz' in open('/disk/ed.py').read()")
    check("... quitting asks before throwing away changes", "False" in out, out)


def cpython_console(m):
    """The prompt behaves like CPython's interactive interpreter (3.13)."""
    boot = m.log.decode(errors="replace")
    check("console banner as in CPython",
          'Type "help", "copyright", "credits" or "license" for more information.' in boot
          and "Python 3." in boot, boot[-400:])
    m.cmd("globals().pop('_', None)")           # a variable named _ would hide the result
    m.cmd("6 * 7")
    out = m.cmd("_ + 1")
    check("_ holds the last result", "43" in out, out)
    out = m.cmd("1 / 0")
    check("errors: traceback, source line, coloured exception",
          "Traceback (most recent call last)" in out and "\x1b[1;35mZeroDivisionError" in out, out)
    out = m.cmd("exit", 60)                     # returns at the prompt after the reboot
    out2 = m.cmd("copyright")
    check("exit without parentheses leaves the interpreter (soft reboot); copyright",
          "soft reboot" in out and "Copyright" in out2, (out, out2))
    m.send(b"abc\x03")
    out = m.until(PROMPT, 20).decode(errors="replace")
    check("Ctrl-C at the prompt: KeyboardInterrupt", "KeyboardInterrupt" in out, out)

    m.send(b"for i in range(2):\r")
    m.until(b"... ", 10)
    m.send(b"print('blk', i * 11)\r")
    m.until(b"... ", 10)
    m.send(b"\r")
    m.until(PROMPT, 10)
    m.send(b"\x1b[A")                            # Up: the whole block comes back
    time.sleep(0.5)
    m.send(b"\r")                                # Enter at its end opens a new line...
    m.until(b"... ", 10)
    m.send(b"\r")                                # ... a blank line runs it again
    out = m.until(PROMPT, 10).decode(errors="replace")
    check("a whole block is recalled with Up and runs again", "blk 11" in out, out)

    m.send(b"import sys; sys.ps1 = 'py> '\r")
    m.until(b"py> ", 10)
    m.send(b"sys.ps1 = '>>> '\r")
    m.until(PROMPT, 10)
    check("sys.ps1 changes the prompt", True)

    m.send(b"\x1bOR")                            # F3: paste mode
    m.until(b"(paste) ", 10)
    m.send(b"pa = 4\r")
    m.until(b"(paste) ", 10)
    m.send(b"if pa:\r")
    m.until(b"(paste) ", 10)
    m.send(b"  pb = pa * 5\r")
    m.until(b"(paste) ", 10)
    m.send(b"\x1bOR")
    m.until(PROMPT, 10)
    out = m.cmd("pb")
    check("F3 paste mode runs lines exactly as pasted", "20" in out, out)

    m.send(b"\x1bOP")                            # F1: interactive help
    m.until(b"help> ", 10)
    m.send(b"copy\r")
    out = m.until(b"help> ", 10).decode(errors="replace")
    m.send(b"q\r")
    m.until(PROMPT, 10)
    check("F1 interactive help", "copy: copy a file" in out, out)


PG_SCRIPT = (
    "import pygame\n"
    "pygame.init()\n"
    "screen = pygame.display.set_mode((640, 480))\n"
    "font = pygame.font.SysFont(None, 48)\n"
    "keys, clicks, frames = [], [], 0\n"
    "clock = pygame.time.Clock()\n"
    "t0 = pygame.time.get_ticks()\n"
    "running = True\n"
    "while running and pygame.time.get_ticks() - t0 < 20000:\n"
    "    for ev in pygame.event.get():\n"
    "        if ev.type == pygame.QUIT:\n"
    "            running = False\n"
    "        elif ev.type == pygame.KEYDOWN:\n"
    "            keys.append(pygame.key.name(ev.key))\n"
    "        elif ev.type == pygame.MOUSEBUTTONDOWN:\n"
    "            clicks.append((ev.button, ev.pos))\n"
    "    screen.fill((0, 0, 128))\n"
    "    pygame.draw.circle(screen, (255, 255, 0), (320, 240), 60)\n"
    "    pygame.draw.rect(screen, (255, 0, 0), (20, 380, 100, 80))\n"
    "    screen.blit(font.render('PyKernel', True, (255, 255, 255)), (20, 20))\n"
    "    pygame.display.flip()\n"
    "    if frames == 2:\n"
    "        print('PG' + 'READY')\n"
    "    frames += 1\n"
    "    clock.tick(30)\n"
    "pygame.quit()\n"
)


def _ppm_pixel(path, x, y):
    data = path.read_bytes()
    fields, pos = [], 0
    while len(fields) < 4:
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        fields.append(data[pos:end])
        pos = end + 1
    w = int(fields[1])
    i = pos + (y * w + x) * 3
    return tuple(data[i:i + 3])


def pygame_graphics(m):
    shot = ROOT / "build" / "pygame.ppm"
    if shot.exists():
        shot.unlink()
    m.cmd("write('/pg.py', %r)" % PG_SCRIPT)
    m.send(b"run('/pg.py')\r")
    m.until(b"PGREADY", 60)                     # importing pygame the first time takes a while
    m.press("a", "up")
    m.monitor("mouse_move 50 40", "mouse_button 1", "mouse_button 0")
    time.sleep(1)
    m.monitor("screendump " + host_path(shot), pause=1.0)
    ok = shot.is_file()
    pixels = (_ppm_pixel(shot, 320, 240), _ppm_pixel(shot, 60, 420), _ppm_pixel(shot, 600, 100)) if ok else None
    if ok:
        ppm_to_png(shot, ROOT / "build" / "pygame.png")
    check("pygame draws on the screen (build/pygame.png)",
          pixels == ((255, 255, 0), (255, 0, 0), (0, 0, 128)), pixels)
    m.press("ctrl-q")                            # no window to close: Ctrl+Q posts QUIT
    m.until(PROMPT, 40)
    out = m.cmd("pg = __import__('__main__'); keys, clicks, frames > 30")
    check("pygame events: keys, mouse button with position, QUIT; frame clock",
          "['a', 'up'" in out and "(1, (50, 40))" in out and "True" in out, out)
    out = m.cmd("from kernel import video; video.current, any('pg.py' in r for r in console.current.text())")
    check("... and the text console comes back afterwards", "(None, True)" in out, out)
    m.monitor("screendump " + host_path(shot), pause=1.0)
    ok = shot.is_file() and shot.stat().st_size < 900000      # 720x400 text, not 640x480
    check("... in real text mode again", ok, shot.stat().st_size if shot.is_file() else None)


def second_boot(m):
    boot = m.until(PROMPT, 60).decode(errors="replace")
    check("after power-off: disk autoexec.py runs at boot", "autoexec from disk ran" in boot, boot)
    out = m.cmd("cat('/disk/note.txt')")
    check("after power-off: file contents are still there", "written before power-off" in out, out)
    out = m.cmd("import mymod; mymod.ANSWER")
    check("after power-off: modules import from /disk/lib", "42" in out, out)
    out = m.cmd("any(('marker' + '_7731') in h for h in _kernel.history())")
    check("after power-off: command history restored", "True" in out, out)
    out = m.cmd("lk")
    check("after power-off: aliases restored", "boot.py" in out, out)


def main():
    mkfs.pack(ROOT / "pyfs", ROOT / "build" / "pyfs.img")
    disk = make_disk(ROOT / "build" / "test-disk.img", fresh=True)
    log = bytearray()
    for stage in (first_boot, second_boot):
        m = Machine(disk)
        try:
            stage(m)
        except TimeoutError as e:
            check("no timeout in " + stage.__name__, False, str(e))
        finally:
            m.close()
            log += m.log + b"\n\n===== machine powered off =====\n\n"
    (ROOT / "build" / "test.log").write_bytes(bytes(log))
    print(f"\n{sum(CHECKS)}/{len(CHECKS)} checks passed (transcript: build/test.log)")
    return 0 if all(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
