# Settings: keyboard layout, network, date and time, users, about the machine.
import pygame
from desktop import theme as T, ui
from desktop.wm import App


class Settings(App):
    title = "Configuracion"
    size = (600, 420)

    def __init__(self, win):
        App.__init__(self, win)
        self.page = 0
        self.pages = ["Teclado", "Red", "Fecha", "Usuarios", "Sistema"]
        self.msg = ""
        self.build()

    def build(self):
        f = self.form = ui.Form()
        for i, name in enumerate(self.pages):
            b = f.add(ui.Button((8, 8 + 30 * i, 110, 26), name, lambda i=i: self.go(i)))
            b.primary = i == self.page
        x = 132
        if self.page == 0:
            for i, (code, label) in enumerate((("us", "Estados Unidos (us)"), ("es", "Espana (es)"),
                                                ("latam", "Latinoamerica (latam)"))):
                f.add(ui.Button((x, 40 + 32 * i, 220, 26), label, lambda c=code: self.set_kbd(c)))
        elif self.page == 1:
            f.add(ui.Button((x, 150, 160, 26), "Pedir IP (DHCP)", self.dhcp))
            self.ip = f.add(ui.Field((x, 210, 140, 22), "10.0.2.15"))
            self.gw = f.add(ui.Field((x + 150, 210, 140, 22), "10.0.2.2"))
            self.dns = f.add(ui.Field((x + 300, 210, 140, 22), "10.0.2.3"))
            f.add(ui.Button((x, 240, 160, 26), "Usar IP fija", self.static))
            self.host = f.add(ui.Field((x, 300, 220, 22), "10.0.2.2"))
            f.add(ui.Button((x + 230, 300, 80, 24), "Ping", self.ping))
        elif self.page == 2:
            import time
            t = time.localtime()
            self.date = f.add(ui.Field((x, 70, 200, 22), "%04d-%02d-%02d %02d:%02d" % t[:5]))
            f.add(ui.Button((x, 100, 200, 26), "Guardar en el reloj (RTC)", self.set_date))
        elif self.page == 3:
            from kernel import users
            self.users = f.add(ui.ListBox((x, 40, 220, 160), sorted(users.accounts())))
            self.uname = f.add(ui.Field((x, 230, 140, 22), ""))
            self.upass = f.add(ui.Field((x + 150, 230, 140, 22), "", password=True))
            f.add(ui.Button((x, 260, 140, 26), "Crear usuario", self.add_user))
            f.add(ui.Button((x + 150, 260, 140, 26), "Cambiar clave", self.set_pass))
            f.add(ui.Button((x + 300, 260, 140, 26), "Iniciar sesion", self.login))

    def go(self, i):
        self.page = i
        self.msg = ""
        self.build()

    def set_kbd(self, code):
        from kernel import keyboard
        keyboard.set_layout(code) if hasattr(keyboard, "set_layout") else __import__("kernel.shell").shell.kbd(code)
        self.msg = "teclado: " + code

    def dhcp(self):
        from kernel import net
        try:
            net.ip = 0
            self.msg = "direccion: " + net.up()
        except OSError as e:
            self.msg = "DHCP fallo: %s" % e

    def static(self):
        from kernel import net
        if net.nic is None:
            net.up(use_dhcp=False)
        net.configure(self.ip.text, "255.255.255.0", self.gw.text, self.dns.text)
        self.msg = "IP fija " + self.ip.text

    def ping(self):
        from kernel import net
        try:
            rtt = net.ping(self.host.text)
            self.msg = "respuesta en %d ms" % rtt if rtt is not None else "sin respuesta"
        except OSError as e:
            self.msg = str(e)

    def set_date(self):
        try:
            d, t = self.date.text.split()
            y, m, dd = (int(v) for v in d.split("-"))
            hh, mm = (int(v) for v in t.split(":"))
            from kernel import rtc
            if hasattr(rtc, "set"):
                rtc.set((y, m, dd, hh, mm, 0))
                import time
                time._boot_epoch = None
                self.msg = "hora guardada"
            else:
                self.msg = "este reloj no se puede escribir"
        except Exception as e:
            self.msg = "formato: AAAA-MM-DD HH:MM (%s)" % e

    def add_user(self):
        from kernel import users
        try:
            users.require_root()
            users.useradd(self.uname.text.strip(), self.upass.text)
            self.msg = "usuario creado"
            self.build()
        except Exception as e:
            self.msg = str(e)

    def set_pass(self):
        from kernel import users
        name = self.uname.text.strip() or users.whoami()
        try:
            if name != users.whoami():
                users.require_root()
            users.passwd(name, self.upass.text)
            self.msg = "clave cambiada"
        except Exception as e:
            self.msg = str(e)

    def login(self):
        from kernel import users
        try:
            users.login(self.uname.text.strip(), self.upass.text)
            self.msg = "sesion: " + users.whoami()
        except Exception as e:
            self.msg = str(e)

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        pygame.draw.line(surf, T.FIELD_BORDER, (124, 0), (124, self.win.h))
        x = 132
        if self.page == 0:
            ui.text(surf, "Distribucion del teclado", x, 12, T.TEXT)
        elif self.page == 1:
            from kernel import net
            for i, line in enumerate(net.summary().split("\n")):
                ui.text(surf, line, x, 12 + 18 * i, T.TEXT, max_w=self.win.w - x - 8)
            ui.text(surf, "IP                 puerta de enlace     DNS", x, 192, T.MUTED)
            ui.text(surf, "Probar conexion con:", x, 282, T.MUTED)
        elif self.page == 2:
            ui.text(surf, "Fecha y hora (AAAA-MM-DD HH:MM)", x, 48, T.TEXT)
        elif self.page == 3:
            from kernel import users
            ui.text(surf, "Cuentas  (sesion actual: %s)" % users.whoami(), x, 16, T.TEXT)
            ui.text(surf, "nombre             clave", x, 212, T.MUTED)
        else:
            from kernel import shell, mm, VERSION
            import sys
            rows = ["PyKernel %s" % VERSION, "MicroPython %s" % sys.version, "CPU: " + shell.cpu_name(),
                    "RAM: %d MiB" % (mm.total_ram >> 20)]
            try:
                from kernel import acpi
                if not acpi.tables:
                    acpi.init()
                rows += ["ACPI: " + " ".join(sorted(acpi.tables)), "CPUs: %d" % max(1, len(acpi.cpus))]
            except Exception:
                pass
            for i, r in enumerate(rows):
                ui.text(surf, r, x, 16 + 20 * i, T.TEXT, max_w=self.win.w - x - 8)
        self.form.draw(surf)
        ui.text(surf, self.msg, x, self.win.h - 24, T.ACCENT, max_w=self.win.w - x - 8)

    def event(self, ev, pos):
        return self.form.event(ev, pos)
