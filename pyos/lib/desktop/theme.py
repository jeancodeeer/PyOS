# The look of the desktop, in one place: colours, sizes, fonts.
SCREEN = (1024, 768)

# window contents (light)
WIN_BG = (250, 250, 248)
TEXT = (28, 30, 36)
MUTED = (112, 118, 130)
ACCENT = (30, 79, 140)              # Python's strong blue
ACCENT_TEXT = (255, 255, 255)
SELECT = (214, 228, 246)
FIELD = (255, 255, 255)
FIELD_BORDER = (206, 210, 218)
BUTTON = (236, 238, 242)
BUTTON_HI = (222, 226, 234)
RED = (236, 84, 76)
YELLOW = (255, 222, 115)            # Python's yellow, softened
SOFT_YELLOW = (255, 244, 200)
GREEN = (72, 190, 100)
DARK_BG = (22, 24, 30)
DARK_TEXT = (226, 230, 238)

# window frame
TITLE_H = 30
RADIUS = 12
TITLE_BG = (238, 240, 244)
TITLE_BG_OFF = (246, 247, 249)
TITLE_TEXT = (40, 44, 52)
TITLE_TEXT_OFF = (150, 154, 162)
WIN_BORDER = (190, 194, 204)

# desktop
TOP_H = 30                         # top bar: menu, clock, status
DOCK_H = 90                        # the glass dock with the app icons
WALL_TOP = (24, 62, 118)           # wallpaper: deep Python blue ...
WALL_BOTTOM = (250, 214, 110)      # ... melting into soft yellow
PANEL = (250, 250, 246, 222)       # frosted, light bars (macOS-like)
PANEL_TEXT = (26, 40, 64)

# old names some apps use
CHAR_W, CHAR_H = 8, 16
BAR_H = DOCK_H


# ---- light and dark, and the accent colour (Settings > Personalizacion) ----

LIGHT = {"WIN_BG": (247, 248, 250), "TEXT": (28, 30, 36), "MUTED": (112, 118, 130), "SELECT": (220, 232, 255),
         "FIELD": (255, 255, 255), "FIELD_BORDER": (206, 210, 218), "BUTTON": (236, 238, 242),
         "BUTTON_HI": (222, 226, 234), "TITLE_BG": (238, 240, 244), "TITLE_BG_OFF": (246, 247, 249),
         "TITLE_TEXT": (40, 44, 52), "TITLE_TEXT_OFF": (150, 154, 162), "WIN_BORDER": (190, 194, 204)}
DARK = {"WIN_BG": (32, 34, 40), "TEXT": (226, 230, 238), "MUTED": (150, 156, 170), "SELECT": (52, 70, 110),
        "FIELD": (44, 47, 55), "FIELD_BORDER": (72, 76, 88), "BUTTON": (54, 58, 68), "BUTTON_HI": (68, 72, 84),
        "TITLE_BG": (40, 42, 50), "TITLE_BG_OFF": (34, 36, 42), "TITLE_TEXT": (226, 230, 238),
        "TITLE_TEXT_OFF": (130, 134, 146), "WIN_BORDER": (20, 22, 26)}
CONTRAST = {"WIN_BG": (0, 0, 0), "TEXT": (255, 255, 255), "MUTED": (230, 230, 120), "SELECT": (0, 70, 160),
            "FIELD": (0, 0, 0), "FIELD_BORDER": (255, 255, 255), "BUTTON": (0, 0, 0), "BUTTON_HI": (60, 60, 60),
            "TITLE_BG": (0, 0, 0), "TITLE_BG_OFF": (0, 0, 0), "TITLE_TEXT": (255, 255, 0),
            "TITLE_TEXT_OFF": (200, 200, 200), "WIN_BORDER": (255, 255, 255)}
MODES = {"claro": LIGHT, "oscuro": DARK, "contraste": CONTRAST}
ACCENTS = {"python": (30, 79, 140), "azul": (64, 120, 242), "violeta": (128, 84, 230), "rosa": (226, 72, 140), "rojo": (220, 60, 60),
           "naranja": (236, 128, 30), "verde": (40, 160, 90), "turquesa": (20, 150, 160), "grafito": (90, 96, 110)}
mode = "claro"


def apply(new_mode=None, accent=None):
    """Change the colours of every window at once (apps read them when they draw)."""
    global mode, ACCENT, SELECT
    g = globals()
    if new_mode in MODES:
        mode = new_mode
        g.update(MODES[new_mode])
    if accent in ACCENTS:
        ACCENT = ACCENTS[accent]
        if mode == "claro":                      # a pale version for selections
            SELECT = tuple(255 - (255 - c) // 6 for c in ACCENT)
        elif mode == "oscuro":
            SELECT = tuple(c // 3 + 20 for c in ACCENT)


def open_screen(size=None):
    """The screen in graphics mode at size (SCREEN when None). When the display cannot
    show it, a smaller mode that works (and SCREEN follows): never a black screen."""
    global SCREEN
    import pygame
    tries = [tuple(size or SCREEN), (1280, 800), (1024, 768), (800, 600), (640, 480)]
    last = None
    for s in tries:
        try:
            screen = pygame.display.set_mode(s)
            SCREEN = tuple(screen.get_size())
            return screen
        except (ValueError, OSError) as e:
            last = e
    raise last
