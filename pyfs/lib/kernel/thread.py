# Preemptive threads.
#
# Threads are real kernel threads: each has its own stack and the timer
# interrupt takes the CPU away from one that will not give it up. The
# switching itself is in the Rust layer; this module is the friendly face
# of the standard `_thread` module and keeps the names shown by `ps`.
#
#   t = thread.start(worker, arg1, arg2, name="worker")
#   lock = thread.Lock()        # with lock: ...
import sys
import _thread
import _kernel

names = {0: "main (console)"}
STATES = {1: "ready", 2: "asleep", 3: "running"}

Lock = _thread.allocate_lock
current = _thread.get_ident


def start(fn, *args, name=None, stack=0):
    """Run fn(*args) in a new thread; returns its id."""
    label = name or getattr(fn, "__name__", "thread")

    def body():
        me = _thread.get_ident()
        names[me] = label
        try:
            fn(*args)
        except SystemExit:
            pass                                    # thread.kill()
        except KeyboardInterrupt:
            print("thread %d (%s) interrupted" % (me, label))
        except Exception as e:
            from kernel import errors
            errors.show(e, "thread %d (%s) died:" % (me, label))
        finally:
            names.pop(me, None)

    if stack:
        _thread.stack_size(stack)
    try:
        return _thread.start_new_thread(body, ())
    finally:
        if stack:
            _thread.stack_size(0)


def kill(tid):
    """Stop thread `tid` (it raises SystemExit at its next Python bytecode).

    A thread blocked waiting for a lock stops once it gets the lock, and a
    thread inside a @micropython.native/viper loop only when that returns.
    Locks it holds are not released unless it used `with lock:`."""
    if tid == 0:
        raise ValueError("thread 0 is the console; use Ctrl-C there")
    _kernel.thread_raise(tid, SystemExit)


def interrupt(tid):
    """Ctrl-C for one thread: raise KeyboardInterrupt in thread `tid`."""
    _kernel.thread_raise(tid, KeyboardInterrupt)


def info():
    """[(id, name, state, ticks, switches)] for every live thread."""
    return [(i, names.get(i, "?"), STATES.get(s, "?"), ticks, sw) for i, s, ticks, sw in _kernel.threads()]


def time_slice(ticks):
    """Timer ticks each thread runs before being preempted (0 = never)."""
    from kernel import timer
    _kernel.preempt(timer.VECTOR, ticks)
