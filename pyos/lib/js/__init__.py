# JavaScript for SnakeyOS, all in Python: the same interface the browser used
# with the QuickJS engine it replaces (the old _js module).
#
#   ctx = js.Context(callback)        callback(name, json_text) -> json_text: what JS's __py() calls
#   ctx.eval(code, name="<script>", timeout_ms=3000, mem_extra=0) -> the result (None, bool, int, float,
#                                     str; objects come back as JSON text)
#   ctx.run_jobs(timeout_ms=1000)     waiting promise reactions; how many ran
#   ctx.memory(), ctx.gc(), ctx.close()
#   js.set_clock(epoch_ms, tz_minutes, tsc_per_ms)
#
# A script that throws raises js.Error with JavaScript's message and stack.
# A script that runs past its time is stopped ("script stopped: it ran too long").
import time
from js import rt, interp, compiler
from js.rt import UNDEF, JSObject, JSFunction, R
from js.lexer import JSSyntaxError


try:
    RecursionError
except NameError:                   # MicroPython
    RecursionError = RuntimeError

class JSError(Exception):
    pass


Error = JSError


_built = [False]
_snapshot = {}
_last_stop = [""]


def _ticks():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)


def _setup():
    if _built[0]:
        return
    from js import builtins, builtins2
    builtins.install_globals(_global_eval)
    g = R.glob
    _snapshot["p"] = dict(g.p)
    _snapshot["ks"] = list(g.ks)
    ns = _NS
    for mod in (rt, interp):
        for name in dir(mod):
            if not name.startswith("__"):
                ns[name] = getattr(mod, name)
    ns["regex"] = builtins2.regex
    ns["direct_eval"] = _direct_eval
    ns["LEX"] = R.lex
    ns["tmpl_strings"] = _tmpl_strings
    ns["iterate_await"] = _iterate_await
    _built[0] = True


_NS = {}
_SCRIPTS = {}            # big scripts (dom.js, libraries), compiled once
_TMPL = {}


def _tmpl_strings(k):
    a = _TMPL.get(id(k))
    if a is None:
        cooked, raws = k
        a = rt.JSArray([UNDEF if c is None else c for c in cooked])
        raw = rt.JSArray(list(raws))
        a.p["raw"] = rt.Slot(raw, e=False, w=False, c=False)
        a.ks.append("raw")
        a.ext = False
        _TMPL[id(k)] = a
    return a


def _iterate_await(v):
    rt.throw("SyntaxError", "for await is not supported here")


def run_script(src, name="<script>", want_value=False):
    """Compile and run a script at the top level; with want_value, the value of its last expression."""
    _setup()
    key = (src, want_value) if len(src) > 4096 else None
    code = _SCRIPTS.get(key) if key is not None else None
    if code is not None:
        return code(None, R.glob)
    try:
        code = compiler.compile_script(src, name, _NS, want_value)
        if key is not None:
            if len(_SCRIPTS) > 8:
                _SCRIPTS.clear()
            _SCRIPTS[key] = code
    except JSSyntaxError as e:
        raise rt.JSThrow(rt.make_error("SyntaxError", "%s (%s %s)" % (e.msg, name, e.where())))
    return code(None, R.glob)


def _global_eval(src, name):
    """eval and new Function: the value of the code."""
    return run_script(src, name, True)


def _direct_eval(code=UNDEF, *_):
    if type(code) is not str:
        return code
    return _global_eval(code, "eval")


def _to_python(v):
    if v is UNDEF or v is None:
        return None
    t = type(v)
    if t is bool or t is str:
        return v
    if t is int:
        return v
    if t is float:
        if v == v and v == int(v) and -9e15 < v < 9e15:
            return int(v)
        return v
    if isinstance(v, JSObject):
        from js import builtins
        try:
            s = builtins.json_stringify(None, None, v)
        except rt.JSThrow:
            return None
        return None if s is UNDEF else s
    return rt.to_str(v) if t is not rt.Symbol else str(v)


def _error_text(e):
    v = e.value
    if isinstance(v, JSObject):
        try:
            name = rt.to_str(v.get("name"))
            msg = rt.to_str(v.get("message"))
            st = v.get("stack")
            text = "%s: %s" % (name, msg)
            if type(st) is str and st:
                text += "\n" + st
            return text
        except Exception:
            return "Error"
    try:
        return "Uncaught " + rt.to_str(v)
    except Exception:
        return "Uncaught exception"


def set_clock(epoch_ms, tz_minutes=0, tsc_per_ms=0):
    from js import builtins2
    base = float(epoch_ms)
    t0 = _ticks()
    builtins2.CLOCK["tz"] = int(tz_minutes)
    builtins2.CLOCK["now"] = lambda: int(base + (_ticks() - t0))


def last_stop():
    return _last_stop[0]


class Context:
    def __init__(self, callback=None):
        _setup()
        g = R.glob
        # a fresh global object: what earlier pages added is gone
        g.p = dict(_snapshot["p"])
        g.ks = list(_snapshot["ks"])
        R.lex.clear()
        R.jobs[:] = []
        self.callback = callback
        self.closed = False
        from js.interp import native_fn

        def py(F, this, name=UNDEF, arg=UNDEF, *_):
            cb = self.callback
            if cb is None:
                return None
            r = cb(rt.to_str(name), None if arg is None or arg is UNDEF else rt.to_str(arg))
            return None if r is None else r
        g.define("__py", native_fn(py, "__py", 2))
        R.ticks_ms = _ticks

    def _check_open(self):
        if self.closed:
            raise ValueError("JavaScript context is closed")

    def _run(self, f, timeout):
        R.deadline = (_ticks() + int(timeout)) if timeout and timeout > 0 else 0
        try:
            return f()
        except rt.Interrupted as e:
            _last_stop[0] = "time"
            raise Error("script stopped: it ran too long\n" + str(e.why))
        except rt.JSThrow as e:
            raise Error(_error_text(e))
        except RecursionError:
            raise Error("RangeError: Maximum call stack size exceeded")
        except (rt.BreakTo, rt.ContinueTo, rt.GenReturn):
            raise Error("SyntaxError: illegal break or continue")
        finally:
            R.deadline = 0

    def eval(self, code, name="<script>", timeout_ms=3000, mem_extra=0):
        self._check_open()

        def go():
            return _to_python(_global_eval(code, name))
        return self._run(go, timeout_ms)

    def run(self, code, name="<script>", timeout_ms=3000, mem_extra=0):
        """Run a script (no value)."""
        self._check_open()
        return self._run(lambda: (run_script(code, name), None)[1], timeout_ms)

    def run_jobs(self, timeout_ms=1000, mem_extra=0):
        self._check_open()
        R.deadline = _ticks() + int(timeout_ms)
        try:
            return interp.run_jobs()
        except rt.Interrupted:
            return 0
        finally:
            R.deadline = 0

    def memory(self):
        try:
            import gc
            return gc.mem_alloc()
        except (ImportError, AttributeError):
            return 0

    def gc(self):
        try:
            import gc
            gc.collect()
        except ImportError:
            pass

    def close(self):
        self.closed = True
        self.callback = None
        R.jobs[:] = []
