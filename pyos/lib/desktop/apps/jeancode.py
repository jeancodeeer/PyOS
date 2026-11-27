# JeanCode in a window of the desktop: the same chat app as the full-screen
# "jeancode" command, drawn into the window, so it can be moved, minimized,
# maximized and resized like any other app.
from desktop.wm import App


class JeanCode(App):
    title = "JeanCode"
    size = (860, 560)

    def __init__(self, win):
        App.__init__(self, win)
        from jeancode import app
        self.jc = app.App(surface=win.surf)

    def tick(self, now):
        self.jc.step()
        return self.jc.dirty                  # replies arrive from another thread: redraw as they come

    def draw(self, surf):
        self.jc.screen = surf                 # a new Surface after a resize or maximize
        self.jc.draw()
        self.jc.dirty = False

    def resized(self, w, h):
        self.jc.dirty = True

    def event(self, ev, pos):
        if not self.jc.handle(ev):            # Ctrl+Q closes the window
            from desktop import wm
            wm.wm.later(lambda: wm.wm.close(self.win))
        return True

    def close(self):
        self.jc.stop = True                   # a reply still coming stops
        try:
            self.jc.save_chat()
        except Exception:
            pass
        return True
