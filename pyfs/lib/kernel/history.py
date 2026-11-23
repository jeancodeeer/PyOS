# Console command history kept on disk, so Up-arrow works across reboots.
#
# Entries are separated by \x1e (multi-line statements stay one entry).
# New entries are appended while the console waits for input (the idle
# hook), when nothing else is using the console thread.
import _kernel

PATH = "/disk/.history"
KEEP = 100
SEP = "\x1e"
_last = None


def load(path=PATH):
    """Read the saved history into the console. Returns how many entries."""
    global _last
    try:
        with open(path) as f:
            saved = [e for e in f.read().split(SEP) if e.strip()]
    except OSError:
        return 0
    recent = saved[-KEEP:]
    for entry in recent:                     # oldest first, so the newest ends on top
        _kernel.history_add(entry)
    _last = recent[-1] if recent else None
    if len(saved) > 4 * KEEP:                # keep the file from growing forever
        with open(path, "w") as f:
            f.write(SEP.join(recent) + SEP)
    return len(recent)


def save_new(path=PATH):
    """Append entries typed since the last save."""
    global _last
    current = _kernel.history()             # newest first
    if not current or current[0] == _last:
        return
    new = []
    for entry in current:
        if entry == _last:
            break
        new.append(entry)
    with open(path, "a") as f:
        for entry in reversed(new):
            f.write(entry + SEP)
    _last = current[0]


def enable(path=PATH):
    """Load the saved history and keep saving new commands."""
    n = load(path)
    _kernel.idle_hook(lambda: save_new(path))
    return n
