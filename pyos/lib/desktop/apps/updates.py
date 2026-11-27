# Actualizaciones: SnakeyOS's Windows Update. The provider is GitHub (the
# repository's releases); the work is in pyos/update.py. Everything that
# touches the network runs in a thread: the desktop keeps going.
import _thread
import pygame
from desktop import theme as T, ui
from desktop.wm import App
from pyos import update

IDLE, CHECKING, AVAILABLE, UP_TO_DATE, WORKING, DONE, ERROR = range(7)


class Updates(App):
    title = "Actualizaciones"
    size = (720, 520)

    def __init__(self, win, check_now=False):
        App.__init__(self, win)
        self.state = DONE if update.restart_pending() else IDLE
        self.info = None
        self.message = ""
        self.progress = 0.0
        self.form = ui.Form()
        x = 24
        self.check_btn = self.form.add(ui.Button((x, 150, 200, 34), "Buscar actualizaciones", self.check, primary=True))
        self.install_btn = self.form.add(ui.Button((x, 150, 200, 34), "Descargar e instalar", self.install, primary=True))
        self.restart_btn = self.form.add(ui.Button((x, 150, 200, 34), "Reiniciar ahora", self.restart, primary=True))
        self.rollback_btn = self.form.add(ui.Button((x + 214, 150, 230, 34), "Volver a la version anterior", self.rollback))
        self.auto_btn = self.form.add(ui.Button((x, self.win.h - 44, 300, 28), "", self.flip_auto))
        self.auto_install_btn = self.form.add(ui.Button((x + 310, self.win.h - 44, 300, 28), "", self.flip_auto_install))
        self.notes = self.form.add(ui.TextView((x, 230, self.win.w - 48, 150), []))
        self.sync()
        if check_now or (self.state == IDLE and update.config().get("auto_check")):
            self.check()

    # ---- what the buttons show ----
    def sync(self):
        s = self.state
        self.check_btn.visible = s in (IDLE, UP_TO_DATE, ERROR)
        self.install_btn.visible = s == AVAILABLE
        self.restart_btn.visible = s == DONE
        try:
            import os
            os.stat(update.SYSTEM + ".prev")
            has_prev = True
        except OSError:
            has_prev = False
        self.rollback_btn.visible = has_prev and s not in (CHECKING, WORKING)
        c = update.config()
        self.auto_btn.label = "Buscar automaticamente: %s" % ("Si" if c.get("auto_check") else "No")
        self.auto_install_btn.label = "Instalar automaticamente: %s" % ("Si" if c.get("auto_install") else "No")
        lines = []
        if self.info:
            lines += ["Novedades de SnakeyOS %s" % self.info["version"], ""]
            lines += (self.info.get("notes") or "(sin notas)").replace("\r", "").split("\n")
        else:
            h = update.history()
            lines.append("Historial de actualizaciones" if h else "Todavia no se ha instalado ninguna actualizacion.")
            for e in h[:12]:
                lines.append("%s   SnakeyOS %s   %s" % (e.get("date", ""), e.get("version", "?"), e.get("result", "")))
        self.notes.lines = lines
        self.redraw()

    # ---- work, in a thread ----
    def _run(self, fn):
        def worker():
            try:
                fn()
            except Exception as e:
                self.state, self.message = ERROR, "No se pudo completar: %s" % e
            from desktop import wm
            wm.wm.later(self.sync)
        _thread.start_new_thread(worker, ())

    def check(self):
        self.state, self.message, self.info = CHECKING, "Buscando actualizaciones en GitHub...", None
        self.sync()

        def work():
            info = update.check()
            if info is None:
                self.state, self.message = UP_TO_DATE, "Ultima busqueda: ahora mismo"
            else:
                self.info = info
                self.state, self.message = AVAILABLE, "SnakeyOS %s esta disponible" % info["version"]
                if update.config().get("auto_install"):
                    self._install_work()
        self._run(work)

    def install(self):
        self.state, self.progress = WORKING, 0.0
        self.sync()
        self._run(self._install_work)

    def _install_work(self):
        self.state = WORKING

        def progress(text, frac=None):
            self.message = text
            if frac is not None:
                self.progress = frac
            self.redraw()
        m, package = update.download(self.info, progress)
        update.install(m, package, progress)
        self.info = None
        self.state, self.message = DONE, "SnakeyOS %s instalado. Reinicia para terminar." % m["version"]

    def restart(self):
        from kernel import acpi
        acpi.reset()

    def rollback(self):
        def work():
            update.rollback()
            self.state, self.message = DONE, "Version anterior restaurada. Reinicia para usarla."
        self._run(work)

    def flip_auto(self):
        update.set_config(auto_check=not update.config().get("auto_check"))
        self.sync()

    def flip_auto_install(self):
        update.set_config(auto_install=not update.config().get("auto_install"))
        self.sync()

    def tick(self, now):
        return self.state in (CHECKING, WORKING) and now // 250 != getattr(self, "_q", None) and self._mark(now)

    def _mark(self, now):
        self._q = now // 250
        return True

    def resized(self, w, h):
        self.notes.rect.size = (w - 48, h - 300)
        self.auto_btn.rect.y = self.auto_install_btn.rect.y = h - 44

    # ---- drawing ----
    def draw(self, surf):
        surf.fill(T.WIN_BG)
        from desktop import icons
        surf.blit(icons.icon("updates", 64), (24, 22))
        s = self.state
        head = {IDLE: "Actualizaciones de SnakeyOS", CHECKING: "Buscando actualizaciones...",
                AVAILABLE: "Hay una actualizacion disponible", UP_TO_DATE: "Estas al dia",
                WORKING: "Actualizando SnakeyOS", DONE: "Reinicio pendiente", ERROR: "Algo salio mal"}[s]
        ui.text(surf, head, 104, 26, T.TEXT, ui.font(24, bold=True), self.win.w - 120)
        c = update.config()
        ui.text(surf, "Version instalada: SnakeyOS %s   -   Proveedor: GitHub (%s)" % (update.current_version(), c["repo"]),
                104, 62, T.MUTED, ui.font(13), self.win.w - 120)
        last = c.get("last_check") or 0
        if last:
            import time
            t = time.localtime(last)
            ui.text(surf, "Ultima busqueda: %02d/%02d %02d:%02d" % (t[2], t[1], t[3], t[4]), 104, 82, T.MUTED, ui.font(13))
        color = T.RED if s == ERROR else T.ACCENT
        ui.text(surf, self.message, 24, 112, color, ui.font(14), self.win.w - 48)
        if s == WORKING:
            bar = pygame.Rect(24, 196, self.win.w - 48, 10)
            pygame.draw.rect(surf, T.BUTTON_HI, bar, 0, 5)
            pygame.draw.rect(surf, T.ACCENT, (bar.x, bar.y, int(bar.w * self.progress), bar.h), 0, 5)
            ui.text(surf, "%d %%" % int(self.progress * 100), bar.right - 40, bar.y + 14, T.MUTED, ui.font(12))
        if s == CHECKING:                                   # dots going round while it looks
            import math
            import time
            t = time.ticks_ms() / 150.0
            for k in range(8):
                a = t - k * 0.5
                pygame.draw.circle(surf, T.ACCENT, (40 + int(14 * math.cos(a)), 168 + int(14 * math.sin(a))), max(1, 4 - k // 2))
        self.form.draw(surf)
        ui.text(surf, "Las actualizaciones vienen firmadas: SnakeyOS solo instala las que verifica con su clave.",
                24, self.win.h - 70, T.MUTED, ui.font(12), self.win.w - 48)

    def event(self, ev, pos):
        return self.form.event(ev, pos)
