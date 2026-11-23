# What the browser remembers: bookmarks, history and cookies, in /disk/browser.
import json
import os
from urllib.parse import urlsplit

DIR = "/disk/browser"
_bookmarks = None
_history = None
_cookies = {}        # host -> {name: value}


def _path(name):
    return DIR + "/" + name


def _load(name, default):
    try:
        with open(_path(name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(name, value):
    try:
        os.mkdir(DIR)
    except OSError:
        pass
    try:
        with open(_path(name), "w") as f:
            json.dump(value, f)
    except OSError:
        pass


def bookmarks():
    global _bookmarks
    if _bookmarks is None:
        _bookmarks = _load("bookmarks.json", [["Inicio", "about:home"]])
    return _bookmarks


def add_bookmark(title, url):
    b = bookmarks()
    if not any(u == url for _, u in b):
        b.append([title, url])
        _save("bookmarks.json", b)


def history():
    global _history
    if _history is None:
        _history = _load("history.json", [])
    return _history


def visit(title, url):
    if url.startswith("about:"):
        return
    h = history()
    h.append([title, url])
    del h[:-300]
    _save("history.json", h)


def set_cookie(url, header):
    host = urlsplit(url).hostname or ""
    pair = header.split(";")[0]
    if "=" in pair:
        k, v = pair.split("=", 1)
        _cookies.setdefault(host, {})[k.strip()] = v.strip()


def cookies_for(url):
    host = urlsplit(url).hostname or ""
    jar = {}
    for h, values in _cookies.items():
        if host == h or host.endswith("." + h.lstrip(".")):
            jar.update(values)
    return "; ".join("%s=%s" % kv for kv in jar.items())


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def about_page(url):
    if url == "about:bookmarks":
        rows = "".join('<li><a href="%s">%s</a></li>' % (_esc(u), _esc(t)) for t, u in bookmarks())
        return "<title>Marcadores</title><h1>Marcadores</h1><ul>%s</ul>" % rows
    if url == "about:history":
        rows = "".join('<li><a href="%s">%s</a></li>' % (_esc(u), _esc(t)) for t, u in reversed(history()[-100:]))
        return "<title>Historial</title><h1>Historial</h1><ol>%s</ol>" % rows
    return None
