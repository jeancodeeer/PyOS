# Installing Windows programs in SnakeyOS, and what is installed.
#
# What is installed is read as Windows' "Programs and Features" does (Wine's
# dlls/appwiz.cpl/appwiz.c, ReadApplicationsFromRegistry, LGPL 2.1): the keys
# under ...\CurrentVersion\Uninstall with a DisplayName and a way to uninstall,
# skipping SystemComponent ones. The programs to start are the shortcuts (.lnk)
# installers leave in the Start menu.
#
#   install(path, done)     an installer (.exe) runs in PyWin; a .zip or a lone
#                           .exe is copied to C:\Program Files\<name> by SnakeyOS
#   programs()              [{"key", "name", "publisher", "version", "icon", "uninstall", "location"}]
#   shortcuts()             [{"name", "target" (SnakeyOS path), "arguments", "workdir", "icon"}]
#   uninstall(program, done)
import json
import os

REGISTRY = "/disk/pywin/registro.json"
UNINSTALL = ("HKEY_LOCAL_MACHINE\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall",
             "HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall",
             "HKEY_LOCAL_MACHINE\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall")
OWN = "snakeyos-uninstall "            # an UninstallString of SnakeyOS's own installs
INSTALLER_WORDS = ("setup", "install", "instal", "installer", "_inst", "-inst")
INSTALLER_MARKS = (b"Nullsoft", b"NullsoftInst", b"Inno Setup", b"InstallShield", b"WiX", b"7zS.sfx",
                   b"Setup Factory")
_listeners = []


def on_change(fn):
    """fn() is called when something was installed or uninstalled (the launcher, PyWin's window)."""
    _listeners.append(fn)


def changed():
    for fn in list(_listeners):
        try:
            fn()
        except Exception:
            pass


# ---- the registry file (what PyWin's advapi32 keeps) ----

def _load():
    try:
        with open(REGISTRY) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(reg):
    try:
        os.mkdir("/disk/pywin")
    except OSError:
        pass
    with open(REGISTRY, "w") as f:
        json.dump(reg, f)


def _value(values, name):
    for k in values:
        if k.lower() == name.lower():
            v = values[k]
            return v[1] if isinstance(v, list) and len(v) == 2 else v
    return None


# ---- what is installed ----

def programs():
    reg = _load()
    out = []
    for root in UNINSTALL:
        prefix = root.lower() + "\\"
        for key in sorted(reg):
            low = key.lower()
            if not low.startswith(prefix) or "\\" in low[len(prefix):]:
                continue
            values = reg[key]
            if _value(values, "SystemComponent") == 1:
                continue
            name = _value(values, "DisplayName")
            if not name:
                continue
            if _value(values, "WindowsInstaller") == 1:
                command = "msiexec /x" + key.rsplit("\\", 1)[-1]
            else:
                command = _value(values, "UninstallString")
                if not command:
                    continue
            icon = _value(values, "DisplayIcon") or ""
            index = 0
            if "," in icon:
                icon, _, idx = icon.rpartition(",")
                try:
                    index = int(idx)
                except ValueError:
                    index = 0
            out.append({"key": key, "name": name, "publisher": _value(values, "Publisher") or "",
                        "version": _value(values, "DisplayVersion") or "", "icon": icon.strip('"'),
                        "icon_index": index, "uninstall": command,
                        "location": _value(values, "InstallLocation") or ""})
    return out


def _start_menus():
    from pywin import winpaths
    return [winpaths.folder(0x17, False), winpaths.folder(0x02, False)]


def shortcuts():
    """The program shortcuts in the Start menu (and its folders)."""
    from pywin import shortcut
    from pywin.process import to_host
    out = []
    seen = set()
    stack = [f for f in _start_menus()]
    while stack:
        folder = stack.pop()
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            path = folder + "/" + name
            try:
                is_dir = os.stat(path)[0] & 0x4000
            except OSError:
                continue
            if is_dir:
                stack.append(path)
                continue
            if not name.lower().endswith(".lnk"):
                continue
            try:
                with open(path, "rb") as f:
                    info = shortcut.read(f.read())
            except (OSError, ValueError):
                continue
            target = to_host(info["target"]) if info["target"] else ""
            low = target.lower()
            if not low.endswith(".exe") or "unins" in low.rsplit("/", 1)[-1]:
                continue                                    # uninstallers and links to documents
            if low in seen:
                continue
            seen.add(low)
            out.append({"name": name[:-4], "target": target, "arguments": info["arguments"],
                        "workdir": to_host(info["workdir"]) if info["workdir"] else "",
                        "icon": to_host(info["icon"]) if info["icon"] else target, "link": path})
    out.sort(key=lambda s: s["name"].lower())
    return out


def launch(item):
    """Start an installed program (a shortcut dict)."""
    from pywin import host
    args = item.get("arguments") or ""
    host.start(item["target"], tuple(_split(args)) if args else ())


# ---- installing ----

def is_installer(path):
    name = path.rsplit("/", 1)[-1].lower()
    if any(w in name for w in INSTALLER_WORDS):
        return True
    try:
        with open(path, "rb") as f:
            head = f.read(2 << 20)
        return any(m in head for m in INSTALLER_MARKS)
    except OSError:
        return False


def _nice_name(path):
    name = path.rsplit("/", 1)[-1]
    if "." in name:
        name = name.rsplit(".", 1)[0]
    for junk in ("-portable", "_portable", " portable", "-win64", "_win64", "-x64", "_x64", "-win32"):
        i = name.lower().find(junk)
        if i > 0:
            name = name[:i]
    return name.replace("_", " ").strip() or "Programa"


def install(path, done=None):
    """Install a Windows program. done(ok, message) is called at the end (perhaps later)."""
    low = path.lower()
    done = done or (lambda ok, msg: None)
    try:
        if low.endswith(".msi"):
            done(False, "Los paquetes .msi todavia no se pueden instalar: usa el instalador .exe o el .zip")
        elif low.endswith(".zip"):
            done(True, _install_zip(path))
        elif low.endswith(".exe") and is_installer(path):
            _run_installer(path, done)
        elif low.endswith(".exe"):
            done(True, _install_copy(path))
        else:
            done(False, "No es un programa de Windows (.exe, .zip)")
    except Exception as e:
        done(False, "No se pudo instalar: %s" % e)


def _program_folder(name):
    from pywin import winpaths
    base = winpaths.folder(0x26)
    folder = base + "/" + name
    winpaths._make(folder)
    return folder


def _register(name, folder, exe, own=True):
    """The Uninstall key and the Start menu shortcut, as an installer leaves them."""
    from pywin import winpaths, shortcut
    win_exe = winpaths.windows(exe)
    key = UNINSTALL[0] + "\\" + name
    reg = _load()
    reg[key] = {"DisplayName": [1, name], "DisplayIcon": [1, win_exe], "InstallLocation": [1, winpaths.windows(folder)],
                "UninstallString": [1, OWN + name], "Publisher": [1, "SnakeyOS (PyWin)"], "NoModify": [4, 1]}
    _save(reg)
    menu = winpaths.folder(0x17)
    with open(menu + "/" + name + ".lnk", "wb") as f:
        f.write(shortcut.write(win_exe, workdir=winpaths.windows(folder), description=name, icon=win_exe))
    changed()


def _main_exe(folder, hint):
    """The program in a folder: an .exe that is not an uninstaller or helper, the name's one first."""
    found = []
    stack = [folder]
    while stack:
        d = stack.pop()
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            p = d + "/" + n
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st[0] & 0x4000:
                stack.append(p)
            elif n.lower().endswith(".exe") and not any(w in n.lower() for w in ("unins", "setup", "update", "crash",
                                                                                  "helper", "install")):
                found.append((p, st[6]))
    if not found:
        return None
    want = hint.lower().replace(" ", "")
    for p, size in found:
        if want and want in p.rsplit("/", 1)[-1].lower().replace(" ", ""):
            return p
    found.sort(key=lambda x: (x[0].count("/"), -x[1]))       # near the top, the biggest
    return found[0][0]


def _install_zip(path):
    from office import zipper
    with open(path, "rb") as f:
        files = zipper.read(f.read())
    name = _nice_name(path)
    # one folder at the top of the archive: its name is the program's
    tops = set(n.split("/", 1)[0] for n in files if "/" in n)
    strip = ""
    if len(tops) == 1 and all("/" in n for n in files):
        strip = tops.pop() + "/"
    folder = _program_folder(name)
    from pywin import winpaths
    for n, data in files.items():
        rel = n[len(strip):] if n.startswith(strip) else n
        if not rel or rel.endswith("/") or ".." in rel.split("/"):
            continue
        target = folder + "/" + rel
        winpaths._make(target.rsplit("/", 1)[0])
        with open(target, "wb") as out:
            out.write(data)
    exe = _main_exe(folder, name)
    if exe is None:
        raise ValueError("el .zip no tiene ningun programa .exe")
    _register(name, folder, exe)
    return "%s instalado en %s" % (name, winpaths.windows(folder))


def _install_copy(path):
    """A program that is just an .exe (and maybe its DLLs next to it): copied into Program Files."""
    name = _nice_name(path)
    folder = _program_folder(name)
    src = path.rsplit("/", 1)[0]
    try:
        siblings = [n for n in os.listdir(src) if n.lower().endswith(".dll")]
    except OSError:
        siblings = []
    for n in [path.rsplit("/", 1)[-1]] + siblings:
        with open(src + "/" + n, "rb") as a, open(folder + "/" + n, "wb") as b:
            while True:
                chunk = a.read(65536)
                if not chunk:
                    break
                b.write(chunk)
    exe = folder + "/" + path.rsplit("/", 1)[-1]
    _register(name, folder, exe)
    from pywin import winpaths
    return "%s instalado en %s" % (name, winpaths.windows(folder))


def _run_installer(path, done):
    """A real installer: it runs in PyWin; what it leaves (Uninstall key, shortcuts) shows up after."""
    from pywin import host
    before = set(p["key"] for p in programs())
    before_links = set(s["link"] for s in shortcuts())

    def finished(code):
        new = [p for p in programs() if p["key"] not in before]
        links = [s for s in shortcuts() if s["link"] not in before_links]
        changed()
        if new or links:
            names = ", ".join([p["name"] for p in new] or [s["name"] for s in links])
            done(True, "Instalado: " + names)
        elif code == 0:
            done(True, "El instalador ha terminado")
        else:
            done(False, "El instalador ha terminado con el codigo %#x" % code)
    host.start(path, (), on_exit=finished)


# ---- uninstalling ----

def _split(command):
    """A Windows command line -> its parts (quotes keep spaces)."""
    out, cur, quoted = [], [], False
    for c in command:
        if c == '"':
            quoted = not quoted
        elif c == " " and not quoted:
            if cur:
                out.append("".join(cur))
                cur = []
        else:
            cur.append(c)
    if cur:
        out.append("".join(cur))
    return out


def _remove_tree(path):
    try:
        names = os.listdir(path)
    except OSError:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    for n in names:
        _remove_tree(path + "/" + n)
    try:
        os.rmdir(path)
    except OSError:
        pass


def uninstall(program, done=None):
    done = done or (lambda ok, msg: None)
    cmd = program["uninstall"]
    from pywin.process import to_host
    if cmd.startswith(OWN):
        if program["location"]:
            _remove_tree(to_host(program["location"]))
        reg = _load()
        reg.pop(program["key"], None)
        _save(reg)
        for s in shortcuts():
            if program["location"] and s["target"].lower().startswith(to_host(program["location"]).lower()):
                try:
                    os.remove(s["link"])
                except OSError:
                    pass
        changed()
        done(True, "%s desinstalado" % program["name"])
        return
    if cmd.lower().startswith("msiexec"):
        done(False, "Los programas de Windows Installer (.msi) todavia no se pueden desinstalar")
        return
    parts = _split(cmd)
    if not parts:
        done(False, "No se sabe como desinstalar %s" % program["name"])
        return
    from pywin import host

    def finished(code):
        changed()
        gone = all(p["key"] != program["key"] for p in programs())
        done(gone or code == 0, ("%s desinstalado" % program["name"]) if gone else
             "El desinstalador ha terminado (codigo %#x)" % code)
    host.start(to_host(parts[0]), tuple(parts[1:]), on_exit=finished)
