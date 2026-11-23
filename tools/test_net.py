"""Network checks: boot PyKernel in QEMU with a network card and talk to
servers on this host (QEMU's NAT shows the host as 10.0.2.2).

    python tools/test_net.py
"""
import http.server
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import mkfs  # noqa: E402
import test as T  # noqa: E402
from run import make_disk  # noqa: E402

BIG = os.urandom(300000).hex().encode()          # 600 KB


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/big":
            body = BIG
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/hello")
            self.end_headers()
            return
        elif self.path == "/chunked":
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for part in (b"uno ", b"dos ", b"tres"):
                self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
            self.wfile.write(b"0\r\n\r\n")
            return
        else:
            body = b"<html><body><h1>hola</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def http_server():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def tls_server(work):
    """openssl s_server with a throwaway CA; None if openssl is missing."""
    if not shutil.which("openssl"):
        return None, None, []
    run = lambda *a: subprocess.run(a, cwd=work, check=True, capture_output=True)
    run("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", "ca.key")
    run("openssl", "req", "-x509", "-new", "-key", "ca.key", "-subj", "/CN=Test CA", "-days", "30", "-out", "ca.pem")
    (work / "ext.cnf").write_text("subjectAltName=DNS:test.local\n")
    procs, ports = [], []
    for kind in ("rsa", "ec"):
        if kind == "rsa":
            run("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", "k.key", "-subj", "/CN=test.local", "-out", "k.csr")
        else:
            run("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", "k.key")
            run("openssl", "req", "-new", "-key", "k.key", "-subj", "/CN=test.local", "-out", "k.csr")
        run("openssl", "x509", "-req", "-in", "k.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial",
            "-days", "30", "-extfile", "ext.cnf", "-out", kind + ".pem")
        os.rename(work / "k.key", work / (kind + ".key"))
        port = T_free_port()
        procs.append(subprocess.Popen(["openssl", "s_server", "-accept", str(port), "-cert", kind + ".pem", "-key",
                                       kind + ".key", "-tls1_3", "-www", "-quiet"], cwd=work,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        ports.append(port)
    return (work / "ca.pem").read_text(), ports, procs


def run(m, code, timeout=120):
    """Run a block of several lines at the prompt, as one exec()."""
    return m.cmd("exec(%r)" % code, timeout)


def T_free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    subprocess.run([sys.executable, str(ROOT / "tools" / "build.py"), "--fs"], check=True, capture_output=True)
    port = http_server()
    work = Path(tempfile.mkdtemp())
    ca, tls_ports, procs = tls_server(work)
    m = T.Machine(make_disk(ROOT / "build" / "net-disk.img", fresh=True))
    check = T.check
    try:
        m.until(T.PROMPT, 60)
        out = m.cmd("from kernel import net; net.up()", 30)
        check("DHCP gives the card an address", "10.0.2.15" in out, out)
        out = m.cmd("ifconfig")
        check("ifconfig shows the card and the gateway", "gateway 10.0.2.2" in out and "mac 52:54" in out, out)
        out = m.cmd("ping('10.0.2.2', 2)")
        check("ping the gateway (ICMP echo)", "2 received" in out, out)
        out = m.cmd("import requests; r = requests.get('http://10.0.2.2:%d/'); r.status_code, r.text" % port)
        check("HTTP GET over the kernel's TCP", "200" in out and "<h1>hola</h1>" in out, out)
        out = m.cmd("r = requests.get('http://10.0.2.2:%d/big'); len(r.content), r.content[-8:]" % port, 60)
        check("600 KB download arrives whole", "(600000, %r)" % BIG[-8:] in out, out)
        out = m.cmd("requests.get('http://10.0.2.2:%d/redirect').text" % port)
        check("redirects are followed", "hola" in out, out)
        out = m.cmd("requests.get('http://10.0.2.2:%d/chunked').text" % port)
        check("chunked transfer encoding", "uno dos tres" in out, out)
        out = m.cmd("wget('http://10.0.2.2:%d/', '/tmp.html'); len(open('/tmp.html').read())" % port)
        check("wget saves a file", "200: 39 bytes" in out and "\n39" in out, out)
        out = m.cmd("import socket; srv = socket.socket(); srv.bind(('', 7)); srv.listen(); netstat", 10)
        check("a socket can listen (netstat)", "LISTEN" in out, out)
        if ca:
            m.cmd("import ssl; ctx = ssl.create_default_context(cadata=%r)" % ca)
            for kind, p in zip(("RSA", "ECDSA"), tls_ports):
                out = run(m, "s = ctx.wrap_socket(socket.socket(), server_hostname='test.local')\n"
                          "try:\n    s.connect(('10.0.2.2', %d)); s.send(b'GET / HTTP/1.0\\r\\n\\r\\n')\n"
                          "    print(s.version(), s.recv(4000)[:15])\nfinally:\n    s.close()\n" % p)
                check("TLS 1.3 with a verified %s certificate" % kind, "TLSv1.3" in out and "HTTP/1.0 200" in out, out)
            out = run(m, "s = ctx.wrap_socket(socket.socket(), server_hostname='other.name')\n"
                      "try:\n    s.connect(('10.0.2.2', %d))\nexcept OSError as e:\n    print('refused:', e)\nfinally:\n    s.close()\n" % tls_ports[0])
            check("TLS refuses a certificate for another name", "refused:" in out and "other.name" in out, out)
            out = run(m, "s = ssl.create_default_context().wrap_socket(socket.socket(), server_hostname='test.local')\n"
                      "try:\n    s.connect(('10.0.2.2', %d))\nexcept OSError as e:\n    print('refused:', e)\nfinally:\n    s.close()\n" % tls_ports[0])
            check("TLS refuses a certificate from an unknown CA", "refused:" in out and "no trusted root" in out, out)
    except TimeoutError as e:
        check("no timeout", False, str(e)[-1500:])
    finally:
        m.close()
        for p in procs:
            p.kill()
    print("\n%d/%d network checks passed" % (sum(T.CHECKS), len(T.CHECKS)))
    sys.exit(0 if all(T.CHECKS) else 1)


if __name__ == "__main__":
    main()
