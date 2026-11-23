# Cooperative multitasking.
#
# A task is a generator. Each `yield` gives the CPU back; `yield 250` also
# sleeps for about 250 ms. Tasks are stepped from the timer interrupt, so
# they keep running while you type at the prompt or run other code.
import sys
from kernel import timer

tasks = []
_next_id = 1


class Task:
    def __init__(self, gen, name):
        global _next_id
        self.id = _next_id
        _next_id += 1
        self.gen = gen
        self.name = name
        self.wake = 0
        self.steps = 0

    def __repr__(self):
        return "<Task %d %s steps=%d>" % (self.id, self.name, self.steps)


def spawn(fn, name=None):
    """Start a background task from a generator (or generator function)."""
    gen = fn() if callable(fn) else fn
    task = Task(gen, name or getattr(fn, "__name__", "task"))
    tasks.append(task)
    timer.subscribe(_tick)
    return task


def kill(task_id):
    for t in tasks:
        if t.id == task_id:
            tasks.remove(t)
            return True
    return False


def _tick():
    now = timer.ticks()
    for t in tasks[:]:
        if t.wake > now:
            continue
        try:
            delay = next(t.gen)
        except StopIteration:
            tasks.remove(t)
            continue
        except Exception as e:
            from kernel import errors
            errors.show(e, "task %d (%s) died:" % (t.id, t.name))
            tasks.remove(t)
            continue
        t.steps += 1
        t.wake = now + (max(1, delay * timer.HZ // 1000) if delay else 1)
