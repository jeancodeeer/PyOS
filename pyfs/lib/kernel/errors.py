# Readable error reports: the usual traceback plus, under every frame, the
# line of source code that was running.
#
# install() makes this the format for every error reported to the console,
# including errors at the >>> prompt (for those the line comes from the
# command history). run(), threads, tasks and boot scripts use show().
import io
import sys
import _kernel

_cache = {}


def _source(path, number, typed):
    if path == "<stdin>":
        if not typed:
            return None
        from kernel import lineedit
        if lineedit.last_statement:
            lines = lineedit.last_statement.split("\n")
        else:
            hist = _kernel.history()
            lines = hist[0].split("\n") if hist else []
    elif path.startswith("<"):
        return None
    else:
        lines = _cache.get(path)
        if lines is None:
            try:
                with open(path) as f:
                    lines = f.read().split("\n")
            except Exception:
                return None
            if len(_cache) > 8:
                _cache.clear()
            _cache[path] = lines
    if 0 < number <= len(lines):
        return lines[number - 1].strip()
    return None


def format(exc, typed=False):
    """The traceback of `exc` with source lines; typed=True also shows the
    line for <stdin> frames (what was just entered at the prompt)."""
    buf = io.StringIO()
    sys.print_exception(exc, buf)
    out = []
    for line in buf.getvalue().rstrip("\n").split("\n"):
        out.append(line)
        s = line.strip()
        if s.startswith('File "') and ", line " in s:
            try:
                path = s[6:s.index('"', 6)]
                number = int(s.split(", line ")[1].split(",")[0])
            except (ValueError, IndexError):
                continue
            src = _source(path, number, typed)
            if src:
                out.append("    \x1b[93m> " + src + "\x1b[0m")
    return "\n".join(out)


def show(exc, title=None):
    if title:
        print("\x1b[91m" + title + "\x1b[0m")
    print(format(exc))
    _cache.clear()                      # files may change before the next error


def _console_report(exc):
    print(format(exc, typed=True))
    _cache.clear()


def install():
    """Use this format for every error the console reports."""
    _kernel.exc_hook(_console_report)


def uninstall():
    _kernel.exc_hook(None)
