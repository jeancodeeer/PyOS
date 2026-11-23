# The first screens: a boot splash with a progress bar, then the login
# (only if some account has a password).
import time
import pygame
from desktop import theme as T, ui


def splash(screen, steps):
    """Show the logo while steps (a list of (label, fn)) run one by one."""
    w, h = T.SCREEN
    for i, (label, fn) in enumerate(steps):
        screen.fill((14, 16, 24))
        from pyos import logo
        screen.blit(logo.surface(120), (w // 2 - 60, h // 2 - 150))
        ui.text(screen, "PyOS", w // 2, h // 2 + 6, (236, 238, 246), ui.font(32, bold=True), center=True)
        bar = pygame.Rect(w // 2 - 120, h // 2 + 70, 240, 6)
        pygame.draw.rect(screen, (50, 54, 70), bar, 0, 3)
        done = bar.copy()
        done.w = max(6, bar.w * (i + 1) // len(steps))
        pygame.draw.rect(screen, (100, 150, 255), done, 0, 3)
        ui.text(screen, label, w // 2, h // 2 + 86, (140, 146, 162), ui.font(13), center=True)
        pygame.display.flip()
        try:
            fn()
        except Exception:
            pass


def login(screen):
    """Ask for a user and password until one works; returns the user name."""
    from kernel import users
    accounts = users.accounts()
    if not any(a["hash"] for a in accounts.values()):
        return users.whoami()                         # no passwords: no login screen
    names = sorted(n for n in accounts if n != "root") + ["root"]
    chosen, password, message = 0, "", ""
    clock = pygame.time.Clock()
    while True:
        _draw_login(screen, names, chosen, password, message)
        for ev in pygame.event.get():
            if ev.type != pygame.KEYDOWN:
                continue
            if ev.key in (pygame.K_UP, pygame.K_LEFT):
                chosen = (chosen - 1) % len(names)
            elif ev.key in (pygame.K_DOWN, pygame.K_RIGHT, pygame.K_TAB):
                chosen = (chosen + 1) % len(names)
            elif ev.key == pygame.K_RETURN:
                try:
                    users.login(names[chosen], password)
                    return names[chosen]
                except PermissionError:
                    message, password = "Contrasena incorrecta", ""
            elif ev.key == pygame.K_BACKSPACE:
                password = password[:-1]
            elif ui.is_text_key(ev):
                password += ev.unicode
        clock.tick(30)


def _draw_login(screen, names, chosen, password, message):
    from desktop import wm
    w, h = T.SCREEN
    if getattr(wm, "_cached_wallpaper", None) is None:
        wm._cached_wallpaper = wm.wallpaper()
    screen.blit(wm._cached_wallpaper, (0, 0))
    t = time.localtime()
    ui.text(screen, "%02d:%02d" % (t[3], t[4]), w // 2, 120, (255, 255, 255), ui.font(44, bold=True), center=True)
    card = pygame.Rect(w // 2 - 170, h // 2 - 110, 340, 230)
    panel = pygame.Surface(card.size, pygame.SRCALPHA)
    panel.fill((0, 0, 0, 0))
    pygame.draw.rect(panel, (20, 22, 32, 210), (0, 0, card.w, card.h), 0, 16)
    screen.blit(panel, card.topleft)
    pygame.draw.circle(screen, (90, 130, 240), (card.centerx, card.y + 50), 30)
    ui.text(screen, names[chosen][:1].upper(), card.centerx, card.y + 36, (255, 255, 255), ui.font(24, bold=True), center=True)
    ui.text(screen, "<  %s  >" % names[chosen], card.centerx, card.y + 92, (236, 238, 246), ui.font(18, bold=True), center=True)
    field = pygame.Rect(card.x + 40, card.y + 130, card.w - 80, 34)
    pygame.draw.rect(screen, (46, 50, 66), field, 0, 10)
    ui.text(screen, "•" * len(password) if password else "Contrasena", field.x + 14, field.y + 8,
            (236, 238, 246) if password else (140, 146, 160), ui.font(15))
    ui.text(screen, message or "Enter para entrar  -  flechas para cambiar de usuario", card.centerx, card.y + 186,
            (255, 140, 130) if message else (150, 156, 170), ui.font(13), center=True)
    pygame.display.flip()
