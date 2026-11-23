# The user's folders, the trash, and opening a file with the right app.
import os

ROOT = "/disk"
NAMES = ("Escritorio", "Documentos", "Descargas", "Imagenes", "Musica")
TRASH_NAME = ".Papelera"


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def is_dir(path):
    try:
        return os.stat(path)[0] & 0x4000 != 0
    except OSError:
        return False


def home():
    """Where the user's folders live: the hard disk (in RAM if there is none)."""
    return ROOT


def path(name):
    return home() + "/" + name


def desktop():
    return path("Escritorio")


def trash():
    return path(TRASH_NAME)


def ensure():
    """Create the user's folders the first time, with a welcome note."""
    base = home()
    for d in (base,) + tuple(base + "/" + n for n in NAMES + (TRASH_NAME,)):
        try:
            os.mkdir(d)
        except OSError:
            pass
    welcome = desktop() + "/Bienvenida.txt"
    if not _exists(welcome) and not _exists(base + "/.bienvenida"):
        with open(welcome, "w") as f:
            f.write("Bienvenido a PyOS.\n\n"
                    "- Clic derecho en el escritorio: nueva carpeta, nuevo documento, fondo.\n"
                    "- Doble clic en un icono para abrirlo; arrastralo para moverlo.\n"
                    "- El boton PyOS (arriba a la izquierda) abre el lanzador.\n"
                    "- Las apps son archivos .py: instala mas desde la Tienda.\n")
        with open(base + "/.bienvenida", "w") as f:
            f.write("1")


def unique(folder, name):
    """name, or 'name 2', 'name 3'... so nothing is overwritten."""
    if not _exists(folder + "/" + name):
        return name
    stem, dot, ext = name.rpartition(".") if "." in name[1:] else (name, "", "")
    i = 2
    while True:
        candidate = "%s %d%s%s" % (stem, i, dot, ext)
        if not _exists(folder + "/" + candidate):
            return candidate
        i += 1


def join(folder, name):
    return ("/" if folder == "/" else folder.rstrip("/") + "/") + name


def new_folder(folder, name="Carpeta nueva"):
    name = unique(folder, name)
    os.mkdir(join(folder, name))
    return name


def new_file(folder, name="Documento nuevo.txt", text=""):
    name = unique(folder, name)
    with open(join(folder, name), "w") as f:
        f.write(text)
    return name


def rename(folder, old, new):
    new = new.strip().replace("/", "-")
    if new and new != old:
        os.rename(join(folder, old), join(folder, unique(folder, new)))


def to_trash(path_):
    """Move a file or folder to the trash (deleting from the trash removes it)."""
    t = trash()
    if path_.startswith(t + "/"):
        remove(path_)
        return
    name = path_.rstrip("/").rsplit("/", 1)[-1]
    try:
        os.rename(path_, join(t, unique(t, name)))
    except OSError:
        remove(path_)                      # another disk (e.g. RAM): just delete it


def remove(path_):
    if is_dir(path_):
        for n in os.listdir(path_):
            remove(join(path_, n))
        os.rmdir(path_)
    else:
        os.remove(path_)


def empty_trash():
    t = trash()
    for n in os.listdir(t):
        remove(join(t, n))


def copy(src, dst_folder):
    name = unique(dst_folder, src.rstrip("/").rsplit("/", 1)[-1])
    dst = join(dst_folder, name)
    if is_dir(src):
        os.mkdir(dst)
        for n in os.listdir(src):
            copy(join(src, n), dst)
    else:
        with open(src, "rb") as a, open(dst, "wb") as b:
            while True:
                chunk = a.read(8192)
                if not chunk:
                    break
                b.write(chunk)
    return name


IMAGES = (".png", ".bmp", ".gif", ".jpg", ".jpeg")


def kind(path_):
    """What a path is, for icons: folder, image, sound, web, app, python, text."""
    if is_dir(path_):
        return "folder"
    low = path_.lower()
    if low.endswith(IMAGES):
        return "image"
    if low.endswith(".wav"):
        return "sound"
    if low.endswith((".html", ".htm")):
        return "web"
    if low.endswith(".py"):
        from desktop import apps
        return "app" if apps.read_header(path_) else "python"
    if low.endswith(".csv"):
        return "sheet"
    if low.endswith(".exe"):
        return "exe"
    return "text"


def open_path(path_):
    """Open a file or folder with the app that suits it."""
    from desktop import wm, apps
    k = kind(path_)
    w = wm.wm
    if k == "folder":
        return w.launch("files", path_)
    if k == "image":
        return w.launch("images", path_)
    if k == "sound":
        return w.launch("music", path_)
    if k == "web":
        return w.launch("browser", "file://" + path_)
    if k == "app":
        name = apps.install(path_) if not path_.startswith(("/apps/", "/disk/apps/")) else path_.rsplit("/", 1)[-1][:-3]
        apps.scan()
        return w.launch(name)
    if k == "exe":                              # a Windows program: PyWin runs it
        from pywin import host
        return host.start(path_)
    if k == "sheet" and "hoja" in apps.app_files():
        return w.launch("hoja", path_)
    if k == "text" and "bloc" in apps.app_files():
        return w.launch("bloc", path_)          # plain text: the notepad; Python code: the editor
    return w.launch("editor", path_)
