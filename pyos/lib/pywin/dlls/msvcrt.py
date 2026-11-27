# msvcrt.dll: the C library (printf, malloc, fopen, strlen...), plus the
# start-up functions that compilers put before main().
import math
from pywin import mem, cformat
from pywin.dlls import Dll

dll = Dll("msvcrt")
FILE_SIZE = 48
EOF = 0xFFFFFFFF


def _i32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


def _i64(v):
    return v - (1 << 64) if v >> 63 else v


def _text(data):
    try:
        return data.decode()
    except UnicodeError:
        return "".join(chr(b) for b in data)


# ---- FILE* streams ----
# A FILE* the program holds is a small block of its memory; Python keeps the
# real stream for each one in p.state["files"].

class Stream:
    def __init__(self, p, kind, f=None):
        self.p, self.kind, self.f = p, kind, f      # kind: "out", "in" or "file"
        self.pending = b""                           # console input not read yet
        self.eof = False

    def write(self, data):
        if self.kind == "out":
            self.p.ui.write(_text(data))
        elif self.kind == "file":
            self.f.write(data)
        return len(data)

    def _fill(self):
        if self.kind == "in" and not self.pending and not self.eof:
            line = self.p.ui.read_line()
            if not line:
                self.eof = True
            self.pending = line.encode()

    def read(self, n):
        if self.kind == "file":
            data = self.f.read(n)
            self.eof = len(data) < n
            return data
        out = b""
        while len(out) < n:
            self._fill()
            if not self.pending:
                break
            take = self.pending[:n - len(out)]
            self.pending = self.pending[len(take):]
            out += take
            if out.endswith(b"\n"):
                break
        return out

    def getc(self):
        if self.kind == "file":
            b = self.f.read(1)
            if not b:
                self.eof = True
                return EOF
            return b[0]
        self._fill()
        if not self.pending:
            return EOF
        c, self.pending = self.pending[0], self.pending[1:]
        return c

    def ungetc(self, c):
        if self.kind == "file":
            self.f.seek(-1, 1)
        else:
            self.pending = bytes([c]) + self.pending

    def readline(self, limit):
        if self.kind == "file":
            line = self.f.readline()
            if len(line) > limit:
                self.f.seek(len(line[limit:]) * -1, 1)
                line = line[:limit]
            if not line:
                self.eof = True
            return line
        self._fill()
        k = self.pending.find(b"\n")
        k = len(self.pending) if k < 0 else k + 1
        k = min(k, limit)
        line, self.pending = self.pending[:k], self.pending[k:]
        return line

    def close(self):
        if self.f:
            self.f.close()


def _files(p):
    if "files" not in p.state:
        iob = p.bound.get(("msvcrt", "_iob")) or p.heap.alloc(FILE_SIZE * 3)
        p.state["iob"] = iob
        p.state["files"] = {iob: Stream(p, "in"), iob + FILE_SIZE: Stream(p, "out"),
                            iob + 2 * FILE_SIZE: Stream(p, "out")}
    return p.state["files"]


def _stream(p, fp):
    return _files(p).get(fp)


@dll(0)
def __iob_func(p):
    _files(p)
    return p.state["iob"]


@dll(1)
def __acrt_iob_func(p, n):
    _files(p)
    return p.state["iob"] + FILE_SIZE * n


@dll(2)
def fopen(p, name, mode):
    return _open(p, mem.cstr(name), mem.cstr(mode))


@dll(2)
def _wfopen(p, name, mode):
    return _open(p, mem.wstr(name), mem.wstr(mode))


def _open(p, name, mode):
    m = mode.replace("t", "").replace("b", "").replace("c", "").replace("n", "")
    m = {"r": "rb", "w": "wb", "a": "ab", "r+": "r+b", "w+": "w+b", "a+": "a+b"}.get(m, "rb")
    try:
        f = open(p.host_path(name, write=m != "rb"), m)
    except OSError:
        p.state["errno"] = 2
        return 0
    fp = p.heap.alloc(FILE_SIZE)
    _files(p)[fp] = Stream(p, "file", f)
    return fp


@dll(3)
def fopen_s(p, out, name, mode):
    fp = fopen(p, name, mode)
    mem.put64(out, fp)
    return 0 if fp else 2


@dll(1)
def fclose(p, fp):
    s = _files(p).pop(fp, None)
    if s is None:
        return EOF
    s.close()
    p.heap.free(fp)
    return 0


@dll(1)
def fflush(p, fp):
    return 0


@dll(4)
def fwrite(p, buf, size, n, fp):
    s = _stream(p, fp)
    if not s or not size:
        return 0
    s.write(mem.read(buf, size * n))
    return n


@dll(4)
def fread(p, buf, size, n, fp):
    s = _stream(p, fp)
    if not s or not size:
        return 0
    data = s.read(size * n)
    mem.write(buf, data)
    return len(data) // size


@dll(2)
def fputc(p, c, fp):
    s = _stream(p, fp)
    if not s:
        return EOF
    s.write(bytes([c & 255]))
    return c & 255


dll.alias("putc", "fputc")
dll.alias("_fputc_nolock", "fputc")


@dll(2)
def fputs(p, text, fp):
    s = _stream(p, fp)
    if not s:
        return EOF
    s.write(mem.cbytes(text))
    return 0


@dll(1)
def puts(p, text):
    _out(p, mem.cbytes(text) + b"\n")
    return 0


@dll(1)
def putchar(p, c):
    _out(p, bytes([c & 255]))
    return c & 255


def _out(p, data):
    _files(p)[p.state["iob"] + FILE_SIZE].write(data)


@dll(1)
def fgetc(p, fp):
    s = _stream(p, fp)
    return s.getc() if s else EOF


dll.alias("getc", "fgetc")


@dll(2)
def ungetc(p, c, fp):
    s = _stream(p, fp)
    if s and _i32(c) != -1:
        s.ungetc(c & 255)
    return c


@dll(0)
def getchar(p):
    return _files(p)[p.state["iob"]].getc()


@dll(0)
def _getch(p):
    return getchar(p)


dll.alias("_getche", "_getch")


@dll(0)
def _kbhit(p):
    return 0


@dll(3)
def fgets(p, buf, n, fp):
    s = _stream(p, fp)
    if not s or n <= 1:
        return 0
    line = s.readline(n - 1)
    if not line:
        return 0
    mem.write(buf, line + b"\0")
    return buf


@dll(1)
def gets(p, buf):
    line = _files(p)[p.state["iob"]].readline(1 << 16)
    if not line:
        return 0
    mem.write(buf, line.rstrip(b"\n") + b"\0")
    return buf


@dll(1)
def feof(p, fp):
    s = _stream(p, fp)
    return 1 if s and s.eof else 0


@dll(1)
def ferror(p, fp):
    return 0


@dll(1)
def clearerr(p, fp):
    s = _stream(p, fp)
    if s:
        s.eof = False


@dll(3)
def fseek(p, fp, offset, whence):
    s = _stream(p, fp)
    if not s or not s.f:
        return -1
    s.f.seek(_i32(offset), whence)
    s.eof = False
    return 0


dll.alias("_fseeki64", "fseek")


@dll(1)
def ftell(p, fp):
    s = _stream(p, fp)
    return s.f.tell() if s and s.f else 0


dll.alias("_ftelli64", "ftell")


@dll(1)
def rewind(p, fp):
    fseek(p, fp, 0, 0)


@dll(4)
def setvbuf(p, fp, buf, mode, size):
    return 0


@dll(2)
def setbuf(p, fp, buf):
    pass


@dll(1)
def _fileno(p, fp):
    return (fp - p.state.get("iob", 0)) // FILE_SIZE if fp in _files(p) else 3


@dll(2)
def _setmode(p, fd, mode):
    return 0x4000                                 # it was text mode


@dll(1)
def _isatty(p, fd):
    return 1 if fd < 3 else 0


@dll(3)
def _write(p, fd, buf, n):
    if fd in (1, 2):
        _out(p, mem.read(buf, n))
    return n


@dll(1)
def remove(p, name):
    import os
    try:
        os.remove(p.host_path(mem.cstr(name), write=True))
        return 0
    except OSError:
        return -1


dll.alias("_unlink", "remove")


@dll(2)
def rename(p, old, new):
    import os
    try:
        os.rename(p.host_path(mem.cstr(old), write=True), p.host_path(mem.cstr(new), write=True))
        return 0
    except OSError:
        return -1


# ---- printf and scanf ----

def _fmt(p, fmt, first=None, va=None):
    return cformat.printf(mem.cbytes(fmt), cformat.Args(p, first, va))


@dll(1)
def printf(p, fmt):
    data = _fmt(p, fmt, first=1)
    _out(p, data)
    return len(data)


@dll(2)
def vprintf(p, fmt, va):
    data = _fmt(p, fmt, va=va)
    _out(p, data)
    return len(data)


@dll(2)
def fprintf(p, fp, fmt):
    data = _fmt(p, fmt, first=2)
    s = _stream(p, fp)
    if s:
        s.write(data)
    return len(data)


@dll(3)
def vfprintf(p, fp, fmt, va):
    data = _fmt(p, fmt, va=va)
    s = _stream(p, fp)
    if s:
        s.write(data)
    return len(data)


@dll(2)
def sprintf(p, buf, fmt):
    data = _fmt(p, fmt, first=2)
    mem.write(buf, data + b"\0")
    return len(data)


@dll(3)
def vsprintf(p, buf, fmt, va):
    data = _fmt(p, fmt, va=va)
    mem.write(buf, data + b"\0")
    return len(data)


def _put_n(buf, n, data):
    if n:
        mem.write(buf, data[:n - 1] + b"\0")
    return len(data)


@dll(3)
def snprintf(p, buf, n, fmt):
    return _put_n(buf, n, _fmt(p, fmt, first=3))


dll.alias("_snprintf", "snprintf")


@dll(4)
def vsnprintf(p, buf, n, fmt, va):
    return _put_n(buf, n, _fmt(p, fmt, va=va))


dll.alias("_vsnprintf", "vsnprintf")


# The Universal CRT (programs made with Visual Studio) sends every printf here.
@dll(5)
def __stdio_common_vfprintf(p, options, fp, fmt, locale, va):
    return vfprintf(p, fp, fmt, va)


@dll(6)
def __stdio_common_vsprintf(p, options, buf, n, fmt, locale, va):
    data = _fmt(p, fmt, va=va)
    if buf:
        _put_n(buf, n, data)
    return len(data)


def _store(p, args):
    """scanf's way of writing each value it reads through the next pointer."""
    def store(conv, size, value):
        ptr = args.int()
        if conv in "feEgGa":
            import struct
            mem.write(ptr, struct.pack("<d", value) if "l" in size else struct.pack("<f", value))
        elif conv in "sc":
            mem.write(ptr, value.encode() + (b"\0" if conv == "s" else b""))
        elif "ll" in size or "I64" in size:
            mem.put64(ptr, value)
        elif size == "h":
            mem.put16(ptr, value)
        elif size == "hh":
            mem.put8(ptr, value)
        else:
            mem.put32(ptr, value)
    return store


def _scan_stream(p, s, fmt, args):
    """scanf from a stream: read lines until the format is satisfied."""
    text = ""
    while True:
        line = s.readline(1 << 16)
        if not line:
            count, used = cformat.scanf(fmt, text, lambda *a: None)
            break
        text += _text(line)
        count, used = cformat.scanf(fmt, text, lambda *a: None)
        wanted = fmt.count(b"%") - 2 * fmt.count(b"%%") - fmt.count(b"%*")
        if count >= wanted or (text.strip() and count < 0):
            break
    count, used = cformat.scanf(fmt, text, _store(p, args))
    rest = text[used:]
    if rest.strip():
        s.pending = rest.encode() + s.pending        # keep what was not read
    return count & 0xFFFFFFFF


@dll(1)
def scanf(p, fmt):
    return _scan_stream(p, _files(p)[p.state["iob"]] if _files(p) else None, mem.cbytes(fmt),
                        cformat.Args(p, 1))


dll.alias("scanf_s", "scanf")


@dll(2)
def fscanf(p, fp, fmt):
    return _scan_stream(p, _stream(p, fp), mem.cbytes(fmt), cformat.Args(p, 2))


@dll(2)
def sscanf(p, src, fmt):
    count, used = cformat.scanf(mem.cbytes(fmt), mem.cstr(src), _store(p, cformat.Args(p, 2)))
    return count & 0xFFFFFFFF


dll.alias("sscanf_s", "sscanf")


@dll(5)
def __stdio_common_vsscanf(p, options, src, n, fmt, locale):
    va = p.arg(5)
    text = mem.cstr(src) if _i64(n) < 0 else _text(mem.read(src, n))
    count, used = cformat.scanf(mem.cbytes(fmt), text, _store(p, cformat.Args(p, va_list=va)))
    return count & 0xFFFFFFFF


@dll(4)
def __stdio_common_vfscanf(p, options, fp, fmt, locale):
    return _scan_stream(p, _stream(p, fp), mem.cbytes(fmt), cformat.Args(p, va_list=p.arg(4)))


# ---- memory ----

@dll(1)
def malloc(p, n):
    return p.heap.alloc(n, zero=False)


@dll(2)
def calloc(p, n, size):
    return p.heap.alloc(n * size)


@dll(2)
def realloc(p, addr, n):
    return p.heap.realloc(addr, n)


@dll(1)
def free(p, addr):
    if addr:
        p.heap.free(addr)


@dll(1)
def _msize(p, addr):
    return p.heap.size(addr)


@dll(2)
def _aligned_malloc(p, n, align):
    return p.heap.alloc(n + align)


@dll(1)
def _aligned_free(p, addr):
    pass


dll.alias("??2@YAPEAX_K@Z", "malloc")       # C++ operator new
dll.alias("??_U@YAPEAX_K@Z", "malloc")      # operator new[]
dll.alias("??3@YAXPEAX@Z", "free")          # operator delete
dll.alias("??_V@YAXPEAX@Z", "free")


@dll(3)
def memcpy(p, dst, src, n):
    if n:
        mem.write(dst, mem.read(src, n))
    return dst


dll.alias("memmove", "memcpy")


@dll(3)
def memset(p, dst, c, n):
    if n:
        mem.write(dst, bytes([c & 255]) * n)
    return dst


@dll(3)
def memcmp(p, a, b, n):
    x, y = mem.read(a, n), mem.read(b, n)
    return (x > y) - (x < y)


@dll(3)
def memchr(p, s, c, n):
    k = mem.read(s, n).find(bytes([c & 255]))
    return s + k if k >= 0 else 0


# ---- strings ----

@dll(1)
def strlen(p, s):
    return len(mem.cbytes(s))


@dll(2)
def strnlen(p, s, n):
    return min(n, len(mem.cbytes(s, n)))


@dll(1)
def wcslen(p, s):
    return len(mem.wstr(s))


@dll(2)
def strcpy(p, dst, src):
    mem.write(dst, mem.cbytes(src) + b"\0")
    return dst


@dll(3)
def strncpy(p, dst, src, n):
    data = mem.cbytes(src, n)[:n]
    mem.write(dst, data + bytes(n - len(data)))
    return dst


@dll(3)
def strcpy_s(p, dst, size, src):
    mem.write(dst, mem.cbytes(src)[:size - 1] + b"\0")
    return 0


@dll(2)
def strcat(p, dst, src):
    mem.write(dst + len(mem.cbytes(dst)), mem.cbytes(src) + b"\0")
    return dst


@dll(3)
def strncat(p, dst, src, n):
    mem.write(dst + len(mem.cbytes(dst)), mem.cbytes(src)[:n] + b"\0")
    return dst


@dll(3)
def strcat_s(p, dst, size, src):
    strcat(p, dst, src)
    return 0


def _cmp(x, y):
    return (x > y) - (x < y)


@dll(2)
def strcmp(p, a, b):
    return _cmp(mem.cbytes(a), mem.cbytes(b))


@dll(3)
def strncmp(p, a, b, n):
    return _cmp(mem.cbytes(a, n)[:n], mem.cbytes(b, n)[:n])


@dll(2)
def _stricmp(p, a, b):
    return _cmp(mem.cbytes(a).lower(), mem.cbytes(b).lower())


dll.alias("_strcmpi", "_stricmp")
dll.alias("stricmp", "_stricmp")
dll.alias("strcoll", "strcmp")


@dll(3)
def _strnicmp(p, a, b, n):
    return _cmp(mem.cbytes(a, n)[:n].lower(), mem.cbytes(b, n)[:n].lower())


@dll(2)
def strchr(p, s, c):
    data = mem.cbytes(s)
    if c & 255 == 0:
        return s + len(data)
    k = data.find(bytes([c & 255]))
    return s + k if k >= 0 else 0


@dll(2)
def strrchr(p, s, c):
    data = mem.cbytes(s)
    if c & 255 == 0:
        return s + len(data)
    k = data.rfind(bytes([c & 255]))
    return s + k if k >= 0 else 0


@dll(2)
def strstr(p, s, sub):
    k = mem.cbytes(s).find(mem.cbytes(sub))
    return s + k if k >= 0 else 0


@dll(2)
def strspn(p, s, chars):
    data, ok = mem.cbytes(s), mem.cbytes(chars)
    n = 0
    while n < len(data) and data[n] in ok:
        n += 1
    return n


@dll(2)
def strcspn(p, s, chars):
    data, stop = mem.cbytes(s), mem.cbytes(chars)
    n = 0
    while n < len(data) and data[n] not in stop:
        n += 1
    return n


@dll(2)
def strpbrk(p, s, chars):
    n = strcspn(p, s, chars)
    return s + n if mem.u8(s + n) else 0


@dll(2)
def strtok(p, s, delims):
    d = mem.cbytes(delims)
    at = s or p.state.get("strtok", 0)
    if not at:
        return 0
    while mem.u8(at) and mem.u8(at) in d:
        at += 1
    if not mem.u8(at):
        p.state["strtok"] = 0
        return 0
    start = at
    while mem.u8(at) and mem.u8(at) not in d:
        at += 1
    if mem.u8(at):
        mem.put8(at, 0)
        p.state["strtok"] = at + 1
    else:
        p.state["strtok"] = 0
    return start


@dll(1)
def _strdup(p, s):
    data = mem.cbytes(s) + b"\0"
    out = p.heap.alloc(len(data))
    mem.write(out, data)
    return out


dll.alias("strdup", "_strdup")


@dll(1)
def _strrev(p, s):
    mem.write(s, mem.cbytes(s)[::-1])
    return s


@dll(1)
def _strupr(p, s):
    mem.write(s, mem.cbytes(s).upper())
    return s


@dll(1)
def _strlwr(p, s):
    mem.write(s, mem.cbytes(s).lower())
    return s


@dll(1)
def strerror(p, n):
    if "strerror" not in p.state:
        p.state["strerror"] = p.heap.alloc(64)
    mem.put_cstr(p.state["strerror"], "error %d" % _i32(n))
    return p.state["strerror"]


# characters
for _name, _test in (("isdigit", lambda c: 48 <= c <= 57), ("isalpha", lambda c: chr(c).isalpha() and c < 128),
                     ("isspace", lambda c: c in (9, 10, 11, 12, 13, 32)), ("isupper", lambda c: 65 <= c <= 90),
                     ("islower", lambda c: 97 <= c <= 122), ("isalnum", lambda c: chr(c).isalpha() and c < 128 or 48 <= c <= 57),
                     ("isxdigit", lambda c: chr(c) in "0123456789abcdefABCDEF"), ("isprint", lambda c: 32 <= c < 127),
                     ("ispunct", lambda c: 33 <= c < 127 and not chr(c).isalpha() and not 48 <= c <= 57),
                     ("iscntrl", lambda c: c < 32 or c == 127)):
    dll.functions[_name] = ((lambda t: lambda p, c: 1 if 0 <= _i32(c) < 256 and t(_i32(c)) else 0)(_test), 1)


@dll(1)
def toupper(p, c):
    return c - 32 if 97 <= c <= 122 else c


@dll(1)
def tolower(p, c):
    return c + 32 if 65 <= c <= 90 else c


# numbers in text
def _parse_int(text, base):
    t = text.lstrip()
    sign = 1
    if t[:1] in ("-", "+"):
        sign = -1 if t[0] == "-" else 1
        t = t[1:]
    if base in (0, 16) and t[:2].lower() == "0x":
        t, base = t[2:], 16
    elif base == 0:
        base = 8 if t[:1] == "0" and len(t) > 1 else 10
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"[:base]
    n, k = 0, 0
    while k < len(t) and t[k].lower() in digits:
        n = n * base + digits.index(t[k].lower())
        k += 1
    return sign * n, len(text) - len(t) + k if k else 0


@dll(1)
def atoi(p, s):
    return _parse_int(mem.cstr(s), 10)[0]


dll.alias("atol", "atoi")
dll.alias("_atoi64", "atoi")
dll.alias("atoll", "atoi")


@dll(3)
def strtol(p, s, end, base):
    v, used = _parse_int(mem.cstr(s), base)
    if end:
        mem.put64(end, s + used)
    return v


dll.alias("strtoul", "strtol")
dll.alias("strtoll", "strtol")
dll.alias("strtoull", "strtol")
dll.alias("_strtoi64", "strtol")
dll.alias("_strtoui64", "strtol")


def _parse_float(text):
    t = text.lstrip()
    k = 0
    while k < len(t) and t[k] in "+-0123456789.eE":
        k += 1
    while k:
        try:
            return float(t[:k]), len(text) - len(t) + k
        except ValueError:
            k -= 1
    return 0.0, 0


@dll(1)
def atof(p, s):
    return _parse_float(mem.cstr(s))[0]


@dll(2)
def strtod(p, s, end):
    v, used = _parse_float(mem.cstr(s))
    if end:
        mem.put64(end, s + used)
    return v


@dll(3)
def _itoa(p, value, buf, base):
    v = _i32(value)
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    n, out = abs(v), ""
    while True:
        out = digits[n % base] + out
        n //= base
        if not n:
            break
    mem.put_cstr(buf, ("-" if v < 0 and base == 10 else "") + out)
    return buf


dll.alias("itoa", "_itoa")
dll.alias("_ltoa", "_itoa")


@dll(1, "abs")
def abs_(p, v):
    v = _i32(v)
    return -v if v < 0 else v


dll.alias("labs", "abs")


@dll(1)
def llabs(p, v):
    v = _i64(v)
    return -v if v < 0 else v


# ---- maths (doubles travel in the XMM registers) ----

def _math1(fn):
    return lambda p: fn(p.arg_double(0))


def _math2(fn):
    return lambda p: fn(p.arg_double(0), p.arg_double(1))


for _name, _fn in (("sqrt", math.sqrt), ("sin", math.sin), ("cos", math.cos), ("tan", math.tan),
                   ("asin", math.asin), ("acos", math.acos), ("atan", math.atan), ("exp", math.exp),
                   ("log", math.log), ("log10", math.log10), ("floor", math.floor), ("ceil", math.ceil),
                   ("fabs", math.fabs), ("sinh", math.sinh), ("cosh", math.cosh), ("tanh", math.tanh),
                   ("round", lambda x: float(math.floor(x + 0.5)) if x >= 0 else float(-math.floor(-x + 0.5))),
                   ("trunc", lambda x: float(int(x)))):
    dll.functions[_name] = ((lambda f: lambda p: float(f(p.arg_double(0))))(_fn), 0)

for _name, _fn in (("pow", math.pow), ("atan2", math.atan2), ("fmod", math.fmod),
                   ("hypot", lambda a, b: math.sqrt(a * a + b * b))):
    dll.functions[_name] = ((lambda f: lambda p: float(f(p.arg_double(0), p.arg_double(1))))(_fn), 0)


@dll(0)
def rand(p):
    seed = p.state.get("rand", 1)
    seed = (seed * 214013 + 2531011) & 0xFFFFFFFF      # the formula msvcrt uses
    p.state["rand"] = seed
    return (seed >> 16) & 0x7FFF


@dll(1)
def srand(p, seed):
    p.state["rand"] = seed & 0xFFFFFFFF


@dll(4)
def qsort(p, base, n, size, compare):
    items = [mem.read(base + k * size, size) for k in range(n)]
    scratch = p.heap.alloc(size * 2)

    def less(a, b):                                        # ask the program's function
        mem.write(scratch, a)
        mem.write(scratch + size, b)
        return _i32(p.call(compare, scratch, scratch + size)) < 0

    for i in range(1, len(items)):                         # insertion sort: few calls for small arrays
        x = items[i]
        j = i - 1
        while j >= 0 and less(x, items[j]):
            items[j + 1] = items[j]
            j -= 1
        items[j + 1] = x
    for k, item in enumerate(items):
        mem.write(base + k * size, item)
    p.heap.free(scratch)


@dll(5)
def bsearch(p, key, base, n, size, compare):
    lo, hi = 0, n - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        c = _i32(p.call(compare, key, base + mid * size))
        if c == 0:
            return base + mid * size
        if c < 0:
            hi = mid - 1
        else:
            lo = mid + 1
    return 0


# ---- time ----

@dll(1, "time")
def time_(p, out):
    t = _now()
    if out:
        mem.put64(out, t)
    return t


dll.alias("_time64", "time")


def _now():
    import time as t
    epoch = t.mktime((1970, 1, 1, 0, 0, 0, 0, 0)) if hasattr(t, "mktime") else 0
    return int(t.time() - epoch)


@dll(0)
def clock(p):
    import time as t
    return t.ticks_ms()


def _tm(p, seconds):
    import time as t
    epoch = t.mktime((1970, 1, 1, 0, 0, 0, 0, 0)) if hasattr(t, "mktime") else 0
    y, mo, d, h, mi, s, wd, yd = t.localtime(seconds + epoch)[:8]
    if "tm" not in p.state:
        p.state["tm"] = p.heap.alloc(36)
    out = p.state["tm"]
    for k, v in enumerate((s, mi, h, d, mo - 1, y - 1900, (wd + 1) % 7, yd - 1, 0)):
        mem.put32(out + 4 * k, v)
    return out


@dll(1)
def localtime(p, t):
    return _tm(p, mem.u64(t))


dll.alias("gmtime", "localtime")
dll.alias("_localtime64", "localtime")


@dll(1)
def ctime(p, t):
    import time as tm
    epoch = tm.mktime((1970, 1, 1, 0, 0, 0, 0, 0)) if hasattr(tm, "mktime") else 0
    y, mo, d, h, mi, s, wd = tm.localtime(mem.u64(t) + epoch)[:7]
    text = "%s %s %2d %02d:%02d:%02d %d\n" % ("Mon Tue Wed Thu Fri Sat Sun".split()[wd],
                                              "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()[mo - 1],
                                              d, h, mi, s, y)
    if "ctime" not in p.state:
        p.state["ctime"] = p.heap.alloc(32)
    mem.put_cstr(p.state["ctime"], text)
    return p.state["ctime"]


# ---- the program's start and end ----

@dll(5)
def __getmainargs(p, argc, argv, envp, wildcard, info):
    mem.put32(argc, len(p.argv))
    mem.put64(argv, _argv(p))
    mem.put64(envp, _env(p))
    return 0


dll.alias("__wgetmainargs", "__getmainargs")


def _argv(p):
    if "argv" not in p.state:
        table = p.heap.alloc(8 * (len(p.argv) + 1))
        for k, a in enumerate(p.argv):
            s = p.heap.alloc(len(a.encode()) + 1)
            mem.put_cstr(s, a)
            mem.put64(table + 8 * k, s)
        p.state["argv"] = table
    return p.state["argv"]


def _env(p):
    if "env" not in p.state:
        p.state["env"] = p.heap.alloc(16)                  # an empty list
    return p.state["env"]


@dll(0)
def __p___argc(p):
    if "argc" not in p.state:
        p.state["argc"] = p.heap.alloc(8)
        mem.put32(p.state["argc"], len(p.argv))
    return p.state["argc"]


@dll(0)
def __p___argv(p):
    if "argvp" not in p.state:
        p.state["argvp"] = p.heap.alloc(8)
        mem.put64(p.state["argvp"], _argv(p))
    return p.state["argvp"]


@dll(0)
def _get_initial_narrow_environment(p):
    return _env(p)


@dll(1)
def _configure_narrow_argv(p, mode):
    return 0


dll.alias("_initialize_narrow_environment", "_configure_narrow_argv")
dll.alias("_set_app_type", "_configure_narrow_argv")
dll.alias("__set_app_type", "_configure_narrow_argv")
dll.alias("_configthreadlocale", "_configure_narrow_argv")
dll.alias("_set_new_mode", "_configure_narrow_argv")
dll.alias("_set_fmode", "_configure_narrow_argv")
dll.alias("__setusermatherr", "_configure_narrow_argv")
dll.alias("_setusermatherr", "_configure_narrow_argv")
dll.alias("_register_thread_local_exe_atexit_callback", "_configure_narrow_argv")
dll.alias("_seh_filter_exe", "_configure_narrow_argv")
dll.alias("__std_type_info_destroy_list", "_configure_narrow_argv")
dll.alias("_fpreset", "_configure_narrow_argv")
dll.alias("_lock", "_configure_narrow_argv")
dll.alias("_unlock", "_configure_narrow_argv")
dll.alias("_lock_file", "_configure_narrow_argv")
dll.alias("_unlock_file", "_configure_narrow_argv")


@dll(2)
def _initterm(p, start, end):
    """Call each function in a table: the C and C++ initialisers."""
    while start < end:
        fn = mem.u64(start)
        if fn:
            p.call(fn)
        start += 8


@dll(2)
def _initterm_e(p, start, end):
    while start < end:
        fn = mem.u64(start)
        if fn:
            r = _i32(p.call(fn))
            if r:
                return r
        start += 8
    return 0


@dll(1)
def atexit(p, fn):
    p.state.setdefault("atexit", []).append(fn)
    return 0


dll.alias("_crt_atexit", "atexit")


@dll(1)
def _onexit(p, fn):
    atexit(p, fn)
    return fn


@dll(1)
def exit(p, code):
    from pywin.process import Exit
    from pywin import dlls
    dlls.run_atexit(p)
    raise Exit(code)


@dll(1)
def _exit(p, code):
    from pywin.process import Exit
    raise Exit(code)


dll.alias("_Exit", "_exit")
dll.alias("quick_exit", "_exit")


@dll(0)
def _cexit(p):
    from pywin import dlls
    dlls.run_atexit(p)


dll.alias("_c_exit", "_cexit")


@dll(0)
def abort(p):
    from pywin.process import Exit
    p.ui.write("\nabnormal program termination\n")
    raise Exit(3)


dll.alias("terminate", "abort")


@dll(1)
def _amsg_exit(p, n):
    from pywin.process import Exit
    p.ui.write("\nruntime error R60%02d\n" % n)
    raise Exit(255)


@dll(3)
def _assert(p, text, file, line):
    from pywin.process import Exit
    p.ui.write("Assertion failed: %s, file %s, line %d\n" % (mem.cstr(text), mem.cstr(file), line))
    raise Exit(3)


dll.alias("_wassert", "_assert")


@dll(2)
def signal(p, sig, fn):
    return 0


@dll(1, "raise")
def raise_(p, sig):
    return 0


@dll(0)
def _errno(p):
    if "errno_at" not in p.state:
        p.state["errno_at"] = p.heap.alloc(8)
    mem.put32(p.state["errno_at"], p.state.get("errno", 0))
    return p.state["errno_at"]


@dll(1)
def getenv(p, name):
    return 0


@dll(1)
def system(p, cmd):
    p.warn("system() no esta disponible")
    return -1


@dll(1)
def _ismbblead(p, c):
    return 0                                          # UTF-8 text: no double-byte lead bytes


dll.alias("_ismbbtrail", "_ismbblead")


@dll(0)
def ___lc_codepage_func(p):
    return 65001


@dll(0)
def ___mb_cur_max_func(p):
    return 1


dll.alias("__p___mb_cur_max", "___mb_cur_max_func")


@dll(0)
def localeconv(p):
    """struct lconv: the decimal point is '.'."""
    if "lconv" not in p.state:
        block = p.heap.alloc(160)
        dot = block + 128
        mem.put_cstr(dot, ".")
        for k in range(10):
            mem.put64(block + 8 * k, dot + 2)          # empty strings
        mem.put64(block, dot)
        p.state["lconv"] = block
    return p.state["lconv"]


@dll(2)
def setlocale(p, category, name):
    if "locale" not in p.state:
        p.state["locale"] = p.heap.alloc(8)
        mem.put_cstr(p.state["locale"], "C")
    return p.state["locale"]


@dll(0)
def __p__fmode(p):
    if "fmode" not in p.state:
        p.state["fmode"] = p.heap.alloc(8)
    return p.state["fmode"]


dll.alias("__p__commode", "__p__fmode")


@dll(3)
def _controlfp_s(p, current, new, mask):
    if current:
        mem.put32(current, 0x9001F)
    return 0


@dll(2)
def _controlfp(p, new, mask):
    return 0x9001F


@dll(4)
def __C_specific_handler(p, record, frame, context, dispatch):
    return 1                                          # ExceptionContinueSearch


dll.variable("_fmode", 4)
dll.variable("_commode", 4)
dll.variable("__initenv", 8)
dll.variable("_acmdln", 8)
dll.variable("__argc", 4)
dll.variable("__argv", 8)
dll.variable("_environ", 8)
dll.variable("__mb_cur_max", 4, 1)
dll.variable("_iob", FILE_SIZE * 3)


# ---- less common things C++ programs pull in ----

def _fd_stream(p, fd):
    """A low-level file number (0, 1, 2...) as one of our streams."""
    for fp, s in _files(p).items():
        if _fileno(p, fp) == fd:
            return s
    return None


@dll(3)
def _read(p, fd, buf, n):
    s = _fd_stream(p, fd)
    data = s.read(n) if s else b""
    mem.write(buf, data)
    return len(data)


@dll(2)
def _fdopen(p, fd, mode):
    _files(p)
    return p.state["iob"] + FILE_SIZE * fd if fd < 3 else 0


@dll(3)
def _lseeki64(p, fd, offset, whence):
    s = _fd_stream(p, fd)
    return s.f.seek(_i64(offset), whence) if s and s.f else -1


@dll(1)
def _filelengthi64(p, fd):
    s = _fd_stream(p, fd)
    if not s or not s.f:
        return -1
    here = s.f.tell()
    end = s.f.seek(0, 2)
    s.f.seek(here)
    return end


@dll(2)
def _fstat64(p, fd, out):
    mem.zero(out, 56)
    mem.put16(out + 6, 0x2000 if fd < 3 else 0x8000)    # character device, or a file
    size = _filelengthi64(p, fd)
    mem.put64(out + 24, max(0, _i64(size)))
    return 0


@dll(2)
def fgetpos(p, fp, pos):
    mem.put64(pos, ftell(p, fp))
    return 0


@dll(2)
def fsetpos(p, fp, pos):
    return fseek(p, fp, mem.u64(pos), 0)


@dll(1)
def getwc(p, fp):
    c = fgetc(p, fp)
    return 0xFFFF if c == EOF else c


@dll(2)
def putwc(p, c, fp):
    fputc(p, c & 0xFF, fp)
    return c


@dll(2)
def ungetwc(p, c, fp):
    return ungetc(p, c, fp)


@dll(2)
def iswctype(p, c, mask):
    ch = chr(c & 0xFFFF)
    kinds = ((1, ch.isupper()), (2, ch.islower()), (4, ch.isdigit()), (8, ch.isspace()),
             (0x100, ch.isalpha()), (0x80, 33 <= c < 127 and not ch.isalpha() and not ch.isdigit()))
    return 1 if any(on and mask & bit for bit, on in kinds) else 0


@dll(1)
def towlower(p, c):
    return ord(chr(c & 0xFFFF).lower()[0])


@dll(1)
def towupper(p, c):
    return ord(chr(c & 0xFFFF).upper()[0])


@dll(2)
def wcscoll(p, a, b):
    x, y = mem.wstr(a), mem.wstr(b)
    return (x > y) - (x < y)


@dll(3)
def strxfrm(p, dst, src, n):
    data = mem.cbytes(src)
    if n > len(data):
        mem.write(dst, data + b"\0")
    return len(data)


@dll(3)
def wcsxfrm(p, dst, src, n):
    s = mem.wstr(src)
    if n > len(s):
        mem.put_wstr(dst, s)
    return len(s)


def _strftime(p, fmt, tm):
    v = [mem.i32(tm + 4 * k) for k in range(9)]       # sec, min, hour, mday, mon, year, wday, yday
    days = "Sunday Monday Tuesday Wednesday Thursday Friday Saturday".split()
    months = "January February March April May June July August September October November December".split()
    codes = {"Y": "%d" % (v[5] + 1900), "m": "%02d" % (v[4] + 1), "d": "%02d" % v[3], "H": "%02d" % v[2],
             "M": "%02d" % v[1], "S": "%02d" % v[0], "y": "%02d" % (v[5] % 100), "A": days[v[6] % 7],
             "a": days[v[6] % 7][:3], "B": months[v[4] % 12], "b": months[v[4] % 12][:3], "j": "%03d" % (v[7] + 1),
             "%": "%"}
    codes["c"] = "%s %s %s %s:%s:%s %s" % (codes["a"], codes["b"], codes["d"], codes["H"], codes["M"], codes["S"], codes["Y"])
    codes["x"] = "%s/%s/%s" % (codes["m"], codes["d"], codes["y"])
    codes["X"] = "%s:%s:%s" % (codes["H"], codes["M"], codes["S"])
    out, i = "", 0
    while i < len(fmt):
        if fmt[i] == "%" and i + 1 < len(fmt):
            out += codes.get(fmt[i + 1], "")
            i += 2
        else:
            out += fmt[i]
            i += 1
    return out


@dll(4)
def strftime(p, buf, size, fmt, tm):
    text = _strftime(p, mem.cstr(fmt), tm).encode()
    if len(text) >= size:
        return 0
    mem.write(buf, text + b"\0")
    return len(text)


@dll(4)
def wcsftime(p, buf, size, fmt, tm):
    text = _strftime(p, mem.wstr(fmt), tm)
    if len(text) >= size:
        return 0
    mem.put_wstr(buf, text)
    return len(text)


# ---- threads (kernel32 does the work) ----

@dll(6)
def _beginthreadex(p, security, stack, fn, arg, flags, tid_out):
    from pywin.dlls import kernel32
    return kernel32.CreateThread(p, security, stack, fn, arg, flags, tid_out)


@dll(3)
def _beginthread(p, fn, stack, arg):
    return p.new_handle(p.start_thread(fn, arg, stack))


@dll(1)
def _endthreadex(p, code):
    from pywin.dlls import kernel32
    kernel32.ExitThread(p, code)


@dll(0)
def _endthread(p):
    _endthreadex(p, 0)


@dll(1)
def _mkdir(p, name):
    import os
    try:
        os.mkdir(p.host_path(mem.cstr(name), write=True))
        return 0
    except OSError:
        p.state["errno"] = 17                           # EEXIST
        return -1


@dll(1)
def _rmdir(p, name):
    import os
    try:
        os.rmdir(p.host_path(mem.cstr(name), write=True))
        return 0
    except OSError:
        return -1


@dll(2)
def _access(p, name, mode):
    import os
    try:
        os.stat(p.host_path(mem.cstr(name)))
        return 0
    except OSError:
        p.state["errno"] = 2
        return -1
