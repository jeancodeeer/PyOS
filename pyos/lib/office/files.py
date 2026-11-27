# Saving and opening documents for the office apps: the format comes from
# the file's extension, as in Office ("informe.docx", "cuentas.xlsx").
import os


def ext(path):
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def with_ext(path, extension):
    """path with its extension changed (or added)."""
    folder, _, name = path.rpartition("/")
    base = name.rsplit(".", 1)[0] if "." in name else name
    return (folder + "/" if folder else "") + base + "." + extension


def write(path, data):
    folder = path.rsplit("/", 1)[0]
    if folder:
        try:
            os.mkdir(folder)
        except OSError:
            pass
    with open(path, "wb") as f:
        f.write(data.encode() if isinstance(data, str) else data)


def read(path):
    with open(path, "rb") as f:
        return f.read()
