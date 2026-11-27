# What compiled JavaScript calls besides rt: globals, closures, classes,
# object literals, generators, async functions and the promise job queue.
from js import rt
from js.rt import (UNDEF, MISSING, JSObject, JSArray, JSFunction, FuncInfo, Slot, JSThrow, R, HOLE,
                   OBJECT_PROTO, FUNCTION_PROTO, GENERATOR_PROTO, ASYNC_GENERATOR_PROTO, PROMISE_PROTO,
                   throw_type, to_key, get, put, call, truthy)


# ---- globals ----

def gget(name):
    v = R.lex.get(name, MISSING)
    if v is not MISSING:
        return v
    g = R.glob
    v = g.p.get(name, MISSING)
    if v is not MISSING:
        if type(v) is Slot:
            return g.get(name)
        return v
    if g.has(name):
        return g.get(name)
    rt.throw_ref("%s is not defined" % name)


def gset(name, v):
    lex = R.lex
    if name in lex:
        lex[name] = v
        return v
    R.glob.put(name, v)
    return v


def gvar(name):
    g = R.glob
    if name not in g.p and not g.has(name):
        g.define(name, UNDEF)


def gtypeof(name):
    v = R.lex.get(name, MISSING)
    if v is not MISSING:
        return rt.typeof(v)
    g = R.glob
    if not g.has(name):
        return "undefined"
    return rt.typeof(g.get(name))


def gdelete(name):
    return R.glob.remove(name)


def gupd(name, fn, prefix):
    old = rt.to_numeric(gget(name))
    new = fn(old)
    gset(name, new)
    return new if prefix else old


def sset(frame, i, v):
    frame[i] = v
    return v


def supd(frame, i, fn, prefix):
    old = rt.to_numeric(frame[i])
    new = fn(old)
    frame[i] = new
    return new if prefix else old


def upd(o, k, fn, prefix):
    old = rt.to_numeric(rt.getv(o, k))
    new = fn(old)
    rt.putv(o, k, new)
    return new if prefix else old


def upd_super(home, this, k, fn, prefix):
    old = rt.to_numeric(rt.super_get(home, this, k))
    new = fn(old)
    rt.super_put(home, this, k, new)
    return new if prefix else old


def ctor_result(v, this):
    if isinstance(v, JSObject):
        return v
    if v is not UNDEF:
        throw_type("Derived constructors may only return object or undefined")
    return this


def coercible(v):
    if v is None or v is UNDEF:
        throw_type("Cannot destructure '%s' as it is %s." % (rt.to_str(v), rt.to_str(v)))
    return v


def obj_rest(o, used):
    out = JSObject(OBJECT_PROTO)
    if not isinstance(o, JSObject):
        if type(o) is str:
            for i in range(len(o)):
                if str(i) not in used:
                    out.define(str(i), o[i])
        return out
    for k in rt.own_enum_keys(o):
        if k not in used:
            out.define(k, rt.getv(o, k))
    for k in o.ks:
        if type(k) is rt.Symbol and k not in used:
            v = o.p[k]
            if type(v) is not Slot or v.e:
                out.define(k, o.get(k))
    return out


def nullish_or(a, b):
    return b if a is None or a is UNDEF else a


def close_iter(it):
    c = getattr(it, "close", None)
    if c is not None:
        try:
            c()
        except Exception:
            pass


def mkargs(a):
    o = JSArray(list(a), ARGUMENTS_PROTO)
    o.cls = "Arguments"
    return o


ARGUMENTS_PROTO = JSObject(OBJECT_PROTO)


def with_frame(parent, n, f):
    return f([parent] + [UNDEF] * n)


# ---- functions ----

def mkfn(info, env):
    return JSFunction(info, env)


def mkarrow(info, env, this, home):
    f = JSFunction(info, env)
    f.this = this
    f.home = home
    return f


def method(info, env, home, name=None):
    f = JSFunction(info, env)
    f.home = home
    if name is not None and not info.name:
        info.name = name if type(name) is str else "[%s]" % (name.desc if name.desc is not UNDEF else "")
    return f


def objx(env, *items):
    """An object literal with methods, accessors, spreads or computed keys."""
    o = JSObject(OBJECT_PROTO)
    for kind, k, v in items:
        if kind == "=":
            if isinstance(v, JSFunction) and not v.info.name and type(k) is str and v.p.get("name") is None:
                v.info.name = k if v.info.name == "" else v.info.name
            rt.define_value(o, k, v)
        elif kind == "m":
            rt.define_value(o, k, method(v, env, o, k))
        elif kind == "g" or kind == "s":
            f = method(v, env, o, k)
            cur = o.p.get(k)
            if type(cur) is Slot and cur.acc:
                s = cur
            else:
                s = Slot(acc=True)
                if k not in o.p:
                    o.ks.append(k)
                o.p[k] = s
            if kind == "g":
                s.get = f
            else:
                s.set = f
        elif kind == "...":
            copy_props(o, v)
        elif kind == "proto":
            if v is None or isinstance(v, JSObject):
                o.proto = v
    return o


def copy_props(o, src):
    if src is None or src is UNDEF:
        return
    if type(src) is str:
        for i in range(len(src)):
            o.define(str(i), src[i])
        return
    if not isinstance(src, JSObject):
        return
    for k in rt.own_enum_keys(src):
        rt.define_value(o, k, rt.getv(src, k))
    for k in list(src.ks):
        if type(k) is rt.Symbol:
            v = src.p.get(k)
            if type(v) is not Slot or v.e:
                rt.define_value(o, k, src.get(k))


def mkclass(name, sup, ctor_info, env, members):
    """A class: its constructor function, prototype, methods, accessors and fields."""
    if sup is MISSING:
        proto_parent = OBJECT_PROTO
        ctor_parent = FUNCTION_PROTO
        derived = False
    elif sup is None:
        proto_parent = None
        ctor_parent = FUNCTION_PROTO
        derived = True
    else:
        if not isinstance(sup, JSFunction) or not sup.info.ctor:
            throw_type("Class extends value %s is not a constructor or null" % rt._show(sup))
        pp = sup.get("prototype")
        if pp is not None and not isinstance(pp, JSObject):
            throw_type("Class extends value does not have valid prototype property")
        proto_parent = pp
        ctor_parent = sup
        derived = True
    if ctor_info is None:
        ctor_info = FuncInfo(_default_derived if derived else _default_base, name, 0, "class", ctor=True)
        ctor_info.derived = derived
    else:
        ctor_info.derived = derived
        ctor_info.kind = "class"
        ctor_info.ctor = True
        if ctor_info.node is not None:
            ctor_info.node.derived = derived
    if not ctor_info.name:
        ctor_info.name = name
    C = JSFunction(ctor_info, env, None, ctor_parent)
    proto = JSObject(proto_parent)
    C.p["prototype"] = Slot(proto, e=False, w=False, c=False)
    C.ks.append("prototype")
    proto.p["constructor"] = Slot(C, e=False)
    proto.ks.append("constructor")
    C.home = proto
    fields = []
    static_init = []
    for kind, static, k, info in members:
        target = C if static else proto
        if kind == "m":
            f = method(info, env, target, k)
            target.p[k] = Slot(f, e=False)
            if k not in target.ks:
                target.ks.append(k)
        elif kind == "g" or kind == "s":
            f = method(info, env, target, k)
            cur = target.p.get(k)
            if type(cur) is Slot and cur.acc:
                s = cur
            else:
                s = Slot(acc=True, e=False)
                if k not in target.ks:
                    target.ks.append(k)
                target.p[k] = s
            if kind == "g":
                s.get = f
            else:
                s.set = f
        elif kind == "f":
            f = method(info, env, target) if info is not None else None
            if static:
                static_init.append((k, f))
            else:
                fields.append((k, f))
        elif kind == "b":
            static_init.append((None, method(info, env, C)))
    if fields:
        C.fields = fields
    # fields of the parent class run in its own constructor; this class's after super()
    for k, f in static_init:
        if k is None:
            f.info.code(f, C)
        else:
            v = f.info.code(f, C) if f is not None else UNDEF
            rt.define_value(C, k, v)
    return C


def _default_base(F, this, *args):
    if rt.take_newtarget() is UNDEF:
        throw_type("Class constructor %s cannot be invoked without 'new'" % F.info.name)
    return UNDEF


def _default_derived(F, this, *args):
    nt = rt.take_newtarget()
    if nt is UNDEF:
        throw_type("Class constructor %s cannot be invoked without 'new'" % F.info.name)
    return rt.super_call(F, nt, list(args))


def tmpl_strings(k):
    """The strings array of a tagged template (made once per place in the code)."""
    if type(k) is tuple:
        return k[2] if len(k) > 2 else k[0]
    return k


# ---- generators ----

class GenState:
    __slots__ = ("gen", "started", "done", "running")

    def __init__(self, gen):
        self.gen = gen
        self.started = False
        self.done = False
        self.running = False


def make_generator(F, pygen):
    proto = F.get("prototype")
    if not isinstance(proto, JSObject):
        proto = GENERATOR_PROTO
    o = JSObject(proto, "Generator")
    o.x = GenState(pygen)
    return o


def gen_resume(o, mode, value):
    """next / throw / return on a generator: an iterator result."""
    st = o.x
    if not isinstance(st, GenState):
        throw_type("next method called on incompatible receiver")
    if st.running:
        throw_type("Generator is already running")
    if st.done:
        if mode == 1:
            raise JSThrow(value)
        return rt.iter_result(value if mode == 2 else UNDEF, True)
    g = st.gen
    if not st.started and mode != 0:
        st.done = True
        if mode == 1:
            raise JSThrow(value)
        return rt.iter_result(value, True)
    st.running = True
    try:
        if mode == 0:
            v = g.send(value if st.started else None)
        elif mode == 1:
            v = g.throw(JSThrow(value))
        else:
            v = g.throw(rt.GenReturn(value))
        st.started = True
        return rt.iter_result(v, False)
    except StopIteration as e:
        st.done = True
        v = e.value if e.args else UNDEF
        return rt.iter_result(UNDEF if v is None else v, True)
    except rt.GenReturn as e:
        st.done = True
        return rt.iter_result(e.value, True)
    except BaseException:
        st.done = True
        raise
    finally:
        st.running = False


def delegate(v):
    """yield* v: pass everything through to the inner iterator."""
    if isinstance(v, JSObject) and isinstance(v.x, GenState) and v.cls == "Generator" and \
            v.proto is not None and v.get("next") is GEN_NEXT[0]:
        st = v.x
        if not st.started and not st.done:
            st.started = True
            st.running = False
            r = yield from st.gen
            st.done = True
            return UNDEF if r is None else r
    it = rt.call(rt.get(v, rt.SYM_ITERATOR), v) if isinstance(v, JSObject) or type(v) is str else None
    if it is None:
        throw_type("yield* on a value that is not iterable")
    nxt = get(it, "next")
    sent = UNDEF
    while True:
        r = call(nxt, it, sent)
        if not isinstance(r, JSObject):
            throw_type("Iterator result is not an object")
        if truthy(r.get("done")):
            return r.get("value")
        try:
            sent = yield r.get("value")
        except JSThrow as e:
            th = get(it, "throw")
            if not isinstance(th, JSFunction):
                raise
            r = call(th, it, e.value)
            if truthy(r.get("done")):
                return r.get("value")
            sent = UNDEF
            continue
        except rt.GenReturn as e:
            ret = get(it, "return")
            if isinstance(ret, JSFunction):
                call(ret, it, e.value)
            raise
        if sent is None and False:
            sent = UNDEF


GEN_NEXT = [None]


# ---- promises and jobs ----

PENDING, FULFILLED, REJECTED = 0, 1, 2


class PromiseState:
    __slots__ = ("state", "value", "reactions", "handled")

    def __init__(self):
        self.state = PENDING
        self.value = UNDEF
        self.reactions = []
        self.handled = False


def new_promise(proto=None):
    p = JSObject(PROMISE_PROTO if proto is None else proto, "Promise")
    p.x = PromiseState()
    return p


def is_promise(v):
    return isinstance(v, JSObject) and type(v.x) is PromiseState


def enqueue(job):
    R.jobs.append(job)


def settle(p, state, value):
    st = p.x
    if st.state != PENDING:
        return
    st.state = state
    st.value = value
    rs = st.reactions
    st.reactions = None
    for r in rs:
        _schedule(r, state, value)


def _schedule(reaction, state, value):
    enqueue((reaction, state, value))


def resolve_promise(p, value):
    """Resolve p with value: following it when it is a thenable."""
    if p.x.state != PENDING:
        return
    if value is p:
        settle(p, REJECTED, rt.make_error("TypeError", "Chaining cycle detected for promise"))
        return
    if isinstance(value, JSObject):
        if type(value.x) is PromiseState and value.proto is PROMISE_PROTO and PROMISE_PROTO.p.get("then") is \
                PROMISE_THEN[0]:
            # a native promise: follow it directly (one job, like the spec's then)
            then_native(value, lambda v: resolve_promise(p, v), lambda e: settle(p, REJECTED, e))
            return
        try:
            then = value.get("then")
        except JSThrow as e:
            settle(p, REJECTED, e.value)
            return
        if isinstance(then, JSFunction):
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

            def job():
                try:
                    then.info.code(then, value, native_fn(res, "", 1), native_fn(rej, "", 1))
                except JSThrow as e:
                    if not done[0]:
                        done[0] = True
                        settle(p, REJECTED, e.value)
            enqueue((job, None, None))
            return
    settle(p, FULFILLED, value)


PROMISE_THEN = [None]


def then_native(p, on_ok, on_err):
    """Python callbacks for when p settles (as jobs)."""
    st = p.x
    st.handled = True
    reaction = ("py", on_ok, on_err)
    if st.state == PENDING:
        st.reactions.append(reaction)
    else:
        _schedule(reaction, st.state, st.value)


def run_reaction(reaction, state, value):
    if reaction[0] == "py":
        f = reaction[1] if state == FULFILLED else reaction[2]
        f(value)
        return
    # (target promise, on_fulfilled, on_rejected)
    target, ok, err = reaction
    handler = ok if state == FULFILLED else err
    if not isinstance(handler, JSFunction):
        if target is not None:
            if state == FULFILLED:
                resolve_promise(target, value)
            else:
                settle(target, REJECTED, value)
        return
    try:
        v = handler.info.code(handler, UNDEF, value)
    except JSThrow as e:
        if target is not None:
            settle(target, REJECTED, e.value)
        return
    if target is not None:
        resolve_promise(target, v)


def run_jobs(limit_ms=1000):
    """Run waiting promise jobs (and the jobs they make). Returns how many ran."""
    jobs = R.jobs
    n = 0
    while jobs:
        job = jobs.pop(0)
        n += 1
        if job[1] is None:
            try:
                job[0]()
            except JSThrow as e:
                report_unhandled(e)
        else:
            try:
                run_reaction(job[0], job[1], job[2])
            except JSThrow as e:
                report_unhandled(e)
        if n & 255 == 0:
            rt.check()
    return n


def report_unhandled(e):
    h = R.on_error
    if h is not None:
        h(e)


R.on_error = None


def promise_resolved(v):
    if is_promise(v) and v.proto is PROMISE_PROTO:
        return v
    p = new_promise()
    resolve_promise(p, v)
    return p


# ---- async functions: Python generators driven by promises ----

def run_async(pygen):
    p = new_promise()
    _async_step(pygen, p, 0, None)
    return p


def _async_step(g, p, mode, value):
    while True:
        try:
            if mode == 0:
                awaited = g.send(value)
            else:
                awaited = g.throw(JSThrow(value))
        except StopIteration as e:
            v = e.value if e.args else UNDEF
            resolve_promise(p, UNDEF if v is None else v)
            return
        except JSThrow as e:
            settle(p, REJECTED, e.value)
            return
        if is_promise(awaited) and awaited.proto is PROMISE_PROTO:
            src = awaited
        elif isinstance(awaited, JSObject) and isinstance(awaited.get("then"), JSFunction):
            src = promise_resolved(awaited)
        else:
            # not a promise: still one tick later, as await does
            src = new_promise()
            settle(src, FULFILLED, awaited)
        then_native(src, lambda v: _async_step(g, p, 0, v), lambda e: _async_step(g, p, 1, e))
        return


def await_sync(v):
    rt.throw("SyntaxError", "await is only valid in async functions and the top level bodies of modules")


def dynamic_import(spec):
    p = new_promise()
    settle(p, REJECTED, rt.make_error("TypeError", "import() is not supported: %s" % rt.to_str(spec)))
    return p


# ---- async generators ----

class AsyncGenState:
    __slots__ = ("gen", "queue", "running", "done", "started")

    def __init__(self, gen):
        self.gen = gen
        self.queue = []
        self.running = False
        self.done = False
        self.started = False


def make_async_generator(F, pygen):
    proto = F.get("prototype")
    if not isinstance(proto, JSObject):
        proto = ASYNC_GENERATOR_PROTO
    o = JSObject(proto, "AsyncGenerator")
    o.x = AsyncGenState(pygen)
    return o


def async_gen_request(o, mode, value):
    st = o.x
    p = new_promise()
    if not isinstance(st, AsyncGenState):
        settle(p, REJECTED, rt.make_error("TypeError", "not an async generator"))
        return p
    st.queue.append((mode, value, p))
    if not st.running:
        _agen_next(o)
    return p


def _agen_next(o):
    st = o.x
    if not st.queue:
        return
    mode, value, p = st.queue[0]
    if st.done:
        st.queue.pop(0)
        if mode == 1:
            settle(p, REJECTED, value)
        else:
            settle(p, FULFILLED, rt.iter_result(value if mode == 2 else UNDEF, True))
        _agen_next(o)
        return
    if not st.started and mode != 0:
        st.done = True
        _agen_next(o)
        return
    st.running = True
    _agen_step(o, mode, value)


def _agen_step(o, mode, value):
    st = o.x
    g = st.gen
    while True:
        try:
            if mode == 0:
                out = g.send(value if st.started else None)
            elif mode == 1:
                out = g.throw(JSThrow(value))
            else:
                out = g.throw(rt.GenReturn(value))
            st.started = True
        except StopIteration as e:
            v = e.value if e.args else UNDEF
            _agen_finish(o, FULFILLED, rt.iter_result(UNDEF if v is None else v, True), True)
            return
        except rt.GenReturn as e:
            _agen_finish(o, FULFILLED, rt.iter_result(e.value, True), True)
            return
        except JSThrow as e:
            _agen_finish(o, REJECTED, e.value, True)
            return
        kind, v = out
        if kind == 0:                                   # await
            src = promise_resolved(v)
            then_native(src, lambda r: _agen_step(o, 0, r), lambda e: _agen_step(o, 1, e))
            return
        # yield: the value is awaited, then given out
        src = promise_resolved(v)
        then_native(src, lambda r: _agen_finish(o, FULFILLED, rt.iter_result(r, False), False),
                    lambda e: _agen_step(o, 1, e))
        return


def _agen_finish(o, state, value, done):
    st = o.x
    if done:
        st.done = True
    mode, _, p = st.queue.pop(0)
    settle(p, state, value)
    st.running = False
    _agen_next(o)


def async_delegate(v):
    """yield* in an async generator: over an async (or sync) iterator."""
    f = rt.get(v, rt.SYM_ASYNC_ITERATOR)
    is_async = isinstance(f, JSFunction)
    if not is_async:
        f = rt.get(v, rt.SYM_ITERATOR)
    it = rt.call(f, v)
    nxt = get(it, "next")
    sent = UNDEF
    while True:
        r = call(nxt, it, sent)
        if is_async:
            r = yield (0, r)
        if truthy(get(r, "done")):
            return get(r, "value")
        sent = yield (1, get(r, "value"))


def iterate_await(v):
    rt.throw("SyntaxError", "for await is only valid in async functions")


# ---- natives ----

def native_fn(code, name, nparams=0, ctor=False, proto=None):
    info = FuncInfo(code, name, nparams, "native", ctor)
    return JSFunction(info, None, None, proto)
