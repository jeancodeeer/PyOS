# Excel workbooks (.xlsx, Office Open XML) and CSV, for the Hoja app.
#
# The sheet is a dict {(column, row): text}, both counted from 0, where a
# text starting with "=" is a formula in the Hoja's own syntax (Python):
#   =A1*2   =sum(A1:A5)   =max(B1:B3)/2   =A1**2
# In the .xlsx it becomes Excel's syntax (SUM, MAX, ^), with the value it
# had when saved, so Excel and LibreOffice show it at once.
#
#   data = excel.to_xlsx(cells, value_of)      value_of(c, r) -> the computed value
#   cells = excel.from_xlsx(data)
from office import zipper
from office.xml import escape, events

FUNCS = ("sum", "max", "min", "abs", "round", "average")

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets>
<calcPr calcId="191029" fullCalcOnLoad="1"/>
</workbook>"""

WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def col_name(c):
    """0 -> A, 25 -> Z, 26 -> AA"""
    name = ""
    c += 1
    while c:
        c, rest = divmod(c - 1, 26)
        name = chr(65 + rest) + name
    return name


def split_ref(ref):
    """'B12' -> (1, 11)"""
    i = 0
    while i < len(ref) and ref[i].isalpha():
        i += 1
    c = 0
    for ch in ref[:i].upper():
        c = c * 26 + ord(ch) - 64
    return c - 1, int(ref[i:]) - 1


def _swap_words(formula, table):
    """Replace whole words (not inside cell names) using table {old: new}."""
    out, i, n = [], 0, len(formula)
    while i < n:
        if formula[i].isalpha():
            j = i
            while j < n and (formula[j].isalpha() or formula[j].isdigit() or formula[j] == "_"):
                j += 1
            word = formula[i:j]
            out.append(table.get(word, word))
            i = j
        elif formula[i] == '"':                          # text in quotes stays as it is
            j = formula.find('"', i + 1)
            j = n if j < 0 else j + 1
            out.append(formula[i:j])
            i = j
        else:
            out.append(formula[i])
            i += 1
    return "".join(out)


def to_excel_formula(expr):
    """Hoja's '=sum(A1:A3)**2' -> Excel's 'SUM(A1:A3)^2' (without the '=')."""
    expr = expr[1:] if expr.startswith("=") else expr
    expr = expr.replace("**", "^")
    return _swap_words(expr, {f: f.upper() for f in FUNCS})


def from_excel_formula(formula):
    """Excel's 'SUM(A1:A3)^2' -> Hoja's '=sum(A1:A3)**2'."""
    f = formula.replace("^", "**").replace("$", "")
    table = {}
    for name in FUNCS:
        table[name.upper()] = name
    return "=" + _swap_words(f, table)


def _number(text):
    try:
        return float(text) if any(ch in text for ch in ".eE") else int(text)
    except ValueError:
        return None


def to_xlsx(cells, value_of=None, sheet="Hoja1"):
    rows = {}
    for (c, r), raw in cells.items():
        if raw != "":
            rows.setdefault(r, []).append((c, raw))
    body = []
    for r in sorted(rows):
        out = []
        for c, raw in sorted(rows[r]):
            ref = "%s%d" % (col_name(c), r + 1)
            if raw.startswith("="):
                value = value_of(c, r) if value_of else None
                f = "<f>%s</f>" % escape(to_excel_formula(raw))
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    shown = "" if value is None else str(value)
                    out.append('<c r="%s" t="str">%s<v>%s</v></c>' % (ref, f, escape(shown)))
                else:
                    out.append('<c r="%s">%s<v>%s</v></c>' % (ref, f, repr(value)))
            elif _number(raw) is not None:
                out.append('<c r="%s"><v>%s</v></c>' % (ref, raw))
            else:
                out.append('<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, escape(raw)))
        body.append('<row r="%d">%s</row>' % (r + 1, "".join(out)))
    sheet_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                 '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                 '<sheetData>%s</sheetData></worksheet>' % "".join(body))
    return zipper.write({
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": ROOT_RELS,
        "xl/workbook.xml": WORKBOOK % escape(sheet),
        "xl/_rels/workbook.xml.rels": WORKBOOK_RELS,
        "xl/worksheets/sheet1.xml": sheet_xml,
        "xl/styles.xml": STYLES,
    })


def _first_sheet(files):
    """The path of the workbook's first sheet (from workbook.xml and its rels)."""
    rid = None
    for kind, name, attrs, _ in events(files.get("xl/workbook.xml", b"")):
        if kind == "start" and name == "sheet":
            rid = attrs.get("r:id")
            break
    for kind, name, attrs, _ in events(files.get("xl/_rels/workbook.xml.rels", b"")):
        if kind == "start" and name == "Relationship" and attrs.get("Id") == rid:
            target = attrs.get("Target", "")
            return target.lstrip("/") if target.startswith("/") else "xl/" + target
    return "xl/worksheets/sheet1.xml"


def from_xlsx(data):
    """{(c, r): text} of the first sheet: numbers, texts, and formulas as '=...'."""
    files = zipper.read(data)
    shared = []
    if "xl/sharedStrings.xml" in files:
        cur, inside = None, False
        for kind, name, attrs, text in events(files["xl/sharedStrings.xml"]):
            if kind == "start" and name == "si":
                cur = ""
            elif kind == "start" and name == "t":
                inside = True
            elif kind == "end" and name == "t":
                inside = False
            elif kind == "end" and name == "si":
                shared.append(cur)
            elif kind == "text" and inside and cur is not None:
                cur += text
    cells = {}
    ref = kind_attr = None
    value = formula = None
    inside = None
    for kind, name, attrs, text in events(files.get(_first_sheet(files), b"")):
        if kind == "start":
            if name == "c":
                ref, kind_attr = attrs.get("r"), attrs.get("t", "n")
                value = formula = None
            elif name in ("v", "f", "t"):
                inside = name
                if name == "f":
                    formula = ""
                elif name == "v":
                    value = ""
                elif name == "t":
                    value = (value or "")
        elif kind == "end":
            if name in ("v", "f", "t"):
                inside = None
            elif name == "c" and ref:
                pos = split_ref(ref)
                if formula:
                    cells[pos] = from_excel_formula(formula)
                elif value is not None:
                    if kind_attr == "s":
                        i = int(value)
                        cells[pos] = shared[i] if i < len(shared) else ""
                    elif kind_attr == "b":
                        cells[pos] = "TRUE" if value == "1" else "FALSE"
                    else:
                        cells[pos] = value
        elif kind == "text" and inside:
            if inside == "f":
                formula += text
            else:
                value = (value or "") + text
    return cells


def to_csv(cells, value_of=None, sep=","):
    if not cells:
        return ""
    cols = max(c for c, _ in cells) + 1
    rows = max(r for _, r in cells) + 1
    lines = []
    for r in range(rows):
        row = []
        for c in range(cols):
            raw = cells.get((c, r), "")
            v = value_of(c, r) if (raw.startswith("=") and value_of) else raw
            s = "" if v is None else (("%.10g" % v) if isinstance(v, float) else str(v))
            if sep in s or '"' in s or "\n" in s:
                s = '"' + s.replace('"', '""') + '"'
            row.append(s)
        lines.append(sep.join(row))
    return "\r\n".join(lines) + "\r\n"


def from_csv(text, sep=None):
    """CSV as written by Excel: quotes for fields with commas; ';' is guessed too."""
    if sep is None:
        first = text.split("\n", 1)[0]
        sep = ";" if first.count(";") > first.count(",") else ","
    cells, r = {}, 0
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line:
            r += 1
            continue
        c, field, quoted, i = 0, "", False, 0
        while i <= len(line):
            ch = line[i] if i < len(line) else None
            if quoted:
                if ch == '"' and i + 1 < len(line) and line[i + 1] == '"':
                    field += '"'
                    i += 1
                elif ch == '"':
                    quoted = False
                elif ch is not None:
                    field += ch
            elif ch == '"':
                quoted = True
            elif ch == sep or ch is None:
                if field:
                    cells[(c, r)] = field
                c, field = c + 1, ""
            else:
                field += ch
            i += 1
        r += 1
    return cells
