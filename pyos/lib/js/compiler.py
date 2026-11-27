# JavaScript -> Python. Each JavaScript function becomes a Python function,
# made the first time it runs (most of a big page's code never does).
#
# Variables a nested function uses ("captured") live in frames: lists
# [parent_frame, slot1, slot2...]; the others are plain Python locals. The
# top of a script is global: var and function there are properties of the
# global object, let/const/class are in the global lexical table (R.lex).
from js.parser import Node, parse, ascii_source
from js import rt

_ids = [0]


def _next_id():
    _ids[0] += 1
    return _ids[0]


# ---- scopes ----

class Binding:
    __slots__ = ("name", "kind", "scope", "captured", "slot", "py", "glob")

    def __init__(self, name, kind, scope):
        self.name = name
        self.kind = kind            # var, let, const, class, function, param, catch, arguments, fname
        self.scope = scope
        self.captured = False
        self.slot = -1
        self.py = None
        self.glob = False           # declared at the top of a script


class Scope:
    __slots__ = ("kind", "parent", "fn", "names", "id", "frame", "nslots", "funcs", "pyframe")

    def __init__(self, kind, parent, fn):
        self.kind = kind            # fn, block, script, catch, for, class
        self.parent = parent
        self.fn = fn
        self.names = {}
        self.id = _next_id()
        self.frame = False
        self.nslots = 0
        self.funcs = []             # function declarations to make at the scope's start
        self.pyframe = None


class Fn:
    """One function (or the script) as the analysis sees it."""

    def __init__(self, node, parent, scope_parent):
        self.node = node
        self.parent = parent
        self.arrow = node is not None and node.t == "Function" and node.is_arrow
        self.scope = None
        self.scope_parent = scope_parent      # the scope the function is defined in
        self.args = None                      # the `arguments` binding, when used
        self.uses_this = False
        self.uses_nt = False
        self.names = 0
        self.strict = False
        self.fname = None                     # a named function expression's own name
        self.info = None
        self.scopes = []


def _sanitize(name):
    out = []
    for c in name:
        if "a" <= c <= "z" or "A" <= c <= "Z" or "0" <= c <= "9" or c == "_":
            out.append(c)
        else:
            out.append("_%x" % ord(c))
    return "".join(out)


class Analyzer:
    def __init__(self, strict):
        self.fn = None
        self.scope = None
        self.strict = strict
        self.fns = []

    # declarations
    def declare(self, scope, name, kind):
        b = scope.names.get(name)
        if b is not None:
            if kind in ("let", "const", "class") and b.kind in ("let", "const", "class") and scope.kind != "script":
                pass                                    # a redeclaration: keep the first
            if kind == "function" and b.kind in ("var", "param", "function"):
                b.kind = "function" if b.kind != "param" else b.kind
            return b
        b = Binding(name, kind, scope)
        if scope.kind == "script":
            b.glob = True
        scope.names[name] = b
        return b

    def var_scope(self):
        s = self.scope
        while s.kind not in ("fn", "script"):
            s = s.parent
        return s

    def pattern_names(self, p, out):
        if p is None:
            return out
        t = p.t
        if t == "Ident":
            out.append(p.name)
        elif t == "ArrayPattern":
            for e in p.elems:
                self.pattern_names(e, out)
        elif t == "ObjectPattern":
            for item in p.props:
                if isinstance(item, Node):
                    self.pattern_names(item, out)
                else:
                    self.pattern_names(item[2], out)
        elif t == "AssignPattern":
            self.pattern_names(p.target, out)
        elif t == "Rest":
            self.pattern_names(p.arg, out)
        return out

    def hoist_vars(self, body, scope):
        """var declarations (and, in sloppy code, functions in blocks) of a function body."""
        stack = list(reversed(body))
        while stack:
            s = stack.pop()
            if s is None:
                continue
            t = s.t
            if t == "Var":
                if s.kind == "var":
                    for target, _ in s.decls:
                        for n in self.pattern_names(target, []):
                            self.declare(scope, n, "var")
            elif t == "Block":
                for x in s.body:
                    if x.t == "Function" and x.is_decl and not self.fn.strict:
                        self.declare(scope, x.name, "var")
                stack.extend(reversed(s.body))
            elif t == "If":
                stack.append(s.alt)
                stack.append(s.cons)
            elif t in ("For",):
                stack.append(s.body)
                if s.init is not None and s.init.t == "Var":
                    stack.append(s.init)
            elif t == "ForIn":
                stack.append(s.body)
                if s.left.t == "Var":
                    stack.append(s.left)
            elif t in ("While", "DoWhile"):
                stack.append(s.body)
            elif t == "Labeled" or t == "With":
                stack.append(s.body)
            elif t == "Try":
                stack.append(s.final)
                stack.append(s.handler)
                stack.append(s.block)
            elif t == "Switch":
                for _, cb in s.cases:
                    for x in cb:
                        if x.t == "Function" and x.is_decl and not self.fn.strict:
                            self.declare(scope, x.name, "var")
                    stack.extend(reversed(cb))

    def lexical(self, body, scope, top=False):
        """let/const/class/function declarations directly in a block."""
        for s in body:
            t = s.t
            if t == "Var" and s.kind != "var":
                for target, _ in s.decls:
                    for n in self.pattern_names(target, []):
                        self.declare(scope, n, s.kind)
            elif t == "Class" and s.is_decl:
                self.declare(scope, s.name, "class")
            elif t == "Function" and s.is_decl:
                if top or self.fn.strict:
                    self.declare(scope, s.name, "function")
                scope.funcs.append(s)
            elif t == "Labeled":
                inner = s.body
                while inner.t == "Labeled":
                    inner = inner.body
                if inner.t == "Function" and inner.is_decl:
                    if top or self.fn.strict:
                        self.declare(scope, inner.name, "function")
                    scope.funcs.append(inner)

    # references
    def resolve(self, name):
        s = self.scope
        fn = self.fn
        self.withs = None
        while s is not None:
            b = s.names.get(name)
            if b is not None:
                if b.scope.fn is not fn and not b.glob:
                    b.captured = True
                return b
            if s.kind == "with":
                w = s.names["%with"]
                if w.scope.fn is not fn:
                    w.captured = True
                if self.withs is None:
                    self.withs = []
                self.withs.append(w)
            s = s.parent
        return None

    def push(self, kind, node=None):
        s = Scope(kind, self.scope, self.fn)
        self.fn.scopes.append(s)
        self.scope = s
        if node is not None:
            node.scope = s
        return s

    def pop(self):
        self.scope = self.scope.parent

    # ---- the walk ----
    def program(self, prog):
        fn = Fn(None, None, None)
        fn.strict = prog.strict
        self.fn = fn
        self.fns.append(fn)
        s = self.push("script", prog)
        fn.scope = s
        self.hoist_vars(prog.body, s)
        self.lexical(prog.body, s, True)
        for st in prog.body:
            self.stmt(st)
        self.pop()
        return fn

    def function(self, node):
        fn = Fn(node, self.fn, self.scope)
        fn.strict = node.strict or self.fn.strict
        node.fn = fn
        saved = (self.fn, self.scope)
        self.fn = fn
        self.fns.append(fn)
        s = self.push("fn")
        fn.scope = s
        node.scope = s
        for p in node.params:
            for n in self.pattern_names(p, []):
                self.declare(s, n, "param")
        if node.name and not node.is_decl and node.kind not in ("method", "ctor") and not node.is_arrow:
            if node.name not in s.names:
                fn.fname = self.declare(s, node.name, "fname")
        self.hoist_vars(node.body, s)
        self.lexical(node.body, s, True)
        # defaults may refer to the parameters
        for p in node.params:
            self.pattern(p, False)
        for st in node.body:
            self.stmt(st)
        self.fn, self.scope = saved

    def block_body(self, body, node, kind="block"):
        s = self.push(kind, node)
        self.lexical(body, s)
        for st in body:
            self.stmt(st)
        self.pop()
        return s

    def stmt(self, s):
        if s is None:
            return
        t = s.t
        if t == "Expr":
            self.expr(s.e)
        elif t == "Var":
            for target, init in s.decls:
                self.pattern(target, False)
                if init is not None:
                    self.expr(init)
        elif t == "Function":
            self.function(s)
        elif t == "Class":
            self.class_(s)
        elif t == "Return" or t == "Throw":
            if s.arg is not None:
                self.expr(s.arg)
        elif t == "If":
            self.expr(s.test)
            self.sub(s.cons)
            self.sub(s.alt)
        elif t == "Block":
            self.block_body(s.body, s)
        elif t == "For":
            sc = self.push("for", s)
            if s.init is not None:
                if s.init.t == "Var" and s.init.kind != "var":
                    for target, _ in s.init.decls:
                        for n in self.pattern_names(target, []):
                            self.declare(sc, n, s.init.kind)
                self.stmt(s.init)
            if s.test is not None:
                self.expr(s.test)
            if s.update is not None:
                self.expr(s.update)
            self.sub(s.body)
            self.pop()
        elif t == "ForIn":
            self.expr(s.right)
            sc = self.push("for", s)
            if s.left.t == "Var":
                if s.left.kind != "var":
                    for target, _ in s.left.decls:
                        for n in self.pattern_names(target, []):
                            self.declare(sc, n, s.left.kind)
                self.stmt(s.left)
            else:
                self.pattern(s.left, False)
            self.sub(s.body)
            self.pop()
        elif t == "While" or t == "DoWhile":
            self.expr(s.test)
            self.sub(s.body)
        elif t == "Labeled":
            self.stmt(s.body)
        elif t == "With":
            self.expr(s.obj)
            sc = self.push("with", s)
            self.declare(sc, "%with", "let")
            self.sub(s.body)
            self.pop()
        elif t == "Try":
            self.block_body(s.block.body, s.block)
            if s.handler is not None:
                sc = self.push("catch", s)
                if s.param is not None:
                    for n in self.pattern_names(s.param, []):
                        self.declare(sc, n, "catch")
                    self.pattern(s.param, False)
                self.block_body(s.handler.body, s.handler)
                self.pop()
            if s.final is not None:
                self.block_body(s.final.body, s.final)
        elif t == "Switch":
            self.expr(s.disc)
            sc = self.push("block", s)
            allb = []
            for test, body in s.cases:
                allb.extend(body)
            self.lexical(allb, sc)
            for test, body in s.cases:
                if test is not None:
                    self.expr(test)
                for st in body:
                    self.stmt(st)
            self.pop()

    def sub(self, s):
        """A statement in a statement's place (if/loop body): a block of its own when it is one."""
        if s is None:
            return
        if s.t == "Block":
            self.block_body(s.body, s)
        else:
            if s.t in ("Function", "Class", "Var") and (s.t != "Var" or s.kind != "var"):
                self.block_body([s], s, "block")
                s.wrapped = True
            else:
                self.stmt(s)

    def class_(self, node):
        if node.sup is not None:
            self.expr(node.sup)
        s = self.push("class", node)
        if node.name:
            node.inner = self.declare(s, node.name, "const")
        for m in node.members:
            if m.computed:
                self.expr(m.key)
            if m.value is not None:
                self.function(m.value)
        self.pop()
        if node.is_decl:
            node.outer = self.resolve(node.name)

    def pattern(self, p, assign):
        if p is None:
            return
        t = p.t
        if t == "Ident":
            self.expr(p)
        elif t == "ArrayPattern":
            for e in p.elems:
                self.pattern(e, assign)
        elif t == "ObjectPattern":
            for item in p.props:
                if isinstance(item, Node):
                    self.pattern(item, assign)
                else:
                    if item[1]:
                        self.expr(item[0])
                    self.pattern(item[2], assign)
        elif t == "AssignPattern":
            self.pattern(p.target, assign)
            self.expr(p.default)
        elif t == "Rest":
            self.pattern(p.arg, assign)
        else:
            self.expr(p)

    def this_fn(self):
        """The function whose `this` is meant here (arrows see through)."""
        fn = self.fn
        while fn.arrow:
            fn = fn.parent
        return fn

    def expr(self, e):
        if e is None:
            return
        t = e.t
        if t == "Ident":
            name = e.name
            b = self.resolve(name)
            if b is None and name == "arguments":
                f = self.this_fn()
                if f.node is not None:
                    if f.args is None:
                        f.args = Binding("arguments", "arguments", f.scope)
                        f.scope.names["arguments"] = f.args
                    b = self.resolve(name)
            e.b = b
            if self.withs:
                e.withs = self.withs
        elif t in ("Num", "Str", "Regex", "Null", "Bool", "Super"):
            if t == "Super":
                self.this_fn().uses_this = True
        elif t == "This":
            self.this_fn().uses_this = True
        elif t == "NewTarget":
            self.this_fn().uses_nt = True
        elif t == "Tmpl":
            for x in e.exprs:
                self.expr(x)
        elif t == "TaggedTmpl":
            self.expr(e.tag)
            for x in e.quasi.exprs:
                self.expr(x)
        elif t == "Array":
            for x in e.elems:
                self.expr(x)
        elif t == "Object":
            for p in e.props:
                if p.computed:
                    self.expr(p.key)
                if p.value is not None:
                    if p.value.t == "Function":
                        self.function(p.value)
                    else:
                        self.expr(p.value)
        elif t == "Function":
            self.function(e)
        elif t == "Class":
            self.class_(e)
        elif t in ("Unary", "Update", "Spread", "Await", "Yield", "Import"):
            self.expr(e.arg)
        elif t in ("Binary", "Logical"):
            self.expr(e.l)
            self.expr(e.r)
        elif t == "Assign":
            if e.target.t in ("ArrayPattern", "ObjectPattern"):
                self.pattern(e.target, True)
            else:
                self.expr(e.target)
            self.expr(e.value)
        elif t == "Cond":
            self.expr(e.test)
            self.expr(e.cons)
            self.expr(e.alt)
        elif t == "Call":
            self.expr(e.callee)
            for a in e.args:
                self.expr(a)
            if e.callee.t == "Super":
                self.this_fn().uses_nt = True
        elif t == "New":
            self.expr(e.callee)
            for a in e.args:
                self.expr(a)
        elif t == "Member":
            self.expr(e.obj)
            if e.computed:
                self.expr(e.prop)
        elif t == "Seq":
            for x in e.exprs:
                self.expr(x)
        elif t == "Chain":
            self.expr(e.e)
        elif t in ("ArrayPattern", "ObjectPattern", "AssignPattern", "Rest"):
            self.pattern(e, True)
        elif t == "ShorthandInit":
            self.expr(e.target)
            self.expr(e.default)
        elif t == "ArrowParams":
            pass


def layout(fns):
    """Slots for captured names, Python names for the others."""
    for fn in fns:
        for sc in fn.scopes:
            for name in sc.names:
                b = sc.names[name]
                if b.glob:
                    continue
                if b.captured:
                    sc.nslots += 1
                    b.slot = sc.nslots
                    sc.frame = True
                else:
                    fn.names += 1
                    b.py = "v%s_%d" % (_sanitize(name), fn.names)
            if sc.frame:
                sc.pyframe = "E%d" % sc.id


# ---- the code ----

class Unit:
    """One script: its tree, and the namespace its Python code runs in."""

    def __init__(self, src, name, ns):
        self.src = src
        self.name = name
        self.ns = ns


class FnGen:
    """Python source for one function (or the top of a script)."""

    def __init__(self, fn, unit):
        self.fn = fn
        self.unit = unit
        self.lines = []
        self.ind = 1
        self.tmp = 0
        self.pre = []
        self.ctx = []               # breakable statements: [kind, labels, id, pyloop, need_break, need_cont]
        self.scope = fn.scope
        self.outer_frames = []      # frame scopes outside this function, nearest first
        s = fn.scope_parent
        while s is not None:
            if s.frame:
                self.outer_frames.append(s)
            s = s.parent
        self.uses_P = False
        self.consts = []
        self.is_gen = fn.node is not None and (fn.node.is_gen or fn.node.is_async)
        self.has_yield = False
        self.loopc = False

    # ---- output ----
    def emit(self, text):
        if self.pre:
            for p in self.pre:
                for line in p:
                    self.lines.append((self.ind + line[0], line[1]))
            self.pre = []
        self.lines.append((self.ind, text))

    def t(self):
        self.tmp += 1
        return "_t%d" % self.tmp

    def const(self, value):
        """A constant made once (a regex, a template's strings)."""
        name = "K%d" % _next_id()
        self.unit.ns[name] = value
        return name

    # ---- names ----
    def frame_of(self, scope):
        if scope.fn is self.fn:
            return scope.pyframe
        self.uses_P = True
        hops = self.outer_frames.index(scope)
        return "P" + "[0]" * hops

    def cur_frame(self):
        s = self.scope
        while s is not None and s.fn is self.fn:
            if s.frame:
                return s.pyframe
            s = s.parent
        if self.outer_frames:
            self.uses_P = True
            return "P"
        return "None"

    def read(self, b, name):
        if b is None:
            if name == "undefined":
                return "UNDEF"
            if name == "NaN":
                return "NAN"
            if name == "Infinity":
                return "INF"
            return "gget(%r)" % name
        if b.glob:
            return "gget(%r)" % name
        if b.slot >= 0:
            return "%s[%d]" % (self.frame_of(b.scope), b.slot)
        return b.py

    def write_stmt(self, b, name, value):
        if b is None or b.glob:
            self.emit("gset(%r, %s)" % (name, value))
        elif b.slot >= 0:
            self.emit("%s[%d] = %s" % (self.frame_of(b.scope), b.slot, value))
        else:
            self.emit("%s = %s" % (b.py, value))

    def write_expr(self, b, name, value):
        if b is None or b.glob:
            return "gset(%r, %s)" % (name, value)
        if b.slot >= 0:
            return "sset(%s, %d, %s)" % (self.frame_of(b.scope), b.slot, value)
        return "(%s := %s)" % (b.py, value)

    def decl_stmt(self, b, name, value, kind):
        """A declaration's first value."""
        if b is not None and b.glob:
            if kind in ("let", "const", "class"):
                self.emit("LEX[%r] = %s" % (name, value))
            else:
                self.emit("gset(%r, %s)" % (name, value))
            return
        self.write_stmt(b, name, value)

    # ---- the function ----
    def gen(self, pyname):
        fn = self.fn
        node = fn.node
        body_start = len(self.lines)
        if node is None:
            self.prologue_script()
            body = self.unit.tree.body
            for k in range(len(body)):
                st = body[k]
                if k == len(body) - 1 and self.unit.want_value and st.t == "Expr":
                    self.emit("return %s" % self.expr(st.e))
                    break
                self.stmt(st)
            self.emit("return UNDEF")
            head = "def %s(F, this):" % pyname
        else:
            head = self.prologue(pyname)
            for st in node.body:
                self.stmt(st)
            if node.kind == "ctor" and getattr(node, "derived", False):
                self.emit("return this")
            else:
                self.emit("return UNDEF")
            if self.is_gen and not self.has_yield:
                self.emit("yield")
        out = [head]
        pro = []
        if self.uses_P:
            pro.append("    P = F.env")
        if self.loopc:
            pro.append("    _c = 0")
        lines = self.lines
        for k in range(len(lines)):
            if k == body_start and pro:
                out.extend(pro)
                pro = None
            ind, text = lines[k]
            out.append("    " * ind + text)
        if pro:
            out.extend(pro)
        return "\n".join(out) + "\n"

    def prologue_script(self):
        sc = self.fn.scope
        for name in sc.names:
            b = sc.names[name]
            if b.kind in ("let", "const", "class"):
                self.emit("LEX.setdefault(%r, UNDEF)" % name)
            elif b.kind == "var":
                self.emit("gvar(%r)" % name)
        for f in sc.funcs:
            self.emit("gset(%r, %s)" % (f.name, self.func_value(f)))

    def prologue(self, pyname):
        fn = self.fn
        node = fn.node
        sc = fn.scope
        params = node.params
        simple = all(p.t == "Ident" for p in params)
        use_star = fn.args is not None or not simple
        lines_head = []
        sig = ["F", "this"]
        if use_star:
            sig.append("*A")
        else:
            for p in params:
                b = sc.names[p.name]
                pn = b.py if b.slot < 0 else "_p_" + _sanitize(p.name)
                sig.append("%s=UNDEF" % pn)
            sig.append("*_x")
        head = "def %s(%s):" % (pyname, ", ".join(sig))
        del lines_head
        is_ctor = node.kind == "ctor"
        if fn.uses_nt or is_ctor:
            self.emit("NT = take_newtarget()")
            if is_ctor:
                self.emit("if NT is UNDEF: throw_type(%r)" % ("Class constructor %s cannot be invoked without 'new'"
                                                              % (node.name or "")))
        if fn.uses_this and not fn.strict and not node.is_arrow and node.kind != "ctor":
            self.emit("if this is UNDEF or this is None: this = R.glob")
        # locals: everything starts undefined
        names = []
        for sc2 in fn.scopes:
            for name in sc2.names:
                b = sc2.names[name]
                if b.py is not None and not (b.kind == "param" and not use_star and b.scope is sc):
                    names.append(b.py)
        for i in range(0, len(names), 20):
            self.emit(" = ".join(names[i:i + 20]) + " = UNDEF")
        if sc.frame:
            slots = ["UNDEF"] * sc.nslots
            self.emit("%s = [%s, %s]" % (sc.pyframe, self.parent_frame_expr(), ", ".join(slots)))
        if fn.fname is not None:
            self.write_stmt(fn.fname, node.name, "F")
        if fn.args is not None:
            self.write_stmt(fn.args, "arguments", "mkargs(A)")
        # the parameters
        if use_star:
            for i in range(len(params)):
                p = params[i]
                if p.t == "Rest":
                    self.assign_pattern(p.arg, "arr(list(A[%d:]))" % i, "let")
                    break
                v = "(A[%d] if len(A) > %d else UNDEF)" % (i, i)
                self.assign_pattern(p, v, "let")
        else:
            for p in params:
                b = sc.names[p.name]
                if b.slot >= 0:
                    self.emit("%s[%d] = _p_%s" % (sc.pyframe, b.slot, _sanitize(p.name)))
        for f in sc.funcs:
            b = sc.names.get(f.name)
            self.write_stmt(b, f.name, self.func_value(f))
        return head

    def parent_frame_expr(self):
        if self.outer_frames:
            self.uses_P = True
            return "P"
        return "None"

    # ---- blocks ----
    def enter_scope(self, scope):
        """At a block's start: its frame, its functions."""
        saved = self.scope
        if scope is None:
            return saved
        parent = self.cur_frame()
        self.scope = scope
        if scope.frame:
            self.emit("%s = [%s%s]" % (scope.pyframe, parent, ", UNDEF" * scope.nslots))
        for f in scope.funcs:
            b = scope.names.get(f.name)
            if b is None:
                b = self.lookup(f.name)
            self.write_stmt(b, f.name, self.func_value(f))
        return saved

    def lookup(self, name):
        s = self.scope
        while s is not None:
            b = s.names.get(name)
            if b is not None:
                return b
            s = s.parent
        return None

    def block(self, body, scope):
        saved = self.enter_scope(scope)
        n = len(self.lines)
        for st in body:
            self.stmt(st)
        if len(self.lines) == n:
            self.emit("pass")
        self.scope = saved

    def sub(self, s):
        """A statement as a body (indented by the caller)."""
        if s.t == "Block":
            self.block(s.body, s.scope)
        elif getattr(s, "wrapped", False):
            self.block([s], s.scope)
        else:
            n = len(self.lines)
            self.stmt(s)
            if len(self.lines) == n:
                self.emit("pass")

    # ---- statements ----
    def stmt(self, s):
        t = s.t
        m = getattr(self, "s_" + t)
        m(s)

    def s_Empty(self, s):
        pass

    def s_Expr(self, s):
        e = s.e
        t = e.t
        if t == "Assign":
            self.assign_stmt(e)
            return
        if t == "Update":
            self.update_stmt(e)
            return
        if t == "Seq":
            for x in e.exprs:
                self.s_Expr(Node("Expr", x.pos, e=x))
            return
        if t == "Call" and e.callee.t == "Super":
            self.emit("this = %s" % self.expr(e))
            return
        code = self.expr(e)
        self.emit(code)

    def s_Var(self, s):
        for target, init in s.decls:
            if init is None:
                if s.kind == "var":
                    continue
                if target.t == "Ident":
                    b = self.lookup(target.name)
                    self.decl_stmt(b, target.name, "UNDEF", s.kind)
                continue
            if target.t == "Ident":
                b = self.lookup(target.name)
                v = self.expr(init, target.name)
                self.decl_stmt(b, target.name, v, s.kind)
            else:
                self.assign_pattern(target, self.expr(init), s.kind)

    def s_Function(self, s):
        pass                                    # made at the start of its scope

    def s_Class(self, s):
        v = self.class_value(s)
        b = getattr(s, "outer", None)
        self.decl_stmt(b, s.name, v, "class")

    def s_Return(self, s):
        fn = self.fn
        if s.arg is None:
            v = "UNDEF"
        else:
            v = self.expr(s.arg)
        if fn.node is not None and fn.node.kind == "ctor" and getattr(fn.node, "derived", False):
            self.emit("return ctor_result(%s, this)" % v)
        else:
            self.emit("return %s" % v)

    def s_Throw(self, s):
        self.emit("raise JSThrow(%s)" % self.expr(s.arg))

    def s_If(self, s):
        self.emit("if %s:" % self.cond(s.test))
        self.ind += 1
        self.sub(s.cons)
        self.ind -= 1
        if s.alt is not None:
            if s.alt.t == "If" and not getattr(s.alt, "wrapped", False):
                # elif chains stay flat
                n = len(self.lines)
                self.emit("else:")
                self.ind += 1
                self.s_If(s.alt)
                self.ind -= 1
                del n
            else:
                self.emit("else:")
                self.ind += 1
                self.sub(s.alt)
                self.ind -= 1

    def s_Block(self, s):
        self.block(s.body, s.scope)

    # loops: labels and how break/continue reach them
    def push_ctx(self, kind, labels, pyloop):
        c = [kind, labels, _next_id(), pyloop, False, False]
        self.ctx.append(c)
        return c

    def take_labels(self, s):
        labels = getattr(s, "labels", None) or []
        return labels

    def s_Labeled(self, s):
        labels = [s.label]
        body = s.body
        while body.t == "Labeled":
            labels.append(body.label)
            body = body.body
        if body.t in ("For", "ForIn", "While", "DoWhile", "Switch"):
            body.labels = labels
            self.stmt(body)
            return
        # a labeled block: break label leaves it
        c = self.push_ctx("block", labels, False)
        start = len(self.lines)
        self.ind += 1
        self.sub(body)
        self.ind -= 1
        self.ctx.pop()
        if c[4]:
            self.wrap(start, "try:", ["except BreakTo as _b:", "    if _b.label != %d: raise" % c[2]])
        else:
            self.unindent(start)

    def unindent(self, start):
        lines = self.lines
        for k in range(start, len(lines)):
            ind, text = lines[k]
            lines[k] = (ind - 1, text)

    def wrap(self, start, head, tail):
        """Put lines[start:] (already indented one more) under head, then tail."""
        self.lines.insert(start, (self.ind, head))
        for line in tail:
            self.lines.append((self.ind, line))

    def loop(self, s, head_lines, body_fn, labels):
        """A Python loop: head_lines (already emitted up to the `while`), body by body_fn."""
        c = self.push_ctx("loop", labels, True)
        outer_start = len(self.lines)
        for h in head_lines:
            self.emit(h)
        self.ind += 1
        body_start = len(self.lines)
        self.ind += 1
        body_fn()
        self.ind -= 1
        if c[5]:
            self.wrap(body_start, "try:", ["except ContinueTo as _k:", "    if _k.label != %d: raise" % c[2]])
        else:
            self.unindent(body_start)
        self.ind -= 1
        self.ctx.pop()
        if c[4]:
            # a break from inside a switch or a labeled break: by exception
            self.ind_lines(outer_start)
            self.wrap(outer_start, "try:", ["except BreakTo as _b:", "    if _b.label != %d: raise" % c[2]])

    def ind_lines(self, start):
        lines = self.lines
        for k in range(start, len(lines)):
            ind, text = lines[k]
            lines[k] = (ind + 1, text)

    def tick(self):
        self.loopc = True
        self.emit("_c += 1")
        self.emit("if not _c & 1023: check()")

    def s_While(self, s):
        labels = self.take_labels(s)
        pre_save = self.pre
        self.pre = []
        test = self.cond(s.test)
        tpre = self.pre
        self.pre = pre_save
        if tpre:
            def body():
                self.pre = tpre
                self.emit("if not (%s): break" % test)
                self.tick()
                self.sub(s.body)
            self.loop(s, ["while True:"], body, labels)
        else:
            def body():
                self.tick()
                self.sub(s.body)
            self.loop(s, ["while %s:" % test], body, labels)

    def s_DoWhile(self, s):
        labels = self.take_labels(s)
        f = self.t()
        self.emit("%s = True" % f)
        pre_save = self.pre
        self.pre = []
        test = self.cond(s.test)
        tpre = self.pre
        self.pre = pre_save
        if tpre:
            # rare: the test needs code first
            def body():
                self.emit("if not %s:" % f)
                self.ind += 1
                self.pre = tpre
                self.emit("if not (%s): break" % test)
                self.ind -= 1
                self.emit("%s = False" % f)
                self.tick()
                self.sub(s.body)
            self.loop(s, ["while True:"], body, labels)
            return

        def body():
            self.emit("%s = False" % f)
            self.tick()
            self.sub(s.body)
        self.loop(s, ["while %s or %s:" % (f, test)], body, labels)

    def s_For(self, s):
        labels = self.take_labels(s)
        sc = s.scope
        saved = self.enter_scope(sc)
        if s.init is not None:
            self.stmt(s.init)
        f = self.t()
        per_iter = sc is not None and sc.frame
        if s.update is not None or per_iter:
            self.emit("%s = True" % f)

        def body():
            if s.update is not None or per_iter:
                self.emit("if %s: %s = False" % (f, f))
                self.emit("else:")
                self.ind += 1
                if per_iter:
                    self.emit("%s = list(%s)" % (sc.pyframe, sc.pyframe))
                if s.update is not None:
                    n = len(self.lines)
                    self.s_Expr(Node("Expr", s.update.pos, e=s.update))
                    if len(self.lines) == n:
                        self.emit("pass")
                else:
                    self.emit("pass")
                self.ind -= 1
            if s.test is not None:
                self.emit("if not (%s): break" % self.cond(s.test))
            self.tick()
            self.sub(s.body)
        self.loop(s, ["while True:"], body, labels)
        self.scope = saved

    def s_ForIn(self, s):
        labels = self.take_labels(s)
        right = self.expr(s.right)
        it = self.t()
        v = self.t()
        sc = s.scope
        if s.of:
            if s.is_await:
                self.emit("%s = iterate_await(%s)" % (it, right))
            else:
                self.emit("%s = iterate(%s)" % (it, right))
        else:
            self.emit("%s = for_in_keys(%s)" % (it, right))
        start = len(self.lines)
        saved_scope = self.scope

        def body():
            self.scope = saved_scope
            self.enter_scope(sc)
            left = s.left
            if left.t == "Var":
                target, _ = left.decls[0]
                self.assign_pattern(target, v, left.kind)
            else:
                self.assign_pattern(left, v, None)
            self.tick()
            self.sub(s.body)
            self.scope = saved_scope
        if s.of:
            self.ind += 1
            self.loop(s, ["for %s in %s:" % (v, it)], body, labels)
            self.ind -= 1
            self.wrap(start, "try:", ["finally:", "    close_iter(%s)" % it])
        else:
            self.loop(s, ["for %s in %s:" % (v, it)], body, labels)
        self.scope = saved_scope

    def s_With(self, s):
        v = self.expr(s.obj)
        saved = self.enter_scope(s.scope)
        b = s.scope.names["%with"]
        self.write_stmt(b, "%with", "to_obj(%s)" % v)
        self.sub(s.body)
        self.scope = saved

    def with_read(self, e, plain):
        """A name inside with blocks: the with objects first (innermost last in the list order given)."""
        out = plain
        for w in reversed(e.withs):
            W = self.read(w, "%with")
            out = "(get(%s, %r) if has_prop(%r, %s) else %s)" % (W, e.name, e.name, W, out)
        return out

    def s_Break(self, s):
        self.jump(s, True)

    def s_Continue(self, s):
        self.jump(s, False)

    def jump(self, s, is_break):
        label = s.label
        target = None
        crossed_py_loop = False
        for c in reversed(self.ctx):
            if label is None:
                if c[0] == "loop" or (is_break and c[0] == "switch"):
                    target = c
                    break
            elif label in c[1]:
                target = c
                break
            if c[3]:
                crossed_py_loop = True
        if target is None:
            raise rt.JSThrow(rt.make_error("SyntaxError", "Illegal %s statement" % ("break" if is_break else
                                                                                    "continue")))
        if not crossed_py_loop and target[3] and (is_break or target[0] == "loop"):
            self.emit("break" if is_break else "continue")
            return
        if is_break:
            target[4] = True
            self.emit("raise BreakTo(%d)" % target[2])
        else:
            target[5] = True
            self.emit("raise ContinueTo(%d)" % target[2])

    def s_Switch(self, s):
        labels = self.take_labels(s)
        d = self.t()
        k = self.t()
        self.emit("%s = %s" % (d, self.expr(s.disc)))
        saved = self.enter_scope(s.scope)
        n = len(s.cases)
        default = n
        first = True
        for i in range(n):
            test, _ = s.cases[i]
            if test is None:
                default = i
                continue
            self.emit("%s seq(%s, %s):" % ("if" if first else "elif", d, self.expr(test)))
            first = False
            self.ind += 1
            self.emit("%s = %d" % (k, i))
            self.ind -= 1
        if first:
            self.emit("%s = %d" % (k, default))
        else:
            self.emit("else:")
            self.ind += 1
            self.emit("%s = %d" % (k, default))
            self.ind -= 1
        c = self.push_ctx("switch", labels, True)
        start = len(self.lines)
        self.emit("while True:")
        self.ind += 1
        for i in range(n):
            _, body = s.cases[i]
            if not body:
                continue
            self.emit("if %s <= %d:" % (k, i))
            self.ind += 1
            for st in body:
                self.stmt(st)
            self.emit("pass")
            self.ind -= 1
        self.emit("break")
        self.ind -= 1
        self.ctx.pop()
        if c[4]:
            self.ind_lines(start)
            self.wrap(start, "try:", ["except BreakTo as _b:", "    if _b.label != %d: raise" % c[2]])
        self.scope = saved

    def s_Try(self, s):
        self.emit("try:")
        self.ind += 1
        self.block(s.block.body, s.block.scope)
        self.ind -= 1
        if s.handler is not None:
            e = self.t()
            self.emit("except BaseException as %s:" % e)
            self.ind += 1
            saved = self.enter_scope(s.scope)
            if s.param is not None:
                self.assign_pattern(s.param, "catch(%s)" % e, "let")
            else:
                self.emit("catch(%s)" % e)
            self.block(s.handler.body, s.handler.scope)
            self.scope = saved
            self.ind -= 1
        if s.final is not None:
            self.emit("finally:")
            self.ind += 1
            self.block(s.final.body, s.final.scope)
            self.ind -= 1

    # ---- destructuring ----
    def assign_pattern(self, p, value, kind):
        """Statements that put value into the pattern. kind: var/let/const (a declaration) or None."""
        t = p.t
        if t == "Ident":
            b = self.lookup(p.name)
            if kind is None:
                self.write_stmt(b, p.name, value)
            else:
                self.decl_stmt(b, p.name, value, kind)
        elif t == "Member":
            self.emit(self.member_put(p, value))
        elif t == "AssignPattern":
            v = self.t()
            self.emit("%s = %s" % (v, value))
            self.emit("if %s is UNDEF:" % v)
            self.ind += 1
            name = p.target.name if p.target.t == "Ident" else None
            self.emit("%s = %s" % (v, self.expr(p.default, name)))
            self.ind -= 1
            self.assign_pattern(p.target, v, kind)
        elif t == "ArrayPattern":
            v = self.t()
            self.emit("%s = spread(%s)" % (v, value))
            for i in range(len(p.elems)):
                el = p.elems[i]
                if el is None:
                    continue
                if el.t == "Rest":
                    self.assign_pattern(el.arg, "arr(%s[%d:])" % (v, i), kind)
                    break
                self.assign_pattern(el, "(%s[%d] if len(%s) > %d else UNDEF)" % (v, i, v, i), kind)
        elif t == "ObjectPattern":
            v = self.t()
            self.emit("%s = coercible(%s)" % (v, value))
            used = []
            for item in p.props:
                if isinstance(item, Node):                 # ...rest
                    self.assign_pattern(item.arg, "obj_rest(%s, [%s])" % (v, ", ".join(used)), kind)
                    continue
                key, computed, target = item
                if computed:
                    kv = self.t()
                    self.emit("%s = to_key(%s)" % (kv, self.expr(key)))
                    k = kv
                else:
                    k = repr(str(key.value) if key.t == "Str" else rt.num_str(key.value))
                used.append(k)
                self.assign_pattern(target, "get(%s, %s)" % (v, k), kind)
        else:
            raise rt.JSThrow(rt.make_error("SyntaxError", "Invalid destructuring assignment target"))

    # ---- assignments as statements ----
    def assign_stmt(self, e):
        target = e.target
        op = e.op
        if target.t in ("ArrayPattern", "ObjectPattern"):
            self.assign_pattern(target, self.expr(e.value), None)
            return
        if op == "=":
            if target.t == "Ident":
                b = self.lookup(target.name)
                if getattr(target, "withs", None):
                    self.emit(self.e_Assign(e))
                    return
                self.write_stmt(b, target.name, self.expr(e.value, target.name))
            else:
                self.emit(self.member_put(target, self.expr(e.value)))
            return
        self.emit(self.expr(e))

    def update_stmt(self, e):
        a = e.arg
        fn = "inc" if e.op == "++" else "dec"
        if a.t == "Ident":
            b = self.lookup(a.name)
            if b is not None and not b.glob and b.slot < 0:
                self.emit("%s = %s(%s)" % (b.py, fn, b.py))
                return
        self.emit(self.expr(e))

    def member_put(self, target, value):
        if target.obj.t == "Super":
            return "super_put(F.home, this, %s, %s)" % (self.key(target), value)
        o = self.expr(target.obj)
        if target.computed:
            return "putv(%s, %s, %s)" % (o, self.expr(target.prop), value)
        return "put(%s, %r, %s)" % (o, target.prop.value, value)

    def key(self, m):
        if m.computed:
            return "to_key(%s)" % self.expr(m.prop)
        return repr(m.prop.value)

    # ---- expressions ----
    def cond(self, e):
        """A Python boolean for a JavaScript condition."""
        t = e.t
        if t == "Unary" and e.op == "!":
            return "not (%s)" % self.cond(e.arg)
        if t == "Logical" and e.op in ("&&", "||"):
            return "(%s %s %s)" % (self.cond(e.l), "and" if e.op == "&&" else "or", self.cond(e.r))
        if t == "Binary" and e.op in _BOOL_OPS:
            return self.expr(e)
        if t == "Bool":
            return "True" if e.value else "False"
        return "truthy(%s)" % self.expr(e)

    def expr(self, e, name=None):
        return getattr(self, "e_" + e.t)(e, name) if e.t in ("Function", "Class") else getattr(self, "e_" + e.t)(e)

    def e_Num(self, e):
        v = e.value
        if type(v) is float:
            if v != v:
                return "NAN"
            if v == rt.INF:
                return "INF"
            return repr(v)
        return str(v)

    def e_Str(self, e):
        return repr(e.value)

    def e_Bool(self, e):
        return "True" if e.value else "False"

    def e_Null(self, e):
        return "None"

    def e_Ident(self, e):
        plain = self.read(getattr(e, "b", None), e.name)
        if getattr(e, "withs", None):
            return self.with_read(e, plain)
        return plain

    def e_This(self, e):
        if self.fn.node is not None and self.fn.arrow:
            return "F.this"
        return "this"

    def e_NewTarget(self, e):
        if self.fn.node is not None and not self.fn.arrow:
            return "NT"
        return "UNDEF"

    def e_Regex(self, e):
        k = self.const((e.pattern, e.flags))
        return "regex(%s)" % k

    def e_Tmpl(self, e):
        parts = []
        for i in range(len(e.quasis)):
            q = e.quasis[i]
            if q:
                parts.append(repr(q))
            if i < len(e.exprs):
                parts.append(self.expr(e.exprs[i]))
        if not parts:
            return "''"
        if len(parts) == 1 and parts[0][0] in "'\"":
            return parts[0]
        return "cat(%s)" % ", ".join(parts)

    def e_TaggedTmpl(self, e):
        q = e.quasi
        strings = self.const((list(q.quasis), list(q.raws)))
        args = ["tmpl_strings(%s)" % strings] + [self.expr(x) for x in q.exprs]
        tag = e.tag
        if tag.t == "Member" and tag.obj.t != "Super":
            o = self.expr(tag.obj)
            if tag.computed:
                return "callv(%s, %s, %s)" % (o, self.expr(tag.prop), ", ".join(args))
            return "callm(%s, %r, %s)" % (o, tag.prop.value, ", ".join(args))
        return "call(%s, UNDEF, %s)" % (self.expr(tag), ", ".join(args))

    def e_Array(self, e):
        items = []
        has_spread = False
        for x in e.elems:
            if x is None:
                items.append("HOLE")
            elif x.t == "Spread":
                items.append("*spread(%s)" % self.expr(x.arg))
                has_spread = True
            else:
                items.append(self.expr(x))
        if has_spread:
            return "arr(%s)" % self.joined(items)
        return "arr([%s])" % ", ".join(items)

    def joined(self, items):
        """[a, *b, c] for MicroPython (no unpacking in displays): xs([a], b, [c])."""
        parts = []
        run = []
        for it in items:
            if it.startswith("*"):
                if run:
                    parts.append("[%s]" % ", ".join(run))
                    run = []
                parts.append(it[1:])
            else:
                run.append(it)
        if run:
            parts.append("[%s]" % ", ".join(run))
        return "xs(%s)" % ", ".join(parts)

    def e_Object(self, e):
        simple = True
        for p in e.props:
            if p.kind != "init" or p.computed or getattr(p, "method", False) or \
                    (p.key is not None and p.key.t == "Str" and p.key.value == "__proto__"):
                simple = False
                break
        if simple:
            items = []
            for p in e.props:
                k = p.key.value if p.key.t == "Str" else rt.num_str(p.key.value)
                items.append(repr(str(k)))
                items.append(self.expr(p.value, str(k)))
            return "obj(%s)" % ", ".join(items)
        items = []
        for p in e.props:
            if p.kind == "spread":
                items.append("('...', None, %s)" % self.expr(p.value))
                continue
            if p.computed:
                k = "to_key(%s)" % self.expr(p.key)
            else:
                k = repr(str(p.key.value) if p.key.t == "Str" else rt.num_str(p.key.value))
            if getattr(p, "method", False) or p.kind in ("get", "set"):
                info = self.func_info(p.value)
                kind = {"get": "g", "set": "s"}.get(p.kind, "m")
                items.append("(%r, %s, %s)" % (kind, k, info))
            elif not p.computed and p.key.t == "Str" and p.key.value == "__proto__" and \
                    not getattr(p, "shorthand", False):
                items.append("('proto', None, %s)" % self.expr(p.value))
            else:
                items.append("('=', %s, %s)" % (k, self.expr(p.value, None if p.computed else str(p.key.value))))
        return "objx(%s, %s)" % (self.cur_frame(), ", ".join(items) if items else "")

    def func_info(self, node):
        """The FuncInfo of a nested function (a constant of this code)."""
        info = getattr(node, "info", None)
        if info is None:
            info = make_info(node, self.unit)
        return self.unit.ns_name(info)

    def func_value(self, node, name=None):
        info = self.func_info(node)
        if name and not node.name:
            info_obj = node.info
            if not info_obj.name:
                info_obj.name = name
        env = self.cur_frame()
        if node.is_arrow:
            this = "F.this" if (self.fn.node is not None and self.fn.arrow) else "this"
            home = "F.home" if self.fn.node is not None else "None"
            return "mkarrow(%s, %s, %s, %s)" % (info, env, this, home)
        return "mkfn(%s, %s)" % (info, env)

    def e_Function(self, e, name=None):
        return self.func_value(e, name)

    def class_value(self, node, name=None):
        sup = "MISSING" if node.sup is None else self.expr(node.sup)
        ctor = None
        members = []
        saved = self.enter_scope(node.scope)
        for m in node.members:
            if m.kind == "constructor":
                m.value.derived = node.sup is not None
                ctor = m.value
                continue
            if m.computed:
                k = "to_key(%s)" % self.expr(m.key)
            elif m.key is None:
                k = "None"
            else:
                k = repr(str(m.key.value) if m.key.t == "Str" else rt.num_str(m.key.value))
            info = self.func_info(m.value) if m.value is not None else "None"
            kind = {"method": "m", "get": "g", "set": "s", "field": "f", "block": "b"}[m.kind]
            members.append("(%r, %s, %s, %s)" % (kind, "True" if m.static else "False", k, info))
        if ctor is not None:
            ctor.name = node.name or name or ""
            cinfo = self.func_info(ctor)
        else:
            cinfo = "None"
        cname = node.name or name or ""
        v = "mkclass(%r, %s, %s, %s, [%s])" % (cname, sup, cinfo, self.cur_frame(), ", ".join(members))
        inner = getattr(node, "inner", None)
        if inner is not None and inner.slot >= 0:
            v = "sset(%s, %d, %s)" % (self.frame_of(inner.scope), inner.slot, v)
        elif inner is not None and inner.py is not None:
            v = "(%s := %s)" % (inner.py, v)
        self.scope = saved
        if node.scope is not None and node.scope.frame:
            # the class's own frame (for its name) is made in an expression: a helper does it
            pf = self.cur_frame()
            v = "with_frame(%s, %d, lambda %s: %s)" % (pf, node.scope.nslots, node.scope.pyframe, v)
        return v

    def e_Class(self, e, name=None):
        return self.class_value(e, name)

    def e_Unary(self, e):
        op = e.op
        if op == "!":
            return "(not %s)" % self.cond(e.arg)
        if op == "-":
            a = e.arg
            if a.t == "Num":
                v = a.value
                if v == 0:
                    return "-0.0"
                return "(-%s)" % self.e_Num(a)
            return "neg(%s)" % self.expr(a)
        if op == "+":
            return "to_num(%s)" % self.expr(e.arg)
        if op == "~":
            return "bit_not(%s)" % self.expr(e.arg)
        if op == "typeof":
            a = e.arg
            if a.t == "Ident" and (getattr(a, "b", None) is None or a.b.glob):
                return "gtypeof(%r)" % a.name
            return "typeof(%s)" % self.expr(a)
        if op == "void":
            return "(%s, UNDEF)[1]" % self.expr(e.arg)
        if op == "delete":
            a = e.arg
            if a.t == "Member":
                o = self.expr(a.obj)
                if a.computed:
                    return "delete(%s, %s)" % (o, self.expr(a.prop))
                return "delete(%s, %r)" % (o, a.prop.value)
            if a.t == "Ident":
                if getattr(a, "b", None) is None:
                    return "gdelete(%r)" % a.name
                return "False"
            if a.t == "Chain":
                return "(%s, True)[1]" % self.expr(a)
            return "(%s, True)[1]" % self.expr(a)
        raise ValueError(op)

    def e_Update(self, e):
        a = e.arg
        fn = "inc" if e.op == "++" else "dec"
        if a.t == "Ident":
            b = self.lookup(a.name)
            if b is not None and not b.glob and b.slot < 0:
                if e.prefix:
                    return "(%s := %s(%s))" % (b.py, fn, b.py)
                t = self.t()
                return "((%s := to_numeric(%s)), (%s := %s(%s)))[0]" % (t, b.py, b.py, fn, t)
            if b is not None and not b.glob:
                return "supd(%s, %d, %s, %s)" % (self.frame_of(b.scope), b.slot, fn, "True" if e.prefix else "False")
            return "gupd(%r, %s, %s)" % (a.name, fn, "True" if e.prefix else "False")
        if a.obj.t == "Super":
            return "upd_super(F.home, this, %s, %s, %s)" % (self.key(a), fn, "True" if e.prefix else "False")
        o = self.expr(a.obj)
        k = self.expr(a.prop) if a.computed else repr(a.prop.value)
        return "upd(%s, %s, %s, %s)" % (o, k, fn, "True" if e.prefix else "False")

    def e_Binary(self, e):
        op = e.op
        f = _BINOPS[op]
        if op == "in":
            return "has_prop(%s, %s)" % (self.expr(e.l), self.expr(e.r))
        l = self.expr(e.l)
        r = self.expr(e.r)
        if op in ("===", "!==") and (e.r.t in ("Null",) or (e.r.t == "Ident" and e.r.name == "undefined" and
                                                          getattr(e.r, "b", None) is None)):
            return "(%s %s %s)" % (l, "is" if op == "===" else "is not", r)
        if op in ("===", "!==") and e.r.t == "Str":
            return "(%s %s %s)" % (l, "==" if op == "===" else "!=", r)
        return "%s(%s, %s)" % (f, l, r)

    def e_Logical(self, e):
        t = self.t()
        l = self.expr(e.l)
        r = self.expr(e.r)
        if e.op == "&&":
            return "(%s if not truthy(%s := %s) else %s)" % (t, t, l, r)
        if e.op == "||":
            return "(%s if truthy(%s := %s) else %s)" % (t, t, l, r)
        return "(%s if (%s := %s) is not None and %s is not UNDEF else %s)" % (t, t, l, t, r)

    def e_Cond(self, e):
        return "(%s if %s else %s)" % (self.expr(e.cons), self.cond(e.test), self.expr(e.alt))

    def e_Seq(self, e):
        return "(%s)[-1]" % ", ".join([self.expr(x) for x in e.exprs] + [""])

    def e_Assign(self, e):
        target = e.target
        op = e.op
        if target.t in ("ArrayPattern", "ObjectPattern"):
            return self.pattern_expr(target, self.expr(e.value))
        if op == "=":
            if target.t == "Ident":
                plain = self.write_expr(self.lookup(target.name), target.name, self.expr(e.value, target.name))
                if getattr(target, "withs", None):
                    out = plain
                    for w in reversed(target.withs):
                        W = self.read(w, "%with")
                        out = "(put(%s, %r, %s) if has_prop(%r, %s) else %s)" % (
                            W, target.name, self.expr(e.value), target.name, W, out)
                    return out
                return plain
            return self.member_put(target, self.expr(e.value))
        if op in ("&&=", "||=", "??="):
            return self.logical_assign(e)
        f = _BINOPS[op[:-1]]
        if target.t == "Ident":
            b = self.lookup(target.name)
            cur = self.read(b, target.name)
            return self.write_expr(b, target.name, "%s(%s, %s)" % (f, cur, self.expr(e.value)))
        if target.obj.t == "Super":
            k = self.t()
            return "super_put(F.home, this, (%s := %s), %s(super_get(F.home, this, %s), %s))" % (
                k, self.key(target), f, k, self.expr(e.value))
        o = self.t()
        oe = self.expr(target.obj)
        if target.computed:
            k = self.t()
            return "putv((%s := %s), (%s := %s), %s(getv(%s, %s), %s))" % (
                o, oe, k, self.expr(target.prop), f, o, k, self.expr(e.value))
        return "put((%s := %s), %r, %s(get(%s, %r), %s))" % (
            o, oe, target.prop.value, f, o, target.prop.value, self.expr(e.value))

    def logical_assign(self, e):
        target = e.target
        op = e.op[:-2]
        t = self.t()
        if op == "&&":
            test = "not truthy(%s := %%s)" % t
        elif op == "||":
            test = "truthy(%s := %%s)" % t
        else:
            test = "not nullish(%s := %%s)" % t
        if target.t == "Ident":
            b = self.lookup(target.name)
            cur = self.read(b, target.name)
            new = self.write_expr(b, target.name, self.expr(e.value, target.name))
            return "(%s if %s else %s)" % (t, test % cur, new)
        o = self.t()
        oe = self.expr(target.obj)
        if target.computed:
            k = self.t()
            cur = "getv((%s := %s), (%s := %s))" % (o, oe, k, self.expr(target.prop))
            new = "putv(%s, %s, %s)" % (o, k, self.expr(e.value))
        else:
            cur = "get((%s := %s), %r)" % (o, oe, target.prop.value)
            new = "put(%s, %r, %s)" % (o, target.prop.value, self.expr(e.value))
        return "(%s if %s else %s)" % (t, test % cur, new)

    def pattern_expr(self, target, value):
        """A destructuring assignment in an expression: a nested def does it."""
        name = "_d%d" % _next_id()
        saved_lines, saved_ind, saved_pre = self.lines, self.ind, self.pre
        self.lines = []
        self.ind = 1
        self.pre = []
        self.assign_pattern(target, "_v", None)
        body = self.lines
        self.lines, self.ind, self.pre = saved_lines, saved_ind, saved_pre
        locs = set()
        for b in self._pattern_bindings(target):
            if b is not None and not b.glob and b.slot < 0:
                locs.add(b.py)
        block = [(0, "def %s(_v):" % name)]
        if locs:
            block.append((1, "nonlocal " + ", ".join(sorted(locs))))
        block.extend(body)
        block.append((1, "return _v"))
        self.pre.append(block)
        return "%s(%s)" % (name, value)

    def _pattern_bindings(self, p):
        out = []
        names = Analyzer(False).pattern_names(p, [])
        for n in names:
            out.append(self.lookup(n))
        return out

    def e_Call(self, e):
        callee = e.callee
        args = self.args(e.args)
        if callee.t == "Super":
            return "super_call(F, NT, %s)" % (args[1:] if args.startswith("*") else "[%s]" % args)
        if callee.t == "Member":
            if callee.obj.t == "Super":
                return "call(super_get(F.home, this, %s), this%s)" % (self.key(callee), ", " + args if args else "")
            o = self.expr(callee.obj)
            if callee.computed:
                return "callv(%s, %s%s)" % (o, self.expr(callee.prop), ", " + args if args else "")
            return "callm(%s, %r%s)" % (o, callee.prop.value, ", " + args if args else "")
        if callee.t == "Ident" and getattr(callee, "withs", None):
            out = "call(%s, UNDEF%s)" % (self.read(getattr(callee, "b", None), callee.name), ", " + args if args else "")
            for w in reversed(callee.withs):
                W = self.read(w, "%with")
                out = "(callv(%s, %r%s) if has_prop(%r, %s) else %s)" % (W, callee.name, ", " + args if args else "",
                                                                         callee.name, W, out)
            return out
        if callee.t == "Ident" and callee.name == "eval" and getattr(callee, "b", None) is None:
            return "direct_eval(%s)" % (args or "UNDEF")
        return "call(%s, UNDEF%s)" % (self.expr(callee), ", " + args if args else "")

    def args(self, args):
        out = []
        spread = False
        for a in args:
            if a.t == "Spread":
                out.append("*spread(%s)" % self.expr(a.arg))
                spread = True
            else:
                out.append(self.expr(a))
        if spread:
            return "*" + self.joined(out)
        return ", ".join(out)

    def e_New(self, e):
        a = self.args(e.args)
        if a.startswith("*"):
            return "construct(%s, %s)" % (self.expr(e.callee), a[1:])
        return "construct(%s, [%s])" % (self.expr(e.callee), a)

    def e_Member(self, e):
        if e.obj.t == "Super":
            return "super_get(F.home, this, %s)" % self.key(e)
        o = self.expr(e.obj)
        if e.computed:
            p = e.prop
            if p.t == "Str":
                return "get(%s, %r)" % (o, p.value)
            return "getv(%s, %s)" % (o, self.expr(p))
        return "get(%s, %r)" % (o, e.prop.value)

    def e_Super(self, e):
        return "F.home"

    def e_Spread(self, e):
        return "arr(spread(%s))" % self.expr(e.arg)

    def e_Yield(self, e):
        self.has_yield = True
        v = "UNDEF" if e.arg is None else self.expr(e.arg)
        node = self.fn.node
        if node is not None and node.is_async:
            if e.delegate:
                return "(yield from async_delegate(%s))" % v
            return "(yield (1, %s))" % v
        if e.delegate:
            return "(yield from delegate(%s))" % v
        return "(yield %s)" % v

    def e_Await(self, e):
        node = self.fn.node
        if node is None or not node.is_async:
            return "await_sync(%s)" % self.expr(e.arg)
        self.has_yield = True
        if node.is_gen:
            return "(yield (0, %s))" % self.expr(e.arg)
        return "(yield %s)" % self.expr(e.arg)

    def e_Import(self, e):
        return "dynamic_import(%s)" % self.expr(e.arg)

    def e_Chain(self, e):
        # flatten: base, then links
        links = []
        x = e.e
        while True:
            if x.t == "Member" and x.obj.t != "Super":
                links.append(("get", x))
                x = x.obj
            elif x.t == "Call" and x.callee.t != "Super":
                links.append(("call", x))
                x = x.callee
            else:
                break
        links.reverse()
        base = self.expr(x)
        return self._chain(base, links, 0, None)

    def _chain(self, cur, links, i, this):
        """cur: the expression so far; this: the object a call made now would get (or None)."""
        if i >= len(links):
            return cur
        kind, node = links[i]
        if node.optional:
            t = self.t()
            rest = self._chain_link(t, links, i, this)
            return "(UNDEF if nullish(%s := %s) else %s)" % (t, cur, rest)
        return self._chain_link(cur, links, i, this)

    def _chain_link(self, cur, links, i, this):
        kind, node = links[i]
        if kind == "get":
            # a get followed by a non-optional call is a method call
            if i + 1 < len(links) and links[i + 1][0] == "call" and not links[i + 1][1].optional:
                call = links[i + 1][1]
                a = self.args(call.args)
                if node.computed:
                    v = "callv(%s, %s%s)" % (cur, self.expr(node.prop), ", " + a if a else "")
                else:
                    v = "callm(%s, %r%s)" % (cur, node.prop.value, ", " + a if a else "")
                return self._chain(v, links, i + 2, None)
            if i + 1 < len(links) and links[i + 1][0] == "call":
                # a?.b?.(): keep the object for the call
                o = self.t()
                k = self.expr(node.prop) if node.computed else repr(node.prop.value)
                v = "getv((%s := %s), %s)" % (o, cur, k)
                return self._chain(v, links, i + 1, o)
            k = self.expr(node.prop) if node.computed else repr(node.prop.value)
            v = ("getv(%s, %s)" if node.computed else "get(%s, %s)") % (cur, k)
            return self._chain(v, links, i + 1, None)
        a = self.args(node.args)
        v = "call(%s, %s%s)" % (cur, this or "UNDEF", ", " + a if a else "")
        return self._chain(v, links, i + 1, None)

    def e_ArrowParams(self, e):
        raise rt.JSThrow(rt.make_error("SyntaxError", "Unexpected token '=>'"))

    def e_ShorthandInit(self, e):
        raise rt.JSThrow(rt.make_error("SyntaxError", "Invalid shorthand property initializer"))


_BOOL_OPS = ("==", "!=", "===", "!==", "<", ">", "<=", ">=", "instanceof", "in")
_BINOPS = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod", "**": "power",
           "==": "leq", "!=": "lne", "===": "seq", "!==": "sne", "<": "lt", ">": "gt", "<=": "le", ">=": "ge",
           "&": "bit_and", "|": "bit_or", "^": "bit_xor", "<<": "shl", ">>": "sar", ">>>": "shr",
           "instanceof": "instance_of", "in": "has_prop", "??": "nullish_or"}


# ---- functions: made lazily ----

def make_info(node, unit):
    fn = node.fn
    kind = "normal"
    if node.is_arrow:
        kind = "arrow"
    elif node.kind == "ctor":
        kind = "class"
    elif node.kind == "method":
        kind = "method"
    if node.is_gen and node.is_async:
        kind = "asyncgen"
    elif node.is_gen:
        kind = "gen"
    elif node.is_async:
        kind = "async"
    n = 0
    for p in node.params:
        if p.t in ("Rest", "AssignPattern"):
            break
        n += 1
    info = rt.FuncInfo(None, node.name or "", n, kind,
                       ctor=kind in ("normal", "class") and not node.is_arrow and node.kind != "method")
    info.node = node
    info.unit = unit
    info.strict = fn.strict
    info.derived = node.kind == "ctor" and getattr(node, "derived", False)
    info.id = _next_id()
    info.code = _stub(info)
    node.info = info
    fn.info = info
    return info


def _stub(info):
    def stub(F, this, *args):
        compile_function(info)
        return info.code(F, this, *args)
    return stub


def compile_function(info):
    unit = info.unit
    node = info.node
    g = FnGen(node.fn, unit)
    name = "J%d" % info.id
    src = g.gen(name)
    ns = unit.ns
    try:
        exec(src, ns)
    except SyntaxError as e:
        raise rt.JSThrow(rt.make_error("InternalError", "compiling %s: %s\n%s" % (info.name or "function", e,
                                                                                  _numbered(src))))
    code = ns[name]
    info.pyname = name
    kind = info.kind
    if kind == "gen":
        mk = ns["make_generator"]
        info.code = lambda F, this, *a: mk(F, code(F, this, *a))
    elif kind == "async":
        run = ns["run_async"]
        info.code = lambda F, this, *a: run(code(F, this, *a))
    elif kind == "asyncgen":
        mk = ns["make_async_generator"]
        info.code = lambda F, this, *a: mk(F, code(F, this, *a))
    else:
        info.code = code
    if ns.get("_DEBUG_SRC"):
        ns["_DEBUG_SRC"].append(src)


def _numbered(src):
    lines = src.split("\n")
    return "\n".join("%4d %s" % (i + 1, lines[i]) for i in range(min(len(lines), 400)))


def compile_script(src, name, ns, want_value=False):
    """A script -> a Python function to run it (with this = the global object)."""
    src = ascii_source(src)
    tree = parse(src)
    an = Analyzer(tree.strict)
    fn = an.program(tree)
    layout(an.fns)
    unit = Unit(src, name, ns)
    unit.tree = tree
    unit.want_value = want_value
    unit.ns_name = lambda info: _ns_name(ns, info)
    g = FnGen(fn, unit)
    pyname = "S%d" % _next_id()
    code = g.gen(pyname)
    try:
        exec(code, ns)
    except SyntaxError as e:
        raise rt.JSThrow(rt.make_error("InternalError", "compiling the script: %s\n%s" % (e, _numbered(code))))
    if ns.get("_DEBUG_SRC") is not None:
        ns["_DEBUG_SRC"].append(code)
    return ns[pyname]


def _ns_name(ns, info):
    name = "I%d" % info.id
    if name not in ns:
        ns[name] = info
    return name
