# pygame.sprite: Sprite, Group and collision helpers.


class Sprite:
    def __init__(self, *groups):
        self._groups = []
        if groups:
            self.add(*groups)

    def add(self, *groups):
        for g in _flat(groups):
            if g not in self._groups:
                self._groups.append(g)
                g.add_internal(self)

    def remove(self, *groups):
        for g in _flat(groups):
            if g in self._groups:
                self._groups.remove(g)
                g.remove_internal(self)

    def kill(self):
        for g in self._groups[:]:
            g.remove_internal(self)
        self._groups.clear()

    def alive(self):
        return bool(self._groups)

    def groups(self):
        return self._groups[:]

    def update(self, *args, **kw):
        pass

    def add_internal(self, group):
        if group not in self._groups:
            self._groups.append(group)

    def remove_internal(self, group):
        if group in self._groups:
            self._groups.remove(group)


DirtySprite = Sprite


def _flat(items):
    out = []
    for g in items:
        if isinstance(g, (list, tuple)):
            out.extend(_flat(g))
        else:
            out.append(g)
    return out


class Group:
    def __init__(self, *sprites):
        self._sprites = []
        self.add(*sprites)

    def sprites(self):
        return self._sprites[:]

    def add_internal(self, sprite):
        if sprite not in self._sprites:
            self._sprites.append(sprite)

    def remove_internal(self, sprite):
        if sprite in self._sprites:
            self._sprites.remove(sprite)

    def add(self, *sprites):
        for s in _flat(sprites):
            if isinstance(s, Group):
                self.add(*s.sprites())
            elif s not in self._sprites:
                self._sprites.append(s)
                s.add_internal(self)

    def remove(self, *sprites):
        for s in _flat(sprites):
            if s in self._sprites:
                self._sprites.remove(s)
                s.remove_internal(self)

    def has(self, *sprites):
        return all(s in self._sprites for s in _flat(sprites))

    def copy(self):
        return self.__class__(*self._sprites)

    def update(self, *args, **kw):
        for s in self._sprites[:]:
            s.update(*args, **kw)

    def draw(self, surface, bgsurf=None, special_flags=0):
        return [surface.blit(s.image, s.rect) for s in self._sprites]

    def clear(self, surface, background):
        for s in self._sprites:
            if callable(background):
                background(surface, s.rect)
            else:
                surface.blit(background, s.rect, s.rect)

    def empty(self):
        for s in self._sprites[:]:
            self.remove(s)

    def __len__(self):
        return len(self._sprites)

    def __iter__(self):
        return iter(self._sprites[:])

    def __contains__(self, sprite):
        return sprite in self._sprites

    def __bool__(self):
        return bool(self._sprites)

    def __repr__(self):
        return "<%s(%d sprites)>" % (self.__class__.__name__, len(self._sprites))


RenderPlain = RenderClear = RenderUpdates = OrderedUpdates = LayeredUpdates = LayeredDirty = Group


class GroupSingle(Group):
    def add(self, *sprites):
        sprites = _flat(sprites)
        if sprites:
            self.empty()
            Group.add(self, sprites[-1])

    @property
    def sprite(self):
        return self._sprites[0] if self._sprites else None


def collide_rect(a, b):
    return a.rect.colliderect(b.rect)


def collide_rect_ratio(ratio):
    def collide(a, b):
        ra = a.rect.inflate(int(a.rect.w * ratio) - a.rect.w, int(a.rect.h * ratio) - a.rect.h)
        rb = b.rect.inflate(int(b.rect.w * ratio) - b.rect.w, int(b.rect.h * ratio) - b.rect.h)
        return ra.colliderect(rb)
    return collide


def collide_circle(a, b):
    ra = getattr(a, "radius", None) or max(a.rect.w, a.rect.h) / 2
    rb = getattr(b, "radius", None) or max(b.rect.w, b.rect.h) / 2
    dx = a.rect.centerx - b.rect.centerx
    dy = a.rect.centery - b.rect.centery
    return dx * dx + dy * dy <= (ra + rb) ** 2


def collide_mask(a, b):
    return collide_rect(a, b)


def spritecollide(sprite, group, dokill, collided=None):
    test = collided or collide_rect
    hit = [s for s in group if test(sprite, s)]
    if dokill:
        for s in hit:
            s.kill()
    return hit


def spritecollideany(sprite, group, collided=None):
    test = collided or collide_rect
    for s in group:
        if test(sprite, s):
            return s
    return None


def groupcollide(groupa, groupb, dokilla, dokillb, collided=None):
    out = {}
    for s in groupa.sprites():
        hit = spritecollide(s, groupb, dokillb, collided)
        if hit:
            out[s] = hit
            if dokilla:
                s.kill()
    return out
