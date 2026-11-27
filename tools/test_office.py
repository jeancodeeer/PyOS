"""Office formats: the documents SnakeyOS writes open in real office software.

    python tools/test_office.py

Runs pyos/lib/office on this PC (CPython) and checks the files with the
reference libraries (pip install python-docx openpyxl python-pptx) and,
if it is installed, LibreOffice (converts each one to PDF). Also reads
files those libraries wrote (compressed, as Office writes them).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pyos" / "lib"))
sys.path.insert(0, str(ROOT / "tools"))
import test as T  # noqa: E402
from office import word, excel, powerpoint  # noqa: E402

check = T.check
PARS = [{"text": "Informe", "style": "titulo", "bold": True, "align": "center", "color": (200, 40, 40)},
        {"text": "Sección", "style": "subtitulo", "bold": True, "align": "left", "color": (40, 120, 220)},
        {"text": "Texto con ñ, á y <&>.", "style": "normal", "bold": False, "align": "right", "color": (0, 0, 0)}]
CELLS = {(0, 0): "Producto", (1, 0): "Precio", (0, 1): "Pan", (1, 1): "1.5", (0, 2): "Leche", (1, 2): "2",
         (1, 3): "=sum(B2:B3)", (1, 4): "=B4**2"}
SLIDES = [{"title": "Presentación", "body": "Uno\nDos"}, {"title": "Fin", "body": "Gracias"}]
THEME = ((24, 30, 48), (255, 255, 255), (210, 216, 232), (255, 200, 80))


def main():
    tmp = Path(tempfile.mkdtemp())
    docx_data = word.to_docx(PARS, "Informe")
    xlsx_data = excel.to_xlsx(CELLS, lambda c, r: {(1, 3): 3.5, (1, 4): 12.25}.get((c, r)))
    pptx_data = powerpoint.to_pptx(SLIDES, THEME)
    (tmp / "a.docx").write_bytes(docx_data)
    (tmp / "a.xlsx").write_bytes(xlsx_data)
    (tmp / "a.pptx").write_bytes(pptx_data)
    check("docx: read back the same", word.from_docx(docx_data) == PARS)
    check("xlsx: read back the same", excel.from_xlsx(xlsx_data) == CELLS)
    check("pptx: read back the same", powerpoint.from_pptx(pptx_data)[0] == SLIDES)
    check("pdf: a PDF", word.to_pdf(PARS).startswith(b"%PDF-1.4"))
    try:
        import docx
        import openpyxl
        import pptx
    except ImportError:
        print("(python-docx / openpyxl / python-pptx not installed: skipping their checks)")
    else:
        d = docx.Document(str(tmp / "a.docx"))
        check("python-docx: styles and text", [(p.style.name, p.text) for p in d.paragraphs] ==
              [("Title", "Informe"), ("Heading 1", "Sección"), ("Normal", "Texto con ñ, á y <&>.")])
        ws = openpyxl.load_workbook(str(tmp / "a.xlsx")).active
        check("openpyxl: values and Excel formulas", ws["B2"].value == 1.5 and ws["B4"].value == "=SUM(B2:B3)"
              and ws["B5"].value == "=B4^2")
        p = pptx.Presentation(str(tmp / "a.pptx"))
        check("python-pptx: two slides with their text",
              [[s.text_frame.text for s in sl.shapes if s.has_text_frame] for sl in p.slides] ==
              [["Presentación", "Uno\nDos"], ["Fin", "Gracias"]])
        d2 = docx.Document()
        d2.add_heading("De Word", 0)
        d2.add_paragraph("normal")
        d2.save(str(tmp / "b.docx"))
        check("reads a .docx written by python-docx", [p["text"] for p in word.from_docx((tmp / "b.docx").read_bytes())]
              == ["De Word", "normal"])
        wb = openpyxl.Workbook()
        wb.active["A1"] = "hola"
        wb.active["B1"] = "=SUM(1,2)"
        wb.save(str(tmp / "b.xlsx"))
        check("reads an .xlsx written by openpyxl", excel.from_xlsx((tmp / "b.xlsx").read_bytes()) ==
              {(0, 0): "hola", (1, 0): "=sum(1,2)"})
    office = shutil.which("soffice") or shutil.which("libreoffice")
    if office:
        for name in ("a.docx", "a.xlsx", "a.pptx"):
            subprocess.run([office, "--headless", "--convert-to", "pdf", "--outdir", str(tmp / "lo"), str(tmp / name)],
                           capture_output=True, timeout=180)
            check("LibreOffice opens %s" % name, (tmp / "lo" / name.replace(name[-4:], "pdf")).is_file())
    print("%d/%d passed" % (sum(T.CHECKS), len(T.CHECKS)))
    return all(T.CHECKS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
