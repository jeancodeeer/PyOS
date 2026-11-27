# System monitor: processes, threads, memory, network and the kernel log.
import gc
import pygame
from desktop import theme as T, ui
from desktop.wm import App


class Monitor(App):
    title = "Monitor del sistema"
    size = (640, 440)

    def __init__(self, win):
        App.__init__(self, win)
        self.tab = 0
        self.tabs = ["Procesos", "Rendimiento", "Red", "Registro"]
        self.form = ui.Form()
        for i, name in enumerate(self.tabs):
            self.form.add(ui.Button((8 + 104 * i, 6, 100, 24), name, lambda i=i: self.set_tab(i)))
        self.list = self.form.add(ui.ListBox((8, 38, 620, 320), []))
        self.kill_btn = self.form.add(ui.Button((8, 400, 140, 24), "Terminar proceso", self.kill))
        self.view = self.form.add(ui.TextView((8, 38, 620, 360), []))
        self.next = 0
        self.history = []                      # RAM in use, one point a second
        self.cpu = []                          # desktop CPU load, one point a second
        self.lines_perf = []
        self.message = ""
        self.set_tab(0)

    def set_tab(self, i):
        self.tab = i
        self.list.visible = i == 0
        self.kill_btn.visible = i == 0
        self.view.visible = i not in (0, 1)
        self.next = 0

    def resized(self, w, h):
        self.list.rect.size = (w - 16, h - 80)
        self.view.rect.size = (w - 16, h - 46)
        self.kill_btn.rect.y = h - 32

    def refresh(self):
        from kernel import proc, thread, sched, timer
        if self.tab == 0:
            rows = []
            for p in sorted(proc.table.values(), key=lambda p: p.pid):
                rows.append(("%5d %5d  %s  %-14s %s" % (p.pid, p.ppid, p.state, p.name[:14], " ".join(p.argv)[:40]), p.pid))
            for i, name, state, ticks, sw in thread.info():
                rows.append(("  hilo %3d  %-16s %-7s cpu %d" % (i, name[:16], state, ticks), None))
            for t in sched.tasks:
                rows.append(("  tarea t%d %s pasos=%d" % (t.id, t.name, t.steps), None))
            sel = self.list.selected
            self.list.items = rows
            self.list.selected = min(max(0, sel), len(rows) - 1)
        elif self.tab == 1:
            from kernel import mm
            from desktop import wm
            s = mm.stats()
            used = s["total"] - s["free"]
            self.history = (self.history + [used / float(s["total"] or 1)])[-60:]
            self.cpu = (self.cpu + [getattr(wm.wm, "cpu_load", 0.0)])[-60:]
            up = timer.ms() // 1000
            self.lines_perf = [
                "CPU (escritorio): %d %%" % int(self.cpu[-1] * 100),
                "RAM en uso: %d de %d MiB (%d %%)" % (used >> 20, s["total"] >> 20, int(self.history[-1] * 100)),
                "Python: %d MiB usados, %d MiB libres" % (s["python_used"] >> 20, s["python_free"] >> 20),
                "Reserva para crecer: %d de %d MiB libres" % (s["reserve_free"] >> 20, s["reserve"] >> 20),
                "Espacios de memoria: %d (%d KiB)" % (s["spaces"], s["space_bytes"] >> 10),
                "Procesos: %d   hilos: %d" % (len(proc.table), len(thread.info())),
                "Encendido: %d:%02d:%02d" % (up // 3600, up // 60 % 60, up % 60)]
            self.view.lines = []
        elif self.tab == 2:
            from kernel import net
            self.view.lines = (net.summary() + "\n\n" + (net.connections() or "sin conexiones")).split("\n")
        else:
            from kernel import log
            self.view.lines = log.lines()[-200:]
            self.view.top = max(0, len(self.view.lines) - self.view.rows())

    def kill(self):
        if 0 <= self.list.selected < len(self.list.items):
            pid = self.list.items[self.list.selected][1]
            if pid:
                from kernel import proc
                try:
                    proc.kill(pid, proc.SIGTERM)
                    self.message = "senal TERM enviada a %d" % pid
                except OSError as e:
                    self.message = str(e)

    def tick(self, now):
        if now >= self.next:
            self.next = now + 1000
            self.refresh()
            return True
        return False

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        for i, b in enumerate(self.form.widgets[:4]):
            b.primary = i == self.tab
        self.form.draw(surf)
        if self.tab == 1:
            w = (self.win.w - 40) // 2
            self.graph(surf, (12, 44, w, 150), self.cpu, "CPU", (80, 160, 255))
            self.graph(surf, (28 + w, 44, w, 150), self.history, "Memoria", (170, 90, 230))
            for k, line in enumerate(self.lines_perf):
                ui.text(surf, line, 16, 230 + 22 * k, T.TEXT, ui.font(14))
        if self.tab == 0:
            ui.text(surf, self.message, 156, self.win.h - 28, T.MUTED)

    def graph(self, surf, rect, values, name, color):
        """A line of the last 60 seconds, 0..100 %, with the area under it filled."""
        x0, y0, w, h = rect
        pygame.draw.rect(surf, T.FIELD, rect)
        for k in range(1, 4):                                # grid lines at 25, 50, 75 %
            pygame.draw.line(surf, T.FIELD_BORDER, (x0, y0 + h * k // 4), (x0 + w, y0 + h * k // 4))
        pygame.draw.rect(surf, T.FIELD_BORDER, rect, 1)
        pts = [(x0 + w - (len(values) - 1 - i) * w // 59, y0 + h - 1 - int(min(1.0, v) * (h - 2)))
               for i, v in enumerate(values)]
        if len(pts) > 1:
            pygame.draw.polygon(surf, tuple(c // 3 + 2 * b // 3 for c, b in zip(color, T.FIELD)),
                                pts + [(pts[-1][0], y0 + h - 1), (pts[0][0], y0 + h - 1)])
            pygame.draw.lines(surf, color, False, pts, 2)
        now = "%d %%" % int(values[-1] * 100) if values else ""
        ui.text(surf, name + "  " + now, x0, y0 + h + 6, T.TEXT, ui.font(14, True))
        ui.text(surf, "60 s", x0 + w - 30, y0 + h + 6, T.MUTED, ui.font(12))

    def event(self, ev, pos):
        return self.form.event(ev, pos)
