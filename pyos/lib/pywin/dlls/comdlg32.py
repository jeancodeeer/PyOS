# comdlg32.dll: the "Open" and "Save as" dialogs. SnakeyOS asks for the file
# with its own dialog (or, at the text console, on the keyboard).
from pywin import mem
from pywin.dlls import Dll
from pywin.process import to_host, to_windows

dll = Dll("comdlg32")

# OPENFILENAME (64-bit): where the fields are
FILE, MAX_FILE, INITIAL_DIR, TITLE, DEF_EXT = 48, 56, 80, 88, 112


def _ask(p, ofn, save, wide):
    get = mem.wstr if wide else mem.cstr
    title_at, dir_at = mem.u64(ofn + TITLE), mem.u64(ofn + INITIAL_DIR)
    title = get(title_at) if title_at else ("Guardar como" if save else "Abrir")
    file_at, room = mem.u64(ofn + FILE), mem.u32(ofn + MAX_FILE)
    start = get(file_at) if file_at else ""
    folder = to_host(get(dir_at), p.cwd) if dir_at else p.cwd
    default = to_host(start, folder) if start else folder.rstrip("/") + "/"
    answer = p.ui.ask_path(title, default, save)
    if not answer:
        return 0
    win = to_windows(to_host(answer, folder))
    if len(win) + 1 > room:
        return 0
    (mem.put_wstr if wide else mem.put_cstr)(file_at, win)
    return 1


@dll(1)
def GetOpenFileNameA(p, ofn):
    return _ask(p, ofn, False, False)


@dll(1)
def GetOpenFileNameW(p, ofn):
    return _ask(p, ofn, False, True)


@dll(1)
def GetSaveFileNameA(p, ofn):
    return _ask(p, ofn, True, False)


@dll(1)
def GetSaveFileNameW(p, ofn):
    return _ask(p, ofn, True, True)


@dll(0)
def CommDlgExtendedError(p):
    return 0


@dll(1)
def ChooseColorA(p, cc):
    return 0                                    # "cancelled": the program keeps its colour


# ---- printing: choose the printer, get a DC to draw the pages on ----

PD_RETURNDC, PD_RETURNDEFAULT = 0x100, 0x400


@dll(1)
def PrintDlgW(p, pd):
    from pywin.dlls import g32_extra
    names = g32_extra.printer_names()
    flags = mem.u32(pd + 40)
    if flags & PD_RETURNDEFAULT:
        choice = 0
    else:
        choice = p.ui.choose("Imprimir", "¿En qué impresora?", names) if hasattr(p.ui, "choose") else 0
    if choice is None:
        return 0                                             # cancelled
    if flags & PD_RETURNDC:
        mem.put64(pd + 32, g32_extra.create_printer_dc(p, names[choice]))
    mem.put64(pd + 16, 0)                                    # no DEVMODE / DEVNAMES of ours
    mem.put64(pd + 24, 0)
    mem.put16(pd + 52, 1)                                    # one copy
    return 1


@dll(1)
def PageSetupDlgW(p, psd):
    return 0


@dll(1)
def ChooseColorW(p, cc):
    return 0                                    # "cancelled": the program keeps its colour


@dll(1)
def ChooseFontW(p, cf):
    return 0
