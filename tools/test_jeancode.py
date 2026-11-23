"""JeanCode inside PyKernel, end to end.

A fake OpenAI-style API runs here; the machine boots with COM2 wired to the
network bridge (tools/jeancode_bridge.py); the test types on the emulated PS/2
keyboard into the JeanCode window and checks the streamed answer.

    python tools/test_jeancode.py          (screenshots: build/jeancode*.png)
"""
import http.server
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import mkfs  # noqa: E402
import run  # noqa: E402
import test as T  # noqa: E402

ANSWER = ["Hola", ", ñandú", " desde el puente"]


class FakeAPI(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        ok = self.headers.get("Authorization") == "Bearer test-key"
        data = json.dumps({"data": [{"id": "jean-marvel"}, {"id": "jean-grey"}]} if ok
                          else {"error": {"message": "Invalid API key"}}).encode()
        self.send_response(200 if ok else 401)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in ANSWER:
            self.wfile.write(("data: %s\n\n" % json.dumps({"choices": [{"delta": {"content": piece}}]})).encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")


class Machine(T.Machine):
    def __init__(self, disk, port):
        cmd = run.qemu_command(["-display", "none", "-serial", "mon:stdio"] + run.bridge_serial(port), disk=disk)
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.q = queue.Queue()
        self.log = bytearray()
        threading.Thread(target=self._pump, daemon=True).start()


def shot(m, name):
    ppm = ROOT / "build" / "jeancode.ppm"
    ppm.unlink(missing_ok=True)
    m.monitor("screendump " + run.host_path(ppm), pause=1.5)
    if ppm.is_file():
        T.ppm_to_png(ppm, ROOT / "build" / name)
    return ppm.is_file()


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ep = {"provider": "custom", "url": "http://127.0.0.1:%d/v1" % srv.server_address[1],
          "key": "test-key", "model": "jean-marvel"}
    mkfs.pack(ROOT / "pyfs", ROOT / "build" / "pyfs.img")
    disk = run.make_disk(ROOT / "build" / "jeancode-disk.img", fresh=True)
    port = run.free_port()
    m = Machine(disk, port)
    bridge = run.start_bridge(port, ROOT / "build" / "bridge.log")
    check = T.check
    try:
        m.until(T.PROMPT, 60)
        out = m.cmd("from jeancode import net, chat; t = net.transport(); t.ready()", 30)
        check("the bridge answers on COM2", "(True, '')" in out, out)
        m.cmd("ep = %r" % ep)
        out = m.cmd("st, txt = net.fetch(*chat.models_request(ep)); st, chat.parse_models(txt)", 60)
        check("model list through the bridge", "(200, ['jean-grey', 'jean-marvel'])" in out, out)
        out = m.cmd("net.fetch(*chat.models_request(dict(ep, key='x')))[0]", 60)
        check("HTTP errors come back as they are", "401" in out, out)
        m.cmd("from jeancode.store import Store; s = Store(); st = s.settings(); "
              "st['endpoint'].update(ep); s.save_settings(st)")
        m.send(b"jeancode\r")
        time.sleep(8)
        m.press("h", "o", "l", "a", "ret")
        time.sleep(6)
        check("the JeanCode window on screen (build/jeancode.png)", shot(m, "jeancode.png"))
        m.press("f4")
        time.sleep(3)
        check("history screen (build/jeancode-history.png)", shot(m, "jeancode-history.png"))
        m.press("esc", "ctrl-q")
        m.until(T.PROMPT, 30)
        out = m.cmd("[(c['messages'][0]['content'], c['messages'][1]['content']) for c in Store().chats()]")
        check("typed on the keyboard, answer streamed and saved on /disk",
              r"('hola', 'Hola, \xf1and\xfa desde el puente')" in out, out)
        out = m.cmd("from kernel import video; video.current is None")
        check("Ctrl+Q goes back to the text console", "True" in out, out)
    except TimeoutError as e:
        check("no timeout", False, str(e))
    finally:
        m.close()
        bridge.kill()
        srv.shutdown()
    print(f"\n{sum(T.CHECKS)}/{len(T.CHECKS)} checks passed")
    return 0 if all(T.CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
