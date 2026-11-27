# More of the standard library: RegExp (with js/regexp.py), the string
# methods that take patterns, Date, ArrayBuffer, typed arrays and DataView.
import math
import struct
import time
from js import rt, regexp
from js.rt import (UNDEF, MISSING, HOLE, JSObject, JSArray, JSFunction, Slot, JSThrow, R, OBJECT_PROTO,
                   REGEXP_PROTO, NAN, INF, to_str, to_num, to_int, get, call, throw_type, throw_range, truthy)
from js.interp import native_fn
from js.builtins import define, fn, getter, ctor, new_target_proto, to_list, py_iterator, callable_

# ---- RegExp ----


try:
    RecursionError
except NameError:                   # MicroPython
    RecursionError = RuntimeError

def _compile(pattern, flags):
    try:
        return regexp.compile(pattern, flags)
    except regexp.RegexError as e:
        rt.throw("SyntaxError", str(e))
    except (RecursionError, IndexError, ValueError) as e:
        rt.throw("SyntaxError", "Invalid regular expression: /%s/: %s" % (pattern, e))


def make_regexp(pattern, flags, proto=REGEXP_PROTO):
    o = JSObject(proto, "RegExp")
    o.x = _compile(pattern, flags)
    o.p["lastIndex"] = Slot(0, e=False, c=False)
    o.ks.append("lastIndex")
    return o


def regex(k):
    """A regex literal (compiled once; a new object each time the code runs)."""
    return make_regexp(k[0], k[1])


def regexp_ctor(F, this, pat=UNDEF, flags=UNDEF, *_):
    proto = new_target_proto(REGEXP_PROTO) if this is MISSING else None
    if isinstance(pat, JSObject) and pat.cls == "RegExp":
        if proto is None and flags is UNDEF:
            return pat
        p = pat.x.pattern
        f = pat.x.flags if flags is UNDEF else to_str(flags)
    else:
        p = "(?:)" if pat is UNDEF else to_str(pat)
        f = "" if flags is UNDEF else to_str(flags)
    return make_regexp(p, f, proto or REGEXP_PROTO)


REGEXP = ctor("RegExp", regexp_ctor, 2, REGEXP_PROTO)


def this_rx(o):
    if isinstance(o, JSObject) and o.cls == "RegExp" and isinstance(o.x, regexp.Regex):
        return o.x
    throw_type("RegExp method called on incompatible receiver")


for _name, _flag in (("global", "g"), ("ignoreCase", "i"), ("multiline", "m"), ("dotAll", "s"),
                     ("unicode", "u"), ("sticky", "y"), ("hasIndices", "d"), ("unicodeSets", "v")):
    getter(REGEXP_PROTO, _name)((lambda f: lambda F, this, *_: f in this_rx(this).flags
                                 if this is not REGEXP_PROTO else UNDEF)(_flag))


@getter(REGEXP_PROTO, "source")
def rx_source(F, this, *_):
    if this is REGEXP_PROTO:
        return "(?:)"
    p = this_rx(this).pattern
    return p.replace("/", "\\/") if "/" in p and "\\/" not in p else (p or "(?:)")


@getter(REGEXP_PROTO, "flags")
def rx_flags(F, this, *_):
    f = this_rx(this).flags
    return "".join(c for c in "dgimsuvy" if c in f)


def _last_index(o):
    v = o.get("lastIndex")
    return int(max(0, to_int(v))) if v is not UNDEF else 0


def _set_last_index(o, v):
    o.put("lastIndex", v)


def rx_exec_raw(o, s):
    """The spec's RegExpBuiltinExec: (start, end, caps) or None; updates lastIndex."""
    rx = this_rx(o)
    glob = "g" in rx.flags or "y" in rx.flags
    start = _last_index(o) if glob else 0
    if start > len(s):
        if glob:
            _set_last_index(o, 0)
        return None
    m = rx.exec(s, start, "y" in rx.flags)
    if m is None:
        if glob:
            _set_last_index(o, 0)
        return None
    if glob:
        _set_last_index(o, m[1])
    return m


def match_array(rx, s, m):
    start, end, caps = m
    items = [s[start:end]]
    for g in range(rx.ngroups):
        a, b = caps[2 * g], caps[2 * g + 1]
        items.append(s[a:b] if a >= 0 and b >= 0 else UNDEF)
    arr = JSArray(items)
    arr.define("index", start)
    arr.define("input", s)
    if rx.names:
        groups = JSObject(None)
        for name, idx in rx.names.items():
            groups.define(name, items[idx])
        arr.define("groups", groups)
    else:
        arr.define("groups", UNDEF)
    if "d" in rx.flags:
        ind = [JSArray([start, end])]
        for g in range(rx.ngroups):
            a, b = caps[2 * g], caps[2 * g + 1]
            ind.append(JSArray([a, b]) if a >= 0 else UNDEF)
        arr.define("indices", JSArray(ind))
    return arr


@fn(REGEXP_PROTO, "exec", 1)
def rx_exec(F, this, s=UNDEF, *_):
    s = to_str(s)
    m = rx_exec_raw(this, s)
    if m is None:
        return None
    return match_array(this.x, s, m)


@fn(REGEXP_PROTO, "test", 1)
def rx_test(F, this, s=UNDEF, *_):
    if isinstance(this, JSObject) and this.cls == "RegExp" and this.p.get("exec") is None and \
            REGEXP_PROTO.p["exec"].v is rx_exec_fn[0]:
        return rx_exec_raw(this, to_str(s)) is not None
    r = rt.callm(this, "exec", to_str(s))
    return r is not None


rx_exec_fn = [REGEXP_PROTO.p["exec"].v]


@fn(REGEXP_PROTO, "toString", 0)
def rx_to_string(F, this, *_):
    return "/%s/%s" % (to_str(get(this, "source")), to_str(get(this, "flags")))


@fn(REGEXP_PROTO, "compile", 2)
def rx_compile(F, this, p=UNDEF, f=UNDEF, *_):
    this.x = _compile("(?:)" if p is UNDEF else to_str(p), "" if f is UNDEF else to_str(f))
    _set_last_index(this, 0)
    return this


def regexp_split(o, s, lim):
    rx = this_rx(o)
    out = []
    if lim == 0:
        return JSArray([])
    if not s:
        m = rx.exec(s, 0, True)
        return JSArray([] if m is not None else [s])
    p = 0
    q = 0
    n = len(s)
    while q < n:
        m = rx.exec(s, q, True)
        if m is None or m[1] == p and m[1] == m[0] and False:
            q += 1
            continue
        e = m[1]
        if e == p or (m[0] == m[1] and m[0] == q and e == p):
            q += 1
            continue
        if m[0] == m[1] and m[0] >= n:
            break
        out.append(s[p:q])
        if len(out) >= lim:
            return JSArray(out)
        caps = m[2]
        for g in range(rx.ngroups):
            a, b = caps[2 * g], caps[2 * g + 1]
            out.append(s[a:b] if a >= 0 and b >= 0 else UNDEF)
            if len(out) >= lim:
                return JSArray(out)
        p = e
        q = p if e > q else q + 1
    out.append(s[p:])
    return JSArray(out[:lim])


def _expand(repl, s, start, end, groups, names_obj):
    """$&, $1, $<name>... in a replacement string."""
    if "$" not in repl:
        return repl
    out = []
    i = 0
    n = len(repl)
    while i < n:
        c = repl[i]
        if c == "$" and i + 1 < n:
            d = repl[i + 1]
            if d == "$":
                out.append("$")
                i += 2
                continue
            if d == "&":
                out.append(s[start:end])
                i += 2
                continue
            if d == "`":
                out.append(s[:start])
                i += 2
                continue
            if d == "'":
                out.append(s[end:])
                i += 2
                continue
            if d.isdigit():
                two = repl[i + 1:i + 3]
                if len(two) == 2 and two.isdigit() and 1 <= int(two) <= len(groups):
                    v = groups[int(two) - 1]
                    out.append("" if v is UNDEF else v)
                    i += 3
                    continue
                k = int(d)
                if 1 <= k <= len(groups):
                    v = groups[k - 1]
                    out.append("" if v is UNDEF else v)
                    i += 2
                    continue
            if d == "<" and names_obj is not None:
                j = repl.find(">", i)
                if j > 0:
                    v = names_obj.get(repl[i + 2:j])
                    out.append("" if v is UNDEF else to_str(v))
                    i = j + 1
                    continue
        out.append(c)
        i += 1
    return "".join(out)


def string_regexp_op(name, s, pat, args):
    is_rx = isinstance(pat, JSObject) and pat.cls == "RegExp" and isinstance(pat.x, regexp.Regex)
    if name == "match":
        if not is_rx:
            pat = make_regexp("(?:)" if pat is UNDEF else to_str(pat), "")
        rx = pat.x
        if "g" not in rx.flags:
            m = rx_exec_raw(pat, s)
            return None if m is None else match_array(rx, s, m)
        _set_last_index(pat, 0)
        out = []
        while True:
            m = rx_exec_raw(pat, s)
            if m is None:
                break
            out.append(s[m[0]:m[1]])
            if m[0] == m[1]:
                _set_last_index(pat, m[1] + 1)
        return JSArray(out) if out else None
    if name == "matchAll":
        if is_rx:
            if "g" not in pat.x.flags:
                throw_type("String.prototype.matchAll called with a non-global RegExp argument")
            rxo = make_regexp(pat.x.pattern, pat.x.flags)
            _set_last_index(rxo, _last_index(pat))
        else:
            rxo = make_regexp(to_str(pat), "g")

        def gen():
            while True:
                m = rx_exec_raw(rxo, s)
                if m is None:
                    return
                if m[0] == m[1]:
                    _set_last_index(rxo, m[1] + 1)
                yield match_array(rxo.x, s, m)
        return py_iterator(gen())
    if name == "search":
        if not is_rx:
            pat = make_regexp(to_str(pat), "")
        m = pat.x.exec(s, 0, "y" in pat.x.flags)
        return -1 if m is None else m[0]
    # replace / replaceAll
    repl = args[0] if args else UNDEF
    fn_ = repl if isinstance(repl, JSFunction) else None
    rtext = None if fn_ is not None else to_str(repl)
    if not is_rx:
        needle = to_str(pat)
        positions = []
        if name == "replace":
            k = s.find(needle)
            if k >= 0:
                positions.append(k)
        else:
            k = s.find(needle)
            step = max(1, len(needle))
            while k >= 0:
                positions.append(k)
                k = s.find(needle, k + step) if needle else (k + 1 if k + 1 <= len(s) else -1)
        if not positions:
            return s
        out = []
        last = 0
        for k in positions:
            out.append(s[last:k])
            if fn_ is not None:
                out.append(to_str(call(fn_, UNDEF, needle, k, s)))
            else:
                out.append(_expand(rtext, s, k, k + len(needle), [], None))
            last = k + len(needle)
        out.append(s[last:])
        return "".join(out)
    rx = pat.x
    glob = "g" in rx.flags
    if name == "replaceAll" and not glob:
        throw_type("replaceAll must be called with a global RegExp")
    matches = []
    if glob:
        _set_last_index(pat, 0)
        while True:
            m = rx_exec_raw(pat, s)
            if m is None:
                break
            matches.append(m)
            if m[0] == m[1]:
                _set_last_index(pat, m[1] + 1)
    else:
        m = rx_exec_raw(pat, s)
        if m is not None:
            matches.append(m)
    if not matches:
        return s
    out = []
    last = 0
    for start, end, caps in matches:
        groups = []
        for g in range(rx.ngroups):
            a, b = caps[2 * g], caps[2 * g + 1]
            groups.append(s[a:b] if a >= 0 and b >= 0 else UNDEF)
        names_obj = None
        if rx.names:
            names_obj = JSObject(None)
            for nm, idx in rx.names.items():
                names_obj.define(nm, groups[idx - 1])
        out.append(s[last:start])
        if fn_ is not None:
            a = [s[start:end]] + groups + [start, s]
            if names_obj is not None:
                a.append(names_obj)
            out.append(to_str(call(fn_, UNDEF, *a)))
        else:
            out.append(_expand(rtext, s, start, end, groups, names_obj))
        last = end
    out.append(s[last:])
    return "".join(out)


for _n in ("match", "matchAll", "search", "replace", "split"):
    pass

# ---- Date ----

DATE_PROTO = JSObject(OBJECT_PROTO, "Date")
CLOCK = {"base_ms": None, "base_mono": 0.0, "tz": 0, "now": None}
MS_DAY = 86400000


def now_ms():
    f = CLOCK["now"]
    if f is not None:
        return f()
    return int(time.time() * 1000)


def tz_offset_ms():
    return CLOCK["tz"] * 60000


def days_from_civil(y, m, d):
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return y + (m <= 2), m, d


def make_time(y, mo, d=1, h=0, mi=0, s=0, ms=0):
    """Fields (month 0-11, may overflow) -> ms since the epoch (as if UTC)."""
    for v in (y, mo, d, h, mi, s, ms):
        if v != v or v in (INF, -INF):
            return NAN
    y = int(y) + int(mo) // 12
    mo = int(mo) % 12
    days = days_from_civil(y, mo + 1, 1) + int(d) - 1
    return days * MS_DAY + int(h) * 3600000 + int(mi) * 60000 + int(s) * 1000 + int(ms)


def fields(t):
    """ms -> (year, month 0-11, day, hours, minutes, seconds, ms, weekday)."""
    t = int(t)
    days, rest = divmod(t, MS_DAY)
    y, m, d = civil_from_days(days)
    wd = (days + 4) % 7
    return y, m - 1, d, rest // 3600000, rest // 60000 % 60, rest // 1000 % 60, rest % 1000, wd


def time_clip(t):
    if t != t or abs(t) > 8.64e15:
        return NAN
    return int(t)


def this_time(o):
    if isinstance(o, JSObject) and o.cls == "Date":
        return o.x
    throw_type("this is not a Date object.")


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_DAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
_MONTHS_LONG = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                "november", "december")


def parse_date(s):
    s = s.strip()
    if not s:
        return NAN
    # ISO 8601
    try:
        return _parse_iso(s)
    except (ValueError, IndexError):
        pass
    return _parse_loose(s)


def _parse_iso(s):
    i = 0
    sign = 1
    if s[0] in "+-":
        sign = -1 if s[0] == "-" else 1
        y = int(s[1:7])
        i = 7
    else:
        y = int(s[0:4])
        if not s[0:4].isdigit():
            raise ValueError
        i = 4
    y *= sign
    mo, d = 1, 1
    if i < len(s) and s[i] == "-":
        mo = int(s[i + 1:i + 3])
        i += 3
        if i < len(s) and s[i] == "-":
            d = int(s[i + 1:i + 3])
            i += 3
    h = mi = sec = ms = 0
    date_only = True
    local = False
    if i < len(s) and s[i] in "T ":
        date_only = False
        h = int(s[i + 1:i + 3])
        mi = int(s[i + 4:i + 6])
        if s[i + 3] != ":":
            raise ValueError
        i += 6
        if i < len(s) and s[i] == ":":
            sec = int(s[i + 1:i + 3])
            i += 3
            if i < len(s) and s[i] in ".,":
                j = i + 1
                while j < len(s) and s[j].isdigit():
                    j += 1
                ms = int((s[i + 1:j] + "000")[:3])
                i = j
        local = True
    off = 0
    if i < len(s):
        if s[i] == "Z":
            local = False
            i += 1
        elif s[i] in "+-":
            sg = 1 if s[i] == "+" else -1
            oh = int(s[i + 1:i + 3])
            om = int(s[i + 4:i + 6]) if s[i + 3:i + 4] == ":" else int(s[i + 3:i + 5])
            off = sg * (oh * 60 + om)
            local = False
            i = len(s)
    if i != len(s):
        raise ValueError
    if not (1 <= mo <= 12 and 1 <= d <= 31 and h <= 24 and mi < 60 and sec < 60):
        return NAN
    t = make_time(y, mo - 1, d, h, mi, sec, ms) - off * 60000
    if local and not date_only:
        t -= tz_offset_ms()
    return t


def _parse_loose(s):
    """'Tue, 01 Jan 2024 10:00:00 GMT', 'January 1, 2024 10:00', '1/2/2024'..."""
    words = s.replace(",", " ").split()
    y = mo = d = None
    h = mi = sec = 0
    off = None
    for w in words:
        lw = w.lower()
        if lw[:3] in [m.lower() for m in _MONTHS] and lw.isalpha():
            mo = [m.lower() for m in _MONTHS].index(lw[:3])
            continue
        if lw[:3] in [x.lower() for x in _DAYS] and lw.isalpha():
            continue
        if lw in ("gmt", "utc", "z"):
            off = 0
            continue
        if ":" in w:
            parts = w.split(":")
            try:
                h = int(parts[0])
                mi = int(parts[1])
                sec = int(float(parts[2])) if len(parts) > 2 else 0
            except ValueError:
                return NAN
            continue
        if (w.startswith("+") or w.startswith("-") or lw.startswith("gmt+") or lw.startswith("gmt-")) and \
                len(w.lstrip("GMTgmt+-")) == 4 and w.lstrip("GMTgmt+-").isdigit():
            v = w.lstrip("GMTgmt")
            sg = -1 if v[0] == "-" else 1
            off = sg * (int(v[1:3]) * 60 + int(v[3:5]))
            continue
        if "/" in w:
            parts = w.split("/")
            try:
                mo = int(parts[0]) - 1
                d = int(parts[1])
                y = int(parts[2]) if len(parts) > 2 else y
            except ValueError:
                return NAN
            continue
        if w.isdigit():
            n = int(w)
            if d is None and n <= 31 and len(w) <= 2:
                d = n
            elif y is None:
                y = n if n >= 100 else 1900 + n if n >= 50 else 2000 + n
            continue
        if lw in ("am", "pm"):
            if lw == "pm" and h < 12:
                h += 12
            if lw == "am" and h == 12:
                h = 0
            continue
        if lw.startswith("(") or lw.endswith(")"):
            continue
        return NAN
    if y is None or mo is None:
        return NAN
    t = make_time(y, mo, d or 1, h, mi, sec, 0)
    if off is None:
        t -= tz_offset_ms()
    else:
        t -= off * 60000
    return t


def date_ctor(F, this, *a):
    if this is not MISSING:
        return date_string(now_ms())
    proto = new_target_proto(DATE_PROTO) or DATE_PROTO
    if not a:
        t = now_ms()
    elif len(a) == 1:
        v = a[0]
        if isinstance(v, JSObject) and v.cls == "Date":
            t = v.x
        else:
            v = rt.to_primitive(v)
            t = parse_date(v) if type(v) is str else to_num(v)
    else:
        nums = [to_num(x) for x in a]
        y = nums[0]
        if y == y and 0 <= y <= 99:
            y = 1900 + int(y)
        t = make_time(y, *nums[1:])
        if t == t:
            t -= tz_offset_ms()
    o = JSObject(proto, "Date")
    o.x = time_clip(t)
    return o


DATE = ctor("Date", date_ctor, 7, DATE_PROTO)


@fn(DATE, "now", 0)
def date_now(F, this, *_):
    return now_ms()


@fn(DATE, "parse", 1)
def date_parse(F, this, s=UNDEF, *_):
    return time_clip(parse_date(to_str(s)))


@fn(DATE, "UTC", 7)
def date_utc(F, this, *a):
    nums = [to_num(x) for x in a] or [NAN]
    y = nums[0]
    if y == y and 0 <= y <= 99:
        y = 1900 + int(y)
    if len(nums) < 2:
        nums.append(0)
    return time_clip(make_time(y, *nums[1:]))


def _local(t):
    return t + tz_offset_ms()


def _tz_text():
    off = CLOCK["tz"]
    sg = "+" if off >= 0 else "-"
    return "GMT%s%02d%02d" % (sg, abs(off) // 60, abs(off) % 60)


def date_string(t):
    if t != t:
        return "Invalid Date"
    y, m, d, h, mi, s, ms, wd = fields(_local(t))
    return "%s %s %02d %s %02d:%02d:%02d %s" % (_DAYS[wd], _MONTHS[m], d, _year(y), h, mi, s, _tz_text())


def _year(y):
    return ("%04d" % y) if y >= 0 else ("-%06d" % -y)


_GETTERS = (("FullYear", 0), ("Month", 1), ("Date", 2), ("Hours", 3), ("Minutes", 4), ("Seconds", 5),
            ("Milliseconds", 6), ("Day", 7))


def _mk_getter(idx, utc):
    def code(F, this, *_):
        t = this_time(this)
        if t != t:
            return NAN
        return fields(t if utc else _local(t))[idx]
    return code


for _n, _i in _GETTERS:
    define(DATE_PROTO, "get" + _n, native_fn(_mk_getter(_i, False), "get" + _n))
    define(DATE_PROTO, "getUTC" + _n, native_fn(_mk_getter(_i, True), "getUTC" + _n))
define(DATE_PROTO, "getYear", native_fn(lambda F, this, *_: _mk_getter(0, False)(F, this) - 1900, "getYear"))


def _mk_setter(first, utc):
    # first: which field the first argument sets (0 year .. 6 ms); the others follow
    def code(F, this, *a):
        t = this_time(this)
        if t != t and first != 0:
            return NAN
        base = 0 if t != t else (t if utc else _local(t))
        f = list(fields(base)[:7])
        for k in range(len(a)):
            if first + k > 6:
                break
            f[first + k] = to_num(a[k])
        if not a:
            f[first] = NAN
        nt = make_time(*f)
        if not utc and nt == nt:
            nt -= tz_offset_ms()
        this.x = time_clip(nt)
        return this.x
    return code


for _n, _i in (("FullYear", 0), ("Month", 1), ("Date", 2), ("Hours", 3), ("Minutes", 4), ("Seconds", 5),
               ("Milliseconds", 6)):
    define(DATE_PROTO, "set" + _n, native_fn(_mk_setter(_i, False), "set" + _n, 1))
    define(DATE_PROTO, "setUTC" + _n, native_fn(_mk_setter(_i, True), "setUTC" + _n, 1))


@fn(DATE_PROTO, "getTime", 0)
def date_get_time(F, this, *_):
    return this_time(this)


define(DATE_PROTO, "valueOf", DATE_PROTO.p["getTime"].v)


@fn(DATE_PROTO, "setTime", 1)
def date_set_time(F, this, t=UNDEF, *_):
    this_time(this)
    this.x = time_clip(to_num(t))
    return this.x


@fn(DATE_PROTO, "getTimezoneOffset", 0)
def date_tz(F, this, *_):
    t = this_time(this)
    return NAN if t != t else -CLOCK["tz"]


@fn(DATE_PROTO, "toISOString", 0)
def date_iso(F, this, *_):
    t = this_time(this)
    if t != t:
        throw_range("Invalid time value")
    y, m, d, h, mi, s, ms, wd = fields(t)
    ys = ("%04d" % y) if 0 <= y <= 9999 else ("%+07d" % y)
    return "%s-%02d-%02dT%02d:%02d:%02d.%03dZ" % (ys, m + 1, d, h, mi, s, ms)


@fn(DATE_PROTO, "toJSON", 1)
def date_json(F, this, *_):
    t = this.x if isinstance(this, JSObject) and this.cls == "Date" else NAN
    if t != t:
        return None
    return date_iso(F, this)


@fn(DATE_PROTO, "toString", 0)
def date_to_string(F, this, *_):
    return date_string(this_time(this))


@fn(DATE_PROTO, "toDateString", 0)
def date_to_date_string(F, this, *_):
    t = this_time(this)
    if t != t:
        return "Invalid Date"
    y, m, d, h, mi, s, ms, wd = fields(_local(t))
    return "%s %s %02d %s" % (_DAYS[wd], _MONTHS[m], d, _year(y))


@fn(DATE_PROTO, "toTimeString", 0)
def date_to_time_string(F, this, *_):
    t = this_time(this)
    if t != t:
        return "Invalid Date"
    y, m, d, h, mi, s, ms, wd = fields(_local(t))
    return "%02d:%02d:%02d %s" % (h, mi, s, _tz_text())


@fn(DATE_PROTO, "toUTCString", 0)
def date_to_utc(F, this, *_):
    t = this_time(this)
    if t != t:
        return "Invalid Date"
    y, m, d, h, mi, s, ms, wd = fields(t)
    return "%s, %02d %s %s %02d:%02d:%02d GMT" % (_DAYS[wd], d, _MONTHS[m], _year(y), h, mi, s)


define(DATE_PROTO, "toGMTString", DATE_PROTO.p["toUTCString"].v)


@fn(DATE_PROTO, "toLocaleDateString", 0)
def date_locale_date(F, this, *_):
    t = this_time(this)
    if t != t:
        return "Invalid Date"
    y, m, d = fields(_local(t))[:3]
    return "%d/%d/%d" % (m + 1, d, y)


@fn(DATE_PROTO, "toLocaleTimeString", 0)
def date_locale_time(F, this, *_):
    t = this_time(this)
    if t != t:
        return "Invalid Date"
    h, mi, s = fields(_local(t))[3:6]
    return "%d:%02d:%02d %s" % ((h % 12) or 12, mi, s, "PM" if h >= 12 else "AM")


@fn(DATE_PROTO, "toLocaleString", 0)
def date_locale(F, this, *_):
    if this_time(this) != this_time(this):
        return "Invalid Date"
    return date_locale_date(F, this) + ", " + date_locale_time(F, this)


def _date_to_prim(F, this, hint=UNDEF, *_):
    if hint == "number":
        return this_time(this)
    return date_to_string(F, this)


define(DATE_PROTO, rt.SYM_TO_PRIMITIVE, native_fn(_date_to_prim, "[Symbol.toPrimitive]", 1), w=False)

# ---- ArrayBuffer, typed arrays, DataView ----

AB_PROTO = JSObject(OBJECT_PROTO, "ArrayBuffer")


def new_buffer(data):
    o = JSObject(AB_PROTO, "ArrayBuffer")
    o.x = data
    return o


def ab_ctor(F, this, n=UNDEF, *_):
    proto = new_target_proto(AB_PROTO) if this is MISSING else None
    if proto is None:
        throw_type("Constructor ArrayBuffer requires 'new'")
    size = int(to_int(n))
    if size < 0 or size > 1 << 30:
        throw_range("Array buffer allocation failed")
    o = JSObject(proto, "ArrayBuffer")
    o.x = bytearray(size)
    return o


ARRAYBUFFER = ctor("ArrayBuffer", ab_ctor, 1, AB_PROTO)
define(AB_PROTO, rt.SYM_TO_STRING_TAG, "ArrayBuffer", w=False)


@getter(AB_PROTO, "byteLength")
def ab_len(F, this, *_):
    return len(this.x)


@fn(AB_PROTO, "slice", 2)
def ab_slice(F, this, a=UNDEF, b=UNDEF, *_):
    n = len(this.x)
    return new_buffer(bytearray(this.x[rt.to_index(a, n, 0):rt.to_index(b, n, n)]))


@fn(ARRAYBUFFER, "isView", 1)
def ab_is_view(F, this, v=UNDEF, *_):
    return isinstance(v, (TypedArray,)) or (isinstance(v, JSObject) and v.cls == "DataView")


TYPES = {"Int8Array": ("b", 1), "Uint8Array": ("B", 1), "Uint8ClampedArray": ("C", 1), "Int16Array": ("h", 2),
         "Uint16Array": ("H", 2), "Int32Array": ("i", 4), "Uint32Array": ("I", 4), "Float32Array": ("f", 4),
         "Float64Array": ("d", 8), "BigInt64Array": ("q", 8), "BigUint64Array": ("Q", 8)}


class TypedArray(JSObject):
    __slots__ = ("buf", "off", "length", "code", "size", "kind")

    def own(self, k):
        if type(k) is str and k and "0" <= k[0] <= "9" and k.isdigit():
            i = int(k)
            if i < self.length:
                return self.at(i)
            return UNDEF
        return self.p.get(k, MISSING)

    def own_keys(self):
        return [str(i) for i in range(self.length)] + JSObject.own_keys(self)

    def at(self, i):
        code = self.code
        if code == "B" or code == "C":
            return self.buf.x[self.off + i]
        v = struct.unpack_from("<" + code, self.buf.x, self.off + i * self.size)[0]
        if code in "fd":
            return rt.norm(int(v)) if v == v and v not in (INF, -INF) and v == int(v) and abs(v) < 2 ** 53 else v
        return v

    def set_at(self, i, v):
        if i < 0 or i >= self.length:
            return
        code = self.code
        n = to_num(v)
        if code == "C":
            n = 0 if n != n else int(max(0, min(255, math.floor(n + 0.5) if n - math.floor(n) != 0.5 else
                                         (math.floor(n) if math.floor(n) % 2 == 0 else math.floor(n) + 1))))
            self.buf.x[self.off + i] = n
            return
        if code in "fd":
            struct.pack_into("<" + code, self.buf.x, self.off + i * self.size, float(n))
            return
        if n != n or n in (INF, -INF):
            n = 0
        n = int(n)
        bits = self.size * 8
        n &= (1 << bits) - 1
        if code in "bhiq" and n >= 1 << (bits - 1):
            n -= 1 << bits
        if code == "B":
            self.buf.x[self.off + i] = n
            return
        struct.pack_into("<" + code, self.buf.x, self.off + i * self.size, n)

    def get(self, k, recv=None):
        if type(k) is str and k and "0" <= k[0] <= "9" and k.isdigit():
            i = int(k)
            return self.at(i) if i < self.length else UNDEF
        if k == "length":
            return self.length
        return JSObject.get(self, k, recv)

    def put(self, k, v, recv=None):
        if type(k) is str and k and "0" <= k[0] <= "9" and k.isdigit():
            self.set_at(int(k), v)
            return
        JSObject.put(self, k, v, recv)


TA_PROTO = JSObject(OBJECT_PROTO, "TypedArray")
TA_PROTOS = {}


def make_typed(kind, length=0, buf=None, off=0, proto=None):
    code, size = TYPES[kind]
    o = TypedArray(proto or TA_PROTOS[kind], kind)
    o.kind = kind
    o.code = code
    o.size = size
    if buf is None:
        buf = new_buffer(bytearray(length * size))
    o.buf = buf
    o.off = off
    o.length = length
    return o


def _ta_ctor(kind):
    code, size = TYPES[kind]

    def c(F, this, a=UNDEF, off=UNDEF, length=UNDEF, *_):
        proto = new_target_proto(TA_PROTOS[kind]) if this is MISSING else None
        if proto is None:
            throw_type("Constructor %s requires 'new'" % kind)
        if isinstance(a, JSObject) and a.cls == "ArrayBuffer":
            o = int(to_int(off)) if off is not UNDEF else 0
            n = (len(a.x) - o) // size if length is UNDEF else int(to_int(length))
            if o % size or n < 0 or o + n * size > len(a.x):
                throw_range("Invalid typed array length")
            return make_typed(kind, n, a, o, proto)
        if isinstance(a, JSObject):
            vals = list(rt.iterate(a)) if isinstance(get(a, rt.SYM_ITERATOR), JSFunction) else to_list(a)
            t = make_typed(kind, len(vals), proto=proto)
            for i in range(len(vals)):
                t.set_at(i, vals[i])
            return t
        n = 0 if a is UNDEF else int(to_int(a))
        if n < 0:
            throw_range("Invalid typed array length: %d" % n)
        return make_typed(kind, n, proto=proto)
    return c


TYPED_CTORS = {}
for _kind in TYPES:
    _p = JSObject(TA_PROTO, _kind)
    TA_PROTOS[_kind] = _p
    TYPED_CTORS[_kind] = ctor(_kind, _ta_ctor(_kind), 3, _p)
    define(TYPED_CTORS[_kind], "BYTES_PER_ELEMENT", TYPES[_kind][1], w=False, c=False)
    define(_p, "BYTES_PER_ELEMENT", TYPES[_kind][1], w=False, c=False)
    define(TYPED_CTORS[_kind], "from", native_fn(
        (lambda k: lambda F, this, src=UNDEF, f=UNDEF, *_: _ta_from(k, src, f))(_kind), "from", 1))
    define(TYPED_CTORS[_kind], "of", native_fn(
        (lambda k: lambda F, this, *a: _ta_from(k, JSArray(list(a)), UNDEF))(_kind), "of", 0))


def _ta_from(kind, src, f):
    vals = list(rt.iterate(src)) if (isinstance(src, JSObject) and isinstance(get(src, rt.SYM_ITERATOR),
                                                                             JSFunction)) else to_list(src)
    if isinstance(f, JSFunction):
        vals = [call(f, UNDEF, vals[i], i) for i in range(len(vals))]
    t = make_typed(kind, len(vals))
    for i in range(len(vals)):
        t.set_at(i, vals[i])
    return t


def this_ta(o):
    if isinstance(o, TypedArray):
        return o
    throw_type("this is not a typed array.")


@getter(TA_PROTO, "length")
def ta_length(F, this, *_):
    return this_ta(this).length


@getter(TA_PROTO, "byteLength")
def ta_byte_length(F, this, *_):
    t = this_ta(this)
    return t.length * t.size


@getter(TA_PROTO, "byteOffset")
def ta_byte_offset(F, this, *_):
    return this_ta(this).off


@getter(TA_PROTO, "buffer")
def ta_buffer(F, this, *_):
    return this_ta(this).buf


def _ta_vals(t):
    return [t.at(i) for i in range(t.length)]


@fn(TA_PROTO, "set", 2)
def ta_set(F, this, src=UNDEF, off=UNDEF, *_):
    t = this_ta(this)
    o = int(to_int(off)) if off is not UNDEF else 0
    vals = _ta_vals(src) if isinstance(src, TypedArray) else to_list(src)
    if o + len(vals) > t.length:
        throw_range("offset is out of bounds")
    if isinstance(src, TypedArray) and src.code == t.code and t.code in "BC":
        t.buf.x[t.off + o:t.off + o + len(vals)] = src.buf.x[src.off:src.off + len(vals)]
        return UNDEF
    for i in range(len(vals)):
        t.set_at(o + i, vals[i])
    return UNDEF


@fn(TA_PROTO, "subarray", 2)
def ta_subarray(F, this, a=UNDEF, b=UNDEF, *_):
    t = this_ta(this)
    n = t.length
    s = rt.to_index(a, n, 0)
    e = rt.to_index(b, n, n)
    return make_typed(t.kind, max(0, e - s), t.buf, t.off + s * t.size)


@fn(TA_PROTO, "slice", 2)
def ta_slice(F, this, a=UNDEF, b=UNDEF, *_):
    t = this_ta(this)
    n = t.length
    s = rt.to_index(a, n, 0)
    e = rt.to_index(b, n, n)
    out = make_typed(t.kind, max(0, e - s))
    out.buf.x[:] = t.buf.x[t.off + s * t.size:t.off + e * t.size] if e > s else b""
    return out


@fn(TA_PROTO, "fill", 1)
def ta_fill(F, this, v=UNDEF, a=UNDEF, b=UNDEF, *_):
    t = this_ta(this)
    n = t.length
    for i in range(rt.to_index(a, n, 0), rt.to_index(b, n, n)):
        t.set_at(i, v)
    return this


def _ta_generic(name, f):
    define(TA_PROTO, name, native_fn(f, name, 1))


def _ta_map(F, this, f=UNDEF, th=UNDEF, *_):
    t = this_ta(this)
    callable_(f)
    out = make_typed(t.kind, t.length)
    for i in range(t.length):
        out.set_at(i, call(f, th, t.at(i), i, this))
    return out


def _ta_filter(F, this, f=UNDEF, th=UNDEF, *_):
    t = this_ta(this)
    vals = [v for i, v in enumerate(_ta_vals(t)) if truthy(call(f, th, v, i, this))]
    out = make_typed(t.kind, len(vals))
    for i in range(len(vals)):
        out.set_at(i, vals[i])
    return out


_ta_generic("map", _ta_map)
_ta_generic("filter", _ta_filter)


def _via_array(name):
    from js import builtins

    def code(F, this, *a):
        t = this_ta(this)
        arr = JSArray(_ta_vals(t))
        m = rt.ARRAY_PROTO.p[name].v if type(rt.ARRAY_PROTO.p[name]) is Slot else rt.ARRAY_PROTO.p[name]
        r = m.info.code(m, arr, *a)
        if name in ("reverse", "sort", "copyWithin"):
            for i in range(t.length):
                t.set_at(i, arr.a[i])
            return this
        return r
    return code


for _n in ("forEach", "indexOf", "lastIndexOf", "includes", "join", "find", "findIndex", "findLast",
           "findLastIndex", "some", "every", "reduce", "reduceRight", "reverse", "sort", "at", "keys", "values",
           "entries", "copyWithin", "toString", "toLocaleString"):
    define(TA_PROTO, _n, native_fn(_via_array(_n), _n, 1))
define(TA_PROTO, rt.SYM_ITERATOR, TA_PROTO.p["values"].v)

DV_PROTO = JSObject(OBJECT_PROTO, "DataView")


def dv_ctor(F, this, buf=UNDEF, off=UNDEF, length=UNDEF, *_):
    proto = new_target_proto(DV_PROTO) if this is MISSING else None
    if proto is None:
        throw_type("Constructor DataView requires 'new'")
    if not (isinstance(buf, JSObject) and buf.cls == "ArrayBuffer"):
        throw_type("First argument to DataView constructor must be an ArrayBuffer")
    o = JSObject(proto, "DataView")
    start = int(to_int(off)) if off is not UNDEF else 0
    n = len(buf.x) - start if length is UNDEF else int(to_int(length))
    o.x = (buf, start, n)
    return o


DATAVIEW = ctor("DataView", dv_ctor, 1, DV_PROTO)
for _name, _code in (("Int8", "b"), ("Uint8", "B"), ("Int16", "h"), ("Uint16", "H"), ("Int32", "i"),
                     ("Uint32", "I"), ("Float32", "f"), ("Float64", "d"), ("BigInt64", "q"), ("BigUint64", "Q")):
    def _getter(code):
        def g(F, this, off=UNDEF, little=UNDEF, *_):
            buf, start, n = this.x
            o = int(to_int(off))
            size = struct.calcsize(code)
            if o < 0 or o + size > n:
                throw_range("Offset is outside the bounds of the DataView")
            v = struct.unpack_from(("<" if truthy(little) else ">") + code, buf.x, start + o)[0]
            return rt.norm(v) if type(v) is int else v
        return g

    def _setter(code):
        def s(F, this, off=UNDEF, v=UNDEF, little=UNDEF, *_):
            buf, start, n = this.x
            o = int(to_int(off))
            size = struct.calcsize(code)
            if o < 0 or o + size > n:
                throw_range("Offset is outside the bounds of the DataView")
            x = to_num(v)
            if code not in "fd":
                x = int(x) if x == x and x not in (INF, -INF) else 0
                bits = size * 8
                x &= (1 << bits) - 1
                if code.islower() and x >= 1 << (bits - 1):
                    x -= 1 << bits
            struct.pack_into(("<" if truthy(little) else ">") + code, buf.x, start + o, x)
            return UNDEF
        return s
    define(DV_PROTO, "get" + _name, native_fn(_getter(_code), "get" + _name, 1))
    define(DV_PROTO, "set" + _name, native_fn(_setter(_code), "set" + _name, 2))
getter(DV_PROTO, "byteLength")(lambda F, this, *_: this.x[2])
getter(DV_PROTO, "byteOffset")(lambda F, this, *_: this.x[1])
getter(DV_PROTO, "buffer")(lambda F, this, *_: this.x[0])


def install(g):
    define(g, "RegExp", REGEXP)
    define(g, "Date", DATE)
    define(g, "ArrayBuffer", ARRAYBUFFER)
    define(g, "DataView", DATAVIEW)
    for k, c in TYPED_CTORS.items():
        define(g, k, c)
