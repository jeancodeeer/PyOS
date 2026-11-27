"""PyKernel's TLS client against OpenSSL servers on this PC, one kind of server
each: TLS 1.3 with AES-GCM or ChaCha20, TLS 1.3 that only takes P-256 (a
HelloRetryRequest), and TLS 1.2 with ECDHE-RSA / ECDHE-ECDSA, AES-GCM /
ChaCha20, X25519 / P-256. Needs openssl.

    python tools/test_tls.py
"""
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402
from run import make_disk  # noqa: E402

check = T.check
SERVERS = [  # (port, certificate kind, openssl options, expected version, expected cipher)
    (9441, "rsa", "-tls1_3 -ciphersuites TLS_AES_128_GCM_SHA256", "TLSv1.3", "TLS_AES_128_GCM_SHA256"),
    (9442, "rsa", "-tls1_3 -groups P-256", "TLSv1.3", None),
    (9443, "rsa", "-tls1_2 -cipher ECDHE-RSA-AES128-GCM-SHA256", "TLSv1.2", "ECDHE-RSA-AES128-GCM-SHA256"),
    (9444, "ec", "-tls1_2 -cipher ECDHE-ECDSA-CHACHA20-POLY1305 -groups P-256", "TLSv1.2",
     "ECDHE-ECDSA-CHACHA20-POLY1305"),
    (9445, "rsa", "-tls1_3 -ciphersuites TLS_CHACHA20_POLY1305_SHA256", "TLSv1.3", "TLS_CHACHA20_POLY1305_SHA256"),
    (9446, "rsa", "-tls1_2 -cipher ECDHE-RSA-CHACHA20-POLY1305 -groups P-256", "TLSv1.2", "ECDHE-RSA-CHACHA20-POLY1305"),
]
NAMES = {9441: "TLS 1.3, AES-128-GCM only", 9442: "TLS 1.3, P-256 only (HelloRetryRequest)",
         9443: "TLS 1.2, ECDHE-RSA with AES-128-GCM", 9444: "TLS 1.2, ECDHE-ECDSA with ChaCha20, P-256",
         9445: "TLS 1.3, ChaCha20-Poly1305", 9446: "TLS 1.2, ECDHE-RSA with ChaCha20, P-256"}

GUEST = '''
import socket, ssl
def get(port, ca):
    ctx = ssl.create_default_context(cadata=ca)
    s = ctx.wrap_socket(socket.socket(), server_hostname="pykernel.test")
    try:
        s.connect(("10.0.2.2", port))
        s.send(b"GET / HTTP/1.0\\r\\n\\r\\n")
        data = b""
        while len(data) < 200000:
            d = s.recv(4096)
            if not d:
                break
            data += d
        return (s.version(), s.cipher()[0], data[:15])
    except Exception as e:
        return ("error", repr(e)[:120], b"")
    finally:
        s.close()
'''


def make_certs(d):
    run = lambda *a: subprocess.run(a, cwd=d, check=True, capture_output=True)
    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem", "-days", "30",
        "-subj", "/CN=PyKernel Test CA", "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    (d / "ext.cnf").write_text("subjectAltName=DNS:pykernel.test\nbasicConstraints=CA:FALSE\nextendedKeyUsage=serverAuth\n")
    run("openssl", "genrsa", "-out", "rsa.key", "2048")
    run("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", "ec.key")
    for kind in ("rsa", "ec"):
        run("openssl", "req", "-new", "-key", kind + ".key", "-out", kind + ".csr", "-subj", "/CN=pykernel.test")
        run("openssl", "x509", "-req", "-in", kind + ".csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial",
            "-out", kind + ".pem", "-days", "20", "-extfile", "ext.cnf")
    # another CA, that PyKernel is not told to trust
    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "other.key", "-out", "other.pem",
        "-days", "30", "-subj", "/CN=Someone Else")


def main():
    if not shutil.which("openssl"):
        print("needs openssl")
        return False
    procs = []
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_certs(d)
        for port, kind, opts, _, _ in SERVERS:
            procs.append(subprocess.Popen(["openssl", "s_server", "-quiet", "-www", "-accept", str(port),
                                           "-cert", kind + ".pem", "-key", kind + ".key"] + opts.split(),
                                          cwd=d, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        time.sleep(1)
        ca = (d / "ca.pem").read_text()
        other = (d / "other.pem").read_text()
        m = T.Machine(make_disk(ROOT / "build" / "test-disk.img"))
        try:
            m.until(T.PROMPT, 90)
            m.cmd("exec(%r)" % GUEST, 20)
            m.cmd("CA = %r; OTHER = %r" % (ca, other), 20)
            for port, _, _, version, cipher in SERVERS:
                t0 = time.time()
                out = m.cmd("print(get(%d, CA))" % port, 180)
                line = [x for x in out.splitlines() if x.startswith("(")]
                got = line[-1] if line else out[-200:]
                ok = ("'%s'" % version) in got and (cipher is None or ("'%s'" % cipher) in got) and "HTTP/1.0 200" in got
                check("%s (%.0f s)" % (NAMES[port], time.time() - t0), ok, got)
            out = m.cmd("print(get(9443, OTHER))", 180)
            check("a certificate from a CA we do not trust is refused", "error" in out and "verif" in out.lower(), out[-300:])
        finally:
            m.close()
            for p in procs:
                p.kill()
    print("%d/%d passed" % (sum(T.CHECKS), len(T.CHECKS)))
    return all(T.CHECKS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
