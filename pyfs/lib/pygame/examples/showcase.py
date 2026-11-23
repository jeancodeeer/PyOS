# What the pygame API can draw: run('/lib/pygame/examples/showcase.py')
# Esc or Ctrl+Q quits.
import math
import pygame

pygame.init()
screen = pygame.display.set_mode((640, 480))
clock = pygame.time.Clock()
title = pygame.font.SysFont(None, 48)
small = pygame.font.SysFont(None, 24)

stars = [((i * 97) % 640, (i * 53) % 480, 1 + i % 3) for i in range(90)]
ship = pygame.Surface((40, 24), pygame.SRCALPHA)
pygame.draw.polygon(ship, (240, 240, 235), [(0, 12), (40, 0), (30, 12), (40, 24)])
pygame.draw.polygon(ship, (255, 120, 40), [(30, 9), (40, 12), (30, 15)])

t = 0
running = True
while running:
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
            running = False
    screen.fill((8, 8, 12))
    for x, y, s in stars:                                    # parallax star field
        pygame.draw.rect(screen, (90 * s, 90 * s, 80 * s), ((x - t * s) % 640, y, s, s))
    pygame.draw.circle(screen, (60, 70, 160), (470, 300), 110)          # planet
    pygame.draw.circle(screen, (90, 110, 210), (450, 280), 70)
    pygame.draw.ellipse(screen, (220, 200, 140), (330, 285, 280, 34), 3)  # ring
    pygame.draw.circle(screen, (240, 230, 200), (130, 110), 26)           # moon
    for k in range(5):                                       # orbiting dots
        a = t / 30 + k * 1.2566
        pygame.draw.circle(screen, (255, 200, 80),
                           (int(470 + math.cos(a) * 160), int(300 + math.sin(a) * 40)), 4)
    angle = math.sin(t / 25) * 15
    s = pygame.transform.rotate(ship, angle)
    screen.blit(s, s.get_rect(center=(200, 330 + int(math.sin(t / 20) * 20))))
    screen.blit(title.render("import pygame", True, (242, 241, 236)), (24, 400))
    screen.blit(small.render("no OS underneath -- PyKernel", True, (150, 150, 145)), (24, 440))
    pygame.draw.line(screen, (242, 241, 236), (24, 434), (330, 434), 1)
    pygame.display.flip()
    clock.tick(30)
    t += 1

pygame.quit()
