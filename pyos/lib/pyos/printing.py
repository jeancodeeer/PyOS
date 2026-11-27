# The SnakeyOS print spooler: a queue of print jobs and the printers they go to.
#
# Printers:
#   "PDF"   saves each job as a PDF file in /disk/Documentos (always there)
#   "LPT1"  a printer on the parallel port (kernel/lpt.py); it receives the
#           job as PDF, which most printers of the last 20 years understand
#
# A job is either text (print_text: real text in the PDF, small files) or
# pages already drawn as pictures (submit: what Windows programs in PyWin
# send through StartDoc / EndPage / EndDoc).
#
# The jobs are done one by one in a background thread; jobs() lists them.
import _thread
import time

OUT_DIR = "/disk/Documentos"
PAGE_W, PAGE_H = 595, 842                   # A4 in PDF points (1/72 inch)
MARGIN = 50
FONT_SIZE = 10
LINE_H = 12

_queue = []                                  # jobs waiting
_done = []                                   # the last jobs finished (or failed)
_lock = _thread.allocate_lock()
_worker = {"running": False}
_next_id = [1]


class Job:
    def __init__(self, printer, title, text=None, pages=None, dpi=150):
        self.id = _next_id[0]
        _next_id[0] += 1
        self.printer, self.title = printer, title or "Documento"
        self.text, self.pages, self.dpi = text, pages, dpi
        self.state = "en cola"
        self.result = ""                         # the PDF path, or the error

    def __repr__(self):
        return "<trabajo %d %r en %s: %s %s>" % (self.id, self.title, self.printer, self.state, self.result)


def printer_names():
    """The printers: PDF first (the default), then every parallel port found."""
    names = ["PDF"]
    try:
        from kernel import lpt
        names += [port.name for port in lpt.ports]
    except ImportError:
        pass
    return names


def print_text(text, title="Documento", printer="PDF"):
    """Print plain text. Returns the job."""
    return _add(Job(printer, title, text=text))


def submit(printer, title, pages, dpi=150):
    """Print pages drawn as pygame Surfaces (white paper, dpi dots per inch)."""
    return _add(Job(printer, title, pages=list(pages), dpi=dpi))


def jobs():
    with _lock:
        return list(_queue) + list(_done)


def _add(job):
    if job.printer not in printer_names():
        raise ValueError("no hay impresora %r" % job.printer)
    with _lock:
        _queue.append(job)
        start = not _worker["running"]
        _worker["running"] = True
    if start:
        _thread.start_new_thread(_work, ())
    return job


def _work():
    while True:
        with _lock:
            if not _queue:
                _worker["running"] = False
                return
            job = _queue.pop(0)
        job.state = "imprimiendo"
        try:
            _print(job)
            job.state = "hecho"
        except Exception as e:
            job.state = "error"
            job.result = str(e)
        job.pages = job.text = None              # free the memory
        with _lock:
            _done.append(job)
            del _done[:-20]
        _notify(job)


def _notify(job):
    try:
        from desktop import wm
        if wm.wm is not None:
            msg = ("Impreso: %s" % job.title) if job.state == "hecho" else ("No se pudo imprimir: %s" % job.result)
            wm.wm.later(lambda: wm.wm.toast(msg))
    except Exception:
        pass


def _print(job):
    data = text_pdf(job.text, job.title) if job.text is not None else image_pdf(job.pages, job.dpi, job.title)
    if job.printer == "PDF":
        job.result = _save(data, job.title)
        return
    from kernel import lpt
    port = lpt.find(job.printer)
    if port is None:
        raise OSError("la impresora %s ya no está" % job.printer)
    port.write(data)
    job.result = "%d bytes" % len(data)


def _save(data, title):
    import os
    try:
        os.mkdir(OUT_DIR)
    except OSError:
        pass
    safe = "".join(c if c.isalpha() or c.isdigit() or c in " -_." else "_" for c in title).strip() or "Documento"
    path = "%s/%s.pdf" % (OUT_DIR, safe[:60])
    n = 2
    while _exists(path):
        path = "%s/%s (%d).pdf" % (OUT_DIR, safe[:60], n)
        n += 1
    with open(path, "wb") as f:
        f.write(data)
    return path


def _exists(path):
    import os
    try:
        os.stat(path)
        return True
    except OSError:
        return False


# ---- writing a PDF file ----
#
# A PDF is a list of numbered objects, then a table with where each one
# starts (the "xref"), so a reader can jump to any of them.

class PDF:
    def __init__(self):
        self.objects = []                        # bytes of each object, numbered from 1

    def add(self, body):
        self.objects.append(body if isinstance(body, bytes) else body.encode())
        return len(self.objects)

    def reserve(self):
        self.objects.append(b"")
        return len(self.objects)

    def set(self, n, body):
        self.objects[n - 1] = body if isinstance(body, bytes) else body.encode()

    def stream(self, header, data):
        return self.add(b"<< " + header.encode() + b" /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")

    def output(self, root, info):
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        where = []
        for n, body in enumerate(self.objects, 1):
            where.append(len(out))
            out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(self.objects) + 1)
        for at in where:
            out += b"%010d 00000 n \n" % at
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(self.objects) + 1, root, info, xref)
        return bytes(out)


def _pdf_string(text):
    """Text as a PDF string in WinAnsi (Latin-1 is close enough for Spanish)."""
    out = bytearray(b"(")
    for ch in text:
        c = ord(ch)
        if ch in "()\\":
            out += b"\\" + ch.encode()
        elif c < 32:
            out += b" "
        elif c < 256:
            out.append(c)
        else:
            out += b"?"
    out += b")"
    return bytes(out)


def _info(pdf, title):
    t = time.localtime()
    when = "D:%04d%02d%02d%02d%02d%02d" % t[:6]
    return pdf.add(b"<< /Title " + _pdf_string(title) + b" /Producer (SnakeyOS) /CreationDate (" + when.encode() + b") >>")


def _wrap(text, width):
    """Cut long lines (tabs become 4 spaces) so they fit in width characters."""
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.replace("\t", "    ")
        while len(line) > width:
            cut = line.rfind(" ", 0, width)
            cut = cut if cut > width // 2 else width
            lines.append(line[:cut])
            line = line[cut:].lstrip(" ")
        lines.append(line)
    return lines


def text_pdf(text, title="Documento"):
    """A PDF with the text in Courier, as many A4 pages as it needs."""
    pdf = PDF()
    pages_obj = pdf.reserve()
    font = pdf.add("<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")
    per_page = (PAGE_H - 2 * MARGIN) // LINE_H
    chars = int((PAGE_W - 2 * MARGIN) / (FONT_SIZE * 0.6))      # Courier is 0.6 em wide
    lines = _wrap(text or "", chars)
    kids = []
    for first in range(0, max(1, len(lines)), per_page):
        body = bytearray(b"BT /F1 %d Tf %d TL %d %d Td\n" % (FONT_SIZE, LINE_H, MARGIN, PAGE_H - MARGIN - FONT_SIZE))
        for line in lines[first:first + per_page]:
            body += _pdf_string(line) + b" Tj T*\n"
        body += b"ET"
        content = pdf.stream("", bytes(body))
        kids.append(pdf.add("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                            "/Resources << /Font << /F1 %d 0 R >> >> >>" % (pages_obj, PAGE_W, PAGE_H, content, font)))
    pdf.set(pages_obj, "<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kids), len(kids)))
    root = pdf.add("<< /Type /Catalog /Pages %d 0 R >>" % pages_obj)
    return pdf.output(root, _info(pdf, title))


def image_pdf(pages, dpi=150, title="Documento"):
    """A PDF with one picture per page (each a pygame Surface)."""
    pdf = PDF()
    pages_obj = pdf.reserve()
    kids = []
    for surface in pages:
        w, h = surface.get_size()
        data, filter_name = _compress(_rgb(surface))
        image = pdf.stream("/Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB "
                           "/BitsPerComponent 8 /Filter /%s" % (w, h, filter_name), data)
        pw, ph = w * 72 // dpi, h * 72 // dpi                    # the paper size in points
        content = pdf.stream("", b"q %d 0 0 %d 0 0 cm /Im0 Do Q" % (pw, ph))
        kids.append(pdf.add("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                            "/Resources << /XObject << /Im0 %d 0 R >> >> >>" % (pages_obj, pw, ph, content, image)))
    pdf.set(pages_obj, "<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kids), len(kids)))
    root = pdf.add("<< /Type /Catalog /Pages %d 0 R >>" % pages_obj)
    return pdf.output(root, _info(pdf, title))


# ---- pixels: the Surface keeps B, G, R, A; a PDF wants R, G, B ----

try:
    import micropython

    @micropython.viper
    def _bgra_to_rgb(src: ptr8, dst: ptr8, n: int):
        i = 0
        j = 0
        while n > 0:
            dst[j] = src[i + 2]
            dst[j + 1] = src[i + 1]
            dst[j + 2] = src[i]
            i += 4
            j += 3
            n -= 1

    @micropython.viper
    def _run_length(src: ptr8, n: int, dst: ptr8) -> int:
        # PDF RunLengthDecode: L < 128 means "L + 1 bytes follow as they are",
        # L > 128 means "repeat the next byte 257 - L times", 128 ends the data
        i = 0
        o = 0
        while i < n:
            j = i + 1
            while j < n and j - i < 128 and src[j] == src[i]:
                j += 1
            if j - i >= 2:
                dst[o] = 257 - (j - i)
                dst[o + 1] = src[i]
                o += 2
                i = j
            else:
                start = i
                i += 1
                while i < n and i - start < 128:
                    if i + 1 < n and src[i] == src[i + 1]:
                        break
                    i += 1
                dst[o] = i - start - 1
                o += 1
                k = start
                while k < i:
                    dst[o] = src[k]
                    o += 1
                    k += 1
        dst[o] = 128
        return o + 1
except (ImportError, AttributeError, SyntaxError):
    def _bgra_to_rgb(src, dst, n):
        for k in range(n):
            dst[3 * k], dst[3 * k + 1], dst[3 * k + 2] = src[4 * k + 2], src[4 * k + 1], src[4 * k]

    def _run_length(src, n, dst):
        o = 0
        i = 0
        while i < n:
            j = i + 1
            while j < n and j - i < 128 and src[j] == src[i]:
                j += 1
            if j - i >= 2:
                dst[o], dst[o + 1] = 257 - (j - i), src[i]
                o, i = o + 2, j
            else:
                start = i
                i += 1
                while i < n and i - start < 128 and not (i + 1 < n and src[i] == src[i + 1]):
                    i += 1
                dst[o] = i - start - 1
                dst[o + 1:o + 1 + i - start] = src[start:i]
                o += 1 + i - start
        dst[o] = 128
        return o + 1


def _rgb(surface):
    w, h = surface.get_size()
    out = bytearray(w * h * 3)
    _bgra_to_rgb(surface._buf, out, w * h)
    return out


def _compress(data):
    """Squeeze the pixels: zlib (Flate) when this MicroPython can, else run-length."""
    try:
        import deflate
        import io
        buf = io.BytesIO()
        with deflate.DeflateIO(buf, deflate.ZLIB) as z:
            z.write(data)
        return buf.getvalue(), "FlateDecode"
    except Exception:
        pass
    try:
        import zlib
        return zlib.compress(bytes(data)), "FlateDecode"
    except Exception:
        pass
    out = bytearray(len(data) + len(data) // 128 + 2)
    n = _run_length(data, len(data), out)
    return bytes(out[:n]), "RunLengthDecode"


# ---- for desktop apps: "Archivo > Imprimir" ----

def print_from_app(text, title):
    """Ask which printer (when there is more than one) and print text there."""
    from desktop import ui, wm
    names = printer_names()

    def go(name):
        if name is None or name is False:
            return
        try:
            print_text(text, title, name)
            ui.toast("imprimiendo en %s..." % name)
        except Exception as e:
            ui.toast("no se pudo imprimir: %s" % e)
    if len(names) == 1:
        go(names[0])
        return
    from desktop.dialog import Dialog
    buttons = tuple((n, n) for n in names) + (("Cancelar", None),)
    wm.wm.dialog = Dialog(wm.wm, "Imprimir", "¿En qué impresora?", None, buttons, go)
