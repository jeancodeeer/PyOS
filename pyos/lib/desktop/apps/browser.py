# The web browser window: tabs, address bar, back/forward/reload/home,
# bookmarks, find in page, view source, forms, scrolling.
import pygame
from desktop import theme as T, ui, clipboard
from desktop.wm import App
from browser import page as P, store

TOOL_H = 40
TAB_H = 32
STATUS_H = 22
SCROLLBAR = 12


class Tab:
    def __init__(self, browser):
        self.browser = browser
        self.history, self.pos = [], -1
        self.page = None
        self.scroll = 0
        self.focus = None              # form control with the keyboard
        self.find = ""

    def go(self, url, data=None, method="GET", record=True):
        url = url.strip()
        if not url:
            return
        if "://" not in url and not url.startswith(("about:", "data:", "file:")):
            if " " in url or "." not in url:
                from urllib.parse import quote_plus
                url = "https://lite.duckduckgo.com/lite/?q=" + quote_plus(url)
            elif url.startswith("/"):
                url = "file://" + url
            else:
                url = "http://" + url if url.split("/")[0].split(":")[0].replace(".", "").isdigit() else "https://" + url
        if record:
            self.history = self.history[:self.pos + 1] + [url]
            self.pos = len(self.history) - 1
        frag = url.split("#", 1)[1] if "#" in url else None
        self.page = P.Page(url.split("#")[0] if not url.startswith("about:") else url, self.browser.page_changed)
        self.page.fragment = frag
        self.scroll = 0
        self.focus = None
        self.page.load(self.browser.page_width(), data, method)
        self.browser.sync_bar(self)

    def back(self):
        if self.pos > 0:
            self.pos -= 1
            self.go(self.history[self.pos], record=False)

    def forward(self):
        if self.pos + 1 < len(self.history):
            self.pos += 1
            self.go(self.history[self.pos], record=False)

    def reload(self):
        if self.page:
            self.go(self.page.url, record=False)


class Browser(App):
    title = "Navegador"
    size = (940, 620)

    def __init__(self, win, url=P.HOME):
        App.__init__(self, win)
        self.form = ui.Form()
        y = TAB_H + 6
        self.btn_back = self.form.add(ui.Button((8, y, 30, 28), "\u2190", lambda: self.tab.back()))
        self.btn_fwd = self.form.add(ui.Button((42, y, 30, 28), "\u2192", lambda: self.tab.forward()))
        self.btn_reload = self.form.add(ui.Button((76, y, 30, 28), "\u21bb", lambda: self.tab.reload()))
        self.btn_home = self.form.add(ui.Button((110, y, 30, 28), "\u2302", lambda: self.tab.go(P.HOME)))
        self.bar = self.form.add(ui.Field((148, y, 600, 28), url, self.navigate, placeholder="Buscar o escribir una direccion"))
        self.btn_star = self.form.add(ui.Button((742, y, 30, 28), "\u2606", self.bookmark))
        self.btn_marks = self.form.add(ui.Button((776, y, 34, 28), "\u2630", lambda: self.tab.go("about:bookmarks")))
        self.find_field = None
        self.tabs = []
        self.tab = None
        self.dirty_page = True
        self.hover = ""
        self.source_mode = False
        self.layout_bar()
        self.new_tab(url)

    # ---- tabs ----
    def new_tab(self, url=P.HOME):
        t = Tab(self)
        self.tabs.append(t)
        self.tab = t
        t.go(url)

    def close_tab(self, t=None):
        t = t or self.tab
        if len(self.tabs) == 1:
            t.go(P.HOME)
            return
        i = self.tabs.index(t)
        self.tabs.remove(t)
        self.tab = self.tabs[min(i, len(self.tabs) - 1)]
        self.sync_bar(self.tab)

    def tab_rects(self):
        w = min(200, max(80, (self.win.w - 40) // max(1, len(self.tabs))))
        rects = [pygame.Rect(6 + i * (w + 4), 6, w, TAB_H - 6) for i in range(len(self.tabs))]
        plus = pygame.Rect(6 + len(self.tabs) * (w + 4), 6, 26, TAB_H - 6)
        return rects, plus

    # ---- geometry ----
    def layout_bar(self):
        w = self.win.w
        self.bar.rect.w = max(100, w - 148 - 90)
        self.btn_star.rect.x = self.bar.rect.right + 8
        self.btn_marks.rect.x = self.bar.rect.right + 42

    def page_area(self):
        top = TAB_H + TOOL_H
        return (0, top, self.win.w - SCROLLBAR, self.win.h - top - STATUS_H)

    def page_width(self):
        return self.page_area()[2]

    def resized(self, w, h):
        self.layout_bar()
        for t in self.tabs:
            if t.page and t.page.doc is not None:
                t.page.relayout(self.page_width())
        self.dirty_page = True

    # ---- callbacks ----
    def page_changed(self, page):
        self.dirty_page = True
        for t in self.tabs:
            if t.page is page:
                if page.status == "listo" and getattr(page, "fragment", None) and page.layout:
                    y = page.layout.anchors.get(page.fragment)
                    if y is not None:
                        t.scroll = max(0, y - 4)
                    page.fragment = None
                if page.status == "listo" and not page.loading and not getattr(page, "visited", False):
                    page.visited = True
                    store.visit(page.title, page.url)
                if t is self.tab:
                    self.sync_bar(t)

    def sync_bar(self, t):
        if t is self.tab and t.page and not self.bar.focus:
            self.bar.set(t.page.url)
        title = (t.page.title if t.page else "") or "Navegador"
        if t is self.tab:
            self.win.set_title(title[:60] + " - Navegador")
        self.dirty_page = True

    def navigate(self, url):
        self.bar.focus = False
        self.tab.go(url)

    def bookmark(self):
        p = self.tab.page
        if p:
            store.add_bookmark(p.title, p.url)
            from desktop import wm
            wm.wm.toast("marcador guardado: " + p.title[:40])

    def tick(self, now):
        if self.dirty_page:
            self.dirty_page = False
            return True
        return False

    # ---- drawing ----
    def draw(self, surf):
        surf.fill((226, 230, 238), (0, 0, self.win.w, TAB_H))
        surf.fill(T.WIN_BG, (0, TAB_H, self.win.w, TOOL_H))
        rects, plus = self.tab_rects()
        f = ui.FONT()
        for t, r in zip(self.tabs, rects):
            active = t is self.tab
            pygame.draw.rect(surf, T.WIN_BG if active else (212, 217, 226), (r.x, r.y, r.w, r.h + 8), 0, 8)
            label = (t.page.title if t.page else "") or "Nueva pestana"
            if t.page and t.page.loading:
                label = "\u25cf " + label
            ui.text(surf, label, r.x + 10, r.y + (r.h - f.get_height()) // 2 + 1, T.TEXT if active else T.MUTED, f, r.w - 34)
            ui.text(surf, "\u2715", r.right - 18, r.y + (r.h - f.get_height()) // 2 + 1, T.MUTED, f)
        ui.text(surf, "+", plus.centerx, plus.y + 2, T.MUTED, ui.font(18, bold=True), center=True)
        pygame.draw.line(surf, (214, 218, 226), (0, TAB_H + TOOL_H - 1), (self.win.w, TAB_H + TOOL_H - 1))
        self.form.draw(surf)
        area = self.page_area()
        p = self.tab.page
        if self.source_mode and p is not None:
            self._draw_source(surf, area, p)
        elif p is not None:
            maxs = self.max_scroll()
            self.tab.scroll = max(0, min(self.tab.scroll, maxs))
            p.paint(surf, self.tab.scroll, area, self.tab.focus, self.tab.find or None)
            self._draw_scrollbar(surf, area, maxs)
        sy = self.win.h - STATUS_H
        surf.fill((240, 242, 246), (0, sy, self.win.w, STATUS_H))
        status = self.hover or (p.status if p else "")
        if self.tab.find:
            status = "buscar: %s (Enter siguiente, Esc salir)   %s" % (self.tab.find, status)
        ui.text(surf, status, 8, sy + 3, T.MUTED, max_w=self.win.w - 16)

    def _draw_source(self, surf, area, p):
        ax, ay, aw, ah = area
        surf.fill((250, 250, 246), area)
        lines = p.source.split("\n")
        rows = ah // 16
        start = self.tab.scroll // 16
        for i, line in enumerate(lines[start:start + rows]):
            ui.text(surf, line.replace("\t", "    ")[:aw // 8], ax + 4, ay + i * 16, (40, 40, 60))

    def _draw_scrollbar(self, surf, area, maxs):
        ax, ay, aw, ah = area
        x = ax + aw
        surf.fill((230, 232, 236), (x, ay, SCROLLBAR, ah))
        total = maxs + ah
        if maxs > 0:
            h = max(20, ah * ah // total)
            y = ay + (ah - h) * self.tab.scroll // maxs
            pygame.draw.rect(surf, (160, 166, 178), (x + 2, y, SCROLLBAR - 4, h))

    def max_scroll(self):
        p = self.tab.page
        ah = self.page_area()[3]
        if self.source_mode and p:
            return max(0, len(p.source.split("\n")) * 16 - ah)
        if p is None or p.layout is None:
            return 0
        return max(0, p.layout.height - ah + 16)

    # ---- input ----
    def scroll_by(self, dy):
        self.tab.scroll = max(0, min(self.max_scroll(), self.tab.scroll + dy))
        self.dirty_page = True

    def event(self, ev, pos):
        t = self.tab
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if pos[1] < TAB_H:
                rects, plus = self.tab_rects()
                if plus.collidepoint(pos):
                    self.new_tab()
                    return True
                for tab, r in zip(self.tabs, rects):
                    if r.collidepoint(pos):
                        if pos[0] > r.right - 18:
                            self.close_tab(tab)
                        else:
                            self.tab = tab
                            self.sync_bar(tab)
                        return True
                return False
            if pos[1] < TAB_H + TOOL_H:
                self.tab.focus = None
                return self.form.event(ev, pos)
            self.bar.focus = False
            if ev.button == 4:
                self.scroll_by(-48)
                return True
            if ev.button == 5:
                self.scroll_by(48)
                return True
            area = self.page_area()
            if pos[0] >= area[2]:                     # scroll bar
                frac = (pos[1] - area[1]) / max(1, area[3])
                self.tab.scroll = int(self.max_scroll() * frac)
                return True
            if ev.button == 1 and t.page and not self.source_mode:
                return self.click(pos[0] - area[0], pos[1] - area[1] + t.scroll, ev)
            return False
        if ev.type == pygame.MOUSEMOTION and t.page and pos and not self.source_mode:
            area = self.page_area()
            it = t.page.item_at(pos[0] - area[0], pos[1] - area[1] + t.scroll) if pos[1] > area[1] else None
            hover = it.href if it is not None and it.href else ""
            if hover != self.hover:
                self.hover = hover
                return True
            return False
        if ev.type != pygame.KEYDOWN:
            return self.form.event(ev, pos)
        return self.key(ev)

    def click(self, x, y, ev):
        t = self.tab
        it = t.page.item_at(x, y)
        if it is None:
            t.focus = None
            return True
        if it.kind == "widget":
            return self.click_widget(it.node)
        if it.href:
            self.follow(it.href, ui.ctrl(ev))
            return True
        return False

    def follow(self, href, new_tab=False):
        if href.startswith("javascript:"):
            from desktop import wm
            wm.wm.toast("JavaScript no esta soportado")
            return
        if href.startswith("mailto:"):
            return
        cur = self.tab.page.url if self.tab.page else ""
        if "#" in href and href.split("#")[0] == cur.split("#")[0] and self.tab.page.layout:
            y = self.tab.page.layout.anchors.get(href.split("#", 1)[1])
            if y is not None:
                self.tab.scroll = max(0, y - 4)
                self.dirty_page = True
                return
        if new_tab:
            self.new_tab(href)
        else:
            self.tab.go(href)

    def click_widget(self, node):
        p = self.tab.page
        st = p.widget_state(node)
        kind = st["kind"]
        if node.tag == "button" or kind in ("submit", "image"):
            if node.tag == "button" and node.attrs.get("type", "submit").lower() not in ("submit",):
                return True
            target = p.submit(node)
            if target:
                url, data, method = target
                self.tab.go(url, data, method)
            return True
        if kind == "checkbox":
            st["checked"] = not st["checked"]
        elif kind == "radio":
            name = node.attrs.get("name")
            form = p.form_of(node) or p.doc
            for other in form.iter("input"):
                if other.attrs.get("name") == name and other.attrs.get("type", "").lower() == "radio":
                    p.widget_state(other)["checked"] = other is node
        elif node.tag == "select":
            opts = list(node.iter("option"))
            values = [(o.attrs.get("value") or o.text_content().strip()) for o in opts]
            if values:
                i = values.index(st["value"]) if st["value"] in values else -1
                st["value"] = values[(i + 1) % len(values)]
        else:
            self.tab.focus = node
        self.dirty_page = True
        return True

    def key(self, ev):
        t = self.tab
        c = ui.ctrl(ev)
        alt = ev.mod & pygame.KMOD_ALT
        k = ev.key
        if c and k == pygame.K_l:
            self.bar.focus = True
            self.bar.cursor = len(self.bar.text)
            return True
        if c and k == pygame.K_t:
            self.new_tab()
            self.bar.focus = True
            self.bar.set("")
            return True
        if c and k == pygame.K_w:
            self.close_tab()
            return True
        if c and k == pygame.K_d:
            self.bookmark()
            return True
        if c and k == pygame.K_u:
            self.source_mode = not self.source_mode
            t.scroll = 0
            return True
        if c and k == pygame.K_f:
            t.find = t.find or " "
            t.find = ""
            self.finding = True
            return True
        if (alt and k == pygame.K_LEFT) or (k == pygame.K_BACKSPACE and not self.bar.focus and t.focus is None
                                            and not getattr(self, "finding", False)):
            t.back()
            return True
        if alt and k == pygame.K_RIGHT:
            t.forward()
            return True
        if k == pygame.K_F5:
            t.reload()
            return True
        if self.bar.focus:
            if k == pygame.K_ESCAPE:
                self.bar.focus = False
                self.sync_bar(t)
                return True
            return self.bar.event(ev, None)
        if getattr(self, "finding", False):
            if k == pygame.K_ESCAPE:
                self.finding = False
                t.find = ""
            elif k == pygame.K_RETURN:
                y = t.page.find_y(t.find, t.scroll + 4) if t.page else None
                if y is None and t.page:
                    y = t.page.find_y(t.find, -1)
                if y is not None:
                    t.scroll = max(0, y - 40)
            elif k == pygame.K_BACKSPACE:
                t.find = t.find[:-1]
            elif ev.unicode and ord(ev.unicode[0]) >= 32:
                t.find += ev.unicode
                y = t.page.find_y(t.find, t.scroll - 1) if t.page else None
                if y is not None and not (t.scroll <= y < t.scroll + self.page_area()[3] - 20):
                    t.scroll = max(0, y - 40)
            self.dirty_page = True
            return True
        if t.focus is not None:
            return self.type_into(t.focus, ev)
        ah = self.page_area()[3]
        if k == pygame.K_DOWN:
            self.scroll_by(40)
        elif k == pygame.K_UP:
            self.scroll_by(-40)
        elif k in (pygame.K_PAGEDOWN, pygame.K_SPACE):
            self.scroll_by(ah - 40)
        elif k == pygame.K_PAGEUP:
            self.scroll_by(-(ah - 40))
        elif k == pygame.K_HOME:
            t.scroll = 0
        elif k == pygame.K_END:
            t.scroll = self.max_scroll()
        else:
            return False
        return True

    def type_into(self, node, ev):
        p = self.tab.page
        st = p.widget_state(node)
        k = ev.key
        if k == pygame.K_ESCAPE:
            self.tab.focus = None
        elif k == pygame.K_RETURN and node.tag != "textarea":
            target = p.submit(node)
            if target:
                url, data, method = target
                self.tab.go(url, data, method)
        elif k == pygame.K_RETURN:
            st["value"] += "\n"
        elif k == pygame.K_BACKSPACE:
            st["value"] = st["value"][:-1]
        elif k == pygame.K_TAB:
            fields = [n for n in (p.form_of(node) or p.doc).iter() if n.tag in ("input", "textarea")
                      and n.attrs.get("type", "text").lower() in ("text", "search", "email", "password", "url", "number", "tel")]
            if node in fields and len(fields) > 1:
                self.tab.focus = fields[(fields.index(node) + 1) % len(fields)]
        elif ui.ctrl(ev) and k == pygame.K_v:
            st["value"] += clipboard.get()
        elif ev.unicode and ord(ev.unicode[0]) >= 32:
            st["value"] += ev.unicode
        else:
            return False
        self.dirty_page = True
        return True
