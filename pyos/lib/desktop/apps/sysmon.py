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
        self.tabs = ["Procesos", "Memoria", "Red", "Registro"]
        self.form = ui.Form()
        for i, name in enumerate(self.tabs):
            self.form.add(ui.Button((8 + 104 * i, 6, 100, 24), name, lambda i=i: self.set_tab(i)))
        self.list = self.form.add(ui.ListBox((8, 38, 620, 320), []))
        self.kill_btn = self.form.add(ui.Button((8, 400, 140, 24), "Terminar proceso", self.kill))
        self.view = self.form.add(ui.TextView((8, 38, 620, 360), []))
        self.next = 0
        self.history = []
        self.message = ""
        self.set_tab(0)

    def set_tab(self, i):
        self.tab = i
        self.list.visible = i == 0
        self.kill_btn.visible = i == 0
        self.view.visible = i != 0
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
            s = mm.stats()
            free, used = gc.mem_free(), gc.mem_alloc()
            self.history = (self.history + [used])[-60:]
            lines = ["RAM total:          %6d MiB" % (s["total"] >> 20),
                     "RAM sin asignar:    %6d MiB" % (s["free"] >> 20),
                     "Heap de Python:     %6d MiB" % (s["heap"] >> 20),
                     "  usado:            %6d KiB" % (used >> 10),
                     "  libre:            %6d KiB" % (free >> 10),
                     "Espacios de memoria: %d (%d KiB)" % (s["spaces"], s["space_bytes"] >> 10),
                     "Tiempo encendido:   %d s" % (timer.ms() // 1000)]
            self.view.lines = lines
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
        if self.tab == 1 and self.history:
            x0, y0, w, h = 330, 60, self.win.w - 350, 120
            pygame.draw.rect(surf, T.FIELD, (x0, y0, w, h))
            pygame.draw.rect(surf, T.FIELD_BORDER, (x0, y0, w, h), 1)
            top = max(self.history) or 1
            pts = [(x0 + i * w // 60, y0 + h - 2 - (v * (h - 4) // top)) for i, v in enumerate(self.history)]
            if len(pts) > 1:
                pygame.draw.lines(surf, T.ACCENT, False, pts, 2)
            ui.text(surf, "heap usado (60 s)", x0 + 4, y0 + h + 4, T.MUTED)
        if self.tab == 0:
            ui.text(surf, self.message, 156, self.win.h - 28, T.MUTED)

    def event(self, ev, pos):
        return self.form.event(ev, pos)
