# A web page: fetch it, parse it, style it, load its images, lay it out and
# paint the part of it that is on screen.
import _thread
import pygame
from urllib.parse import urljoin, urlsplit, urlencode, quote_plus
from browser import html, css, layout

USER_AGENT = "PyKernel-Browser/0.2 (Python; bare metal; no JavaScript)"
MAX_BYTES = 3 << 20
HOME = "about:home"

_font = None


def font():
    global _font
    if _font is None:
        pygame.font.init()
        _font = pygame.font.Font(None, 16)
    return _font


ABOUT = {
    "about:home": """<html><head><title>Inicio</title><style>
body { font-family: sans-serif; margin: 24px; background: #f4f6fa }
h1 { color: #1d3d78 } .box { background: white; border: 1px solid #c8d0e0; padding: 12px; margin-bottom: 16px }
a { color: #2456b8 }
</style></head><body>
<h1>PyKernel Navegador</h1>
<p>Un navegador escrito en Python, que corre sobre un sistema operativo escrito en Python.
HTML, CSS, imagenes (PNG, BMP, GIF, JPEG), formularios, enlaces, pestanas, marcadores e historial. No ejecuta JavaScript.</p>
<div class="box"><b>Prueba:</b><ul>
<li><a href="https://example.com/">example.com</a></li>
<li><a href="https://en.wikipedia.org/wiki/Python_(programming_language)">Wikipedia: Python</a></li>
<li><a href="https://lite.duckduckgo.com/lite/">DuckDuckGo Lite (busqueda sin JavaScript)</a></li>
<li><a href="https://text.npr.org/">NPR solo texto</a></li>
<li><a href="https://lite.cnn.com/">CNN Lite</a></li>
<li><a href="file:///lib/browser/README.html">Como funciona este navegador</a></li>
</ul></div>
<div class="box"><b>Atajos:</b> Ctrl+L barra de direcciones, Ctrl+T pestana nueva, Ctrl+W cerrar pestana,
Ctrl+D marcador, Ctrl+F buscar, Ctrl+U ver codigo, Alt+Izq atras, F5 recargar, Inicio/Fin, RePag/AvPag.</div>
<p><a href="about:bookmarks">Marcadores</a> - <a href="about:history">Historial</a></p>
</body></html>""",
}


class Response:
    def __init__(self, url, status, ctype, body, error=None):
        self.url, self.status, self.ctype, self.body, self.error = url, status, ctype, body, error


def fetch(url, data=None, method="GET"):
    """Bytes of a URL: http, https, file, about, data."""
    if url.startswith("about:"):
        if url in ABOUT:
            return Response(url, 200, "text/html", ABOUT[url].encode())
        from browser import store
        page = store.about_page(url)
        if page:
            return Response(url, 200, "text/html", page.encode())
        return Response(url, 404, "text/html", b"<h1>No existe</h1>")
    if url.startswith("data:"):
        import binascii
        head, _, payload = url[5:].partition(",")
        body = binascii.a2b_base64(payload) if head.endswith(";base64") else payload.encode()
        return Response(url, 200, head.split(";")[0] or "text/plain", body)
    u = urlsplit(url)
    if u.scheme == "file":
        path = u.path
        try:
            import os
            if os.stat(path)[0] & 0x4000:
                rows = "".join('<li><a href="file://%s/%s">%s</a></li>' % (path.rstrip("/"), n, n)
                               for n in sorted(os.listdir(path)))
                return Response(url, 200, "text/html", ("<h1>%s</h1><ul>%s</ul>" % (path, rows)).encode())
            with open(path, "rb") as f:
                body = f.read()
        except OSError as e:
            return Response(url, 404, "text/html", ("<h1>No se puede abrir</h1><p>%s</p>" % e).encode(), str(e))
        low = path.lower()
        ctype = "text/html" if low.endswith((".html", ".htm")) else (
            "image/png" if low.endswith(".png") else "image/jpeg" if low.endswith((".jpg", ".jpeg")) else
            "image/gif" if low.endswith(".gif") else "image/bmp" if low.endswith(".bmp") else "text/plain")
        return Response(url, 200, ctype, body)
    from urllib import request
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,image/*;q=0.8,*/*;q=0.5",
               "Accept-Language": "es,en;q=0.8"}
    from browser import store
    cookie = store.cookies_for(url)
    if cookie:
        headers["Cookie"] = cookie
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = request.Request(url, data, headers, method)
    try:
        r = request.urlopen(req, timeout=30)
        body = r.read()
        for c in r.headers.get_all("set-cookie"):
            store.set_cookie(r.geturl(), c)
        return Response(r.geturl(), r.status, (r.getheader("content-type") or "text/html"), body[:MAX_BYTES])
    except request.HTTPError as e:
        return Response(url, e.code, (e.headers.get("content-type") if e.headers else "text/html") or "text/html",
                        e.read() or ("<h1>Error %d</h1>" % e.code).encode())
    except Exception as e:
        msg = "<h1>No se pudo cargar la pagina</h1><p>%s</p><p><code>%s</code></p>" % (url, html_escape(repr(e)))
        return Response(url, 0, "text/html", msg.encode(), repr(e))


def html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def decode(body, ctype):
    enc = "utf-8"
    low = ctype.lower()
    if "charset=" in low:
        enc = low.split("charset=")[1].split(";")[0].strip().strip('"')
    else:
        head = body[:1024].lower()
        i = head.find(b"charset=")
        if i >= 0:
            enc = head[i + 8:i + 30].split(b'"')[0].split(b"'")[0].split(b";")[0].split(b">")[0].strip().decode() or "utf-8"
    try:
        return body.decode("utf-8" if enc in ("utf-8", "utf8") else enc)
    except (UnicodeError, LookupError):
        try:
            return body.decode("utf-8", "replace")
        except Exception:
            return "".join(chr(b) for b in body)


def ensure_memory(want_mib=24):
    """Big pages need room: move free RAM into the Python heap if it is short."""
    import gc
    gc.collect()
    if gc.mem_free() >= want_mib << 20:
        return
    try:
        from kernel import mm
        if mm.free_bytes() > (want_mib + 32) << 20:
            mm.grow_heap(max(32, want_mib))
    except Exception:
        pass


class Page:
    def __init__(self, url, on_change=None):
        self.url = url
        self.title = url
        self.status = "cargando..."
        self.doc = None
        self.layout = None
        self.images = {}
        self.widgets = {}
        self.forms = []
        self.on_change = on_change
        self.loading = True
        self.source = ""
        self.width = 0
        self.error = None
        self.raw_image = None

    def resolve(self, href):
        href = href.strip()
        if href.startswith(("javascript:", "mailto:", "tel:")):
            return href
        return urljoin(self.url, href)

    def _changed(self):
        if self.on_change:
            self.on_change(self)

    # ---- loading (runs in a thread) ----
    def load(self, width, data=None, method="GET"):
        self.width = width
        _thread.start_new_thread(self._load, (data, method))

    def _load(self, data, method):
        try:
            r = fetch(self.url, data, method)
            self.url = r.url
            self.error = r.error
            ctype = r.ctype.lower()
            if ctype.startswith("image/"):
                self._show_image(r)
                return
            if not ctype.startswith(("text/", "application/xhtml", "application/xml")) and r.status == 200:
                self._download(r)
                return
            text = decode(r.body, r.ctype)
            self.source = text
            if "html" not in ctype and not text.lstrip()[:200].lower().startswith(("<!doctype html", "<html")):
                text = "<pre>%s</pre>" % html_escape(text)
            self.status = "analizando HTML..."
            self._changed()
            ensure_memory()
            r = None
            self.doc = html.parse(text)          # decoded with the page's charset, re-encoded as UTF-8
            text = None
            t = self.doc.find("title")
            if t is not None:
                self.title = " ".join(t.text_content().split())[:80] or self.url
            else:
                self.title = self.url
            self.sheets = []
            for node in self.doc.iter():
                if node.tag == "style":
                    s = css.StyleSheet()
                    s.add(node.text_content(), self.width)
                    self.sheets.append(s)
                elif node.tag == "link" and "stylesheet" in node.attrs.get("rel", "").lower() and node.attrs.get("href"):
                    media = node.attrs.get("media", "all").lower()
                    if "print" in media and "screen" not in media:
                        continue
                    self.status = "hojas de estilo..."
                    self._changed()
                    sr = fetch(self.resolve(node.attrs["href"]))
                    if sr.status == 200:
                        s = css.StyleSheet()
                        s.add(decode(sr.body, sr.ctype), self.width)
                        self.sheets.append(s)
            self.relayout()
            self.status = "listo"
            self.loading = False
            self._changed()
            self._load_images()
        except Exception as e:
            import sys
            sys.print_exception(e)
            self.doc = html.parse("<h1>Error del navegador</h1><pre>%s</pre>" % html_escape(repr(e)))
            self.sheets = []
            self.relayout()
            self.loading = False
            self.status = "error: %r" % e
            self._changed()

    def _show_image(self, r):
        from imaging import load
        try:
            self.images[r.url] = load(r.body, r.url)
        except Exception as e:
            self.status = "imagen no soportada: %r" % e
        self.title = r.url.rsplit("/", 1)[-1]
        self.doc = html.parse('<body style="margin:0;background:#222"><img src="%s"></body>' % r.url)
        self.sheets = []
        self.relayout()
        self.loading = False
        self.status = "imagen"
        self._changed()

    def _download(self, r):
        import os
        name = urlsplit(r.url).path.rsplit("/", 1)[-1] or "descarga"
        folder = "/disk/Descargas"
        try:
            os.mkdir(folder)
        except OSError:
            pass
        try:
            with open(folder + "/" + name, "wb") as f:
                f.write(r.body)
            msg = "Guardado en %s/%s (%d bytes, %s)" % (folder, name, len(r.body), r.ctype)
        except OSError as e:
            msg = "No se pudo guardar: %s" % e
        self.doc = html.parse("<h1>Descarga</h1><p>%s</p>" % html_escape(msg))
        self.sheets = []
        self.title = name
        self.relayout()
        self.loading = False
        self.status = msg
        self._changed()

    def _load_images(self):
        if self.doc is None:
            return
        seen = []
        for node in self.doc.iter("img"):
            src = node.attrs.get("src") or node.attrs.get("data-src")
            if not src or (node.style or {}).get("display") == "none":
                continue
            url = self.resolve(src)
            if url in self.images or url in seen or url.startswith("javascript:"):
                continue
            seen.append(url)
        from imaging import load
        changed = 0
        for i, url in enumerate(seen[:40]):
            self.status = "imagenes %d/%d" % (i + 1, len(seen))
            self._changed()
            try:
                r = fetch(url)
                if r.status == 200 and r.ctype.lower().startswith("image/") or url.lower().endswith((".png", ".gif", ".jpg", ".jpeg", ".bmp")):
                    img = load(r.body, url)
                    w, h = img.get_size()
                    if w * h > 1600 * 1200:
                        img = pygame.transform.scale(img, (w // 2, h // 2))
                    self.images[url] = img
                    changed += 1
                else:
                    self.images[url] = None
            except Exception:
                self.images[url] = None
            if changed and (changed % 4 == 0):
                self.relayout()
                self._changed()
        if changed:
            self.relayout()
        self.status = "listo"
        self._changed()

    def relayout(self, width=None):
        if width:
            self.width = width
        if self.doc is None:
            return
        css.compute(self.doc, self.sheets, self.width)
        self.layout = layout.Layout(self, self.width).run(self.doc)
        self.forms = list(self.doc.iter("form"))

    # ---- forms ----
    def widget_state(self, node):
        key = id(node)
        st = self.widgets.get(key)
        if st is None:
            kind = node.attrs.get("type", "text").lower()
            if node.tag == "textarea":
                value = node.text_content()
            elif node.tag == "select":
                opts = list(node.iter("option"))
                chosen = [o for o in opts if "selected" in o.attrs] or opts[:1]
                value = (chosen[0].attrs.get("value") or chosen[0].text_content().strip()) if chosen else ""
            else:
                value = node.attrs.get("value", "")
            st = {"value": value, "checked": "checked" in node.attrs, "kind": kind}
            self.widgets[key] = st
        return st

    def form_of(self, node):
        n = node
        while n is not None:
            if n.tag == "form":
                return n
            n = n.parent
        return None

    def submit(self, node):
        """(url, data, method) for the form that `node` belongs to."""
        form = self.form_of(node)
        if form is None:
            return None
        fields = []
        for el in form.iter():
            if el.tag not in ("input", "select", "textarea") or "disabled" in el.attrs:
                continue
            name = el.attrs.get("name")
            if not name:
                continue
            st = self.widget_state(el)
            kind = st["kind"]
            if el.tag == "input" and kind in ("submit", "button", "image", "reset") and el is not node:
                continue
            if kind in ("checkbox", "radio") and not st["checked"]:
                continue
            if kind in ("checkbox", "radio"):
                fields.append((name, el.attrs.get("value", "on")))
            else:
                fields.append((name, st["value"]))
        action = self.resolve(form.attrs.get("action", "") or self.url)
        method = form.attrs.get("method", "get").upper()
        query = urlencode(fields)
        if method == "POST":
            return action, query.encode(), "POST"
        return action.split("?")[0] + "?" + query, None, "GET"

    # ---- painting ----
    def paint(self, surf, scroll, area, focus=None, find=None):
        """Draw the page into surf at area (x, y, w, h), scrolled by `scroll` px."""
        ax, ay, aw, ah = area
        lay = self.layout
        surf.fill(lay.bg if lay else (255, 255, 255), area)
        if lay is None:
            return
        top, bottom = scroll, scroll + ah
        f = font()
        clip = surf.get_clip() if hasattr(surf, "get_clip") else None
        for it in lay.items:
            if it.y + it.h < top or it.y > bottom:
                continue
            x, y = ax + it.x, ay + it.y - scroll
            k = it.kind
            if k == "rect":
                _fill(surf, it.color, x, y, it.w, it.h, area)
            elif k == "text":
                sc, bold, under, strike, bg = it.extra
                if bg:
                    _fill(surf, bg, x, y, it.w, it.h, area)
                if y < ay or y + it.h > ay + ah + 16:
                    continue
                img = _render(it.data, it.color, sc)
                surf.blit(img, (x, y))
                if under or (it.href and False):
                    _fill(surf, it.color, x, y + it.h - 2, it.w, 1, area)
                if strike:
                    _fill(surf, it.color, x, y + it.h // 2, it.w, 1, area)
                if find and find.lower() in it.data.lower():
                    pygame.draw.rect(surf, (255, 200, 0), (x - 1, y - 1, it.w + 2, it.h + 2), 2)
            elif k == "image":
                img = self.images.get(it.data)
                if img is not None:
                    iw, ih = img.get_size()
                    if (iw, ih) != (it.w, it.h):
                        key = (it.data, it.w, it.h)
                        img = _scaled.get(key)
                        if img is None:
                            img = pygame.transform.scale(self.images[it.data], (it.w, it.h))
                            if len(_scaled) > 60:
                                _scaled.clear()
                            _scaled[key] = img
                    surf.blit(img, (x, y))
                else:
                    pygame.draw.rect(surf, (200, 200, 200), (x, y, it.w, it.h), 1)
                    if it.extra and it.h >= 16:
                        surf.blit(_render(it.extra[:max(1, it.w // 7)], (90, 90, 90)), (x + 3, y + 2))
            elif k == "border":
                t, r, b, l = it.extra
                c = it.color if isinstance(it.color, tuple) else (0, 0, 0)
                if t:
                    _fill(surf, c, x, y, it.w, t, area)
                if b:
                    _fill(surf, c, x, y + it.h - b, it.w, b, area)
                if l:
                    _fill(surf, c, x, y, l, it.h, area)
                if r:
                    _fill(surf, c, x + it.w - r, y, r, it.h, area)
            elif k == "hr":
                _fill(surf, it.color if isinstance(it.color, tuple) else (160, 160, 160), x, y, it.w, 1, area)
                _fill(surf, (230, 230, 230), x, y + 1, it.w, 1, area)
            elif k == "marker":
                mk = _render(it.data, it.color)
                surf.blit(mk, (x + it.w - mk.get_width(), y))
            elif k == "widget":
                self._paint_widget(surf, it, x, y, focus)

    def _paint_widget(self, surf, it, x, y, focus):
        node = it.node
        st = self.widget_state(node)
        kind = st["kind"]
        if node.tag == "button" or kind in ("submit", "button", "reset"):
            label = node.text_content().strip() if node.tag == "button" else node.attrs.get(
                "value", "Enviar" if kind == "submit" else "Boton")
            pygame.draw.rect(surf, (225, 228, 234), (x, y, it.w, it.h))
            pygame.draw.rect(surf, (140, 146, 156), (x, y, it.w, it.h), 1)
            surf.blit(_render(" ".join(label.split()), (20, 20, 20)), (x + 12, y + 5))
        elif kind in ("checkbox", "radio"):
            pygame.draw.rect(surf, (255, 255, 255), (x, y, 14, 14))
            pygame.draw.rect(surf, (120, 120, 120), (x, y, 14, 14), 1)
            if st["checked"]:
                pygame.draw.rect(surf, (40, 90, 200), (x + 3, y + 3, 8, 8))
        else:
            pygame.draw.rect(surf, (255, 255, 255), (x, y, it.w, it.h))
            pygame.draw.rect(surf, (40, 100, 220) if focus is node else (150, 150, 160), (x, y, it.w, it.h), 1)
            value = st["value"]
            if kind == "password":
                value = "*" * len(value)
            if not value and node.attrs.get("placeholder"):
                surf.blit(_render(node.attrs["placeholder"][:it.w // 7], (150, 150, 150)), (x + 5, y + 5))
            else:
                cols = max(1, it.w // 7)
                if node.tag == "textarea":
                    for i, line in enumerate(value.split("\n")[:max(1, it.h // 16)]):
                        surf.blit(_render(line[:cols], (0, 0, 0)), (x + 5, y + 4 + 18 * i))
                else:
                    shown = value[-cols:]
                    surf.blit(_render(shown, (0, 0, 0)), (x + 5, y + 5))
                    if focus is node:
                        cx = x + 5 + layout.ui_w(shown)
                        pygame.draw.line(surf, (0, 0, 0), (cx, y + 3), (cx, y + it.h - 4))
            if node.tag == "select":
                pygame.draw.polygon(surf, (80, 80, 80), [(x + it.w - 14, y + 8), (x + it.w - 6, y + 8), (x + it.w - 10, y + 13)])

    def item_at(self, x, y):
        if self.layout is None:
            return None
        for it in reversed(self.layout.items):
            if it.kind in ("text", "image", "widget") and it.x <= x < it.x + it.w and it.y <= y < it.y + it.h:
                return it
        return None

    def find_y(self, text, after=0):
        if self.layout is None or not text:
            return None
        low = text.lower()
        for it in self.layout.items:
            if it.kind == "text" and it.y > after and low in it.data.lower():
                return it.y
        return None


_text_cache = {}
_scaled = {}


def _render(s, color, f=None):
    """Text in a font (default: the browser's interface font), cached."""
    f = f or layout.ui_font()
    key = (s, color, id(f))
    img = _text_cache.get(key)
    if img is None:
        if len(_text_cache) > 700:              # each entry is a small image: keep memory in check
            _text_cache.clear()
        img = f.render(s, True, color if isinstance(color, tuple) else (0, 0, 0))
        _text_cache[key] = img
    return img


def _fill(surf, color, x, y, w, h, area):
    ax, ay, aw, ah = area
    x2, y2 = min(x + w, ax + aw), min(y + h, ay + ah)
    x, y = max(x, ax), max(y, ay)
    if x2 > x and y2 > y and isinstance(color, tuple):
        surf.fill(color, (x, y, x2 - x, y2 - y))
