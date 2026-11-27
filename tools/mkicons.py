"""The SnakeyOS icon pack and wallpaper, made from assets/iconpack (needs Pillow):

    /share/icons/<app>-<size>.png    every app icon at the sizes the desktop draws
    /share/images/snakeyos.jpg       the default wallpaper

    python tools/mkicons.py
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "assets" / "iconpack"
OUT = ROOT / "pyos" / "share" / "icons"
SIZES = (20, 32, 44, 52, 56, 64, 72, 96)
S = 512
ICONS = [
 ("files",145,141,112),("terminal",317,141,104),("settings",483,141,104),("clock",641,141,104),
 ("sysmon",800,141,104),("disks",960,141,104),("store",1123,141,108),
 ("editor",139,345,92),("images",278,345,92),("paint",418,345,92),("music",551,345,92),
 ("calc",123,547,86),("browser",241,547,86),("bloc",478,547,86),("escritor",595,547,86),
 ("sheet",709,547,86),("presentaciones",822,547,86),("calendario",938,547,86),("notes",1058,547,86),
 ("tareas",1181,547,86),("recortes",1298,547,86),("caracteres",1424,547,86),
 ("lupa",123,676,86),("teclado",241,676,86),
 ("snake",139,885,90),("blocks",277,885,90),("mines",419,885,90),("solitario",557,885,90),
]


def cut(img, cx, cy, s, thresh=34):
    box = (cx - s//2, cy - s//2, cx + s//2, cy + s//2)
    c = img.crop(box)
    # background: what a flood fill from the border reaches (smooth glass / wallpaper)
    mark = c.copy()
    W, H = c.size
    seeds = [(x, 0) for x in range(0, W, 6)] + [(x, H-1) for x in range(0, W, 6)] + \
            [(0, y) for y in range(0, H, 6)] + [(W-1, y) for y in range(0, H, 6)]
    for sd in seeds:
        if mark.getpixel(sd) != (255, 0, 255):
            ImageDraw.floodfill(mark, sd, (255, 0, 255), thresh=thresh)
    mask = Image.new('L', c.size, 255)
    px = mark.load(); mp = mask.load()
    for y in range(H):
        for x in range(W):
            if px[x, y] == (255, 0, 255):
                mp[x, y] = 0
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    out = c.convert('RGBA'); out.putalpha(mask)
    return out

def tile(img, cx, cy, s, inset=0.06, radius=0.24):
    box = (cx - s//2, cy - s//2, cx + s//2, cy + s//2)
    c = img.crop(box).convert('RGBA').resize((512, 512), Image.LANCZOS)
    m = Image.new('L', (512, 512), 0)
    k = int(512 * inset)
    ImageDraw.Draw(m).rounded_rectangle((k, k, 511 - k, 511 - k), radius=int(512 * radius), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(1.2))
    c.putalpha(m)
    return c


def glass_tile(top, bottom):
    t = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    g = Image.new('RGBA', (S, S))
    gd = ImageDraw.Draw(g)
    for y in range(S):
        f = y / S
        gd.line([(0, y), (S, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * f) for i in range(3)) + (255,))
    m = Image.new('L', (S, S), 0)
    k = int(S * 0.06)
    ImageDraw.Draw(m).rounded_rectangle((k, k, S - 1 - k, S - 1 - k), radius=int(S * 0.24), fill=255)
    t.paste(g, (0, 0), m.filter(ImageFilter.GaussianBlur(1.2)))
    # a soft top highlight, as glass
    hl = Image.new('L', (S, S), 0)
    ImageDraw.Draw(hl).rounded_rectangle((k + 6, k + 6, S - 7 - k, S // 2), radius=int(S * 0.2), fill=60)
    white = Image.new('RGBA', (S, S), (255, 255, 255, 255))
    t.paste(white, (0, 0), Image.composite(hl.filter(ImageFilter.GaussianBlur(18)), Image.new('L', (S, S), 0), m))
    return t

SHAPE = ("files", "store")          # no tile: cut out by colour


def pywin_icon():
    # PyWin: the Windows 11 logo (four squares) in Python's blue and yellow
    t = glass_tile((236, 242, 252), (205, 218, 240))
    d = ImageDraw.Draw(t)
    q = 118; gap = 14; x0 = (S - 2 * q - gap) // 2; y0 = x0
    BLUE, YELLOW = (55, 118, 171), (255, 212, 59)
    for i, (dx, dy) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
        col = BLUE if (dx + dy) % 2 == 0 else YELLOW
        d.rounded_rectangle((x0 + dx * (q + gap), y0 + dy * (q + gap), x0 + dx * (q + gap) + q, y0 + dy * (q + gap) + q),
                            radius=10, fill=col)
    return t


def wallpaper():
    # the wallpaper: blue above, yellow below, a glassy S-wave between, the logo in the middle
    W, H = 1920, 1080
    wp = Image.new('RGB', (W, H))
    px = wp.load()
    for y in range(H):
        for x in range(W):
            px[x, y] = (40 + int(30 * x / W), 100 + int(40 * y / H), 220 - int(20 * y / H))
    blue = wp
    yel = Image.new('RGB', (W, H))
    yd = ImageDraw.Draw(yel)
    for y in range(H):
        yd.line([(0, y), (W, y)], fill=(255, 205 - int(40 * y / H), 60 - int(20 * y / H)))
    mask = Image.new('L', (W, H), 0)
    pts = []
    for x in range(0, W + 20, 20):
        t_ = x / W
        yv = H * (0.62 + 0.18 * math.sin(math.pi * (t_ * 1.2 + 0.15)) - 0.10 * t_)
        pts.append((x, yv))
    ImageDraw.Draw(mask).polygon(pts + [(W, H), (0, H)], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(6))
    out = Image.composite(yel, blue, mask)
    # a light glassy band along the wave
    band = Image.new('L', (W, H), 0)
    ImageDraw.Draw(band).line(pts, fill=255, width=70)
    band = band.filter(ImageFilter.GaussianBlur(40))
    out = Image.composite(Image.new('RGB', (W, H), (235, 242, 255)), out, band.point(lambda v: v * 0.55))
    # a second, higher light wave in the blue
    mask2 = Image.new('L', (W, H), 0)
    pts2 = [(x, H * (0.35 + 0.22 * math.sin(math.pi * (x / W * 1.1 - 0.1)))) for x in range(0, W + 20, 20)]
    ImageDraw.Draw(mask2).line(pts2, fill=255, width=160)
    out = Image.composite(Image.new('RGB', (W, H), (120, 170, 245)), out, mask2.filter(ImageFilter.GaussianBlur(80)).point(lambda v: v * 0.5))
    logo = Image.open(ROOT / 'pyos' / 'share' / 'pyos' / 'logo-256.png').convert('RGBA').resize((200, 200), Image.LANCZOS)
    lg = logo.copy(); lg.putalpha(logo.getchannel('A').point(lambda v: v * 0.82))
    out = out.convert('RGBA'); out.alpha_composite(lg, (W // 2 - 100, H // 2 - 130))
    return out.convert("RGB")


# ---- the apps the pack has no icon for: drawn in its glass style ----

def _poly(d, pts, fill):
    d.polygon([(int(x), int(y)) for x, y in pts], fill=fill)


def videos_icon():
    t = glass_tile((52, 56, 72), (18, 20, 30))
    d = ImageDraw.Draw(t)
    d.rounded_rectangle((130, 160, 382, 352), radius=36, fill=(255, 255, 255, 235))
    _poly(d, [(225, 205), (225, 307), (310, 256)], (40, 44, 60))
    for x in (148, 214, 280, 346):
        d.rounded_rectangle((x - 14, 132, x + 14, 150), radius=6, fill=(255, 255, 255, 200))
    return t


def updates_icon():
    t = glass_tile((80, 160, 255), (30, 100, 220))
    d = ImageDraw.Draw(t)
    for start in (200, 20):
        d.arc((136, 136, 376, 376), start, start + 130, fill=(255, 255, 255), width=34)
    for a in (330, 150):
        r = math.radians(a)
        cx, cy = 256 + 120 * math.cos(r), 256 + 120 * math.sin(r)
        tang = r + math.pi / 2
        _poly(d, [(cx + 46 * math.cos(tang), cy + 46 * math.sin(tang)),
                  (cx + 36 * math.cos(r), cy + 36 * math.sin(r)),
                  (cx - 36 * math.cos(r), cy - 36 * math.sin(r))], (255, 255, 255))
    return t


def about_icon():
    t = glass_tile((246, 248, 252), (214, 224, 240))
    logo = Image.open(ROOT / "pyos" / "share" / "pyos" / "logo-256.png").convert("RGBA").resize((300, 300), Image.LANCZOS)
    t.alpha_composite(logo, (106, 106))
    return t


def space_icon():
    t = glass_tile((24, 28, 70), (8, 10, 30))
    d = ImageDraw.Draw(t)
    import random
    rnd = random.Random(3)
    for _ in range(40):
        x, y = rnd.randint(70, 440), rnd.randint(70, 440)
        r = rnd.choice((2, 3, 4))
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, rnd.randint(140, 255)))
    # a rocket going up and right
    _poly(d, [(330, 150), (360, 182), (230, 312), (198, 280)], (240, 244, 252))
    _poly(d, [(330, 150), (380, 132), (360, 182)], (255, 90, 90))
    _poly(d, [(198, 280), (170, 286), (214, 242)], (55, 118, 171))
    _poly(d, [(230, 312), (224, 340), (268, 296)], (55, 118, 171))
    d.ellipse((276, 196, 306, 226), fill=(55, 118, 171))
    _poly(d, [(208, 300), (160, 366), (226, 318)], (255, 212, 59))
    return t


def ball_icon():
    t = glass_tile((120, 220, 140), (40, 160, 90))
    d = ImageDraw.Draw(t)
    d.ellipse((150, 150, 362, 362), fill=(255, 255, 255))
    d.ellipse((150, 150, 362, 362), outline=(30, 40, 50), width=10)
    _poly(d, [(256, 214), (296, 243), (281, 290), (231, 290), (216, 243)], (30, 40, 50))
    for a in range(5):
        r = math.radians(a * 72 - 90)
        x, y = 256 + 92 * math.cos(r), 256 + 92 * math.sin(r)
        d.line([(256 + 40 * math.cos(r), 256 + 40 * math.sin(r)), (x, y)], fill=(30, 40, 50), width=8)
    d.ellipse((180, 175, 225, 205), fill=(255, 255, 255, 160))
    return t


def cube_icon():
    t = glass_tile((40, 44, 64), (14, 16, 26))
    d = ImageDraw.Draw(t)
    top = [(256, 120), (380, 190), (256, 260), (132, 190)]
    left = [(132, 190), (256, 260), (256, 400), (132, 330)]
    right = [(256, 260), (380, 190), (380, 330), (256, 400)]
    _poly(d, top, (120, 170, 235))
    _poly(d, left, (55, 118, 171))
    _poly(d, right, (255, 212, 59))
    for f in (top, left, right):
        d.line([(int(x), int(y)) for x, y in f + [f[0]]], fill=(255, 255, 255, 160), width=4)
    return t


def exe_icon():
    t = glass_tile((236, 242, 252), (205, 218, 240))
    d = ImageDraw.Draw(t)
    d.rounded_rectangle((110, 130, 402, 380), radius=26, fill=(255, 255, 255), outline=(150, 166, 190), width=6)
    d.rounded_rectangle((110, 130, 402, 180), radius=26, fill=(55, 118, 171))
    d.rectangle((110, 160, 402, 180), fill=(55, 118, 171))
    for i, x in enumerate((360, 330, 300)):
        d.ellipse((x - 9, 146, x + 9, 164), fill=(255, 255, 255) if i else (255, 212, 59))
    q, g, x0, y0 = 58, 10, 194, 206
    for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        col = (55, 118, 171) if (dx + dy) % 2 == 0 else (255, 212, 59)
        d.rounded_rectangle((x0 + dx * (q + g), y0 + dy * (q + g), x0 + dx * (q + g) + q, y0 + dy * (q + g) + q),
                            radius=6, fill=col)
    return t


def trash_icon():
    """No tile (as on the mockup): a white bin."""
    t = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(t)
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((150, 150, 362, 450), radius=40, fill=(0, 0, 0, 90))
    t.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)), (0, 10))
    _poly(d, [(140, 140), (372, 140), (348, 440), (164, 440)], (245, 247, 250))
    for x in (200, 256, 312):
        d.line([(x, 180), (x + (x - 256) * 0.12, 410)], fill=(205, 212, 222), width=12)
    d.rounded_rectangle((118, 104, 394, 150), radius=18, fill=(232, 236, 242), outline=(200, 206, 216), width=4)
    d.rounded_rectangle((216, 80, 296, 112), radius=12, fill=(220, 226, 234))
    return t


DRAWN = {"videos": videos_icon, "updates": updates_icon, "about": about_icon, "espacio": space_icon,
         "pelota": ball_icon, "cubo": cube_icon, "exe": exe_icon, "trash": trash_icon}


def save(name, big):
    for size in SIZES:
        big.resize((size, size), Image.LANCZOS).save(OUT / ("%s-%d.png" % (name, size)), optimize=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    src = Image.open(PACK / "pack.png").convert("RGB")
    for name, cx, cy, s in ICONS:
        big = cut(src, cx, cy, s).resize((512, 512), Image.LANCZOS) if name in SHAPE else tile(src, cx, cy, s)
        save(name, big)
    j = Image.open(PACK / "jeancode.jpg").convert("RGB")
    save("jeancode", tile(j, 129, 120, 236, inset=0.05, radius=0.22))
    save("pywin", pywin_icon())
    for name, f in DRAWN.items():
        save(name, f())
    wallpaper().resize((1280, 720), Image.LANCZOS).save(ROOT / "pyos" / "share" / "images" / "snakeyos.jpg", quality=88)
    print("icons:", len(list(OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
