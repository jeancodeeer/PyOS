# pyos-app
# name: Cubo 3D
# icon: cubo
# mode: fullscreen
#
# OpenGL demo, written as for PyOpenGL + pygame on a PC: a lit cube that
# turns, a textured floor and a ring of spheres. Arrows turn the camera,
# W toggles wireframe, L the light; Esc (or Ctrl+Q) quits.
import math
import pygame
from pygame.locals import DOUBLEBUF, OPENGL, QUIT, KEYDOWN, K_ESCAPE, K_LEFT, K_RIGHT, K_UP, K_DOWN, K_w, K_l
from OpenGL.GL import *
from OpenGL.GLU import *

W, H = 640, 480

FACES = (((0, 0, 1), (1.0, 0.3, 0.3), ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))),
         ((0, 0, -1), (0.3, 1.0, 0.3), ((1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1))),
         ((1, 0, 0), (0.3, 0.5, 1.0), ((1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1))),
         ((-1, 0, 0), (1.0, 0.9, 0.2), ((-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1))),
         ((0, 1, 0), (0.9, 0.4, 1.0), ((-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1))),
         ((0, -1, 0), (0.3, 1.0, 1.0), ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1))))


def checker_texture():
    """A 64x64 chessboard, as RGB bytes."""
    data = bytearray()
    for y in range(64):
        for x in range(64):
            light = ((x // 8) + (y // 8)) % 2
            data += bytes((220, 220, 230) if light else (60, 70, 110))
    tex = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, 64, 64, 0, GL_RGB, GL_UNSIGNED_BYTE, bytes(data))
    return tex


def cube():
    glBegin(GL_QUADS)
    for normal, color, corners in FACES:
        glNormal3fv(normal)
        glColor3fv(color)
        for v in corners:
            glVertex3fv(v)
    glEnd()


def floor(tex):
    glEnable(GL_TEXTURE_2D)
    glBindTexture(GL_TEXTURE_2D, tex)
    glColor3f(1, 1, 1)
    glNormal3f(0, 1, 0)
    glBegin(GL_QUADS)
    for (x, z, s, t) in ((-6, -6, 0, 0), (6, -6, 3, 0), (6, 6, 3, 3), (-6, 6, 0, 3)):
        glTexCoord2f(s, t)
        glVertex3f(x, -2, z)
    glEnd()
    glDisable(GL_TEXTURE_2D)


def main():
    pygame.init()
    pygame.display.set_mode((W, H), DOUBLEBUF | OPENGL)
    pygame.display.set_caption("Cubo 3D (OpenGL)")
    glViewport(0, 0, W, H)
    glMatrixMode(GL_PROJECTION)
    gluPerspective(45, W / H, 0.5, 50.0)
    glMatrixMode(GL_MODELVIEW)
    glEnable(GL_DEPTH_TEST)
    glEnable(GL_LIGHTING)
    glEnable(GL_LIGHT0)
    glEnable(GL_COLOR_MATERIAL)
    glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
    glClearColor(0.08, 0.09, 0.16, 1)
    tex = checker_texture()
    spheres = glGenLists(1)                      # a display list: recorded once, drawn every frame
    glNewList(spheres, GL_COMPILE)
    q = gluNewQuadric()
    for i in range(6):
        a = i * math.pi / 3
        glPushMatrix()
        glTranslatef(4 * math.cos(a), -1.4, 4 * math.sin(a))
        glColor3f(0.5 + 0.5 * math.cos(a), 0.6, 0.5 + 0.5 * math.sin(a))
        gluSphere(q, 0.5, 10, 8)
        glPopMatrix()
    glEndList()
    yaw, pitch, angle = 30.0, 20.0, 0.0
    wire = False
    clock = pygame.time.Clock()
    frames, t0 = 0, pygame.time.get_ticks()
    while True:
        for ev in pygame.event.get():
            if ev.type == QUIT or (ev.type == KEYDOWN and ev.key == K_ESCAPE):
                return
            if ev.type == KEYDOWN:
                if ev.key == K_w:
                    wire = not wire
                    glPolygonMode(GL_FRONT_AND_BACK, GL_LINE if wire else GL_FILL)
                elif ev.key == K_l:
                    (glDisable if glIsEnabled(GL_LIGHTING) else glEnable)(GL_LIGHTING)
        keys = pygame.key.get_pressed()
        yaw += (keys[K_RIGHT] - keys[K_LEFT]) * 3
        pitch = max(-10, min(80, pitch + (keys[K_DOWN] - keys[K_UP]) * 2))
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        glTranslatef(0, 0, -12)
        glRotatef(pitch, 1, 0, 0)
        glRotatef(yaw, 0, 1, 0)
        glLightfv(GL_LIGHT0, GL_POSITION, (4, 6, 5, 1))
        floor(tex)
        glCallList(spheres)
        glPushMatrix()
        glRotatef(angle, 1, 1, 0)
        cube()
        glPopMatrix()
        pygame.display.flip()
        angle += 3
        frames += 1
        if frames % 30 == 0:
            secs = (pygame.time.get_ticks() - t0) / 1000
            pygame.display.set_caption("Cubo 3D - %.1f fps" % (frames / secs))
        clock.tick(60)


main()
