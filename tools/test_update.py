"""SnakeyOS Update (pyos/lib/pyos/update.py) end to end, against a stand-in for
GitHub on this PC (its releases API, and downloads that redirect as GitHub's
do): find the new version, check its signature and package, install it,
restart and run it; and refuse a package that was changed or a manifest
signed with another key. Needs the `cryptography` package.

    python tools/test_update.py
"""
import http.server
import json
import shutil
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402
import make_update  # noqa: E402
from run import make_disk  # noqa: E402

check = T.check


def keypair(folder, name):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    key = ec.generate_private_key(ec.SECP256R1())
    pem = folder / (name + ".pem")
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return pem, pub.hex()


def release(folder, version, key_pem, public_hex, tamper=False):
    """dist/ files for `version` signed with key_pem, moved to folder/version/."""
    make_update.PUBLIC = folder / "public.pub"
    make_update.PUBLIC.write_text(public_hex + "\n")
    make_update.build(version, None, str(key_pem))
    out = folder / version
    out.mkdir()
    for name in ("snakeyos-%s.zip" % version, "update.json", "update.json.sig"):
        shutil.move(str(ROOT / "dist" / name), str(out / name))
    if tamper:                                     # a byte changed in the package after it was signed
        p = out / ("snakeyos-%s.zip" % version)
        data = bytearray(p.read_bytes())
        data[len(data) // 2] ^= 0xFF
        p.write_bytes(bytes(data))


class GitHub(http.server.SimpleHTTPRequestHandler):
    """/repos/test/pyos/releases, and /download/<version>/<file> -> 302 -> /files/<version>/<file>."""
    folder = None
    versions = []
    port = 0

    def do_GET(self):
        if self.path.startswith("/repos/test/pyos/releases"):
            rels = []
            for v in self.versions:
                assets = [{"name": n, "browser_download_url": "http://10.0.2.2:%d/download/%s/%s" % (self.port, v, n)}
                          for n in ("snakeyos-%s.zip" % v, "update.json", "update.json.sig")]
                rels.append({"tag_name": "v" + v, "name": "SnakeyOS " + v, "body": "Novedades de la %s" % v,
                             "draft": False, "prerelease": False, "assets": assets})
            body = json.dumps(rels).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/download/"):
            self.send_response(302)
            self.send_header("Location", "/files/" + self.path[len("/download/"):])
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path.startswith("/files/"):
            p = self.folder / self.path[len("/files/"):]
            data = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


def main():
    try:
        import cryptography  # noqa: F401
    except ImportError:
        print("needs the cryptography package")
        return False
    saved_public = make_update.PUBLIC
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        good_pem, good_pub = keypair(d, "good")
        bad_pem, bad_pub = keypair(d, "bad")
        release(d, "9.9.9", good_pem, good_pub)
        release(d, "9.9.10", good_pem, good_pub, tamper=True)
        release(d, "9.9.11", bad_pem, bad_pub)            # signed with a key the system does not have
        make_update.PUBLIC = saved_public
        GitHub.folder = d
        httpd = socketserver.ThreadingTCPServer(("0.0.0.0", 0), GitHub)
        GitHub.port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        disk = make_disk(ROOT / "build" / "update-disk.img", fresh=True)
        setup = ("from pyos import update\nwith open('/etc/update_key.pub', 'w') as f:\n    f.write(%r)\n"
                 "update.set_config(api='http://10.0.2.2:%d', repo='test/pyos')" % (good_pub, GitHub.port))
        m = T.Machine(disk)
        try:
            m.until(T.PROMPT, 90)
            m.cmd("import os; os.mkdir('/disk/etc') if 'etc' not in os.listdir('/disk') else None", 30)
            m.cmd("exec(%r)" % setup, 30)
            # the newest release (9.9.11) is signed with a stranger's key: refused
            GitHub.versions = ["9.9.11"]
            out = m.cmd("info = update.check(); print(info['version']); update.download(info)", 300)
            check("a release signed with another key is refused", "firma" in out and "no es valida" in out, out[-300:])
            GitHub.versions = ["9.9.10"]
            out = m.cmd("info = update.check(); update.download(info)", 300)
            check("a package changed after signing is refused", "no coincide" in out, out[-300:])
            GitHub.versions = ["9.9.9", "1.0.0"]
            out = m.cmd("info = update.check(); print('NEW', info['version'], info['notes'])", 300)
            check("finds the newest version on 'GitHub'", "NEW 9.9.9 Novedades de la 9.9.9" in out, out[-300:])
            out = m.cmd("mf, pkg = update.download(info); update.install(mf, pkg); "
                        "print('PENDING', update.restart_pending(), open('/disk/system/etc/version').read().strip())", 600)
            check("downloads, checks and installs it (a restart pending)", "PENDING True 9.9.9" in out, out[-300:])
            out = m.cmd("print('AGAIN', update.check())", 120)
            check("after installing: nothing newer to get", "AGAIN None" in out, out[-200:])
            out = m.cmd("print(update.history()[0]['version'], update.history()[0]['result'])", 30)
            check("the history remembers it", "9.9.9 instalada" in out, out[-200:])
        finally:
            m.close()
        m = T.Machine(disk)                            # the restart
        try:
            m.until(T.PROMPT, 120)
            out = m.cmd("import pyos, sys; print('NOW', pyos.running_version(), open('/etc/version').read().strip(), "
                        "sys.path[0])", 30)
            check("after the restart SnakeyOS 9.9.9 runs (its /etc and /lib in use)",
                  "NOW 9.9.9 9.9.9 /disk/system/lib" in out, out[-300:])
        finally:
            m.close()
            httpd.shutdown()
    print("%d/%d passed" % (sum(T.CHECKS), len(T.CHECKS)))
    return all(T.CHECKS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
