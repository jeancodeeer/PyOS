# Where Windows' special folders are on the SnakeyOS disk (C:\ is /disk).
#
# The table follows Wine's dlls/shell32/shellpath.c (LGPL 2.1, see
# THIRD_PARTY.md): CSIDL numbers and KNOWNFOLDERID GUIDs -> folders. Folders the
# user already has in SnakeyOS (Escritorio, Documentos, Musica...) are used for
# the matching Windows ones, so programs save where the user looks.
#
#   folder(0x26)                        -> "/disk/Program Files" (made if missing)
#   known_folder("905e63b6-...")        -> the same, by GUID
#   environment()                       -> {"PROGRAMFILES": "C:\\Program Files", ...}

START_MENU = "ProgramData/Microsoft/Windows/Start Menu"
USER_START_MENU = "AppData/Microsoft/Windows/Start Menu"

# CSIDL -> folder under /disk ("" is the disk itself, the user's profile)
CSIDL = {
    0x00: "Escritorio",                          # CSIDL_DESKTOP
    0x02: USER_START_MENU + "/Programs",         # CSIDL_PROGRAMS
    0x05: "Documentos",                          # CSIDL_PERSONAL
    0x06: "Favoritos",                           # CSIDL_FAVORITES
    0x07: USER_START_MENU + "/Programs/Startup",  # CSIDL_STARTUP
    0x08: "AppData/Microsoft/Windows/Recent",    # CSIDL_RECENT
    0x09: "AppData/Microsoft/Windows/SendTo",    # CSIDL_SENDTO
    0x0B: USER_START_MENU,                       # CSIDL_STARTMENU
    0x0D: "Musica",                              # CSIDL_MYMUSIC
    0x0E: "Videos",                              # CSIDL_MYVIDEO
    0x10: "Escritorio",                          # CSIDL_DESKTOPDIRECTORY
    0x13: "AppData/Microsoft/Windows/Network Shortcuts",
    0x14: "Windows/Fonts",                       # CSIDL_FONTS
    0x15: "AppData/Microsoft/Windows/Templates",  # CSIDL_TEMPLATES
    0x16: START_MENU,                            # CSIDL_COMMON_STARTMENU
    0x17: START_MENU + "/Programs",              # CSIDL_COMMON_PROGRAMS
    0x18: START_MENU + "/Programs/Startup",       # CSIDL_COMMON_STARTUP
    0x19: "Escritorio",                          # CSIDL_COMMON_DESKTOPDIRECTORY
    0x1A: "AppData",                             # CSIDL_APPDATA (roaming)
    0x1C: "AppData/Local",                       # CSIDL_LOCAL_APPDATA
    0x1F: "Favoritos",                           # CSIDL_COMMON_FAVORITES
    0x20: "AppData/Local/Microsoft/Windows/INetCache",
    0x21: "AppData/Roaming/Microsoft/Windows/Cookies",
    0x22: "AppData/Local/Microsoft/Windows/History",
    0x23: "ProgramData",                         # CSIDL_COMMON_APPDATA
    0x24: "Windows",                             # CSIDL_WINDOWS
    0x25: "Windows/System32",                    # CSIDL_SYSTEM
    0x26: "Program Files",                       # CSIDL_PROGRAM_FILES
    0x27: "Imagenes",                            # CSIDL_MYPICTURES
    0x28: "",                                    # CSIDL_PROFILE
    0x29: "Windows/System32",                    # CSIDL_SYSTEMX86
    0x2A: "Program Files (x86)",                 # CSIDL_PROGRAM_FILESX86
    0x2B: "Program Files/Common Files",          # CSIDL_PROGRAM_FILES_COMMON
    0x2C: "Program Files (x86)/Common Files",    # CSIDL_PROGRAM_FILES_COMMONX86
    0x2D: "ProgramData/Microsoft/Windows/Templates",
    0x2E: "Documentos",                          # CSIDL_COMMON_DOCUMENTS
    0x2F: START_MENU + "/Programs/Administrative Tools",
    0x30: USER_START_MENU + "/Programs/Administrative Tools",
    0x35: "Musica",                              # CSIDL_COMMON_MUSIC
    0x36: "Imagenes",                            # CSIDL_COMMON_PICTURES
    0x37: "Videos",                              # CSIDL_COMMON_VIDEO
    0x38: "Windows/Resources",
}

# KNOWNFOLDERID (as text, lower case) -> CSIDL, or a folder for the ones with no CSIDL
KNOWN = {
    "b4bfcc3a-db2c-424c-b029-7fe99a87c641": 0x10,     # Desktop
    "fdd39ad0-238f-46af-adb4-6c85480369c7": 0x05,     # Documents
    "374de290-123f-4565-9164-39c4925e467b": "Descargas",   # Downloads
    "fd228cb7-ae11-4ae3-864c-16f3910ab8fe": 0x14,     # Fonts
    "f1b32785-6fba-4fcf-9d55-7b8e7f157091": 0x1C,     # LocalAppData
    "4bd8d571-6d19-48d3-be97-422220080e43": 0x0D,     # Music
    "33e28130-4e1e-4676-835a-98395c3bc3bb": 0x27,     # Pictures
    "5e6c858f-0e22-4760-9afe-ea3317b67173": 0x28,     # Profile
    "62ab5d82-fdc1-4dc3-a9dd-070d1d495d97": 0x23,     # ProgramData
    "905e63b6-c1bf-494e-b29c-65b732d3d21a": 0x26,     # ProgramFiles
    "f7f1ed05-9f6d-47a2-aaae-29d317c6f066": 0x2B,     # ProgramFilesCommon
    "7c5a40ef-a0fb-4bfc-874a-c0f2e0b9fa8e": 0x2A,     # ProgramFilesX86
    "a77f5d77-2e2b-44c3-a6a2-aba601054a51": 0x02,     # Programs
    "0139d44e-6afe-49f2-8690-3dafcae6ffb8": 0x17,     # CommonPrograms
    "a4115719-d62e-491d-aa7c-e74b8be3b067": 0x16,     # CommonStartMenu
    "c4aa340d-f20f-4863-afef-f87ef2e6ba25": 0x19,     # PublicDesktop
    "3eb685db-65f9-4cf6-a03a-e3ef65729f3d": 0x1A,     # RoamingAppData
    "625b53c3-ab48-4ec1-ba1f-a1ef4146fc19": 0x0B,     # StartMenu
    "b97d20bb-f46a-4c97-ba10-5e3608430854": 0x07,     # Startup
    "1ac14e77-02e7-4e5d-b744-2eb1ae5198b7": 0x25,     # System
    "18989b1d-99b5-455b-841c-ab7c74e4ddfc": 0x0E,     # Videos
    "f38bf404-1d43-42f2-9305-67de0b28fc23": 0x24,     # Windows
}


def _make(path):
    import os
    built = ""
    for part in path.split("/"):
        if not part:
            continue
        built += "/" + part
        try:
            os.mkdir(built)
        except OSError:
            pass


def unix_folder(sub):
    path = "/disk/" + sub if sub else "/disk"
    _make(path)
    return path


def folder(csidl, create=True):
    """The SnakeyOS path of a CSIDL folder (made when asked), or None for an unknown CSIDL."""
    sub = CSIDL.get(csidl & 0xFF)
    if sub is None:
        return None
    return unix_folder(sub) if create else ("/disk/" + sub if sub else "/disk")


def known_folder(guid_text):
    v = KNOWN.get(guid_text.lower().strip("{}"))
    if v is None:
        return None
    if type(v) is int:
        return folder(v)
    return unix_folder(v)


def windows(path):
    from pywin.process import to_windows
    return to_windows(path)


def environment():
    """The environment variables a Windows program expects (as Windows paths)."""
    w = lambda csidl: windows(folder(csidl, False))
    return {"USERPROFILE": "C:\\", "HOMEDRIVE": "C:", "HOMEPATH": "\\", "SYSTEMDRIVE": "C:",
            "APPDATA": w(0x1A), "LOCALAPPDATA": w(0x1C), "PROGRAMDATA": w(0x23), "ALLUSERSPROFILE": w(0x23),
            "PROGRAMFILES": w(0x26), "PROGRAMFILES(X86)": w(0x2A), "COMMONPROGRAMFILES": w(0x2B),
            "PROGRAMW6432": w(0x26), "TEMP": "C:\\Temp", "TMP": "C:\\Temp", "WINDIR": w(0x24),
            "SYSTEMROOT": w(0x24), "PUBLIC": "C:\\", "USERNAME": "usuario", "COMPUTERNAME": "SNAKEYOS",
            "OS": "Windows_NT", "PROCESSOR_ARCHITECTURE": "AMD64", "NUMBER_OF_PROCESSORS": "1"}


def expand(text):
    """%VARIABLE% -> its value (unknown ones stay as they are, as on Windows)."""
    env = environment()
    out = []
    i = 0
    while i < len(text):
        j = text.find("%", i)
        if j < 0:
            out.append(text[i:])
            break
        k = text.find("%", j + 1)
        if k < 0:
            out.append(text[i:])
            break
        name = text[j + 1:k].upper()
        out.append(text[i:j])
        if name in env:
            out.append(env[name])
            i = k + 1
        else:
            out.append(text[j:k])
            i = k
    return "".join(out)


def guid_text(addr):
    """A GUID in memory -> 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'."""
    from pywin import mem
    import struct
    raw = mem.read(addr, 16)
    d1, d2, d3 = struct.unpack_from("<IHH", raw, 0)
    rest = bytes(raw[8:16])
    return "%08x-%04x-%04x-%s-%s" % (d1, d2, d3, "".join("%02x" % b for b in rest[:2]),
                                     "".join("%02x" % b for b in rest[2:]))
