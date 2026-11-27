# Users, groups and passwords.
#
# Accounts live in /disk/etc/passwd (so they survive power-off), one per
# line:  name:uid:gid:home:salt$hash:full name
# Passwords are stored as PBKDF2-HMAC-SHA256 hashes, never in clear text.
import hashlib
import binascii
import os

PASSWD = "/disk/etc/passwd"
ITERATIONS = 2000
_accounts = None
current_uid = 0

try:
    PermissionError
except NameError:                                 # MicroPython has no PermissionError of its own
    class PermissionError(OSError):
        pass


def _pbkdf2(password, salt, iterations=ITERATIONS):
    import crypto
    key = password.encode()
    u = crypto.hmac("sha256", key, salt + b"\x00\x00\x00\x01")
    out = bytearray(u)
    for _ in range(iterations - 1):
        u = crypto.hmac("sha256", key, u)
        for i in range(32):
            out[i] ^= u[i]
    return bytes(out)


def hash_password(password):
    from crypto import random_bytes
    salt = random_bytes(8)
    return binascii.hexlify(salt).decode() + "$" + binascii.hexlify(_pbkdf2(password, salt)).decode()


def check_password(password, stored):
    if not stored:
        return True                               # account without a password
    salt, _, digest = stored.partition("$")
    return binascii.hexlify(_pbkdf2(password, binascii.unhexlify(salt))).decode() == digest


def accounts():
    global _accounts
    if _accounts is None:
        _accounts = {"root": {"uid": 0, "gid": 0, "home": "/", "hash": "", "gecos": "administrator"}}
        try:
            with open(PASSWD) as f:
                for line in f:
                    parts = line.rstrip("\n").split(":")
                    if len(parts) >= 6:
                        _accounts[parts[0]] = {"uid": int(parts[1]), "gid": int(parts[2]), "home": parts[3],
                                               "hash": parts[4], "gecos": parts[5]}
        except OSError:
            pass
    return _accounts


def save():
    try:
        os.mkdir("/disk/etc")
    except OSError:
        pass
    with open(PASSWD, "w") as f:
        for name, a in accounts().items():
            f.write("%s:%d:%d:%s:%s:%s\n" % (name, a["uid"], a["gid"], a["home"], a["hash"], a["gecos"]))


def name_of(uid):
    for name, a in accounts().items():
        if a["uid"] == uid:
            return name
    return str(uid)


def useradd(name, password="", gecos=""):
    acc = accounts()
    if name in acc:
        raise ValueError("user exists: " + name)
    uid = max(a["uid"] for a in acc.values()) + 1
    uid = max(uid, 1000)
    home = "/disk/home/" + name
    for d in ("/disk/home", home):
        try:
            os.mkdir(d)
        except OSError:
            pass
    acc[name] = {"uid": uid, "gid": uid, "home": home, "hash": hash_password(password) if password else "",
                 "gecos": gecos}
    save()
    return uid


def userdel(name):
    if name == "root":
        raise ValueError("root cannot be removed")
    accounts().pop(name)
    save()


def passwd(name, password):
    accounts()[name]["hash"] = hash_password(password) if password else ""
    save()


def authenticate(name, password):
    a = accounts().get(name)
    return a is not None and check_password(password, a["hash"])


def login(name, password):
    """Become `name` for this console: sets $USER, $HOME and the uid."""
    global current_uid
    if not authenticate(name, password):
        raise PermissionError("login incorrect")
    a = accounts()[name]
    current_uid = a["uid"]
    from kernel import proc
    p = proc.current()
    p.uid = a["uid"]
    p.env.update(USER=name, HOME=a["home"])
    return a


def whoami():
    from kernel import proc
    return name_of(proc.current().uid)


def is_root():
    from kernel import proc
    return proc.current().uid == 0


def require_root():
    if not is_root():
        raise PermissionError("you need to be root (su('root'))")


def is_admin(name=None):
    """root, or an account marked "administrador" (the first one SnakeyOS creates is)."""
    name = name or whoami()
    a = accounts().get(name)
    return name == "root" or (a is not None and "administrador" in a["gecos"])


def require_admin():
    if not is_admin():
        raise PermissionError("hace falta una cuenta de administrador")
