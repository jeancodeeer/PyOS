# pkg: install Python packages from the network.
#
#   pkg.install('pystone')          from micropython-lib (micropython.org/pi)
#   pkg.install('github:user/repo') a package.json in a GitHub repository
#   pkg.install('https://host/x.py')  one module
#   pkg.remove('pystone');  pkg.list();  pkg.search('json')
#
# Modules go to /disk/lib (on the import path), programs to /disk/bin, and
# /disk/var/pkg/installed.json remembers what came from where.
import json
import os

INDEX = "https://micropython.org/pi/v2"
LIB, BIN, DB = "/disk/lib", "/disk/bin", "/disk/var/pkg/installed.json"


def _mkdirs(path):
    parts = path.strip("/").split("/")
    for i in range(1, len(parts) + 1):
        try:
            os.mkdir("/" + "/".join(parts[:i]))
        except OSError:
            pass


def _get(url):
    from urllib import request
    return request.urlopen(url).read()


def _db():
    try:
        with open(DB) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(db):
    _mkdirs(DB.rsplit("/", 1)[0])
    with open(DB, "w") as f:
        json.dump(db, f)


def _write(dest, data):
    _mkdirs(dest.rsplit("/", 1)[0])
    with open(dest, "wb") as f:
        f.write(data)


def _github_url(spec, path, branch="HEAD"):
    repo = spec[len("github:"):]
    if "@" in repo:
        repo, branch = repo.split("@", 1)
    return "https://raw.githubusercontent.com/%s/%s/%s" % (repo, branch, path)


def install(spec, target=LIB, version="latest", _seen=None):
    """Install a package and its dependencies; returns the files written."""
    seen = _seen if _seen is not None else set()
    if spec in seen:
        return []
    seen.add(spec)
    written = []
    if spec.endswith(".py") and spec.startswith(("http://", "https://")):
        dest = target + "/" + spec.rsplit("/", 1)[-1]
        _write(dest, _get(spec))
        written.append(dest)
        name = spec.rsplit("/", 1)[-1][:-3]
        source = spec
    else:
        if spec.startswith("github:"):
            manifest = json.loads(_get(_github_url(spec, "package.json")))
            base = lambda p: _github_url(spec, p)
            name = manifest.get("name") or spec.rsplit("/", 1)[-1]
        else:
            name = spec
            manifest = json.loads(_get("%s/package/py/%s/%s.json" % (INDEX, spec, version)))
            base = None
        for path, short_hash in manifest.get("hashes", []):
            data = _get("%s/file/%s/%s" % (INDEX, short_hash[:2], short_hash))
            dest = target + "/" + path
            _write(dest, data)
            written.append(dest)
        for path, url in manifest.get("urls", []):
            if url.startswith("github:"):
                repo, _, rest = url[len("github:"):].partition("/")
                owner = repo
                repo, _, rest = rest.partition("/")
                url = _github_url("github:%s/%s" % (owner, repo), rest)
            elif base and not url.startswith("http"):
                url = base(url)
            dest = (BIN if path.startswith("bin/") else target) + "/" + (path[4:] if path.startswith("bin/") else path)
            _write(dest, _get(url))
            written.append(dest)
        for dep in manifest.get("deps", []):
            dep_name = dep[0] if isinstance(dep, list) else dep
            written += install(dep_name, target, _seen=seen)
        source = spec
        version = manifest.get("version", version)
    db = _db()
    db[name] = {"source": source, "version": version, "files": written}
    _save(db)
    return written


def remove(name):
    db = _db()
    entry = db.pop(name, None)
    if entry is None:
        raise KeyError("not installed: " + name)
    for path in entry["files"]:
        try:
            os.remove(path)
        except OSError:
            pass
    _save(db)
    return entry["files"]


def installed():
    return _db()


def search(text):
    """Names in the micropython-lib index that contain `text`."""
    index = json.loads(_get(INDEX + "/index.json"))
    return [(p["name"], p.get("version", ""), p.get("description", "")) for p in index.get("packages", [])
            if text in p["name"] or text in p.get("description", "")]
