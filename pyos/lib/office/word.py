# Word documents (.docx, Office Open XML) and PDF, for the Escritor app.
#
# A paragraph here is a dict:
#   {"text": "Hola", "style": "titulo" | "subtitulo" | "normal",
#    "bold": False, "align": "left" | "center" | "right", "color": (r, g, b)}
#
#   data = word.to_docx(paragraphs, title="Carta")      bytes of a .docx file
#   paragraphs = word.from_docx(data)
#   data = word.to_pdf(paragraphs, title="Carta")       bytes of a PDF
#
# In the .docx, "titulo" is Word's "Title" style and "subtitulo" its
# "Heading 1", so the document keeps its outline in Word.
from office import zipper
from office.xml import escape, events

STYLE_IDS = {"titulo": "Title", "subtitulo": "Heading1", "normal": "Normal"}
STYLE_OF_ID = {"Title": "titulo", "Heading1": "subtitulo", "Heading2": "subtitulo", "Subtitle": "subtitulo",
               "Normal": "normal"}
SIZES = {"titulo": 32, "subtitulo": 24, "normal": 12}       # points
JC = {"left": "left", "center": "center", "right": "right"}

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles %s>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="es-ES"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="259" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="64"/><w:szCs w:val="64"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="48"/><w:szCs w:val="48"/></w:rPr></w:style>
</w:styles>""" % W


def _core(title):
    import time
    t = time.localtime()
    when = "%04d-%02d-%02dT%02d:%02d:%02dZ" % t[:6]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<dc:title>%s</dc:title><dc:creator>SnakeyOS</dc:creator>'
            '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
            '<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>'
            '</cp:coreProperties>' % (escape(title), when, when))


def _app(name):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            '<Application>%s</Application></Properties>' % escape(name))


def _hex(color):
    return "%02X%02X%02X" % tuple(color[:3])


def to_docx(paragraphs, title="Documento"):
    body = []
    for par in paragraphs:
        style = par.get("style", "normal")
        ppr = '<w:pStyle w:val="%s"/>' % STYLE_IDS.get(style, "Normal")
        if par.get("align", "left") != "left":
            ppr += '<w:jc w:val="%s"/>' % JC.get(par["align"], "left")
        rpr = ""
        if par.get("bold"):
            rpr += "<w:b/><w:bCs/>"
        color = par.get("color")
        if color and tuple(color[:3]) != (0, 0, 0):
            rpr += '<w:color w:val="%s"/>' % _hex(color)
        runs = ""
        if par.get("text"):
            runs = '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (
                "<w:rPr>%s</w:rPr>" % rpr if rpr else "", escape(par["text"]))
        body.append("<w:p><w:pPr>%s</w:pPr>%s</w:p>" % (ppr, runs))
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document %s %s><w:body>%s'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1417" w:right="1701" w:bottom="1417" w:left="1701" w:header="708" w:footer="708" w:gutter="0"/>'
                '</w:sectPr></w:body></w:document>' % (W, R, "".join(body)))
    return zipper.write({
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": ROOT_RELS,
        "word/document.xml": document,
        "word/_rels/document.xml.rels": DOC_RELS,
        "word/styles.xml": STYLES,
        "docProps/core.xml": _core(title),
        "docProps/app.xml": _app("SnakeyOS Escritor"),
    })


def from_docx(data):
    """The paragraphs of a .docx (text, style, bold, alignment and colour of its first run)."""
    files = zipper.read(data)
    doc = files.get("word/document.xml")
    if doc is None:
        raise ValueError("this .docx has no word/document.xml")
    out = []
    par = None
    in_text = False
    in_rpr = False
    first_run = True
    for kind, name, attrs, text in events(doc):
        if kind == "start":
            if name == "w:p":
                par = {"text": "", "style": "normal", "bold": False, "align": "left", "color": (0, 0, 0)}
                first_run = True
            elif par is None:
                continue
            elif name == "w:pStyle":
                par["style"] = STYLE_OF_ID.get(attrs.get("w:val", ""), "normal")
            elif name == "w:jc":
                v = attrs.get("w:val", "left")
                par["align"] = {"both": "left", "start": "left", "end": "right"}.get(v, v)
                if par["align"] not in JC:
                    par["align"] = "left"
            elif name == "w:rPr":
                in_rpr = True
            elif name == "w:b" and in_rpr and first_run:
                par["bold"] = attrs.get("w:val", "1") not in ("0", "false")
            elif name == "w:color" and in_rpr and first_run:
                v = attrs.get("w:val", "000000")
                if len(v) == 6 and v != "auto":
                    par["color"] = (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
            elif name == "w:t":
                in_text = True
            elif name == "w:tab":
                par["text"] += "\t"
            elif name in ("w:br", "w:cr"):
                par["text"] += " "
        elif kind == "end":
            if name == "w:t":
                in_text = False
            elif name == "w:rPr":
                in_rpr = False
            elif name == "w:r":
                first_run = False
            elif name == "w:p" and par is not None:
                out.append(par)
                par = None
        elif kind == "text" and in_text and par is not None:
            par["text"] += text
    return out


# ---- PDF: real text (Helvetica), with the styles, bold, colours and alignment ----

# widths of the characters 32..126 in Helvetica and Helvetica-Bold, in 1/1000 of the size
REGULAR = (278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556,
           556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278,
           500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469,
           556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500,
           278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584)
BOLD = (278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556,
        556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722,
        611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556,
        611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778,
        556, 556, 500, 389, 280, 389, 584)
PAGE_W, PAGE_H, MARGIN = 595, 842, 72


def text_width(text, size, bold=False):
    table = BOLD if bold else REGULAR
    return sum(table[ord(c) - 32] if 32 <= ord(c) < 127 else 556 for c in text) * size / 1000.0


def wrap(text, size, bold, width):
    """Lines of text that fit in `width` points."""
    lines, line = [], ""
    for word in text.replace("\t", "    ").split(" "):
        test = word if not line else line + " " + word
        if text_width(test, size, bold) <= width or not line:
            line = test
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def to_pdf(paragraphs, title="Documento"):
    from pyos.printing import PDF, _pdf_string, _info
    pdf = PDF()
    pages_obj = pdf.reserve()
    regular = pdf.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    bold = pdf.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pages, page = [], bytearray()
    y = PAGE_H - MARGIN
    for par in paragraphs:
        style = par.get("style", "normal")
        size = SIZES.get(style, 12)
        is_bold = bool(par.get("bold")) or style != "normal"
        leading = size * 1.25
        r, g, b = [c / 255.0 for c in (par.get("color") or (0, 0, 0))[:3]]
        if style != "normal":
            y -= size * 0.5                                      # space before headings
        for line in wrap(par.get("text", ""), size, is_bold, PAGE_W - 2 * MARGIN):
            if y - leading < MARGIN:
                pages.append(bytes(page))
                page, y = bytearray(), PAGE_H - MARGIN
            y -= leading
            w = text_width(line, size, is_bold)
            align = par.get("align", "left")
            x = MARGIN + ((PAGE_W - 2 * MARGIN - w) / 2 if align == "center" else
                          (PAGE_W - 2 * MARGIN - w) if align == "right" else 0)
            page += b"BT /F%d %d Tf %.3f %.3f %.3f rg %.2f %.2f Td " % (2 if is_bold else 1, size, r, g, b, x, y)
            page += _pdf_string(line) + b" Tj ET\n"
        y -= size * 0.6                                          # space after a paragraph
    pages.append(bytes(page))
    kids = []
    for content in pages:
        stream = pdf.stream("", content)
        kids.append(pdf.add("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                            "/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>"
                            % (pages_obj, PAGE_W, PAGE_H, stream, regular, bold)))
    pdf.set(pages_obj, "<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kids), len(kids)))
    root = pdf.add("<< /Type /Catalog /Pages %d 0 R >>" % pages_obj)
    return pdf.output(root, _info(pdf, title))


def to_text(paragraphs):
    return "\r\n".join(p.get("text", "") for p in paragraphs) + "\r\n"
