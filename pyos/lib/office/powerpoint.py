# PowerPoint presentations (.pptx, Office Open XML), for the Presentaciones app.
#
# A slide is {"title": "...", "body": "line 1\nline 2"} (each body line a
# bullet point). The theme is four colours: background, title, text, accent.
#
#   data = powerpoint.to_pptx(slides, theme)
#   slides, theme = powerpoint.from_pptx(data)
#
# A .pptx needs a few parts besides the slides: a theme, one slide master
# and one layout. They are as small as PowerPoint accepts.
from office import zipper
from office.xml import escape, events

EMU = 12700                         # 1 point = 12700 EMU (the unit of Office drawings)
SLIDE_W, SLIDE_H = 12192000, 6858000   # 16:9, 13.33 x 7.5 inches
NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _hex(color):
    return "%02X%02X%02X" % tuple(color[:3])


def _content_types(n):
    slides = "".join('<Override PartName="/ppt/slides/slide%d.xml" ContentType="application/vnd.openxmlformats-'
                     'officedocument.presentationml.slide+xml"/>' % (i + 1) for i in range(n))
    return (HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
            '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
            '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
            + slides + '</Types>')


def _rels(items):
    """items: [(id, type, target)]"""
    return (HEAD + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join('<Relationship Id="%s" Type="%s%s" Target="%s"/>' % (i, REL, t, target) for i, t, target in items)
            + '</Relationships>')


def _theme(colors):
    bg, title, text, accent = [_hex(c) for c in colors]
    scheme = ('<a:dk1><a:srgbClr val="%s"/></a:dk1><a:lt1><a:srgbClr val="%s"/></a:lt1>'
              '<a:dk2><a:srgbClr val="%s"/></a:dk2><a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>' % (text, bg, title)
              + "".join('<a:accent%d><a:srgbClr val="%s"/></a:accent%d>' % (k, accent if k == 1 else v, k)
                        for k, v in enumerate(("", "4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47"))
                        if k) +
              '<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink>')
    fill = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    line = '<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
    fonts = ('<a:latin typeface="%s"/><a:ea typeface=""/><a:cs typeface=""/>')
    return (HEAD + '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="SnakeyOS">'
            '<a:themeElements><a:clrScheme name="SnakeyOS">' + scheme + '</a:clrScheme>'
            '<a:fontScheme name="SnakeyOS"><a:majorFont>' + fonts % "Calibri Light" + '</a:majorFont>'
            '<a:minorFont>' + fonts % "Calibri" + '</a:minorFont></a:fontScheme>'
            '<a:fmtScheme name="SnakeyOS"><a:fillStyleLst>' + fill * 3 + '</a:fillStyleLst>'
            '<a:lnStyleLst>' + line * 3 + '</a:lnStyleLst>'
            '<a:effectStyleLst>' + '<a:effectStyle><a:effectLst/></a:effectStyle>' * 3 + '</a:effectStyleLst>'
            '<a:bgFillStyleLst>' + fill * 3 + '</a:bgFillStyleLst></a:fmtScheme></a:themeElements>'
            '<a:objectDefaults/><a:extraClrSchemeLst/></a:theme>')


EMPTY_TREE = ('<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
              '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/>'
              '<a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>')
CLR_MAP = ('<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
           'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>')

MASTER = (HEAD + '<p:sldMaster ' + NS + '><p:cSld><p:spTree>' + EMPTY_TREE + '</p:spTree></p:cSld>' + CLR_MAP +
          '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst></p:sldMaster>')
LAYOUT = (HEAD + '<p:sldLayout ' + NS + ' type="obj" preserve="1"><p:cSld name="Title and Content"><p:spTree>'
          + EMPTY_TREE + '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')


def _shape(n, name, ph, x, y, w, h, paragraphs, size, color, bold, bullets):
    paras = []
    for text in paragraphs:
        ppr = ('<a:pPr marL="342900" indent="-342900"><a:buFont typeface="Arial"/><a:buChar char="&#8226;"/></a:pPr>'
               if bullets and text else '<a:pPr><a:buNone/></a:pPr>' if bullets else "")
        rpr = '<a:rPr lang="es-ES" sz="%d"%s dirty="0"><a:solidFill><a:srgbClr val="%s"/></a:solidFill></a:rPr>' % (
            size * 100, ' b="1"' if bold else "", _hex(color))
        run = '<a:r>%s<a:t>%s</a:t></a:r>' % (rpr, escape(text)) if text else ""
        paras.append('<a:p>%s%s<a:endParaRPr lang="es-ES" sz="%d"/></a:p>' % (ppr, run, size * 100))
    return ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            '<p:nvPr><p:ph %s/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/>'
            '</a:xfrm></p:spPr><p:txBody><a:bodyPr wrap="square"><a:normAutofit/></a:bodyPr><a:lstStyle/>%s</p:txBody></p:sp>'
            % (n, name, ph, x, y, w, h, "".join(paras)))


def _slide(slide, theme):
    bg, title_c, text_c, accent = theme
    margin = 838200
    title = _shape(2, "Title 1", 'type="title"', margin, 365125, SLIDE_W - 2 * margin, 1325563,
                   [slide.get("title", "")], 40, title_c, True, False)
    lines = slide.get("body", "").split("\n") if slide.get("body") else [""]
    body = _shape(3, "Content 2", 'idx="1"', margin, 1825625, SLIDE_W - 2 * margin, 4351338,
                  lines, 24, text_c, False, True)
    background = ('<p:bg><p:bgPr><a:solidFill><a:srgbClr val="%s"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
                  % _hex(bg))
    return (HEAD + '<p:sld ' + NS + '><p:cSld>' + background + '<p:spTree>' + EMPTY_TREE + title + body +
            '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


def to_pptx(slides, theme):
    """theme: (background, title colour, text colour, accent) as (r, g, b)."""
    n = len(slides)
    presentation = (HEAD + '<p:presentation ' + NS + ' saveSubsetFonts="1">'
                    '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
                    '<p:sldIdLst>' + "".join('<p:sldId id="%d" r:id="rId%d"/>' % (256 + i, i + 3) for i in range(n)) +
                    '</p:sldIdLst><p:sldSz cx="%d" cy="%d"/><p:notesSz cx="6858000" cy="9144000"/>'
                    '<p:defaultTextStyle/></p:presentation>' % (SLIDE_W, SLIDE_H))
    files = {
        "[Content_Types].xml": _content_types(n),
        "_rels/.rels": _rels([("rId1", "officeDocument", "ppt/presentation.xml")]),
        "ppt/presentation.xml": presentation,
        "ppt/_rels/presentation.xml.rels": _rels(
            [("rId1", "slideMaster", "slideMasters/slideMaster1.xml"), ("rId2", "theme", "theme/theme1.xml")] +
            [("rId%d" % (i + 3), "slide", "slides/slide%d.xml" % (i + 1)) for i in range(n)]),
        "ppt/slideMasters/slideMaster1.xml": MASTER,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": _rels(
            [("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"), ("rId2", "theme", "../theme/theme1.xml")]),
        "ppt/slideLayouts/slideLayout1.xml": LAYOUT,
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": _rels(
            [("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")]),
        "ppt/theme/theme1.xml": _theme(theme),
    }
    for i, slide in enumerate(slides):
        files["ppt/slides/slide%d.xml" % (i + 1)] = _slide(slide, theme)
        files["ppt/slides/_rels/slide%d.xml.rels" % (i + 1)] = _rels(
            [("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml")])
    return zipper.write(files)


def _slide_order(files):
    """The slide part names, in the order presentation.xml lists them."""
    ids = [attrs.get("r:id") for kind, name, attrs, _ in events(files.get("ppt/presentation.xml", b""))
           if kind == "start" and name == "p:sldId"]
    targets = {}
    for kind, name, attrs, _ in events(files.get("ppt/_rels/presentation.xml.rels", b"")):
        if kind == "start" and name == "Relationship":
            t = attrs.get("Target", "")
            targets[attrs.get("Id")] = t.lstrip("/") if t.startswith("/") else "ppt/" + t
    return [targets[i] for i in ids if i in targets]


def from_pptx(data):
    """(slides, background colour or None): each slide's title and the text of its other boxes."""
    files = zipper.read(data)
    slides, background = [], None
    for part in _slide_order(files):
        title, body = [], []
        is_title = False
        para, inside_t, in_bg = None, False, False
        for kind, name, attrs, text in events(files.get(part, b"")):
            if kind == "start":
                if name == "p:sp":
                    is_title, box = False, []
                elif name == "p:ph":
                    is_title = attrs.get("type") in ("title", "ctrTitle")
                elif name == "a:p":
                    para = ""
                elif name == "a:t":
                    inside_t = True
                elif name == "p:bg":
                    in_bg = True
                elif name == "a:srgbClr" and in_bg and background is None:
                    v = attrs.get("val", "FFFFFF")
                    background = (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
            elif kind == "end":
                if name == "a:t":
                    inside_t = False
                elif name == "p:bg":
                    in_bg = False
                elif name == "a:p" and para is not None:
                    (title if is_title else body).append(para)
                    para = None
            elif kind == "text" and inside_t and para is not None:
                para += text
        slides.append({"title": " ".join(t for t in title if t), "body": "\n".join(body).strip("\n")})
    return slides, background
