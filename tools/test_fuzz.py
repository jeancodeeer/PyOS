"""Every app of the desktop gets random clicks, drags, wheel turns, keys and
shortcuts (in QEMU); any error an app raises is reported, with its traceback.

    python tools/test_fuzz.py [seed] [events per app]
"""
import sys
import time
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402
from run import make_disk  # noqa: E402

GUEST = r'''
import pygame, random
from pygame.locals import *
from desktop import wm, apps
random.seed(%(seed)d)
names = [n for n in apps.names() if n not in ('jeancode',) and apps.info(n)['mode'] == 'window']
report = []
KEYS = [K_RETURN, K_BACKSPACE, K_DELETE, K_TAB, K_ESCAPE, K_LEFT, K_RIGHT, K_UP, K_DOWN, K_HOME, K_END,
        K_PAGEUP, K_PAGEDOWN, K_SPACE, K_F2, K_F5, K_a, K_z, K_c, K_v, K_x, K_s, K_n, K_1]
def post_random(w):
    x0, y0 = w.x, w.y
    r = random.random()
    px = x0 + random.randint(-5, w.w + 5)
    py = y0 + random.randint(-30, w.h + 5)
    if r < 0.35:
        pygame.event.post(pygame.event.Event(MOUSEBUTTONDOWN, pos=(px, py), button=1))
        pygame.event.post(pygame.event.Event(MOUSEBUTTONUP, pos=(px, py), button=1))
    elif r < 0.45:
        pygame.event.post(pygame.event.Event(MOUSEBUTTONDOWN, pos=(px, py), button=3))
        pygame.event.post(pygame.event.Event(MOUSEBUTTONUP, pos=(px, py), button=3))
    elif r < 0.55:
        q = (px + random.randint(-80, 80), py + random.randint(-80, 80))
        pygame.event.post(pygame.event.Event(MOUSEBUTTONDOWN, pos=(px, py), button=1))
        pygame.event.post(pygame.event.Event(MOUSEMOTION, pos=q, rel=(q[0] - px, q[1] - py), buttons=(1, 0, 0)))
        pygame.event.post(pygame.event.Event(MOUSEBUTTONUP, pos=q, button=1))
    elif r < 0.62:
        pygame.event.post(pygame.event.Event(MOUSEWHEEL, x=0, y=random.choice((-3, -1, 1, 3))))
    else:
        k = random.choice(KEYS)
        mod = KMOD_CTRL if random.random() < 0.2 else 0
        ch = '' if k > 255 or mod else chr(k)
        pygame.event.post(pygame.event.Event(KEYDOWN, key=k, mod=mod, unicode=ch))
        pygame.event.post(pygame.event.Event(KEYUP, key=k, mod=mod))
        if random.random() < 0.3:
            pygame.event.post(pygame.event.Event(TEXTINPUT, text=random.choice('ab1 .-/')))
state = {'i': 0, 'n': 0, 'w': None}
def step():
    if state['w'] is None or state['n'] >= %(events)d or state['w'] not in wm.wm.windows:
        for w in list(wm.wm.windows):
            wm.wm.close(w)
        if state['i'] >= len(names):
            wm.wm.running = False
            return
        name = names[state['i']]
        state['i'] += 1
        state['n'] = 0
        report.append(name)
        try:
            state['w'] = wm.wm.launch(name)
        except Exception as e:
            wm.wm.error(e)
            state['w'] = None
        if state['w'] is None:
            report.append('!no window')
    else:
        for _ in range(3):
            post_random(state['w'])
            state['n'] += 1
    wm.SCRIPT.append((0, step))
wm.SCRIPT.append((1500, step))
'''


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    events = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    with tempfile.TemporaryDirectory() as tmp:
        m = T.Machine(make_disk(Path(tmp) / "d.img"))
        try:
            m.until(T.PROMPT, 120)
            src = GUEST % {"seed": seed, "events": events}
            piece = ""
            for line in src.splitlines(True):
                if len(piece) + len(line) > 500 and not line.startswith((" ", "\t")):
                    m.cmd("exec(%r)" % piece, 20)
                    piece = ""
                piece += line
            if piece:
                m.cmd("exec(%r)" % piece, 20)
            m.send(b"desktop\r")
            live = ROOT / "build" / "fuzz_live.log"
            end = time.time() + 1800
            while True:
                try:
                    m.until(T.PROMPT, 15)
                    break
                except TimeoutError:
                    live.write_bytes(bytes(m.log))
                    if time.time() > end:
                        raise
            time.sleep(2)
            m.cmd("", 10)
            out = m.cmd("print(report)", 20)
            print("apps:", out.strip().splitlines()[-1][:600])
            out = m.cmd("from kernel import log; print('\\n'.join(l for l in log.lines() if 'desktop:' in l))", 30)
            errors = [l for l in out.splitlines() if "desktop:" in l]
            text = m.log.decode(errors="replace")
            print("errors:", len(errors))
            for e in errors:
                print("  " + e[:900])
            (ROOT / "build" / "fuzz.log").write_text(text)
            return not errors
        finally:
            m.proc.kill()


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
