# Google and YouTube, for a browser without JavaScript.
#
# Both sites build their pages with JavaScript, which this browser does not
# run. What they send still has the information, so for these two sites
# the browser makes its own, simple page from it:
#
#   Google search   the results (title, link, text). If Google answers
#                   "turn on JavaScript" and gives no results, the same
#                   search is made on DuckDuckGo's HTML version, and the
#                   page says so.
#   YouTube         the search, the home page and the page of a video come
#                   with their data as JSON (ytInitialData) inside the HTML:
#                   titles, channels, views, lengths, thumbnails, the
#                   description and the related videos.
#
# The video plays in the Videos app (media/youtube.py finds a stream SnakeyOS
# can decode: H.264 Baseline + AAC, 360p).
#
#   page = sites.rewrite(url, html_text, fetch)   # our HTML, or None if this is not one of them
import json
from urllib.parse import urlsplit, quote_plus, unquote

DDG = "https://html.duckduckgo.com/html/?q="
YOUTUBE = "https://www.youtube.com"

STYLE = """<style>
body { font-family: sans-serif; margin: 16px 24px; background: #fff; color: #202124 }
.note { background: #fff7e0; border: 1px solid #f0d090; padding: 8px 12px; margin-bottom: 14px; color: #6a4a00 }
.r { margin-bottom: 18px } .r a { color: #1a0dab; font-size: 18px } .u { color: #0b6b30; font-size: 13px }
.s { color: #4d5156; font-size: 14px } form { margin-bottom: 16px } input[type=text] { width: 60% }
.v { margin-bottom: 14px; overflow: hidden } .v img { float: left; margin-right: 12px; width: 196px; height: 110px }
.v a { color: #0f0f0f; font-size: 16px; font-weight: bold } .m { color: #606060; font-size: 13px }
.yt { color: #ff0000; font-weight: bold } .big img { width: 480px; height: 270px }
.desc { white-space: pre-wrap; background: #f2f2f2; padding: 10px; font-size: 14px }
.play { display: inline-block; background: #cc0000; color: #fff; padding: 10px 18px; font-weight: bold }
</style>"""


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def is_ours(url):
    host = urlsplit(url).netloc.lower().split(":")[0]
    return host.endswith(("google.com", "youtube.com", "youtu.be", "duckduckgo.com"))


def rewrite(url, text, fetch):
    """Our own page for Google, DuckDuckGo and YouTube URLs; None for any other site."""
    u = urlsplit(url)
    host = u.netloc.lower().split(":")[0]
    query = _query(u.query)
    try:
        if host.endswith("google.com") and u.path == "/search":
            return google_results(query.get("q", ""), text, fetch)
        if host.endswith("duckduckgo.com") and u.path.startswith("/html"):
            return results_page(query.get("q", ""), ddg_results(text), "DuckDuckGo")
        if host == "youtu.be":
            return None
        if host.endswith("youtube.com"):
            if u.path == "/results":
                return youtube_search(query.get("search_query", ""), text)
            if u.path == "/watch":
                return youtube_watch(query.get("v", ""), text)
            if u.path in ("", "/"):
                return youtube_home(text)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return _page("Error", "<p>No se pudo leer la página de %s: %s</p>" % (esc(host), esc(repr(e))))
    return None


def _query(q):
    out = {}
    for part in q.split("&"):
        k, _, v = part.partition("=")
        if k:
            out[unquote(k.replace("+", " "))] = unquote(v.replace("+", " "))
    return out


def _page(title, body):
    return "<html><head><title>%s</title>%s</head><body>%s</body></html>" % (esc(title), STYLE, body)


# ---- search results ----

def _text_after(nodes, i, limit=260):
    """The text that comes after node i, until the next result."""
    out = []
    for n in nodes[i + 1:]:
        if n.tag in ("a", "h3") and out or n.tag == "h3":          # the next result starts
            break
        if n.tag is None and n.text and n.text.strip():
            out.append(n.text.strip())
        if sum(len(x) for x in out) > limit:
            break
    return " ".join(out)[:limit]


def _flat(doc):
    """Every node of the document, in reading order (text nodes too)."""
    out, stack = [], [doc]
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(reversed(n.children))
    return out


def _subtree_size(node):
    count, stack = 0, [node]
    while stack:
        n = stack.pop()
        count += 1
        stack.extend(n.children)
    return count


def _thousands(n):
    s = str(n)
    out = ""
    while len(s) > 3:
        out = "." + s[-3:] + out
        s = s[:-3]
    return s + out


def google_links(text):
    """[(title, url, snippet)] of a Google results page (the HTML one, without JavaScript)."""
    from browser import html
    nodes = _flat(html.parse(text))
    out, seen = [], set()
    for i, n in enumerate(nodes):
        if n.tag != "a":
            continue
        href = n.attrs.get("href", "")
        if href.startswith("/url?"):
            target = _query(href.split("?", 1)[1]).get("q", "")
        elif href.startswith("http") and "google." not in urlsplit(href).netloc:
            target = href
        else:
            continue
        title = " ".join(n.text_content().split())
        if not target.startswith("http") or not title or target in seen:
            continue
        h3 = n.find("h3")
        if h3 is not None:
            title = " ".join(h3.text_content().split())
        seen.add(target)
        snippet = _text_after(nodes, i + _subtree_size(n) - 1)     # the text after the link
        out.append((title, target, snippet.replace(title, "").strip()))
    return out


def ddg_results(text):
    """[(title, url, snippet)] of DuckDuckGo's HTML results."""
    from browser import html
    doc = html.parse(text)
    out = []
    snippets = [" ".join(n.text_content().split()) for n in doc.iter("a") if "result__snippet" in n.classes()]
    k = 0
    for n in doc.iter("a"):
        if "result__a" not in n.classes():
            continue
        href = n.attrs.get("href", "")
        if "uddg=" in href:
            href = _query(href.split("?", 1)[1]).get("uddg", href)
        if href.startswith("//"):
            href = "https:" + href
        out.append((" ".join(n.text_content().split()), href, snippets[k] if k < len(snippets) else ""))
        k += 1
    return out


def results_page(q, results, engine, note=""):
    form = ('<form action="https://www.google.com/search" method="get"><input type="text" name="q" value="%s"> '
            '<input type="submit" value="Buscar"></form>' % esc(q))
    rows = "".join('<div class="r"><a href="%s">%s</a><div class="u">%s</div><div class="s">%s</div></div>'
                   % (esc(url), esc(title), esc(url[:90]), esc(snippet)) for title, url, snippet in results)
    if not results:
        rows = "<p>Sin resultados.</p>"
    return _page("%s - Buscar" % q, "%s%s<p class=\"m\">Resultados de %s</p>%s" % (form, note, engine, rows))


def google_results(q, text, fetch):
    results = google_links(text)
    if results:
        return results_page(q, results, "Google")
    # Google wants JavaScript for this search: the same search on DuckDuckGo
    r = fetch(DDG + quote_plus(q))
    alt = ddg_results(r.body.decode("utf-8", "replace") if isinstance(r.body, bytes) else r.body) if r.status == 200 else []
    note = ('<div class="note">Google pidió JavaScript para esta búsqueda (este navegador no lo ejecuta), así que '
            'estos son los resultados de DuckDuckGo para lo mismo.</div>')
    return results_page(q, alt, "DuckDuckGo", note)


# ---- YouTube ----

def initial_json(text, name):
    """The JSON object a YouTube page assigns to `name` (ytInitialData, ytInitialPlayerResponse)."""
    at = text.find(name)
    while at >= 0:
        start = text.find("{", at)
        eq = text.find("=", at)
        if start >= 0 and 0 <= eq < start and start - at < 40:
            end = _matching_brace(text, start)
            if end > 0:
                return json.loads(text[start:end + 1])
        at = text.find(name, at + len(name))
    return None


def _matching_brace(text, start):
    """Where the {...} that starts at `start` ends (strings with braces inside are skipped)."""
    depth, i, n, in_str = 0, start, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def find_all(data, keys):
    """Every value stored under one of `keys`, anywhere in the JSON tree: [(key, value)]."""
    out, stack = [], [data]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            for k, v in x.items():
                if k in keys:
                    out.append((k, v))
                elif isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(x, list):
            stack.extend(reversed(x))
    out.reverse()
    return out


def t(x):
    """YouTube's text: {"simpleText": ...} or {"runs": [{"text": ...}]} or {"content": ...}."""
    if not x:
        return ""
    if isinstance(x, str):
        return x
    if "simpleText" in x:
        return x["simpleText"]
    if "content" in x:
        return x["content"]
    return "".join(r.get("text", "") for r in x.get("runs", []))


def thumb(video_id):
    return "https://i.ytimg.com/vi/%s/mqdefault.jpg" % video_id


def videos(data):
    """[{id, title, channel, meta}] from the renderers YouTube uses for a video in a list."""
    out, seen = [], set()
    for kind, v in find_all(data, ("videoRenderer", "compactVideoRenderer", "gridVideoRenderer", "lockupViewModel")):
        if kind == "lockupViewModel":
            vid = v.get("contentId", "")
            meta = v.get("metadata", {}).get("lockupMetadataViewModel", {})
            title = t(meta.get("title"))
            rows = find_all(meta.get("metadata", {}), ("metadataParts",))
            parts = [t(p.get("text")) for _, ps in rows for p in ps if isinstance(p, dict)]
            channel, info = (parts[0] if parts else ""), " · ".join(parts[1:])
            if v.get("contentType", "LOCKUP_CONTENT_TYPE_VIDEO") != "LOCKUP_CONTENT_TYPE_VIDEO":
                continue
        else:
            vid = v.get("videoId", "")
            title = t(v.get("title"))
            channel = t(v.get("ownerText") or v.get("longBylineText") or v.get("shortBylineText"))
            info = " · ".join(x for x in (t(v.get("viewCountText")), t(v.get("publishedTimeText")),
                                          t(v.get("lengthText"))) if x)
        if vid and title and vid not in seen:
            seen.add(vid)
            out.append({"id": vid, "title": title, "channel": channel, "meta": info})
    return out


def _search_form(q=""):
    return ('<form action="https://www.youtube.com/results" method="get"><span class="yt">▶ YouTube</span> '
            '<input type="text" name="search_query" value="%s"> <input type="submit" value="Buscar"></form>' % esc(q))


def _video_list(items):
    if not items:
        return "<p>No hay vídeos en esta página.</p>"
    return "".join('<div class="v"><a href="%s/watch?v=%s"><img src="%s" alt=""></a><a href="%s/watch?v=%s">%s</a>'
                   '<div class="m">%s</div><div class="m">%s</div></div>'
                   % (YOUTUBE, esc(v["id"]), thumb(v["id"]), YOUTUBE, esc(v["id"]), esc(v["title"]),
                      esc(v["channel"]), esc(v["meta"])) for v in items)


def youtube_search(q, text):
    data = initial_json(text, "ytInitialData")
    if data is None:
        return None
    return _page("%s - YouTube" % q, _search_form(q) + _video_list(videos(data)))


def youtube_home(text):
    data = initial_json(text, "ytInitialData")
    items = videos(data) if data else []
    note = "" if items else ('<p class="m">La portada de YouTube sale vacía sin una cuenta o sin JavaScript: '
                             'busca un vídeo arriba.</p>')
    return _page("YouTube", _search_form() + note + _video_list(items))


def youtube_watch(video_id, text):
    player = initial_json(text, "ytInitialPlayerResponse") or {}
    data = initial_json(text, "ytInitialData") or {}
    d = player.get("videoDetails", {})
    title = d.get("title") or t(next((v for k, v in find_all(data, ("title",)) if isinstance(v, dict)), {}))
    secs = int(d.get("lengthSeconds", "0") or 0)
    length = "%d:%02d:%02d" % (secs // 3600, secs // 60 % 60, secs % 60) if secs >= 3600 else "%d:%02d" % (secs // 60, secs % 60)
    views = d.get("viewCount", "")
    if views.isdigit():
        views = _thousands(int(views)) + " visualizaciones"
    body = (_search_form() +
            '<h2>%s</h2><div class="m">%s · %s · %s</div>' % (esc(title), esc(d.get("author", "")), esc(views), length) +
            '<p class="big"><img src="https://i.ytimg.com/vi/%s/hqdefault.jpg" alt=""></p>' % esc(video_id) +
            '<p><a class="play" href="pyos-video:youtube:%s">▶ Reproducir el video</a></p>' % esc(video_id) +
            '<p class="m">Se reproduce en la app Videos, en 360p (el formato de YouTube que SnakeyOS sabe decodificar).</p>' +
            '<h3>Descripción</h3><div class="desc">%s</div>' % esc(d.get("shortDescription", "")) +
            '<h3>Vídeos relacionados</h3>' + _video_list([v for v in videos(data) if v["id"] != video_id][:20]))
    return _page("%s - YouTube" % title, body)
