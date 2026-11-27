# JavaScript source -> a tree of Nodes (ES2022: classes, arrows, destructuring,
# spread, async/await, generators, optional chaining, template literals...).
#
#   tree = parse(source)          a Node("Program"); raises JSSyntaxError
from js.lexer import Lexer, JSSyntaxError


class Node:
    def __init__(self, t, pos, **kw):
        self.t = t
        self.pos = pos
        for k in kw:
            setattr(self, k, kw[k])

    def __repr__(self):
        return "Node(%s)" % self.t


ASSIGN_OPS = ("=", "+=", "-=", "*=", "/=", "%=", "**=", "<<=", ">>=", ">>>=", "&=", "|=", "^=", "&&=", "||=", "??=")
BINARY = {"??": 1, "||": 1, "&&": 2, "|": 3, "^": 4, "&": 5, "==": 6, "!=": 6, "===": 6, "!==": 6,
          "<": 7, ">": 7, "<=": 7, ">=": 7, "instanceof": 7, "in": 7, "<<": 8, ">>": 8, ">>>": 8,
          "+": 9, "-": 9, "*": 10, "/": 10, "%": 10, "**": 11}
# after these a '/' starts a regular expression
_REGEX_AFTER_NAMES = ("return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case",
                      "do", "else", "yield", "await")
RESERVED = ("break", "case", "catch", "class", "const", "continue", "debugger", "default", "delete", "do", "else",
            "export", "extends", "false", "finally", "for", "function", "if", "import", "in", "instanceof", "new",
            "null", "return", "super", "switch", "this", "throw", "true", "try", "typeof", "var", "void", "while",
            "with", "enum")


class Parser:
    def __init__(self, src):
        self.src = src
        self.lx = Lexer(src)
        self.tok = None
        self.prev = None
        self.in_function = False
        self.in_gen = False
        self.in_async = False
        self.strict = False
        self.labels = []
        self._advance(True)

    # ---- tokens ----
    def _regex_ok(self):
        p = self.tok
        if p is None:
            return True
        k = p[0]
        if k == "p":
            return p[1] not in (")", "]")
        if k == "name":
            return p[1] in _REGEX_AFTER_NAMES
        return False

    def _advance(self, regex_ok=None):
        if regex_ok is None:
            regex_ok = self._regex_ok()
        self.prev = self.tok
        self.tok = self.lx.token(regex_ok)

    def next(self):
        t = self.tok
        self._advance()
        return t

    def error(self, msg, pos=None):
        raise JSSyntaxError(msg, self.tok[2] if pos is None else pos, self.src)

    def unexpected(self):
        t = self.tok
        if t[0] == "eof":
            self.error("unexpected end of input")
        self.error("unexpected token %s" % (t[1] if t[0] in ("p", "name") else t[0]))

    def is_p(self, v):
        t = self.tok
        return t[0] == "p" and t[1] == v

    def is_name(self, v=None):
        t = self.tok
        return t[0] == "name" and (v is None or t[1] == v)

    def eat(self, v):
        t = self.tok
        if t[0] == "p" and t[1] == v:
            self._advance()
            return True
        return False

    def eat_name(self, v):
        t = self.tok
        if t[0] == "name" and t[1] == v:
            self._advance()
            return True
        return False

    def expect(self, v):
        t = self.tok
        if t[0] == "p" and t[1] == v:
            self._advance()
            return t
        self.error("expected %s" % v)

    def semicolon(self):
        if self.eat(";"):
            return
        t = self.tok
        if t[4] or t[0] == "eof" or (t[0] == "p" and t[1] == "}"):
            return
        self.unexpected()

    def as_operand(self):
        """The current token where an operand must be: a '/' here starts a regular expression."""
        t = self.tok
        if t[0] == "p" and t[1] in ("/", "/="):
            self.lx.i = t[2]
            self.tok = self.lx.token(True)

    def as_operator(self):
        """The current token where an operator must be: a regex here was a division."""
        t = self.tok
        if t[0] == "regex":
            self.lx.i = t[2]
            self.tok = self.lx.token(False)

    def save(self):
        return (self.lx.i, self.tok, self.prev)

    def restore(self, st):
        self.lx.i, self.tok, self.prev = st

    def ident(self):
        t = self.tok
        if t[0] != "name":
            self.unexpected()
        if t[1] in RESERVED and t[1] not in ("enum",):
            self.error("unexpected keyword %s" % t[1])
        self._advance()
        return t[1]

    # ---- the program ----
    def parse_program(self):
        body = self.directives_and_statements(True)
        if self.tok[0] != "eof":
            self.unexpected()
        return Node("Program", 0, body=body, strict=self.strict)

    def directives_and_statements(self, top):
        body = []
        # "use strict" at the start
        while self.tok[0] == "str":
            raw = self.src[self.tok[2] + 1:self.tok[3] - 1]
            s = self.statement()
            if s.t == "Expr" and s.e.t == "Str":
                if raw == "use strict":
                    self.strict = True
                body.append(s)
            else:
                body.append(s)
                break
        while not (self.tok[0] == "eof" if top else self.is_p("}")):
            if self.tok[0] == "eof":
                self.error("unexpected end of input")
            body.append(self.statement())
        return body

    # ---- statements ----
    def statement(self):
        t = self.tok
        pos = t[2]
        k, v = t[0], t[1]
        if k == "p":
            if v == "{":
                return self.block()
            if v == ";":
                self.next()
                return Node("Empty", pos)
        elif k == "name":
            if v == "var" or v == "const":
                return self.var_statement()
            if v == "let":
                st = self.save()
                self.next()
                if self.tok[0] == "name" and self.tok[1] not in ("in", "instanceof", "of") or \
                        self.is_p("[") or self.is_p("{"):
                    self.restore(st)
                    return self.var_statement()
                self.restore(st)
            if v == "function":
                return self.function(True, False, pos)
            if v == "async":
                st = self.save()
                self.next()
                if self.is_name("function") and not self.tok[4]:
                    self.restore(st)
                    return self.function(True, True, pos)
                self.restore(st)
            if v == "class":
                return self.class_(True)
            if v == "if":
                self.next()
                self.expect("(")
                test = self.expression()
                self.expect(")")
                cons = self.statement()
                alt = self.statement() if self.eat_name("else") else None
                return Node("If", pos, test=test, cons=cons, alt=alt)
            if v == "for":
                return self.for_statement()
            if v == "while":
                self.next()
                self.expect("(")
                test = self.expression()
                self.expect(")")
                body = self.loop_body()
                return Node("While", pos, test=test, body=body)
            if v == "do":
                self.next()
                body = self.loop_body()
                if not self.eat_name("while"):
                    self.error("expected while")
                self.expect("(")
                test = self.expression()
                self.expect(")")
                self.eat(";")
                return Node("DoWhile", pos, test=test, body=body)
            if v == "return":
                if not self.in_function:
                    self.error("return outside a function")
                self.next()
                arg = None
                if not (self.is_p(";") or self.is_p("}") or self.tok[4] or self.tok[0] == "eof"):
                    arg = self.expression()
                self.semicolon()
                return Node("Return", pos, arg=arg)
            if v == "break" or v == "continue":
                self.next()
                label = None
                if self.tok[0] == "name" and not self.tok[4] and self.tok[1] not in RESERVED:
                    label = self.next()[1]
                self.semicolon()
                return Node("Break" if v == "break" else "Continue", pos, label=label)
            if v == "throw":
                self.next()
                if self.tok[4]:
                    self.error("a line break after throw")
                arg = self.expression()
                self.semicolon()
                return Node("Throw", pos, arg=arg)
            if v == "try":
                return self.try_statement()
            if v == "switch":
                return self.switch_statement()
            if v == "with":
                self.error("with statements are not supported")
            if v == "debugger":
                self.next()
                self.semicolon()
                return Node("Empty", pos)
            if v == "import":
                st = self.save()
                self.next()
                if not (self.is_p("(") or self.is_p(".")):
                    self.error("import declarations need a module loader (not supported)")
                self.restore(st)
            if v == "export":
                self.next()
                if self.eat_name("default"):
                    if self.is_name("function") or self.is_name("class") or self.is_name("async"):
                        return self.statement()
                    e = self.assign()
                    self.semicolon()
                    return Node("Expr", pos, e=e)
                if self.is_p("{") or self.is_p("*"):
                    self.error("export lists need a module loader (not supported)")
                return self.statement()
            # a label?
            if v not in RESERVED:
                st = self.save()
                self.next()
                if self.is_p(":"):
                    self.next()
                    self.labels.append(v)
                    try:
                        if self.is_name("function"):
                            body = self.function(True, False, self.tok[2])
                        else:
                            body = self.statement()
                    finally:
                        self.labels.pop()
                    return Node("Labeled", pos, label=v, body=body)
                self.restore(st)
        e = self.expression()
        self.semicolon()
        return Node("Expr", pos, e=e)

    def loop_body(self):
        return self.statement()

    def block(self):
        pos = self.expect("{")[2]
        body = []
        while not self.is_p("}"):
            if self.tok[0] == "eof":
                self.error("unexpected end of input")
            body.append(self.statement())
        self.next()
        return Node("Block", pos, body=body)

    def var_statement(self):
        node = self.var_decl(False)
        self.semicolon()
        return node

    def var_decl(self, no_in):
        t = self.next()
        kind = t[1]
        decls = []
        while True:
            target = self.binding_target()
            init = None
            if self.eat("="):
                init = self.assign(no_in)
            decls.append((target, init))
            if not self.eat(","):
                break
        return Node("Var", t[2], kind=kind, decls=decls)

    def binding_target(self):
        t = self.tok
        if t[0] == "p" and t[1] in ("[", "{"):
            e = self.primary()
            return self.to_pattern(e)
        return Node("Ident", t[2], name=self.ident())

    def for_statement(self):
        pos = self.next()[2]
        is_await = self.eat_name("await")
        self.expect("(")
        init = None
        if self.is_p(";"):
            pass
        elif self.is_name("var") or self.is_name("const") or self.is_name("let") and self._let_decl():
            init = self.var_decl(True)
            if len(init.decls) == 1 and init.decls[0][1] is None or True:
                if self.is_name("of") or self.is_name("in"):
                    of = self.next()[1] == "of"
                    right = self.assign() if of else self.expression()
                    self.expect(")")
                    body = self.loop_body()
                    return Node("ForIn", pos, left=init, right=right, body=body, of=of, is_await=is_await)
        else:
            st = self.save()
            e = self.expression(True)
            if self.is_name("of") or self.is_name("in"):
                of = self.next()[1] == "of"
                target = self.to_pattern(e) if e.t in ("Array", "Object") else e
                right = self.assign() if of else self.expression()
                self.expect(")")
                body = self.loop_body()
                return Node("ForIn", pos, left=target, right=right, body=body, of=of, is_await=is_await)
            init = Node("Expr", e.pos, e=e)
            del st
        self.expect(";")
        test = None if self.is_p(";") else self.expression()
        self.expect(";")
        update = None if self.is_p(")") else self.expression()
        self.expect(")")
        body = self.loop_body()
        return Node("For", pos, init=init, test=test, update=update, body=body)

    def _let_decl(self):
        st = self.save()
        self.next()
        ok = self.tok[0] == "name" and self.tok[1] not in ("in", "of") or self.is_p("[") or self.is_p("{")
        self.restore(st)
        return ok

    def try_statement(self):
        pos = self.next()[2]
        block = self.block()
        param = handler = final = None
        if self.eat_name("catch"):
            if self.eat("("):
                param = self.binding_target()
                self.expect(")")
            handler = self.block()
        if self.eat_name("finally"):
            final = self.block()
        if handler is None and final is None:
            self.error("try without catch or finally")
        return Node("Try", pos, block=block, param=param, handler=handler, final=final)

    def switch_statement(self):
        pos = self.next()[2]
        self.expect("(")
        disc = self.expression()
        self.expect(")")
        self.expect("{")
        cases = []
        while not self.eat("}"):
            if self.eat_name("case"):
                test = self.expression()
            elif self.eat_name("default"):
                test = None
            else:
                self.unexpected()
            self.expect(":")
            body = []
            while not (self.is_name("case") or self.is_name("default") or self.is_p("}")):
                if self.tok[0] == "eof":
                    self.error("unexpected end of input")
                body.append(self.statement())
            cases.append((test, body))
        return Node("Switch", pos, disc=disc, cases=cases)

    # ---- functions and classes ----
    def function(self, is_decl, is_async, pos):
        if is_async:
            self.next()                         # async
        self.next()                             # function
        is_gen = self.eat("*")
        name = None
        if self.tok[0] == "name" and not self.is_p("("):
            name = self.ident()
        elif is_decl:
            self.error("a function declaration needs a name")
        f = self.function_rest(pos, name, is_async, is_gen, False)
        f.is_decl = is_decl
        return f

    def function_rest(self, pos, name, is_async, is_gen, is_method, kind="normal"):
        saved = (self.in_function, self.in_gen, self.in_async, self.strict, self.labels)
        self.in_function, self.in_gen, self.in_async, self.labels = True, is_gen, is_async, []
        try:
            params = self.params()
            self.expect("{")
            body = self.directives_and_statements(False)
            end = self.tok[3]
            self.next()
            strict = self.strict
        finally:
            self.in_function, self.in_gen, self.in_async, self.strict, self.labels = saved
        return Node("Function", pos, name=name, params=params, body=body, is_arrow=False, is_async=is_async,
                    is_gen=is_gen, expr_body=False, is_decl=False, strict=strict or saved[3], end=end,
                    kind=kind, is_method=is_method)

    def params(self):
        self.expect("(")
        out = []
        while not self.eat(")"):
            if self.eat("..."):
                out.append(Node("Rest", self.prev[2], arg=self.binding_target()))
                self.eat(",")
                self.expect(")")
                break
            t = self.binding_target()
            if self.eat("="):
                t = Node("AssignPattern", t.pos, target=t, default=self.assign())
            out.append(t)
            if not self.is_p(")"):
                self.expect(",")
        return out

    def arrow_body(self, pos, params, is_async):
        saved = (self.in_function, self.in_gen, self.in_async, self.strict, self.labels)
        self.in_function, self.in_gen, self.in_async, self.labels = True, False, is_async, []
        try:
            if self.is_p("{"):
                self.next()
                body = self.directives_and_statements(False)
                end = self.tok[3]
                self.next()
                expr = False
            else:
                e = self.assign()
                end = self.prev[3]
                body = [Node("Return", e.pos, arg=e)]
                expr = True
            strict = self.strict
        finally:
            self.in_function, self.in_gen, self.in_async, self.strict, self.labels = saved
        return Node("Function", pos, name=None, params=params, body=body, is_arrow=True, is_async=is_async,
                    is_gen=False, expr_body=expr, is_decl=False, strict=strict or saved[3], end=end,
                    kind="arrow", is_method=False)

    def class_(self, is_decl):
        pos = self.next()[2]
        name = None
        if self.tok[0] == "name" and not self.is_name("extends") and not self.is_p("{"):
            name = self.ident()
        elif is_decl:
            self.error("a class declaration needs a name")
        sup = None
        if self.eat_name("extends"):
            sup = self.lhs()
        self.expect("{")
        saved = self.strict
        self.strict = True
        members = []
        try:
            while not self.eat("}"):
                if self.eat(";"):
                    continue
                members.append(self.class_member())
        finally:
            self.strict = saved
        end = self.prev[3]
        return Node("Class", pos, name=name, sup=sup, members=members, is_decl=is_decl, end=end)

    def class_member(self):
        pos = self.tok[2]
        static = False
        if self.is_name("static"):
            st = self.save()
            self.next()
            if self.is_p("(") or self.is_p("=") or self.is_p(";") or self.is_p("}"):
                self.restore(st)
            elif self.is_p("{"):                          # static { ... }
                self.next()
                saved = (self.in_function, self.labels)
                self.in_function, self.labels = True, []
                body = []
                try:
                    while not self.eat("}"):
                        body.append(self.statement())
                finally:
                    self.in_function, self.labels = saved
                f = Node("Function", pos, name=None, params=[], body=body, is_arrow=False, is_async=False,
                         is_gen=False, expr_body=False, is_decl=False, strict=True, end=self.prev[3],
                         kind="method", is_method=True)
                return Node("Member", pos, kind="block", key=None, computed=False, value=f, static=True)
            else:
                static = True
        kind, key, computed, is_async, is_gen = self.method_head()
        if kind == "field":
            value = None
            if self.eat("="):
                saved = (self.in_function, self.labels)
                self.in_function, self.labels = True, []
                try:
                    e = self.assign()
                finally:
                    self.in_function, self.labels = saved
                value = Node("Function", e.pos, name=None, params=[], body=[Node("Return", e.pos, arg=e)],
                             is_arrow=False, is_async=False, is_gen=False, expr_body=True, is_decl=False,
                             strict=True, end=self.prev[3], kind="method", is_method=True)
            self.semicolon()
            return Node("Member", pos, kind="field", key=key, computed=computed, value=value, static=static)
        f = self.function_rest(pos, key.value if (key.t == "Str" and not computed) else None, is_async, is_gen,
                               True, "method")
        if not static and not computed and key.t == "Str" and key.value == "constructor" and kind == "method":
            kind = "constructor"
            f.kind = "ctor"
        return Node("Member", pos, kind=kind, key=key, computed=computed, value=f, static=static)

    def method_head(self):
        """The start of a method or field: (kind, key node, computed, async, generator).
        kind: method, get, set, field."""
        is_async = is_gen = False
        kind = "method"
        if self.is_name("async") and not self._next_ends_key():
            st = self.save()
            self.next()
            if self.tok[4]:
                self.restore(st)
            else:
                is_async = True
        if self.eat("*"):
            is_gen = True
        if not is_async and not is_gen and (self.is_name("get") or self.is_name("set")) and not self._next_ends_key():
            kind = self.next()[1]
        key, computed = self.prop_key()
        if kind == "method" and not is_async and not is_gen and not self.is_p("("):
            kind = "field"
        return kind, key, computed, is_async, is_gen

    def _next_ends_key(self):
        """Is the name here a key by itself (followed by ( = ; } , :)?"""
        st = self.save()
        self.next()
        r = self.tok[0] == "p" and self.tok[1] in ("(", "=", ";", "}", ",", ":") or self.tok[0] == "eof"
        self.restore(st)
        return r

    def prop_key(self):
        t = self.tok
        k = t[0]
        if k == "p" and t[1] == "[":
            self.next()
            e = self.assign()
            self.expect("]")
            return e, True
        self.next()
        if k == "name" or k == "priv":
            return Node("Str", t[2], value=t[1]), False
        if k == "str":
            return Node("Str", t[2], value=t[1]), False
        if k == "num":
            return Node("Num", t[2], value=t[1]), False
        self.error("bad property name", t[2])

    # ---- expressions ----
    def expression(self, no_in=False):
        e = self.assign(no_in)
        if self.is_p(","):
            items = [e]
            while self.eat(","):
                items.append(self.assign(no_in))
            return Node("Seq", e.pos, exprs=items)
        return e

    def assign(self, no_in=False):
        self.as_operand()
        t = self.tok
        pos = t[2]
        if t[0] == "name":
            v = t[1]
            if v == "yield" and self.in_gen:
                self.next()
                delegate = False
                arg = None
                if not self.tok[4]:
                    delegate = self.eat("*")
                    if delegate or not (self.tok[0] == "p" and self.tok[1] in (")", "]", "}", ",", ";", ":")
                                        or self.tok[0] == "eof"):
                        arg = self.assign(no_in)
                return Node("Yield", pos, arg=arg, delegate=delegate)
            if v == "async":
                st = self.save()
                self.next()
                if not self.tok[4]:
                    if self.tok[0] == "name" and self.tok[1] != "function":
                        name = self.tok[1]
                        st2 = self.save()
                        self.next()
                        if self.is_p("=>") and not self.tok[4]:
                            self.next()
                            return self.arrow_body(pos, [Node("Ident", pos, name=name)], True)
                        self.restore(st2)
                    elif self.is_p("("):
                        # async (a, b) => ... or a call to a function named async
                        st2 = self.save()
                        try:
                            saved_async = self.in_async
                            self.in_async = True
                            try:
                                params = self.params()
                            finally:
                                self.in_async = saved_async
                            if self.is_p("=>") and not self.tok[4]:
                                self.next()
                                return self.arrow_body(pos, params, True)
                        except JSSyntaxError:
                            pass
                        self.restore(st2)
                self.restore(st)
            elif v not in RESERVED:
                st = self.save()
                self.next()
                if self.is_p("=>") and not self.tok[4]:
                    self.next()
                    return self.arrow_body(pos, [Node("Ident", pos, name=v)], False)
                self.restore(st)
        left = self.conditional(no_in)
        if left.t == "ArrowParams":
            if not self.is_p("=>"):
                self.unexpected()
            self.next()
            return self.arrow_body(pos, left.params, False)
        t = self.tok
        if t[0] == "p" and t[1] in ASSIGN_OPS:
            op = t[1]
            if op == "=":
                target = self.to_pattern(left) if left.t in ("Array", "Object") else left
            else:
                target = left
            if target.t not in ("Ident", "Member", "ArrayPattern", "ObjectPattern"):
                self.error("invalid assignment target", left.pos)
            self.next()
            value = self.assign(no_in)
            return Node("Assign", pos, op=op, target=target, value=value)
        return left

    def conditional(self, no_in):
        test = self.binary(0, no_in)
        if test.t == "ArrowParams":
            return test
        if self.is_p("?"):
            self.next()
            cons = self.assign(False)
            self.expect(":")
            alt = self.assign(no_in)
            return Node("Cond", test.pos, test=test, cons=cons, alt=alt)
        return test

    def binary(self, min_prec, no_in):
        left = self.unary()
        if left.t == "ArrowParams":
            return left
        while True:
            self.as_operator()
            t = self.tok
            if t[0] == "p":
                op = t[1]
            elif t[0] == "name" and t[1] in ("instanceof", "in"):
                op = t[1]
                if op == "in" and no_in:
                    break
            else:
                break
            prec = BINARY.get(op)
            if prec is None or prec <= min_prec and not (op == "**" and prec == min_prec and False):
                if prec is None or prec <= min_prec:
                    break
            self.next()
            if op == "**":
                right = self.binary(prec - 1, no_in)         # right to left
            else:
                right = self.binary(prec, no_in)
            if op in ("&&", "||", "??"):
                left = Node("Logical", left.pos, op=op, l=left, r=right)
            else:
                left = Node("Binary", left.pos, op=op, l=left, r=right)
        return left

    def unary(self):
        self.as_operand()
        t = self.tok
        pos = t[2]
        if t[0] == "p":
            v = t[1]
            if v in ("!", "~", "+", "-"):
                self.next()
                arg = self.unary()
                return Node("Unary", pos, op=v, arg=arg)
            if v in ("++", "--"):
                self.next()
                arg = self.unary()
                if arg.t not in ("Ident", "Member"):
                    self.error("invalid increment target", pos)
                return Node("Update", pos, op=v, prefix=True, arg=arg)
        elif t[0] == "name":
            v = t[1]
            if v in ("typeof", "void", "delete"):
                self.next()
                arg = self.unary()
                return Node("Unary", pos, op=v, arg=arg)
            if v == "await" and (self.in_async or not self.in_function):
                st = self.save()
                self.next()
                if self.in_async or not (self.tok[0] == "p" and self.tok[1] in (")", ";", ",", "=", "]", "}", ".")):
                    arg = self.unary()
                    return Node("Await", pos, arg=arg)
                self.restore(st)
        e = self.postfix()
        return e

    def postfix(self):
        e = self.lhs()
        if e.t == "ArrowParams":
            return e
        self.as_operator()
        t = self.tok
        if t[0] == "p" and t[1] in ("++", "--") and not t[4]:
            if e.t not in ("Ident", "Member"):
                self.error("invalid increment target", e.pos)
            self.next()
            return Node("Update", e.pos, op=t[1], prefix=False, arg=e)
        return e

    def lhs(self):
        """Member accesses, calls, new, optional chains."""
        t = self.tok
        pos = t[2]
        if t[0] == "name" and t[1] == "new":
            e = self.new_expr()
        elif t[0] == "name" and t[1] == "super":
            self.next()
            e = Node("Super", pos)
        elif t[0] == "name" and t[1] == "import":
            self.next()
            if self.eat("."):
                self.ident()
                e = Node("Object", pos, props=[])           # import.meta: an empty object
            else:
                self.expect("(")
                arg = self.assign()
                self.eat(",")
                self.expect(")")
                e = Node("Import", pos, arg=arg)
        else:
            e = self.primary()
            if e.t == "ArrowParams":
                return e
        return self.chain(e, True)

    def chain(self, e, calls):
        optional_seen = False
        while True:
            self.as_operator()
            t = self.tok
            if t[0] == "p":
                v = t[1]
                if v == ".":
                    self.next()
                    nt = self.tok
                    if nt[0] == "name" or nt[0] == "priv":
                        self.next()
                        e = Node("Member", e.pos, obj=e, prop=Node("Str", nt[2], value=nt[1]), computed=False,
                                 optional=False)
                    else:
                        self.unexpected()
                    continue
                if v == "?.":
                    if not calls:
                        self.error("optional chain after new")
                    self.next()
                    optional_seen = True
                    if self.is_p("("):
                        args = self.arguments()
                        e = Node("Call", e.pos, callee=e, args=args, optional=True)
                    elif self.is_p("["):
                        self.next()
                        prop = self.expression()
                        self.expect("]")
                        e = Node("Member", e.pos, obj=e, prop=prop, computed=True, optional=True)
                    else:
                        nt = self.tok
                        if nt[0] not in ("name", "priv"):
                            self.unexpected()
                        self.next()
                        e = Node("Member", e.pos, obj=e, prop=Node("Str", nt[2], value=nt[1]), computed=False,
                                 optional=True)
                    continue
                if v == "[":
                    self.next()
                    prop = self.expression()
                    self.expect("]")
                    e = Node("Member", e.pos, obj=e, prop=prop, computed=True, optional=False)
                    continue
                if v == "(" and calls:
                    args = self.arguments()
                    e = Node("Call", e.pos, callee=e, args=args, optional=False)
                    continue
            elif t[0] == "tmpl":
                if optional_seen:
                    self.error("tagged template in an optional chain")
                q = self.template()
                e = Node("TaggedTmpl", e.pos, tag=e, quasi=q)
                continue
            break
        if optional_seen:
            e = Node("Chain", e.pos, e=e)
        return e

    def new_expr(self):
        pos = self.next()[2]
        if self.eat("."):
            self.ident()                                    # new.target
            return Node("NewTarget", pos)
        if self.is_name("new"):
            callee = self.new_expr()
        else:
            t = self.tok
            if t[0] == "name" and t[1] == "import":
                self.error("new import()")
            callee = self.primary()
        callee = self.chain(callee, False)
        args = self.arguments() if self.is_p("(") else []
        return Node("New", pos, callee=callee, args=args)

    def arguments(self):
        self.expect("(")
        args = []
        while not self.eat(")"):
            if self.eat("..."):
                args.append(Node("Spread", self.prev[2], arg=self.assign()))
            else:
                args.append(self.assign())
            if not self.is_p(")"):
                self.expect(",")
        return args

    def template(self):
        t = self.next()
        quasis = [t[1][0]]
        raws = [t[1][1]]
        exprs = []
        tail = t[1][2]
        while not tail:
            exprs.append(self.expression())
            if not self.is_p("}"):
                self.error("expected } in a template")
            # the template goes on right after the '}'
            self.lx.i = self.tok[3]
            nt = self.lx.template_continue()
            quasis.append(nt[1][0])
            raws.append(nt[1][1])
            tail = nt[1][2]
            self.prev = nt
            self.tok = self.lx.token(False)
        return Node("Tmpl", t[2], quasis=quasis, raws=raws, exprs=exprs)

    def primary(self):
        self.as_operand()
        t = self.tok
        k, v, pos = t[0], t[1], t[2]
        if k == "num":
            self.next()
            return Node("Num", pos, value=v)
        if k == "str":
            self.next()
            return Node("Str", pos, value=v)
        if k == "tmpl":
            return self.template()
        if k == "regex":
            self.next()
            return Node("Regex", pos, pattern=v[0], flags=v[1])
        if k == "priv":
            self.next()                                     # #x in obj
            return Node("Str", pos, value=v)
        if k == "name":
            if v == "function":
                return self.function(False, False, pos)
            if v == "async":
                st = self.save()
                self.next()
                if self.is_name("function") and not self.tok[4]:
                    self.restore(st)
                    return self.function(False, True, pos)
                self.restore(st)
            if v == "class":
                return self.class_(False)
            if v == "this":
                self.next()
                return Node("This", pos)
            if v == "null":
                self.next()
                return Node("Null", pos)
            if v == "true" or v == "false":
                self.next()
                return Node("Bool", pos, value=v == "true")
            if v == "new":
                return self.new_expr()
            if v in RESERVED:
                self.unexpected()
            self.next()
            return Node("Ident", pos, name=v)
        if k == "p":
            if v == "(":
                return self.paren()
            if v == "[":
                return self.array_literal()
            if v == "{":
                return self.object_literal()
        self.unexpected()

    def paren(self):
        pos = self.next()[2]
        if self.is_p(")"):
            self.next()
            if not self.is_p("=>"):
                self.unexpected()
            return Node("ArrowParams", pos, params=[])
        items = []
        rest = None
        while True:
            if self.eat("..."):
                rest = Node("Rest", self.prev[2], arg=self.binding_target())
                self.expect(")")
                break
            items.append(self.assign())
            if self.eat(")"):
                break
            self.expect(",")
            if self.is_p(")"):                            # (a, b,) =>
                self.next()
                rest = False
                break
        if rest is not None or self.is_p("=>") and not self.tok[4]:
            params = [self.to_pattern(e, True) for e in items]
            if rest:
                params.append(rest)
            return Node("ArrowParams", pos, params=params)
        if len(items) == 1:
            e = items[0]
            e.paren = True
            return e
        return Node("Seq", pos, exprs=items)

    def array_literal(self):
        pos = self.next()[2]
        elems = []
        while not self.eat("]"):
            if self.is_p(","):
                self.next()
                elems.append(None)                          # a hole
                continue
            if self.eat("..."):
                elems.append(Node("Spread", self.prev[2], arg=self.assign()))
            else:
                elems.append(self.assign())
            if not self.is_p("]"):
                self.expect(",")
        return Node("Array", pos, elems=elems)

    def object_literal(self):
        pos = self.next()[2]
        props = []
        while not self.eat("}"):
            ppos = self.tok[2]
            if self.eat("..."):
                props.append(Node("Prop", ppos, kind="spread", key=None, computed=False, value=self.assign()))
            else:
                t = self.tok
                kind, key, computed, is_async, is_gen = self.method_head()
                if kind in ("get", "set") or is_async or is_gen or (kind == "field" and self.is_p("(")) or \
                        self.is_p("("):
                    f = self.function_rest(ppos, None if computed else str(key.value), is_async, is_gen, True,
                                           "method")
                    props.append(Node("Prop", ppos, kind=kind if kind in ("get", "set") else "init", key=key,
                                      computed=computed, value=f, method=True))
                elif self.eat(":"):
                    props.append(Node("Prop", ppos, kind="init", key=key, computed=computed, value=self.assign(),
                                      method=False))
                elif t[0] == "name" and not computed:
                    name = t[1]
                    if name in RESERVED and name not in ("enum",):
                        self.error("unexpected keyword %s" % name)
                    value = Node("Ident", t[2], name=name)
                    if self.is_p("="):                      # {a = 1} = obj: a pattern only
                        self.next()
                        value = Node("ShorthandInit", t[2], target=value, default=self.assign())
                    props.append(Node("Prop", ppos, kind="init", key=key, computed=False, value=value,
                                      method=False, shorthand=True))
                else:
                    self.unexpected()
            if not self.is_p("}"):
                self.expect(",")
        return Node("Object", pos, props=props)

    # ---- expressions as patterns (destructuring) ----
    def to_pattern(self, e, binding=False):
        t = e.t
        if t == "Ident":
            return e
        if t == "Member" and not binding:
            return e
        if t == "Assign" and e.op == "=":
            return Node("AssignPattern", e.pos, target=self.to_pattern(e.target, binding), default=e.value)
        if t == "AssignPattern":
            return e
        if t == "ShorthandInit":
            return Node("AssignPattern", e.pos, target=e.target, default=e.default)
        if t == "Array":
            elems = []
            for k, x in enumerate(e.elems):
                if x is None:
                    elems.append(None)
                elif x.t == "Spread":
                    elems.append(Node("Rest", x.pos, arg=self.to_pattern(x.arg, binding)))
                else:
                    elems.append(self.to_pattern(x, binding))
            return Node("ArrayPattern", e.pos, elems=elems)
        if t == "Object":
            props = []
            for p in e.props:
                if p.kind == "spread":
                    props.append(Node("Rest", p.pos, arg=self.to_pattern(p.value, binding)))
                elif p.kind == "init" and not getattr(p, "method", False):
                    props.append((p.key, p.computed, self.to_pattern(p.value, binding)))
                else:
                    self.error("invalid destructuring pattern", p.pos)
            return Node("ObjectPattern", e.pos, props=props)
        if t in ("ArrayPattern", "ObjectPattern", "Rest"):
            return e
        self.error("invalid destructuring target", e.pos)


def parse(src):
    return Parser(src).parse_program()
