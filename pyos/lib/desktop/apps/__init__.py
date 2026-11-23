# PyOS apps: the built-in ones (modules in this folder) and app files.
#
# An app file is one .py file that starts with a header:
#
#     # pyos-app
#     # name: Notas
#     # icon: notes                 (an icon name from icons.py; optional)
#     # mode: window                (or fullscreen; window is the default)
#
# A window app defines `class App(desktop.wm.App)`. A fullscreen app is any
# pygame program: it gets the whole screen until it quits (Ctrl+Q).
# System apps live in /apps, the ones you install in /disk/apps.
import os

#   name: (module, class, label shown to people)
BUILTIN = {
    "terminal": ("desktop.apps.terminal", "Terminal", "Terminal"),
    "files": ("desktop.apps.files", "Files", "Archivos"),
    "browser": ("desktop.apps.browser", "Browser", "Navegador"),
    "editor": ("desktop.apps.editor", "Editor", "Editor"),
    "music": ("desktop.apps.music", "Music", "Musica"),
    "images": ("desktop.apps.images", "Images", "Imagenes"),
    "paint": ("desktop.apps.paint", "Paint", "Dibujo"),
    "calc": ("desktop.apps.calc", "Calculator", "Calculadora"),
    "clock": ("desktop.apps.clock", "Clock", "Reloj"),
    "sysmon": ("desktop.apps.sysmon", "Monitor", "Monitor"),
    "settings": ("desktop.apps.settings", "Settings", "Ajustes"),
    "disks": ("desktop.apps.disks", "Disks", "Discos"),
    "store": ("desktop.apps.store", "Store", "Tienda"),
    "jeancode": ("desktop.apps.about", "JeanCodeLauncher", "JeanCode"),
    "snake": ("desktop.apps.games", "Snake", "Serpiente"),
    "blocks": ("desktop.apps.games", "Blocks", "Bloques"),
    "mines": ("desktop.apps.games", "Mines", "Buscaminas"),
    "pywin": ("desktop.apps.pywin", "PyWin", "PyWin"),
    "about": ("desktop.apps.about", "About", "Acerca de PyOS"),
}
# a dict has no order in MicroPython: these lists give it
ORDER = ["browser", "files", "terminal", "editor", "music", "images", "paint", "calc", "clock",
         "sysmon", "settings", "disks", "store", "pywin", "jeancode", "snake", "blocks", "mines", "about"]
DOCK = ["files", "browser", "terminal", "editor", "music", "settings", "store"]
FOLDERS = ("/apps", "/disk/apps")

_files = None           # name -> header dict, for app files


def read_header(path):
    """The '# key: value' lines at the top of an app file, or None if it is not one."""
    info = {}
    try:
        with open(path) as f:
            first = f.readline().strip()
            if first != "# pyos-app":
                return None
            for _ in range(12):
                line = f.readline().strip()
                if not line.startswith("#") or ":" not in line:
                    break
                k, v = line[1:].split(":", 1)
                info[k.strip().lower()] = v.strip()
    except OSError:
        return None
    name = path.rsplit("/", 1)[-1][:-3]
    info.setdefault("name", name)
    info["label"] = info["name"]
    info.setdefault("icon", name)
    info.setdefault("mode", "window")
    info["path"] = path
    return info


def scan():
    """Find the app files again (after installing one, say)."""
    global _files
    _files = {}
    for folder in FOLDERS:
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for n in names:
            if n.endswith(".py"):
                info = read_header(folder + "/" + n)
                if info:
                    _files[n[:-3]] = info
    return _files


def app_files():
    return _files if _files is not None else scan()


def names():
    return ORDER + [n for n in sorted(app_files()) if n not in BUILTIN]


MENU = None             # kept for old code: names() is the live list


def info(name):
    if name in BUILTIN:
        return {"label": BUILTIN[name][2], "icon": name, "mode": "window"}
    return app_files().get(name, {"label": name, "icon": name, "mode": "window"})


def label(name):
    return info(name)["label"]


def icon_name(name):
    return info(name).get("icon", name)


def load(name):
    """The App class of a window app (built in or from a file)."""
    if name in BUILTIN:
        module, cls, _ = BUILTIN[name]
        mod = __import__(module, None, None, [cls])
        return getattr(mod, cls)
    meta = app_files()[name]
    ns = {"__name__": "pyos_app_" + name, "__file__": meta["path"]}
    with open(meta["path"]) as f:
        exec(compile(f.read(), meta["path"], "exec"), ns)
    cls = ns.get("App")
    if cls is None:
        raise ValueError("%s has no class App" % meta["path"])
    if getattr(cls, "title", "App") == "App":
        cls.title = meta["label"]
    return cls


def install(source):
    """Copy an app file from a URL or a path into /disk/apps; returns its name."""
    if source.startswith(("http://", "https://")):
        from urllib import request
        data = request.urlopen(source).read()
    else:
        with open(source, "rb") as f:
            data = f.read()
    text = data.decode("utf-8")
    if not text.startswith("# pyos-app"):
        if "import pygame" not in text:
            raise ValueError("not a PyOS app (no '# pyos-app' header) nor a pygame program")
        base = source.rstrip("/").rsplit("/", 1)[-1][:-3] if source.endswith(".py") else "app"
        text = "# pyos-app\n# name: %s\n# mode: fullscreen\n" % base + text     # a plain pygame game
    name = source.rstrip("/").rsplit("/", 1)[-1]
    if not name.endswith(".py"):
        name += ".py"
    for d in ("/disk/apps",):
        try:
            os.mkdir(d)
        except OSError:
            pass
    with open("/disk/apps/" + name, "w") as f:
        f.write(text)
    scan()
    return name[:-3]


def uninstall(name):
    meta = app_files().get(name)
    if meta is None or not meta["path"].startswith("/disk/apps/"):
        raise ValueError("only apps installed in /disk/apps can be removed")
    os.remove(meta["path"])
    scan()
