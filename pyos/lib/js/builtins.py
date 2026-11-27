# The standard library of JavaScript, in Python: the global object and what
# hangs from it (Object, Function, Array, String, Number, Math, JSON, Symbol,
# Error, Map, Set, Promise, Reflect, Proxy, typed arrays, Date...).
import math
import time
from js import rt, interp
from js.rt import (UNDEF, MISSING, HOLE, JSObject, JSArray, JSFunction, Slot, JSThrow, Symbol, R,
                   OBJECT_PROTO, FUNCTION_PROTO, ARRAY_PROTO, STRING_PROTO, NUMBER_PROTO, BOOLEAN_PROTO,
                   SYMBOL_PROTO, ERROR_PROTO, ITERATOR_PROTO, GENERATOR_PROTO, ASYNC_GENERATOR_PROTO,
                   PROMISE_PROTO, REGEXP_PROTO, ERROR_PROTOS, NAN, INF,
                   to_str, to_num, to_int, to_key, to_obj, truthy, get, getv, put, putv, call, construct,
                   throw_type, throw_range, is_object, iter_result)
from js.interp import native_fn, new_promise, settle, resolve_promise, then_native, FULFILLED, REJECTED, PENDING

_NONE = object()


def define(o, name, value, e=False, w=True, c=True):
    if e and w and c:
        o.define(name, value)
        return
    if name not in o.p:
        o.ks.append(name)
    o.p[name] = Slot(value, e=e, w=w, c=c)


def fn(o, name, nparams=0):
    """Decorator: a native method on o."""
    def deco(code):
        key = name
        label = name if type(name) is str else "[%s]" % name.desc
        define(o, key, native_fn(code, label, nparams))
        return code
    return deco


def getter(o, name, setter=None):
    def deco(code):
        g = native_fn(code, "get " + name, 0)
        s = native_fn(setter, "set " + name, 1) if setter else None
        if name not in o.p:
            o.ks.append(name)
        o.p[name] = Slot(acc=True, get=g, set=s, e=False)
        return code
    return deco


def ctor(name, code, nparams, proto, parent=None):
    C = native_fn(code, name, nparams, True, parent)
    C.p["prototype"] = Slot(proto, e=False, w=False, c=False)
    C.ks.append("prototype")
    define(proto, "constructor", C)
    return C


def new_target_proto(default):
    nt = rt.take_newtarget()
    if nt is UNDEF:
        return None
    p = nt.get("prototype")
    return p if isinstance(p, JSObject) else default


def arg(a, i):
    return a[i] if len(a) > i else UNDEF


def to_list(v):
    """The items of an array or array-like."""
    if type(v) is JSArray:
        return [UNDEF if x is HOLE else x for x in v.a]
    if not isinstance(v, JSObject):
        if type(v) is str:
            return list(v)
        return []
    n = rt.to_int(v.get("length"))
    if n <= 0:
        return []
    return [v.get(str(i)) for i in range(int(min(n, 10000000)))]


def callable_(f, what="callback"):
    if not isinstance(f, JSFunction):
        throw_type("%s is not a function" % rt._show(f))
    return f


def same_value_zero(a, b):
    if type(a) is float and a != a:
        return type(b) is float and b != b
    return rt.seq(a, b)


def same_value(a, b):
    if type(a) is float and type(b) is float:
        if a != a:
            return b != b
        if a == 0 and b == 0:
            return math.copysign(1, a) == math.copysign(1, b)
    if (type(a) in (int, float)) and (type(b) in (int, float)) and a == 0 and b == 0:
        return (type(a) is float and math.copysign(1, a) < 0) == (type(b) is float and math.copysign(1, b) < 0)
    return rt.seq(a, b)


G = JSObject(OBJECT_PROTO, "global")
R.glob = G

# ---- Object ----


def object_ctor(F, this, v=UNDEF, *_):
    nt = rt.take_newtarget()
    if v is None or v is UNDEF:
        p = OBJECT_PROTO
        if nt is not UNDEF and nt is not OBJECT:
            p = nt.get("prototype")
        return JSObject(p)
    return to_obj(v)


OBJECT = ctor("Object", object_ctor, 1, OBJECT_PROTO)


@fn(OBJECT, "keys", 1)
def object_keys(F, this, o=UNDEF, *_):
    return JSArray(rt.own_enum_keys(to_obj(o) if not isinstance(o, JSObject) and type(o) is not str else o))


@fn(OBJECT, "values", 1)
def object_values(F, this, o=UNDEF, *_):
    o2 = to_obj(o)
    return JSArray([getv(o, k) for k in rt.own_enum_keys(o if type(o) is str else o2)])


@fn(OBJECT, "entries", 1)
def object_entries(F, this, o=UNDEF, *_):
    o2 = to_obj(o)
    return JSArray([JSArray([k, getv(o, k)]) for k in rt.own_enum_keys(o if type(o) is str else o2)])


@fn(OBJECT, "assign", 2)
def object_assign(F, this, target=UNDEF, *srcs):
    t = to_obj(target)
    for s in srcs:
        if s is None or s is UNDEF:
            continue
        if type(s) is str:
            for i in range(len(s)):
                t.put(str(i), s[i])
            continue
        if not isinstance(s, JSObject):
            continue
        for k in own_keys_all(s):
            sl = rt.get_own_slot(s, k)
            if sl is not None and sl.e:
                rt.putv(t, k, s.get(k))
    return t


@fn(OBJECT, "create", 2)
def object_create(F, this, proto=UNDEF, props=UNDEF, *_):
    if proto is not None and not isinstance(proto, JSObject):
        throw_type("Object prototype may only be an Object or null")
    o = JSObject(proto)
    if props is not UNDEF:
        object_define_properties(None, None, o, props)
    return o


@fn(OBJECT, "defineProperty", 3)
def object_define_property(F, this, o=UNDEF, k=UNDEF, d=UNDEF, *_):
    if isinstance(o, JSProxy):
        trap = o.trap("defineProperty")
        if trap is not None:
            call(trap, o.handler, o.target, to_key(k), d)
            return o
        o = o.target
    rt.define_property(o, to_key(k), d)
    return o


@fn(OBJECT, "defineProperties", 2)
def object_define_properties(F, this, o=UNDEF, props=UNDEF, *_):
    props = to_obj(props)
    for k in own_keys_all(props):
        sl = rt.get_own_slot(props, k)
        if sl is not None and sl.e:
            rt.define_property(o, k, props.get(k))
    return o


def own_keys_all(o):
    if isinstance(o, JSProxy):
        trap = o.trap("ownKeys")
        if trap is not None:
            return to_list(call(trap, o.handler, o.target))
        o = o.target
    keys = o.own_keys()
    if o.cls == "String" and type(o.x) is str:
        keys = [str(i) for i in range(len(o.x))] + keys
    return keys


@fn(OBJECT, "getOwnPropertyNames", 1)
def object_gopn(F, this, o=UNDEF, *_):
    o = to_obj(o)
    return JSArray([k for k in own_keys_all(o) if type(k) is str])


@fn(OBJECT, "getOwnPropertySymbols", 1)
def object_gops(F, this, o=UNDEF, *_):
    o = to_obj(o)
    return JSArray([k for k in own_keys_all(o) if type(k) is Symbol])


def descriptor_obj(sl):
    d = JSObject(OBJECT_PROTO)
    if sl.acc:
        d.define("get", sl.get if sl.get is not None else UNDEF)
        d.define("set", sl.set if sl.set is not None else UNDEF)
    else:
        d.define("value", sl.v)
        d.define("writable", sl.w)
    d.define("enumerable", sl.e)
    d.define("configurable", sl.c)
    return d


@fn(OBJECT, "getOwnPropertyDescriptor", 2)
def object_gopd(F, this, o=UNDEF, k=UNDEF, *_):
    o = to_obj(o)
    k = to_key(k)
    if isinstance(o, JSProxy):
        trap = o.trap("getOwnPropertyDescriptor")
        if trap is not None:
            return call(trap, o.handler, o.target, k)
        o = o.target
    if o.cls == "String" and type(o.x) is str and type(k) is str and k.isdigit() and int(k) < len(o.x):
        return descriptor_obj(Slot(o.x[int(k)], e=True, w=False, c=False))
    sl = rt.get_own_slot(o, k)
    return UNDEF if sl is None else descriptor_obj(sl)


@fn(OBJECT, "getOwnPropertyDescriptors", 1)
def object_gopds(F, this, o=UNDEF, *_):
    o = to_obj(o)
    out = JSObject(OBJECT_PROTO)
    for k in own_keys_all(o):
        sl = rt.get_own_slot(o, k)
        if sl is not None:
            out.define(k, descriptor_obj(sl))
    return out


@fn(OBJECT, "getPrototypeOf", 1)
def object_gpo(F, this, o=UNDEF, *_):
    if isinstance(o, JSProxy):
        trap = o.trap("getPrototypeOf")
        if trap is not None:
            return call(trap, o.handler, o.target)
        return o.target.proto
    if isinstance(o, JSObject):
        return o.proto
    return rt.proto_of_primitive(to_obj(o).x) if o is not None and o is not UNDEF else to_obj(o)


@fn(OBJECT, "setPrototypeOf", 2)
def object_spo(F, this, o=UNDEF, p=UNDEF, *_):
    if isinstance(o, JSObject) and (p is None or isinstance(p, JSObject)):
        q = p
        while q is not None:
            if q is o:
                throw_type("Cyclic __proto__ value")
            q = q.proto
        o.proto = p
    return o


@fn(OBJECT, "freeze", 1)
def object_freeze(F, this, o=UNDEF, *_):
    if isinstance(o, JSObject):
        o.ext = False
        if type(o) is JSArray:
            for i in range(len(o.a)):
                k = str(i)
                o.ks.append(k) if k not in o.p else None
            o.p.update({str(i): Slot(o.a[i], w=False, c=False) for i in range(len(o.a))})
        for k in list(o.p):
            v = o.p[k]
            if type(v) is Slot:
                v.c = False
                if not v.acc:
                    v.w = False
            else:
                o.p[k] = Slot(v, w=False, c=False)
        o.cls = o.cls if o.cls != "Object" else "Object"
        if type(o) is JSArray:
            FROZEN_ARRAYS.add(id(o))
    return o


FROZEN_ARRAYS = set()


@fn(OBJECT, "isFrozen", 1)
def object_is_frozen(F, this, o=UNDEF, *_):
    if not isinstance(o, JSObject):
        return True
    if o.ext:
        return False
    for v in o.p.values():
        if type(v) is not Slot or v.c or (not v.acc and v.w):
            return False
    return type(o) is not JSArray or id(o) in FROZEN_ARRAYS or not o.a


@fn(OBJECT, "seal", 1)
def object_seal(F, this, o=UNDEF, *_):
    if isinstance(o, JSObject):
        o.ext = False
        for k in list(o.p):
            v = o.p[k]
            if type(v) is Slot:
                v.c = False
            else:
                o.p[k] = Slot(v, c=False)
    return o


@fn(OBJECT, "isSealed", 1)
def object_is_sealed(F, this, o=UNDEF, *_):
    if not isinstance(o, JSObject):
        return True
    return not o.ext and all(type(v) is Slot and not v.c for v in o.p.values())


@fn(OBJECT, "preventExtensions", 1)
def object_pe(F, this, o=UNDEF, *_):
    if isinstance(o, JSObject):
        o.ext = False
    return o


@fn(OBJECT, "isExtensible", 1)
def object_ie(F, this, o=UNDEF, *_):
    return isinstance(o, JSObject) and o.ext


@fn(OBJECT, "fromEntries", 1)
def object_from_entries(F, this, it=UNDEF, *_):
    o = JSObject(OBJECT_PROTO)
    for e in rt.iterate(it):
        rt.define_value(o, to_key(getv(e, 0)), getv(e, 1))
    return o


@fn(OBJECT, "is", 2)
def object_is(F, this, a=UNDEF, b=UNDEF, *_):
    return same_value(a, b)


@fn(OBJECT, "hasOwn", 2)
def object_has_own(F, this, o=UNDEF, k=UNDEF, *_):
    o = to_obj(o)
    return has_own(o, to_key(k))


@fn(OBJECT, "groupBy", 2)
def object_group_by(F, this, items=UNDEF, f=UNDEF, *_):
    out = JSObject(None)
    i = 0
    for v in rt.iterate(items):
        k = to_key(call(f, UNDEF, v, i))
        i += 1
        g = out.p.get(k)
        if g is None:
            g = JSArray([])
            out.define(k, g)
        g.a.append(v)
    return out


def has_own(o, k):
    if isinstance(o, JSProxy):
        return object_gopd(None, None, o, k) is not UNDEF
    if o.cls == "String" and type(o.x) is str and type(k) is str and k.isdigit():
        return int(k) < len(o.x)
    return o.own(k) is not MISSING


@fn(OBJECT_PROTO, "hasOwnProperty", 1)
def op_has_own(F, this, k=UNDEF, *_):
    k = to_key(k)
    if type(this) is str:
        return k == "length" or (type(k) is str and k.isdigit() and int(k) < len(this))
    return has_own(to_obj(this), k)


@fn(OBJECT_PROTO, "isPrototypeOf", 1)
def op_is_proto(F, this, v=UNDEF, *_):
    if not isinstance(v, JSObject):
        return False
    p = v.proto
    while p is not None:
        if p is this:
            return True
        p = p.proto
    return False


@fn(OBJECT_PROTO, "propertyIsEnumerable", 1)
def op_pie(F, this, k=UNDEF, *_):
    o = to_obj(this)
    sl = rt.get_own_slot(o, to_key(k))
    return sl is not None and sl.e


def class_of(v):
    if v is UNDEF:
        return "Undefined"
    if v is None:
        return "Null"
    if type(v) is str:
        return "String"
    if type(v) in (int, float):
        return "Number"
    if type(v) is bool:
        return "Boolean"
    if isinstance(v, JSObject):
        tag = v.get(rt.SYM_TO_STRING_TAG)
        if type(tag) is str:
            return tag
        if isinstance(v, JSFunction):
            return "Function"
        if type(v) is JSArray and v.cls == "Array":
            return "Array"
        if v.cls in ("Error", "Date", "RegExp", "Arguments", "Boolean", "Number", "String"):
            return v.cls
        return "Object"
    return "Object"


@fn(OBJECT_PROTO, "toString", 0)
def op_to_string(F, this, *_):
    return "[object %s]" % class_of(this)


@fn(OBJECT_PROTO, "toLocaleString", 0)
def op_to_locale_string(F, this, *_):
    return rt.callm(this, "toString")


@fn(OBJECT_PROTO, "valueOf", 0)
def op_value_of(F, this, *_):
    return to_obj(this)


def _proto_get(F, this, *_):
    if isinstance(this, JSObject):
        return this.proto
    return rt.proto_of_primitive(this)


def _proto_set(F, this, p=UNDEF, *_):
    if isinstance(this, JSObject) and (p is None or isinstance(p, JSObject)):
        object_spo(None, None, this, p)
    return UNDEF


OBJECT_PROTO.ks.append("__proto__")
OBJECT_PROTO.p["__proto__"] = Slot(acc=True, get=native_fn(_proto_get, "get __proto__"),
                                   set=native_fn(_proto_set, "set __proto__", 1), e=False)


@fn(OBJECT_PROTO, "__defineGetter__", 2)
def op_define_getter(F, this, k=UNDEF, f=UNDEF, *_):
    d = rt.obj("get", f, "enumerable", True, "configurable", True)
    rt.define_property(this, to_key(k), d)
    return UNDEF


@fn(OBJECT_PROTO, "__defineSetter__", 2)
def op_define_setter(F, this, k=UNDEF, f=UNDEF, *_):
    d = rt.obj("set", f, "enumerable", True, "configurable", True)
    rt.define_property(this, to_key(k), d)
    return UNDEF


@fn(OBJECT_PROTO, "__lookupGetter__", 1)
def op_lookup_getter(F, this, k=UNDEF, *_):
    o = this
    k = to_key(k)
    while isinstance(o, JSObject):
        v = o.p.get(k)
        if type(v) is Slot and v.acc:
            return v.get or UNDEF
        o = o.proto
    return UNDEF


# ---- Function ----

def function_proto_call(F, this, *a):
    return UNDEF


FUNCTION_PROTO_FN = FUNCTION_PROTO


def function_ctor(F, this, *a):
    rt.take_newtarget()
    params = ",".join(to_str(x) for x in a[:-1])
    body = to_str(a[-1]) if a else ""
    return CTX_EVAL[0]("(function anonymous(%s\n) {\n%s\n})" % (params, body), "Function")


CTX_EVAL = [None]
FUNCTION = ctor("Function", function_ctor, 1, FUNCTION_PROTO)


@fn(FUNCTION_PROTO, "call", 1)
def fp_call(F, this, t=UNDEF, *a):
    if not isinstance(this, JSFunction):
        throw_type("Function.prototype.call called on a non-function")
    return this.info.code(this, t, *a)


@fn(FUNCTION_PROTO, "apply", 2)
def fp_apply(F, this, t=UNDEF, a=UNDEF, *_):
    if not isinstance(this, JSFunction):
        throw_type("Function.prototype.apply was called on a non-function")
    args = [] if a is None or a is UNDEF else to_list(a)
    return this.info.code(this, t, *args)


@fn(FUNCTION_PROTO, "bind", 1)
def fp_bind(F, this, t=UNDEF, *bound):
    target = callable_(this)
    bound = list(bound)

    def code(F2, this2, *a):
        if this2 is MISSING:                     # new on a bound function
            nt = rt.take_newtarget()
            return construct(target, bound + list(a), target if nt is F2 or nt is UNDEF else nt)
        return target.info.code(target, t, *(bound + list(a)))
    name = target.get("name")
    n = target.get("length")
    info = rt.FuncInfo(code, "bound " + (name if type(name) is str else ""),
                       max(0, (n if type(n) is int else 0) - len(bound)), "native", target.info.ctor)
    f = JSFunction(info, None, None, target.proto)
    f.bound = (target, t, bound)
    return f


@fn(FUNCTION_PROTO, "toString", 0)
def fp_to_string(F, this, *_):
    if not isinstance(this, JSFunction):
        throw_type("Function.prototype.toString requires that 'this' be a Function")
    info = this.info
    node = info.node
    if node is not None and info.unit is not None:
        return info.unit.src[node.pos:node.end]
    return "function %s() { [native code] }" % info.name


define(FUNCTION_PROTO, rt.SYM_HAS_INSTANCE, native_fn(lambda F, this, v=UNDEF, *_: rt.instance_of(v, this),
                                                      "[Symbol.hasInstance]", 1), w=False, c=False)
FUNCTION_PROTO.x = None
# Function.prototype is itself callable in JS; here, a plain object will do

# ---- Symbol ----

SYMBOL_REGISTRY = {}


def symbol_ctor(F, this, desc=UNDEF, *_):
    if this is MISSING:
        rt.take_newtarget()
        throw_type("Symbol is not a constructor")
    return Symbol(UNDEF if desc is UNDEF else to_str(desc))


SYMBOL = ctor("Symbol", symbol_ctor, 0, SYMBOL_PROTO)
SYMBOL.info.ctor = True
for _name, _sym in (("iterator", rt.SYM_ITERATOR), ("asyncIterator", rt.SYM_ASYNC_ITERATOR),
                    ("hasInstance", rt.SYM_HAS_INSTANCE), ("toPrimitive", rt.SYM_TO_PRIMITIVE),
                    ("toStringTag", rt.SYM_TO_STRING_TAG), ("species", rt.SYM_SPECIES),
                    ("unscopables", rt.SYM_UNSCOPABLES), ("matchAll", rt.SYM_MATCH_ALL)):
    define(SYMBOL, _name, _sym, w=False, c=False)
for _name in ("match", "replace", "search", "split", "isConcatSpreadable"):
    define(SYMBOL, _name, Symbol("Symbol." + _name), w=False, c=False)


@fn(SYMBOL, "for", 1)
def symbol_for(F, this, k=UNDEF, *_):
    k = to_str(k)
    s = SYMBOL_REGISTRY.get(k)
    if s is None:
        s = SYMBOL_REGISTRY[k] = Symbol(k)
    return s


@fn(SYMBOL, "keyFor", 1)
def symbol_key_for(F, this, s=UNDEF, *_):
    for k, v in SYMBOL_REGISTRY.items():
        if v is s:
            return k
    return UNDEF


def this_symbol(v):
    if type(v) is Symbol:
        return v
    if isinstance(v, JSObject) and type(v.x) is Symbol:
        return v.x
    throw_type("not a Symbol")


@fn(SYMBOL_PROTO, "toString", 0)
def symbol_to_string(F, this, *_):
    s = this_symbol(this)
    return "Symbol(%s)" % ("" if s.desc is UNDEF else s.desc)


@fn(SYMBOL_PROTO, "valueOf", 0)
def symbol_value_of(F, this, *_):
    return this_symbol(this)


@getter(SYMBOL_PROTO, "description")
def symbol_description(F, this, *_):
    return this_symbol(this).desc


define(SYMBOL_PROTO, rt.SYM_TO_STRING_TAG, "Symbol", w=False)

# ---- Error ----


def make_error_ctor(name, parent_ctor, proto):
    def code(F, this, msg=UNDEF, opts=UNDEF, *_):
        p = new_target_proto(proto)
        e = JSObject(p if p is not None else proto, "Error")
        if msg is not UNDEF:
            define(e, "message", to_str(msg))
        if isinstance(opts, JSObject) and opts.has("cause"):
            define(e, "cause", opts.get("cause"))
        define(e, "stack", "%s: %s\n    at <anonymous>" % (name, "" if msg is UNDEF else to_str(msg)))
        return e
    C = ctor(name, code, 1, proto, parent_ctor)
    define(proto, "name", name)
    define(proto, "message", "")
    return C


ERROR = make_error_ctor("Error", None, ERROR_PROTO)
ERROR_PROTOS["Error"] = ERROR_PROTO


@fn(ERROR_PROTO, "toString", 0)
def error_to_string(F, this, *_):
    if not isinstance(this, JSObject):
        throw_type("Error.prototype.toString called on a non-object")
    n = this.get("name")
    m = this.get("message")
    n = "Error" if n is UNDEF else to_str(n)
    m = "" if m is UNDEF else to_str(m)
    if not n:
        return m
    if not m:
        return n
    return n + ": " + m


@fn(ERROR, "captureStackTrace", 1)
def error_capture(F, this, o=UNDEF, *_):
    if isinstance(o, JSObject):
        define(o, "stack", to_str(get(o, "name")) + "\n    at <anonymous>")
    return UNDEF


define(ERROR, "stackTraceLimit", 10, e=True)
ERRORS = {}
for _n in ("TypeError", "RangeError", "SyntaxError", "ReferenceError", "EvalError", "URIError", "InternalError"):
    _p = JSObject(ERROR_PROTO, "Error")
    ERROR_PROTOS[_n] = _p
    ERRORS[_n] = make_error_ctor(_n, ERROR, _p)


def aggregate_ctor(F, this, errors=UNDEF, msg=UNDEF, *_):
    p = new_target_proto(AGG_PROTO)
    e = JSObject(p or AGG_PROTO, "Error")
    if msg is not UNDEF:
        define(e, "message", to_str(msg))
    define(e, "errors", JSArray(list(rt.iterate(errors))) if errors is not UNDEF else JSArray([]))
    return e


AGG_PROTO = JSObject(ERROR_PROTO, "Error")
ERROR_PROTOS["AggregateError"] = AGG_PROTO
ERRORS["AggregateError"] = ctor("AggregateError", aggregate_ctor, 2, AGG_PROTO, ERROR)
define(AGG_PROTO, "name", "AggregateError")
define(AGG_PROTO, "message", "")

# ---- Boolean, Number ----


def boolean_ctor(F, this, v=UNDEF, *_):
    b = truthy(v)
    p = new_target_proto(BOOLEAN_PROTO) if this is MISSING else None
    if p is None:
        return b
    o = JSObject(p, "Boolean")
    o.x = b
    return o


BOOLEAN = ctor("Boolean", boolean_ctor, 1, BOOLEAN_PROTO)
BOOLEAN_PROTO.x = False


def this_bool(v):
    if type(v) is bool:
        return v
    if isinstance(v, JSObject) and type(v.x) is bool:
        return v.x
    throw_type("not a Boolean")


@fn(BOOLEAN_PROTO, "toString", 0)
def bool_to_string(F, this, *_):
    return "true" if this_bool(this) else "false"


@fn(BOOLEAN_PROTO, "valueOf", 0)
def bool_value_of(F, this, *_):
    return this_bool(this)


def number_ctor(F, this, *a):
    n = to_num(a[0]) if a else 0
    p = new_target_proto(NUMBER_PROTO) if this is MISSING else None
    if p is None:
        return n
    o = JSObject(p, "Number")
    o.x = n
    return o


NUMBER = ctor("Number", number_ctor, 1, NUMBER_PROTO)
NUMBER_PROTO.x = 0
for _n, _v in (("MAX_SAFE_INTEGER", rt.MAX_SAFE), ("MIN_SAFE_INTEGER", -rt.MAX_SAFE),
               ("MAX_VALUE", 1.7976931348623157e308), ("MIN_VALUE", 5e-324), ("EPSILON", 2.220446049250313e-16),
               ("POSITIVE_INFINITY", INF), ("NEGATIVE_INFINITY", -INF), ("NaN", NAN)):
    define(NUMBER, _n, _v, w=False, c=False)


def this_num(v):
    if type(v) in (int, float) and type(v) is not bool:
        return v
    if isinstance(v, JSObject) and type(v.x) in (int, float) and type(v.x) is not bool and v.cls == "Number":
        return v.x
    throw_type("not a Number")


@fn(NUMBER_PROTO, "toString", 1)
def num_to_string(F, this, radix=UNDEF, *_):
    n = this_num(this)
    r = 10 if radix is UNDEF else to_int(radix)
    if r < 2 or r > 36:
        throw_range("toString() radix must be between 2 and 36")
    if type(n) is float and n == int(n) and abs(n) < 1e21 and r != 10:
        n = int(n)
    return rt.num_str(n, int(r))


@fn(NUMBER_PROTO, "toLocaleString", 0)
def num_to_locale(F, this, *_):
    n = this_num(this)
    if n != n or n in (INF, -INF):
        return rt.num_str(n)
    neg = n < 0
    n = abs(n)
    ip = int(n)
    frac = round(n - ip, 3)
    if frac >= 1:
        ip += 1
        frac = 0
    s = str(ip)
    groups = []
    while len(s) > 3:
        groups.insert(0, s[-3:])
        s = s[:-3]
    groups.insert(0, s)
    out = ",".join(groups)
    if frac:
        out += ("%.3f" % frac)[1:].rstrip("0")
    return ("-" if neg else "") + out


@fn(NUMBER_PROTO, "valueOf", 0)
def num_value_of(F, this, *_):
    return this_num(this)


@fn(NUMBER_PROTO, "toFixed", 1)
def num_to_fixed(F, this, d=UNDEF, *_):
    n = this_num(this)
    d = to_int(d)
    if d < 0 or d > 100:
        throw_range("toFixed() digits argument must be between 0 and 100")
    if n != n:
        return "NaN"
    if abs(n) >= 1e21:
        return rt.num_str(n)
    s = "%.*f" % (int(d), n)
    if s.startswith("-") and float(s) == 0:
        s = s[1:] if n > -0.5 * 10 ** -d else s
    return s


@fn(NUMBER_PROTO, "toPrecision", 1)
def num_to_precision(F, this, p=UNDEF, *_):
    n = this_num(this)
    if p is UNDEF:
        return rt.num_str(n)
    p = to_int(p)
    if n != n or n in (INF, -INF):
        return rt.num_str(n)
    if p < 1 or p > 100:
        throw_range("toPrecision() argument must be between 1 and 100")
    p = int(p)
    if n == 0:
        return "0" + ("." + "0" * (p - 1) if p > 1 else "")
    e = int(math.floor(math.log10(abs(n))))
    s = "%.*e" % (p - 1, n)
    e = int(s.split("e")[1])
    if e < -6 or e >= p:
        m, ex = s.split("e")
        ex = int(ex)
        return m + "e" + ("+" if ex >= 0 else "-") + str(abs(ex))
    return "%.*f" % (max(0, p - 1 - e), n)


@fn(NUMBER_PROTO, "toExponential", 1)
def num_to_exponential(F, this, d=UNDEF, *_):
    n = this_num(this)
    if n != n or n in (INF, -INF):
        return rt.num_str(n)
    if d is UNDEF:
        s = rt.num_str(float(n))
        m = "%e" % n
        digits = None
        for k in range(0, 17):
            t = "%.*e" % (k, n)
            if float(t) == n:
                digits = t
                break
        s = digits or m
    else:
        s = "%.*e" % (int(to_int(d)), n)
    m, ex = s.split("e")
    ex = int(ex)
    return m + "e" + ("+" if ex >= 0 else "-") + str(abs(ex))


def parse_int(F, this, s=UNDEF, radix=UNDEF, *_):
    s = to_str(s).strip(rt._WS)
    r = to_int(radix) if radix is not UNDEF else 0
    sign = 1
    if s[:1] in "+-" and s:
        if s[0] == "-":
            sign = -1
        s = s[1:]
    if r == 0:
        r = 10
        if s[:2].lower() == "0x":
            r = 16
            s = s[2:]
    elif r == 16 and s[:2].lower() == "0x":
        s = s[2:]
    if r < 2 or r > 36:
        return NAN
    digits = rt._DIGITS[:int(r)]
    k = 0
    low = s.lower()
    while k < len(low) and low[k] in digits:
        k += 1
    if k == 0:
        return NAN
    v = int(low[:k], int(r))
    return rt.norm(sign * v)


def parse_float(F, this, s=UNDEF, *_):
    s = to_str(s).strip(rt._WS)
    k = 0
    n = len(s)
    if k < n and s[k] in "+-":
        k += 1
    if s.startswith("Infinity", k):
        return -INF if s[0] == "-" else INF
    start = k
    while k < n and s[k].isdigit():
        k += 1
    if k < n and s[k] == ".":
        k += 1
        while k < n and s[k].isdigit():
            k += 1
    if k == start or s[start:k] == ".":
        return NAN
    if k < n and s[k] in "eE":
        j = k + 1
        if j < n and s[j] in "+-":
            j += 1
        if j < n and s[j].isdigit():
            while j < n and s[j].isdigit():
                j += 1
            k = j
    v = float(s[:k])
    if v == int(v) and abs(v) <= rt.MAX_SAFE:
        return int(v)
    return v


PARSE_INT = native_fn(parse_int, "parseInt", 2)
PARSE_FLOAT = native_fn(parse_float, "parseFloat", 1)
define(NUMBER, "parseInt", PARSE_INT)
define(NUMBER, "parseFloat", PARSE_FLOAT)


@fn(NUMBER, "isNaN", 1)
def number_is_nan(F, this, v=UNDEF, *_):
    return type(v) is float and v != v


@fn(NUMBER, "isFinite", 1)
def number_is_finite(F, this, v=UNDEF, *_):
    return type(v) is int or (type(v) is float and v == v and v not in (INF, -INF))


@fn(NUMBER, "isInteger", 1)
def number_is_integer(F, this, v=UNDEF, *_):
    return type(v) is int or (type(v) is float and v == v and v not in (INF, -INF) and v == int(v))


@fn(NUMBER, "isSafeInteger", 1)
def number_is_safe(F, this, v=UNDEF, *_):
    return number_is_integer(F, this, v) and abs(v) <= rt.MAX_SAFE


# ---- Math ----

MATH = JSObject(OBJECT_PROTO, "Math")
define(MATH, rt.SYM_TO_STRING_TAG, "Math", w=False)
for _n, _v in (("PI", math.pi), ("E", math.e), ("LN2", math.log(2)), ("LN10", math.log(10)),
               ("LOG2E", 1 / math.log(2)), ("LOG10E", 1 / math.log(10)), ("SQRT2", math.sqrt(2)),
               ("SQRT1_2", math.sqrt(0.5))):
    define(MATH, _n, _v, w=False, c=False)


def _m1(name, f):
    def code(F, this, x=UNDEF, *_):
        x = to_num(x)
        try:
            return rt.norm(f(x))
        except (ValueError, OverflowError):
            return NAN
    define(MATH, name, native_fn(code, name, 1))


def _floor(x):
    if type(x) is int:
        return x
    if x != x or x in (INF, -INF):
        return x
    return int(math.floor(x)) if abs(x) < 9e15 else math.floor(x)


def _ceil(x):
    if type(x) is int:
        return x
    if x != x or x in (INF, -INF):
        return x
    r = math.ceil(x)
    if r == 0 and x < 0:
        return -0.0
    return int(r) if abs(x) < 9e15 else float(r)


def _round(x):
    if type(x) is int:
        return x
    if x != x or x in (INF, -INF):
        return x
    r = math.floor(x + 0.5)
    if r == 0 and x < 0:
        return -0.0
    return int(r) if abs(x) < 9e15 else float(r)


def _trunc(x):
    if type(x) is int:
        return x
    if x != x or x in (INF, -INF):
        return x
    return int(x) if abs(x) < 9e15 else float(int(x))


def _sign(x):
    if x != x:
        return NAN
    return 1 if x > 0 else -1 if x < 0 else x


def _sqrt(x):
    if x < 0 or x != x:
        return NAN
    if x == INF:
        return INF
    return math.sqrt(x)


def _log(f):
    def g(x):
        if x != x or x < 0:
            return NAN
        if x == 0:
            return -INF
        if x == INF:
            return INF
        return f(x)
    return g


def _cbrt(x):
    if x != x or x in (INF, -INF) or x == 0:
        return x
    r = abs(x) ** (1.0 / 3)
    rr = round(r)
    if rr ** 3 == abs(x):
        r = rr
    return r if x > 0 else -r


def _clz32(x):
    x = rt.to_uint32(x)
    n = 32
    while x:
        x >>= 1
        n -= 1
    return n


def _fround(x):
    import struct
    try:
        return struct.unpack("f", struct.pack("f", x))[0]
    except (OverflowError, ValueError):
        return INF if x > 0 else -INF


for _n, _f in (("abs", abs), ("floor", _floor), ("ceil", _ceil), ("round", _round), ("trunc", _trunc),
               ("sign", _sign), ("sqrt", _sqrt), ("cbrt", _cbrt), ("exp", math.exp),
               ("expm1", getattr(math, "expm1", lambda x: math.exp(x) - 1)), ("log", _log(math.log)),
               ("log2", _log(lambda x: math.log(x) / math.log(2) if x not in (8, 1024) else
                             (3 if x == 8 else 10))),
               ("log10", _log(math.log10)), ("log1p", lambda x: _log(math.log)(1 + x)),
               ("sin", math.sin), ("cos", math.cos), ("tan", math.tan), ("asin", math.asin), ("acos", math.acos),
               ("atan", math.atan), ("sinh", math.sinh), ("cosh", math.cosh), ("tanh", math.tanh),
               ("asinh", math.asinh), ("acosh", math.acosh), ("atanh", math.atanh), ("clz32", _clz32),
               ("fround", _fround)):
    _m1(_n, _f)


@fn(MATH, "max", 2)
def math_max(F, this, *a):
    r = -INF
    for x in a:
        x = to_num(x)
        if x != x:
            return NAN
        if x > r:
            r = x
    return r


@fn(MATH, "min", 2)
def math_min(F, this, *a):
    r = INF
    for x in a:
        x = to_num(x)
        if x != x:
            return NAN
        if x < r:
            r = x
    return r


@fn(MATH, "pow", 2)
def math_pow(F, this, a=UNDEF, b=UNDEF, *_):
    return rt.power(a, b)


@fn(MATH, "atan2", 2)
def math_atan2(F, this, a=UNDEF, b=UNDEF, *_):
    return math.atan2(to_num(a), to_num(b))


@fn(MATH, "hypot", 2)
def math_hypot(F, this, *a):
    s = 0.0
    for x in a:
        x = to_num(x)
        if x in (INF, -INF):
            return INF
        s += x * x
    return rt.norm(math.sqrt(s)) if s else 0


@fn(MATH, "imul", 2)
def math_imul(F, this, a=UNDEF, b=UNDEF, *_):
    return rt.to_int32(rt.to_int32(a) * rt.to_int32(b))


_rand = [int(time.time() * 1000) & 0xFFFFFFFFFFFF or 12345]


@fn(MATH, "random", 0)
def math_random(F, this, *_):
    x = _rand[0]
    x = (x * 25214903917 + 11) & 0xFFFFFFFFFFFF
    _rand[0] = x
    return (x >> 16) / 4294967296.0


# ---- String ----

def string_ctor(F, this, *a):
    if a:
        v = a[0]
        s = symbol_to_string(None, v) if type(v) is Symbol and this is not MISSING else to_str(v)
    else:
        s = ""
    p = new_target_proto(STRING_PROTO) if this is MISSING else None
    if p is None:
        return s
    o = JSObject(p, "String")
    o.x = s
    return o


STRING = ctor("String", string_ctor, 1, STRING_PROTO)
STRING_PROTO.x = ""


def this_str(v):
    if type(v) is str:
        return v
    if v is None or v is UNDEF:
        throw_type("String.prototype method called on null or undefined")
    if isinstance(v, JSObject) and v.cls == "String" and type(v.x) is str:
        return v.x
    return to_str(v)


@fn(STRING, "fromCharCode", 1)
def string_from_char_code(F, this, *a):
    out = []
    i = 0
    codes = [rt.to_uint32(x) & 0xFFFF for x in a]
    while i < len(codes):
        c = codes[i]
        if 0xD800 <= c < 0xDC00 and i + 1 < len(codes) and 0xDC00 <= codes[i + 1] < 0xE000:
            out.append(chr(0x10000 + ((c - 0xD800) << 10) + (codes[i + 1] - 0xDC00)))
            i += 2
            continue
        try:
            out.append(chr(c))
        except ValueError:
            out.append("�")
        i += 1
    return "".join(out)


@fn(STRING, "fromCodePoint", 1)
def string_from_code_point(F, this, *a):
    out = []
    for x in a:
        n = to_num(x)
        if n != int(n) or n < 0 or n > 0x10FFFF:
            throw_range("Invalid code point %s" % to_str(x))
        try:
            out.append(chr(int(n)))
        except ValueError:
            out.append("�")
    return "".join(out)


@fn(STRING, "raw", 1)
def string_raw(F, this, strings=UNDEF, *subs):
    raw = get(strings, "raw")
    parts = to_list(raw)
    out = []
    for i in range(len(parts)):
        out.append(to_str(parts[i]))
        if i + 1 < len(parts) and i < len(subs):
            out.append(to_str(subs[i]))
    return "".join(out)


def _sm(name, nparams=0):
    return fn(STRING_PROTO, name, nparams)


@_sm("toString")
def str_to_string(F, this, *_):
    if type(this) is str:
        return this
    if isinstance(this, JSObject) and this.cls == "String":
        return this.x
    throw_type("String.prototype.toString requires that 'this' be a String")


define(STRING_PROTO, "valueOf", STRING_PROTO.p["toString"].v)


@_sm("charAt", 1)
def str_char_at(F, this, i=UNDEF, *_):
    s = this_str(this)
    i = to_int(i)
    return s[int(i)] if 0 <= i < len(s) else ""


@_sm("charCodeAt", 1)
def str_char_code_at(F, this, i=UNDEF, *_):
    s = this_str(this)
    i = to_int(i)
    if 0 <= i < len(s):
        c = ord(s[int(i)])
        return c if c < 0x10000 else 0xD800 + ((c - 0x10000) >> 10)
    return NAN


@_sm("codePointAt", 1)
def str_code_point_at(F, this, i=UNDEF, *_):
    s = this_str(this)
    i = to_int(i)
    return ord(s[int(i)]) if 0 <= i < len(s) else UNDEF


@_sm("at", 1)
def str_at(F, this, i=UNDEF, *_):
    s = this_str(this)
    i = to_int(i)
    if i < 0:
        i += len(s)
    return s[int(i)] if 0 <= i < len(s) else UNDEF


@_sm("indexOf", 1)
def str_index_of(F, this, sub=UNDEF, pos=UNDEF, *_):
    s = this_str(this)
    p = max(0, min(int(to_int(pos)), len(s))) if pos is not UNDEF else 0
    return s.find(to_str(sub), p)


@_sm("lastIndexOf", 1)
def str_last_index_of(F, this, sub=UNDEF, pos=UNDEF, *_):
    s = this_str(this)
    sub = to_str(sub)
    n = to_num(pos)
    end = len(s) if n != n else max(0, min(int(n), len(s)))
    return s.rfind(sub, 0, end + len(sub))


@_sm("includes", 1)
def str_includes(F, this, sub=UNDEF, pos=UNDEF, *_):
    s = this_str(this)
    if isinstance(sub, JSObject) and sub.cls == "RegExp":
        throw_type("First argument to String.prototype.includes must not be a regular expression")
    p = int(to_int(pos)) if pos is not UNDEF else 0
    return s.find(to_str(sub), max(0, p)) >= 0


@_sm("startsWith", 1)
def str_starts_with(F, this, sub=UNDEF, pos=UNDEF, *_):
    s = this_str(this)
    p = int(to_int(pos)) if pos is not UNDEF else 0
    return s.startswith(to_str(sub), max(0, p))


@_sm("endsWith", 1)
def str_ends_with(F, this, sub=UNDEF, end=UNDEF, *_):
    s = this_str(this)
    e = len(s) if end is UNDEF else max(0, min(int(to_int(end)), len(s)))
    return s[:e].endswith(to_str(sub))


@_sm("slice", 2)
def str_slice(F, this, a=UNDEF, b=UNDEF, *_):
    s = this_str(this)
    n = len(s)
    return s[rt.to_index(a, n, 0):rt.to_index(b, n, n)]


@_sm("substring", 2)
def str_substring(F, this, a=UNDEF, b=UNDEF, *_):
    s = this_str(this)
    n = len(s)
    x = max(0, min(int(to_int(a)) if to_int(a) not in (INF, -INF) else (n if to_int(a) > 0 else 0), n))
    y = n if b is UNDEF else max(0, min(int(to_int(b)) if to_int(b) not in (INF, -INF) else
                                        (n if to_int(b) > 0 else 0), n))
    if x > y:
        x, y = y, x
    return s[x:y]


@_sm("substr", 2)
def str_substr(F, this, a=UNDEF, n=UNDEF, *_):
    s = this_str(this)
    start = rt.to_index(a, len(s), 0)
    k = len(s) - start if n is UNDEF else max(0, int(min(to_int(n), len(s))))
    return s[start:start + k]


@_sm("toUpperCase")
def str_upper(F, this, *_):
    return this_str(this).upper()


@_sm("toLowerCase")
def str_lower(F, this, *_):
    return this_str(this).lower()


define(STRING_PROTO, "toLocaleUpperCase", STRING_PROTO.p["toUpperCase"].v)
define(STRING_PROTO, "toLocaleLowerCase", STRING_PROTO.p["toLowerCase"].v)


@_sm("trim")
def str_trim(F, this, *_):
    return this_str(this).strip(rt._WS)


@_sm("trimStart")
def str_trim_start(F, this, *_):
    return this_str(this).lstrip(rt._WS)


@_sm("trimEnd")
def str_trim_end(F, this, *_):
    return this_str(this).rstrip(rt._WS)


define(STRING_PROTO, "trimLeft", STRING_PROTO.p["trimStart"].v)
define(STRING_PROTO, "trimRight", STRING_PROTO.p["trimEnd"].v)


def _pad(s, n, fill, start):
    n = int(to_int(n))
    fill = " " if fill is UNDEF else to_str(fill)
    if n <= len(s) or not fill:
        return s
    need = n - len(s)
    p = (fill * (need // len(fill) + 1))[:need]
    return p + s if start else s + p


@_sm("padStart", 2)
def str_pad_start(F, this, n=UNDEF, fill=UNDEF, *_):
    return _pad(this_str(this), n, fill, True)


@_sm("padEnd", 2)
def str_pad_end(F, this, n=UNDEF, fill=UNDEF, *_):
    return _pad(this_str(this), n, fill, False)


@_sm("repeat", 1)
def str_repeat(F, this, n=UNDEF, *_):
    n = to_int(n)
    if n < 0 or n == INF:
        throw_range("Invalid count value: %s" % to_str(n))
    return this_str(this) * int(n)


@_sm("concat", 1)
def str_concat(F, this, *a):
    return this_str(this) + "".join(to_str(x) for x in a)


@_sm("localeCompare", 1)
def str_locale_compare(F, this, other=UNDEF, *_):
    a = this_str(this)
    b = to_str(other)
    ka, kb = a.lower(), b.lower()
    if ka != kb:
        return -1 if ka < kb else 1
    return 0 if a == b else (-1 if a > b else 1)


@_sm("normalize")
def str_normalize(F, this, *_):
    return this_str(this)


@_sm("isWellFormed")
def str_well_formed(F, this, *_):
    return True


@_sm("split", 2)
def str_split(F, this, sep=UNDEF, limit=UNDEF, *_):
    s = this_str(this)
    lim = 0xFFFFFFFF if limit is UNDEF else rt.to_uint32(limit)
    if isinstance(sep, JSObject) and sep.cls == "RegExp":
        from js import builtins2
        return builtins2.regexp_split(sep, s, lim)
    if sep is UNDEF:
        return JSArray([s][:lim])
    sep = to_str(sep)
    if lim == 0:
        return JSArray([])
    if sep == "":
        return JSArray(list(s)[:lim])
    return JSArray(s.split(sep)[:lim])


def _regexp_method(name):
    def code(F, this, pat=UNDEF, *a):
        from js import builtins2
        return builtins2.string_regexp_op(name, this_str(this), pat, a)
    return code


for _n in ("match", "matchAll", "search", "replace", "replaceAll"):
    define(STRING_PROTO, _n, native_fn(_regexp_method(_n), _n, 2 if _n.startswith("replace") else 1))


def _str_iterator(F, this, *_):
    return py_iterator(iter(this_str(this)))


define(STRING_PROTO, rt.SYM_ITERATOR, native_fn(_str_iterator, "[Symbol.iterator]"))

for _n, _t in (("anchor", "a"), ("big", "big"), ("bold", "b"), ("italics", "i"), ("small", "small"),
               ("strike", "strike"), ("sub", "sub"), ("sup", "sup")):
    define(STRING_PROTO, _n, native_fn((lambda t: lambda F, this, *a: "<%s>%s</%s>" % (t, this_str(this), t))(_t),
                                       _n))

# ---- iterators ----

PY_ITER_PROTO = JSObject(ITERATOR_PROTO, "PyIterator")


def py_iterator(it, tag="Array Iterator"):
    o = JSObject(PY_ITER_PROTO, "PyIterator")
    o.x = it
    return o


@fn(PY_ITER_PROTO, "next", 0)
def py_iter_next(F, this, *_):
    it = this.x if isinstance(this, JSObject) else None
    if it is None:
        throw_type("next called on a non-iterator")
    try:
        return iter_result(next(it), False)
    except StopIteration:
        return iter_result(UNDEF, True)


define(ITERATOR_PROTO, rt.SYM_ITERATOR, native_fn(lambda F, this, *_: this, "[Symbol.iterator]"))


def _iter_helper(name, make):
    def code(F, this, f=UNDEF, *a):
        return py_iterator(make(rt.iterate(this), f, a))
    define(ITERATOR_PROTO, name, native_fn(code, name, 1))


def _it_map(it, f, a):
    i = 0
    for v in it:
        yield call(f, UNDEF, v, i)
        i += 1


def _it_filter(it, f, a):
    i = 0
    for v in it:
        if truthy(call(f, UNDEF, v, i)):
            yield v
        i += 1


def _it_take(it, n, a):
    n = to_int(n)
    for v in it:
        if n <= 0:
            return
        n -= 1
        yield v


def _it_drop(it, n, a):
    n = to_int(n)
    for v in it:
        if n > 0:
            n -= 1
            continue
        yield v


for _n, _mk in (("map", _it_map), ("filter", _it_filter), ("take", _it_take), ("drop", _it_drop)):
    _iter_helper(_n, _mk)


@fn(ITERATOR_PROTO, "toArray", 0)
def iter_to_array(F, this, *_):
    return JSArray(list(rt.iterate(this)))


@fn(ITERATOR_PROTO, "forEach", 1)
def iter_for_each(F, this, f=UNDEF, *_):
    i = 0
    for v in rt.iterate(this):
        call(f, UNDEF, v, i)
        i += 1
    return UNDEF


# generators
define(GENERATOR_PROTO, rt.SYM_TO_STRING_TAG, "Generator", w=False)


@fn(GENERATOR_PROTO, "next", 1)
def gen_next(F, this, v=UNDEF, *_):
    return interp.gen_resume(this, 0, v)


interp.GEN_NEXT[0] = GENERATOR_PROTO.p["next"].v


@fn(GENERATOR_PROTO, "throw", 1)
def gen_throw(F, this, v=UNDEF, *_):
    return interp.gen_resume(this, 1, v)


@fn(GENERATOR_PROTO, "return", 1)
def gen_return(F, this, v=UNDEF, *_):
    return interp.gen_resume(this, 2, v)


define(ASYNC_GENERATOR_PROTO, rt.SYM_ASYNC_ITERATOR, native_fn(lambda F, this, *_: this, "[Symbol.asyncIterator]"))
for _n, _m in (("next", 0), ("throw", 1), ("return", 2)):
    define(ASYNC_GENERATOR_PROTO, _n,
           native_fn((lambda m: lambda F, this, v=UNDEF, *_: interp.async_gen_request(this, m, v))(_m), _n, 1))

# ---- Array ----


def array_ctor(F, this, *a):
    p = new_target_proto(ARRAY_PROTO) if this is MISSING else None
    if len(a) == 1 and type(a[0]) in (int, float) and type(a[0]) is not bool:
        n = a[0]
        if n != int(n) or n < 0 or n > 4294967295:
            throw_range("Invalid array length")
        arr = JSArray([HOLE] * int(n))
    else:
        arr = JSArray(list(a))
    if p is not None:
        arr.proto = p
    return arr


ARRAY = ctor("Array", array_ctor, 1, ARRAY_PROTO)


@fn(ARRAY, "isArray", 1)
def array_is_array(F, this, v=UNDEF, *_):
    if isinstance(v, JSProxy):
        v = v.target
    return type(v) is JSArray and v.cls == "Array"


@fn(ARRAY, "of", 0)
def array_of(F, this, *a):
    return JSArray(list(a))


@fn(ARRAY, "from", 1)
def array_from(F, this, items=UNDEF, f=UNDEF, t=UNDEF, *_):
    if items is None or items is UNDEF:
        throw_type("%s is not iterable" % rt.to_str(items))
    it = get(items, rt.SYM_ITERATOR) if isinstance(items, JSObject) or type(items) is str else UNDEF
    vals = list(rt.iterate(items)) if isinstance(it, JSFunction) else to_list(items)
    if f is not UNDEF:
        callable_(f)
        vals = [call(f, t, vals[i], i) for i in range(len(vals))]
    out = JSArray(vals)
    if isinstance(this, JSFunction) and this is not ARRAY and this.info.ctor and this.info.kind != "native":
        o = construct(this, [])
        for i in range(len(vals)):
            putv(o, i, vals[i])
        put(o, "length", len(vals))
        return o
    return out


define(ARRAY, rt.SYM_SPECIES, ARRAY)


def _am(name, nparams=0):
    return fn(ARRAY_PROTO, name, nparams)


def items_of(this):
    if type(this) is JSArray:
        return this.a
    return to_list(to_obj(this))


def _vals(this):
    if type(this) is JSArray:
        a = this.a
        return [UNDEF if x is HOLE else x for x in a] if HOLE in a else a
    return to_list(to_obj(this))


def _arr(this):
    if type(this) is JSArray:
        return this
    if isinstance(this, JSProxy) and type(this.target) is JSArray:
        return this.target
    return None


@_am("push", 1)
def array_push(F, this, *a):
    arr = _arr(this)
    if arr is not None and not isinstance(this, JSProxy):
        if not arr.ext:
            throw_type("Cannot add property, object is not extensible")
        arr.a.extend(a)
        return len(arr.a)
    n = rt.to_int(get(this, "length"))
    for v in a:
        putv(this, n, v)
        n += 1
    put(this, "length", n)
    return n


@_am("pop")
def array_pop(F, this, *_):
    arr = _arr(this)
    if arr is not None and not isinstance(this, JSProxy):
        if not arr.a:
            return UNDEF
        v = arr.a.pop()
        return UNDEF if v is HOLE else v
    n = rt.to_int(get(this, "length"))
    if n <= 0:
        put(this, "length", 0)
        return UNDEF
    v = getv(this, n - 1)
    rt.delete(this, str(int(n - 1)))
    put(this, "length", n - 1)
    return v


@_am("shift")
def array_shift(F, this, *_):
    arr = _arr(this)
    if arr is not None:
        if not arr.a:
            return UNDEF
        v = arr.a.pop(0)
        return UNDEF if v is HOLE else v
    lst = to_list(this)
    if not lst:
        return UNDEF
    for i in range(1, len(lst)):
        putv(this, i - 1, lst[i])
    rt.delete(this, str(len(lst) - 1))
    put(this, "length", len(lst) - 1)
    return lst[0]


@_am("unshift", 1)
def array_unshift(F, this, *a):
    arr = _arr(this)
    if arr is not None:
        arr.a[0:0] = list(a)
        return len(arr.a)
    lst = list(a) + to_list(this)
    for i in range(len(lst)):
        putv(this, i, lst[i])
    put(this, "length", len(lst))
    return len(lst)


@_am("slice", 2)
def array_slice(F, this, a=UNDEF, b=UNDEF, *_):
    v = items_of(this)
    n = len(v)
    return JSArray(v[rt.to_index(a, n, 0):rt.to_index(b, n, n)])


@_am("splice", 2)
def array_splice(F, this, start=UNDEF, count=UNDEF, *items):
    arr = _arr(this)
    lst = arr.a if arr is not None else to_list(this)
    n = len(lst)
    s = rt.to_index(start, n, 0)
    if start is UNDEF and count is UNDEF:
        c = 0
    elif count is UNDEF:
        c = n - s
    else:
        c = max(0, min(int(to_int(count)), n - s))
    removed = lst[s:s + c]
    lst[s:s + c] = list(items)
    if arr is None:
        for i in range(len(lst)):
            putv(this, i, lst[i])
        for i in range(len(lst), n):
            rt.delete(this, str(i))
        put(this, "length", len(lst))
    return JSArray(removed)


@_am("concat", 1)
def array_concat(F, this, *a):
    out = list(items_of(this)) if type(this) is JSArray else [to_obj(this)]
    for x in a:
        if type(x) is JSArray or (isinstance(x, JSObject) and truthy(x.get(SYM_SPREADABLE))):
            out.extend(items_of(x))
        else:
            out.append(x)
    return JSArray(out)


SYM_SPREADABLE = SYMBOL.p["isConcatSpreadable"].v


@_am("join", 1)
def array_join(F, this, sep=UNDEF, *_):
    sep = "," if sep is UNDEF else to_str(sep)
    if id(this) in _JOINING:
        return ""
    _JOINING.add(id(this))
    try:
        return sep.join("" if (x is UNDEF or x is None or x is HOLE) else
                        (x if type(x) is str else to_str(x)) for x in items_of(this))
    finally:
        _JOINING.discard(id(this))


_JOINING = set()


@_am("toString")
def array_to_string(F, this, *_):
    j = get(this, "join")
    if isinstance(j, JSFunction):
        return call(j, this)
    return op_to_string(F, this)


@_am("toLocaleString")
def array_to_locale(F, this, *_):
    return ",".join("" if x is UNDEF or x is None else to_str(rt.callm(x, "toLocaleString"))
                    for x in _vals(this))


@_am("reverse")
def array_reverse(F, this, *_):
    arr = _arr(this)
    if arr is not None:
        arr.a.reverse()
        return this
    lst = to_list(this)
    lst.reverse()
    for i in range(len(lst)):
        putv(this, i, lst[i])
    return this


@_am("indexOf", 1)
def array_index_of(F, this, v=UNDEF, start=UNDEF, *_):
    a = items_of(this)
    n = len(a)
    i = rt.to_index(start, n, 0)
    seq = rt.seq
    while i < n:
        x = a[i]
        if x is v or seq(x, v):
            return i
        i += 1
    return -1


@_am("lastIndexOf", 1)
def array_last_index_of(F, this, v=UNDEF, *a):
    lst = items_of(this)
    n = len(lst)
    i = n - 1 if not a else (int(to_int(a[0])) if to_int(a[0]) >= 0 else n + int(to_int(a[0])))
    i = min(i, n - 1)
    while i >= 0:
        if rt.seq(lst[i], v):
            return i
        i -= 1
    return -1


@_am("includes", 1)
def array_includes(F, this, v=UNDEF, start=UNDEF, *_):
    a = _vals(this)
    n = len(a)
    for i in range(rt.to_index(start, n, 0), n):
        if same_value_zero(a[i], v):
            return True
    return False


def _cb_loop(this, f, t):
    callable_(f)
    return _vals(this), f.info.code, f


@_am("forEach", 1)
def array_for_each(F, this, f=UNDEF, t=UNDEF, *_):
    callable_(f)
    code = f.info.code
    a = items_of(this)
    i = 0
    while i < len(a):
        x = a[i]
        if x is not HOLE:
            code(f, t, x, i, this)
        i += 1
    return UNDEF


@_am("map", 1)
def array_map(F, this, f=UNDEF, t=UNDEF, *_):
    callable_(f)
    code = f.info.code
    a = items_of(this)
    out = []
    for i in range(len(a)):
        x = a[i]
        out.append(HOLE if x is HOLE else code(f, t, x, i, this))
    return JSArray(out)


@_am("filter", 1)
def array_filter(F, this, f=UNDEF, t=UNDEF, *_):
    callable_(f)
    code = f.info.code
    a = items_of(this)
    out = []
    for i in range(len(a)):
        x = a[i]
        if x is not HOLE and truthy(code(f, t, x, i, this)):
            out.append(x)
    return JSArray(out)


@_am("some", 1)
def array_some(F, this, f=UNDEF, t=UNDEF, *_):
    callable_(f)
    a = items_of(this)
    for i in range(len(a)):
        if a[i] is not HOLE and truthy(f.info.code(f, t, a[i], i, this)):
            return True
    return False


@_am("every", 1)
def array_every(F, this, f=UNDEF, t=UNDEF, *_):
    callable_(f)
    a = items_of(this)
    for i in range(len(a)):
        if a[i] is not HOLE and not truthy(f.info.code(f, t, a[i], i, this)):
            return False
    return True


def _find(this, f, t, rev, want_index):
    callable_(f)
    a = _vals(this)
    rng = range(len(a) - 1, -1, -1) if rev else range(len(a))
    for i in rng:
        if truthy(f.info.code(f, t, a[i], i, this)):
            return i if want_index else a[i]
    return -1 if want_index else UNDEF


@_am("find", 1)
def array_find(F, this, f=UNDEF, t=UNDEF, *_):
    return _find(this, f, t, False, False)


@_am("findIndex", 1)
def array_find_index(F, this, f=UNDEF, t=UNDEF, *_):
    return _find(this, f, t, False, True)


@_am("findLast", 1)
def array_find_last(F, this, f=UNDEF, t=UNDEF, *_):
    return _find(this, f, t, True, False)


@_am("findLastIndex", 1)
def array_find_last_index(F, this, f=UNDEF, t=UNDEF, *_):
    return _find(this, f, t, True, True)


@_am("reduce", 1)
def array_reduce(F, this, f=UNDEF, *init):
    callable_(f)
    a = [x for x in items_of(this)]
    idx = [i for i in range(len(a)) if a[i] is not HOLE]
    if init:
        acc = init[0]
    else:
        if not idx:
            throw_type("Reduce of empty array with no initial value")
        acc = a[idx[0]]
        idx = idx[1:]
    code = f.info.code
    for i in idx:
        acc = code(f, UNDEF, acc, a[i], i, this)
    return acc


@_am("reduceRight", 1)
def array_reduce_right(F, this, f=UNDEF, *init):
    callable_(f)
    a = items_of(this)
    idx = [i for i in range(len(a) - 1, -1, -1) if a[i] is not HOLE]
    if init:
        acc = init[0]
    else:
        if not idx:
            throw_type("Reduce of empty array with no initial value")
        acc = a[idx[0]]
        idx = idx[1:]
    for i in idx:
        acc = call(f, UNDEF, acc, a[i], i, this)
    return acc


@_am("fill", 1)
def array_fill(F, this, v=UNDEF, s=UNDEF, e=UNDEF, *_):
    arr = _arr(this)
    if arr is None:
        return this
    n = len(arr.a)
    for i in range(rt.to_index(s, n, 0), rt.to_index(e, n, n)):
        arr.a[i] = v
    return this


def _sort_key_cmp(f):
    def cmp(a, b):
        if a is UNDEF or a is HOLE:
            return 0 if (b is UNDEF or b is HOLE) else 1
        if b is UNDEF or b is HOLE:
            return -1
        if f is UNDEF:
            sa = a if type(a) is str else to_str(a)
            sb = b if type(b) is str else to_str(b)
            return -1 if sa < sb else (1 if sa > sb else 0)
        r = to_num(f.info.code(f, UNDEF, a, b))
        return -1 if r < 0 else (1 if r > 0 else 0)
    return cmp


def merge_sort(a, cmp):
    """A stable sort with a comparison function (MicroPython's sort has no cmp_to_key)."""
    n = len(a)
    if n < 2:
        return a
    # insertion sort on small runs, then merges
    run = 16
    for s in range(0, n, run):
        e = min(s + run, n)
        for i in range(s + 1, e):
            x = a[i]
            j = i - 1
            while j >= s and cmp(a[j], x) > 0:
                a[j + 1] = a[j]
                j -= 1
            a[j + 1] = x
    width = run
    while width < n:
        out = []
        for s in range(0, n, 2 * width):
            m = min(s + width, n)
            e = min(s + 2 * width, n)
            i, j = s, m
            while i < m and j < e:
                if cmp(a[j], a[i]) < 0:
                    out.append(a[j])
                    j += 1
                else:
                    out.append(a[i])
                    i += 1
            out.extend(a[i:m])
            out.extend(a[j:e])
        a = out
        width *= 2
    return a


@_am("sort", 1)
def array_sort(F, this, f=UNDEF, *_):
    if f is not UNDEF:
        callable_(f)
    arr = _arr(this)
    lst = arr.a if arr is not None else to_list(this)
    if f is UNDEF and all(type(x) is str for x in lst):
        lst.sort()
        out = lst
    else:
        out = merge_sort(list(lst), _sort_key_cmp(f))
    if arr is not None:
        arr.a[:] = out
    else:
        for i in range(len(out)):
            putv(this, i, out[i])
    return this


@_am("toSorted", 1)
def array_to_sorted(F, this, f=UNDEF, *_):
    a = JSArray(list(_vals(this)))
    return array_sort(F, a, f)


@_am("toReversed")
def array_to_reversed(F, this, *_):
    return JSArray(list(reversed(_vals(this))))


@_am("toSpliced", 2)
def array_to_spliced(F, this, *a):
    c = JSArray(list(_vals(this)))
    array_splice(F, c, *a)
    return c


@_am("with", 2)
def array_with(F, this, i=UNDEF, v=UNDEF, *_):
    a = list(_vals(this))
    k = int(to_int(i))
    if k < 0:
        k += len(a)
    if not 0 <= k < len(a):
        throw_range("Invalid index : %s" % to_str(i))
    a[k] = v
    return JSArray(a)


@_am("at", 1)
def array_at(F, this, i=UNDEF, *_):
    a = items_of(this)
    k = int(to_int(i))
    if k < 0:
        k += len(a)
    if 0 <= k < len(a):
        v = a[k]
        return UNDEF if v is HOLE else v
    return UNDEF


def _flat(a, depth, out):
    for x in a:
        if x is HOLE:
            continue
        if depth > 0 and type(x) is JSArray:
            _flat(x.a, depth - 1, out)
        else:
            out.append(x)
    return out


@_am("flat", 0)
def array_flat(F, this, depth=UNDEF, *_):
    d = 1 if depth is UNDEF else to_int(depth)
    return JSArray(_flat(items_of(this), d, []))


@_am("flatMap", 1)
def array_flat_map(F, this, f=UNDEF, t=UNDEF, *_):
    callable_(f)
    out = []
    a = _vals(this)
    for i in range(len(a)):
        r = call(f, t, a[i], i, this)
        if type(r) is JSArray:
            out.extend(_vals(r))
        else:
            out.append(r)
    return JSArray(out)


@_am("copyWithin", 2)
def array_copy_within(F, this, t=UNDEF, s=UNDEF, e=UNDEF, *_):
    arr = _arr(this)
    if arr is None:
        return this
    a = arr.a
    n = len(a)
    to = rt.to_index(t, n, 0)
    fr = rt.to_index(s, n, 0)
    end = rt.to_index(e, n, n)
    chunk = a[fr:end][:max(0, n - to)]
    a[to:to + len(chunk)] = chunk
    return this


def _array_iter(this, kind):
    arr = _arr(this)

    def gen():
        i = 0
        while True:
            if arr is not None:
                n = len(arr.a)
            else:
                n = rt.to_int(get(this, "length"))
            if i >= n:
                return
            if kind == 0:
                yield i
            else:
                v = arr.a[i] if arr is not None else getv(this, i)
                if v is HOLE:
                    v = UNDEF
                yield v if kind == 1 else JSArray([i, v])
            i += 1
    return py_iterator(gen())


@_am("keys")
def array_keys(F, this, *_):
    return _array_iter(this, 0)


@_am("values")
def array_values(F, this, *_):
    return _array_iter(this, 1)


@_am("entries")
def array_entries(F, this, *_):
    return _array_iter(this, 2)


define(ARRAY_PROTO, rt.SYM_ITERATOR, ARRAY_PROTO.p["values"].v)
rt._ARRAY_VALUES[0] = ARRAY_PROTO.p[rt.SYM_ITERATOR]
# the iterate() fast path compares with the slot itself
rt._ARRAY_VALUES[0] = ARRAY_PROTO.p.get(rt.SYM_ITERATOR)
interp.ARGUMENTS_PROTO.p[rt.SYM_ITERATOR] = ARRAY_PROTO.p[rt.SYM_ITERATOR]
interp.ARGUMENTS_PROTO.ks.append(rt.SYM_ITERATOR)

# ---- JSON ----

JSON = JSObject(OBJECT_PROTO, "JSON")
define(JSON, rt.SYM_TO_STRING_TAG, "JSON", w=False)


class _JSONParser:
    def __init__(self, s):
        self.s = s
        self.i = 0
        self.n = len(s)

    def ws(self):
        s = self.s
        i = self.i
        n = self.n
        while i < n and s[i] in " \t\n\r":
            i += 1
        self.i = i

    def error(self):
        if self.i >= self.n:
            rt.throw("SyntaxError", "Unexpected end of JSON input")
        rt.throw("SyntaxError", "Unexpected token '%s', \"%s\" is not valid JSON"
                 % (self.s[self.i], self.s[max(0, self.i - 10):self.i + 10]))

    def value(self):
        self.ws()
        if self.i >= self.n:
            self.error()
        c = self.s[self.i]
        if c == "{":
            self.i += 1
            o = JSObject(OBJECT_PROTO)
            self.ws()
            if self.i < self.n and self.s[self.i] == "}":
                self.i += 1
                return o
            while True:
                self.ws()
                if self.i >= self.n or self.s[self.i] != '"':
                    self.error()
                k = self.string()
                self.ws()
                if self.i >= self.n or self.s[self.i] != ":":
                    self.error()
                self.i += 1
                v = self.value()
                if k == "__proto__":
                    if k not in o.p:
                        o.ks.append(k)
                    o.p[k] = v
                else:
                    rt.define_value(o, k, v)
                self.ws()
                if self.i < self.n and self.s[self.i] == ",":
                    self.i += 1
                    continue
                if self.i < self.n and self.s[self.i] == "}":
                    self.i += 1
                    return o
                self.error()
        if c == "[":
            self.i += 1
            a = []
            self.ws()
            if self.i < self.n and self.s[self.i] == "]":
                self.i += 1
                return JSArray(a)
            while True:
                a.append(self.value())
                self.ws()
                if self.i < self.n and self.s[self.i] == ",":
                    self.i += 1
                    continue
                if self.i < self.n and self.s[self.i] == "]":
                    self.i += 1
                    return JSArray(a)
                self.error()
        if c == '"':
            return self.string()
        if c == "t" and self.s.startswith("true", self.i):
            self.i += 4
            return True
        if c == "f" and self.s.startswith("false", self.i):
            self.i += 5
            return False
        if c == "n" and self.s.startswith("null", self.i):
            self.i += 4
            return None
        if c == "-" or c.isdigit():
            s = self.s
            j = self.i
            if s[j] == "-":
                j += 1
            if j >= self.n or not s[j].isdigit():
                self.i = j
                self.error()
            if s[j] == "0" and j + 1 < self.n and s[j + 1].isdigit():
                self.i = j + 1
                self.error()
            while j < self.n and s[j].isdigit():
                j += 1
            isf = False
            if j < self.n and s[j] == ".":
                isf = True
                j += 1
                if j >= self.n or not s[j].isdigit():
                    self.i = j
                    self.error()
                while j < self.n and s[j].isdigit():
                    j += 1
            if j < self.n and s[j] in "eE":
                isf = True
                j += 1
                if j < self.n and s[j] in "+-":
                    j += 1
                while j < self.n and s[j].isdigit():
                    j += 1
            text = s[self.i:j]
            self.i = j
            if isf:
                v = float(text)
                return int(v) if v == int(v) and abs(v) <= rt.MAX_SAFE and text != "-0.0" else v
            v = int(text)
            if text == "-0":
                return -0.0
            return v if abs(v) <= rt.MAX_SAFE else float(v)
        self.error()

    def string(self):
        s = self.s
        i = self.i + 1
        out = []
        n = self.n
        while True:
            j = i
            while j < n and s[j] != '"' and s[j] != "\\":
                if s[j] < " ":
                    self.i = j
                    self.error()
                j += 1
            out.append(s[i:j])
            if j >= n:
                self.i = j
                self.error()
            if s[j] == '"':
                self.i = j + 1
                return "".join(out)
            c = s[j + 1] if j + 1 < n else ""
            if c == "u":
                h = s[j + 2:j + 6]
                try:
                    cp = int(h, 16)
                except ValueError:
                    self.i = j
                    self.error()
                i = j + 6
                if 0xD800 <= cp < 0xDC00 and s[i:i + 2] == "\\u":
                    try:
                        lo = int(s[i + 2:i + 6], 16)
                        if 0xDC00 <= lo < 0xE000:
                            cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                            i += 6
                    except ValueError:
                        pass
                try:
                    out.append(chr(cp))
                except ValueError:
                    out.append("�")
                continue
            m = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}.get(c)
            if m is None:
                self.i = j
                self.error()
            out.append(m)
            i = j + 2


def _revive(holder, key, reviver):
    v = rt.getv(holder, key)
    if isinstance(v, JSObject):
        if type(v) is JSArray:
            for i in range(len(v.a)):
                nv = _revive(v, str(i), reviver)
                if nv is UNDEF:
                    v.a[i] = HOLE
                else:
                    v.a[i] = nv
        else:
            for k in rt.own_enum_keys(v):
                nv = _revive(v, k, reviver)
                if nv is UNDEF:
                    v.remove(k)
                else:
                    rt.define_value(v, k, nv)
    return call(reviver, holder, key, v)


@fn(JSON, "parse", 2)
def json_parse(F, this, text=UNDEF, reviver=UNDEF, *_):
    p = _JSONParser(to_str(text))
    v = p.value()
    p.ws()
    if p.i < p.n:
        p.error()
    if isinstance(reviver, JSFunction):
        root = JSObject(OBJECT_PROTO)
        root.define("", v)
        return _revive(root, "", reviver)
    return v


_ESC = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def json_quote(s):
    out = ['"']
    start = 0
    for i in range(len(s)):
        c = s[i]
        if c == '"' or c == "\\" or c < " " or "\ud800" <= c <= "\udfff":
            out.append(s[start:i])
            e = _ESC.get(c)
            out.append(e if e is not None else "\\u%04x" % ord(c))
            start = i + 1
    out.append(s[start:])
    out.append('"')
    return "".join(out)


def json_str(holder, key, v, rep, allow, gap, ind, stack):
    if isinstance(v, JSObject):
        tj = v.get("toJSON")
        if isinstance(tj, JSFunction):
            v = call(tj, v, key)
    if rep is not None:
        v = call(rep, holder, key, v)
    t = type(v)
    if isinstance(v, JSObject) and not isinstance(v, JSFunction):
        if v.cls == "Number":
            v = to_num(v)
        elif v.cls == "String":
            v = to_str(v)
        elif v.cls == "Boolean":
            v = v.x
        t = type(v)
    if v is None:
        return "null"
    if t is bool:
        return "true" if v else "false"
    if t is str:
        return json_quote(v)
    if t is int:
        return str(v)
    if t is float:
        return rt.num_str(v) if v == v and v not in (INF, -INF) else "null"
    if not isinstance(v, JSObject) or isinstance(v, JSFunction):
        return None
    if id(v) in stack:
        throw_type("Converting circular structure to JSON")
    stack.add(id(v))
    new_ind = ind + gap
    try:
        if type(v) is JSArray or (isinstance(v, JSProxy) and type(v.target) is JSArray):
            items = []
            vals = to_list(v)
            for i in range(len(vals)):
                s = json_str(v, str(i), vals[i], rep, allow, gap, new_ind, stack)
                items.append("null" if s is None else s)
            if not items:
                return "[]"
            if gap:
                return "[\n" + new_ind + (",\n" + new_ind).join(items) + "\n" + ind + "]"
            return "[" + ",".join(items) + "]"
        items = []
        keys = allow if allow is not None else (own_keys_all(v) if isinstance(v, JSProxy) else rt.own_enum_keys(v))
        for k in keys:
            if type(k) is not str:
                continue
            s = json_str(v, k, rt.getv(v, k), rep, allow, gap, new_ind, stack)
            if s is not None:
                items.append(json_quote(k) + (": " if gap else ":") + s)
        if not items:
            return "{}"
        if gap:
            return "{\n" + new_ind + (",\n" + new_ind).join(items) + "\n" + ind + "}"
        return "{" + ",".join(items) + "}"
    finally:
        stack.discard(id(v))


@fn(JSON, "stringify", 3)
def json_stringify(F, this, v=UNDEF, rep=UNDEF, space=UNDEF, *_):
    allow = None
    r = None
    if isinstance(rep, JSFunction):
        r = rep
    elif type(rep) is JSArray:
        allow = []
        for x in rep.a:
            if type(x) is str or type(x) in (int, float):
                k = to_str(x)
                if k not in allow:
                    allow.append(k)
    if isinstance(space, JSObject):
        space = to_num(space) if space.cls == "Number" else to_str(space)
    if type(space) in (int, float) and type(space) is not bool:
        gap = " " * int(max(0, min(10, space)))
    elif type(space) is str:
        gap = space[:10]
    else:
        gap = ""
    root = JSObject(OBJECT_PROTO)
    root.define("", v)
    s = json_str(root, "", v, r, allow, gap, "", set())
    return UNDEF if s is None else s


# ---- Map, Set, WeakMap, WeakSet ----

class OrderedTable:
    """Keys in insertion order with SameValueZero (for Map and Set)."""
    __slots__ = ("index", "keys", "vals", "size", "holes")

    def __init__(self):
        self.index = {}
        self.keys = []
        self.vals = []
        self.size = 0
        self.holes = 0

    @staticmethod
    def norm(k):
        t = type(k)
        if t is bool:
            return ("b", k)
        if t is float:
            if k != k:
                return ("nan",)
            if k == int(k):
                return int(k)
        return k

    def get(self, k, default=UNDEF):
        i = self.index.get(self.norm(k))
        return default if i is None else self.vals[i]

    def has(self, k):
        return self.norm(k) in self.index

    def set(self, k, v):
        nk = self.norm(k)
        i = self.index.get(nk)
        if i is None:
            if type(k) is float and k == 0:
                k = 0
            self.index[nk] = len(self.keys)
            self.keys.append(k)
            self.vals.append(v)
            self.size += 1
        else:
            self.vals[i] = v

    def delete(self, k):
        nk = self.norm(k)
        i = self.index.pop(nk, None)
        if i is None:
            return False
        self.keys[i] = MISSING
        self.vals[i] = MISSING
        self.size -= 1
        self.holes += 1
        return True

    def clear(self):
        for i in range(len(self.keys)):
            self.keys[i] = MISSING
            self.vals[i] = MISSING
        self.holes += self.size
        self.index = {}
        self.size = 0

    def items(self):
        i = 0
        while i < len(self.keys):
            k = self.keys[i]
            if k is not MISSING:
                yield k, self.vals[i]
            i += 1
        if self.holes > 32 and self.holes > self.size:
            self.compact()

    def compact(self):
        ks, vs = [], []
        for i in range(len(self.keys)):
            if self.keys[i] is not MISSING:
                ks.append(self.keys[i])
                vs.append(self.vals[i])
        self.keys, self.vals = ks, vs
        self.index = {}
        for i in range(len(ks)):
            self.index[self.norm(ks[i])] = i
        self.holes = 0


MAP_PROTO = JSObject(OBJECT_PROTO, "Map")
SET_PROTO = JSObject(OBJECT_PROTO, "Set")
WEAKMAP_PROTO = JSObject(OBJECT_PROTO, "WeakMap")
WEAKSET_PROTO = JSObject(OBJECT_PROTO, "WeakSet")


def _table(this, cls):
    if isinstance(this, JSObject) and type(this.x) is OrderedTable and this.cls == cls:
        return this.x
    throw_type("Method %s.prototype function called on incompatible receiver" % cls)


def _mk_coll(cls, proto, is_map):
    def code(F, this, it=UNDEF, *_):
        p = new_target_proto(proto) if this is MISSING else None
        if p is None:
            throw_type("Constructor %s requires 'new'" % cls)
        o = JSObject(p, cls)
        o.x = OrderedTable()
        if it is not UNDEF and it is not None:
            adder = o.get("set" if is_map else "add")
            for e in rt.iterate(it):
                if is_map:
                    if not isinstance(e, JSObject):
                        throw_type("Iterator value %s is not an entry object" % rt._show(e))
                    call(adder, o, getv(e, 0), getv(e, 1))
                else:
                    call(adder, o, e)
        return o
    return ctor(cls, code, 0, proto)


MAP = _mk_coll("Map", MAP_PROTO, True)
SET = _mk_coll("Set", SET_PROTO, False)
WEAKMAP = _mk_coll("WeakMap", WEAKMAP_PROTO, True)
WEAKSET = _mk_coll("WeakSet", WEAKSET_PROTO, False)
for _p, _n in ((MAP_PROTO, "Map"), (SET_PROTO, "Set"), (WEAKMAP_PROTO, "WeakMap"), (WEAKSET_PROTO, "WeakSet")):
    define(_p, rt.SYM_TO_STRING_TAG, _n, w=False)


def _coll_methods(proto, cls, is_map, weak):
    @fn(proto, "get" if is_map else "has", 1)
    def m_get(F, this, k=UNDEF, *_):
        t = _table(this, cls)
        return t.get(k) if is_map else t.has(k)

    if is_map:
        @fn(proto, "set", 2)
        def m_set(F, this, k=UNDEF, v=UNDEF, *_):
            if weak and not isinstance(k, JSObject) and type(k) is not Symbol:
                throw_type("Invalid value used as weak map key")
            _table(this, cls).set(k, v)
            return this

        @fn(proto, "has", 1)
        def m_has(F, this, k=UNDEF, *_):
            return _table(this, cls).has(k)
    else:
        @fn(proto, "add", 1)
        def m_add(F, this, k=UNDEF, *_):
            if weak and not isinstance(k, JSObject):
                throw_type("Invalid value used in weak set")
            _table(this, cls).set(k, k)
            return this

    @fn(proto, "delete", 1)
    def m_delete(F, this, k=UNDEF, *_):
        return _table(this, cls).delete(k)

    if weak:
        return

    @fn(proto, "clear", 0)
    def m_clear(F, this, *_):
        _table(this, cls).clear()
        return UNDEF

    @getter(proto, "size")
    def m_size(F, this, *_):
        return _table(this, cls).size

    @fn(proto, "forEach", 1)
    def m_for_each(F, this, f=UNDEF, t=UNDEF, *_):
        callable_(f)
        for k, v in _table(this, cls).items():
            call(f, t, v, k, this)
        return UNDEF

    def it(kind):
        def code(F, this, *_):
            table = _table(this, cls)

            def gen():
                for k, v in table.items():
                    yield k if kind == 0 else v if kind == 1 else JSArray([k, v])
            return py_iterator(gen())
        return code

    define(proto, "keys", native_fn(it(0), "keys"))
    define(proto, "values", native_fn(it(1), "values"))
    define(proto, "entries", native_fn(it(2), "entries"))
    define(proto, rt.SYM_ITERATOR, proto.p["entries" if is_map else "values"].v)


_coll_methods(MAP_PROTO, "Map", True, False)
_coll_methods(SET_PROTO, "Set", False, False)
_coll_methods(WEAKMAP_PROTO, "WeakMap", True, True)
_coll_methods(WEAKSET_PROTO, "WeakSet", False, True)


@fn(MAP, "groupBy", 2)
def map_group_by(F, this, items=UNDEF, f=UNDEF, *_):
    m = construct(MAP, [])
    t = m.x
    i = 0
    for v in rt.iterate(items):
        k = call(f, UNDEF, v, i)
        i += 1
        g = t.get(k, None)
        if g is None:
            g = JSArray([])
            t.set(k, g)
        g.a.append(v)
    return m


WEAKREF_PROTO = JSObject(OBJECT_PROTO, "WeakRef")


def weakref_ctor(F, this, target=UNDEF, *_):
    p = new_target_proto(WEAKREF_PROTO) or WEAKREF_PROTO
    o = JSObject(p, "WeakRef")
    o.x = target
    return o


WEAKREF = ctor("WeakRef", weakref_ctor, 1, WEAKREF_PROTO)
define(WEAKREF_PROTO, "deref", native_fn(lambda F, this, *_: this.x, "deref"))
FINREG_PROTO = JSObject(OBJECT_PROTO, "FinalizationRegistry")
FINREG = ctor("FinalizationRegistry", lambda F, this, *a: JSObject(new_target_proto(FINREG_PROTO) or FINREG_PROTO),
              1, FINREG_PROTO)
define(FINREG_PROTO, "register", native_fn(lambda F, this, *a: UNDEF, "register", 2))
define(FINREG_PROTO, "unregister", native_fn(lambda F, this, *a: False, "unregister", 1))

# ---- Promise ----


def _resolving(p):
    done = [False]

    def res(F, this, v=UNDEF, *_):
        if not done[0]:
            done[0] = True
            resolve_promise(p, v)
        return UNDEF

    def rej(F, this, e=UNDEF, *_):
        if not done[0]:
            done[0] = True
            settle(p, REJECTED, e)
        return UNDEF
    return native_fn(res, "", 1), native_fn(rej, "", 1)


def promise_ctor(F, this, executor=UNDEF, *_):
    proto = new_target_proto(PROMISE_PROTO) if this is MISSING else None
    if proto is None:
        throw_type("Promise constructor cannot be invoked without 'new'")
    callable_(executor)
    p = new_promise(proto)
    res, rej = _resolving(p)
    try:
        call(executor, UNDEF, res, rej)
    except JSThrow as e:
        call(rej, UNDEF, e.value)
    return p


PROMISE = ctor("Promise", promise_ctor, 1, PROMISE_PROTO)
define(PROMISE_PROTO, rt.SYM_TO_STRING_TAG, "Promise", w=False)


def promise_then(p, ok, err):
    if not interp.is_promise(p):
        throw_type("Method Promise.prototype.then called on incompatible receiver")
    out = new_promise()
    st = p.x
    st.handled = True
    reaction = (out, ok if isinstance(ok, JSFunction) else None, err if isinstance(err, JSFunction) else None)
    if st.state == PENDING:
        st.reactions.append(reaction)
    else:
        interp._schedule(reaction, st.state, st.value)
    return out


@fn(PROMISE_PROTO, "then", 2)
def promise_proto_then(F, this, ok=UNDEF, err=UNDEF, *_):
    return promise_then(this, ok, err)


interp.PROMISE_THEN[0] = PROMISE_PROTO.p["then"]


@fn(PROMISE_PROTO, "catch", 1)
def promise_catch(F, this, err=UNDEF, *_):
    return rt.callm(this, "then", UNDEF, err)


@fn(PROMISE_PROTO, "finally", 1)
def promise_finally(F, this, f=UNDEF, *_):
    if not isinstance(f, JSFunction):
        return rt.callm(this, "then", f, f)

    def ok(F2, this2, v=UNDEF, *_):
        r = call(f, UNDEF)
        return rt.callm(promise_resolved_value(r), "then", native_fn(lambda F3, t3, *a: v, ""))

    def err(F2, this2, e=UNDEF, *_):
        r = call(f, UNDEF)

        def rethrow(F3, t3, *a):
            raise JSThrow(e)
        return rt.callm(promise_resolved_value(r), "then", native_fn(rethrow, ""))
    return rt.callm(this, "then", native_fn(ok, "", 1), native_fn(err, "", 1))


def promise_resolved_value(v):
    return interp.promise_resolved(v)


@fn(PROMISE, "resolve", 1)
def promise_resolve(F, this, v=UNDEF, *_):
    return interp.promise_resolved(v)


@fn(PROMISE, "reject", 1)
def promise_reject(F, this, e=UNDEF, *_):
    p = new_promise()
    settle(p, REJECTED, e)
    return p


@fn(PROMISE, "withResolvers", 0)
def promise_with_resolvers(F, this, *_):
    p = new_promise()
    res, rej = _resolving(p)
    return rt.obj("promise", p, "resolve", res, "reject", rej)


def _py_cb(f):
    def code(F, this, v=UNDEF, *_):
        f(v)
        return UNDEF
    return native_fn(code, "", 1)


def _combinator(kind):
    def code(F, this, it=UNDEF, *_):
        out = new_promise()
        try:
            items = list(rt.iterate(it))
        except JSThrow as e:
            settle(out, REJECTED, e.value)
            return out
        n = len(items)
        results = [UNDEF] * n
        left = [n]
        if n == 0:
            if kind == "any":
                settle(out, REJECTED, aggregate_ctor(None, None, JSArray([]), "All promises were rejected"))
            elif kind != "race":
                settle(out, FULFILLED, JSArray([]))
            return out
        for i in range(n):
            p = interp.promise_resolved(items[i])

            def ok(v, i=i):
                if kind == "all":
                    results[i] = v
                    left[0] -= 1
                    if left[0] == 0:
                        settle(out, FULFILLED, JSArray(results))
                elif kind == "allSettled":
                    results[i] = rt.obj("status", "fulfilled", "value", v)
                    left[0] -= 1
                    if left[0] == 0:
                        settle(out, FULFILLED, JSArray(results))
                elif kind == "race" or kind == "any":
                    resolve_promise(out, v)

            def err(e, i=i):
                if kind == "all" or kind == "race":
                    settle(out, REJECTED, e)
                elif kind == "allSettled":
                    results[i] = rt.obj("status", "rejected", "reason", e)
                    left[0] -= 1
                    if left[0] == 0:
                        settle(out, FULFILLED, JSArray(results))
                else:
                    results[i] = e
                    left[0] -= 1
                    if left[0] == 0:
                        settle(out, REJECTED, aggregate_ctor(None, None, JSArray(results),
                                                             "All promises were rejected"))
            if p.proto is PROMISE_PROTO:
                then_native(p, ok, err)
            else:
                rt.callm(p, "then", _py_cb(ok), _py_cb(err))
        return out
    return code


for _n in ("all", "allSettled", "race", "any"):
    define(PROMISE, _n, native_fn(_combinator(_n), _n, 1))

# ---- Reflect ----

REFLECT = JSObject(OBJECT_PROTO, "Reflect")
define(REFLECT, rt.SYM_TO_STRING_TAG, "Reflect", w=False)


@fn(REFLECT, "apply", 3)
def reflect_apply(F, this, f=UNDEF, t=UNDEF, a=UNDEF, *_):
    return call(f, t, *to_list(a))


@fn(REFLECT, "construct", 2)
def reflect_construct(F, this, f=UNDEF, a=UNDEF, nt=UNDEF, *_):
    return construct(f, to_list(a), f if nt is UNDEF else nt)


@fn(REFLECT, "defineProperty", 3)
def reflect_define(F, this, o=UNDEF, k=UNDEF, d=UNDEF, *_):
    try:
        object_define_property(None, None, o, k, d)
        return True
    except JSThrow:
        return False


@fn(REFLECT, "deleteProperty", 2)
def reflect_delete(F, this, o=UNDEF, k=UNDEF, *_):
    return rt.delete(o, k)


@fn(REFLECT, "get", 2)
def reflect_get(F, this, o=UNDEF, k=UNDEF, recv=UNDEF, *_):
    if not isinstance(o, JSObject):
        throw_type("Reflect.get called on non-object")
    k = to_key(k)
    if recv is not UNDEF and recv is not o:
        return o.get(k, recv)
    return o.get(k)


@fn(REFLECT, "set", 3)
def reflect_set(F, this, o=UNDEF, k=UNDEF, v=UNDEF, recv=UNDEF, *_):
    if not isinstance(o, JSObject):
        throw_type("Reflect.set called on non-object")
    o.put(to_key(k), v, None if recv is UNDEF else recv)
    return True


@fn(REFLECT, "has", 2)
def reflect_has(F, this, o=UNDEF, k=UNDEF, *_):
    return rt.has_prop(k, o)


@fn(REFLECT, "ownKeys", 1)
def reflect_own_keys(F, this, o=UNDEF, *_):
    if not isinstance(o, JSObject):
        throw_type("Reflect.ownKeys called on non-object")
    return JSArray(own_keys_all(o))


define(REFLECT, "getOwnPropertyDescriptor", OBJECT.p["getOwnPropertyDescriptor"].v)
define(REFLECT, "getPrototypeOf", OBJECT.p["getPrototypeOf"].v)
define(REFLECT, "setPrototypeOf", native_fn(lambda F, this, o=UNDEF, p=UNDEF, *_:
                                            (object_spo(F, this, o, p), True)[1], "setPrototypeOf", 2))
define(REFLECT, "isExtensible", OBJECT.p["isExtensible"].v)
define(REFLECT, "preventExtensions", native_fn(lambda F, this, o=UNDEF, *_: (object_pe(F, this, o), True)[1],
                                               "preventExtensions", 1))

# ---- Proxy ----


class JSProxy(JSObject):
    __slots__ = ("target", "handler")

    def __init__(self, target, handler):
        JSObject.__init__(self, target.proto, target.cls)
        self.target = target
        self.handler = handler

    def trap(self, name):
        if self.handler is None:
            throw_type("Cannot perform '%s' on a proxy that has been revoked" % name)
        t = self.handler.get(name)
        return t if isinstance(t, JSFunction) else None

    def own(self, k):
        t = self.trap("getOwnPropertyDescriptor")
        if t is None:
            return self.target.own(k)
        d = call(t, self.handler, self.target, k)
        if not isinstance(d, JSObject):
            return MISSING
        return d.get("value")

    def own_keys(self):
        return own_keys_all(self)

    def get(self, k, recv=None):
        t = self.trap("get")
        if t is None:
            return self.target.get(k, self if recv is None else recv)
        return call(t, self.handler, self.target, k, self if recv is None else recv)

    def put(self, k, v, recv=None):
        t = self.trap("set")
        if t is None:
            self.target.put(k, v, recv)
            return
        call(t, self.handler, self.target, k, v, self if recv is None else recv)

    def has(self, k):
        t = self.trap("has")
        if t is None:
            return self.target.has(k)
        return truthy(call(t, self.handler, self.target, k))

    def remove(self, k):
        t = self.trap("deleteProperty")
        if t is None:
            return self.target.remove(k)
        return truthy(call(t, self.handler, self.target, k))


class JSProxyFunction(JSFunction):
    __slots__ = ("target", "handler")


def proxy_ctor(F, this, target=UNDEF, handler=UNDEF, *_):
    if this is not MISSING:
        throw_type("Constructor Proxy requires 'new'")
    rt.take_newtarget()
    if not isinstance(target, JSObject) or not isinstance(handler, JSObject):
        throw_type("Cannot create proxy with a non-object as target or handler")
    if isinstance(target, JSFunction):
        return _proxy_function(target, handler)
    return JSProxy(target, handler)


def _proxy_function(target, handler):
    def code(F, this, *a):
        if this is MISSING:
            nt = rt.take_newtarget()
            t = handler.get("construct")
            if isinstance(t, JSFunction):
                return call(t, handler, target, JSArray(list(a)), nt)
            return construct(target, list(a))
        t = handler.get("apply")
        if isinstance(t, JSFunction):
            return call(t, handler, target, this, JSArray(list(a)))
        return call(target, this, *a)
    info = rt.FuncInfo(code, target.info.name, target.info.nparams, "native", target.info.ctor)
    f = JSFunction(info, None, None, target.proto)

    def g(k, recv=None):
        t = handler.get("get")
        if isinstance(t, JSFunction):
            return call(t, handler, target, k, f)
        return target.get(k)
    f.p = target.p
    f.ks = target.ks
    return f


PROXY = native_fn(proxy_ctor, "Proxy", 2, True)


@fn(PROXY, "revocable", 2)
def proxy_revocable(F, this, target=UNDEF, handler=UNDEF, *_):
    p = construct(PROXY, [target, handler])

    def revoke(F2, this2, *_):
        if isinstance(p, JSProxy):
            p.handler = None
        return UNDEF
    return rt.obj("proxy", p, "revoke", native_fn(revoke, "revoke"))


# ---- global functions ----

def is_nan(F, this, v=UNDEF, *_):
    n = to_num(v)
    return type(n) is float and n != n


def is_finite(F, this, v=UNDEF, *_):
    n = to_num(v)
    return type(n) is int or (n == n and n not in (INF, -INF))


_URI_RESERVED = ";/?:@&=+$,#"
_URI_UNESCAPED = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()"


def _encode(s, keep):
    out = []
    for c in s:
        if c in keep:
            out.append(c)
        else:
            if "\ud800" <= c <= "\udfff":
                rt.throw("URIError", "URI malformed")
            for b in c.encode("utf-8"):
                out.append("%%%02X" % b)
    return "".join(out)


def _decode(s, reserved):
    out = bytearray()
    res = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "%":
            try:
                b = int(s[i + 1:i + 3], 16)
                if len(s[i + 1:i + 3]) < 2:
                    raise ValueError
            except ValueError:
                rt.throw("URIError", "URI malformed")
            if b < 0x80 and chr(b) in reserved:
                if out:
                    res.append(_utf8(out))
                    out = bytearray()
                res.append(s[i:i + 3])
            else:
                out.append(b)
            i += 3
        else:
            if out:
                res.append(_utf8(out))
                out = bytearray()
            res.append(c)
            i += 1
    if out:
        res.append(_utf8(out))
    return "".join(res)


def _utf8(b):
    try:
        return bytes(b).decode("utf-8")
    except (UnicodeError, ValueError):
        rt.throw("URIError", "URI malformed")


def escape(F, this, s=UNDEF, *_):
    s = to_str(s)
    keep = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789@*_+-./"
    out = []
    for c in s:
        o = ord(c)
        if c in keep:
            out.append(c)
        elif o < 256:
            out.append("%%%02X" % o)
        else:
            out.append("%%u%04X" % o)
    return "".join(out)


def unescape(F, this, s=UNDEF, *_):
    s = to_str(s)
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "%":
            try:
                if s[i + 1:i + 2] == "u":
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                    i += 6
                    continue
                out.append(chr(int(s[i + 1:i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        out.append(c)
        i += 1
    return "".join(out)


def install_globals(ctx_eval):
    CTX_EVAL[0] = ctx_eval
    g = G
    for name, v in (("Object", OBJECT), ("Function", FUNCTION), ("Array", ARRAY), ("String", STRING),
                    ("Number", NUMBER), ("Boolean", BOOLEAN), ("Symbol", SYMBOL), ("Math", MATH), ("JSON", JSON),
                    ("Error", ERROR), ("Map", MAP), ("Set", SET), ("WeakMap", WEAKMAP), ("WeakSet", WEAKSET),
                    ("WeakRef", WEAKREF), ("FinalizationRegistry", FINREG), ("Promise", PROMISE),
                    ("Reflect", REFLECT), ("Proxy", PROXY), ("parseInt", PARSE_INT), ("parseFloat", PARSE_FLOAT),
                    ("isNaN", native_fn(is_nan, "isNaN", 1)), ("isFinite", native_fn(is_finite, "isFinite", 1)),
                    ("encodeURIComponent", native_fn(lambda F, t, s=UNDEF, *_: _encode(to_str(s), _URI_UNESCAPED),
                                                     "encodeURIComponent", 1)),
                    ("encodeURI", native_fn(lambda F, t, s=UNDEF, *_: _encode(to_str(s), _URI_UNESCAPED +
                                                                              _URI_RESERVED), "encodeURI", 1)),
                    ("decodeURIComponent", native_fn(lambda F, t, s=UNDEF, *_: _decode(to_str(s), ""),
                                                     "decodeURIComponent", 1)),
                    ("decodeURI", native_fn(lambda F, t, s=UNDEF, *_: _decode(to_str(s), _URI_RESERVED),
                                            "decodeURI", 1)),
                    ("escape", native_fn(escape, "escape", 1)), ("unescape", native_fn(unescape, "unescape", 1)),
                    ("globalThis", g)):
        define(g, name, v)
    for name, c in ERRORS.items():
        define(g, name, c)
    define(g, "undefined", UNDEF, w=False, c=False)
    define(g, "NaN", NAN, w=False, c=False)
    define(g, "Infinity", INF, w=False, c=False)
    from js import builtins2
    builtins2.install(g)
