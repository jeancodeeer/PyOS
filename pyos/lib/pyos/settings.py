# Every setting of SnakeyOS: its default, the choices it allows, and what
# changing it does. Values are kept in /disk/etc/pyos.json (pyos/config.py)
# and applied when the desktop starts and whenever the Settings app changes
# one.
#
#   settings.get("tema")              -> "claro"
#   settings.set("tema", "oscuro")    saves it and applies it at once
#   settings.apply_all()              at start-up
from pyos import config

RESOLUTIONS = ("800x600", "1024x768", "1280x720", "1280x800", "1366x768", "1440x900", "1600x900", "1920x1080")
ZONES = [("UTC-8 Los Angeles", -480), ("UTC-6 Mexico", -360), ("UTC-5 Lima, Bogota", -300),
         ("UTC-4 Caracas, Santiago", -240), ("UTC-3 Buenos Aires", -180), ("UTC 0 Londres", 0),
         ("UTC+1 Madrid", 60), ("UTC+2 Madrid (verano)", 120), ("UTC+3 Moscu", 180), ("UTC+8 Pekin", 480),
         ("UTC+9 Tokio", 540)]

DEFAULTS = {
    # pantalla
    "resolucion": "1024x768", "escala_texto": 100, "luz_nocturna": 0, "apagar_pantalla_min": 0,
    "bloquear_al_volver": False,
    # personalizacion
    "tema": "claro", "acento": "python", "wallpaper": 0, "iconos_escritorio": True, "dock": "normal",
    # sonido
    "volumen": 80, "sonidos_sistema": True,
    # raton y teclado
    "velocidad_raton": 100, "zurdo": False, "doble_clic_ms": 400, "teclado": "es",
    # fecha y hora
    "zona_minutos": -300, "reloj_24h": True, "hora_automatica": True,
    # red
    "nombre_equipo": "pyos", "cortafuegos": True, "proxy": "",
    # notificaciones, privacidad
    "notificaciones": True, "historial_navegador": True, "javascript": True,
    # avanzado
    "pywin_depuracion": False, "gc_cada_s": 5,
}


def get(key):
    return config.get(key, DEFAULTS.get(key))


def set(key, value):
    config.set(key, value)
    apply(key)


# ---- applying them ----

def _wm():
    from desktop import wm
    return wm.wm


def apply(key):
    """Make one setting take effect now."""
    value = get(key)
    try:
        APPLY.get(key, lambda v: None)(value)
    except Exception as e:
        try:
            from kernel import log
            log.warn("settings: %s: %r" % (key, e))
        except Exception:
            pass


def apply_all(screen=True):
    for key in DEFAULTS:
        if key == "resolucion" and not screen:
            continue
        apply(key)


def _theme(_):
    from desktop import theme
    theme.apply(get("tema"), get("acento"))
    w = _wm()
    if w is not None:
        w.restyle()


def _resolution(value):
    from desktop import theme
    try:
        width, height = (int(v) for v in value.lower().split("x"))
    except ValueError:
        return
    if (width, height) == tuple(theme.SCREEN):
        return
    w = _wm()
    if w is not None:
        w.set_resolution(width, height)
    else:
        theme.SCREEN = (width, height)


def _text_scale(value):
    from desktop import ui
    ui.set_scale(int(value) / 100.0)
    w = _wm()
    if w is not None:
        w.restyle()


def _dock(value):
    from desktop import theme
    theme.DOCK_H = {"pequeno": 52, "normal": 64, "grande": 80}.get(value, 64)
    w = _wm()
    if w is not None:
        w.restyle()


def _volume(value):
    from kernel import sound
    sound.volume(int(value))


def _mouse_speed(value):
    from kernel import mouse
    mouse.speed = max(0.25, min(3.0, int(value) / 100.0))


def _left_handed(value):
    from kernel import mouse
    mouse.left_handed = bool(value)


def _keyboard(value):
    from kernel import keyboard
    keyboard.layout(value)


def _zone(value):
    import time
    time.TZ_MINUTES = int(value)
    w = _wm()
    if w is not None:
        w.dirty = True


def _auto_time(value):
    if not value:
        return
    import _thread

    def sync():
        try:
            from kernel import ntp
            ntp.sync()
        except Exception:
            pass
    _thread.start_new_thread(sync, ())


def _firewall(value):
    from kernel import net
    net.firewall = bool(value)


def _proxy(value):
    try:
        from urllib import request
        request.set_proxy(value or None)
    except (ImportError, AttributeError):
        pass


def _hostname(value):
    try:
        from kernel import net
        net.hostname = value or "pyos"
    except ImportError:
        pass


def _pywin_debug(value):
    try:
        import pywin
        pywin.DEBUG = bool(value)
    except ImportError:
        pass


def _redraw(_):
    w = _wm()
    if w is not None:
        w.restyle()


APPLY = {
    "tema": _theme, "acento": _theme, "resolucion": _resolution, "escala_texto": _text_scale, "dock": _dock,
    "luz_nocturna": _redraw, "iconos_escritorio": _redraw, "volumen": _volume, "velocidad_raton": _mouse_speed,
    "zurdo": _left_handed, "teclado": _keyboard, "zona_minutos": _zone, "hora_automatica": _auto_time,
    "cortafuegos": _firewall, "proxy": _proxy, "nombre_equipo": _hostname, "pywin_depuracion": _pywin_debug,
}
