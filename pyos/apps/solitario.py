# pyos-app
# name: Solitario
# icon: solitario
# mode: window
#
# Klondike patience. Drag cards to move them; click the deck to turn one card;
# double-click a card to send it up to its pile. Build the four piles from
# the ace to the king of each suit.
import random
import time
import pygame
from desktop import theme as T, ui
from desktop.wm import App as Base

W, H = 72, 100                      # card size
GAP = 14
SUITS = "♠♥♦♣"  # spades, hearts, diamonds, clubs
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
TOP = 16                            # y of the deck and the piles
TABLE = TOP + H + 22                # y of the seven columns
FELT = (30, 110, 70)


def red(card):
    return card[1] in (1, 2)


class App(Base):
    title = "Solitario"
    size = (7 * (W + GAP) + GAP, 560)
    resizable = False

    def __init__(self, win):
        Base.__init__(self, win)
        self.deal()
        self.drag = None            # (cards, source, mouse dx, dy, x, y)
        self.last_click = (0, None)

    def deal(self):
        cards = [(r, s) for s in range(4) for r in range(13)]
        _shuffle(cards)
        self.columns = []           # each: [(card, face_up)]
        for i in range(7):
            col = [(cards.pop(), False) for _ in range(i)]
            col.append((cards.pop(), True))
            self.columns.append(col)
        self.stock = cards
        self.waste = []
        self.piles = [[] for _ in range(4)]
        self.moves = 0
        self.won = False
        self.started = time.ticks_ms()

    # ---- where things are ----
    def stock_rect(self):
        return pygame.Rect(GAP, TOP, W, H)

    def waste_rect(self):
        return pygame.Rect(GAP * 2 + W, TOP, W, H)

    def pile_rect(self, i):
        return pygame.Rect(GAP + (3 + i) * (W + GAP), TOP, W, H)

    def column_x(self, i):
        return GAP + i * (W + GAP)

    def card_y(self, col, k):
        y = TABLE
        for j in range(k):
            y += 26 if col[j][1] else 10
        return y

    # ---- drawing ----
    def draw_card(self, surf, card, x, y, face_up=True):
        r = pygame.Rect(x, y, W, H)
        pygame.draw.rect(surf, (20, 70, 45), r.move(2, 2), 0, 8)            # shadow
        if not face_up:
            pygame.draw.rect(surf, (40, 80, 170), r, 0, 8)
            pygame.draw.rect(surf, (255, 255, 255), r.inflate(-10, -10), 2, 6)
            for k in range(3):
                pygame.draw.circle(surf, (90, 130, 220), (r.centerx, r.y + 30 + k * 20), 6)
            return
        pygame.draw.rect(surf, (255, 255, 255), r, 0, 8)
        pygame.draw.rect(surf, (200, 200, 200), r, 1, 8)
        color = (200, 30, 40) if red(card) else (20, 20, 30)
        label = RANKS[card[0]] + SUITS[card[1]]
        ui.text(surf, label, x + 6, y + 4, color, ui.font(15, bold=True))
        big = ui.font(44)
        ui.text(surf, SUITS[card[1]], r.centerx, r.centery - 22, color, big, center=True)

    def draw(self, surf):
        surf.fill(FELT)
        s = self.stock_rect()
        if self.stock:
            self.draw_card(surf, None, s.x, s.y, False)
        else:
            pygame.draw.rect(surf, (60, 140, 95), s, 2, 8)
            ui.text(surf, "↻", s.centerx, s.centery - 12, (200, 230, 210), ui.font(24), center=True)
        if self.waste and not (self.drag and self.drag[1] == ("waste",)):
            w = self.waste_rect()
            self.draw_card(surf, self.waste[-1], w.x, w.y)
        for i in range(4):
            p = self.pile_rect(i)
            pygame.draw.rect(surf, (60, 140, 95), p, 2, 8)
            ui.text(surf, SUITS[i], p.centerx, p.centery - 22, (60, 140, 95), ui.font(44), center=True)
            pile = self.piles[i]
            if self.drag and self.drag[1] == ("pile", i):
                pile = pile[:-1]
            if pile:
                self.draw_card(surf, pile[-1], p.x, p.y)
        for i, col in enumerate(self.columns):
            x = self.column_x(i)
            pygame.draw.rect(surf, (60, 140, 95), (x, TABLE, W, H), 2, 8)
            hide_from = len(col)
            if self.drag and self.drag[1][0] == "column" and self.drag[1][1] == i:
                hide_from = self.drag[1][2]
            for k, (card, up) in enumerate(col[:hide_from]):
                self.draw_card(surf, card, x, self.card_y(col, k), up)
        if self.drag:
            cards, _, dx, dy, mx, my = self.drag
            for k, card in enumerate(cards):
                self.draw_card(surf, card, mx - dx, my - dy + 26 * k)
        secs = (time.ticks_ms() - self.started) // 1000
        ui.text(surf, "Movimientos: %d    Tiempo: %d:%02d    (F2: partida nueva)" % (self.moves, secs // 60, secs % 60),
                GAP, self.win.h - 24, (220, 240, 225))
        if self.won:
            pygame.draw.rect(surf, (255, 255, 255), (self.win.w // 2 - 150, 220, 300, 80), 0, 14)
            ui.text(surf, "¡Ganaste!", self.win.w // 2, 236, (30, 110, 70), ui.font(24, bold=True), center=True)
            ui.text(surf, "F2 para jugar otra vez", self.win.w // 2, 270, T.MUTED, center=True)

    # ---- rules ----
    def fits_pile(self, card, i):
        pile = self.piles[i]
        return card[1] == i and card[0] == (pile[-1][0] + 1 if pile else 0)

    def fits_column(self, card, i):
        col = self.columns[i]
        if not col:
            return card[0] == 12                         # only a king on an empty column
        top, up = col[-1]
        return up and top[0] == card[0] + 1 and red(top) != red(card)

    def take(self, source, count):
        if source[0] == "waste":
            return [self.waste.pop()]
        if source[0] == "pile":
            return [self.piles[source[1]].pop()]
        col = self.columns[source[1]]
        cards = [c for c, _ in col[source[2]:]]
        del col[source[2]:]
        if col and not col[-1][1]:
            col[-1] = (col[-1][0], True)                 # turn the card that is left on top
        return cards

    def auto_pile(self, card, source):
        for i in range(4):
            if self.fits_pile(card, i):
                self.take(source, 1)
                self.piles[i].append(card)
                self.moves += 1
                self.won = all(len(p) == 13 for p in self.piles)
                return True
        return False

    # ---- events ----
    def pick(self, pos):
        """(cards, source, card x, card y) under the mouse, or None."""
        if self.waste and self.waste_rect().collidepoint(pos):
            r = self.waste_rect()
            return [self.waste[-1]], ("waste",), r.x, r.y
        for i in range(4):
            if self.piles[i] and self.pile_rect(i).collidepoint(pos):
                r = self.pile_rect(i)
                return [self.piles[i][-1]], ("pile", i), r.x, r.y
        for i, col in enumerate(self.columns):
            x = self.column_x(i)
            if not x <= pos[0] < x + W:
                continue
            for k in range(len(col) - 1, -1, -1):
                y = self.card_y(col, k)
                if y <= pos[1] < y + H and col[k][1]:
                    return [c for c, _ in col[k:]], ("column", i, k), x, y
        return None

    def event(self, ev, pos):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_F2:
            self.deal()
            return True
        if pos is None:
            return False
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.stock_rect().collidepoint(pos):
                if self.stock:
                    self.waste.append(self.stock.pop())
                else:
                    self.stock, self.waste = list(reversed(self.waste)), []
                self.moves += 1
                return True
            got = self.pick(pos)
            if got is None:
                return False
            cards, source, x, y = got
            now = time.ticks_ms()
            if self.last_click[1] == source and now - self.last_click[0] < 450 and len(cards) == 1:
                self.last_click = (0, None)
                return self.auto_pile(cards[0], source)
            self.last_click = (now, source)
            self.drag = (cards, source, pos[0] - x, pos[1] - y, pos[0], pos[1])
            return True
        if ev.type == pygame.MOUSEMOTION and self.drag:
            cards, source, dx, dy, _, _ = self.drag
            self.drag = (cards, source, dx, dy, pos[0], pos[1])
            return True
        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and self.drag:
            cards, source, dx, dy, mx, my = self.drag
            self.drag = None
            drop = pygame.Rect(mx - dx, my - dy, W, H)
            if len(cards) == 1:
                for i in range(4):
                    if drop.colliderect(self.pile_rect(i)) and self.fits_pile(cards[0], i):
                        self.take(source, 1)
                        self.piles[i].append(cards[0])
                        self.moves += 1
                        self.won = all(len(p) == 13 for p in self.piles)
                        return True
            for i, col in enumerate(self.columns):
                x = self.column_x(i)
                last_y = self.card_y(col, len(col) - 1) if col else TABLE
                if drop.colliderect(pygame.Rect(x, last_y, W, H)) and self.fits_column(cards[0], i) \
                        and not (source[0] == "column" and source[1] == i):
                    moved = self.take(source, len(cards))
                    col.extend((c, True) for c in moved)
                    self.moves += 1
                    return True
            return True
        return False


def _shuffle(items):
    for i in range(len(items) - 1, 0, -1):
        j = random.randint(0, i)
        items[i], items[j] = items[j], items[i]
