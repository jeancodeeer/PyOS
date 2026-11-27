# JavaScript for the browser: the page's scripts run in the JavaScript
# engine written in Python (pyos/lib/js) against a DOM written in JavaScript (dom.js).
#
#   js = Scripts(page)
#   js.start()          the page's tree goes to JS, its scripts run, DOMContentLoaded, load
#   js.tick()           timers and promises (call it a few times a second); True if the page changed
#   js.event(node, "click")   the user clicked node: False if the page cancelled the default
#   js.close()
#
# When scripts change the tree, sync() takes it back from JS and the page is
# laid out again. Everything the DOM cannot do by itself (the network,
# cookies, where things are on screen...) comes here through callback().
import json
from urllib.parse import urlsplit, urljoin

MAX_SCRIPT_BYTES = 6 << 20          # all the scripts of a page together
SCRIPT_TIME_MS = 4000               # one script at most
SCRIPT_MEMORY = 32 << 20            # what one script may add to the page's memory (a runaway loop stops here)
# trackers and ads: nothing on the page needs them, and they cost time
BLOCKED = ("googletagmanager.com", "google-analytics.com", "doubleclick.net", "googlesyndication.com",
           "facebook.net", "connect.facebook", "hotjar.com", "segment.com", "segment.io", "scorecardresearch.com",
           "quantserve.com", "adsystem", "amazon-adsystem", "criteo", "taboola", "outbrain", "newrelic.com",
           "nr-data.net", "clarity.ms", "mixpanel", "fullstory", "optimizely", "chartbeat", "adnxs", "pubmatic",
           "rubiconproject", "moatads", "cookielaw.org", "onetrust", "cookiebot", "sentry-cdn", "browser.sentry")
_dom_source = None


def available():
    try:
        import js  # noqa: F401
        return True
    except ImportError:
        return False


def _dom_js():
    global _dom_source
    if _dom_source is None:
        import os
        here = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
        with open(here + "/dom.js") as f:
            _dom_source = f.read()
    return _dom_source


class Scripts:
    def __init__(self, page):
        self.page = page
        self.ctx = None
        self.nodes = {}            # JS id -> html.Node
        self.ids = {}              # id(html.Node) -> JS id
        self.next_id = 1
        self.log = []              # the page's console (for a developer view)
        self.errors = 0
        self.used = 0              # bytes of script run
        self.rects = None          # JS id -> (x, y, w, h), from the layout (made when asked)
        self.busy = False

    # ---- start ----
    def start(self):
        import js as _js
        import time
        try:
            from kernel import timer
            per_ms = timer.tsc_per_ms or timer.calibrate()
        except Exception:
            per_ms = 0
        try:
            from pyos import settings
            tz = settings.get("zona_minutos") or 0
        except Exception:
            tz = 0
        _js.set_clock(time.time() * 1000, tz, per_ms)
        self.ctx = _js.Context(self.callback)
        self.busy = True
        try:
            self.ctx.eval(_dom_js(), "dom.js", 10000)
            root = self.page.doc.find("html") or self.page.doc
            self._tree_json = json.dumps(self.tree(root))
            self.ctx.eval("__dom_load(%s)" % json.dumps(self.page.url), "load", 10000)
            self._tree_json = None
            for node in list(self.page.doc.iter("script")):
                self.run_script_node(node)
                self.ctx.run_jobs(500, SCRIPT_MEMORY)
            self.ctx.eval("__ready()", "ready", SCRIPT_TIME_MS, SCRIPT_MEMORY)
            self.ctx.run_jobs(1000, SCRIPT_MEMORY)
            for _ in range(5):                          # the first timers (setTimeout 0, frames)
                self.ctx.eval("__tick()", "tick", 2000, SCRIPT_MEMORY)
                self.ctx.run_jobs(500, SCRIPT_MEMORY)
        finally:
            self.busy = False
        return self.changed()

    def run_script_node(self, node):
        a = node.attrs
        kind = a.get("type", "").lower().strip()
        if kind not in ("", "text/javascript", "application/javascript", "module", "text/ecmascript",
                        "application/ecmascript"):
            return                                      # JSON, templates, other languages
        if "nomodule" in a:
            return                                      # for old browsers only (polyfills): a modern engine skips them
        if kind == "module":
            pass                                        # tried as a script: works when it imports nothing
        src = a.get("src")
        if src:
            url = self.page.resolve(src)
            code = self.load(url)
            if code is None:
                return
            name = url
        else:
            code = node.text_content()
            name = "inline"
        if not code.strip():
            return
        self.used += len(code)
        if self.used > MAX_SCRIPT_BYTES:
            return
        try:
            self.ctx.eval("__before(%d)" % self.ids.get(id(node), 0), "before", 2000)
            self.ctx.eval(code, name, SCRIPT_TIME_MS, SCRIPT_MEMORY)   # the code itself: parsed once, no copies
        except Exception as e:
            self.errors += 1
            self.log.append(("error", "%s: %s" % (name, e)))
        finally:
            try:
                self.ctx.eval("__after()", "after", 1000)
            except Exception:
                pass

    def load(self, url):
        if any(b in url for b in BLOCKED):
            self.log.append(("info", "bloqueado (rastreador): " + url))
            return None
        from browser import page as pagemod
        r = pagemod.fetch(url)
        if r.status != 200:
            self.log.append(("error", "no se pudo cargar %s (%s)" % (url, r.status)))
            return None
        return pagemod.decode(r.body, r.ctype)

    # ---- the tree, both ways ----
    def tree(self, node):
        """html.Node -> [id, tag, attrs, children...] (text as strings)."""
        if node.tag is None:
            return node.text
        jid = self.next_id
        self.next_id += 1
        self.nodes[jid] = node
        self.ids[id(node)] = jid
        out = [jid, node.tag, dict(node.attrs)]
        for c in node.children:
            if c.tag is None:
                if c.text:
                    out.append(c.text)
            elif c.tag not in ("!--", "#comment"):
                out.append(self.tree(c))
        return out

    def changed(self):
        return bool(self.ctx and self.ctx.eval("__dirty()", "dirty", 1000))

    def sync(self):
        """Take the tree back from JS and lay the page out again."""
        from browser import html
        data = json.loads(self.ctx.eval("__dump()", "dump", 5000))
        self.nodes, self.ids = {}, {}

        def build(j, parent):
            if isinstance(j, str):
                n = html.Node(None, None, parent, j)
                parent.children.append(n)
                return
            jid, tag, attrs = j[0], j[1], j[2]
            n = html.Node(tag, attrs, parent)
            parent.children.append(n)
            self.nodes[jid] = n
            self.ids[id(n)] = jid
            if jid >= self.next_id:
                self.next_id = jid + 1
            for c in j[3:]:
                build(c, n)

        doc = self.page.doc
        old = doc.find("html")
        holder = old.parent if old is not None else doc
        new_children = [c for c in holder.children if c is not old]
        holder.children = new_children
        build(data, holder)
        t = doc.find("title")
        if t is not None:
            self.page.title = " ".join(t.text_content().split())[:80] or self.page.url
        self.page.restyle()
        self.rects = None

    # ---- while the page is open ----
    def tick(self):
        if self.ctx is None or self.busy:
            return False
        self.busy = True
        try:
            self.ctx.eval("__tick()", "tick", 1500, SCRIPT_MEMORY)
            self.ctx.run_jobs(500, SCRIPT_MEMORY)
            if self.changed():
                self.sync()
                return True
        except Exception as e:
            self.log.append(("error", "timer: %s" % e))
        finally:
            self.busy = False
        return False

    def element_id(self, node):
        while node is not None:
            jid = self.ids.get(id(node))
            if jid:
                return jid
            node = node.parent
        return 0

    def event(self, node, kind, extra=None):
        """Tell the page the user did something; False if it cancelled the default."""
        jid = self.element_id(node)
        if not jid or self.ctx is None or self.busy:
            return True
        self.busy = True
        try:
            ok = self.ctx.eval("__event(%d, %s, %s)" % (jid, json.dumps(kind), json.dumps(extra or {})), "event", 3000)
            self.ctx.run_jobs(500, SCRIPT_MEMORY)
            self.ctx.eval("__tick()", "tick", 1500, SCRIPT_MEMORY)
            self.ctx.run_jobs(500, SCRIPT_MEMORY)
            if self.changed():
                self.sync()
            return ok is not False
        except Exception as e:
            self.log.append(("error", "%s: %s" % (kind, e)))
            return True
        finally:
            self.busy = False

    def set_value(self, node, value):
        jid = self.element_id(node)
        if jid and self.ctx and not self.busy:
            try:
                self.ctx.eval("__set_value(%d, %s)" % (jid, json.dumps(value)), "input", 2000)
            except Exception:
                pass

    def close(self):
        if self.ctx:
            self.ctx.close()
            self.ctx = None

    # ---- what the page's scripts ask for ----
    def callback(self, name, arg):
        if name == "tree":                    # already JSON text
            return self._tree_json
        a = json.loads(arg) if arg else None
        f = getattr(self, "_cb_" + name, None)
        if f is None:
            return None
        out = f(a)
        return None if out is None else json.dumps(out)

    def _cb_parse(self, text):
        from browser import html
        doc = html.parse("<body>" + text + "</body>")
        body = doc.find("body")
        if body is None:
            return []
        out = []
        for c in body.children:
            if c.tag is None:
                out.append(c.text)
            else:
                out.append(self._plain_tree(c))
        return out

    def _plain_tree(self, node):
        if node.tag is None:
            return node.text
        return [0, node.tag, dict(node.attrs)] + [self._plain_tree(c) for c in node.children
                                                    if c.tag is not None or c.text]

    def _cb_parse_document(self, text):
        from browser import html
        root = html.parse(text).find("html")
        return self._plain_tree(root) if root is not None else None

    def _cb_resolve(self, url):
        if url.startswith(("javascript:", "data:", "blob:", "mailto:", "tel:", "about:")):
            return url
        return urljoin(self.page.url, url)

    def _cb_url_parse(self, a):
        url = a["url"]
        if a.get("base"):
            url = urljoin(a["base"], url)
        u = urlsplit(url)
        if not u.scheme or (u.scheme in ("http", "https") and not u.netloc):
            return None
        host = u.netloc.rsplit("@", 1)[-1]
        hostname, _, port = host.partition(":") if not host.startswith("[") else (host, "", "")
        return {"protocol": u.scheme + ":", "hostname": hostname, "port": port, "pathname": u.path or "/",
                "search": ("?" + u.query) if u.query else "", "hash": ("#" + u.fragment) if u.fragment else "",
                "username": "", "password": ""}

    def _cb_fetch(self, a):
        from browser import page as pagemod
        url = a["url"]
        if any(b in url for b in BLOCKED):
            return {"error": "blocked"}
        body = a.get("body")
        method = a.get("method", "GET")
        r = pagemod.fetch(url, body.encode() if isinstance(body, str) else None, method, a.get("headers") or {})
        if r.status == 0:
            return {"error": r.error or "network"}
        return {"status": r.status, "url": r.url, "headers": {"content-type": r.ctype},
                "body": pagemod.decode(r.body, r.ctype) if r.body else ""}

    def _cb_load_script(self, url):
        return self.load(url)

    def _cb_cookie_get(self, _):
        from browser import store
        return store.cookies_for(self.page.url) or ""

    def _cb_cookie_set(self, text):
        from browser import store
        store.set_cookie(self.page.url, text)

    def _origin(self):
        u = urlsplit(self.page.url)
        return "%s_%s" % (u.scheme, u.netloc.replace(":", "_"))

    def _cb_storage_load(self, _):
        try:
            with open("/disk/browser/storage_%s.json" % self._origin()) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _cb_storage_save(self, data):
        try:
            import os
            try:
                os.mkdir("/disk/browser")
            except OSError:
                pass
            text = json.dumps(data)
            if len(text) < (5 << 20):                    # localStorage's usual limit
                with open("/disk/browser/storage_%s.json" % self._origin(), "w") as f:
                    f.write(text)
        except OSError:
            pass

    def _cb_log(self, a):
        self.log.append((a.get("level", "log"), a.get("text", "")[:500]))
        if len(self.log) > 300:
            del self.log[:100]

    def _cb_error(self, text):
        self.errors += 1
        self.log.append(("error", text[:800]))

    def _cb_user_agent(self, _):
        from browser import page as pagemod
        return pagemod.JS_USER_AGENT

    def _cb_media(self, query):
        from browser import css
        q = query.strip()
        if q.startswith("@media"):
            q = q[6:]
        return css._media_ok(q.lower(), self.page.width or 1000)

    def _cb_rect(self, jid):
        if self.rects is None:
            self.rects = self._make_rects()
        return self.rects.get(jid, [0, 0, 0, 0])

    def _make_rects(self):
        """Where each element is: the box around the things drawn for it and inside it."""
        out = {}
        lay = self.page.layout
        if lay is None:
            return out
        for it in lay.items:
            n = it.node
            while n is not None:
                jid = self.ids.get(id(n))
                if jid:
                    r = out.get(jid)
                    if r is None:
                        out[jid] = [it.x, it.y, it.w, it.h]
                    else:
                        x0, y0 = min(r[0], it.x), min(r[1], it.y)
                        x1, y1 = max(r[0] + r[2], it.x + it.w), max(r[1] + r[3], it.y + it.h)
                        out[jid] = [x0, y0, x1 - x0, y1 - y0]
                n = n.parent
        return out

    def _cb_style(self, jid):
        n = self.nodes.get(jid)
        st = (n.style if n is not None else None) or {}
        out = {}
        for k, v in st.items():
            if k == "--":
                for name, val in v.items():
                    out[name] = val
            elif isinstance(v, tuple) and len(v) == 3:
                out[k] = "rgb(%d, %d, %d)" % v
            elif isinstance(v, int):
                out[k] = "%dpx" % v
            elif isinstance(v, str):
                out[k] = v
        out.setdefault("display", "inline")
        out.setdefault("visibility", "visible")
        out.setdefault("opacity", "1")
        out.setdefault("position", "static")
        return out

    def _cb_navigate(self, url):
        self.page.navigate_to = url
        self.page._changed()

    def _cb_open(self, url):
        self.page.navigate_to = url
        self.page._changed()

    def _cb_url_changed(self, url):
        self.page.url = url
        self.page._changed()

    def _cb_submit(self, jid):
        n = self.nodes.get(jid)
        if n is not None:
            self.page.pending_submit = n

    def _cb_alert(self, text):
        self.log.append(("alert", text))
        self.page.alert = text

    def _cb_confirm(self, text):
        self.log.append(("confirm", text))
        return True

    def _cb_clipboard(self, text):
        try:
            from desktop import clipboard
            clipboard.set(text)
        except Exception:
            pass

    def _cb_clipboard_read(self, _):
        try:
            from desktop import clipboard
            return clipboard.get()
        except Exception:
            return ""

    def _cb_scroll_to(self, jid):
        r = self._cb_rect(jid)
        if r and r[3]:
            self.page.scroll_request = r[1]

    def _cb_document_write(self, text):
        self.log.append(("info", "document.write (%d chars) ignored" % len(text)))
