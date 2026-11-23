# Three small games: Snake, Blocks (falling pieces) and Mines.
import random
import pygame
from desktop import theme as T, ui
from desktop.wm import App


class Snake(App):
    title = "Serpiente"
    size = (420, 440)
    resizable = False
    CELL, W, H = 20, 21, 20

    def __init__(self, win):
        App.__init__(self, win)
        self.reset()

    def reset(self):
        self.body = [(10, 10), (9, 10), (8, 10)]
        self.dir = (1, 0)
        self.food = self._place()
        self.next = 0
        self.alive = True
        self.started = False
        self.score = 0
        self.speed = 140

    def _place(self):
        while True:
            p = (random.randrange(self.W), random.randrange(self.H))
            if p not in self.body:
                return p

    def tick(self, now):
        if not self.alive or not self.started or now < self.next:
            return False
        self.next = now + self.speed
        hx, hy = self.body[0]
        head = (hx + self.dir[0], hy + self.dir[1])
        if not (0 <= head[0] < self.W and 0 <= head[1] < self.H) or head in self.body:
            self.alive = False
            return True
        self.body.insert(0, head)
        if head == self.food:
            self.score += 10
            self.speed = max(60, self.speed - 4)
            self.food = self._place()
        else:
            self.body.pop()
        return True

    def draw(self, surf):
        surf.fill((16, 24, 16))
        c = self.CELL
        pygame.draw.rect(surf, (200, 60, 60), (self.food[0] * c + 2, self.food[1] * c + 22, c - 4, c - 4))
        for i, (x, y) in enumerate(self.body):
            pygame.draw.rect(surf, (120, 220, 120) if i else (200, 255, 200), (x * c + 1, y * c + 21, c - 2, c - 2))
        ui.text(surf, "puntos %d" % self.score, 8, 2, (200, 230, 200))
        if not self.alive:
            ui.text(surf, "fin del juego - Enter para jugar otra vez", 40, 200, (255, 255, 255))
        elif not self.started:
            ui.text(surf, "pulsa una flecha para empezar", 90, 200, (255, 255, 255))

    def event(self, ev, pos):
        if ev.type != pygame.KEYDOWN:
            return False
        dirs = {pygame.K_UP: (0, -1), pygame.K_DOWN: (0, 1), pygame.K_LEFT: (-1, 0), pygame.K_RIGHT: (1, 0)}
        if ev.key in dirs:
            self.started = True
            d = dirs[ev.key]
            if (d[0] + self.dir[0], d[1] + self.dir[1]) != (0, 0):
                self.dir = d
            return True
        if ev.key == pygame.K_RETURN and not self.alive:
            self.reset()
            return True
        return False


PIECES = [[(0, 0), (1, 0), (2, 0), (3, 0)], [(0, 0), (1, 0), (0, 1), (1, 1)], [(1, 0), (0, 1), (1, 1), (2, 1)],
          [(0, 0), (0, 1), (1, 1), (2, 1)], [(2, 0), (0, 1), (1, 1), (2, 1)], [(1, 0), (2, 0), (0, 1), (1, 1)],
          [(0, 0), (1, 0), (1, 1), (2, 1)]]
COLORS = [(80, 200, 230), (240, 210, 60), (170, 90, 220), (60, 100, 230), (240, 150, 40), (80, 200, 90), (220, 70, 70)]


class Blocks(App):
    title = "Bloques"
    size = (330, 460)
    resizable = False
    W, H, C = 10, 20, 21

    def __init__(self, win):
        App.__init__(self, win)
        self.reset()

    def reset(self):
        self.grid = [[None] * self.W for _ in range(self.H)]
        self.score = self.lines = 0
        self.over = False
        self.next_t = 0
        self.spawn()

    def spawn(self):
        i = random.randrange(len(PIECES))
        self.cells, self.color = list(PIECES[i]), COLORS[i]
        self.px, self.py = 3, 0
        if not self.fits(self.cells, self.px, self.py):
            self.over = True

    def fits(self, cells, px, py):
        for x, y in cells:
            gx, gy = px + x, py + y
            if gx < 0 or gx >= self.W or gy >= self.H or (gy >= 0 and self.grid[gy][gx]):
                return False
        return True

    def lock(self):
        for x, y in self.cells:
            if self.py + y >= 0:
                self.grid[self.py + y][self.px + x] = self.color
        full = [r for r in range(self.H) if all(self.grid[r])]
        for r in full:
            del self.grid[r]
            self.grid.insert(0, [None] * self.W)
        self.lines += len(full)
        self.score += (0, 100, 300, 500, 800)[len(full)]
        self.spawn()

    def tick(self, now):
        if self.over or now < self.next_t:
            return False
        self.next_t = now + max(120, 600 - self.lines * 20)
        if self.fits(self.cells, self.px, self.py + 1):
            self.py += 1
        else:
            self.lock()
        return True

    def rotate(self):
        rot = [(-y, x) for x, y in self.cells]
        mx, my = min(x for x, _ in rot), min(y for _, y in rot)
        rot = [(x - mx, y - my) for x, y in rot]
        for dx in (0, -1, 1, -2):
            if self.fits(rot, self.px + dx, self.py):
                self.cells, self.px = rot, self.px + dx
                return

    def draw(self, surf):
        surf.fill((20, 22, 30))
        c, ox, oy = self.C, 8, 20
        pygame.draw.rect(surf, (40, 44, 56), (ox - 2, oy - 2, self.W * c + 4, self.H * c + 4), 2)
        for y in range(self.H):
            for x in range(self.W):
                if self.grid[y][x]:
                    pygame.draw.rect(surf, self.grid[y][x], (ox + x * c, oy + y * c, c - 1, c - 1))
        for x, y in self.cells:
            if self.py + y >= 0:
                pygame.draw.rect(surf, self.color, (ox + (self.px + x) * c, oy + (self.py + y) * c, c - 1, c - 1))
        ui.text(surf, "puntos %d  lineas %d" % (self.score, self.lines), 8, 2, (220, 224, 230))
        ui.text(surf, "flechas, arriba gira", 230, 30, (130, 134, 140))
        if self.over:
            ui.text(surf, "fin - Enter", 110, 200, (255, 255, 255))

    def event(self, ev, pos):
        if ev.type != pygame.KEYDOWN:
            return False
        if self.over:
            if ev.key == pygame.K_RETURN:
                self.reset()
            return True
        if ev.key == pygame.K_LEFT and self.fits(self.cells, self.px - 1, self.py):
            self.px -= 1
        elif ev.key == pygame.K_RIGHT and self.fits(self.cells, self.px + 1, self.py):
            self.px += 1
        elif ev.key == pygame.K_DOWN and self.fits(self.cells, self.px, self.py + 1):
            self.py += 1
        elif ev.key == pygame.K_UP:
            self.rotate()
        elif ev.key == pygame.K_SPACE:
            while self.fits(self.cells, self.px, self.py + 1):
                self.py += 1
            self.lock()
        else:
            return False
        return True


class Mines(App):
    title = "Buscaminas"
    size = (340, 380)
    resizable = False
    N, MINES, C = 12, 20, 26

    def __init__(self, win):
        App.__init__(self, win)
        self.reset()

    def reset(self):
        n = self.N
        cells = [(x, y) for x in range(n) for y in range(n)]
        self.mines = set(random.sample(cells, self.MINES)) if hasattr(random, "sample") else set(
            cells[i] for i in _pick(len(cells), self.MINES))
        self.open = set()
        self.flags = set()
        self.state = "play"

    def count(self, x, y):
        return sum((x + dx, y + dy) in self.mines for dx in (-1, 0, 1) for dy in (-1, 0, 1))

    def reveal(self, x, y):
        todo = [(x, y)]
        while todo:
            p = todo.pop()
            if p in self.open or p in self.flags:
                continue
            self.open.add(p)
            if p in self.mines:
                self.state = "lost"
                return
            if self.count(*p) == 0:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        q = (p[0] + dx, p[1] + dy)
                        if 0 <= q[0] < self.N and 0 <= q[1] < self.N:
                            todo.append(q)
        if len(self.open) == self.N * self.N - self.MINES:
            self.state = "won"

    def draw(self, surf):
        surf.fill(T.WIN_BG)
        c, ox, oy = self.C, 14, 34
        colors = [None, (40, 90, 210), (40, 150, 60), (210, 50, 50), (100, 40, 160), (140, 60, 20), (20, 140, 140),
                  (0, 0, 0), (90, 90, 90)]
        for x in range(self.N):
            for y in range(self.N):
                r = (ox + x * c, oy + y * c, c - 1, c - 1)
                p = (x, y)
                if p in self.open or (self.state == "lost" and p in self.mines):
                    pygame.draw.rect(surf, (225, 226, 230), r)
                    if p in self.mines:
                        pygame.draw.circle(surf, (20, 20, 20), (r[0] + c // 2, r[1] + c // 2), 7)
                    else:
                        n = self.count(x, y)
                        if n:
                            ui.text(surf, str(n), r[0] + 9, r[1] + 5, colors[n])
                else:
                    pygame.draw.rect(surf, (150, 160, 180), r)
                    if p in self.flags:
                        pygame.draw.polygon(surf, T.RED, [(r[0] + 8, r[1] + 5), (r[0] + 19, r[1] + 10), (r[0] + 8, r[1] + 15)])
        msg = {"play": "minas: %d   (clic derecho marca)" % (self.MINES - len(self.flags)),
               "lost": "boom! clic para empezar otra vez", "won": "ganaste! clic para jugar otra vez"}[self.state]
        ui.text(surf, msg, 14, 8, T.TEXT)

    def event(self, ev, pos):
        if ev.type != pygame.MOUSEBUTTONDOWN:
            return False
        if self.state != "play":
            self.reset()
            return True
        x, y = (pos[0] - 14) // self.C, (pos[1] - 34) // self.C
        if not (0 <= x < self.N and 0 <= y < self.N):
            return False
        if ev.button == 3:
            self.flags ^= {(x, y)}
        elif ev.button == 1:
            self.reveal(x, y)
        return True


def _pick(n, k):
    chosen = set()
    while len(chosen) < k:
        chosen.add(random.randrange(n))
    return chosen
