# crypt32.dll, wintrust.dll and bcrypt.dll: certificates, signatures and
# hashes. Programs use them to check that a file is signed (PyWin answers
# "no signature": nothing here can vouch for a Windows signature) and to
# hash data (done for real with Python's hashlib).
import hashlib
from pywin import mem
from pywin.dlls import Dll

dll = Dll("crypt32")
dll_wintrust = Dll("wintrust")
dll_bcrypt = Dll("bcrypt")
CRYPT_E_NO_MATCH, TRUST_E_NOSIGNATURE = 0x80092009, 0x800B0100
STATUS_SUCCESS, STATUS_NOT_SUPPORTED, STATUS_INVALID_PARAMETER = 0, 0xC00000BB, 0xC000000D


# ---- crypt32: no certificates to find ----

@dll(11)
def CryptQueryObject(p, kind, obj, content, fmt, flags, enc, content_type, fmt_type, store, msg, ctx):
    p.last_error = CRYPT_E_NO_MATCH
    return 0


for _name, _n in (("CertCloseStore", 2), ("CryptMsgClose", 1)):
    dll.functions[_name] = ((lambda p, *a: 1), _n)

for _name, _n in (("CertGetCertificateContextProperty", 4), ("CertFindCertificateInStore", 6),
                  ("CryptMsgGetParam", 5), ("CertNameToStrW", 5), ("CertGetNameStringW", 6),
                  ("CertFreeCertificateContext", 1)):
    dll.functions[_name] = ((lambda p, *a: 0), _n)


# ---- wintrust: is this file signed by someone Windows trusts? ----

@dll_wintrust(3)
def WinVerifyTrust(p, hwnd, action, data):
    return TRUST_E_NOSIGNATURE


# ---- bcrypt: hashes, done with hashlib ----

ALGORITHMS = {"SHA256": "sha256", "SHA1": "sha1", "MD5": "md5", "SHA384": "sha384", "SHA512": "sha512"}
SIZES = {"sha256": 32, "sha1": 20, "md5": 16, "sha384": 48, "sha512": 64}


class Algorithm:
    def __init__(self, name):
        self.name = name

    def close(self):
        pass


class Hash:
    def __init__(self, name):
        self.name = name
        if name == "sha384" or name == "sha512":
            import crypto
            self.h = getattr(crypto, name)()
        else:
            self.h = getattr(hashlib, name)()

    def close(self):
        pass


@dll_bcrypt(4)
def BCryptOpenAlgorithmProvider(p, out, alg_id, impl, flags):
    name = ALGORITHMS.get((mem.wstr(alg_id) or "").upper())
    if name is None or not hasattr(hashlib, name) and name not in ("sha384", "sha512"):
        return STATUS_NOT_SUPPORTED
    mem.put64(out, p.new_handle(Algorithm(name)))
    return STATUS_SUCCESS


@dll_bcrypt(2)
def BCryptCloseAlgorithmProvider(p, h, flags):
    p.handles.pop(h, None)
    return STATUS_SUCCESS


@dll_bcrypt(6)
def BCryptGetProperty(p, h, prop, out, size, result, flags):
    alg = p.handles.get(h)
    name = mem.wstr(prop) or ""
    if not isinstance(alg, (Algorithm, Hash)):
        return STATUS_INVALID_PARAMETER
    if name == "HashDigestLength":
        value = SIZES[alg.name]
    elif name == "ObjectLength":
        value = 64
    else:
        return STATUS_NOT_SUPPORTED
    if out and size >= 4:
        mem.put32(out, value)
    if result:
        mem.put32(result, 4)
    return STATUS_SUCCESS


@dll_bcrypt(7)
def BCryptCreateHash(p, alg_h, out, obj, obj_size, secret, secret_size, flags):
    alg = p.handles.get(alg_h)
    if not isinstance(alg, Algorithm):
        return STATUS_INVALID_PARAMETER
    mem.put64(out, p.new_handle(Hash(alg.name)))
    return STATUS_SUCCESS


@dll_bcrypt(4)
def BCryptHashData(p, h, data, size, flags):
    obj = p.handles.get(h)
    if not isinstance(obj, Hash):
        return STATUS_INVALID_PARAMETER
    obj.h.update(mem.read(data, size))
    return STATUS_SUCCESS


@dll_bcrypt(4)
def BCryptFinishHash(p, h, out, size, flags):
    obj = p.handles.get(h)
    if not isinstance(obj, Hash):
        return STATUS_INVALID_PARAMETER
    digest = obj.h.digest()
    mem.write(out, digest[:size])
    return STATUS_SUCCESS


@dll_bcrypt(1)
def BCryptDestroyHash(p, h):
    p.handles.pop(h, None)
    return STATUS_SUCCESS


@dll_bcrypt(4)
def BCryptGenRandom(p, alg, buf, size, flags):
    import crypto
    mem.write(buf, crypto.random_bytes(size))
    return STATUS_SUCCESS
