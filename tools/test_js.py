"""JavaScript in SnakeyOS: the engine written in Python (pyos/lib/js), and the browser running
pages' scripts against its DOM (browser/dom.js): DOM changes, fetch,
timers, localStorage, clicks; and, when the npm registry can be reached,
real React 18 and Vue 3 apps.

    python tools/test_js.py
"""
import http.server
import io
import shutil
import socketserver
import sys
import tarfile
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402
from run import make_disk  # noqa: E402

check = T.check

PAGE = """<!doctype html><html><head><title>Prueba JS</title><style>
.oculto { display: none } .activa { background: #36c; color: white }
</style></head><body>
<h1 id="t">Sin JavaScript</h1><p id="ext">externo: no</p><ul id="lista"></ul>
<p id="datos">fetch: esperando</p><p id="reloj">temporizador: esperando</p><p id="visitas"></p>
<button id="btn" type="button">Abrir</button><div id="menu" class="oculto">Menu desplegado</div>
<span class="tab activa" data-p="1">Uno</span> <span class="tab" data-p="2">Dos</span>
<div class="panel" id="p1">Panel UNO</div><div class="panel oculto" id="p2">Panel DOS</div>
<script>
document.getElementById("t").textContent = "Hecho por JavaScript";
document.title = "Prueba JS modificada";
for (const n of ["uno", "dos", "tres"]) { const li = document.createElement("li"); li.textContent = "item " + n; lista.appendChild(li); }
fetch("datos.json").then(r => r.json()).then(d => { datos.innerHTML = "fetch: <b>" + d.frutas.join(", ") + "</b>"; });
setTimeout(() => { document.querySelector("#reloj").textContent = "temporizador: OK"; }, 200);
const n = +(localStorage.getItem("visitas") || 0) + 1; localStorage.setItem("visitas", n);
visitas.textContent = "visitas: " + n;
btn.addEventListener("click", () => menu.classList.toggle("oculto"));
document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("oculto", p.id !== "p" + t.dataset.p));
}));
</script><script src="externo.js"></script></body></html>"""

REACT = """<!doctype html><html><head><title>React</title></head><body><div id="root">cargando</div>
<script src="react.js"></script><script src="react-dom.js"></script><script>
const e = React.createElement;
function App() {
  const [n, setN] = React.useState(0);
  return e("div", null, e("h1", null, "React " + React.version), e("p", null, "pulsado " + n),
           e("button", {id: "mas", type: "button", onClick: () => setN(n + 1)}, "Sumar"));
}
ReactDOM.createRoot(document.getElementById("root")).render(e(App));
</script></body></html>"""

VUE = """<!doctype html><html><head><title>Vue</title></head><body>
<div id="app"><h1>{{ t }}</h1><p>total {{ items.length }}</p><button id="add" type="button" @click="items.push('x')">Agregar</button>
<ul><li v-for="x in items">{{ x }}</li></ul></div>
<script src="vue.js"></script><script>
Vue.createApp({ data() { return { t: "Vue " + Vue.version, items: ["a", "b"] }; } }).mount("#app");
</script></body></html>"""

GUEST = '''
import pygame
pygame.init()
from browser import page
def load(url):
    p = page.Page(url)
    p.width = 800
    p._load(None, "GET")
    return p
def text(p):
    return " ".join(it.data for it in p.layout.items if it.kind == "text")
def by_id(p, i):
    for n in p.doc.iter():
        if n.attrs.get("id") == i:
            return n
def first_text(p, word):
    for it in p.layout.items:
        if it.kind == "text" and it.data == word:
            return it.node
'''


def npm(dest, package, version, inside, name):
    """A file from an npm package, or False when the registry cannot be reached."""
    url = "https://registry.npmjs.org/%s/-/%s-%s.tgz" % (package, package, version)
    try:
        data = urllib.request.urlopen(url, timeout=30).read()
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            (dest / name).write_bytes(t.extractfile("package/" + inside).read())
        return True
    except Exception:
        return False


def serve(folder):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(folder), **kw)

        def log_message(self, *a):
            pass
    httpd = socketserver.ThreadingTCPServer(("0.0.0.0", 0), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "js.html").write_text(PAGE)
        (d / "datos.json").write_text('{"frutas": ["manzana", "pera", "uva"]}')
        (d / "externo.js").write_text('document.getElementById("ext").textContent = "externo: OK";')
        have_react = npm(d, "react", "18.3.1", "umd/react.production.min.js", "react.js") and \
            npm(d, "react-dom", "18.3.1", "umd/react-dom.production.min.js", "react-dom.js")
        have_vue = npm(d, "vue", "3.5.13", "dist/vue.global.prod.js", "vue.js")
        (d / "react.html").write_text(REACT)
        (d / "vue.html").write_text(VUE)
        httpd = serve(d)
        base = "http://10.0.2.2:%d/" % httpd.server_address[1]
        m = T.Machine(make_disk(ROOT / "build" / "test-disk.img"))
        try:
            m.until(T.PROMPT, 90)
            m.cmd("import js; c = js.Context(lambda n, a: a)", 60)
            check("JS engine: classes, regexps, JSON", "'14|H0LA'" in m.cmd(
                "c.eval('class A { get d() { return 7 * 2 } }; [new A().d, \"hola\".replace(/o/g, \"0\").toUpperCase()].join(\"|\")')", 30))
            out = m.cmd("c.eval('throw new TypeError(\"mal\")')", 30)
            check("JS engine: a script's error becomes a Python exception", "JSError" in out and "TypeError: mal" in out, out[-200:])
            out = m.cmd("c.eval('while (true) {}', 'loop', 300)", 30)
            check("JS engine: a script that never ends is stopped", "ran too long" in out, out[-200:])
            m.cmd("exec(%r)" % GUEST, 60)
            m.cmd("p = load(%r)" % (base + "js.html"), 180)
            m.cmd("import time; time.sleep_ms(300); p.js.tick()", 60)      # the browser's clock, as the app runs it
            out = m.cmd("print(repr(text(p)), p.title)", 60)
            check("page: scripts change the text and the title", "Hecho por JavaScript" in out and "Prueba JS modificada" in out, out[-400:])
            check("page: elements made by a script", "item uno" in out and "item tres" in out, out[-400:])
            check("page: fetch() and JSON", "manzana, pera, uva" in out, out[-400:])
            check("page: setTimeout()", "temporizador: OK" in out, out[-400:])
            check("page: localStorage and an external script", "visitas: 1" in out and "externo: OK" in out, out[-400:])
            out = m.cmd("p.js.event(by_id(p, 'btn'), 'click'); print(repr(text(p)))", 60)
            check("page: a click runs the page's handler (the menu opens)", "Menu desplegado" in out, out[-300:])
            out = m.cmd("p.js.event(first_text(p, 'Dos'), 'click'); print(repr(text(p)))", 60)
            check("page: tabs switch", "Panel DOS" in out and "Panel UNO" not in out, out[-300:])
            if have_react:
                m.cmd("p.close(); p = load(%r)" % (base + "react.html"), 240)
                out = m.cmd("print(repr(text(p)))", 60)
                check("React 18 draws its app", "React 18.3.1" in out and "pulsado 0" in out, out[-300:])
                out = m.cmd("p.js.event(by_id(p, 'mas'), 'click'); p.js.tick(); print(repr(text(p)))", 60)
                check("React 18: a click updates the state", "pulsado 1" in out, out[-300:])
            else:
                print("SKIP  React (no npm registry)")
            if have_vue:
                m.cmd("p.close(); p = load(%r)" % (base + "vue.html"), 240)
                out = m.cmd("print(repr(text(p)))", 60)
                check("Vue 3 draws its template", "Vue 3.5.13" in out and "total 2" in out, out[-300:])
                out = m.cmd("p.js.event(by_id(p, 'add'), 'click'); p.js.tick(); print(repr(text(p)))", 60)
                check("Vue 3: a click updates the list", "total 3" in out, out[-300:])
            else:
                print("SKIP  Vue (no npm registry)")
        finally:
            m.close()
            httpd.shutdown()
    print("%d/%d passed" % (sum(T.CHECKS), len(T.CHECKS)))
    return all(T.CHECKS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
