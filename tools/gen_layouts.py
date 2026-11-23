"""Generate pyfs/lib/kernel/layouts.py from the X11 keyboard definitions.

The kernel's keyboard tables are not typed by hand: they are read from the
xkb "symbols" files that every Linux desktop uses (package xkb-data), so
they match the real layouts. Run inside WSL/Linux:

    python3 tools/gen_layouts.py
"""
import re
import sys
from pathlib import Path

XKB = Path("/usr/share/X11/xkb/symbols")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pyfs" / "lib" / "kernel" / "layouts.py"

# name in the kernel -> (xkb file, section)
LAYOUTS = {"us": ("us", "basic"), "es": ("es", "basic"), "latam": ("latam", "basic")}

# xkb key name -> PC scancode (set 1)
SCANCODES = {"TLDE": 0x29, "BKSL": 0x2B, "LSGT": 0x56, "SPCE": 0x39}
SCANCODES.update({"AE%02d" % i: 0x01 + i for i in range(1, 13)})
SCANCODES.update({"AD%02d" % i: 0x0F + i for i in range(1, 13)})
SCANCODES.update({"AC%02d" % i: 0x1D + i for i in range(1, 12)})
SCANCODES.update({"AB%02d" % i: 0x2B + i for i in range(1, 11)})

# keysym name -> character (only what these layouts use; unknown names are reported)
KEYSYMS = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$",
    "percent": "%", "ampersand": "&", "apostrophe": "'", "parenleft": "(", "parenright": ")",
    "asterisk": "*", "plus": "+", "comma": ",", "minus": "-", "period": ".", "slash": "/",
    "colon": ":", "semicolon": ";", "less": "<", "equal": "=", "greater": ">", "question": "?",
    "at": "@", "bracketleft": "[", "backslash": "\\", "bracketright": "]", "asciicircum": "^",
    "underscore": "_", "grave": "`", "braceleft": "{", "bar": "|", "braceright": "}",
    "asciitilde": "~", "exclamdown": "¡", "cent": "¢", "sterling": "£", "currency": "¤",
    "yen": "¥", "brokenbar": "¦", "section": "§", "diaeresis": "¨", "copyright": "©",
    "ordfeminine": "ª", "guillemotleft": "«", "notsign": "¬", "registered": "®",
    "macron": "¯", "degree": "°", "plusminus": "±", "twosuperior": "²",
    "threesuperior": "³", "acute": "´", "mu": "µ", "paragraph": "¶", "periodcentered": "·",
    "cedilla": "¸", "onesuperior": "¹", "masculine": "º", "guillemotright": "»",
    "onequarter": "¼", "onehalf": "½", "threequarters": "¾", "questiondown": "¿",
    "multiply": "×", "division": "÷", "EuroSign": "€", "ntilde": "ñ", "Ntilde": "Ñ",
    "ccedilla": "ç", "Ccedilla": "Ç", "ae": "æ", "AE": "Æ", "oslash": "ø", "Ooblique": "Ø",
    "ssharp": "ß", "eth": "ð", "ETH": "Ð", "thorn": "þ", "THORN": "Þ", "aring": "å",
    "Aring": "Å", "oe": "œ", "OE": "Œ", "lstroke": "ł", "Lstroke": "Ł", "eng": "ŋ",
    "ENG": "Ŋ", "dstroke": "đ", "Dstroke": "Đ", "hstroke": "ħ", "Hstroke": "Ħ",
    "kra": "ĸ", "idotless": "ı", "leftarrow": "←", "rightarrow": "→", "downarrow": "↓",
    "uparrow": "↑", "schwa": "ə", "SCHWA": "Ə", "ezh": "ʒ", "EZH": "Ʒ",
    "rightdoublequotemark": "”", "leftdoublequotemark": "“", "rightsinglequotemark": "’",
    "leftsinglequotemark": "‘", "doublelowquotemark": "„", "singlelowquotemark": "‚",
    "ellipsis": "…", "endash": "–", "emdash": "—", "trademark": "™", "oneeighth": "⅛",
    "threeeighths": "⅜", "fiveeighths": "⅝", "seveneighths": "⅞", "Greek_OMEGA": "Ω",
    "dagger": "†", "doubledagger": "‡", "infinity": "∞", "abovedot": "˙",
    "doubleacute": "˝", "ogonek": "˛", "caron": "ˇ", "breve": "˘",
    "Greek_omega": "ω", "Greek_mu": "μ", "Greek_pi": "π", "permille": "‰",
    "tslash": "ŧ", "Tslash": "Ŧ",
}
# dead keys: the kernel stores "dead:" + the accent typed alone (accent + space)
DEAD = {
    "dead_grave": "`", "dead_acute": "´", "dead_circumflex": "^", "dead_tilde": "~",
    "dead_diaeresis": "¨", "dead_cedilla": "¸", "dead_abovering": "°", "dead_macron": "¯",
    "dead_caron": "ˇ", "dead_breve": "˘", "dead_doubleacute": "˝", "dead_ogonek": "˛",
    "dead_abovedot": "˙", "dead_belowdot": ".", "dead_hook": "?", "dead_horn": "?",
    "dead_stroke": "/", "dead_currency": "¤", "dead_greek": "µ",
}

unknown = set()


def keysym(name):
    if not name or name in ("NoSymbol", "VoidSymbol"):
        return ""
    if name in DEAD:
        return "dead:" + DEAD[name]
    if len(name) == 1:
        return name
    if name in KEYSYMS:
        return KEYSYMS[name]
    m = re.fullmatch(r"U([0-9A-Fa-f]{4,6})", name)
    if m:
        return chr(int(m.group(1), 16))
    m = re.fullmatch(r"0x0*1?([0-9A-Fa-f]{4,6})", name)
    if m:
        return chr(int(m.group(1), 16))
    unknown.add(name)
    return ""


def sections(path):
    """{section name: body text} for one xkb symbols file; '' = default."""
    text = re.sub(r"//[^\n]*", "", path.read_text(encoding="utf-8"))
    out = {}
    for m in re.finditer(r'((?:\w+\s+)*)xkb_symbols\s+"([^"]+)"\s*\{', text):
        start = m.end()
        depth, i = 1, start
        while depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        body = text[start:i - 1]
        out[m.group(2)] = body
        if "default" in m.group(1).split():
            out[""] = body
    return out


def resolve(file, section, keys):
    """Apply an xkb section (and what it includes) onto keys {name: [levels]}."""
    path = XKB / file
    if not path.is_file():
        return
    body = sections(path).get(section or "")
    if body is None:
        sys.exit(f"no section {section!r} in {file}")
    for stmt in re.finditer(r'include\s+"([^"]+)"|key\s+<(\w+)>\s*\{([^;]*?)\}\s*;', body, re.S):
        if stmt.group(1):
            for part in re.split(r"[+|]", stmt.group(1)):
                m = re.fullmatch(r"\s*(\w+)(?:\((\w+)\))?\s*", part)
                if m and m.group(1) in ("pc", "latin", "us", "es", "latam"):
                    resolve(m.group(1), m.group(2), keys)
            continue
        name, spec = stmt.group(2), stmt.group(3)
        m = re.search(r"\[([^\]]*)\]", spec)
        if not m or name not in SCANCODES:
            continue
        levels = [s.strip() for s in m.group(1).split(",")]
        old = keys.get(name, [])
        merged = levels + old[len(levels):]            # override the levels given
        keys[name] = merged


def build(file, section):
    keys = {}
    resolve("pc", None, keys)          # what every PC keyboard shares (e.g. the ISO < > key)
    resolve(file, section, keys)
    table = {}
    for name, levels in keys.items():
        syms = [keysym(s) for s in (levels + ["", "", ""])[:3]]
        normal, shifted, altgr = syms
        letter = (len(normal) == 1 and normal.lower() != normal.upper()
                  and shifted == normal.upper())
        table[SCANCODES[name]] = (normal, shifted, altgr, letter)
    return table


def main():
    tables = {name: build(*src) for name, src in LAYOUTS.items()}
    if unknown:
        print("unknown keysyms (left empty):", ", ".join(sorted(unknown)))
    lines = [
        "# Keyboard layouts: scancode (set 1) -> (normal, shift, AltGr, caps-affects).",
        "# GENERATED by tools/gen_layouts.py from the X11 xkb symbols files; do not edit.",
        "# \"dead:x\" is a dead key whose accent, typed alone, is x.",
        "",
        "LAYOUTS = {",
    ]
    for name, table in tables.items():
        lines.append("    %r: {" % name)
        for code in sorted(table):
            lines.append("        0x%02X: %r," % (code, table[code]))
        lines.append("    },")
    lines.append("}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: " + ", ".join(f"{n} ({len(t)} keys)" for n, t in tables.items()))


if __name__ == "__main__":
    main()
