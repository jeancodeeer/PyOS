# A small pygame demo: run('/lib/pygame/examples/bounce.py')
# Arrow keys move the paddle, the mouse moves it too; Esc or Ctrl+Q quits.
import pygame

pygame.init()
screen = pygame.display.set_mode((640, 480))
pygame.display.set_caption("bounce")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 32)

ball = pygame.Rect(300, 200, 16, 16)
speed = [4, 3]
paddle = pygame.Rect(270, 440, 100, 12)
score = 0
running = True
while running:
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            running = False
        elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            running = False
        elif ev.type == pygame.MOUSEMOTION:
            paddle.centerx = ev.pos[0]
    keys = pygame.key.get_pressed()
    if keys[pygame.K_LEFT]:
        paddle.x -= 8
    if keys[pygame.K_RIGHT]:
        paddle.x += 8
    paddle.clamp_ip(screen.get_rect())

    ball.move_ip(speed)
    if ball.left < 0 or ball.right > 640:
        speed[0] = -speed[0]
    if ball.top < 0:
        speed[1] = -speed[1]
    if ball.colliderect(paddle) and speed[1] > 0:
        speed[1] = -speed[1]
        score += 1
    if ball.top > 480:
        ball.topleft = (300, 200)
        score = 0

    screen.fill((20, 24, 40))
    pygame.draw.rect(screen, (240, 200, 60), paddle, border_radius=4)
    pygame.draw.circle(screen, (255, 255, 255), ball.center, 8)
    screen.blit(font.render("score %d" % score, True, (200, 220, 255)), (12, 10))
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
