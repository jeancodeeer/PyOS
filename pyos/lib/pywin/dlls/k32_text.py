# kernel32.dll, part 3: text. Character types, upper/lower case, comparing
# strings, the locale (language and formats), dates and times as text, and
# the small helpers programs built with Visual C++ call at start-up.
# SnakeyOS has one locale: Spanish text in UTF-8, shown as LCID 0x0C0A.
import struct
import time
from pywin import mem
from pywin.dlls.kernel32 import dll, _i32

LCID = 0x0C0A                                          # es-ES
LOCALE_NAME = "es-ES"
CP_UTF8 = 65001


def _wide(ptr, n):
    """A UTF-16 string of n characters (n = -1: up to the zero)."""
    n = _i32(n)
    if n < 0:
        return mem.wstr(ptr) or ""
    raw = mem.read(ptr, 2 * n)
    return "".join(chr(raw[2 * k] | raw[2 * k + 1] << 8) for k in range(n))


def _put_wide(ptr, text):
    mem.write(ptr, b"".join(struct.pack("<H", ord(c) & 0xFFFF) for c in text))


# ---- what kind of character ----

C1_UPPER, C1_LOWER, C1_DIGIT, C1_SPACE, C1_PUNCT, C1_CNTRL, C1_BLANK, C1_XDIGIT, C1_ALPHA, C1_DEFINED = \
    1, 2, 4, 8, 0x10, 0x20, 0x40, 0x80, 0x100, 0x200


def char_type(c):
    ch = chr(c)
    t = C1_DEFINED
    if ch.isupper():
        t |= C1_UPPER | C1_ALPHA
    elif ch.islower():
        t |= C1_LOWER | C1_ALPHA
    elif ch.isalpha():
        t |= C1_ALPHA
    if ch.isdigit():
        t |= C1_DIGIT
    if ch in "0123456789abcdefABCDEF":
        t |= C1_XDIGIT
    if ch in " \t\n\r\x0b\x0c":
        t |= C1_SPACE
    if ch in " \t":
        t |= C1_BLANK
    if c < 32 or c == 127:
        t |= C1_CNTRL
    elif 32 < c < 127 and not ch.isalpha() and not ch.isdigit():
        t |= C1_PUNCT
    return t


@dll(4)
def GetStringTypeW(p, kind, text, n, out):
    s = _wide(text, n)
    for k, ch in enumerate(s):
        mem.put16(out + 2 * k, char_type(ord(ch)) if kind == 1 else 0)
    return 1


@dll(5)
def GetStringTypeExW(p, locale, kind, text, n, out):
    return GetStringTypeW(p, kind, text, n, out)


@dll(5)
def GetStringTypeExA(p, locale, kind, text, n, out):
    raw = mem.cbytes(text) if _i32(n) < 0 else mem.read(text, n)
    for k, c in enumerate(raw):
        mem.put16(out + 2 * k, char_type(c) if kind == 1 else 0)
    return 1


dll.alias("GetStringTypeA", "GetStringTypeExA")


# ---- upper and lower case, sorting keys ----

LCMAP_LOWERCASE, LCMAP_UPPERCASE, LCMAP_SORTKEY = 0x100, 0x200, 0x400


def _map(text, flags):
    if flags & LCMAP_LOWERCASE:
        return text.lower()
    if flags & LCMAP_UPPERCASE:
        return text.upper()
    return text


def _lcmap_w(p, flags, src, n, dst, size):
    s = _map(_wide(src, n), flags)
    if flags & LCMAP_SORTKEY:                          # bytes that sort like the text
        key = s.lower().encode() + b"\0"
        if size:
            mem.write(dst, key[:size])
        return len(key)
    if _i32(n) < 0:
        s += "\0"
    if size:
        _put_wide(dst, s[:size])
    return len(s)


@dll(6)
def LCMapStringW(p, locale, flags, src, n, dst, size):
    return _lcmap_w(p, flags, src, n, dst, size)


@dll(9)
def LCMapStringEx(p, name, flags, src, n, dst, size, info, reserved, param):
    return _lcmap_w(p, flags, src, n, dst, size)


@dll(6)
def LCMapStringA(p, locale, flags, src, n, dst, size):
    raw = mem.cbytes(src) if _i32(n) < 0 else mem.read(src, n)
    out = bytes(ord(c) & 255 for c in _map("".join(chr(c) for c in raw), flags))
    if _i32(n) < 0:
        out += b"\0"
    if size:
        mem.write(dst, out[:size])
    return len(out)


@dll(1)
def CharUpperW(p, s):
    if s < 0x10000:
        return ord(chr(s).upper()[0])
    text = mem.wstr(s)
    _put_wide(s, text.upper())
    return s


@dll(1)
def CharLowerW(p, s):
    if s < 0x10000:
        return ord(chr(s).lower()[0])
    text = mem.wstr(s)
    _put_wide(s, text.lower())
    return s


@dll(1)
def IsCharAlphaW(p, c):
    return 1 if chr(c & 0xFFFF).isalpha() else 0


@dll(1)
def IsCharAlphaNumericW(p, c):
    ch = chr(c & 0xFFFF)
    return 1 if ch.isalpha() or ch.isdigit() else 0


@dll(1)
def IsCharLowerW(p, c):
    return 1 if chr(c & 0xFFFF).islower() else 0


@dll(1)
def IsCharUpperW(p, c):
    return 1 if chr(c & 0xFFFF).isupper() else 0


# ---- comparing ----

NORM_IGNORECASE = 1
CSTR_LESS, CSTR_EQUAL, CSTR_GREATER = 1, 2, 3


def _compare(a, b, ignore_case):
    if ignore_case:
        a, b = a.lower(), b.lower()
    return CSTR_LESS if a < b else CSTR_GREATER if a > b else CSTR_EQUAL


@dll(6)
def CompareStringW(p, locale, flags, a, na, b, nb):
    return _compare(_wide(a, na), _wide(b, nb), flags & (NORM_IGNORECASE | 0x10000000))


@dll(9)
def CompareStringEx(p, name, flags, a, na, b, nb, info, reserved, param):
    return _compare(_wide(a, na), _wide(b, nb), flags & (NORM_IGNORECASE | 0x10000000))


@dll(5)
def CompareStringOrdinal(p, a, na, b, nb, ignore_case):
    return _compare(_wide(a, na), _wide(b, nb), ignore_case)


@dll(6)
def CompareStringA(p, locale, flags, a, na, b, nb):
    x = mem.cbytes(a) if _i32(na) < 0 else mem.read(a, na)
    y = mem.cbytes(b) if _i32(nb) < 0 else mem.read(b, nb)
    if flags & NORM_IGNORECASE:
        x, y = x.lower(), y.lower()
    return CSTR_LESS if x < y else CSTR_GREATER if x > y else CSTR_EQUAL


def _cmp(a, b):
    return (a > b) - (a < b)


@dll(2)
def lstrcmpW(p, a, b):
    return _cmp(mem.wstr(a) or "", mem.wstr(b) or "")


@dll(2)
def lstrcmpiW(p, a, b):
    return _cmp((mem.wstr(a) or "").lower(), (mem.wstr(b) or "").lower())


@dll(2)
def lstrcpyW(p, dst, src):
    mem.put_wstr(dst, mem.wstr(src) or "")
    return dst


@dll(3)
def lstrcpynW(p, dst, src, n):
    if n > 0:
        mem.put_wstr(dst, (mem.wstr(src) or "")[:n - 1])
    return dst


@dll(3)
def lstrcpynA(p, dst, src, n):
    if n > 0:
        mem.write(dst, mem.cbytes(src)[:n - 1] + b"\0")
    return dst


@dll(2)
def lstrcatW(p, dst, src):
    mem.put_wstr(dst, (mem.wstr(dst) or "") + (mem.wstr(src) or ""))
    return dst


@dll(3)
def MulDiv(p, a, b, c):
    a, b, c = _i32(a), _i32(b), _i32(c)
    if c == 0:
        return -1
    q = a * b
    r = (abs(q) + abs(c) // 2) // abs(c)                 # rounded, like Windows
    return r if (q >= 0) == (c > 0) else -r


@dll(2)
def GetCPInfo(p, cp, out):
    mem.zero(out, 20)
    mem.put32(out, 4 if cp in (CP_UTF8, 0) else 1)       # longest character, in bytes
    mem.put8(out + 4, ord("?"))
    return 1


@dll(3)
def GetCPInfoExW(p, cp, flags, out):
    GetCPInfo(p, cp, out)
    mem.put32(out + 20, cp)
    mem.put_wstr(out + 24, "65001 (UTF-8)")
    return 1


# ---- the locale ----

LOCALE_VALUES = {
    0x0001: "0c0a",   # LOCALE_ILANGUAGE
    0x0002: "Español (España)", 0x0003: "ESP", 0x0004: "Español", 0x0005: "34", 0x0006: "España",
    0x0007: "ESP", 0x0009: "es-ES",
    0x000C: ";",      # list separator
    0x000E: ",",      # decimal point
    0x000F: ".",      # thousands
    0x0010: "3;0", 0x0011: "2", 0x0014: "€", 0x0015: "EUR", 0x0016: ",", 0x0017: ".",
    0x001D: "/", 0x001E: ":", 0x001F: "dd/MM/yyyy", 0x0020: "dddd, d' de 'MMMM' de 'yyyy",
    0x0021: "1", 0x0022: "0", 0x0023: "1", 0x0024: "0", 0x0025: "1", 0x0028: "", 0x0029: "",
    0x1003: "HH:mm:ss", 0x1004: "1", 0x1005: "1", 0x1009: "0", 0x100C: "0",
    0x002A: "lunes", 0x002B: "martes", 0x002C: "miércoles", 0x002D: "jueves", 0x002E: "viernes",
    0x002F: "sábado", 0x0030: "domingo",
    0x0038: "enero", 0x0039: "febrero", 0x003A: "marzo", 0x003B: "abril", 0x003C: "mayo",
    0x003D: "junio", 0x003E: "julio", 0x003F: "agosto", 0x0040: "septiembre", 0x0041: "octubre",
    0x0042: "noviembre", 0x0043: "diciembre",
    0x005C: "es", 0x0059: "es", 0x005A: "ES", 0x0068: "es-ES", 0x006F: "es-ES",
}


def _locale_value(kind):
    kind &= 0x0FFFFFFF                                   # drop LOCALE_NOUSEROVERRIDE and friends
    if kind & 0x20000000:
        kind &= ~0x20000000
    return LOCALE_VALUES.get(kind & 0xFFFF, "")


@dll(4)
def GetLocaleInfoW(p, locale, kind, buf, size):
    if kind & 0x20000000:                                # LOCALE_RETURN_NUMBER
        value = _locale_value(kind)
        n = int(value, 16) if kind & 0xFFFF == 1 else int(value or "0")
        if size >= 2:
            mem.put32(buf, n)
        return 2
    value = _locale_value(kind)
    if not size:
        return len(value) + 1
    mem.put_wstr(buf, value[:size - 1])
    return min(len(value), size - 1) + 1


@dll(4)
def GetLocaleInfoEx(p, name, kind, buf, size):
    return GetLocaleInfoW(p, LCID, kind, buf, size)


@dll(4)
def GetLocaleInfoA(p, locale, kind, buf, size):
    value = _locale_value(kind).encode()
    if not size:
        return len(value) + 1
    mem.write(buf, value[:size - 1] + b"\0")
    return min(len(value), size - 1) + 1


@dll(0)
def GetUserDefaultLCID(p):
    return LCID


for _n in ("GetSystemDefaultLCID", "GetThreadLocale", "GetUserDefaultLangID", "GetSystemDefaultLangID",
           "GetUserDefaultUILanguage", "GetSystemDefaultUILanguage"):
    dll.alias(_n, "GetUserDefaultLCID")


@dll(2)
def GetUserDefaultLocaleName(p, buf, size):
    if size <= len(LOCALE_NAME):
        return 0
    mem.put_wstr(buf, LOCALE_NAME)
    return len(LOCALE_NAME) + 1


dll.alias("GetSystemDefaultLocaleName", "GetUserDefaultLocaleName")


@dll(4)
def LCIDToLocaleName(p, lcid, buf, size, flags):
    return GetUserDefaultLocaleName(p, buf, size)


@dll(2)
def LocaleNameToLCID(p, name, flags):
    return LCID


@dll(2)
def IsValidLocale(p, lcid, flags):
    return 1


@dll(1)
def IsValidLocaleName(p, name):
    return 1


@dll(2)
def EnumSystemLocalesW(p, fn, flags):
    s = p.heap.alloc(16)
    mem.put_wstr(s, "00000C0A")
    p.call(fn, s)
    return 1


@dll(4)
def EnumSystemLocalesEx(p, fn, flags, param, reserved):
    s = p.heap.alloc(16)
    mem.put_wstr(s, LOCALE_NAME)
    p.call(fn, s, 0, param)
    return 1


@dll(1)
def SetThreadLocale(p, lcid):
    return 1


@dll(0)
def AreFileApisANSI(p):
    return 1


# ---- dates and times as text ----

def _now_or(st):
    if st:
        y, mo, wd, d, h, mi, s, ms = struct.unpack("<8H", mem.read(st, 16))
        return y, mo, d, h, mi, s, wd
    t = time.localtime()
    return t[0], t[1], t[2], t[3], t[4], t[5], (t[6] + 1) % 7


DAYS = ("domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado")
MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
          "octubre", "noviembre", "diciembre")


def format_date(fmt, y, mo, d, wd):
    out, i = "", 0
    while i < len(fmt):
        ch = fmt[i]
        if ch == "'":                                       # quoted text
            j = fmt.find("'", i + 1)
            j = len(fmt) if j < 0 else j
            out += fmt[i + 1:j]
            i = j + 1
            continue
        run = 1
        while i + run < len(fmt) and fmt[i + run] == ch:
            run += 1
        if ch == "d":
            out += (str(d), "%02d" % d, DAYS[wd][:3], DAYS[wd])[min(run, 4) - 1]
        elif ch == "M":
            out += (str(mo), "%02d" % mo, MONTHS[mo - 1][:3], MONTHS[mo - 1])[min(run, 4) - 1]
        elif ch == "y":
            out += "%02d" % (y % 100) if run <= 2 else str(y)
        else:
            out += ch * run
        i += run
    return out


def format_time(fmt, h, mi, s):
    out, i = "", 0
    while i < len(fmt):
        ch = fmt[i]
        run = 1
        while i + run < len(fmt) and fmt[i + run] == ch:
            run += 1
        if ch == "H":
            out += "%02d" % h if run > 1 else str(h)
        elif ch == "h":
            v = h % 12 or 12
            out += "%02d" % v if run > 1 else str(v)
        elif ch == "m":
            out += "%02d" % mi if run > 1 else str(mi)
        elif ch == "s":
            out += "%02d" % s if run > 1 else str(s)
        elif ch == "t":
            out += ("a. m." if h < 12 else "p. m.") if run > 1 else ("a" if h < 12 else "p")
        else:
            out += ch * run
        i += run
    return out


def _out_w(text, buf, size):
    if not size:
        return len(text) + 1
    mem.put_wstr(buf, text[:size - 1])
    return min(len(text), size - 1) + 1


@dll(6)
def GetDateFormatW(p, locale, flags, st, fmt, buf, size):
    y, mo, d, h, mi, s, wd = _now_or(st)
    pattern = mem.wstr(fmt) if fmt else ("dddd, d' de 'MMMM' de 'yyyy" if flags & 2 else "dd/MM/yyyy")
    return _out_w(format_date(pattern, y, mo, d, wd), buf, size)


@dll(7)
def GetDateFormatEx(p, name, flags, st, fmt, buf, size, calendar):
    return GetDateFormatW(p, 0, flags, st, fmt, buf, size)


@dll(6)
def GetTimeFormatW(p, locale, flags, st, fmt, buf, size):
    y, mo, d, h, mi, s, wd = _now_or(st)
    pattern = mem.wstr(fmt) if fmt else ("HH:mm" if flags & 2 else "HH:mm:ss")
    return _out_w(format_time(pattern, h, mi, s), buf, size)


@dll(6)
def GetTimeFormatEx(p, name, flags, st, fmt, buf, size):
    return GetTimeFormatW(p, 0, flags, st, fmt, buf, size)


# ---- messages, environment ----

@dll(7)
def FormatMessageW(p, flags, source, msg_id, lang, buf, size, args):
    text = "Error %d\r\n" % (msg_id & 0xFFFF)
    if flags & 0x100:                                       # FORMAT_MESSAGE_ALLOCATE_BUFFER
        block = p.heap.alloc(2 * len(text) + 2)
        mem.put_wstr(block, text)
        mem.put64(buf, block)
    elif size:
        mem.put_wstr(buf, text[:size - 1])
    return len(text)


@dll(3)
def ExpandEnvironmentStringsW(p, src, dst, size):
    text = mem.wstr(src) or ""
    for name, value in (("%USERPROFILE%", "C:\\"), ("%APPDATA%", "C:\\AppData"), ("%TEMP%", "C:\\Temp"),
                        ("%TMP%", "C:\\Temp"), ("%WINDIR%", "C:\\Windows"), ("%SYSTEMROOT%", "C:\\Windows"),
                        ("%PROGRAMFILES%", "C:\\Programas"), ("%LOCALAPPDATA%", "C:\\AppData")):
        i = text.upper().find(name)
        while i >= 0:
            text = text[:i] + value + text[i + len(name):]
            i = text.upper().find(name)
    if size > len(text):
        mem.put_wstr(dst, text)
    return len(text) + 1


@dll(3)
def GetEnvironmentVariableW(p, name, buf, size):
    values = {"USERPROFILE": "C:\\", "APPDATA": "C:\\AppData", "TEMP": "C:\\Temp", "TMP": "C:\\Temp",
              "WINDIR": "C:\\Windows", "SYSTEMROOT": "C:\\Windows", "LOCALAPPDATA": "C:\\AppData"}
    value = values.get((mem.wstr(name) or "").upper())
    if value is None:
        p.last_error = 203                                  # ERROR_ENVVAR_NOT_FOUND
        return 0
    if size <= len(value):
        return len(value) + 1
    mem.put_wstr(buf, value)
    return len(value)
