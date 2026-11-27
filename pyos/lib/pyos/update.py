# SnakeyOS Update: the system updates itself from GitHub, like Windows Update.
#
# The provider is a GitHub repository's Releases. A release that updates
# SnakeyOS carries three files (made by tools/make_update.py, or by the GitHub
# workflow when a vX.Y.Z tag is pushed):
#
#   update.json       the manifest: version, notes, the package's size and SHA-256
#   update.json.sig   an ECDSA P-256 signature of update.json (hex, DER)
#   pyos-X.Y.Z.zip    the whole system: lib/, bin/, etc/, apps/, share/
#
# Safety: an update is only installed when update.json is signed by the key
# whose public half is in /etc/update_key.pub (built into the system), and
# when the package matches the SHA-256 and the size the manifest says. A
# changed package, a fake release or a man in the middle all fail there.
#
# Installing: the package goes to /disk/system.new; then the running copy
# becomes /disk/system.prev (for "go back") and the new one /disk/system,
# which the next boot uses (kernel.disktool.apply_update()).
#
#   from pyos import update
#   info = update.check()            None (up to date) or a dict about the new version
#   update.download(info, progress)  the package, checked
#   update.install(info, package)    to /disk/system; then restart
#   update.rollback()                back to the version before
import json
import os
import time

CONFIG = "/disk/etc/update.json"
HISTORY = "/disk/etc/update_history.json"
KEY_FILE = "/etc/update_key.pub"
SYSTEM = "/disk/system"
DEFAULTS = {
    "repo": "jeancodeeer/PyOS",         # where the releases are (GitHub redirects it if renamed)
    "api": "https://api.github.com",
    "channel": "stable",                 # "beta": prereleases too
    "auto_check": True,                  # look once a day, in the background
    "auto_install": False,               # download and install by itself (else: ask)
    "last_check": 0,
}
MAX_PACKAGE = 64 << 20


class UpdateError(Exception):
    pass


# ---- settings and history ----

def config():
    c = dict(DEFAULTS)
    try:
        with open(CONFIG) as f:
            c.update(json.load(f))
    except (OSError, ValueError):
        pass
    return c


def set_config(**changes):
    c = config()
    c.update(changes)
    _mkdirs("/disk/etc")
    with open(CONFIG, "w") as f:
        json.dump(c, f)
    return c


def history():
    try:
        with open(HISTORY) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _remember(entry):
    h = history()
    h.insert(0, entry)
    _mkdirs("/disk/etc")
    with open(HISTORY, "w") as f:
        json.dump(h[:30], f)


def current_version():
    """The version running now (not one installed and waiting for the restart)."""
    import pyos
    return pyos.running_version()


def restart_pending():
    """An update is installed and the computer has not been restarted since."""
    import pyos
    return pyos.version() != pyos.running_version()


def version_tuple(v):
    """'v1.2.10' -> (1, 2, 10); things that are not numbers count as 0."""
    out = []
    for part in v.strip().lstrip("vV").split("-")[0].split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


# ---- the network ----

def _get(url, accept="application/vnd.github+json"):
    from urllib import request
    req = request.Request(url, None, {"User-Agent": "SnakeyOS-Update/1.0", "Accept": accept})
    r = request.urlopen(req, timeout=60)
    if r.status != 200:
        raise UpdateError("%s: HTTP %d" % (url, r.status))
    return r.read()


def _asset(release, name):
    for a in release.get("assets", []):
        if a.get("name") == name:
            return a.get("browser_download_url")
    return None


# ---- check ----

def check():
    """Ask GitHub for the newest release. None if SnakeyOS is up to date; else a dict:
    version, notes, published, manifest_url, signature_url, package_url, size."""
    c = config()
    url = "%s/repos/%s/releases?per_page=15" % (c["api"].rstrip("/"), c["repo"])
    releases = json.loads(_get(url))
    set_config(last_check=int(time.time()))
    best = None
    for rel in releases:
        if rel.get("draft") or (rel.get("prerelease") and c["channel"] != "beta"):
            continue
        manifest, sig = _asset(rel, "update.json"), _asset(rel, "update.json.sig")
        if not manifest or not sig:
            continue                                  # a release without an update in it
        v = rel.get("tag_name", "")
        if best is None or version_tuple(v) > version_tuple(best["version"]):
            best = {"version": v.lstrip("vV"), "notes": rel.get("body") or "", "published": rel.get("published_at", ""),
                    "name": rel.get("name") or v, "manifest_url": manifest, "signature_url": sig, "release": rel}
    import pyos
    installed = max(version_tuple(current_version()), version_tuple(pyos.version()))
    if best is None or version_tuple(best["version"]) <= installed:
        return None
    return best


# ---- download and check what came ----

def public_key():
    """The update key built into the system: (x, y) on P-256."""
    try:
        with open(KEY_FILE) as f:
            text = f.read().strip()
    except OSError:
        raise UpdateError("este sistema no tiene clave de actualizaciones (%s): no puede comprobar la firma" % KEY_FILE)
    import binascii
    try:
        raw = binascii.unhexlify(text)
    except ValueError:
        raw = b""
    if len(raw) != 65 or raw[0] != 4:
        raise UpdateError("la clave de actualizaciones no es un punto P-256 sin comprimir")
    return int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:], "big")


def verify_manifest(data, signature_hex):
    """True if `data` (update.json's bytes) is signed with the system's update key."""
    import hashlib
    from crypto import ec, x509
    try:
        import binascii
        sig = binascii.unhexlify(signature_hex.strip())
        r, s = x509.decode_ecdsa_sig(sig)
    except Exception:
        return False
    return ec.verify("P-256", public_key(), hashlib.sha256(data).digest(), r, s)


def download(info, progress=None):
    """The package of the update `info` (from check()), checked: returns (manifest, package bytes)."""
    import hashlib
    say = progress or (lambda text, frac=None: None)
    say("Comprobando la firma...", 0.02)
    manifest_bytes = _get(info["manifest_url"], "application/octet-stream")
    signature = _get(info["signature_url"], "application/octet-stream").decode()
    if not verify_manifest(manifest_bytes, signature):
        raise UpdateError("la firma de la actualizacion no es valida: no se instala")
    m = json.loads(manifest_bytes)
    if m.get("format") != 1 or version_tuple(m.get("version", "0")) != version_tuple(info["version"]):
        raise UpdateError("el manifiesto no corresponde a esta version")
    size = int(m.get("size", 0))
    if not 0 < size <= MAX_PACKAGE:
        raise UpdateError("tamano de paquete no valido")
    url = _asset(info["release"], m["package"])
    if not url:
        raise UpdateError("la version no trae el paquete %s" % m["package"])
    say("Descargando SnakeyOS %s..." % m["version"], 0.05)
    package = _download(url, size, lambda frac: say("Descargando SnakeyOS %s..." % m["version"], 0.05 + 0.75 * frac))
    say("Comprobando el paquete...", 0.82)
    import binascii
    if len(package) != size or binascii.hexlify(hashlib.sha256(package).digest()).decode() != m.get("sha256"):
        raise UpdateError("el paquete descargado no coincide con el manifiesto firmado")
    return m, package


def _download(url, size, progress):
    """The bytes at url, in pieces, telling how far it got."""
    from urllib import request
    req = request.Request(url, None, {"User-Agent": "SnakeyOS-Update/1.0", "Accept": "application/octet-stream"})
    r = request.urlopen(req, timeout=120)
    if r.status != 200:
        raise UpdateError("descarga: HTTP %d" % r.status)
    out = bytearray()
    while True:
        piece = r.read(256 * 1024)
        if not piece:
            break
        out += piece
        if len(out) > MAX_PACKAGE:
            raise UpdateError("el paquete es mas grande de lo esperado")
        progress(min(1.0, len(out) / float(size)))
    return bytes(out)


# ---- install ----

def _mkdirs(path):
    part = ""
    for name in path.strip("/").split("/"):
        part += "/" + name
        try:
            os.mkdir(part)
        except OSError:
            pass


def _rmtree(path):
    try:
        entries = os.listdir(path)
    except OSError:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    for name in entries:
        full = path + "/" + name
        if os.stat(full)[0] & 0x4000:
            _rmtree(full)
        else:
            os.remove(full)
    os.rmdir(path)


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


SAFE_TOP = ("lib", "bin", "etc", "apps", "share", "licenses")


def install(manifest, package, progress=None):
    """Put the checked package in place: the next boot runs the new version."""
    say = progress or (lambda text, frac=None: None)
    from office import zipper
    say("Descomprimiendo...", 0.85)
    files = zipper.read(package)
    new = SYSTEM + ".new"
    _rmtree(new)
    _mkdirs(new)
    total = len(files)
    for i, (name, data) in enumerate(sorted(files.items())):
        # Safety: only paths inside the system's own folders ("../" or absolute paths could
        # write anywhere on the disk)
        parts = name.split("/")
        if name.startswith("/") or ".." in parts or parts[0] not in SAFE_TOP or name.endswith("/"):
            continue
        _mkdirs(new + "/" + "/".join(parts[:-1]))
        with open(new + "/" + name, "wb") as f:
            f.write(data)
        if i % 20 == 0:
            say("Instalando (%d de %d archivos)..." % (i, total), 0.85 + 0.12 * i / max(1, total))
    with open(new + "/etc/version", "w") as f:
        f.write(manifest["version"] + "\n")
    with open(new + "/INSTALLED", "w") as f:
        f.write("SnakeyOS %s from GitHub (%s)\n" % (manifest["version"], config()["repo"]))
    # the swap: two renames, so a power cut leaves one complete copy
    say("Terminando...", 0.98)
    _rmtree(SYSTEM + ".prev")
    if _exists(SYSTEM):
        os.rename(SYSTEM, SYSTEM + ".prev")
    os.rename(new, SYSTEM)
    _remember({"version": manifest["version"], "from": current_version_before(manifest), "date": _today(),
               "result": "instalada", "notes": manifest.get("notes", "")[:300]})
    say("Listo: reinicia para usar SnakeyOS %s" % manifest["version"], 1.0)


def current_version_before(manifest):
    v = current_version()
    return v if v != manifest["version"] else "?"


def rollback():
    """Back to the version installed before the last update."""
    if not _exists(SYSTEM + ".prev"):
        raise UpdateError("no hay una version anterior guardada")
    bad = SYSTEM + ".bad"
    _rmtree(bad)
    if _exists(SYSTEM):
        os.rename(SYSTEM, bad)
    os.rename(SYSTEM + ".prev", SYSTEM)
    _rmtree(bad)
    _remember({"version": current_version(), "date": _today(), "result": "version anterior restaurada"})


def _today():
    t = time.localtime()
    return "%04d-%02d-%02d %02d:%02d" % t[:5]


def update_now(progress=None):
    """Check, download and install in one go. Returns the version installed, or None."""
    info = check()
    if info is None:
        return None
    m, package = download(info, progress)
    install(m, package, progress)
    return m["version"]
