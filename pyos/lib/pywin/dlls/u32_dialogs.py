# user32.dll, part 3: dialog boxes and two more built-in controls.
#
# A dialog is described by a DIALOG or DIALOGEX resource (a "template"):
# its size, title, font and a list of controls. PyWin reads the template,
# creates a "#32770" window with the controls inside, and sends the
# program's dialog procedure WM_INITDIALOG. A modal dialog (DialogBox...)
# runs its own message loop until the program calls EndDialog.
#
# Sizes in a template are in "dialog units": a quarter of the average
# character width across, an eighth of the character height down.
#
# The controls added here: LISTBOX (a list of lines) and COMBOBOX (a box
# that shows one choice and opens a menu with all of them).
import pygame
from pywin import mem, gui
from pywin.dlls.user32 import dll, state, _wnd, _send, _changed, _create, _i32, _notify, _ui_font, \
    _resource_name, EXTRA_CLASSES, DefWindowProcA, DestroyWindow, ShowWindow, EnableWindow, SetFocus, GetDlgItem
from pywin.gui import WM_COMMAND, WM_CLOSE, WM_KEYDOWN, WM_LBUTTONDOWN, WS_CHILD, WS_VISIBLE

WM_INITDIALOG, WM_SETFONT, WM_NEXTDLGCTL = 0x110, 0x30, 0x28
IDOK, IDCANCEL = 1, 2
DS_SETFONT, DS_CENTER, DS_CONTROL = 0x40, 0x800, 0x400
DWLP_MSGRESULT, DWLP_DLGPROC = 0, 8
VK_RETURN, VK_ESCAPE = 0x0D, 0x1B
CHAR_W, CHAR_H = 6, 13                     # the dialog font's average character, in pixels
CLASS_BY_NUMBER = {0x80: "button", 0x81: "edit", 0x82: "static", 0x83: "listbox", 0x84: "scrollbar",
                   0x85: "combobox"}
# messages whose answer is the dialog procedure's own return value, not DWLP_MSGRESULT
DIRECT_ANSWER = (WM_INITDIALOG, 0x37, 0x2E, 0x2F, 0x39) + tuple(range(0x132, 0x139))


def du_x(n):
    return n * CHAR_W // 4


def du_y(n):
    return n * CHAR_H // 8


# ---- reading a template ----

class Reader:
    """Reads a template field by field from guest memory."""

    def __init__(self, addr):
        self.start = self.at = addr

    def u16(self):
        v = mem.u16(self.at)
        self.at += 2
        return v

    def s16(self):
        v = self.u16()
        return v - 0x10000 if v & 0x8000 else v

    def u32(self):
        v = mem.u32(self.at)
        self.at += 4
        return v

    def u8(self):
        v = mem.u8(self.at)
        self.at += 1
        return v

    def text(self):
        s = mem.wstr(self.at) or ""
        self.at += 2 * (len(s) + 1)
        return s

    def name(self):
        """sz_Or_Ord: nothing, a number (0xFFFF then the number) or a string."""
        first = mem.u16(self.at)
        if first == 0:
            self.at += 2
            return None
        if first == 0xFFFF:
            self.at += 4
            return mem.u16(self.at - 2)
        return self.text()

    def align(self):
        self.at = self.start + ((self.at - self.start + 3) & ~3)


class Template:
    def __init__(self):
        self.style = self.ex_style = 0
        self.x = self.y = self.w = self.h = 0
        self.title, self.cls, self.menu = "", None, None
        self.font_size, self.font_face = 8, ""
        self.items = []


def parse_template(addr):
    """A DLGTEMPLATE or DLGTEMPLATEEX at addr, as a Template."""
    r = Reader(addr)
    t = Template()
    extended = mem.u16(addr) == 1 and mem.u16(addr + 2) == 0xFFFF
    if extended:
        r.u16(), r.u16(), r.u32()                            # version, signature, help id
        t.ex_style, t.style = r.u32(), r.u32()
    else:
        t.style, t.ex_style = r.u32(), r.u32()
    count = r.u16()
    t.x, t.y, t.w, t.h = r.s16(), r.s16(), r.s16(), r.s16()
    t.menu, t.cls, t.title = r.name(), r.name(), r.text()
    if t.style & DS_SETFONT:
        t.font_size = r.u16()
        if extended:
            r.u16(), r.u8(), r.u8()                          # weight, italic, character set
        t.font_face = r.text()
    for _ in range(min(count, 512)):                         # a bad template cannot loop for ever
        r.align()
        item = {}
        if extended:
            r.u32()                                          # help id
            item["ex_style"], item["style"] = r.u32(), r.u32()
        else:
            item["style"], item["ex_style"] = r.u32(), r.u32()
        item["x"], item["y"], item["w"], item["h"] = r.s16(), r.s16(), r.s16(), r.s16()
        item["id"] = r.u32() if extended else r.u16()
        cls = r.name()
        item["class"] = CLASS_BY_NUMBER.get(cls, "static") if isinstance(cls, int) else (cls or "static")
        title = r.name()
        item["title"] = title if isinstance(title, str) else ""
        item["icon"] = title if isinstance(title, int) else None
        extra = r.u16()
        item["data"] = r.at if extra else 0
        r.at += extra
        t.items.append(item)
    return t


# ---- the dialog window ----

def _dialog_proc(p, w, msg, wparam, lparam):
    """The window procedure of every dialog: ask the program's dialog procedure first."""
    fn = w.extra.get(DWLP_DLGPROC)
    if fn and w.extra.get("ready"):
        handled = p.call(fn, w.handle, msg, wparam & 0xFFFFFFFFFFFFFFFF, lparam & 0xFFFFFFFFFFFFFFFF)
        if msg in DIRECT_ANSWER and (handled or msg == WM_INITDIALOG):
            return handled                                   # these answer directly
        if handled & 0xFFFFFFFF:
            return w.extra.get(DWLP_MSGRESULT, 0)            # handled: the answer was stored
    if msg == WM_CLOSE:                                      # the X button means Cancel
        _send(p, w, WM_COMMAND, IDCANCEL, GetDlgItem(p, w.handle, IDCANCEL))
        return 0
    if msg == WM_INITDIALOG:
        return 1
    return DefWindowProcA(p, w.handle, msg, wparam, lparam)


def _dialog_class(p):
    s = state(p)
    if "#32770" not in s.classes:
        s.classes["#32770"] = gui.WndClass("#32770", _dialog_proc, (240, 240, 240))
    return s.classes["#32770"]


def _class_for_control(p, name):
    """The class to create a control with; an unknown one becomes a plain box (and a warning)."""
    s = state(p)
    key = name.lower()
    if key not in s.classes:
        p.warn("control de diálogo desconocido: " + name)
        s.classes[key] = gui.WndClass(key, _plain_proc, (240, 240, 240))
    return name


def _plain_proc(p, w, msg, wparam, lparam):
    return DefWindowProcA(p, w.handle, msg, wparam, lparam)


def create_dialog(p, inst, template_addr, owner, proc, param):
    """Build a dialog from its template. Returns its HWND (still hidden) and whether it should show."""
    t = parse_template(template_addr)
    _dialog_class(p)
    cls = t.cls if isinstance(t.cls, str) and t.cls.lower() in state(p).classes else "#32770"
    child = bool(t.style & WS_CHILD)
    w_px, h_px = du_x(t.w), du_y(t.h)
    x, y = du_x(t.x), du_y(t.y)
    owner_w = _wnd(p, owner)
    if not child:
        w_px += gui.FRAME_W
        h_px += gui.FRAME_H
        sw, sh = getattr(p.ui, "screen_size", (1024, 768))
        if t.style & DS_CENTER or owner_w is None:
            x, y = max(0, (sw - w_px) // 2), max(0, (sh - h_px) // 2)
        elif owner_w is not None:
            x, y = owner_w.x + x, owner_w.y + y
    style = t.style & ~WS_VISIBLE
    hwnd = _create(p, t.ex_style, cls, t.title, style, x, y, w_px, h_px, owner, 0, inst, param, True)
    w = _wnd(p, hwnd)
    if w is None:
        return 0, False
    w.extra[DWLP_DLGPROC] = proc
    w.dialog = True
    for item in t.items:
        name = _class_for_control(p, item["class"])
        h = _create(p, item["ex_style"], name, item["title"], item["style"] | WS_CHILD,
                    du_x(item["x"]), du_y(item["y"]), du_x(item["w"]), du_y(item["h"]),
                    hwnd, item["id"] & 0xFFFF, inst, item["data"], True)
        c = _wnd(p, h)
        if c is not None:
            c.visible = bool(item["style"] & WS_VISIBLE)
    w.extra["ready"] = True
    first = next((c for c in w.children if c.visible and c.enabled), None)
    if _send(p, w, WM_INITDIALOG, first.handle if first else 0, param) and first is not None:
        SetFocus(p, first.handle)
    return hwnd, bool(t.style & WS_VISIBLE)


def _template(p, inst, name):
    found = p.resource(inst, 5, _resource_name(name, True))            # RT_DIALOG
    return found[0] if found else 0


def _modeless(p, inst, addr, owner, proc, param):
    if not addr:
        p.last_error = 1814                                  # ERROR_RESOURCE_NAME_NOT_FOUND
        return 0
    hwnd, show = create_dialog(p, inst, addr, owner, proc, param)
    if hwnd and show:
        ShowWindow(p, hwnd, 1)
    return hwnd


@dll(5)
def CreateDialogParamW(p, inst, name, owner, proc, param):
    return _modeless(p, inst, _template(p, inst, name), owner, proc, param)


@dll(5)
def CreateDialogIndirectParamW(p, inst, template, owner, proc, param):
    return _modeless(p, inst, template, owner, proc, param)


dll.alias("CreateDialogParamA", "CreateDialogParamW")
dll.alias("CreateDialogIndirectParamA", "CreateDialogIndirectParamW")


def _modal(p, inst, addr, owner, proc, param):
    """Show the dialog and run messages until EndDialog. Its result."""
    from pywin.dlls.user32 import _next_message, DispatchMessageA, _write_msg, MSG_SIZE
    if not addr:
        return -1 & 0xFFFFFFFFFFFFFFFF
    hwnd, _ = create_dialog(p, inst, addr, owner, proc, param)
    w = _wnd(p, hwnd)
    if w is None:
        return -1 & 0xFFFFFFFFFFFFFFFF
    if "end" not in w.extra:
        ShowWindow(p, hwnd, 1)
    owner_w = _wnd(p, owner)
    if owner_w is not None:
        EnableWindow(p, owner, 0)                            # the owner waits for the dialog
    msg = p.heap.alloc(MSG_SIZE)
    try:
        while "end" not in w.extra and hwnd in state(p).windows:
            m = _next_message(p, 0)
            if m is None:
                p.ui.wait(15)
                continue
            if m[1] == gui.WM_QUIT:                          # the main loop still needs to see it
                import _thread
                state(p).quit[_thread.get_ident()] = m[2]
                break
            _write_msg(msg, m)
            if not IsDialogMessageW(p, hwnd, msg):
                DispatchMessageA(p, msg)
    finally:
        p.heap.free(msg)
        if owner_w is not None:
            EnableWindow(p, owner, 1)
    result = w.extra.get("end", 0)
    DestroyWindow(p, hwnd)
    return result


@dll(5)
def DialogBoxParamW(p, inst, name, owner, proc, param):
    return _modal(p, inst, _template(p, inst, name), owner, proc, param)


@dll(5)
def DialogBoxIndirectParamW(p, inst, template, owner, proc, param):
    return _modal(p, inst, template, owner, proc, param)


dll.alias("DialogBoxParamA", "DialogBoxParamW")
dll.alias("DialogBoxIndirectParamA", "DialogBoxIndirectParamW")


@dll(2)
def EndDialog(p, hwnd, result):
    w = _wnd(p, hwnd)
    if w is None:
        return 0
    w.extra["end"] = result
    if w.host is not None:
        ShowWindow(p, hwnd, 0)                               # gone at once; destroyed by the loop
    return 1


@dll(4)
def DefDlgProcW(p, hwnd, msg, wparam, lparam):
    return DefWindowProcA(p, hwnd, msg, wparam, lparam)


dll.alias("DefDlgProcA", "DefDlgProcW")


def _dialog_of(p, hwnd):
    w = _wnd(p, hwnd)
    while w is not None and not getattr(w, "dialog", False):
        w = w.parent
    return w


@dll(2)
def IsDialogMessageW(p, hwnd, msg):
    """Enter means OK and Esc means Cancel inside a dialog."""
    dlg = _wnd(p, hwnd)
    if dlg is None or not getattr(dlg, "dialog", False):
        return 0
    target = _dialog_of(p, mem.u64(msg))
    if target is not dlg or mem.u32(msg + 8) != WM_KEYDOWN:
        return 0
    key = mem.u64(msg + 16) & 0xFF
    focus = _wnd(p, state(p).focus)
    multiline_edit = focus is not None and focus.cls and focus.cls.name == "edit" and focus.style & 4
    if key == VK_ESCAPE:
        _send(p, dlg, WM_COMMAND, IDCANCEL, GetDlgItem(p, hwnd, IDCANCEL))
        return 1
    if key == VK_RETURN and not multiline_edit:
        _send(p, dlg, WM_COMMAND, IDOK, GetDlgItem(p, hwnd, IDOK))
        return 1
    return 0


dll.alias("IsDialogMessageA", "IsDialogMessageW")


@dll(0)
def GetDialogBaseUnits(p):
    return (CHAR_H << 16) | CHAR_W


@dll(2)
def MapDialogRect(p, hwnd, rect):
    for k, f in ((0, du_x), (4, du_y), (8, du_x), (12, du_y)):
        mem.put32(rect + k, f(mem.i32(rect + k)))
    return 1


@dll(3)
def GetNextDlgTabItem(p, hwnd, ctl, previous):
    dlg = _wnd(p, hwnd)
    if dlg is None or not dlg.children:
        return 0
    stops = [c for c in dlg.children if c.visible and c.enabled] or dlg.children
    cur = _wnd(p, ctl)
    i = stops.index(cur) if cur in stops else -1
    return stops[(i + (-1 if previous else 1)) % len(stops)].handle


dll.alias("GetNextDlgGroupItem", "GetNextDlgTabItem")


@dll(4)
def CheckRadioButton(p, hwnd, first, last, check):
    for n in range(first, last + 1):
        c = _wnd(p, GetDlgItem(p, hwnd, n))
        if c is not None:
            c.checked = 1 if n == check else 0
            _changed(c)
    return 1


# ---- LISTBOX and COMBOBOX: a list of lines ----

LB_ADDSTRING, LB_INSERTSTRING, LB_DELETESTRING, LB_RESETCONTENT = 0x180, 0x181, 0x182, 0x184
LB_SETCURSEL, LB_GETCURSEL, LB_GETTEXT, LB_GETTEXTLEN, LB_GETCOUNT = 0x186, 0x188, 0x189, 0x18A, 0x18B
LB_GETITEMDATA, LB_SETITEMDATA, LB_FINDSTRING, LB_FINDSTRINGEXACT = 0x199, 0x19A, 0x18F, 0x1A2
LB_GETSEL, LB_SETSEL, LB_GETTOPINDEX, LB_SETTOPINDEX = 0x187, 0x185, 0x18E, 0x197
CB_ADDSTRING, CB_DELETESTRING, CB_GETCOUNT, CB_GETCURSEL, CB_GETLBTEXT = 0x143, 0x144, 0x146, 0x147, 0x148
CB_GETLBTEXTLEN, CB_INSERTSTRING, CB_RESETCONTENT, CB_FINDSTRING, CB_SETCURSEL = 0x149, 0x14A, 0x14B, 0x14C, 0x14E
CB_GETITEMDATA, CB_SETITEMDATA, CB_FINDSTRINGEXACT, CB_LIMITTEXT = 0x150, 0x151, 0x158, 0x141
CB_GETDROPPEDSTATE, CB_SHOWDROPDOWN, CB_SETITEMHEIGHT, CB_GETITEMHEIGHT = 0x157, 0x14F, 0x153, 0x154
LBN_SELCHANGE, CBN_SELCHANGE, LBN_DBLCLK = 1, 1, 2
LB_ERR = 0xFFFFFFFFFFFFFFFF
ROW_H = 16

# the combo box messages, renamed to the list box ones they work like
COMBO_AS_LIST = {CB_ADDSTRING: LB_ADDSTRING, CB_DELETESTRING: LB_DELETESTRING, CB_GETCOUNT: LB_GETCOUNT,
                 CB_GETCURSEL: LB_GETCURSEL, CB_GETLBTEXT: LB_GETTEXT, CB_GETLBTEXTLEN: LB_GETTEXTLEN,
                 CB_INSERTSTRING: LB_INSERTSTRING, CB_RESETCONTENT: LB_RESETCONTENT,
                 CB_FINDSTRING: LB_FINDSTRING, CB_SETCURSEL: LB_SETCURSEL, CB_GETITEMDATA: LB_GETITEMDATA,
                 CB_SETITEMDATA: LB_SETITEMDATA, CB_FINDSTRINGEXACT: LB_FINDSTRINGEXACT}


def _lines(w):
    if "lines" not in w.extra:
        w.extra["lines"] = []                                # [text, item data]
        w.extra["sel"] = -1
        w.extra["top"] = 0
    return w.extra["lines"]


def _text_arg(w, ptr):
    if not ptr:
        return ""
    return (mem.wstr(ptr) if getattr(w, "wide", False) else mem.cstr(ptr)) or ""


def _find(lines, text, start, exact):
    want = text.lower()
    n = len(lines)
    for k in range(n):
        i = (start + 1 + k) % n if start != LB_ERR and start < n else k
        line = lines[i][0].lower()
        if line == want or (not exact and line.startswith(want)):
            return i
    return LB_ERR


def _list_message(p, w, msg, wparam, lparam):
    """The messages a list box and a combo box share. None if msg is not one of them."""
    lines = _lines(w)
    sel = w.extra["sel"]
    if msg == LB_ADDSTRING:
        lines.append([_text_arg(w, lparam), 0])
        if w.style & 2 and w.cls.name == "listbox" or w.style & 0x100 and w.cls.name == "combobox":
            lines.sort(key=lambda x: x[0].lower())           # LBS_SORT / CBS_SORT
        _changed(w)
        return next(i for i, x in enumerate(lines) if x[0] == _text_arg(w, lparam))
    if msg == LB_INSERTSTRING:
        i = wparam if wparam < len(lines) else len(lines)
        lines.insert(i, [_text_arg(w, lparam), 0])
        _changed(w)
        return i
    if msg == LB_DELETESTRING:
        if wparam >= len(lines):
            return LB_ERR
        del lines[wparam]
        if sel >= len(lines):
            w.extra["sel"] = len(lines) - 1
        _changed(w)
        return len(lines)
    if msg == LB_RESETCONTENT:
        lines.clear()
        w.extra["sel"] = -1
        _changed(w)
        return 0
    if msg == LB_GETCOUNT:
        return len(lines)
    if msg == LB_GETCURSEL:
        return sel if sel >= 0 else LB_ERR
    if msg == LB_SETCURSEL:
        i = _i32(wparam)
        w.extra["sel"] = i if 0 <= i < len(lines) else -1
        if w.cls.name == "combobox":
            w.title = lines[i][0] if 0 <= i < len(lines) else ""
        _changed(w)
        return w.extra["sel"] if w.extra["sel"] >= 0 else LB_ERR
    if msg == LB_GETTEXT:
        if wparam >= len(lines):
            return LB_ERR
        text = lines[wparam][0]
        (mem.put_wstr if getattr(w, "wide", False) else mem.put_cstr)(lparam, text)
        return len(text)
    if msg == LB_GETTEXTLEN:
        return len(lines[wparam][0]) if wparam < len(lines) else LB_ERR
    if msg == LB_GETITEMDATA:
        return lines[wparam][1] if wparam < len(lines) else LB_ERR
    if msg == LB_SETITEMDATA:
        if wparam >= len(lines):
            return LB_ERR
        lines[wparam][1] = lparam
        return 1
    if msg in (LB_FINDSTRING, LB_FINDSTRINGEXACT):
        return _find(lines, _text_arg(w, lparam), wparam, msg == LB_FINDSTRINGEXACT)
    return None


def _listbox_proc(p, w, msg, wparam, lparam):
    msg = msg & 0xFFFF
    r = _list_message(p, w, msg, wparam, lparam)
    if r is not None:
        return r
    if msg == LB_GETSEL:
        return 1 if _i32(wparam) == w.extra["sel"] else 0
    if msg == LB_SETSEL:
        w.extra["sel"] = _i32(lparam) if wparam else -1
        _changed(w)
        return 0
    if msg == LB_GETTOPINDEX:
        return w.extra["top"]
    if msg == LB_SETTOPINDEX:
        w.extra["top"] = wparam
        _changed(w)
        return 0
    if msg == WM_LBUTTONDOWN:
        row = w.extra["top"] + ((lparam >> 16) & 0xFFFF) // ROW_H
        if row < len(_lines(w)):
            w.extra["sel"] = row
            _changed(w)
            if w.style & 1:                                  # LBS_NOTIFY
                _notify(p, w, LBN_SELCHANGE)
        SetFocus(p, w.handle)
        return 0
    if msg == gui.WM_MOUSEWHEEL:
        delta = _i32(wparam) >> 16
        w.extra["top"] = max(0, min(len(_lines(w)) - 1, w.extra["top"] - (1 if delta > 0 else -1)))
        _changed(w)
        return 0
    return DefWindowProcA(p, w.handle, msg, wparam, lparam)


def _listbox_render(w):
    lines = _lines(w)
    w.surface.fill((255, 255, 255))
    font = _ui_font()
    for k in range(w.h // ROW_H + 1):
        i = w.extra["top"] + k
        if i >= len(lines):
            break
        y = k * ROW_H
        if i == w.extra["sel"]:
            pygame.draw.rect(w.surface, (0, 120, 215), (0, y, w.w, ROW_H))
        colour = (255, 255, 255) if i == w.extra["sel"] else (0, 0, 0)
        w.surface.blit(font.render(lines[i][0], True, colour), (3, y + 1))
    pygame.draw.rect(w.surface, (130, 135, 144), (0, 0, w.w, w.h), 1)


def _combobox_proc(p, w, msg, wparam, lparam):
    msg = msg & 0xFFFF
    if msg in COMBO_AS_LIST:
        return _list_message(p, w, COMBO_AS_LIST[msg], wparam, lparam)
    if msg in (CB_LIMITTEXT, CB_SHOWDROPDOWN, CB_SETITEMHEIGHT):
        return 1
    if msg == CB_GETDROPPEDSTATE:
        return 0
    if msg == CB_GETITEMHEIGHT:
        return ROW_H
    if msg == WM_LBUTTONDOWN and w.enabled and hasattr(p.ui, "popup_menu"):
        menu = gui.Menu()
        for i, line in enumerate(_lines(w)):
            menu.items.append(gui.MenuItem(line[0].replace("&", "&&"), i + 1))
        ox, oy = p.ui.client_origin(w) if hasattr(p.ui, "client_origin") else (0, 0)
        choice = p.ui.popup_menu(menu, (ox, oy + w.h)) if menu.items else 0
        if choice:
            _list_message(p, w, LB_SETCURSEL, choice - 1, 0)
            _notify(p, w, CBN_SELCHANGE)
        return 0
    return DefWindowProcA(p, w.handle, msg, wparam, lparam)


def _combobox_render(w):
    _lines(w)
    w.surface.fill((255, 255, 255))
    pygame.draw.rect(w.surface, (130, 135, 144), (0, 0, w.w, min(w.h, 22)), 1)
    w.surface.blit(_ui_font().render(w.title, True, (0, 0, 0)), (4, 3))
    x = w.w - 14                                             # the little arrow
    pygame.draw.polygon(w.surface, (60, 60, 60), [(x, 8), (x + 8, 8), (x + 4, 13)])


# every process gets these classes (see EXTRA_CLASSES in user32.py)
EXTRA_CLASSES.append(gui.WndClass("listbox", _listbox_proc, (255, 255, 255), render=_listbox_render))
EXTRA_CLASSES.append(gui.WndClass("combobox", _combobox_proc, (255, 255, 255), render=_combobox_render))
EXTRA_CLASSES.append(gui.WndClass("#32770", _dialog_proc, (240, 240, 240)))
