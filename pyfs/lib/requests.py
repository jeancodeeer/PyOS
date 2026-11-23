# A small `requests`: requests.get(url).text, .json(), .status_code.
import json as _json
from urllib import request as _req
from urllib.parse import urlencode


class Response:
    def __init__(self, status, reason, headers, content, url):
        self.status_code, self.reason, self.headers, self.content, self.url = status, reason, headers, content, url
        self.ok = status < 400

    @property
    def text(self):
        ctype = self.headers.get("content-type") or ""
        enc = "utf-8"
        if "charset=" in ctype:
            enc = ctype.split("charset=")[1].split(";")[0].strip().lower()
        try:
            return self.content.decode(enc)
        except (UnicodeError, LookupError):
            return self.content.decode("latin-1")

    def json(self):
        return _json.loads(self.content)

    def raise_for_status(self):
        if not self.ok:
            raise OSError("HTTP %d %s for %s" % (self.status_code, self.reason, self.url))


def request(method, url, params=None, data=None, json=None, headers=None, timeout=30, verify=True):
    headers = dict(headers or {})
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    if json is not None:
        data = _json.dumps(json).encode()
        headers.setdefault("Content-Type", "application/json")
    elif isinstance(data, dict):
        data = urlencode(data).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    ctx = None
    if not verify:
        import ssl
        ctx = ssl._create_unverified_context()
    try:
        r = _req.urlopen(_req.Request(url, data, headers, method.upper()), timeout=timeout, context=ctx)
        return Response(r.status, r.reason, r.headers, r.read(), r.geturl())
    except _req.HTTPError as e:
        return Response(e.code, e.reason, e.headers, e.read(), url)


def get(url, **kw):
    return request("GET", url, **kw)


def post(url, **kw):
    return request("POST", url, **kw)


def put(url, **kw):
    return request("PUT", url, **kw)


def delete(url, **kw):
    return request("DELETE", url, **kw)


def head(url, **kw):
    return request("HEAD", url, **kw)
