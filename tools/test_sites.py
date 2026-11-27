"""The browser's simple pages for Google and YouTube (browser/sites.py), on
sample pages shaped like the real ones. Runs on this PC, no network needed.

    python tools/test_sites.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pyos" / "lib"))
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402
from browser import sites  # noqa: E402

check = T.check
GOOGLE = ('<div><a href="/url?q=https://www.python.org/&amp;sa=U"><h3>Welcome to Python.org</h3>'
          '<div>www.python.org</div></a></div><div><span>The official home.</span></div>'
          '<div><a href="/url?q=https://es.wikipedia.org/wiki/Python"><h3>Python - Wikipedia</h3></a></div>'
          '<div>Python es un lenguaje.</div><a href="/search?start=10">Siguiente</a>')
WALL = '<html><noscript><meta http-equiv="refresh" content="0;url=/httpservice/retry/enablejs"></noscript></html>'
DDG = ('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2F&amp;rut=x">Python.org</a>'
       '<a class="result__snippet" href="x">The official home of Python</a>')
DATA = {"contents": [{"videoRenderer": {"videoId": "abc123", "title": {"runs": [{"text": "Curso de Python"}]},
                                        "ownerText": {"runs": [{"text": "Canal X"}]},
                                        "lengthText": {"simpleText": "10:01"}}},
                     {"lockupViewModel": {"contentId": "def456", "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
                                          "metadata": {"lockupMetadataViewModel": {
                                              "title": {"content": "Python en 100 s {}"},
                                              "metadata": {"rows": [{"metadataParts": [{"text": {"content": "Fireship"}}]}]}}}}}]}
PLAYER = {"videoDetails": {"title": "Curso de Python", "author": "Canal X", "viewCount": "1234567",
                           "lengthSeconds": "601", "shortDescription": "Aprende <Python>"}}


class Reply:
    status = 200
    body = DDG.encode()


def main():
    check("Google: results with their real links", sites.google_links(GOOGLE) == [
        ("Welcome to Python.org", "https://www.python.org/", "The official home."),
        ("Python - Wikipedia", "https://es.wikipedia.org/wiki/Python", "Python es un lenguaje.")])
    page = sites.rewrite("https://www.google.com/search?q=python", WALL, lambda url: Reply())
    check("Google asks for JavaScript: DuckDuckGo results instead, and a note",
          "www.python.org" in page and "DuckDuckGo" in page and "JavaScript" in page)
    search = "<script>var ytInitialData = %s;</script>" % json.dumps(DATA)
    page = sites.rewrite("https://www.youtube.com/results?search_query=python", search, None)
    check("YouTube search: both kinds of video entries, with thumbnails",
          "Curso de Python" in page and "Python en 100 s {}" in page and "i.ytimg.com/vi/abc123" in page)
    watch = ("<script>var ytInitialPlayerResponse = %s;var x=1;</script><script>var ytInitialData = %s;</script>"
             % (json.dumps(PLAYER), json.dumps(DATA)))
    page = sites.rewrite("https://www.youtube.com/watch?v=abc123", watch, None)
    check("YouTube video page: title, views, length, description, related",
          "1.234.567 visualizaciones" in page and "10:01" in page and "Aprende &lt;Python&gt;" in page
          and "def456" in page)
    check("other sites are left alone", sites.rewrite("https://example.com/", "<p>x</p>", None) is None)
    print("%d/%d passed" % (sum(T.CHECKS), len(T.CHECKS)))
    return all(T.CHECKS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
