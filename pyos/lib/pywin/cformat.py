# printf and scanf, the C way, for msvcrt.
#
#   printf(fmt, args)    fmt: bytes; args has .int() .double() .ptr() for
#                        the next argument; returns the text as bytes
#   scanf(fmt, text, store)   reads values from text and calls
#                        store(kind, value) for each; returns (count, used)
import struct
from pywin import mem

_FLOAT = "fFeEgG"


def printf(fmt, args):
    out = []
    i, n = 0, len(fmt)
    while i < n:
        c = fmt[i]
        if c != 37:                                  # not '%'
            j = fmt.find(b"%", i)
            j = n if j < 0 else j
            out.append(fmt[i:j])
            i = j
            continue
        i += 1
        flags = ""
        while i < n and chr(fmt[i]) in "-+ #0":
            flags += chr(fmt[i])
            i += 1
        width, i = _number(fmt, i, args)
        prec = None
        if i < n and fmt[i] == 46:                   # '.'
            prec, i = _number(fmt, i + 1, args)
            prec = prec or 0
        size = ""
        while i < n and chr(fmt[i]) in "hlLqjztI0123456789":
            size += chr(fmt[i])
            i += 1
        if i >= n:
            break
        conv = chr(fmt[i])
        i += 1
        out.append(_one(conv, flags, width, prec, size, args).encode())
    return b"".join(out)


def _number(fmt, i, args):
    if i < len(fmt) and fmt[i] == 42:                # '*': taken from the arguments
        v = _signed(args.int(), 32)
        return v, i + 1
    v = None
    while i < len(fmt) and 48 <= fmt[i] <= 57:
        v = (v or 0) * 10 + fmt[i] - 48
        i += 1
    return v, i


def _signed(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def _bits(size):
    if size in ("ll", "I64", "q", "j", "z", "t", "I", "L"):
        return 64
    if size == "hh":
        return 8
    if size == "h":
        return 16
    return 32                                         # int and long are 32 bits on Windows


def _one(conv, flags, width, prec, size, args):
    if conv == "%":
        return "%"
    if conv in "di":
        v = _signed(args.int(), _bits(size))
        body = str(abs(v))
        if prec is not None:
            body = "0" * (prec - len(body)) + body
        return _pad(body, "-" if v < 0 else "+" if "+" in flags else " " if " " in flags else "",
                    flags, width, prec is None)
    if conv in "uxXo":
        v = args.int() & ((1 << _bits(size)) - 1)
        body = {"u": "%d", "x": "%x", "X": "%X", "o": "%o"}[conv] % v
        if prec is not None:
            body = "0" * (prec - len(body)) + body
        prefix = ("0x" if conv == "x" else "0X" if conv == "X" else "0") if "#" in flags and v else ""
        return _pad(body, prefix, flags, width, prec is None)
    if conv == "p":
        return _pad("%016X" % args.int(), "", flags, width, False)
    if conv in _FLOAT:
        v = args.double()
        p = 6 if prec is None else prec
        if v != v:
            body = "nan"
        elif v in (float("inf"), float("-inf")):
            body = "inf"
        else:
            body = ("%." + str(p) + conv.lower()) % abs(v)
            if conv.lower() == "g" and "#" not in flags and "." in body and "e" not in body:
                body = body.rstrip("0").rstrip(".")
        if conv.isupper():
            body = body.upper()
        sign = "-" if v < 0 or (v == 0 and str(v).startswith("-")) else "+" if "+" in flags else " " if " " in flags else ""
        return _pad(body, sign, flags, width, True)
    if conv == "c":
        return _pad(chr(args.int() & 0xFF), "", flags.replace("0", ""), width, False)
    if conv in "sS":
        ptr = args.int()
        wide = conv == "S" or size in ("l", "w")
        s = "(null)" if not ptr else (mem.wstr(ptr) if wide else mem.cstr(ptr))
        if prec is not None:
            s = s[:prec]
        return _pad(s, "", flags.replace("0", ""), width, False)
    if conv == "n":
        args.int()
        return ""
    return "%" + conv


def _pad(body, sign, flags, width, zero_ok):
    text = sign + body
    if width is None or len(text) >= abs(width):
        return text
    if width < 0 or "-" in flags:
        return text + " " * (abs(width) - len(text))
    if "0" in flags and zero_ok:
        return sign + "0" * (width - len(text)) + body
    return " " * (width - len(text)) + text


class Args:
    """The arguments after the format: from the registers and stack (first
    = the index of the first one), or from a va_list pointer."""

    def __init__(self, p, first=None, va_list=None):
        self.p, self.i, self.va = p, first, va_list

    def int(self):
        if self.va is not None:
            v = mem.u64(self.va)
            self.va += 8
            return v
        v = self.p.arg(self.i)
        self.i += 1
        return v

    def double(self):
        return struct.unpack("<d", struct.pack("<Q", self.int()))[0]


# ---- scanf ----

def scanf(fmt, text, store):
    """Match text against fmt. store(conv, size, value) writes each value."""
    count = 0
    i = t = 0
    fmt = fmt.decode() if isinstance(fmt, bytes) else fmt
    while i < len(fmt):
        c = fmt[i]
        if c.isspace():
            while t < len(text) and text[t].isspace():
                t += 1
            i += 1
            continue
        if c != "%":
            if t >= len(text) or text[t] != c:
                break
            i += 1
            t += 1
            continue
        i += 1
        skip = i < len(fmt) and fmt[i] == "*"
        if skip:
            i += 1
        width = 0
        while i < len(fmt) and fmt[i].isdigit():
            width = width * 10 + int(fmt[i])
            i += 1
        size = ""
        while i < len(fmt) and fmt[i] in "hlLqI64":
            size += fmt[i]
            i += 1
        if i >= len(fmt):
            break
        conv = fmt[i]
        i += 1
        if conv == "%":
            if t < len(text) and text[t] == "%":
                t += 1
                continue
            break
        if conv != "c":
            while t < len(text) and text[t].isspace():
                t += 1
        if t >= len(text):
            return (count if count else -1), t
        start = t
        limit = len(text) if not width else min(len(text), t + width)
        if conv == "c":
            t = min(len(text), t + (width or 1))
            value = text[start:t]
        elif conv == "s":
            while t < limit and not text[t].isspace():
                t += 1
            value = text[start:t]
        elif conv in "dius":
            if t < limit and text[t] in "+-":
                t += 1
            while t < limit and text[t].isdigit():
                t += 1
            try:
                value = int(text[start:t])
            except ValueError:
                break
        elif conv in "xX":
            while t < limit and text[t] in "0123456789abcdefABCDEFxX":
                t += 1
            try:
                value = int(text[start:t], 16)
            except ValueError:
                break
        elif conv in "feEgGa":
            while t < limit and text[t] in "+-0123456789.eE":
                t += 1
            try:
                value = float(text[start:t])
            except ValueError:
                break
        else:
            break
        if not skip:
            store(conv, size, value)
            count += 1
    return count, t
