# Configuracion: every setting of SnakeyOS, grouped like in other systems.
#
# A list of sections on the left; on the right, the section's settings.
# Each setting is a row: a title, a short explanation, and a control:
#   Choice   a few buttons, one of them chosen (theme, resolution...)
#   Toggle   on / off
#   Slider   a number between two limits (volume, pointer speed...)
# Changing one saves it (pyos/settings.py) and applies it at once.
import time
import pygame
from desktop import theme as T, ui
from desktop.wm import App
from pyos import settings as S

ROW_H = 58
SIDE_W = 170
SECTIONS = ["Pantalla", "Personalizacion", "Sonido", "Raton y teclado", "Fecha y hora", "Red",
            "Usuarios", "Accesibilidad", "Notificaciones", "Privacidad", "Almacenamiento", "Energia",
            "Avanzado", "Acerca de"]


# ---- the three kinds of control ----

class Choice(ui.Widget):
    def __init__(self, rect, key, options, labels=None, after=None):
        ui.Widget.__init__(self, rect)
        self.key, self.options = key, list(options)
        self.labels = labels or [str(o) for o in self.options]
        self.after = after

    def spots(self):
        f = ui.font(12)
        x = self.rect.x
        for opt, label in zip(self.options, self.labels):
            w = ui.width(label, f) + 18
            yield opt, label, pygame.Rect(x, self.rect.y, w, self.rect.h)
            x += w + 4

    def draw(self, surf):
        current = S.get(self.key)
        f = ui.font(12)
        for opt, label, r in self.spots():
            on = opt == current
            ui.box(surf, r, T.ACCENT if on else T.BUTTON, None if on else T.FIELD_BORDER, 6)
            ui.text(surf, label, r.centerx, r.y + (r.h - f.get_height()) // 2, T.ACCENT_TEXT if on else T.TEXT, f,
                    center=True)

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for opt, _, r in self.spots():
                if r.collidepoint(pos):
                    S.set(self.key, opt)
                    if self.after:
                        self.after()
                    return True
        return False


class Toggle(ui.Widget):
    def __init__(self, rect, key, after=None):
        ui.Widget.__init__(self, rect)
        self.key, self.after = key, after

    def draw(self, surf):
        on = bool(S.get(self.key))
        r = self.rect
        ui.box(surf, r, T.ACCENT if on else T.BUTTON_HI, None, r.h // 2)
        knob = r.h - 6
        x = r.right - knob - 3 if on else r.x + 3
        pygame.draw.circle(surf, (255, 255, 255), (x + knob // 2, r.centery), knob // 2)
        ui.text(surf, "Si" if on else "No", r.right + 10, r.y + 2, T.MUTED, ui.font(12))

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.rect.collidepoint(pos):
            S.set(self.key, not S.get(self.key))
            if self.after:
                self.after()
            return True
        return False


class Slider(ui.Widget):
    def __init__(self, rect, key, lo, hi, step=1, unit=""):
        ui.Widget.__init__(self, rect)
        self.key, self.lo, self.hi, self.step, self.unit = key, lo, hi, step, unit
        self.dragging = False

    def value_at(self, x):
        t = max(0.0, min(1.0, (x - self.rect.x) / float(self.rect.w)))
        v = self.lo + t * (self.hi - self.lo)
        return int(round(v / self.step) * self.step)

    def draw(self, surf):
        v = S.get(self.key)
        r = self.rect
        t = (v - self.lo) / float(self.hi - self.lo) if self.hi > self.lo else 0
        cy = r.centery
        pygame.draw.rect(surf, T.BUTTON_HI, (r.x, cy - 3, r.w, 6), 0, 3)
        pygame.draw.rect(surf, T.ACCENT, (r.x, cy - 3, int(r.w * t), 6), 0, 3)
        pygame.draw.circle(surf, T.ACCENT, (r.x + int(r.w * t), cy), 9)
        pygame.draw.circle(surf, (255, 255, 255), (r.x + int(r.w * t), cy), 5)
        ui.text(surf, "%d%s" % (v, self.unit), r.right + 14, cy - 8, T.TEXT, ui.font(13))

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.rect.inflate(0, 16).collidepoint(pos):
            self.dragging = True
        elif ev.type == pygame.MOUSEBUTTONUP and self.dragging:
            self.dragging = False
            S.set(self.key, self.value_at(pos[0]))       # applied once, when let go
            return True
        if self.dragging and ev.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
            from pyos import config
            config.set(self.key, self.value_at(pos[0]))   # moves while dragging
            return True
        return False


# ---- the app ----

class Settings(App):
    title = "Configuracion"
    size = (860, 600)

    def __init__(self, win, section=None):
        App.__init__(self, win)
        self.section = SECTIONS.index(section) if section in SECTIONS else 0
        self.msg = ""
        self.rows = []          # (title, explanation, y) of the settings shown
        self.lines = []         # extra text lines (information pages): (text, y, colour)
        self.scroll = 0
        self.build()

    # ---- building a section ----
    def row(self, title, note, control=None, h=ROW_H):
        y = self.y
        self.rows.append((title, note, y))
        if control is not None:
            self.form.add(control)
        self.y += h
        return control

    def cx(self):
        return SIDE_W + 290

    def build(self):
        self.form = ui.Form()
        self.rows, self.lines = [], []
        self.y = 64
        x, cw = self.cx(), self.win.w - self.cx() - 70
        getattr(self, "page_" + str(self.section))(x, cw)

    def go(self, i):
        self.section = i
        self.msg = ""
        self.build()

    def info(self, text, color=None):
        self.lines.append((text, self.y, color))
        self.y += 22

    # 0 Pantalla
    def page_0(self, x, cw):
        modes = S.resolutions() or ["1024x768"]
        self.row("Resolucion", "Las que esta pantalla puede mostrar",
                 Choice((x, self.y + 10, cw, 26), "resolucion", modes[:5],
                        [r.replace("x", "×") for r in modes[:5]]))
        if len(modes) > 5:
            self.row("", "", Choice((x, self.y - 22, cw, 26), "resolucion", modes[5:],
                                    [r.replace("x", "×") for r in modes[5:]]), h=36)
        self.row("Tamano del texto", "Letras mas grandes en menus y ventanas",
                 Choice((x, self.y + 10, cw, 26), "escala_texto", (100, 110, 125, 150),
                        ["100%", "110%", "125%", "150%"], after=self.build))
        self.row("Luz nocturna", "Colores mas calidos, que cansan menos la vista de noche",
                 Slider((x, self.y + 10, 200, 26), "luz_nocturna", 0, 100, 5, "%"))
        self.row("Apagar la pantalla", "Tras estos minutos sin usar el teclado ni el raton (0 = nunca)",
                 Choice((x, self.y + 10, cw, 26), "apagar_pantalla_min", (0, 1, 5, 10, 30),
                        ["Nunca", "1 min", "5 min", "10 min", "30 min"]))
        self.row("Pedir la clave al volver", "Bloquear la sesion cuando la pantalla se enciende otra vez",
                 Toggle((x, self.y + 14, 46, 24), "bloquear_al_volver"))
        self.row("Bloquear ahora", "La pantalla de inicio de sesion, hasta escribir la clave",
                 ui.Button((x, self.y + 10, 140, 28), "Bloquear", self.lock))

    # 1 Personalizacion
    def page_1(self, x, cw):
        self.row("Tema", "Ventanas claras, oscuras o de alto contraste",
                 Choice((x, self.y + 10, cw, 26), "tema", ("claro", "oscuro", "contraste"),
                        ["Claro", "Oscuro", "Alto contraste"]))
        names = list(T.ACCENTS)
        self.row("Color de acento", "El color de botones, selecciones y enlaces",
                 Choice((x, self.y + 10, cw, 26), "acento", names[:4], [n[0].upper() + n[1:] for n in names[:4]]))
        self.row("", "", Choice((x, self.y - 22, cw, 26), "acento", names[4:], [n[0].upper() + n[1:] for n in names[4:]]),
                 h=36)
        from desktop import wm
        count = wm.wallpaper_count()
        self.row("Fondo de escritorio", "Los de SnakeyOS y las imagenes de Documentos > Imagenes (%d en total)" % count,
                 Choice((x, self.y + 10, cw, 26), "wallpaper", list(range(min(count, 10))),
                        [str(i + 1) for i in range(min(count, 10))], after=self.set_wallpaper))
        self.row("Iconos en el escritorio", "Mostrar la papelera, archivos y carpetas del escritorio",
                 Toggle((x, self.y + 14, 46, 24), "iconos_escritorio"))
        self.row("Tamano del dock", "La barra de aplicaciones de abajo",
                 Choice((x, self.y + 10, cw, 26), "dock", ("pequeno", "normal", "grande"),
                        ["Pequeno", "Normal", "Grande"]))

    def set_wallpaper(self):
        from desktop import wm
        w = wm.wm
        w.wall_index = S.get("wallpaper")
        w.wallpaper = wm.wallpaper(w.wall_index)
        w.dirty = True

    # 2 Sonido
    def page_2(self, x, cw):
        self.row("Volumen", "El volumen general de la tarjeta de sonido",
                 Slider((x, self.y + 10, 220, 26), "volumen", 0, 100, 5, "%"))
        self.row("Sonidos del sistema", "Avisos, inicio de sesion y papelera",
                 Toggle((x, self.y + 14, 46, 24), "sonidos_sistema"))
        self.row("Probar", "Un tono de 440 Hz durante medio segundo",
                 ui.Button((x, self.y + 10, 140, 28), "Reproducir", self.beep))
        try:
            from kernel import sound
            card = sound.card.name if sound.card else "ninguna (prueba -device intel-hda o AC97 en QEMU)"
        except Exception:
            card = "?"
        self.info("Tarjeta de sonido: %s" % card)

    def beep(self):
        try:
            from kernel import sound
            sound.beep(440, 500)
            self.msg = "sonando" if sound.card else "no hay tarjeta de sonido"
        except Exception as e:
            self.msg = repr(e)

    # 3 Raton y teclado
    def page_3(self, x, cw):
        self.row("Velocidad del puntero", "Cuanto se mueve el puntero al mover el raton",
                 Slider((x, self.y + 10, 220, 26), "velocidad_raton", 25, 300, 5, "%"))
        self.row("Raton para zurdos", "Cambia el boton izquierdo por el derecho",
                 Toggle((x, self.y + 14, 46, 24), "zurdo"))
        self.row("Doble clic", "Tiempo maximo entre los dos clics",
                 Slider((x, self.y + 10, 220, 26), "doble_clic_ms", 200, 900, 50, " ms"))
        self.row("Distribucion del teclado", "Donde esta cada letra y simbolo",
                 Choice((x, self.y + 10, cw, 26), "teclado", ("es", "latam", "us"),
                        ["Espana", "Latinoamerica", "EE. UU."]))
        self.row("Probar el teclado", "Escribe aqui para comprobarlo",
                 ui.Field((x, self.y + 12, cw, 26), "", placeholder="ñ ç ¿? @ # ~ € ..."))

    # 4 Fecha y hora
    def page_4(self, x, cw):
        names = [n for n, _ in S.ZONES]
        minutes = [m for _, m in S.ZONES]
        self.row("Zona horaria", "La hora del reloj se ajusta a tu pais",
                 Choice((x, self.y + 10, cw, 26), "zona_minutos", minutes[:4], [n.split(" ", 1)[0] for n in names[:4]]))
        self.row("", "", Choice((x, self.y - 22, cw, 26), "zona_minutos", minutes[4:8],
                                [n.split(" ", 1)[0] for n in names[4:8]]), h=32)
        self.row("", "", Choice((x, self.y - 22, cw, 26), "zona_minutos", minutes[8:],
                                [n.split(" ", 1)[0] for n in names[8:]]), h=36)
        zone = dict((m, n) for n, m in S.ZONES).get(S.get("zona_minutos"), "")
        self.info("Zona elegida: " + zone, T.MUTED)
        self.row("Hora automatica", "Pedir la hora exacta a un servidor de Internet (NTP)",
                 Toggle((x, self.y + 14, 46, 24), "hora_automatica"))
        self.row("Formato de 24 horas", "14:30 en vez de 2:30 p. m.", Toggle((x, self.y + 14, 46, 24), "reloj_24h"))
        t = time.localtime()
        self.date = self.row("Poner la hora a mano", "AAAA-MM-DD HH:MM, hora local",
                             ui.Field((x, self.y + 12, 160, 26), "%04d-%02d-%02d %02d:%02d" % t[:5]))
        self.form.add(ui.Button((x + 170, self.y - ROW_H + 11, 110, 28), "Guardar", self.set_date))

    def set_date(self):
        try:
            d, t = self.date.text.split()
            y, m, dd = (int(v) for v in d.split("-"))
            hh, mm = (int(v) for v in t.split(":"))
            from kernel import rtc
            secs = time.mktime((y, m, dd, hh, mm, 0, 0, 0)) - time.TZ_MINUTES * 60   # the chip keeps UTC
            rtc.set(time.gmtime(secs)[:6])
            time._boot_epoch = None
            self.msg = "hora guardada"
        except Exception as e:
            self.msg = "formato: AAAA-MM-DD HH:MM (%s)" % e

    # 5 Red
    def page_5(self, x, cw):
        from kernel import net
        for line in net.summary().split("\n")[:5]:
            self.info(line)
        self.y += 6
        self.host = self.row("Nombre del equipo", "Como se llama este PC en la red",
                             ui.Field((x, self.y + 12, 160, 26), S.get("nombre_equipo"),
                                      on_enter=lambda: S.set("nombre_equipo", self.host.text.strip())))
        self.row("Cortafuegos", "Rechazar las conexiones que llegan de otros equipos",
                 Toggle((x, self.y + 14, 46, 24), "cortafuegos"))
        self.proxy = self.row("Proxy", "Para redes de empresa: host:puerto (vacio = sin proxy). Enter para guardar",
                              ui.Field((x, self.y + 12, 220, 26), S.get("proxy") or "",
                                       on_enter=lambda: S.set("proxy", self.proxy.text.strip())))
        self.row("Direccion automatica", "Pedir IP al router (DHCP)", ui.Button((x, self.y + 10, 160, 28), "Pedir IP", self.dhcp))
        self.ip = self.row("IP fija", "Direccion, puerta de enlace y DNS", ui.Field((x, self.y + 12, 110, 26), "192.168.1.50"))
        self.gw = self.form.add(ui.Field((x + 116, self.y - ROW_H + 12, 110, 26), "192.168.1.1"))
        self.dns = self.form.add(ui.Field((x + 232, self.y - ROW_H + 12, 90, 26), "1.1.1.1"))
        self.form.add(ui.Button((x + 328, self.y - ROW_H + 11, 70, 28), "Usar", self.static))
        self.ping_host = self.row("Probar la conexion", "Ping a una direccion o nombre",
                                  ui.Field((x, self.y + 12, 160, 26), "10.0.2.2"))
        self.form.add(ui.Button((x + 170, self.y - ROW_H + 11, 80, 28), "Ping", self.ping))

    def dhcp(self):
        from kernel import net
        try:
            net.ip = 0
            self.msg = "direccion: " + str(net.up())
        except OSError as e:
            self.msg = "DHCP fallo: %s" % e
        self.build()

    def static(self):
        from kernel import net
        if net.nic is None:
            net.up(use_dhcp=False)
        net.configure(self.ip.text, "255.255.255.0", self.gw.text, self.dns.text)
        self.msg = "IP fija " + self.ip.text
        self.build()

    def ping(self):
        from kernel import net
        try:
            rtt = net.ping(self.ping_host.text)
            self.msg = "respuesta en %d ms" % rtt if rtt is not None else "sin respuesta"
        except OSError as e:
            self.msg = str(e)

    # 6 Usuarios
    def page_6(self, x, cw):
        from kernel import users
        self.info("Sesion actual: %s%s" % (users.whoami(), " (administrador)" if users.is_admin() else ""))
        self.users = self.row("Cuentas", "Elige una para cambiar su clave o borrarla",
                              ui.ListBox((x, self.y + 6, 220, 110), sorted(users.accounts())), h=126)
        self.uname = self.row("Nombre", "Para crear una cuenta o iniciar sesion", ui.Field((x, self.y + 12, 160, 26), ""))
        self.upass = self.row("Clave", "Dejala vacia para una cuenta sin clave",
                              ui.Field((x, self.y + 12, 160, 26), "", password=True))
        y = self.y + 4
        for i, (label, fn) in enumerate((("Crear cuenta", self.add_user), ("Cambiar clave", self.set_pass),
                                         ("Borrar cuenta", self.del_user), ("Iniciar sesion", self.login))):
            self.form.add(ui.Button((x + (i % 2) * 150, y + (i // 2) * 34, 140, 28), label, fn))

    def chosen_user(self):
        name = self.uname.text.strip()
        if not name and self.users.selected is not None:
            name = self.users.items[self.users.selected]
        return name

    def add_user(self):
        from kernel import users
        try:
            users.require_admin()
            users.useradd(self.uname.text.strip(), self.upass.text)
            self.msg = "cuenta creada"
            self.build()
        except Exception as e:
            self.msg = str(e)

    def set_pass(self):
        from kernel import users
        name = self.chosen_user() or users.whoami()
        try:
            if name != users.whoami():
                users.require_admin()
            users.passwd(name, self.upass.text)
            self.msg = "clave cambiada para " + name
        except Exception as e:
            self.msg = str(e)

    def del_user(self):
        from kernel import users
        name = self.chosen_user()
        try:
            users.require_admin()
            if name in ("root", users.whoami()):
                raise ValueError("no se puede borrar " + name)
            users.userdel(name)
            self.msg = "cuenta borrada: " + name
            self.build()
        except Exception as e:
            self.msg = str(e)

    def login(self):
        from kernel import users
        try:
            users.login(self.chosen_user(), self.upass.text)
            self.msg = "sesion: " + users.whoami()
            self.build()
        except Exception as e:
            self.msg = str(e)

    # 7 Accesibilidad
    def page_7(self, x, cw):
        self.row("Texto grande", "Letras al 125% en todo el escritorio",
                 Choice((x, self.y + 10, cw, 26), "escala_texto", (100, 125, 150), ["Normal", "Grande", "Muy grande"],
                        after=self.build))
        self.row("Alto contraste", "Negro, blanco y amarillo: lo mas facil de leer",
                 Choice((x, self.y + 10, cw, 26), "tema", ("claro", "contraste"), ["Normal", "Alto contraste"]))
        self.row("Teclado en pantalla", "Escribir con el raton", ui.Button((x, self.y + 10, 140, 28), "Abrir",
                                                                         lambda: self.launch("teclado")))
        self.row("Lupa", "Ampliar la zona del puntero", ui.Button((x, self.y + 10, 140, 28), "Abrir",
                                                                lambda: self.launch("lupa")))
        self.row("Puntero mas lento", "Mas facil de colocar con precision",
                 Slider((x, self.y + 10, 220, 26), "velocidad_raton", 25, 300, 5, "%"))

    def launch(self, name):
        from desktop import wm
        try:
            wm.wm.launch(name)
        except Exception as e:
            self.msg = repr(e)

    # 8 Notificaciones
    def page_8(self, x, cw):
        self.row("Avisos", "Los mensajes que aparecen abajo (guardado, errores, descargas)",
                 Toggle((x, self.y + 14, 46, 24), "notificaciones"))
        self.row("Sonido en los avisos", "Un sonido cuando aparece un mensaje",
                 Toggle((x, self.y + 14, 46, 24), "sonidos_sistema"))
        self.row("Probar", "Mostrar un aviso de ejemplo", ui.Button((x, self.y + 10, 140, 28), "Mostrar",
                                                                    lambda: __import__("desktop.wm").wm.wm.toast("Esto es un aviso")))

    # 9 Privacidad
    def page_9(self, x, cw):
        self.row("Guardar el historial", "El navegador recuerda las paginas visitadas",
                 Toggle((x, self.y + 14, 46, 24), "historial_navegador"))
        self.row("JavaScript", "Los scripts de las paginas (menus, buscadores...); sin rastreadores",
                 Toggle((x, self.y + 14, 46, 24), "javascript"))
        self.row("Borrar el historial", "Las paginas visitadas", ui.Button((x, self.y + 10, 160, 28), "Borrar historial",
                                                                         self.clear_history))
        self.row("Borrar las cookies", "Cierra la sesion en los sitios web",
                 ui.Button((x, self.y + 10, 160, 28), "Borrar cookies", self.clear_cookies))
        self.row("Programas de Windows (PyWin)", "Solo pueden escribir en C: (el disco) y nunca en el sistema", None)
        self.info("Siempre activo: no leen contrasenas ni escriben en /disk/apps o /disk/etc.", T.MUTED)

    def clear_history(self):
        try:
            from browser import store
            store.clear_history()
            self.msg = "historial borrado"
        except Exception as e:
            self.msg = repr(e)

    def clear_cookies(self):
        try:
            from browser import store
            store.clear_cookies()
            self.msg = "cookies borradas"
        except Exception as e:
            self.msg = repr(e)

    # 10 Almacenamiento
    def page_10(self, x, cw):
        import os
        for name, path in (("Disco (C:)", "/disk"), ("USB", "/usb"), ("Sistema (memoria)", "/")):
            try:
                st = os.statvfs(path)
                total, free = st[0] * st[2], st[0] * st[3]
                self.storage_bar(name, total, free)
            except OSError:
                pass
        self.y += 10
        self.row("Papelera", "Borrar para siempre lo que hay en la papelera",
                 ui.Button((x, self.y + 10, 160, 28), "Vaciar papelera", self.empty_trash))
        self.row("Archivos temporales", "Lo que queda en /tmp", ui.Button((x, self.y + 10, 160, 28), "Borrar", self.clear_tmp))

    def storage_bar(self, name, total, free):
        self.lines.append(("bar", self.y, (name, total, free)))
        self.y += 48

    def empty_trash(self):
        from desktop import places
        try:
            n = places.empty_trash() if hasattr(places, "empty_trash") else _remove_all("/disk/.Papelera")
            self.msg = "papelera vaciada"
        except OSError as e:
            self.msg = str(e)
        self.build()

    def clear_tmp(self):
        try:
            _remove_all("/tmp")
            self.msg = "/tmp vaciado"
        except OSError as e:
            self.msg = str(e)
        self.build()

    # 11 Energia
    def page_11(self, x, cw):
        self.row("Apagar la pantalla", "Tras estos minutos sin usar el equipo",
                 Choice((x, self.y + 10, cw, 26), "apagar_pantalla_min", (0, 1, 5, 10, 30),
                        ["Nunca", "1 min", "5 min", "10 min", "30 min"]))
        self.row("Apagar el equipo", "Cierra todo y apaga (ACPI)", ui.Button((x, self.y + 10, 140, 28), "Apagar", self.poweroff))
        self.row("Reiniciar", "Vuelve a arrancar SnakeyOS", ui.Button((x, self.y + 10, 140, 28), "Reiniciar", self.reboot))

    def poweroff(self):
        from desktop import wm
        wm.wm.confirm("Apagar", "Se cerraran todas las ventanas.", lambda ok: ok and __import__("kernel.acpi").acpi.poweroff())

    def reboot(self):
        from desktop import wm
        wm.wm.confirm("Reiniciar", "Se cerraran todas las ventanas.", lambda ok: ok and __import__("kernel.acpi").acpi.reset())

    # 12 Avanzado
    def page_12(self, x, cw):
        import gc
        from kernel import mm
        st = mm.stats()
        self.info("Memoria del heap de Python: %d MiB usados, %d MiB libres; reserva %d/%d MiB libre" % (
            gc.mem_alloc() >> 20, gc.mem_free() >> 20, st["reserve_free"] >> 20, st["reserve"] >> 20))
        self.row("Limpiar la memoria", "Recolectar la basura de Python ahora",
                 ui.Button((x, self.y + 10, 140, 28), "Recolectar", self.collect))
        self.row("Depuracion de PyWin", "Avisos de los programas de Windows por el puerto serie",
                 Toggle((x, self.y + 14, 46, 24), "pywin_depuracion"))
        self.row("Servicios", "Los programas que arrancan con el sistema (/etc/init.d)", None)
        try:
            from kernel import services
            for line in str(services.status() or "").split("\n")[:5]:
                if line.strip():
                    self.info("   " + line[:90], T.MUTED)
        except Exception:
            self.info("   (no disponible)", T.MUTED)
        self.row("Registro del sistema", "Los ultimos mensajes del kernel", None)
        try:
            from kernel import log
            for line in log.lines()[-6:]:
                self.info("   " + line[:100], T.MUTED)
        except Exception:
            pass

    def collect(self):
        import gc
        before = gc.mem_free()
        gc.collect()
        self.msg = "liberados %d KiB" % ((gc.mem_free() - before) >> 10)
        self.build()

    # 13 Acerca de
    def page_13(self, x, cw):
        import sys
        from kernel import shell, mm, VERSION, timer
        import pyos
        st = mm.stats()
        s = timer.ms() // 1000
        rows = [("Sistema", "%s %s" % (pyos.NAME, pyos.version())), ("Kernel", "PyKernel %s" % VERSION),
                ("Python", "MicroPython " + sys.version), ("Procesador", shell.cpu_name()),
                ("Memoria RAM", "%.1f GB (%.1f GB libres)" % (st["total"] / 2 ** 30, st["free"] / 2 ** 30)),
                ("Pantalla", "%d x %d" % T.SCREEN), ("Encendido desde hace", "%d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60))]
        try:
            from kernel import acpi
            if not acpi.tables:
                acpi.init()
            rows.append(("Nucleos", str(max(1, len(acpi.cpus)))))
        except Exception:
            pass
        for k, v in rows:
            self.lines.append(("kv", self.y, (k, v)))
            self.y += 26
        # SnakeyOS Update (GitHub), as Settings > Windows Update
        from desktop import wm
        self.form.add(ui.Button((x, self.y + 4, 220, 30), "Buscar actualizaciones",
                                lambda: wm.wm.launch("updates", True), primary=True))
        self.y += 44
        self.lines.append(("Dispositivos:", self.y, T.MUTED))
        self.y += 22
        try:
            from kernel import drivers
            for where, ids, cls, drv in drivers.table():
                if drv:
                    self.info("   %s  %s  %s" % (where, cls, drivers.WHAT.get(drv, drv)), T.MUTED)
            for where, what, drv in drivers.legacy():
                self.info("   %s  %s" % (where, what), T.MUTED)
        except Exception:
            pass

    def lock(self):
        from desktop import splash, wm
        splash.lock_screen(wm.wm)

    # ---- drawing and events ----
    def draw(self, surf):
        surf.fill(T.WIN_BG)
        side = pygame.Rect(0, 0, SIDE_W, self.win.h)
        pygame.draw.rect(surf, T.BUTTON, side)
        f = ui.font(13)
        for i, name in enumerate(SECTIONS):
            r = pygame.Rect(8, 10 + 34 * i, SIDE_W - 16, 30)
            if i == self.section:
                ui.box(surf, r, T.ACCENT, None, 6)
            ui.text(surf, name, r.x + 12, r.y + 7, T.ACCENT_TEXT if i == self.section else T.TEXT, f)
        x0 = SIDE_W + 24
        ui.text(surf, SECTIONS[self.section], x0, 18, T.TEXT, ui.font(22, True))
        for title, note, y in self.rows:
            if title:
                ui.text(surf, title, x0, y + 10, T.TEXT, ui.font(14, True), self.cx() - x0 - 10)
            if note:
                for k, line in enumerate(ui.wrap(note, self.cx() - x0 - 16, ui.font(12))[:2]):
                    ui.text(surf, line, x0, y + 30 + 14 * k, T.MUTED, ui.font(12))
        for text, y, extra in self.lines:
            if text == "bar":
                name, total, free = extra
                used = total - free
                ui.text(surf, "%s: %s usados de %s" % (name, _size(used), _size(total)), x0, y, T.TEXT, f)
                bar = pygame.Rect(x0, y + 20, self.win.w - x0 - 40, 12)
                pygame.draw.rect(surf, T.BUTTON_HI, bar, 0, 6)
                pygame.draw.rect(surf, T.ACCENT, (bar.x, bar.y, int(bar.w * used / max(1, total)), bar.h), 0, 6)
            elif text == "kv":
                k, v = extra
                ui.text(surf, k, x0, y, T.MUTED, f)
                ui.text(surf, v, x0 + 190, y, T.TEXT, f, self.win.w - x0 - 210)
            else:
                ui.text(surf, text, x0, y, extra or T.TEXT, f, self.win.w - x0 - 20)
        self.form.draw(surf)
        if self.msg:
            ui.text(surf, self.msg, x0, self.win.h - 24, T.ACCENT, max_w=self.win.w - x0 - 8)

    def event(self, ev, pos):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and pos and pos[0] < SIDE_W:
            i = (pos[1] - 10) // 34
            if 0 <= i < len(SECTIONS):
                self.go(i)
                return True
        used = self.form.event(ev, pos)
        if used and ev.type == pygame.MOUSEBUTTONUP:
            self.msg = self.msg or "guardado"
        return used


def _size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%.1f %s" % (n, unit)) if unit != "B" else "%d B" % n
        n /= 1024.0


def _remove_all(folder):
    import os
    for name in os.listdir(folder):
        path = folder.rstrip("/") + "/" + name
        try:
            if os.stat(path)[0] & 0x4000:
                _remove_all(path)
                os.rmdir(path)
            else:
                os.remove(path)
        except OSError:
            pass
