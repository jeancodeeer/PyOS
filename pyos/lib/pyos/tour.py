# The guided tour: SnakeyOS shows itself. A robot (pyos/robot.py) opens every
# app on the desktop and uses it with the mouse and the keyboard, while
# subtitles say what is happening. Type  tour()  at the PyKernel prompt.
#
# Each step is a function that gets the robot; a step that fails is noted
# in the system log and the tour goes on with the next one.
import _thread
import time

STEPS = []


def step(title):
    def add(fn):
        STEPS.append((title, fn))
        return fn
    return add


def _wm():
    from desktop import wm
    return wm.wm


def _open(r, name, title, label=None, dock=False):
    """Open an app the way a person would: from the dock or the launcher."""
    if dock and r.dock(name):
        pass
    else:
        from desktop import apps
        r.launcher(label or apps.label(name), name)
    return r.window(title)


# ---- the desktop ----

@step("Bienvenido a SnakeyOS: un sistema operativo escrito en Python, sobre PyKernel")
def welcome(r):
    r.move(512, 380, 600)
    r.wait(2500)


@step("El lanzador: todas las aplicaciones, con buscador")
def launcher(r):
    r.click(40, 12)
    r.wait(2500)
    r.type("cal", 150)
    r.wait(1500)
    r.press("esc")


@step("Escritorio: clic derecho para crear carpetas y documentos")
def desktop_folder(r):
    r.click(620, 300, button=3)
    r.wait(1200)
    menu = _wm().menu
    if menu:
        for item, rect in menu.rows():
            if item and "carpeta" in item[0].lower():
                r.click(rect.centerx, rect.centery)
                break
    r.wait(900)
    d = _wm().dialog
    if d is not None and d.field is not None:
        r.clear(d.field)
    r.type("Proyectos", 90)
    r.wait(500)
    r.press("enter")
    r.wait(1500)


@step("Archivos: las carpetas del disco, con barra lateral")
def files(r):
    w = _open(r, "files", "Archivos", dock=True)
    r.wait(1200)
    r.click_in(w, 70, 92)                       # Documentos, in the side bar
    r.wait(1500)
    r.click_in(w, 70, 62)                       # Escritorio
    r.wait(1500)
    r.close(w)


@step("El navegador web: HTML y CSS, con su propio motor")
def browser(r):
    w = _open(r, "browser", "Navegador", dock=True)
    r.wait(1500)
    from desktop import ui
    fields = [x for x in r.widgets(w) if isinstance(x, ui.Field)]
    if fields:                                   # the address bar
        f = fields[0]
        r.click_in(w, f.rect.centerx, f.rect.centery)
        r.clear(f)
    r.type("file:///lib/browser/README.html\n", 90)
    r.wait(6000)
    for _ in range(4):
        r.press("pagedown")
        r.wait(700)
    r.close(w)


@step("Terminal: la consola de Python del sistema, con comandos")
def terminal(r):
    w = _open(r, "terminal", "Terminal", dock=True)
    r.wait(1000)
    r.type("cpus()\n", 80)
    r.wait(1200)
    r.type("[2 ** n for n in range(12)]\n", 60)
    r.wait(1500)
    r.type("lsdrv()\n", 80)
    r.wait(2500)
    r.close(w)


@step("Editor de código, con resaltado de Python")
def editor(r):
    w = _open(r, "editor", "Editor", dock=True)
    r.wait(1000)
    r.type("def saludo(nombre):\n    return 'Hola ' + nombre\n\nprint(saludo('SnakeyOS'))\n", 45)
    r.wait(1500)
    r.close(w)
    if _wm().dialog:
        _wm().dialog.done(False)


@step("Calculadora")
def calc(r):
    w = _open(r, "calc", "Calculadora")
    r.wait(800)
    for k in "12*34=":
        r.button(w, k)
        r.wait(250)
    r.wait(1500)
    r.close(w)


@step("Dibujo: pinceles, figuras y colores")
def paint(r):
    w = _open(r, "paint", "Dibujo")
    r.wait(800)
    ox, oy = w.client_origin()
    import math
    pts = [(ox + 300 + int(120 * math.cos(a / 8)), oy + 220 + int(90 * math.sin(a / 8))) for a in range(0, 52, 2)]
    r.drag(pts, 60)
    r.drag([(ox + 220, oy + 120), (ox + 420, oy + 330)], 400)
    r.wait(1500)
    r.close(w)
    if _wm().dialog:
        _wm().dialog.done(False)


@step("Música: reproduce sonidos WAV con la tarjeta AC'97")
def music(r):
    w = _open(r, "music", "Musica", dock=True)
    r.wait(1000)
    r.button(w, "Reproducir")
    r.wait(2500)
    r.button(w, "Detener")
    r.close(w)


@step("Imágenes: BMP, PNG, JPEG y GIF")
def images(r):
    w = _open(r, "images", "Imagenes")
    r.wait(3000)
    r.press("right")
    r.wait(2000)
    r.close(w)


@step("Reloj, y el Monitor del sistema: procesos, memoria y CPU")
def clock_monitor(r):
    w = _open(r, "clock", "Reloj")
    r.wait(2500)
    r.close(w)
    w = _open(r, "sysmon", "Monitor")
    r.wait(3500)
    r.close(w)


@step("Ajustes: teclado, red, fecha, usuarios y sistema")
def settings(r):
    w = _open(r, "settings", "Ajustes", dock=True)
    for page in ("Red", "Fecha", "Usuarios", "Sistema"):
        r.wait(900)
        r.button(w, page)
    r.wait(1500)
    r.close(w)


@step("Discos, y la Tienda para instalar apps y paquetes")
def disks_store(r):
    w = _open(r, "disks", "Discos")
    r.wait(2500)
    r.close(w)
    w = _open(r, "store", "Tienda", dock=True)
    r.wait(2500)
    r.close(w)


@step("Juegos: Serpiente, Bloques y Buscaminas")
def games(r):
    w = _open(r, "snake", "Serpiente")
    for k in ("up", "left", "down", "right", "up"):
        r.wait(700)
        r.press(k)
    r.wait(800)
    r.close(w)
    w = _open(r, "blocks", "Bloques")
    for k in ("left", "left", "up", "down", "down", "right"):
        r.wait(450)
        r.press(k)
    r.wait(800)
    r.close(w)
    w = _open(r, "mines", "Buscaminas")
    for cx, cy in ((5, 5), (2, 8), (9, 3)):
        r.click_in(w, 14 + 26 * cx + 13, 34 + 26 * cy + 13)
        r.wait(500)
    r.wait(1200)
    r.close(w)


# ---- the apps in the style of Windows ----

@step("Bloc de notas, con menús Archivo, Editar y Formato")
def bloc(r):
    w = _open(r, "bloc", "Bloc de notas")
    r.wait(800)
    r.type("Notas de la demo de SnakeyOS.\nTodo esta escrito en Python.\n", 45)
    r.wait(1200)
    r.close(w)
    if _wm().dialog:
        _wm().dialog.done(False)


@step("Hoja de calculo con formulas")
def hoja(r):
    w = _open(r, "hoja", "Hoja")
    r.wait(800)
    for col, row, text in ((0, 0, "15\n"), (0, 1, "27\n"), (0, 2, "=A1+A2\n")):
        r.click_in(w, 40 + 96 * col + 40, 40 + 24 + 24 * row + 12)
        r.type(text, 90)
    r.wait(1800)
    r.close(w)
    if _wm().dialog:
        _wm().dialog.done(False)


@step("Escritor: documentos con titulos y formato")
def escritor(r):
    w = _open(r, "escritor", "Escritor")
    r.wait(900)
    r.click_in(w, 300, 90)                       # into the document
    r.type(" de SnakeyOS", 60)
    r.press("enter")
    r.type("Escrito con el teclado, en Python.", 50)
    r.wait(1500)
    r.close(w)
    if _wm().dialog:
        _wm().dialog.done(False)


@step("Presentaciones: diapositivas a pantalla completa")
def slides(r):
    w = _open(r, "presentaciones", "Presentaciones")
    r.wait(1500)
    r.press("f5")
    r.wait(2500)
    r.press("right")
    r.wait(2500)
    r.press("esc")
    r.wait(800)
    r.close(w)


@step("Solitario y Calendario")
def solitaire(r):
    w = _open(r, "solitario", "Solitario")
    r.wait(800)
    r.click_in(w, 50, 60)
    r.wait(700)
    r.click_in(w, 50, 60)
    r.wait(1500)
    r.close(w)
    w = _open(r, "calendario", "Calendario")
    r.wait(1000)
    r.button(w, "→")
    r.wait(800)
    r.button(w, "Hoy")
    r.wait(1500)
    r.close(w)


@step("Notas adhesivas y lista de Tareas")
def notes_tasks(r):
    w = _open(r, "notas", "Notas")
    r.wait(800)
    r.button(w, "+ Nueva nota")
    r.type("Comprar pan", 70)
    r.wait(1200)
    r.close(w)
    w = _open(r, "tareas", "Tareas")
    r.wait(800)
    r.click_in(w, 170, 29)
    r.type("Grabar el video de SnakeyOS\n", 50)
    r.wait(1500)
    r.close(w)


@step("Recortes, Mapa de caracteres, Teclado en pantalla y Lupa")
def tools(r):
    w = _open(r, "recortes", "Recortes")
    r.wait(800)
    r.button(w, "Pantalla completa")
    r.wait(3000)
    w = r.window("Recortes")
    r.close(w)
    w = _open(r, "caracteres", "caracteres")
    r.wait(800)
    for i in (37, 70, 90):
        r.click_in(w, 16 + 34 * (i % 16) + 17, 16 + 34 * (i // 16) + 17)
        r.wait(300)
    r.wait(1000)
    r.close(w)
    w = _open(r, "teclado", "Teclado")
    r.wait(1500)
    r.close(w)
    w = _open(r, "lupa", "Lupa")
    r.move(200, 120, 800)
    r.move(700, 600, 1200)
    r.wait(800)
    r.close(w)


# ---- full-screen programs and OpenGL ----

def _play(keys):
    def play(r):
        r.wait(1500)
        for k, ms in keys:
            r.hold(k, ms)
            r.wait(250)
        r.wait(1000)
    return play


@step("Juegos pygame a pantalla completa: Pelota y Espacio")
def fullscreen_games(r):
    r.fullscreen("Pelota", "pelota", _play([("left", 600), ("right", 900), ("left", 500), ("right", 700)]))
    r.wait(1000)
    r.fullscreen("Espacio", "espacio", _play([("space", 100), ("left", 500), ("space", 100), ("right", 800),
                                              ("space", 100), ("up", 400), ("space", 100)]))


@step("OpenGL por software: el Cubo 3D, con luz y texturas")
def opengl(r):
    r.fullscreen("Cubo 3D", "cubo", _play([("right", 2500), ("up", 900), ("left", 1500)]))


# ---- PyWin: Windows programs ----

def _pywin(r, exe):
    """Pick a program in the PyWin app and run it."""
    w = r.window("PyWin", 1000)
    if w is None:
        w = _open(r, "pywin", "PyWin")
        r.wait(1200)
    paths = w.app.paths
    for i, p in enumerate(paths):
        if p.endswith("/" + exe):
            top = w.app.list.top
            row = i - top
            if row < 0 or row >= w.app.list.rows():
                w.app.list.selected = i
                w.app.pick()
                row = i - w.app.list.top
            r.click_in(w, 12 + 120, 64 + 2 + row * 28 + 14)
            r.wait(900)
            if w.app.list.selected != i:          # the click missed the row: choose it directly
                w.app.list.selected = i
                w.app.pick()
            r.button(w, "Ejecutar")
            return True
    return False


@step("PyWin: programas de Windows (.exe) que corren de verdad en el procesador")
def pywin_console(r):
    w = _open(r, "pywin", "PyWin")
    r.wait(2500)
    _pywin(r, "hola.exe")
    r.wait(5000)
    c = r.window("hola.exe")
    r.close(c)
    _pywin(r, "colores.exe")
    r.wait(4000)
    r.close(r.window("colores.exe"))
    _pywin(r, "hilos.exe")
    r.wait(5000)
    r.close(r.window("hilos.exe"))


@step("PyWin: ventanas Win32 con botones, menús y dibujo GDI")
def pywin_windows(r):
    _pywin(r, "ventana.exe")
    w = r.window("Ventana Win32")
    r.wait(1500)
    if w:
        for _ in range(3):
            r.click_in(w, 80, 96)
            r.wait(500)
        r.wait(1500)
        r.close(w)
    _pywin(r, "notas.exe")
    w = r.window("Notas Win32")
    r.wait(1500)
    if w:
        r.type("Un .exe de Windows escrito en C", 50)
        r.wait(800)
        bar = getattr(w.app, "bar", [])        # the words of the menu bar: (rect, item)
        if bar:
            r.click_in(w, bar[0][0].centerx, bar[0][0].centery)      # Archivo
            r.wait(2000)
            _wm().menu = None
            _wm().dirty = True
            r.click_in(w, bar[-1][0].centerx, bar[-1][0].centery)    # Ayuda
            r.wait(1000)
        menu = _wm().menu
        if menu:
            for item, rect in menu.rows():
                if item and "Acerca" in item[0]:
                    r.click(rect.centerx, rect.centery)
        r.wait(2500)
        if _wm().dialog:
            r.press("enter")
        r.wait(800)
        r.close(w)


@step("PyWin + OpenGL: un programa OpenGL de Windows")
def pywin_gl(r):
    _pywin(r, "cubo_gl.exe")
    w = r.window("OpenGL en PyWin")
    r.wait(7000)
    if w:
        r.close(w)


def _game_window(r, timeout_ms):
    """The Win32 window a PyWin program opened (its console is another window)."""
    from pywin.host import Win32App
    end = time.ticks_add(time.ticks_ms(), timeout_ms)
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        for w in reversed(_wm().windows):
            if isinstance(w.app, Win32App):
                return w
        time.sleep_ms(200)
    return None


@step("DOOM (1993) en PyWin: el shareware de Internet Archive, compilado para Windows x64")
def doom(r):
    if not _pywin(r, "doom.exe"):
        r.say("DOOM no esta instalado (tools/doom.py)", 3000)
        return
    w = _game_window(r, 30000)                 # DOOM's own window, not its console
    console = r.window("doom.exe", 1000)
    if w is None:
        return
    end = time.ticks_add(time.ticks_ms(), 60000)
    while "shareware" not in (w.title or "").lower() and time.ticks_diff(end, time.ticks_ms()) > 0:
        time.sleep_ms(300)                     # DOOM names its window once the game is loaded
    r.wait(6000)                               # the title screen
    r.click(*r.title_bar(w))                   # bring it to the front: the keys go to it
    r.say("DOOM: Nueva partida, episodio 1, dificultad normal", 4000)
    r.press("esc", 150)                        # the menu
    r.wait(1500)
    for _ in range(3):                         # New game, episode 1, "Hurt me plenty"
        r.press("enter", 150)
        r.wait(1600)
    r.wait(3000)
    r.say("Andar, girar, disparar y abrir puertas, con el teclado", 4000)
    r.hold("up", 1800)
    r.hold("right", 450)
    r.hold("up", 1500)
    for _ in range(3):
        r.hold("ctrl", 200)
        r.wait(350)
    r.hold("left", 900)
    r.hold("up", 2000)
    r.press("space", 150)
    r.hold("up", 2500)
    r.hold("right", 700)
    for _ in range(3):
        r.hold("ctrl", 200)
        r.wait(350)
    r.hold("up", 2000)
    r.wait(2500)
    r.close(w)
    r.wait(1500)
    if console:
        r.close(r.window("doom.exe", 500))


@step("Acerca de SnakeyOS")
def about(r):
    pw = r.window("PyWin", 500)
    if pw:
        r.close(pw)
    w = _open(r, "about", "Acerca de")
    r.wait(4000)
    r.close(w)


# ---- running it ----

def _tour(speed, only=None):
    from pyos.robot import Robot
    from desktop import wm
    r = Robot(speed)
    while wm.wm is None or not getattr(wm.wm, "running", False):
        time.sleep_ms(200)
    time.sleep_ms(2500)
    for title, fn in STEPS:
        if only and fn.__name__ not in only:
            continue
        if not wm.wm.running:
            break
        try:
            r.say(title, 4500)
            fn(r)
            r.wait(600)
        except Exception as e:
            _note(title, e)
            for w in list(wm.wm.windows):
                wm.wm.later(lambda w=w: wm.wm.close(w))
            wm.wm.menu = wm.wm.dialog = wm.wm.launcher = None
    if wm.wm.running:
        r.say("Fin del tour. Gracias por mirar.", 4000)
        r.wait(4500)
        wm.wm.running = False


def _note(title, e):
    import io
    import sys
    try:
        from kernel import log
        buf = io.StringIO()
        sys.print_exception(e, buf)
        log.error("tour: %s: %s" % (title, buf.getvalue().strip().replace("\n", " | ")))
    except Exception:
        pass


def run(speed=1.0, only=None):
    """Start the desktop and walk through it (only: names of some steps)."""
    import desktop
    try:
        _thread.stack_size(32 * 1024)
    except Exception:
        pass
    _thread.start_new_thread(_tour, (speed, only))
    desktop.run()
