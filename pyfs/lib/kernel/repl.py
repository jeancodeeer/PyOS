# The interactive console: a read-eval-print loop that behaves like
# CPython's own (the 3.13 one, `python` with no arguments).
#
# What it does, the CPython way:
#   - banner:  Python <version> ... / Type "help", "copyright", ...
#   - prompts: sys.ps1 / sys.ps2 (assign to change them; str() is taken
#     each time, so an object with __str__ gives a dynamic prompt)
#   - blocks are edited as a whole: Enter inside an unfinished statement
#     opens the next line (auto-indented); a blank line runs it; Up/Down
#     move between its lines and recall whole blocks from the history
#   - results are shown by displayhook() (repr, None hidden) and kept in _
#   - errors are shown by excepthook() as a traceback with source lines
#   - exit / quit (with or without the parentheses), Ctrl-D on an empty
#     line: leave the interpreter -- here that is a soft reboot
#   - Ctrl-C: KeyboardInterrupt, the line is dropped
#   - F1 interactive help, F2 history browser, F3 paste mode (also Ctrl-E)
#   - copyright, credits, license
#
# Replace displayhook / excepthook in this module to change how results
# and errors are shown (MicroPython's sys does not take new attributes).
import sys
import builtins
import _kernel
from kernel import VERSION, lineedit

# key codes the line editor returns (besides finished text)
CTRL_A, CTRL_B, CTRL_C, CTRL_D, CTRL_E = 1, 2, 3, 4, 5
F1, F2, F3 = 0xF1, 0xF2, 0xF3

# colours like CPython 3.13 (PYTHON_COLORS); colour = False turns them off
colour = True
C_PROMPT, C_ERROR, C_OFF = "\x1b[1;35m", "\x1b[1;35m", "\x1b[0m"

EXIT = 0          # what run() returns: soft reboot
RAW_REPL = 1      # ... or: switch to MicroPython's raw REPL (for tools)


# ---- the objects CPython's site module puts in builtins ----

class Quitter:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return "Use %s() or Ctrl-D (i.e. EOF) to exit" % self.name

    def __call__(self, code=None):
        raise SystemExit(code)


class _Printer:
    def __init__(self, name, text):
        self.name, self.text = name, text

    def __repr__(self):
        return self.text

    def __call__(self):
        print(self.text)


COPYRIGHT = """Copyright (c) 2013-2025 Damien P. George and MicroPython contributors.
All Rights Reserved.

Python language: Copyright (c) 2001 Python Software Foundation.
PyKernel: the kernel in /lib/kernel and the Rust layer under it."""
CREDITS = """Thanks to the MicroPython team for the Python engine, and to the
CPython developers for the language and the interactive console this
one imitates."""
LICENSE = """MicroPython is released under the MIT license.
Type help('modules') to see the modules in this system."""


def _version():
    impl = sys.implementation
    mpy = ".".join(str(n) for n in impl.version[:3])
    lang = sys.version.split(";")[0]
    from kernel.arch import NAME
    return "Python %s (MicroPython v%s, PyKernel %s) [%s] on %s" % (lang, mpy, VERSION, NAME, sys.platform)


def banner():
    print(_version())
    print('Type "help", "copyright", "credits" or "license" for more information.')


# ---- showing results and errors ----

def displayhook(value):
    """Called with the value of every expression typed at the prompt."""
    if value is None:
        return
    builtins._ = None                    # as CPython: _ is unset while repr() runs
    text = repr(value)
    if text:                             # a command prints its own output
        print(text)
    builtins._ = value


def excepthook(exc):
    """Called with every exception that reaches the prompt."""
    from kernel import errors
    report = errors.format(exc, typed=True)
    errors._cache.clear()
    if colour:
        head, _, last = report.rpartition("\n")
        report = (head + "\n" if head else "") + C_ERROR + last + C_OFF
    print(report)


def _repl_print(value):                  # what the compiler calls for "single" input
    displayhook(value)


# ---- reading ----

def _prompt(name, default):
    try:
        return str(getattr(sys, name))
    except AttributeError:
        return default


def _main():
    import __main__
    return __main__.__dict__


def read():
    """Read one statement (possibly several lines). Returns the text or a
    key code."""
    ps1, ps2 = _prompt("ps1", ">>> "), _prompt("ps2", "... ")
    editor = lineedit.LineEditor(ps1, "", shell=True, ps2=ps2,
                                 prompt_colour=C_PROMPT if colour else "")
    lineedit.active = editor
    try:
        return editor.run()
    finally:
        lineedit.active = None


def paste_mode():
    """F3 / Ctrl-E: take lines exactly as given (no auto-indent) until F3
    or Ctrl-D, then run them as one block. Ctrl-C cancels."""
    print("(paste mode: F3 or Ctrl-D runs it, Ctrl-C cancels)")
    lines = []
    while True:
        editor = lineedit.LineEditor("(paste) ", "")
        editor.fkeys = True
        lineedit.active = editor
        try:
            line = editor.run()
        finally:
            lineedit.active = None
        if line in (F3, CTRL_D, CTRL_E):
            print()
            break
        if line == CTRL_C:
            print("\nKeyboardInterrupt")
            return
        if isinstance(line, str):
            lines.append(line)
    source = "\n".join(lines)
    if source.strip():
        _kernel.history_add(source)
        return execute(source, whole_file=True)


def history_browser():
    """F2: every earlier statement, oldest first, without prompts."""
    entries = list(reversed(_kernel.history()))
    print()
    if not entries:
        print("(no history yet)")
        return
    from kernel import shell
    shell.more(text="\n".join(entries) + "\n")


def help_utility():
    """F1 or help(): CPython-style interactive help."""
    from kernel import shell
    print("\nWelcome to the PyKernel help utility! Enter the name of a command,")
    print('module, keyword or any object (e.g. "ls", "kernel.console", "str.split").')
    print('"commands", "modules" and "keywords" list them. "q" or Enter leaves.\n')
    while True:
        editor = lineedit.LineEditor("help> ", "")
        topic = editor.run()
        if not isinstance(topic, str):
            print()
            return
        topic = topic.strip()
        if topic in ("", "q", "quit", "exit"):
            print("\nYou are now leaving help and returning to the Python interpreter.")
            return
        try:
            if topic == "commands":
                shell.help()
            elif topic == "keywords":
                print(" ".join(sorted(lineedit.KEYWORDS)))
            elif topic == "modules":
                shell._builtin_help("modules")
            elif topic in lineedit.KEYWORDS:
                print("%s: a Python keyword (see the language reference)" % topic)
            elif topic in shell._commands:
                shell.help(shell._commands[topic])
            else:
                try:
                    obj = eval(topic, _main())
                except Exception:
                    obj = __import__(topic)
                shell.help(obj)
        except Exception as e:
            print("No Python documentation found for %r (%s)" % (topic, e))


# ---- running ----

class _Leave(Exception):
    pass


def _graphics_back_to_text():
    """A program left a graphics mode on (pygame without pygame.quit()):
    the prompt needs the text screen back."""
    from kernel import video
    if video.current is None:
        return
    pg = sys.modules.get("pygame.display")
    if pg is not None:
        pg.quit()
    else:
        video.text_mode()


def execute(source, whole_file=False):
    """Run what was typed. Returns EXIT if it asked to leave."""
    lineedit.last_statement = source
    exc = _kernel.repl_exec(source + "\n", whole_file)
    _graphics_back_to_text()
    if exc is None:
        return None
    if isinstance(exc, SystemExit):
        return EXIT
    excepthook(exc)
    return None


def _bare_command(word):
    """exit / quit / clear typed without parentheses (CPython 3.13)."""
    if word in _main():                  # the user's own variable wins
        return None
    if word in ("exit", "quit"):
        return EXIT
    if word == "clear":
        from kernel import keyboard
        keyboard._clear_screen()
        return False
    return None


def one():
    """Read and run one statement. Returns EXIT / RAW_REPL to stop."""
    text = read()
    if isinstance(text, int):
        if text == CTRL_D:
            print()
            return EXIT
        if text == CTRL_C:
            print("\nKeyboardInterrupt")
        elif text == CTRL_A:
            print()
            return RAW_REPL
        elif text == CTRL_B:
            print()
            banner()
        elif text in (F3, CTRL_E):
            print()
            return paste_mode()
        elif text == F1:
            help_utility()
        elif text == F2:
            history_browser()
        return None
    word = text.strip()
    if not word:
        return None
    _kernel.history_add(text)
    bare = _bare_command(word)
    if bare is not None:
        return bare if bare is not False else None
    return execute(text)


def install():
    builtins.exit = Quitter("exit")
    builtins.quit = Quitter("quit")
    builtins.copyright = _Printer("copyright", COPYRIGHT)
    builtins.credits = _Printer("credits", CREDITS)
    builtins.license = _Printer("license", LICENSE)
    builtins.__repl_print__ = _repl_print
    _kernel.repl(run)


def run():
    """The console loop (the VM calls this; see install())."""
    banner()
    while True:
        try:
            result = one()
        except KeyboardInterrupt:
            print("\nKeyboardInterrupt")
            continue
        except Exception as e:           # a bug in the console itself
            print("\x1b[91mconsole error:\x1b[0m")
            sys.print_exception(e)
            continue
        if result is not None:
            return result
