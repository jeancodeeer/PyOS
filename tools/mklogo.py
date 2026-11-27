"""Write the SnakeyOS logo as SVG (pyos/share/pyos/logo.svg and docs/pyos-logo.svg)
from the same shapes pyos/lib/pyos/logo.py draws with pygame.

    python tools/mklogo.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def shapes():
    src = (ROOT / "pyos" / "lib" / "pyos" / "logo.py").read_text()
    ns = {}
    exec(src.split("def _points")[0].replace("import pygame\nfrom pygame.constants import SRCALPHA\n", ""), ns)
    return ns


def svg():
    ns = shapes()

    def rgb(c):
        return "#%02x%02x%02x" % c
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 106" width="256" height="272">',
           "<title>SnakeyOS</title>"]
    for x, y, c in ns["PANES"]:
        out.append('<rect x="%d" y="%d" width="%d" height="%d" rx="6" fill="%s"/>' % (x, y, ns["PANE"], ns["PANE"], rgb(c)))
    d = "M" + " L".join("%g %g" % p for p in ns["PATH"])
    out.append('<path d="%s" fill="none" stroke="%s" stroke-width="%d" stroke-linecap="round" stroke-linejoin="round"/>'
               % (d, rgb(ns["SNAKE"]), ns["BODY"]))
    out.append('<path d="%s" fill="none" stroke="%s" stroke-width="2.6" stroke-dasharray="3 4" stroke-linecap="round" '
               'stroke-linejoin="round" stroke-dashoffset="-14"/>' % (d, rgb(ns["BELLY"])))
    hx, hy = ns["PATH"][-1]
    out.append('<ellipse cx="%g" cy="%g" rx="7" ry="6.5" fill="%s"/>' % (hx, hy + 1.5, rgb(ns["SNAKE"])))
    for ex in (-3, 3):
        out.append('<circle cx="%g" cy="%g" r="2" fill="#fff"/><circle cx="%g" cy="%g" r="1" fill="#0a0a0a"/>'
                   % (hx + ex, hy + 1, hx + ex, hy + 1.6))
    out.append('<path d="M%g %g v4 l-2 2 M%g %g l2 2" stroke="#e63c3c" stroke-width="1.2" fill="none" '
               'stroke-linecap="round"/>' % (hx, hy + 7, hx, hy + 11))
    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    text = svg()
    for path in (ROOT / "pyos" / "share" / "pyos" / "logo.svg", ROOT / "docs" / "pyos-logo.svg"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    print("logo written")
