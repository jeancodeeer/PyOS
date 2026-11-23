"""Desktop and browser checks: boot PyKernel in QEMU, open every desktop app,
load a test web site served from this host, and photograph the screen.

    python tools/test_desktop.py
"""
import http.server
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402
from run import host_path, make_disk  # noqa: E402

SITE = {
    "/": b"""<!DOCTYPE html><html><head><title>Sitio de prueba</title>
<link rel="stylesheet" href="/s.css"><style>.box{background:#ffeeaa;border:1px solid #cc9900;padding:6px}</style>
</head><body><h1 id="top">Hola PyKernel</h1>
<p>Texto con <b>negrita</b>, <a href="/dos">un enlace</a> y acentos: canci\xc3\xb3n.</p>
<div class="box">caja con estilo</div>
<ul><li>uno</li><li>dos</li></ul>
<table border="1"><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>
<form action="/buscar"><input name="q" value="py"><input type="submit" value="Ir"></form>
<img src="/img.bmp" alt="bmp"></body></html>""",
    "/s.css": b"h1 { color: #aa0000 } body { background: #f0f4ff }",
    "/dos": b"<html><head><title>Pagina dos</title></head><body><p>segunda</p></body></html>",
}


def _bmp():
    w, h = 8, 8
    row = bytes([0, 0, 255] * w)                  # red, BGR
    pixels = row * h
    header = b"BM" + (54 + len(pixels)).to_bytes(4, "little") + b"\0\0\0\0" + (54).to_bytes(4, "little")
    info = (40).to_bytes(4, "little") + w.to_bytes(4, "little") + h.to_bytes(4, "little") + \
        (1).to_bytes(2, "little") + (24).to_bytes(2, "little") + bytes(24)
    return header + info + pixels


SITE["/img.bmp"] = _bmp()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        body = SITE.get(path)
        if self.path.startswith("/buscar"):
            body = b"<html><head><title>resultado</title></head><body>q=" + self.path.split("q=")[-1].encode() + b"</body></html>"
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        ctype = "text/css" if path.endswith(".css") else "image/bmp" if path.endswith(".bmp") else "text/html"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    subprocess.run([sys.executable, str(ROOT / "tools" / "build.py"), "--fs"], check=True, capture_output=True)
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    m = T.Machine(make_disk(ROOT / "build" / "desktop-disk.img", fresh=True))
    check = T.check
    shot = Path(tempfile.mkdtemp()) / "desk.ppm"
    try:
        m.until(T.PROMPT, 60)
        # the browser engine on its own, without the desktop
        out = m.cmd("from browser import page as P; p = P.Page('http://10.0.2.2:%d/'); p.width = 900; "
                    "p._load(None, 'GET'); p.title, len(p.layout.items) > 20, "
                    "[i.href for i in p.layout.items if i.href][:1], "
                    "any(i.kind == 'image' for i in p.layout.items), p.images.get('http://10.0.2.2:%d/img.bmp') is not None"
                    % (port, port), 60)
        check("browser engine: fetch, parse, style, lay out, load images",
              "'Sitio de prueba'" in out and "True, ['http://10.0.2.2:%d/dos']" % port in out and out.rstrip().endswith("True, True)"), out)
        out = m.cmd("h1 = p.doc.find('h1'); h1.style['color'], p.doc.find('body').style['background-color'], "
                    "p.doc.find('div').style.get('background-color')")
        check("CSS: linked sheet, <style> and the cascade", "(170, 0, 0)" in out and "(240, 244, 255)" in out
              and "(255, 238, 170)" in out, out)
        out = m.cmd("f = p.doc.find('input'); p.widget_state(f)['value'] = 'pykernel'; p.submit(f)")
        check("forms: a GET form builds its URL", "/buscar?q=pykernel" in out, out)
        out = m.cmd("from imaging import jpeg, gif; import pygame; "
                    "[type(jpeg.load('/share/images/montanas.jpg')).__name__, gif.load('/share/images/estrella.gif').get_size()]", 120)
        check("JPEG and GIF decoders", "['Surface', (200, 200)]" in out, out)

        # the desktop: open every app, the browser on the test site, then leave
        script = ("from desktop import wm, apps\n"
                  "opened = []\n"
                  "def open_one(n):\n"
                  "    while len(wm.wm.windows) >= 5:\n"
                  "        wm.wm.close(wm.wm.windows[0])\n"
                  "    w = wm.wm.launch(n)\n"
                  "    opened.append((n, w is not None))\n"
                  "names = [n for n in apps.names() if n != 'jeancode' and apps.info(n)['mode'] == 'window']\n"
                  "wm.SCRIPT = [(300 + 450 * i, (lambda n=n: open_one(n))) for i, n in enumerate(names)]\n"
                  "wm.SCRIPT.append((300 + 450 * len(names), lambda: wm.wm.launch('browser', 'http://10.0.2.2:%d/')))\n"
                  "result = []\n"
                  "wm.SCRIPT.append((22000, lambda: result.append([w.title for w in wm.wm.windows])))\n"
                  "def use_apps():\n"
                  "    ok = {}\n"
                  "    for w in list(wm.wm.windows): wm.wm.close(w)\n"
                  "    b = wm.wm.launch('bloc').app\n"
                  "    b.insert('hola mundo hola'); b.replace_all('hola', 'adios')\n"
                  "    ok['bloc'] = b.lines == ['adios mundo adios']\n"
                  "    e = wm.wm.launch('escritor').app\n"
                  "    e.pars[0]['text'] = 'Informe'; e.p = 0; e.set('align', 'center'); e.path = '/disk/Documentos/t.html'; e.save()\n"
                  "    e.open('/disk/Documentos/t.html'); ok['escritor'] = (e.pars[0]['text'], e.pars[0]['align']) == ('Informe', 'center')\n"
                  "    s = wm.wm.launch('solitario').app\n"
                  "    ok['solitario'] = s.fits_pile((0, 2), 2) and not s.fits_pile((1, 2), 2) and len(s.stock) == 24\n"
                  "    c = wm.wm.launch('calendario').app\n"
                  "    c.add('Reunion'); ok['calendario'] = 'Reunion' in c.events[c.key()]\n"
                  "    r = wm.wm.launch('recortes').app\n"
                  "    r.start('screen'); r.pending = 0; r.tick(1)\n"
                  "    import os; ok['recortes'] = r.path is not None and os.stat(r.path)[6] > 3000000\n"
                  "    result.append(ok)\n"
                  "wm.SCRIPT.append((23000, use_apps))\n"
                  "wm.SCRIPT.append((26000, lambda: setattr(wm.wm, 'running', False)))\n" % port)
        # in pieces: a very long line can lose bytes on the way through the serial port
        piece = ""
        for line in script.splitlines(True):
            if len(piece) + len(line) > 600 and not line.startswith(" "):
                m.cmd("exec(%r)" % piece, 20)
                piece = ""
            piece += line
        if piece:
            m.cmd("exec(%r)" % piece, 20)
        m.send(b"desktop\r")
        time.sleep(20)
        m.monitor("screendump " + host_path(shot), pause=1.5)
        ok = shot.is_file() and shot.stat().st_size > 2_000_000          # 1024x768 graphics, not text mode
        if ok:
            T.ppm_to_png(shot, ROOT / "build" / "desktop.png")
        check("desktop draws in 1024x768 graphics (build/desktop.png)", ok, shot.stat().st_size if shot.is_file() else None)
        m.until(T.PROMPT, 60)
        time.sleep(2)                     # the console is busy redrawing; typed bytes could be lost
        m.cmd("", 10)
        out = m.cmd("result[0] if result else None", 20)
        check("every app opens a window", out.count("'") >= 2 * (len(["terminal", "files"])) and "Sitio de prueba" in out
              and "Navegador" in out, out)
        out = m.cmd("[l for l in log.lines() if 'desktop:' in l]")
        check("no app raised an error", out.strip().endswith("[]"), out)
        out = m.cmd("result[1] if len(result) > 1 else None")
        for app in ("bloc", "escritor", "solitario", "calendario", "recortes"):
            check("%s works (not only opens)" % app, "'%s': True" % app in out, out)
        out = m.cmd("len(opened), [n for n, ok in opened if not ok]")
        check("... all of them (built in and the .py apps in /apps)", "[])" in out and int(out.split("(")[-1].split(",")[0]) >= 25, out)
        out = m.cmd("from desktop import places; places.ensure(); d = places.desktop(); "
                    "f = places.new_folder(d, 'Prueba'); places.rename(d, f, 'Proyecto'); "
                    "n = places.new_file(d, 'nota.txt', 'hola'); places.to_trash(d + '/' + n); "
                    "import os; sorted(os.listdir(d)), os.listdir(places.trash())")
        check("folders: create, rename, send to the trash", "'Proyecto'" in out and "'nota.txt'" in out
              and out.count("nota.txt") == 1, out)
        out = m.cmd("from desktop import apps; apps.install('/apps/pelota.py'.replace('pelota', 'notas')) and 0; "
                    "sorted(apps.app_files())")
        check(".py apps: found in /apps and installed into /disk/apps", "'notas'" in out and "'hoja'" in out, out)
        out = m.cmd("from kernel import video; video.current is None")
        check("leaving the desktop returns to the text console", "True" in out, out)
    except TimeoutError as e:
        check("no timeout", False, str(e)[-1500:])
    finally:
        m.close()
        srv.shutdown()
    print("\n%d/%d desktop checks passed" % (sum(T.CHECKS), len(T.CHECKS)))
    sys.exit(0 if all(T.CHECKS) else 1)


if __name__ == "__main__":
    main()
