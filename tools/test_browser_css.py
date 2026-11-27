"""The browser's CSS, layout and SVG on this PC (CPython + pygame), no network:
the modern CSS that real pages use (custom properties, calc(), @layer,
Tailwind's escaped classes, :where(), media queries, flex, grid...).

    python tools/test_browser_css.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pyos" / "lib"))
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402
import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((10, 10))


class _Font(pygame.font.Font):          # SnakeyOS's fonts take attributes; the PC's do not
    pass


pygame.font.SysFont = lambda name, size, bold=False, italic=False: _Font(None, size)

from browser import css, html, layout  # noqa: E402
from imaging import svg  # noqa: E402

check = T.check


def styled(page, sheet_text, width=1000):
    doc = html.parse(page)
    sheet = css.StyleSheet()
    sheet.add(sheet_text, width)
    css.compute(doc, [sheet], width)
    return doc


def by_id(doc, ident):
    for n in doc.iter():
        if n.attrs.get("id") == ident:
            return n


class FakePage:
    images, widgets, toggles = {}, {}, {}

    def resolve(self, href):
        return href

    def form_of(self, node):
        return None


def main():
    d = styled('<div id=a>x</div><p id=b>y</p>',
               ':root { --c: #ff0000; --w: 10px } #a { color: var(--c); padding: calc(var(--w) * 2) }'
               '#b { color: var(--nope, blue) }')
    check("custom properties and var() with a fallback",
          by_id(d, "a").style["color"] == (255, 0, 0) and by_id(d, "b").style["color"] == (0, 0, 255))
    check("calc() inside a shorthand", by_id(d, "a").style.get("padding-left") == 20)
    check("min(), max(), clamp()", css.length("min(90%, 1200px)", 16, 1000) == 900
          and css.length("clamp(1rem, 2.5vw, 3rem)") == 25 and css.length("max(10px, 2em)", 16) == 32)
    d = styled('<p id=a class="md:hidden">x</p><p id=b class="w-1/2">y</p>',
               '@layer utilities { .md\\:hidden { display: none } .w-1\\/2 { width: 50% } }')
    check("Tailwind: @layer and escaped class names", by_id(d, "a").style["display"] == "none"
          and by_id(d, "b").style["width"] == ("%", 50.0))
    d = styled('<html class=dark><p id=a class=t>x</p></html>', '.t:where(.dark, .dark *) { color: #070 }')
    check(":where() with a descendant selector inside", by_id(d, "a").style["color"] == (0, 119, 0))
    check("media queries: light colours, the width, ranges",
          not css._media_ok("(prefers-color-scheme: dark)", 1000) and css._media_ok("(min-width: 768px)", 1000)
          and not css._media_ok("(400px <= width < 800px)", 1000) and not css._media_ok("print", 1000))
    d = styled('<ul><li id=a>1</li><li id=b>2</li><li id=c>3</li></ul>', 'li:nth-child(2n) { color: red }')
    check(":nth-child(2n) for real", by_id(d, "b").style["color"] == (255, 0, 0)
          and by_id(d, "a").style["color"] != (255, 0, 0))
    check("oklch() colours (Tailwind 4)", css.color("oklch(0.62 0.21 259)")[2] > 200)
    d = styled('<h1 id=a>x</h1>', '#a { background: linear-gradient(90deg, #e33, #33e); background-clip: text;'
               ' -webkit-text-fill-color: transparent }')
    check("gradient text: drawn in the gradient's colour, no box",
          by_id(d, "a").style["color"] == (238, 51, 51) and "background-color" not in by_id(d, "a").style)
    page = '<div id=g><div>1</div><div>2</div><div>3</div><div>4</div></div>'
    d = styled(page, '#g { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px }')
    lay = layout.Layout(FakePage(), 640).run(d)
    xs = sorted(set(it.x for it in lay.items if it.kind == "text"))
    check("grid: three columns, then a new row", len(xs) == 3, xs)
    d = styled('<div id=f><span id=a>uno</span><div id=b>dos</div></div>',
               '#f { display: flex } #a { display: block; width: 200px } #b { flex: 1 }')
    lay = layout.Layout(FakePage(), 800).run(d)
    words = {it.data: it.x for it in lay.items if it.kind == "text"}
    check("flex: a fixed item and one that takes the rest, side by side", words.get("dos", 0) >= 200, words)
    d = styled('<details id=d><summary>Mas</summary><p id=p>oculto</p></details>', '')
    check("<details> closed until clicked", by_id(d, "p").style["display"] == "none")
    surf = svg.render_text(b'<svg viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="2">'
                           b'<circle cx="12" cy="12" r="9"/></svg>', 48, 48)
    ring = surf.get_at((24, 6))[3] > 100 and surf.get_at((24, 24))[3] == 0
    check("SVG: a circle drawn as a line (empty inside)", ring)
    surf = svg.render_text(b'<svg viewBox="0 0 100 100"><path fill-rule="evenodd" fill="red" '
                           b'd="M50 5a45 45 0 1 0 .1 0zM50 30a20 20 0 1 1-.1 0z"/></svg>', 100, 100)
    check("SVG: arcs and an even-odd hole", surf.get_at((50, 15))[0] > 200 and surf.get_at((50, 50))[3] == 0)
    print("%d/%d passed" % (sum(T.CHECKS), len(T.CHECKS)))
    return all(T.CHECKS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
