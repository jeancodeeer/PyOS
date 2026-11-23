# Layout: the styled HTML tree -> a display list of positioned rectangles,
# text runs, images and form controls.
#
# Block boxes stack vertically; inline content flows into line boxes and
# wraps at spaces. Lists get markers, tables get columns, flex rows are laid
# out side by side. Everything is measured with the 8x16 VGA font (scaled
# x2 for big headings).
from browser import css

CHAR_W, CHAR_H = 8, 18          # rough sizes, only where nothing better is known
LINK_COLOR = (6, 69, 173)


class Item:
    """One thing to paint. kind: 'rect', 'border', 'text', 'image', 'widget', 'hr', 'marker'."""
    __slots__ = ("kind", "x", "y", "w", "h", "data", "color", "href", "node", "extra")

    def __init__(self, kind, x, y, w, h, data=None, color=None, href=None, node=None, extra=None):
        self.kind, self.x, self.y, self.w, self.h = kind, x, y, w, h
        self.data, self.color, self.href, self.node, self.extra = data, color, href, node, extra


def hidden(st):
    """Elements pages hide on purpose: off-screen, clipped, or 1px boxes
    with overflow hidden (screen-reader-only text)."""
    if st.get("display") == "none" or st.get("visibility") == "hidden" and st.get("position") in ("absolute", "fixed"):
        return True
    pos = st.get("position")
    if pos in ("absolute", "fixed"):
        for side in ("left", "top", "right"):
            v = st.get(side, "")
            if isinstance(v, str) and v.startswith("-") and v[1:2].isdigit() and len(v) > 4:
                return True
        if st.get("clip") or st.get("clip-path"):
            return True
        w, h = st.get("width"), st.get("height")
        if (w in (0, 1) or h in (0, 1)) and st.get("overflow") == "hidden":
            return True
    if st.get("overflow") == "hidden" and (st.get("height") == 1 or st.get("width") == 1):
        return True
    if st.get("text-indent", 0) and isinstance(st.get("text-indent"), int) and st["text-indent"] < -900:
        return True
    return False


_fonts = {}
_space = {}
_ui_font = None


def font_for(style):
    """The pygame font for a computed style: size, weight, and mono for code."""
    size = style.get("font-size", 16)
    fam = style.get("font-family", "")
    mono = "mono" in fam or "courier" in fam or "consol" in fam
    bold = style.get("font-weight") == "bold"
    px = min((11, 13, 15, 18, 24, 32, 44), key=lambda s: abs(s - size * 0.94))
    if mono:
        px = 13 if size < 16 else 15
    key = (px, bold, mono)
    f = _fonts.get(key)
    if f is None:
        import pygame
        pygame.font.init()
        f = pygame.font.SysFont("mono" if mono else "sans", px, bold)
        f._px = px                          # sizes here are pixels
        _fonts[key] = f
    return f


def text_w(s, style):
    return font_for(style).size(s)[0]


def line_h(style):
    return font_for(style).get_height() + 3


def ui_font():
    """The font for markers, alt text and form controls."""
    global _ui_font
    if _ui_font is None:
        _ui_font = font_for({"font-size": 14})
    return _ui_font


def ui_w(s):
    return ui_font().size(s)[0]


def _px(style, name, default=0):
    v = style.get(name, default)
    return v if isinstance(v, int) else default


def _resolve_width(style, available):
    w = style.get("width")
    if isinstance(w, tuple):
        return int(w[1] * available / 100)
    if isinstance(w, int) and w > 0:
        return min(w, available) if style.get("display") not in ("table-cell",) else w
    return None


class Layout:
    def __init__(self, page, width):
        self.page = page
        self.width = width
        self.items = []
        self.anchors = {}
        self.images = page.images            # url -> Surface or None
        self.widgets = page.widgets          # node id -> state dict
        self.height = 0
        self.max_x = width
        self.bg = None

    def run(self, root):
        body = root.find("body") or root
        html = root.find("html")
        bg = None
        for n in (html, body):
            if n is not None and n.style and isinstance(n.style.get("background-color"), tuple):
                bg = n.style["background-color"]
        self.bg = bg or (255, 255, 255)
        start = html if html is not None else root
        self.height = self.block(start, 0, 0, self.width, None)
        return self

    # ---- blocks ----
    def block(self, node, x, y, avail, href):
        st = node.style or {}
        disp = st.get("display", "block")
        if disp == "none":
            return 0
        if hidden(st):
            return 0
        if st.get("visibility") == "hidden" and disp != "block":
            pass
        mt, mb = _px(st, "margin-top"), _px(st, "margin-bottom")
        ml, mr = _px(st, "margin-left"), _px(st, "margin-right")
        pt, pb = _px(st, "padding-top"), _px(st, "padding-bottom")
        pl, pr = _px(st, "padding-left"), _px(st, "padding-right")
        bt, bb = _px(st, "border-top-width"), _px(st, "border-bottom-width")
        bl, br = _px(st, "border-left-width"), _px(st, "border-right-width")
        width = _resolve_width(st, avail)
        mw = st.get("max-width")
        box_w = avail - ml - mr
        if width is not None:
            box_w = width + pl + pr + bl + br if st.get("box-sizing") != "border-box" else width
        if isinstance(mw, tuple):
            mw = int(mw[1] * avail / 100)
        if isinstance(mw, int) and mw > 0 and box_w > mw:
            box_w = mw
        box_w = max(16, min(box_w, avail - ml - mr) if width is None else box_w)
        if (st.get("margin-left") == "auto" and st.get("margin-right") == "auto") and box_w < avail:
            ml = (avail - box_w) // 2
        elif node.tag == "table" and node.attrs.get("align") == "center" and box_w < avail:
            ml = (avail - box_w) // 2
        bx = x + ml
        by = y + mt
        content_x = bx + bl + pl
        content_w = max(8, box_w - bl - pl - br - pr)
        ident = node.attrs.get("id") or (node.attrs.get("name") if node.tag == "a" else None)
        if ident:
            self.anchors.setdefault(ident, by)
        bg_index = len(self.items)
        if node.tag == "a" and node.attrs.get("href"):
            href = self.page.resolve(node.attrs["href"])
        cy = by + bt + pt
        if disp == "table":
            h = self.table(node, content_x, cy, content_w, href)
        elif disp == "list-item":
            h = self.flow(node, content_x, cy, content_w, href, marker=self._marker(node))
        elif node.tag == "hr":
            self.items.append(Item("hr", content_x, cy + 4, content_w, 2, color=st.get("border-color", (160, 160, 160))))
            h = 10
        elif disp in ("flex", "inline-flex") and st.get("flex-direction", "row") in ("row", "row-reverse") \
                and st.get("flex-wrap") != "wrap":
            h = self.flex_row(node, content_x, cy, content_w, href)
        else:
            h = self.flow(node, content_x, cy, content_w, href)
        min_h = st.get("height")
        if isinstance(min_h, int) and min_h > h and node.tag not in ("html", "body"):
            h = min(min_h, 2000)
        total_h = bt + pt + h + pb + bb
        bgc = st.get("background-color")
        if isinstance(bgc, tuple) and node.tag not in ("html", "body"):
            self.items.insert(bg_index, Item("rect", bx, by, box_w, total_h, color=bgc))
        if bt or bb or bl or br:
            self.items.append(Item("border", bx, by, box_w, total_h, color=st.get("border-color", st.get("color", (0, 0, 0))),
                                   extra=(bt, br, bb, bl)))
        return mt + total_h + mb

    def _marker(self, node):
        st = node.style
        kind = st.get("list-style-type", "disc")
        if kind == "none":
            return None
        if kind in ("decimal", "lower-alpha", "upper-alpha", "lower-roman", "upper-roman"):
            n = 1
            parent = node.parent
            if parent is not None:
                try:
                    n = int(parent.attrs.get("start", "1"))
                except ValueError:
                    n = 1
                for sib in parent.children:
                    if sib is node:
                        break
                    if sib.tag == "li":
                        n += 1
            if kind == "decimal":
                return "%d." % n
            if kind in ("lower-alpha", "upper-alpha"):
                s = chr(96 + (n - 1) % 26 + 1) + "."
                return s.upper() if kind == "upper-alpha" else s
            return _roman(n).lower() + "." if kind == "lower-roman" else _roman(n) + "."
        return {"disc": "•", "circle": "o", "square": "■"}.get(kind, "•")

    # ---- mixed content: blocks and inline runs ----
    def flow(self, node, x, y, w, href, marker=None):
        cy = y
        run = []
        prev_margin = 0
        first = True

        def flush():
            nonlocal cy, marker
            if run:
                h = self.inline(run, x, cy, w, node.style, marker)
                marker = None
                cy += h
                run.clear()

        for child in node.children:
            if child.tag is None:
                run.append((child, href))
                continue
            cst = child.style or {}
            d = cst.get("display", "inline")
            if d == "none":
                continue
            if d in ("block", "list-item", "table", "flex", "grid", "table-row-group", "table-row") or \
                    child.tag in ("hr",) or (cst.get("float") in ("left", "right") and d != "inline" and False):
                flush()
                if marker is not None:
                    self.items.append(Item("marker", x - 30, cy, 24, CHAR_H, marker,
                                           color=node.style.get("color", (0, 0, 0))))
                    marker = None
                cy += self.block(child, x, cy, w, href if child.tag != "a" else href)
            else:
                run.append((child, href))
        flush()
        if marker is not None:
            self.items.append(Item("marker", x - 30, cy, 24, CHAR_H, marker,
                                   color=node.style.get("color", (0, 0, 0))))
            cy += CHAR_H
        return cy - y

    # ---- inline formatting ----
    def _pieces(self, run):
        """Flatten an inline run into pieces: ('word', text, style, href),
        ('space', style), ('br',), ('image', node, href), ('widget', node)."""
        out = []
        stack = list(reversed(run))
        while stack:
            entry = stack.pop()
            if entry[0] == "close":
                continue
            node, href = entry
            if node.tag is None:
                parent = node.parent
                st = parent.style if parent is not None and parent.style else css.ROOT_STYLE
                text = node.text
                tt = st.get("text-transform")
                if tt == "uppercase":
                    text = text.upper()
                elif tt == "lowercase":
                    text = text.lower()
                if st.get("white-space") in ("pre", "pre-wrap", "pre-line"):
                    lines = text.split("\n")
                    for i, line in enumerate(lines):
                        if i:
                            out.append(("br",))
                        if line:
                            out.append(("word", line.replace("\t", "    ").replace("\r", ""), st, href, True))
                    continue
                words = text.replace("\xa0", "\x01").split()
                if text[:1].isspace():
                    out.append(("space", st))
                for i, wd in enumerate(words):
                    if i:
                        out.append(("space", st))
                    out.append(("word", wd.replace("\x01", " "), st, href, False))
                if words and text[-1:].isspace():
                    out.append(("space", st))
                continue
            st = node.style or {}
            d = st.get("display", "inline")
            if d == "none" or hidden(st):
                continue
            if node.tag == "br":
                out.append(("br",))
                continue
            if node.tag == "img":
                out.append(("image", node, href))
                continue
            if node.tag in ("input", "button", "select", "textarea"):
                out.append(("widget", node, href))
                continue
            if node.tag in ("svg", "video", "canvas", "iframe", "object"):
                continue
            h2 = href
            if node.tag == "a" and node.attrs.get("href"):
                h2 = self.page.resolve(node.attrs["href"])
            ident = node.attrs.get("id")
            if ident:
                out.append(("anchor", ident))
            if d in ("block", "list-item", "table", "flex"):
                out.append(("block", node, h2))
                continue
            for c in reversed(node.children):
                stack.append((c, h2))
        return out

    def inline(self, run, x, y, w, block_style, marker):
        pieces = self._pieces(run)
        if not any(p[0] in ("word", "image", "widget", "block", "br") for p in pieces):
            return 0
        align = block_style.get("text-align", "left")
        lines = []
        line, lw, lh = [], 0, CHAR_H
        cy = y
        indent = block_style.get("text-indent", 0)
        indent = indent if isinstance(indent, int) and indent > 0 else 0
        lw = indent

        def end_line(force=False):
            nonlocal line, lw, lh, cy
            while line and line[-1][0] == "space":
                lw -= line[-1][3]
                line.pop()
            if line or force:
                self._place(line, x, cy, w, lw, lh, align)
                cy += lh
            line, lw, lh = [], 0, CHAR_H

        for p in pieces:
            kind = p[0]
            if kind == "anchor":
                self.anchors.setdefault(p[1], cy)
                continue
            if kind == "br":
                end_line(True)
                continue
            if kind == "space":
                if line and line[-1][0] != "space":
                    sw = text_w(" ", p[1])
                    line.append(("space", None, p[1], sw, line_h(p[1]), None))
                    lw += sw
                continue
            if kind == "block":
                end_line()
                cy += self.block(p[1], x, cy, w, p[2])
                continue
            if kind == "word":
                _, text, st, href, pre = p
                ww, h = text_w(text, st), line_h(st)
                if lw + ww > w and line and not pre:
                    end_line()
                while ww > w and not pre and len(text) > 1:          # a word longer than the line
                    n = len(text) - 1
                    while n > 1 and text_w(text[:n], st) > w - lw:
                        n -= 1
                    piece = text[:n]
                    line.append(("word", piece, st, text_w(piece, st), h, href))
                    lh = max(lh, h)
                    end_line()
                    text = text[n:]
                    ww = text_w(text, st)
                line.append(("word", text, st, ww, h, href))
                lw += ww
                lh = max(lh, h)
                continue
            if kind == "image":
                node, href = p[1], p[2]
                iw, ih = self._image_size(node, w)
                if lw + iw > w and line:
                    end_line()
                line.append(("image", node, None, iw, ih, href))
                lw += iw
                lh = max(lh, ih)
                continue
            if kind == "widget":
                node = p[1]
                ww, wh = self._widget_size(node, w)
                if lw + ww > w and line:
                    end_line()
                line.append(("widget", node, node.style, ww, wh, p[2]))
                lw += ww + 4
                lh = max(lh, wh + 2)
        end_line()
        if marker is not None:
            self.items.append(Item("marker", x - 30, y, 24, CHAR_H, marker,
                                   color=block_style.get("color", (0, 0, 0))))
        return cy - y

    def _place(self, line, x, y, w, lw, lh, align):
        if align == "center":
            cx = x + max(0, (w - lw) // 2)
        elif align == "right":
            cx = x + max(0, w - lw)
        else:
            cx = x
        for kind, data, st, iw, ih, href in line:
            base = y + lh - ih
            if kind == "word":
                color = st.get("color", (0, 0, 0))
                deco = st.get("text-decoration", "none")
                bold = st.get("font-weight") == "bold"
                self.items.append(Item("text", cx, base, iw, ih, data, color, href,
                                       extra=(font_for(st), bold, "underline" in deco, "line-through" in deco,
                                              st.get("background-color") if isinstance(st.get("background-color"), tuple) else None)))
            elif kind == "image":
                self.items.append(Item("image", cx, base, iw, ih, self.page.resolve(data.attrs.get("src", "")), None, href,
                                       node=data, extra=data.attrs.get("alt", "")))
            elif kind == "widget":
                self.items.append(Item("widget", cx, y + (lh - ih) // 2, iw, ih, None, None, href, node=data))
                cx += 4
            cx += iw

    def _image_size(self, node, avail):
        st = node.style or {}
        src = self.page.resolve(node.attrs.get("src", ""))
        surf = self.images.get(src)
        w = st.get("width") if isinstance(st.get("width"), int) else None
        h = st.get("height") if isinstance(st.get("height"), int) else None
        if isinstance(st.get("width"), tuple):
            w = int(st["width"][1] * avail / 100)
        if surf:
            sw, sh = surf.get_size()
            if w and not h:
                h = sh * w // max(1, sw)
            elif h and not w:
                w = sw * h // max(1, sh)
            elif not w:
                w, h = sw, sh
        if not w or not h:
            alt = node.attrs.get("alt", "")
            if not (w or h) and not alt:
                return (16, 16)
            w = w or max(16, min(300, ui_w(alt) + 8))
            h = h or CHAR_H + 4
        if w > avail:
            h = h * avail // w
            w = avail
        return max(1, w), max(1, h)

    def _widget_size(self, node, avail):
        t = node.tag
        kind = node.attrs.get("type", "text").lower()
        if t == "textarea":
            cols = int(node.attrs.get("cols", "40") or 40)
            rows = int(node.attrs.get("rows", "4") or 4)
            return min(avail, cols * 8 + 8), rows * CHAR_H + 6
        if t == "select":
            opts = [o.text_content().strip() for o in node.iter("option")]
            return min(avail, max([ui_w(o) for o in opts] + [32]) + 30), CHAR_H + 8
        if t == "button" or kind in ("submit", "button", "reset"):
            label = node.text_content().strip() if t == "button" else node.attrs.get("value", "Enviar" if kind == "submit" else "")
            return ui_w(label) + 24, CHAR_H + 10
        if kind in ("checkbox", "radio"):
            return 14, 14
        size = int(node.attrs.get("size", "20") or 20) if node.attrs.get("size", "").isdigit() else 24
        st = node.style or {}
        w = st.get("width")
        if isinstance(w, int) and w > 0:
            return min(avail, w), CHAR_H + 10
        return min(avail, size * 8 + 10), CHAR_H + 10

    # ---- flex rows (approximation) ----
    def flex_row(self, node, x, y, w, href):
        kids = [c for c in node.children if c.tag and (c.style or {}).get("display") != "none"]
        text_kids = [c for c in node.children if c.tag is None and c.text.strip()]
        if not kids or len(kids) > 8 or text_kids:
            return self.flow(node, x, y, w, href)
        gap = _px(node.style, "gap", 8)
        fixed = []
        for c in kids:
            cw = _resolve_width(c.style or {}, w)
            fixed.append(cw)
        free = w - sum(f for f in fixed if f) - gap * (len(kids) - 1)
        flexible = [i for i, f in enumerate(fixed) if not f]
        each = max(40, free // max(1, len(flexible))) if flexible else 0
        cx, tallest = x, 0
        for i, c in enumerate(kids):
            cw = fixed[i] or each
            saved = (c.style or {}).get("width")
            c.style["width"] = cw
            h = self.block(c, cx, y, cw, href)
            if saved is None:
                del c.style["width"]
            else:
                c.style["width"] = saved
            tallest = max(tallest, h)
            cx += cw + gap
        return tallest

    # ---- tables ----
    def table(self, node, x, y, w, href):
        rows = []
        caption = None
        for part in node.children:
            if part.tag == "caption":
                caption = part
            elif part.tag == "tr":
                rows.append(part)
            elif part.tag in ("thead", "tbody", "tfoot"):
                rows.extend(r for r in part.children if r.tag == "tr")
        cy = y
        if caption is not None:
            cy += self.block(caption, x, cy, w, href)
        if not rows:
            return cy - y
        grid = [[c for c in r.children if c.tag in ("td", "th") and (c.style or {}).get("display") != "none"] for r in rows]
        ncols = max([sum(_span(c) for c in r) for r in grid] + [1])
        spacing = 2
        # column widths from the content: rough minimum and preferred sizes
        pref = [CHAR_W * 2] * ncols
        for r in grid:
            col = 0
            for c in r:
                span = _span(c)
                text = c.text_content()
                words = text.split()
                cst = c.style or {}
                longest = max([text_w(word, cst) for word in words[:40]] + [8]) + 10
                want = min(w, text_w(" ".join(words)[:300], cst) + 14)
                cwidth = _resolve_width(c.style or {}, w)
                img = c.find("img")
                if img is not None:
                    iw, _ = self._image_size(img, w)
                    want = max(want, iw + 8)
                if cwidth:
                    want = cwidth
                per = max(longest, want) // span
                for k in range(col, min(ncols, col + span)):
                    pref[k] = max(pref[k], per)
                col += span
        table_w = _resolve_width(node.style or {}, w)
        total = sum(pref) + spacing * (ncols + 1)
        target = table_w or min(w, total)
        if total > target:
            factor = (target - spacing * (ncols + 1)) / max(1, sum(pref))
            widths = [max(CHAR_W * 2, int(p * factor)) for p in pref]
        else:
            extra = (target - total) // ncols if table_w else 0
            widths = [p + extra for p in pref]
        for r_node, r in zip(rows, grid):
            cx = x + spacing
            col = 0
            row_h = 0
            start_index = len(self.items)
            cells = []
            for c in r:
                span = _span(c)
                cw = sum(widths[col:col + span]) + spacing * (span - 1)
                saved = c.style.get("display")
                c.style["display"] = "block"
                saved_w = c.style.get("width")
                c.style["width"] = cw
                h = self.block(c, cx, cy, cw, href)
                c.style["display"] = saved
                if saved_w is None:
                    del c.style["width"]
                else:
                    c.style["width"] = saved_w
                cells.append((cx, cw, c))
                row_h = max(row_h, h)
                cx += cw + spacing
                col += span
            rbg = (r_node.style or {}).get("background-color")
            if isinstance(rbg, tuple):
                self.items.insert(start_index, Item("rect", x, cy, w, row_h, color=rbg))
            for cx, cw, c in cells:
                if _px(node.style, "border-top-width") or node.attrs.get("border", "0") not in ("0", ""):
                    self.items.append(Item("border", cx, cy, cw, row_h, color=(160, 160, 160), extra=(1, 1, 1, 1)))
            cy += row_h + spacing
        return cy - y


def _span(cell):
    try:
        return max(1, min(20, int(cell.attrs.get("colspan", "1"))))
    except ValueError:
        return 1


def _roman(n):
    out = ""
    for v, s in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
                 (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out += s
            n -= v
    return out
