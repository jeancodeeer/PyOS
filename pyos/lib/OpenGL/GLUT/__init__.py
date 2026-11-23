# OpenGL.GLUT: a window and its event loop, the GLUT way, on pygame.
#
#   glutInit(); glutInitWindowSize(640, 480); glutCreateWindow(b"Demo")
#   glutDisplayFunc(draw); glutIdleFunc(draw); glutMainLoop()
#
# Plus GLUT's ready-made shapes: cubes, spheres, cones, tori.
import math
import pygame
from OpenGL.GL import *        # noqa: F401,F403
from OpenGL.GLU import gluNewQuadric, gluSphere, gluCylinder, gluDisk, gluQuadricDrawStyle, GLU_LINE, GLU_FILL

GLUT_RGB = GLUT_RGBA = GLUT_SINGLE = 0
GLUT_DOUBLE, GLUT_DEPTH, GLUT_ALPHA = 2, 16, 8
GLUT_LEFT_BUTTON, GLUT_MIDDLE_BUTTON, GLUT_RIGHT_BUTTON = 0, 1, 2
GLUT_DOWN, GLUT_UP = 0, 1
GLUT_KEY_LEFT, GLUT_KEY_UP, GLUT_KEY_RIGHT, GLUT_KEY_DOWN = 100, 101, 102, 103
GLUT_KEY_PAGE_UP, GLUT_KEY_PAGE_DOWN, GLUT_KEY_HOME, GLUT_KEY_END = 104, 105, 106, 107
GLUT_KEY_F1 = 1
GLUT_ELAPSED_TIME, GLUT_WINDOW_WIDTH, GLUT_WINDOW_HEIGHT = 700, 102, 103

_size = [640, 480]
_funcs = {}
_timers = []
_redisplay = [True]
_running = [False]
_start = pygame.time.get_ticks()


def glutInit(*args):
    pygame.init()


def glutInitDisplayMode(mode):
    pass


def glutInitWindowSize(w, h):
    _size[0], _size[1] = w, h


def glutInitWindowPosition(x, y):
    pass


def glutCreateWindow(title):
    pygame.display.set_mode(tuple(_size), pygame.DOUBLEBUF | pygame.OPENGL)
    pygame.display.set_caption(title.decode() if isinstance(title, bytes) else title)
    return 1


def glutDestroyWindow(win):
    _running[0] = False


for _name in ("Display", "Idle", "Reshape", "Keyboard", "KeyboardUp", "Special", "SpecialUp",
              "Mouse", "Motion", "PassiveMotion", "Visibility", "Entry"):
    globals()["glut%sFunc" % _name] = (lambda n: lambda fn: _funcs.__setitem__(n, fn))(_name.lower())


def glutTimerFunc(ms, fn, value):
    _timers.append((pygame.time.get_ticks() + ms, fn, value))


def glutPostRedisplay():
    _redisplay[0] = True


def glutSwapBuffers():
    pygame.display.flip()


def glutGet(what):
    if what == GLUT_ELAPSED_TIME:
        return pygame.time.get_ticks() - _start
    if what == GLUT_WINDOW_WIDTH:
        return _size[0]
    if what == GLUT_WINDOW_HEIGHT:
        return _size[1]
    return 0


def glutLeaveMainLoop():
    _running[0] = False


_SPECIAL = {pygame.K_LEFT: GLUT_KEY_LEFT, pygame.K_RIGHT: GLUT_KEY_RIGHT, pygame.K_UP: GLUT_KEY_UP,
            pygame.K_DOWN: GLUT_KEY_DOWN, pygame.K_PAGEUP: GLUT_KEY_PAGE_UP, pygame.K_PAGEDOWN: GLUT_KEY_PAGE_DOWN,
            pygame.K_HOME: GLUT_KEY_HOME, pygame.K_END: GLUT_KEY_END}


def glutMainLoop():
    """Call the program's functions until the window closes (Esc or Ctrl+Q)."""
    _running[0] = True
    if "reshape" in _funcs:
        _funcs["reshape"](_size[0], _size[1])
    clock = pygame.time.Clock()
    while _running[0]:
        for ev in pygame.event.get():
            x, y = pygame.mouse.get_pos()
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN:
                if ev.key in _SPECIAL and "special" in _funcs:
                    _funcs["special"](_SPECIAL[ev.key], x, y)
                elif ev.unicode and "keyboard" in _funcs:
                    _funcs["keyboard"](ev.unicode.encode(), x, y)
                elif ev.key == pygame.K_ESCAPE:
                    return
            elif ev.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and "mouse" in _funcs:
                _funcs["mouse"](min(2, ev.button - 1), GLUT_DOWN if ev.type == pygame.MOUSEBUTTONDOWN else GLUT_UP, x, y)
            elif ev.type == pygame.MOUSEMOTION:
                fn = _funcs.get("motion" if ev.buttons[0] else "passivemotion")
                if fn:
                    fn(x, y)
        now = pygame.time.get_ticks()
        for t in [t for t in _timers if t[0] <= now]:
            _timers.remove(t)
            t[1](t[2])
        if "idle" in _funcs:
            _funcs["idle"]()
        if _redisplay[0] and "display" in _funcs:
            _redisplay[0] = False
            _funcs["display"]()
        clock.tick(60)


# ---- ready-made shapes ----

_CUBE = (((1, 0, 0), [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
         ((-1, 0, 0), [(-1, -1, 1), (-1, 1, 1), (-1, 1, -1), (-1, -1, -1)]),
         ((0, 1, 0), [(-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1)]),
         ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)]),
         ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
         ((0, 0, -1), [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]))


def _cube(size, mode):
    h = size / 2.0
    for normal, corners in _CUBE:
        glBegin(mode)
        glNormal3f(*normal)
        for x, y, z in corners:
            glVertex3f(x * h, y * h, z * h)
        glEnd()


def glutSolidCube(size):
    _cube(size, GL_QUADS)


def glutWireCube(size):
    _cube(size, GL_LINE_LOOP)


def _quadric(style):
    q = gluNewQuadric()
    gluQuadricDrawStyle(q, style)
    return q


def glutSolidSphere(radius, slices, stacks):
    gluSphere(_quadric(GLU_FILL), radius, slices, stacks)


def glutWireSphere(radius, slices, stacks):
    gluSphere(_quadric(GLU_LINE), radius, slices, stacks)


def glutSolidCone(base, height, slices, stacks):
    gluCylinder(_quadric(GLU_FILL), base, 0.0, height, slices, stacks)
    gluDisk(_quadric(GLU_FILL), 0.0, base, slices, 1)


def glutWireCone(base, height, slices, stacks):
    gluCylinder(_quadric(GLU_LINE), base, 0.0, height, slices, stacks)


def glutSolidTorus(inner, outer, sides, rings):
    _torus(inner, outer, sides, rings, GL_QUAD_STRIP)


def glutWireTorus(inner, outer, sides, rings):
    _torus(inner, outer, sides, rings, GL_LINE_STRIP)


def _torus(inner, outer, sides, rings, mode):
    for i in range(rings):
        glBegin(mode)
        for j in range(sides + 1):
            for k in (i + 1, i):
                a = 2 * math.pi * k / rings
                b = 2 * math.pi * j / sides
                nx, ny, nz = math.cos(a) * math.cos(b), math.sin(a) * math.cos(b), math.sin(b)
                glNormal3f(nx, ny, nz)
                glVertex3f((outer + inner * math.cos(b)) * math.cos(a),
                           (outer + inner * math.cos(b)) * math.sin(a), inner * math.sin(b))
        glEnd()


def glutBitmapCharacter(font, char):
    pass


GLUT_BITMAP_HELVETICA_12 = GLUT_BITMAP_9_BY_15 = GLUT_BITMAP_8_BY_13 = 0
