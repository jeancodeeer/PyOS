# The first screens of SnakeyOS, like any desktop operating system:
#
#   splash(screen, steps, boot=True)   the logo fades in, a ring of dots turns
#                                      while the system gets ready, then fades out
#   session(screen)                    first boot: create your account; then the
#                                      user screen (pick a user, type the password)
#                                      and "Te damos la bienvenida"
#   lock_screen(wm)                    the same user screen, for the user who is in
#
# login(screen) is the short form used when the desktop is opened from the text
# console: it only asks if some account has a password.
import math
import time
import pygame
from desktop import theme as T, ui

DARK = (14, 16, 24)
WHITE = (240, 242, 248)
SOFT = (150, 156, 172)
RED = (255, 140, 130)
DAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre")
AVATAR_COLORS = ((90, 130, 240), (230, 110, 90), (70, 180, 130), (180, 110, 220), (240, 170, 60), (60, 170, 200))


def _ms():
    return time.ticks_ms()


def _since(t0):
    return time.ticks_diff(time.ticks_ms(), t0)


def _cover(screen, amount):
    """Darken the whole screen: amount 0 (nothing) .. 1 (black). For fades."""
    if amount <= 0:
        return
    w, h = screen.get_size()
    c = pygame.Surface((w, h), pygame.SRCALPHA)
    c.fill((0, 0, 0, min(255, int(255 * amount))))
    screen.blit(c, (0, 0))


def _pump():
    """Read the events so the mouse moves and the machine stays responsive."""
    for ev in pygame.event.get():
        pass


# ---- the boot animation ----

def _dots(screen, cx, cy, t):
    """Six dots running around a circle, each a little behind the one before."""
    for k in range(6):
        a = (t / 900.0) * 2 * math.pi - k * 0.42
        a += 0.6 * math.sin(a)                       # they bunch up and spread out as they turn
        x = cx + int(20 * math.cos(a - math.pi / 2))
        y = cy + int(20 * math.sin(a - math.pi / 2))
        shade = 255 - 30 * k
        pygame.draw.circle(screen, (shade, shade, shade), (x, y), 3 if k else 4)


def _boot_frame(screen, label, t, fade=0.0):
    from pyos import logo
    w, h = screen.get_size()
    screen.fill(DARK)
    screen.blit(logo.surface(120), (w // 2 - 60, h // 2 - 160))
    ui.text(screen, "SnakeyOS", w // 2, h // 2 - 4, (236, 238, 246), ui.font(32, bold=True), center=True)
    _dots(screen, w // 2, h // 2 + 90, t)
    ui.text(screen, label, w // 2, h // 2 + 140, SOFT, ui.font(13), center=True)
    _cover(screen, fade)
    pygame.display.flip()


def splash(screen, steps, boot=False):
    """Show the logo while steps (a list of (label, fn)) run one by one.
    boot: the full animation (fade in, turning dots, fade out)."""
    t0 = _ms()
    if boot:
        while _since(t0) < 700:                      # fade in
            _boot_frame(screen, "", _since(t0), 1.0 - _since(t0) / 700.0)
            _pump()
    for label, fn in steps:
        start = _ms()
        _boot_frame(screen, label, _since(t0))
        try:
            fn()
        except Exception:
            pass
        while boot and _since(start) < 450:          # long enough to read, and the dots keep turning
            _boot_frame(screen, label, _since(t0))
            _pump()
    if boot:
        end = _ms()
        while _since(end) < 400:                     # fade out
            _boot_frame(screen, "Listo", _since(t0), _since(end) / 400.0)
            _pump()


# ---- what the user screens share ----

_back = None


def _backdrop(screen):
    """The wallpaper, darkened, with the clock and the date at the top."""
    global _back
    w, h = screen.get_size()
    if _back is None or _back.get_size() != (w, h):
        from desktop import wm
        if getattr(wm, "_cached_wallpaper", None) is None:
            wm._cached_wallpaper = wm.wallpaper()
        _back = pygame.Surface((w, h))
        _back.blit(wm._cached_wallpaper, (0, 0))
        _cover(_back, 0.45)
    screen.blit(_back, (0, 0))
    t = time.localtime()
    ui.text(screen, "%02d:%02d" % (t[3], t[4]), w // 2, 70, WHITE, ui.font(44, bold=True), center=True)
    ui.text(screen, "%s, %d de %s" % (DAYS[t[6]], t[2], MONTHS[t[1] - 1]), w // 2, 130, (210, 214, 226),
            ui.font(16), center=True)


def _card(screen, rect):
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    panel.fill((0, 0, 0, 0))
    pygame.draw.rect(panel, (20, 22, 32, 215), (0, 0, rect.w, rect.h), 0, 18)
    screen.blit(panel, rect.topleft)


def avatar(screen, name, center, radius):
    """A round picture with the user's initial, in a colour of its own."""
    color = AVATAR_COLORS[sum(name.encode()) % len(AVATAR_COLORS)]
    pygame.draw.circle(screen, (255, 255, 255), center, radius + 2)
    pygame.draw.circle(screen, color, center, radius)
    f = ui.font(max(12, radius), bold=True)
    ui.text(screen, name[:1].upper(), center[0], center[1] - f.get_height() // 2, WHITE, f, center=True)


def _power(action):
    from kernel import acpi
    if action == "off":
        acpi.poweroff()
    else:
        acpi.reset()


def _power_buttons(form, w, h):
    form.add(ui.Button((w - 230, h - 50, 100, 32), "Reiniciar", lambda: _power("reset")))
    form.add(ui.Button((w - 120, h - 50, 100, 32), "Apagar", lambda: _power("off")))


def _people(users):
    """The accounts shown on the user screen: everyone but root, or root if alone."""
    names = sorted(n for n in users.accounts() if n != "root")
    return names or ["root"]


# ---- first boot: create the account ----

def first_run(screen):
    """No accounts yet (only root): ask for a name and an optional password."""
    from kernel import users
    w, h = screen.get_size()
    card = pygame.Rect(w // 2 - 210, h // 2 - 150, 420, 330)
    form = ui.Form()
    name = form.add(ui.Field((card.x + 40, card.y + 120, card.w - 80, 34), "", placeholder="Tu nombre (ej. ana)"))
    pw = form.add(ui.Field((card.x + 40, card.y + 166, card.w - 80, 34), "", password=True,
                           placeholder="Contrasena (opcional)"))
    name.focus = True
    state = {"done": None, "message": ""}

    def create(_=None):
        n = name.text.strip().lower().replace(" ", "")
        if not n or not all(c.isalpha() or c.isdigit() or c in "-_." for c in n):
            state["message"] = "Escribe un nombre (letras y numeros)"
            return
        try:
            users.useradd(n, pw.text, "administrador")
            state["done"] = n
        except Exception as e:
            state["message"] = str(e)

    name.on_enter = lambda _: setattr(pw, "focus", True) or setattr(name, "focus", False)
    pw.on_enter = create
    form.add(ui.Button((card.x + 40, card.y + 222, card.w - 80, 38), "Crear cuenta y entrar", create, primary=True))
    _power_buttons(form, w, h)
    clock = pygame.time.Clock()
    while state["done"] is None:
        for ev in pygame.event.get():
            form.event(ev, getattr(ev, "pos", None))
        _backdrop(screen)
        _card(screen, card)
        ui.text(screen, "Te damos la bienvenida a SnakeyOS", card.centerx, card.y + 30, WHITE, ui.font(20, bold=True),
                center=True)
        ui.text(screen, "Crea tu cuenta para empezar. Podras anadir mas", card.centerx, card.y + 66, SOFT,
                ui.font(13), center=True)
        ui.text(screen, "usuarios despues en Configuracion > Usuarios.", card.centerx, card.y + 86, SOFT,
                ui.font(13), center=True)
        form.draw(screen)
        if state["message"]:
            ui.text(screen, state["message"], card.centerx, card.bottom - 40, RED, ui.font(13), center=True)
        pygame.display.flip()
        clock.tick(30)
    return state["done"]


# ---- the user screen ----

def choose_user(screen, only=None, locked=False):
    """Pick a user and type the password (if the account has one). Returns the name.
    only: show just that user (the lock screen)."""
    from kernel import users
    w, h = screen.get_size()
    names = [only] if only else _people(users)
    state = {"chosen": 0, "message": "", "shake": 0, "done": None}
    card = pygame.Rect(w // 2 - 180, h // 2 - 130, 360, 300)
    form = ui.Form()
    pw = form.add(ui.Field((card.x + 50, card.y + 168, card.w - 100, 36), "", password=True,
                           placeholder="Contrasena"))
    go = form.add(ui.Button((card.x + 50, card.y + 216, card.w - 100, 38), "Entrar", None, primary=True))
    _power_buttons(form, w, h)

    def needs_password():
        return bool(users.accounts()[names[state["chosen"]]]["hash"])

    def submit(_=None):
        name = names[state["chosen"]]
        try:
            users.login(name, pw.text)
            state["done"] = name
        except users.PermissionError:
            state["message"] = "Contrasena incorrecta. Intentalo de nuevo."
            state["shake"] = _ms()
            pw.set("")

    def pick(i):
        state["chosen"] = i % len(names)
        state["message"] = ""
        pw.set("")
        pw.visible = pw.focus = needs_password()

    pw.on_enter = submit
    go.on_click = submit
    pick(0)
    tiles = [pygame.Rect(24, h - 70 - 56 * (len(names) - 1 - i), 200, 48) for i in range(len(names))]
    clock = pygame.time.Clock()
    while state["done"] is None:
        for ev in pygame.event.get():
            pos = getattr(ev, "pos", None)
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and len(names) > 1:
                hit = [i for i, r in enumerate(tiles) if r.collidepoint(pos)]
                if hit:
                    pick(hit[0])
                    continue
            if ev.type == pygame.KEYDOWN and not pw.text:
                if ev.key in (pygame.K_UP, pygame.K_LEFT):
                    pick(state["chosen"] - 1)
                    continue
                if ev.key in (pygame.K_DOWN, pygame.K_RIGHT):
                    pick(state["chosen"] + 1)
                    continue
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_RETURN and not pw.focus:
                submit()
                continue
            form.event(ev, pos)
            pw.focus = pw.visible                  # typing always goes to the password
        _backdrop(screen)
        dx = 0
        if state["shake"] and _since(state["shake"]) < 400:   # the card shakes "no"
            dx = int(10 * math.sin(_since(state["shake"]) / 25.0))
        box = card.move(dx, 0)
        _card(screen, box)
        name = names[state["chosen"]]
        avatar(screen, name, (box.centerx, box.y + 70), 44)
        ui.text(screen, name, box.centerx, box.y + 124, WHITE, ui.font(20, bold=True), center=True)
        if not needs_password():
            ui.text(screen, "sin contrasena", box.centerx, box.y + 176, SOFT, ui.font(13), center=True)
        for widget in form.widgets[:2]:
            widget.rect.x = box.x + 50
        form.draw(screen)
        if state["message"]:
            ui.text(screen, state["message"], box.centerx, box.bottom - 30, RED, ui.font(13), center=True)
        if len(names) > 1:                         # the other users, bottom left
            for i, r in enumerate(tiles):
                if i == state["chosen"]:
                    _card(screen, r)
                avatar(screen, names[i], (r.x + 24, r.centery), 16)
                ui.text(screen, names[i], r.x + 50, r.centery - 9, WHITE, ui.font(15))
        if locked:
            ui.text(screen, "Bloqueado", w // 2, h - 44, SOFT, ui.font(13), center=True)
        pygame.display.flip()
        clock.tick(30)
    return state["done"]


def welcome(screen, name):
    """'Te damos la bienvenida' with the turning dots, then a fade to the desktop."""
    w, h = screen.get_size()
    t0 = _ms()
    while _since(t0) < 1300:
        _backdrop(screen)
        avatar(screen, name, (w // 2, h // 2 - 60), 44)
        ui.text(screen, "Te damos la bienvenida, %s" % name, w // 2, h // 2 + 4, WHITE, ui.font(22, bold=True),
                center=True)
        _dots(screen, w // 2, h // 2 + 80, _since(t0))
        _cover(screen, max(0.0, (_since(t0) - 900) / 400.0))
        pygame.display.flip()
        _pump()


def session(screen):
    """The start of a session at boot: create the first account if there is none,
    then the user screen and the welcome. Returns the user's name."""
    from kernel import users
    if not [n for n in users.accounts() if n != "root"]:
        name = first_run(screen)
        if users.accounts()[name]["hash"]:
            name = choose_user(screen, name)       # type the new password once, as on any system
        else:
            users.login(name, "")
    else:
        name = choose_user(screen)
    welcome(screen, name)
    return name


def login(screen):
    """From the text console: ask only if some account has a password."""
    from kernel import users
    if not any(a["hash"] for a in users.accounts().values()):
        return users.whoami()                         # no passwords: no login screen
    return choose_user(screen)


def lock_screen(wm):
    """Lock the screen (Super+L, or when it wakes up if Settings says so): the
    user screen for the user who is in, until the password is typed. Without a
    password it is only a curtain: Enter goes back."""
    from kernel import users
    choose_user(wm.screen, users.whoami(), locked=True)
    wm.dirty = True


def log_out(wm):
    """Close every window and go back to the user screen; then a new session."""
    for win in list(wm.windows):
        wm.close(win)
    wm.launcher = None
    name = choose_user(wm.screen)
    welcome(wm.screen, name)
    wm.dirty = True
