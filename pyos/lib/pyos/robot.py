# A robot that uses PyOS like a person: it moves the mouse and types on
# the keyboard through the same path as the real devices (kernel.mouse and
# kernel.keyboard), so the desktop and the apps cannot tell the difference.
# The guided tour (pyos/tour.py) and the video are made with it.
#
#   from pyos.robot import Robot
#   r = Robot()
#   r.dock("calc")                    # click the Calculadora icon in the dock
#   r.button(r.window("Calculadora"), "7")
#   r.type("hola")  ;  r.press("enter")  ;  r.combo("ctrl", "s")
#
# It must run in a thread of its own while the desktop runs.
import time
from kernel import mouse, keyboard

# keys that have no character: (scancode, extended?)
SPECIAL = {"enter": (0x1C, 0), "esc": (0x01, 0), "backspace": (0x0E, 0), "tab": (0x0F, 0), "space": (0x39, 0),
           "shift": (0x2A, 0), "ctrl": (0x1D, 0), "alt": (0x38, 0), "up": (0x48, 1), "down": (0x50, 1),
           "left": (0x4B, 1), "right": (0x4D, 1), "delete": (0x53, 1), "home": (0x47, 1), "end": (0x4F, 1),
           "pageup": (0x49, 1), "pagedown": (0x51, 1), "f2": (0x3C, 0), "f3": (0x3D, 0), "f5": (0x3F, 0)}


def _wm():
    from desktop import wm
    return wm.wm


class Robot:
    def __init__(self, speed=1.0):
        self.speed = speed          # 2.0 = twice as fast
        self.buttons = 0

    # ---- time ----
    def wait(self, ms):
        time.sleep_ms(int(ms / self.speed))

    # ---- the mouse ----
    def pos(self):
        return mouse.x, mouse.y

    def move(self, x, y, ms=350):
        """Glide to (x, y), easing in and out like a hand does."""
        x0, y0 = mouse.x, mouse.y
        steps = max(1, int(ms / self.speed / 16))
        for i in range(1, steps + 1):
            t = i / steps
            t = t * t * (3 - 2 * t)                      # smooth start and stop
            nx, ny = int(x0 + (x - x0) * t), int(y0 + (y - y0) * t)
            mouse.move(nx - mouse.x, ny - mouse.y, self.buttons)
            time.sleep_ms(16)

    BITS = {1: 1, 2: 4, 3: 2}       # left, middle, right: as a PS/2 mouse reports them

    def down(self, button=1):
        self.buttons |= self.BITS[button]
        mouse.move(0, 0, self.buttons)

    def up(self, button=1):
        self.buttons &= ~self.BITS[button]
        mouse.move(0, 0, self.buttons)

    def click(self, x=None, y=None, button=1, double=False, ms=350):
        if x is not None:
            self.move(x, y, ms)
            self.wait(80)
        for _ in range(2 if double else 1):
            self.down(button)
            time.sleep_ms(60)
            self.up(button)
            time.sleep_ms(90)
        self.wait(150)

    def drag(self, points, ms=250):
        """Press at the first point, glide through the others, let go."""
        self.move(points[0][0], points[0][1])
        self.down()
        for x, y in points[1:]:
            self.move(x, y, ms)
        self.up()
        self.wait(120)

    # ---- the keyboard ----
    def _hit(self, code, ext, down):
        if ext:
            keyboard._key(0xE0)
        keyboard._key(code if down else code | 0x80)

    def press(self, name, hold_ms=60):
        code, ext = SPECIAL[name]
        self._hit(code, ext, True)
        time.sleep_ms(hold_ms)
        self._hit(code, ext, False)
        self.wait(60)

    def hold(self, name, ms):
        """Keep a key down for a while (walking in a game)."""
        code, ext = SPECIAL.get(name, (None, 0)) if name in SPECIAL else (self._code(name)[0], 0)
        self._hit(code, ext, True)
        time.sleep_ms(int(ms))
        self._hit(code, ext, False)

    def combo(self, *names):
        """Ctrl+S, Ctrl+Q...: modifiers down, the key, modifiers up."""
        mods, key = names[:-1], names[-1]
        for m in mods:
            self._hit(SPECIAL[m][0], SPECIAL[m][1], True)
        if key in SPECIAL:
            self.press(key)
        else:
            code, _ = self._code(key)
            self._hit(code, 0, True)
            self._hit(code, 0, False)
        for m in reversed(mods):
            self._hit(SPECIAL[m][0], SPECIAL[m][1], False)
        self.wait(100)

    def _code(self, ch):
        """The scancode that types ch, and whether it needs Shift."""
        for code, entry in keyboard.keys.items():
            if entry and entry[0] == ch:
                return code, False
        for code, entry in keyboard.keys.items():
            if entry and entry[1] == ch:
                return code, True
        return None, False

    def type(self, text, ms_per_key=55):
        for ch in text:
            if ch == "\n":
                self.press("enter")
                continue
            code, shift = self._code(ch)
            if code is None:
                continue
            if shift:
                self._hit(0x2A, 0, True)
            self._hit(code, 0, True)
            self._hit(code, 0, False)
            if shift:
                self._hit(0x2A, 0, False)
            time.sleep_ms(int(ms_per_key / self.speed))

    # ---- the desktop ----
    def say(self, text, ms=3500):
        """A subtitle at the bottom of the screen (for the tour and videos)."""
        _wm().subtitle(text, ms)

    def dock(self, name):
        panel, items = _wm().dock_rects()
        for n, r in items:
            if n == name:
                self.click(r.centerx, r.centery)
                return True
        return False

    def launcher(self, label, name=None):
        """Open the launcher with the PyOS button, search, and click the app
        (the one called `name`, or the first that matches)."""
        self.click(40, 12)
        self.wait(500)
        self.type(label.lower(), 90)
        self.wait(600)
        la = _wm().launcher
        cells = la.cells() if la else []
        for n, lab, cell in cells:
            if n == name or (name is None and lab.lower() == label.lower()):
                self.click(cell.centerx, cell.centery)
                break
        else:
            self.press("enter")
        self.wait(900)

    def fullscreen(self, label, name=None, play=None, ms=6000):
        """Open a full-screen program, let `play(robot)` use it, close it with Esc."""
        self.launcher(label, name)
        w = _wm()
        end = time.ticks_add(time.ticks_ms(), 15000)
        while not getattr(w, "fullscreen", None) and time.ticks_diff(end, time.ticks_ms()) > 0:
            time.sleep_ms(100)
        if not getattr(w, "fullscreen", None):
            return False
        if play:
            play(self)
        else:
            self.wait(ms)
        self.press("esc")
        end = time.ticks_add(time.ticks_ms(), 10000)
        while getattr(w, "fullscreen", None) and time.ticks_diff(end, time.ticks_ms()) > 0:
            time.sleep_ms(100)
        return True

    def clear(self, field):
        """Empty a text field with Backspace, as a person would."""
        for _ in range(len(getattr(field, "text", ""))):
            self._hit(0x0E, 0, True)
            self._hit(0x0E, 0, False)
            time.sleep_ms(15)

    def window(self, title, timeout_ms=8000):
        """The desktop window whose title contains `title` (it may still be opening)."""
        end = time.ticks_add(time.ticks_ms(), timeout_ms)
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            for w in reversed(_wm().windows):
                if title.lower() in (w.title or "").lower():
                    return w
            time.sleep_ms(100)
        return None

    def at(self, win, x, y):
        """Screen coordinates of a point in a window's client area."""
        ox, oy = win.client_origin()
        return ox + x, oy + y

    def click_in(self, win, x, y, **kw):
        sx, sy = self.at(win, x, y)
        self.click(sx, sy, **kw)

    def widgets(self, win):
        """Every ui widget (Button, Field...) the window's app keeps."""
        from desktop import ui
        out = []
        seen = set()

        def walk(obj, depth):
            if depth > 2 or id(obj) in seen:
                return
            seen.add(id(obj))
            if isinstance(obj, ui.Form):
                for w in obj.widgets:
                    out.append(w)
            elif isinstance(obj, (list, tuple)):
                for o in obj:
                    walk(o, depth + 1)
            elif isinstance(obj, dict):
                for o in obj.values():
                    walk(o, depth + 1)
        app = win.app
        for name in dir(app):
            if not name.startswith("__"):
                try:
                    walk(getattr(app, name), 0)
                except Exception:
                    pass
        return out

    def button(self, win, label):
        """Click the button of a window with this label."""
        for w in self.widgets(win):
            if getattr(w, "label", None) == label and hasattr(w, "rect"):
                r = w.rect
                self.click_in(win, r.centerx, r.centery)
                return True
        return False

    def close(self, win):
        """The red button on the title bar."""
        if win is None:
            return
        r = win.buttons()[0]
        self.click(r.centerx, r.centery)
        self.wait(400)

    def title_bar(self, win):
        return win.x + win.w // 2, win.y + 14
