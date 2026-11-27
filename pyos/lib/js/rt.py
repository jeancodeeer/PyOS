# The JavaScript runtime: values, objects, conversions, operators, property
# access and calls. The code the compiler makes (compiler.py) calls these.
#
# Values: undefined is UNDEF, null is None, booleans are bool, numbers are int
# or float, strings are str, everything else is a JSObject (or a Symbol).
import math

try:
    RecursionError
except NameError:                   # MicroPython
    RecursionError = RuntimeError

INF = float("inf")
NAN = float("nan")
MAX_SAFE = 9007199254740991


class Undefined:
    __slots__ = ()

    def __bool__(self):
        return False

    def __repr__(self):
        return "undefined"


UNDEF = Undefined()
MISSING = object()


class Symbol:
    __slots__ = ("desc",)

    def __init__(self, desc):
        self.desc = desc

    def __repr__(self):
        return "Symbol(%s)" % ("" if self.desc is UNDEF else self.desc)


SYM_ITERATOR = Symbol("Symbol.iterator")
SYM_ASYNC_ITERATOR = Symbol("Symbol.asyncIterator")
SYM_HAS_INSTANCE = Symbol("Symbol.hasInstance")
SYM_TO_PRIMITIVE = Symbol("Symbol.toPrimitive")
SYM_TO_STRING_TAG = Symbol("Symbol.toStringTag")
SYM_SPECIES = Symbol("Symbol.species")
SYM_UNSCOPABLES = Symbol("Symbol.unscopables")
SYM_MATCH_ALL = Symbol("Symbol.matchAll")


class Slot:
    """A property that is not a plain writable/enumerable value: an accessor, or other attributes."""
    __slots__ = ("v", "get", "set", "acc", "e", "w", "c")

    def __init__(self, v=UNDEF, get=None, set=None, acc=False, e=True, w=True, c=True):
        self.v = v
        self.get = get
        self.set = set
        self.acc = acc
        self.e = e
        self.w = w
        self.c = c


# ---- exceptions ----

class JSThrow(Exception):
    """A JavaScript exception: .value is what was thrown."""

    def __init__(self, value):
        super().__init__()
        self.value = value

    def __str__(self):
        try:
            v = self.value
            if isinstance(v, JSObject):
                msg = get(v, "message")
                name = get(v, "name")
                if msg is not UNDEF or name is not UNDEF:
                    s = to_str(name) + ": " + to_str(msg)
                    st = v.p.get("stack")
                    if type(st) is str and st:
                        s += "\n" + st
                    return s
            return to_str(v)
        except Exception:
            return "<JavaScript exception>"


class Control(BaseException):
    pass


class BreakTo(Control):
    def __init__(self, label):
        super().__init__()
        self.label = label


class ContinueTo(Control):
    def __init__(self, label):
        super().__init__()
        self.label = label


class GenReturn(Control):
    """generator.return(v): finishes the generator, running its finally blocks."""

    def __init__(self, value):
        super().__init__()
        self.value = value


class Interrupted(Control):
    """The script ran too long (or used too much memory): not catchable by JavaScript."""

    def __init__(self, why):
        super().__init__()
        self.why = why


# ---- objects ----

class JSObject:
    __slots__ = ("p", "ks", "proto", "cls", "ext", "x")

    def __init__(self, proto=None, cls="Object"):
        self.p = {}
        self.ks = []
        self.proto = proto
        self.cls = cls
        self.ext = True
        self.x = None                   # internal data (a Date's time, a Map's table...)

    # own properties
    def own(self, k):
        return self.p.get(k, MISSING)

    def own_keys(self):
        """Own property keys in JavaScript's order: integer keys, strings, then symbols."""
        ks = self.ks
        ints = []
        strs = []
        syms = []
        for k in ks:
            if type(k) is str:
                if k and k[0] in "0123456789" and k.isdigit() and (k == "0" or k[0] != "0"):
                    ints.append(k)
                else:
                    strs.append(k)
            else:
                syms.append(k)
        if ints:
            ints.sort(key=int)
            return ints + strs + syms
        if syms:
            return strs + syms
        return strs

    def define(self, k, v):
        p = self.p
        if k not in p:
            self.ks.append(k)
        p[k] = v

    def remove(self, k):
        p = self.p
        if k in p:
            v = p[k]
            if type(v) is Slot and not v.c:
                return False
            del p[k]
            self.ks.remove(k)
        return True

    def get(self, k, recv=None):
        o = self
        while o is not None:
            if type(o) is JSObject:
                v = o.p.get(k, MISSING)
            else:
                v = o.own(k)
            if v is not MISSING:
                if type(v) is Slot:
                    if v.acc:
                        if v.get is None:
                            return UNDEF
                        return v.get.info.code(v.get, self if recv is None else recv)
                    return v.v
                return v
            o = o.proto
        return UNDEF

    def put(self, k, v, recv=None):
        p = self.p
        cur = p.get(k, MISSING)
        if cur is MISSING:
            # a setter (or a read-only property) up the prototype chain?
            o = self.proto
            while o is not None:
                c = o.p.get(k, MISSING) if type(o) is JSObject else o.own(k)
                if c is not MISSING:
                    if type(c) is Slot:
                        if c.acc:
                            if c.set is not None:
                                c.set.info.code(c.set, self if recv is None else recv, v)
                            return
                        if not c.w:
                            return
                    break
                o = o.proto
            if not self.ext:
                return
            self.ks.append(k)
            p[k] = v
            return
        if type(cur) is Slot:
            if cur.acc:
                if cur.set is not None:
                    cur.set.info.code(cur.set, self if recv is None else recv, v)
                return
            if cur.w:
                cur.v = v
            return
        p[k] = v

    def has(self, k):
        o = self
        while o is not None:
            if o.own(k) is not MISSING:
                return True
            o = o.proto
        return False

    def __repr__(self):
        return "[object %s]" % self.cls


class JSArray(JSObject):
    __slots__ = ("a",)

    def __init__(self, items=None, proto=None):
        JSObject.__init__(self, ARRAY_PROTO if proto is None else proto, "Array")
        self.a = [] if items is None else items

    def own(self, k):
        if type(k) is str:
            if k == "length":
                return len(self.a)
            c = k[0] if k else ""
            if "0" <= c <= "9" and k.isdigit():
                i = int(k)
                if i < len(self.a) and (k == "0" or c != "0"):
                    v = self.a[i]
                    return MISSING if v is HOLE else v
        return self.p.get(k, MISSING)

    def own_keys(self):
        keys = [str(i) for i in range(len(self.a)) if self.a[i] is not HOLE]
        keys.append("length")
        return keys + JSObject.own_keys(self)

    def get(self, k, recv=None):
        if type(k) is str:
            if k == "length":
                return len(self.a)
            c = k[0] if k else ""
            if "0" <= c <= "9" and k.isdigit() and (k == "0" or c != "0"):
                i = int(k)
                if i < len(self.a):
                    v = self.a[i]
                    if v is not HOLE:
                        return v
        return JSObject.get(self, k, recv)

    def put(self, k, v, recv=None):
        if type(k) is str:
            if k == "length":
                set_length(self, v)
                return
            c = k[0] if k else ""
            if "0" <= c <= "9" and k.isdigit() and (k == "0" or c != "0"):
                self.set_index(int(k), v)
                return
        JSObject.put(self, k, v, recv)

    def set_index(self, i, v):
        a = self.a
        n = len(a)
        if i < n:
            a[i] = v
        elif i == n:
            if self.ext:
                a.append(v)
        elif i < n + 10000000 and self.ext:
            a.extend([HOLE] * (i - n))
            a.append(v)

    def remove(self, k):
        if type(k) is str and k.isdigit():
            i = int(k)
            if i < len(self.a):
                if i == len(self.a) - 1 and False:
                    self.a.pop()
                else:
                    self.a[i] = HOLE
                return True
        if k == "length":
            return False
        return JSObject.remove(self, k)


class Hole:
    __slots__ = ()

    def __repr__(self):
        return "<hole>"


HOLE = Hole()


def set_length(arr, v):
    n = to_num(v)
    if n != n or n < 0 or n != int(n) or n > 4294967295:
        throw_range("Invalid array length")
    n = int(n)
    a = arr.a
    if n < len(a):
        del a[n:]
    elif n > len(a):
        a.extend([HOLE] * (n - len(a)))


class FuncInfo:
    """What a function is: its code (compiled the first time it runs) and how it is called."""
    __slots__ = ("code", "name", "nparams", "kind", "node", "unit", "ctor", "strict", "src", "pyname", "fields",
                 "derived", "id")

    def __init__(self, code, name="", nparams=0, kind="normal", ctor=False):
        self.code = code
        self.name = name
        self.nparams = nparams
        self.kind = kind            # normal, arrow, method, gen, async, asyncgen, class, native
        self.node = None
        self.unit = None
        self.ctor = ctor
        self.strict = False
        self.src = None
        self.pyname = None
        self.fields = None
        self.derived = False
        self.id = 0


class JSFunction(JSObject):
    __slots__ = ("info", "env", "home", "this", "fields", "bound")

    def __init__(self, info, env=None, home=None, proto=None):
        JSObject.__init__(self, FUNCTION_PROTO if proto is None else proto, "Function")
        self.info = info
        self.env = env
        self.home = home            # the object the method was defined on (for super)
        self.this = None            # arrows and bound functions: the `this` they keep
        self.fields = None          # classes: the instance field initializer
        self.bound = None

    def own(self, k):
        v = self.p.get(k, MISSING)
        if v is MISSING and (k == "prototype" or k == "name" or k == "length"):
            v = self._lazy(k)
        return v

    def _lazy(self, k):
        info = self.info
        if k == "prototype":
            if not (info.ctor and info.kind != "native") and info.kind not in ("gen", "asyncgen"):
                return MISSING
            proto = JSObject(OBJECT_PROTO)
            if info.kind not in ("gen", "asyncgen"):
                proto.p["constructor"] = Slot(self, e=False)
                proto.ks.append("constructor")
            else:
                proto.proto = GENERATOR_PROTO
            s = Slot(proto, e=False, c=False, w=info.kind != "class")
            self.p["prototype"] = s
            self.ks.append("prototype")
            return proto
        if k == "name":
            s = Slot(info.name, e=False, w=False)
            self.p["name"] = s
            self.ks.append("name")
            return info.name
        if k == "length":
            s = Slot(info.nparams, e=False, w=False)
            self.p["length"] = s
            self.ks.append("length")
            return info.nparams
        return MISSING

    def own_keys(self):
        for k in ("length", "name", "prototype"):
            if k not in self.p:
                self._lazy(k)
        return JSObject.own_keys(self)

    def get(self, k, recv=None):
        v = self.p.get(k, MISSING)
        if v is MISSING:
            if k == "prototype" or k == "name" or k == "length":
                v = self._lazy(k)
                if v is not MISSING:
                    return v
            return JSObject.get(self, k, recv)
        if type(v) is Slot:
            return JSObject.get(self, k, recv)
        return v

    def put(self, k, v, recv=None):
        if (k == "prototype" or k == "name" or k == "length") and k not in self.p:
            self._lazy(k)
        JSObject.put(self, k, v, recv)


# The standard prototypes: made here, filled in by builtins.py
OBJECT_PROTO = JSObject(None)
FUNCTION_PROTO = JSObject(OBJECT_PROTO, "Function")
ARRAY_PROTO = JSArray([], OBJECT_PROTO)
STRING_PROTO = JSObject(OBJECT_PROTO, "String")
NUMBER_PROTO = JSObject(OBJECT_PROTO, "Number")
BOOLEAN_PROTO = JSObject(OBJECT_PROTO, "Boolean")
SYMBOL_PROTO = JSObject(OBJECT_PROTO, "Symbol")
ERROR_PROTO = JSObject(OBJECT_PROTO, "Error")
ITERATOR_PROTO = JSObject(OBJECT_PROTO)
GENERATOR_PROTO = JSObject(ITERATOR_PROTO, "Generator")
ASYNC_GENERATOR_PROTO = JSObject(OBJECT_PROTO, "AsyncGenerator")
PROMISE_PROTO = JSObject(OBJECT_PROTO, "Promise")
REGEXP_PROTO = JSObject(OBJECT_PROTO, "RegExp")
ERROR_PROTOS = {}               # "TypeError" -> its prototype (filled by builtins)


class Realm:
    """The global state: the global object, the global lexical names, the job queue."""
    glob = None                 # the global object
    lex = {}                    # let/const/class at the top of scripts
    jobs = []                   # promise jobs
    newtarget = UNDEF
    deadline = 0
    budget = 0
    ticks_ms = None
    mem_cap = 0
    stack = []                  # names of the functions running (for error stacks)


R = Realm


# ---- errors ----

def make_error(kind, msg):
    proto = ERROR_PROTOS.get(kind, ERROR_PROTO)
    e = JSObject(proto, "Error")
    e.p["message"] = Slot(msg, e=False)
    e.ks.append("message")
    e.p["stack"] = Slot("    at " + " < ".join(reversed(R.stack[-8:])) if R.stack else "", e=False)
    e.ks.append("stack")
    return e


def throw(kind, msg):
    raise JSThrow(make_error(kind, msg))


def throw_type(msg):
    raise JSThrow(make_error("TypeError", msg))


def throw_range(msg):
    raise JSThrow(make_error("RangeError", msg))


def throw_ref(msg):
    raise JSThrow(make_error("ReferenceError", msg))


def catch(e):
    """A Python exception caught by a JavaScript catch: the JavaScript value."""
    if isinstance(e, JSThrow):
        return e.value
    if isinstance(e, Control) or isinstance(e, KeyboardInterrupt) or isinstance(e, GeneratorExit) or \
            isinstance(e, SystemExit):
        raise e
    if isinstance(e, RecursionError):
        return make_error("RangeError", "Maximum call stack size exceeded")
    if isinstance(e, MemoryError):
        return make_error("RangeError", "out of memory")
    if isinstance(e, ZeroDivisionError):
        return make_error("RangeError", "division by zero")
    return make_error("InternalError", "%s: %s" % (type(e).__name__, e))


# ---- types and conversions ----

def typeof(v):
    if v is UNDEF:
        return "undefined"
    if v is None:
        return "object"
    t = type(v)
    if t is str:
        return "string"
    if t is bool:
        return "boolean"
    if t is int or t is float:
        return "number"
    if isinstance(v, JSFunction):
        return "function"
    if t is Symbol:
        return "symbol"
    return "object"


def is_object(v):
    return isinstance(v, JSObject)


def is_callable(v):
    return isinstance(v, JSFunction)


def truthy(v):
    if v is True:
        return True
    if not v:
        return False
    if type(v) is float:
        return v == v
    return True


def num_str(v, radix=10):
    if type(v) is int:
        if radix == 10:
            return str(v)
        return int_radix(v, radix)
    if v != v:
        return "NaN"
    if v == INF:
        return "Infinity"
    if v == -INF:
        return "-Infinity"
    if v == 0:
        return "0"
    if radix != 10:
        return float_radix(v, radix)
    if v == int(v) and abs(v) < 9007199254740992.0:
        return str(int(v))
    # the shortest digits that read back as the same number
    s = None
    for p in range(1, 18):
        t = "%.*e" % (p - 1, v)
        if float(t) == v:
            s = t
            break
    if s is None:
        s = "%.16e" % v
    mant, _, ex = s.partition("e")
    e = int(ex)
    neg = mant.startswith("-")
    if neg:
        mant = mant[1:]
    digits = mant.replace(".", "")
    digits = digits.rstrip("0") or "0"
    k = len(digits)
    n = e + 1
    if k <= n <= 21:
        out = digits + "0" * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + digits
    else:
        e1 = n - 1
        es = ("+" if e1 >= 0 else "-") + str(abs(e1))
        out = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + es
    return "-" + out if neg else out


_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def int_radix(v, radix):
    if v == 0:
        return "0"
    neg = v < 0
    v = abs(v)
    out = []
    while v:
        v, r = divmod(v, radix)
        out.append(_DIGITS[r])
    if neg:
        out.append("-")
    return "".join(reversed(out))


def float_radix(v, radix):
    neg = v < 0
    v = abs(v)
    ip = int(v)
    fp = v - ip
    s = int_radix(ip, radix)
    if fp:
        out = []
        for _ in range(52):
            fp *= radix
            d = int(fp)
            out.append(_DIGITS[d])
            fp -= d
            if not fp:
                break
        s += "." + "".join(out).rstrip("0")
    return "-" + s if neg else s


def to_str(v):
    t = type(v)
    if t is str:
        return v
    if t is int:
        return str(v)
    if t is float:
        return num_str(v)
    if t is bool:
        return "true" if v else "false"
    if v is None:
        return "null"
    if v is UNDEF:
        return "undefined"
    if t is Symbol:
        throw_type("Cannot convert a Symbol value to a string")
    return to_str(to_primitive(v, "string"))


def to_key(v):
    """A property key: a string or a Symbol."""
    t = type(v)
    if t is str:
        return v
    if t is int:
        return str(v)
    if t is Symbol:
        return v
    if t is float:
        return num_str(v)
    if isinstance(v, JSObject):
        v = to_primitive(v, "string")
        if type(v) is Symbol:
            return v
    return to_str(v)


_WS = " \t\n\r\x0b\x0c\xa0﻿                　"


def str_to_num(s):
    s = s.strip(_WS)
    if not s:
        return 0
    try:
        if s[0] == "0" and len(s) > 2 and s[1] in "xXoObB":
            return int(s[2:], {"x": 16, "o": 8, "b": 2}[s[1].lower()])
        if s in ("Infinity", "+Infinity"):
            return INF
        if s == "-Infinity":
            return -INF
        c = s[-1]
        if not ("0" <= c <= "9" or c == "."):
            return NAN
        for ch in s:
            if not ("0" <= ch <= "9" or ch in ".eE+-"):
                return NAN
        if "." not in s and "e" not in s and "E" not in s:
            v = int(s)
            return v if -MAX_SAFE <= v <= MAX_SAFE else float(v)
        f = float(s)
        if f == int(f) and -MAX_SAFE <= f <= MAX_SAFE:
            return int(f)
        return f
    except (ValueError, OverflowError):
        return NAN


def to_num(v):
    t = type(v)
    if t is int or t is float:
        return v
    if t is bool:
        return 1 if v else 0
    if t is str:
        return str_to_num(v)
    if v is None:
        return 0
    if v is UNDEF:
        return NAN
    if t is Symbol:
        throw_type("Cannot convert a Symbol value to a number")
    return to_num(to_primitive(v, "number"))


def to_numeric(v):
    t = type(v)
    if t is int or t is float:
        return v
    return to_num(v)


def norm(v):
    """A number result: an int when exact (and safe), else a float."""
    if type(v) is int:
        if -MAX_SAFE <= v <= MAX_SAFE:
            return v
        return float(v)
    return v


def to_int(v):
    """ToIntegerOrInfinity."""
    n = to_num(v)
    if type(n) is int:
        return n
    if n != n:
        return 0
    if n == INF or n == -INF:
        return n
    return int(n)


def to_int32(v):
    t = type(v)
    if t is int:
        if -2147483648 <= v <= 2147483647:
            return v
    else:
        v = to_num(v)
        if type(v) is float:
            if v != v or v == INF or v == -INF:
                return 0
            v = int(v)
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


def to_uint32(v):
    t = type(v)
    if t is not int:
        v = to_num(v)
        if type(v) is float:
            if v != v or v == INF or v == -INF:
                return 0
            v = int(v)
    return v & 0xFFFFFFFF


def to_index(v, length, default):
    """A relative index (slice, at...) into 0..length."""
    if v is UNDEF:
        return default
    n = to_int(v)
    if n < 0:
        n += length
        return 0 if n < 0 else int(n)
    return length if n > length else int(n)


def to_primitive(v, hint="default"):
    if not isinstance(v, JSObject):
        return v
    f = v.get(SYM_TO_PRIMITIVE)
    if f is not UNDEF and f is not None:
        r = call(f, v, hint)
        if isinstance(r, JSObject):
            throw_type("Cannot convert object to primitive value")
        return r
    order = ("toString", "valueOf") if hint == "string" else ("valueOf", "toString")
    for name in order:
        f = v.get(name)
        if isinstance(f, JSFunction):
            r = f.info.code(f, v)
            if not isinstance(r, JSObject):
                return r
    throw_type("Cannot convert object to primitive value")


def to_obj(v):
    if isinstance(v, JSObject):
        return v
    if v is None or v is UNDEF:
        throw_type("Cannot convert undefined or null to object")
    o = JSObject(proto_of_primitive(v), "Primitive")
    o.x = v
    if type(v) is str:
        o.cls = "String"
    elif type(v) is bool:
        o.cls = "Boolean"
    elif type(v) is Symbol:
        o.cls = "Symbol"
    else:
        o.cls = "Number"
    return o


def proto_of_primitive(v):
    t = type(v)
    if t is str:
        return STRING_PROTO
    if t is int or t is float:
        return NUMBER_PROTO
    if t is bool:
        return BOOLEAN_PROTO
    if t is Symbol:
        return SYMBOL_PROTO
    return OBJECT_PROTO


# ---- property access ----

def _str_get(s, k):
    if type(k) is str:
        if k == "length":
            return len(s)
        c = k[0] if k else ""
        if "0" <= c <= "9" and k.isdigit():
            i = int(k)
            if i < len(s) and (k == "0" or c != "0"):
                return s[i]
            return UNDEF
    return STRING_PROTO.get(k, s)


def _what(v):
    return "undefined" if v is UNDEF else "null"


def get(o, k):
    """o[k] for any value o and a key k (already a string or Symbol)."""
    if isinstance(o, JSObject):
        return o.get(k)
    t = type(o)
    if t is str:
        return _str_get(o, k)
    if o is UNDEF or o is None:
        throw_type("Cannot read properties of %s (reading '%s')" % (_what(o), to_str(k) if type(k) is str else k))
    return proto_of_primitive(o).get(k, o)


def getv(o, k):
    """o[k] where k is any value (computed member access)."""
    tk = type(k)
    if tk is int:
        if type(o) is JSArray:
            if 0 <= k < len(o.a):
                v = o.a[k]
                if v is not HOLE:
                    return v
                return get(o, str(k))
            if k >= 0:
                return o.get(str(k))
        elif type(o) is str:
            if 0 <= k < len(o):
                return o[k]
            if k >= 0:
                return UNDEF
        k = str(k)
    elif tk is not str:
        if tk is float and type(o) is JSArray and k == int(k) and 0 <= k < len(o.a):
            v = o.a[int(k)]
            return UNDEF if v is HOLE else v
        if o is UNDEF or o is None:
            throw_type("Cannot read properties of %s (reading '%s')" % (_what(o), to_str(k)))
        k = to_key(k)
    elif type(o) is JSArray and k and "0" <= k[0] <= "9":
        return o.get(k)
    if isinstance(o, JSObject):
        return o.get(k)
    if type(o) is str:
        return _str_get(o, k)
    if o is UNDEF or o is None:
        throw_type("Cannot read properties of %s (reading '%s')" % (_what(o), k if type(k) is str else k))
    return proto_of_primitive(o).get(k, o)


def put(o, k, v):
    """o[k] = v (k a string or Symbol); returns v."""
    if isinstance(o, JSObject):
        o.put(k, v)
        return v
    if o is UNDEF or o is None:
        throw_type("Cannot set properties of %s (setting '%s')" % (_what(o), k))
    return v


def putv(o, k, v):
    tk = type(k)
    if tk is int:
        if type(o) is JSArray and k >= 0:
            a = o.a
            if k < len(a):
                a[k] = v
            else:
                o.set_index(k, v)
            return v
        k = str(k)
    elif tk is not str:
        if tk is float and type(o) is JSArray and k == int(k) and k >= 0:
            o.set_index(int(k), v)
            return v
        k = to_key(k)
    if isinstance(o, JSObject):
        o.put(k, v)
        return v
    if o is UNDEF or o is None:
        throw_type("Cannot set properties of %s (setting '%s')" % (_what(o), to_str(k)))
    return v


def delete(o, k):
    if isinstance(o, JSObject):
        return o.remove(to_key(k))
    if o is UNDEF or o is None:
        throw_type("Cannot convert undefined or null to object")
    return True


def has_prop(k, o):
    """k in o"""
    if not isinstance(o, JSObject):
        throw_type("Cannot use 'in' operator to search for '%s' in %s" % (to_str(k), to_str(o)))
    return o.has(to_key(k))


def own_enum_keys(o):
    """The enumerable own string keys (Object.keys)."""
    out = []
    if isinstance(o, JSArray):
        for i in range(len(o.a)):
            if o.a[i] is not HOLE:
                out.append(str(i))
        for k in JSObject.own_keys(o):
            if type(k) is str:
                v = o.p.get(k)
                if type(v) is not Slot or v.e:
                    out.append(k)
        return out
    if isinstance(o, JSObject):
        if o.cls == "String" and type(o.x) is str:
            out = [str(i) for i in range(len(o.x))]
        p = o.p
        for k in o.own_keys():
            if type(k) is str:
                v = p.get(k, MISSING)
                if v is MISSING:
                    v = o.own(k)
                    if v is MISSING:
                        continue
                if type(v) is not Slot or v.e:
                    out.append(k)
        return out
    if type(o) is str:
        return [str(i) for i in range(len(o))]
    return out


def for_in_keys(o):
    """The keys a for-in loop goes over: enumerable, own and inherited."""
    if o is None or o is UNDEF:
        return []
    if not isinstance(o, JSObject):
        return own_enum_keys(o)
    seen = set()
    out = []
    while o is not None:
        keys = own_enum_keys(o)
        for k in keys:
            if k not in seen:
                seen.add(k)
                out.append(k)
        # non-enumerable own keys hide inherited ones too
        for k in o.ks:
            if type(k) is str:
                seen.add(k)
        o = o.proto
        if o is OBJECT_PROTO or o is ARRAY_PROTO or o is FUNCTION_PROTO:
            break
    return out


# ---- calls ----

def call(f, this, *args):
    if isinstance(f, JSFunction):
        return f.info.code(f, this, *args)
    throw_type("%s is not a function" % _show(f))


def callm(o, k, *args):
    """o.k(args): a method call."""
    if isinstance(o, JSObject):
        f = o.get(k)
    elif type(o) is str:
        f = STRING_PROTO.get(k, o) if k != "length" else len(o)
    elif o is UNDEF or o is None:
        throw_type("Cannot read properties of %s (reading '%s')" % (_what(o), k))
    else:
        f = proto_of_primitive(o).get(k, o)
    if isinstance(f, JSFunction):
        return f.info.code(f, o, *args)
    throw_type("%s.%s is not a function" % (_show_obj(o), k if type(k) is str else k))


def callv(o, k, *args):
    """o[k](args)"""
    f = getv(o, k)
    if isinstance(f, JSFunction):
        return f.info.code(f, o, *args)
    throw_type("%s[%s] is not a function" % (_show_obj(o), to_str(k) if type(k) is not Symbol else k))


def _show(v):
    if isinstance(v, JSFunction):
        return "function"
    if isinstance(v, JSObject):
        return "object"
    try:
        return to_str(v) if type(v) is not str else repr(v)
    except Exception:
        return "value"


def _show_obj(o):
    if isinstance(o, JSObject):
        c = o.get("constructor")
        if isinstance(c, JSFunction) and c.info.name:
            return "(" + c.info.name + ")"
        return "(object)"
    return _show(o)


def construct(f, args, newtarget=None):
    if not isinstance(f, JSFunction) or not f.info.ctor:
        throw_type("%s is not a constructor" % _show(f))
    if newtarget is None:
        newtarget = f
    info = f.info
    if info.kind == "native":
        R.newtarget = newtarget
        try:
            return info.code(f, MISSING, *args)
        finally:
            R.newtarget = UNDEF
    if info.derived:
        R.newtarget = newtarget
        r = info.code(f, MISSING, *args)
        if isinstance(r, JSObject):
            return r
        throw_type("Derived constructors may only return object or undefined")
    proto = newtarget.get("prototype")
    if not isinstance(proto, JSObject):
        proto = OBJECT_PROTO
    this = JSObject(proto)
    if f.fields is not None:
        init_fields(f, this)
    R.newtarget = newtarget
    try:
        r = info.code(f, this, *args)
    finally:
        R.newtarget = UNDEF
    if isinstance(r, JSObject):
        return r
    return this


def take_newtarget():
    nt = R.newtarget
    R.newtarget = UNDEF
    return nt


def init_fields(cls, this):
    for key, fn in cls.fields:
        v = fn.info.code(fn, this) if fn is not None else UNDEF
        if type(key) is str and key[:1] == "#":
            this.p[key] = Slot(v, e=False)
            if key not in this.ks:
                this.ks.append(key)
        else:
            define_value(this, key, v)


def super_call(F, newtarget, args):
    """super(...) in a derived constructor: the parent builds `this`; then this class's fields."""
    parent = F.proto
    if not isinstance(parent, JSFunction) or not parent.info.ctor:
        throw_type("Super constructor is not a constructor")
    this = construct(parent, args, newtarget if newtarget is not UNDEF else F)
    if F.fields is not None:
        init_fields(F, this)
    return this


def super_get(home, this, k):
    if home is None:
        throw("SyntaxError", "'super' keyword unexpected here")
    p = home.proto
    if p is None:
        return UNDEF
    return p.get(k, this)


def super_put(home, this, k, v):
    p = home.proto if home is not None else None
    if p is not None:
        c = p.p.get(k, MISSING) if type(p) is JSObject else p.own(k)
        if type(c) is Slot and c.acc and c.set is not None:
            c.set.info.code(c.set, this, v)
            return v
    return put(this, k, v)


def define_value(o, k, v):
    """CreateDataProperty: an own, plain property (even over an accessor)."""
    if type(o) is JSArray and type(k) is str and k.isdigit():
        o.set_index(int(k), v)
        return
    p = o.p
    if k not in p:
        o.ks.append(k)
    p[k] = v


def instance_of(v, f):
    if not isinstance(f, JSObject):
        throw_type("Right-hand side of 'instanceof' is not callable")
    h = f.get(SYM_HAS_INSTANCE)
    if isinstance(h, JSFunction) and h.info.name != "[Symbol.hasInstance]":
        return truthy(call(h, f, v))
    if not isinstance(f, JSFunction):
        throw_type("Right-hand side of 'instanceof' is not callable")
    if f.bound is not None:
        return instance_of(v, f.bound[0])
    if not isinstance(v, JSObject):
        return False
    proto = f.get("prototype")
    o = v.proto
    while o is not None:
        if o is proto:
            return True
        o = o.proto
    return False


# ---- operators ----

def add(a, b):
    ta = type(a)
    tb = type(b)
    if (ta is int or ta is float) and (tb is int or tb is float):
        r = a + b
        if type(r) is int and not (-MAX_SAFE <= r <= MAX_SAFE):
            return float(r)
        return r
    if ta is str and tb is str:
        return a + b
    if ta is not str and tb is not str:
        if ta is not int and ta is not float:
            a = to_primitive(a)
            ta = type(a)
        if tb is not int and tb is not float:
            b = to_primitive(b)
            tb = type(b)
        if ta is not str and tb is not str:
            return norm(to_num(a) + to_num(b))
    return to_str(a) + to_str(b)


def sub(a, b):
    ta = type(a)
    tb = type(b)
    if (ta is int or ta is float) and (tb is int or tb is float):
        return norm(a - b)
    return norm(to_num(a) - to_num(b))


def mul(a, b):
    ta = type(a)
    tb = type(b)
    if not ((ta is int or ta is float) and (tb is int or tb is float)):
        a = to_num(a)
        b = to_num(b)
    r = a * b
    if type(r) is int:
        if -MAX_SAFE <= r <= MAX_SAFE:
            if r == 0 and (a < 0 or b < 0) and type(a) is int and type(b) is int:
                return 0
            return r
        return float(r)
    return r


def div(a, b):
    ta = type(a)
    tb = type(b)
    if not ((ta is int or ta is float) and (tb is int or tb is float)):
        a = to_num(a)
        b = to_num(b)
    if b == 0:
        if a != a or a == 0:
            return NAN
        neg = (a < 0) != (math.copysign(1.0, b) < 0) if type(b) is float else a < 0
        return -INF if neg else INF
    r = a / b
    if type(a) is int and type(b) is int and a % b == 0:
        q = a // b
        if -MAX_SAFE <= q <= MAX_SAFE:
            return q
    return r


def mod(a, b):
    ta = type(a)
    tb = type(b)
    if not ((ta is int or ta is float) and (tb is int or tb is float)):
        a = to_num(a)
        b = to_num(b)
    if type(a) is int and type(b) is int:
        if b == 0:
            return NAN
        r = abs(a) % abs(b)
        return -r if a < 0 else r
    if b == 0 or a != a or b != b or a == INF or a == -INF:
        return NAN
    if b == INF or b == -INF:
        return a
    return norm(math.fmod(a, b))


def power(a, b):
    a = to_num(a)
    b = to_num(b)
    if b != b:
        return NAN
    if b == 0:
        return 1
    if (a == 1 or a == -1) and (b == INF or b == -INF):
        return NAN
    try:
        if type(a) is int and type(b) is int and b >= 0:
            return norm(a ** b)
        r = float(a) ** float(b)
        if type(r) is complex:
            return NAN
        return norm(r)
    except (OverflowError, ZeroDivisionError):
        if a == 0:
            return INF
        return INF if a > 0 or (type(b) is int and b % 2 == 0) else -INF
    except ValueError:
        return NAN


def neg(a):
    if type(a) is int:
        return -a if a != 0 else -0.0
    a = to_num(a)
    return -a if a != 0 or type(a) is float else -0.0


def pos(a):
    return to_num(a)


def bit_and(a, b):
    return to_int32(a) & to_int32(b)


def bit_or(a, b):
    if type(a) is int and type(b) is int and -2147483648 <= a <= 2147483647 and -2147483648 <= b <= 2147483647:
        return a | b
    return to_int32(to_int32(a) | to_int32(b))


def bit_xor(a, b):
    return to_int32(to_int32(a) ^ to_int32(b))


def bit_not(a):
    return ~to_int32(a)


def shl(a, b):
    return to_int32(to_int32(a) << (to_uint32(b) & 31))


def sar(a, b):
    return to_int32(a) >> (to_uint32(b) & 31)


def shr(a, b):
    return to_uint32(a) >> (to_uint32(b) & 31)


def inc(v):
    if type(v) is int and v < MAX_SAFE:
        return v + 1
    return norm(to_num(v) + 1)


def dec(v):
    if type(v) is int and v > -MAX_SAFE:
        return v - 1
    return norm(to_num(v) - 1)


def seq(a, b):
    """a === b"""
    if a is b:
        return type(a) is not float or a == a
    ta = type(a)
    tb = type(b)
    if ta is int or ta is float:
        return (tb is int or tb is float) and a == b
    if ta is str:
        return tb is str and a == b
    return False


def sne(a, b):
    return not seq(a, b)


def leq(a, b):
    """a == b"""
    if a is b:
        return type(a) is not float or a == a
    ta = type(a)
    tb = type(b)
    if ta is tb and ta is not bool:
        if ta is int or ta is float or ta is str:
            return a == b
        return False
    if (ta is int or ta is float) and (tb is int or tb is float):
        return a == b
    na = a is None or a is UNDEF
    nb = b is None or b is UNDEF
    if na or nb:
        return na and nb
    if ta is bool:
        return leq(1 if a else 0, b)
    if tb is bool:
        return leq(a, 1 if b else 0)
    if (ta is int or ta is float) and tb is str:
        return a == str_to_num(b)
    if ta is str and (tb is int or tb is float):
        return str_to_num(a) == b
    ao = isinstance(a, JSObject)
    bo = isinstance(b, JSObject)
    if ao and not bo:
        return leq(to_primitive(a), b)
    if bo and not ao:
        return leq(a, to_primitive(b))
    return False


def lne(a, b):
    return not leq(a, b)


def _cmp_prims(a, b):
    a = to_primitive(a, "number")
    b = to_primitive(b, "number")
    if type(a) is str and type(b) is str:
        return a, b
    return to_num(a), to_num(b)


def lt(a, b):
    ta = type(a)
    tb = type(b)
    if (ta is int or ta is float) and (tb is int or tb is float) or ta is str and tb is str:
        return a < b
    a, b = _cmp_prims(a, b)
    return a < b


def gt(a, b):
    ta = type(a)
    tb = type(b)
    if (ta is int or ta is float) and (tb is int or tb is float) or ta is str and tb is str:
        return a > b
    a, b = _cmp_prims(a, b)
    return a > b


def le(a, b):
    ta = type(a)
    tb = type(b)
    if (ta is int or ta is float) and (tb is int or tb is float) or ta is str and tb is str:
        return a <= b
    a, b = _cmp_prims(a, b)
    if type(a) is float and a != a or type(b) is float and b != b:
        return False
    return a <= b


def ge(a, b):
    ta = type(a)
    tb = type(b)
    if (ta is int or ta is float) and (tb is int or tb is float) or ta is str and tb is str:
        return a >= b
    a, b = _cmp_prims(a, b)
    if type(a) is float and a != a or type(b) is float and b != b:
        return False
    return a >= b


def nullish(v):
    return v is None or v is UNDEF


def cat(*parts):
    """A template literal: the strings and the values, as text."""
    return "".join([p if type(p) is str else to_str(p) for p in parts])


# ---- iteration ----

def iterate(v):
    """A Python iterator over a JavaScript iterable (for-of, spread, destructuring)."""
    t = type(v)
    if t is JSArray and ARRAY_PROTO.p.get(SYM_ITERATOR) is _ARRAY_VALUES[0] and SYM_ITERATOR not in v.p:
        return _array_iter(v)
    if t is str:
        return _str_iter(v)
    f = get(v, SYM_ITERATOR) if (isinstance(v, JSObject) or t is str) else UNDEF
    if not isinstance(f, JSFunction):
        if v is UNDEF or v is None:
            throw_type("%s is not iterable" % _what(v))
        throw_type("%s is not iterable" % _show(v))
    it = call(f, v)
    if isinstance(it, JSObject) and it.cls == "PyIterator":
        return it.x
    return _js_iter(it)


_ARRAY_VALUES = [None]          # Array.prototype[Symbol.iterator] (set by builtins)


def _array_iter(arr):
    a = arr.a
    i = 0
    while i < len(a):
        v = a[i]
        yield UNDEF if v is HOLE else v
        i += 1


def _str_iter(s):
    for ch in s:
        yield ch


def _js_iter(it):
    nxt = get(it, "next")
    done = False
    try:
        while True:
            r = call(nxt, it)
            if not isinstance(r, JSObject):
                throw_type("Iterator result %s is not an object" % _show(r))
            if truthy(r.get("done")):
                done = True
                return
            yield r.get("value")
    finally:
        if not done:
            ret = get(it, "return")
            if isinstance(ret, JSFunction):
                try:
                    call(ret, it)
                except JSThrow:
                    pass


def spread(v):
    if type(v) is JSArray and ARRAY_PROTO.p.get(SYM_ITERATOR) is _ARRAY_VALUES[0]:
        return [UNDEF if x is HOLE else x for x in v.a]
    return list(iterate(v))


def iter_result(value, done):
    o = JSObject(OBJECT_PROTO)
    o.p["value"] = value
    o.p["done"] = done
    o.ks.append("value")
    o.ks.append("done")
    return o


# ---- making values ----

def obj(*kv):
    """An object literal with plain keys: obj(k1, v1, k2, v2...)."""
    o = JSObject(OBJECT_PROTO)
    p = o.p
    ks = o.ks
    for i in range(0, len(kv), 2):
        k = kv[i]
        if k not in p:
            ks.append(k)
        p[k] = kv[i + 1]
    return o


def arr(items):
    return JSArray(items)


def new_object():
    return JSObject(OBJECT_PROTO)


# ---- the budget: scripts that run too long are stopped ----

def check():
    """Called by loops and calls from time to time."""
    R.budget = 2000
    f = R.ticks_ms
    if f is not None and R.deadline:
        if f() - R.deadline > 0:
            R.deadline = 0
            raise Interrupted("time")


def to_property_descriptor(d):
    if not isinstance(d, JSObject):
        throw_type("Property description must be an object")
    s = Slot()
    if d.has("get") or d.has("set"):
        g = d.get("get")
        st = d.get("set")
        s.acc = True
        s.get = g if isinstance(g, JSFunction) else None
        s.set = st if isinstance(st, JSFunction) else None
        s.w = False
    s.v = d.get("value")
    s.e = truthy(d.get("enumerable"))
    s.c = truthy(d.get("configurable"))
    if not s.acc:
        s.w = truthy(d.get("writable"))
    return s


def define_property(o, k, d):
    """Object.defineProperty(o, k, d)"""
    if not isinstance(o, JSObject):
        throw_type("Object.defineProperty called on non-object")
    new = to_property_descriptor(d)
    cur = o.p.get(k, MISSING)
    if type(o) is JSArray and type(k) is str and (k.isdigit() or k == "length"):
        if not new.acc:
            if k == "length":
                if d.has("value"):
                    set_length(o, new.v)
                return
            if d.has("value") or not d.has("get"):
                o.set_index(int(k), new.v)
            return
    if type(cur) is Slot:
        # an update: what is not said stays as it was
        if not cur.c and not (cur.w and not new.acc):
            if cur.acc != new.acc or new.acc:
                throw_type("Cannot redefine property: %s" % (to_str(k) if type(k) is str else k))
        if not d.has("enumerable"):
            new.e = cur.e
        if not d.has("configurable"):
            new.c = cur.c
        if new.acc:
            if cur.acc:
                if not d.has("get"):
                    new.get = cur.get
                if not d.has("set"):
                    new.set = cur.set
        else:
            if not d.has("value") and not cur.acc:
                new.v = cur.v
            if not d.has("writable") and not cur.acc:
                new.w = cur.w
        o.p[k] = new
        return
    if cur is not MISSING:
        # it was a plain property: enumerable, writable, configurable
        if not d.has("enumerable"):
            new.e = True
        if not d.has("configurable"):
            new.c = True
        if not new.acc:
            if not d.has("writable"):
                new.w = True
            if not d.has("value"):
                new.v = cur
    elif not o.ext:
        throw_type("Cannot define property %s, object is not extensible" % (k if type(k) is str else k))
    if not new.acc and new.e and new.w and new.c:
        o.define(k, new.v)
        return
    if cur is MISSING:
        o.ks.append(k)
    o.p[k] = new


def get_own_slot(o, k):
    """(value, getter, setter, enumerable, writable, configurable, accessor) of an own property, or None."""
    v = o.own(k) if not (type(o) is JSObject) else o.p.get(k, MISSING)
    if v is MISSING:
        return None
    raw = o.p.get(k, MISSING)
    if type(raw) is Slot:
        return raw
    if isinstance(o, JSFunction) and k in ("name", "length"):
        return Slot(v, e=False, w=False)
    if type(o) is JSArray and k == "length":
        return Slot(v, e=False, c=False)
    return Slot(v)
