# X.509 certificates: a DER reader, the fields TLS needs, and chain
# verification against the trusted roots in /etc/ssl/certs.pem.
import binascii
from crypto import digest, ec, rsa

# ---- DER ----


def read_tlv(data, i):
    """(tag, value_start, value_end, next_index) of the element at i."""
    tag = data[i]
    n = data[i + 1]
    i += 2
    if n & 0x80:
        count = n & 0x7F
        n = int.from_bytes(data[i:i + count], "big")
        i += count
    return tag, i, i + n, i + n


def children(data, start, end):
    out, i = [], start
    while i < end:
        tag, s, e, i = read_tlv(data, i)
        out.append((tag, s, e))
    return out


def oid(raw):
    first = raw[0]
    parts, v = [first // 40, first % 40], 0
    for b in raw[1:]:
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            parts.append(v)
            v = 0
    return ".".join(str(p) for p in parts)


SIG_ALGS = {
    "1.2.840.113549.1.1.11": ("rsa", "sha256"), "1.2.840.113549.1.1.12": ("rsa", "sha384"),
    "1.2.840.113549.1.1.13": ("rsa", "sha512"), "1.2.840.113549.1.1.10": ("pss", None),
    "1.2.840.10045.4.3.2": ("ecdsa", "sha256"), "1.2.840.10045.4.3.3": ("ecdsa", "sha384"),
    "1.2.840.10045.4.3.4": ("ecdsa", "sha512"),
}
NAME_OIDS = {"2.5.4.3": "CN", "2.5.4.10": "O", "2.5.4.11": "OU", "2.5.4.6": "C"}


class Certificate:
    def __init__(self, der):
        self.der = der = bytes(der)
        _, s, e, _ = read_tlv(der, 0)
        tbs, alg, sig = children(der, s, e)
        self.tbs = der[tbs[1] - _hdr_len(der, tbs):tbs[2]]
        self.sig_alg = oid(der[children(der, alg[1], alg[2])[0][1]:children(der, alg[1], alg[2])[0][2]])
        self.signature = der[sig[1] + 1:sig[2]]                 # BIT STRING: skip unused-bits byte
        fields = children(der, tbs[1], tbs[2])
        if fields[0][0] == 0xA0:                                 # [0] version
            fields = fields[1:]
        self.serial = int.from_bytes(der[fields[0][1]:fields[0][2]], "big")
        self.issuer_raw = der[fields[2][1]:fields[2][2]]
        self.issuer = _name(der, fields[2])
        self.not_before, self.not_after = (_time(der, t) for t in children(der, fields[3][1], fields[3][2]))
        self.subject_raw = der[fields[4][1]:fields[4][2]]
        self.subject = _name(der, fields[4])
        self._parse_key(der, fields[5])
        self.dns_names = []
        self.is_ca = False
        for f in fields[6:]:
            if f[0] == 0xA3:                                     # [3] extensions
                self._extensions(der, f)

    def _parse_key(self, der, spki):
        alg, bits = children(der, spki[1], spki[2])
        parts = children(der, alg[1], alg[2])
        kind = oid(der[parts[0][1]:parts[0][2]])
        key = der[bits[1] + 1:bits[2]]
        if kind == "1.2.840.113549.1.1.1":                       # rsaEncryption
            _, s, e, _ = read_tlv(key, 0)
            n, ex = children(key, s, e)
            self.key = ("rsa", int.from_bytes(key[n[1]:n[2]], "big"), int.from_bytes(key[ex[1]:ex[2]], "big"))
        elif kind == "1.2.840.10045.2.1":                        # ecPublicKey
            curve = ec.OIDS.get(oid(der[parts[1][1]:parts[1][2]]))
            self.key = ("ec", curve, ec.decode_point(curve, key) if curve else None)
        else:
            self.key = ("unknown", kind)

    def _extensions(self, der, f):
        _, s, e, _ = read_tlv(der, f[1])
        for ext in children(der, s, e):
            parts = children(der, ext[1], ext[2])
            name = oid(der[parts[0][1]:parts[0][2]])
            value = parts[-1]
            if name == "2.5.29.17":                              # subjectAltName
                _, vs, ve, _ = read_tlv(der, value[1])
                for tag, gs, ge in children(der, vs, ve):
                    if tag == 0x82:
                        self.dns_names.append(der[gs:ge].decode())
            elif name == "2.5.29.19":                            # basicConstraints
                _, vs, ve, _ = read_tlv(der, value[1])
                inner = children(der, vs, ve)
                self.is_ca = bool(inner and inner[0][0] == 0x01 and der[inner[0][1]])

    def matches(self, host):
        names = self.dns_names or [self.subject.get("CN", "")]
        host = host.lower()
        for n in names:
            n = n.lower()
            if n == host:
                return True
            if n.startswith("*.") and "." in host and host.split(".", 1)[1] == n[2:]:
                return True
        return False

    def verify_signed_by(self, issuer):
        kind, hashname = SIG_ALGS.get(self.sig_alg, (None, None))
        if kind is None:
            raise ValueError("unsupported signature algorithm " + self.sig_alg)
        if kind == "pss":
            hashname = "sha256"
        h = digest(hashname, self.tbs)
        key = issuer.key
        if kind in ("rsa", "pss") and key[0] == "rsa":
            check = rsa.verify_pss if kind == "pss" else rsa.verify_pkcs1
            return check(key[1], key[2], hashname, h, self.signature)
        if kind == "ecdsa" and key[0] == "ec":
            r, s = decode_ecdsa_sig(self.signature)
            return ec.verify(key[1], key[2], h, r, s)
        return False

    def __repr__(self):
        return "<Certificate %s issued by %s>" % (self.subject.get("CN", "?"), self.issuer.get("CN", "?"))


def decode_ecdsa_sig(sig):
    _, s, e, _ = read_tlv(sig, 0)
    a, b = children(sig, s, e)
    return int.from_bytes(sig[a[1]:a[2]], "big"), int.from_bytes(sig[b[1]:b[2]], "big")


def _hdr_len(der, el):
    # the header of an element ends where its value starts; find its start
    start = el[1] - 2
    while der[start] not in (0x30,) or read_tlv(der, start)[1] != el[1]:
        start -= 1
    return el[1] - start


def _name(der, el):
    out = {}
    for rdn in children(der, el[1], el[2]):
        for atv in children(der, rdn[1], rdn[2]):
            k, v = children(der, atv[1], atv[2])
            key = NAME_OIDS.get(oid(der[k[1]:k[2]]))
            if key:
                out[key] = der[v[1]:v[2]].decode()
    return out


def _time(der, el):
    text = der[el[1]:el[2]].decode()
    if el[0] == 0x17:                                            # UTCTime YYMMDDhhmmssZ
        year = int(text[:2])
        text = ("19" if year >= 50 else "20") + text
    return text[:14]                                             # YYYYMMDDhhmmss


# ---- trust store ----

_roots = None
ROOTS_PATH = "/etc/ssl/certs.pem"


def load_pem(text):
    certs = []
    for block in text.split("-----BEGIN CERTIFICATE-----")[1:]:
        body = block.split("-----END CERTIFICATE-----")[0]
        certs.append(binascii.a2b_base64("".join(body.split())))
    return certs


def subject_of(der):
    """The raw subject of a certificate, without parsing the rest."""
    _, s, e, _ = read_tlv(der, 0)
    _, ts, te, _ = read_tlv(der, s)                  # tbsCertificate
    fields = children(der, ts, te)
    if fields[0][0] == 0xA0:
        fields = fields[1:]
    f = fields[4]
    return der[f[1]:f[2]]


class _LazyRoots:
    """subject -> [Certificate]; each root is parsed the first time it is used."""

    def __init__(self):
        self.d = {}

    def __len__(self):
        return len(self.d)

    def setdefault(self, key, default):
        return self.d.setdefault(key, default)

    def items(self):
        return [(k, self.get(k)) for k in self.d]

    def get(self, key, default=()):
        hit = self.d.get(key)
        if hit is None:
            return default
        out = []
        for c in hit:
            if isinstance(c, (bytes, bytearray)):
                try:
                    c = Certificate(c)
                except Exception:
                    continue
            out.append(c)
        self.d[key] = out
        return out


def roots():
    """Trusted roots, indexed by their subject (raw DER)."""
    global _roots
    if _roots is None:
        _roots = _LazyRoots()
        for path in (ROOTS_PATH, "/disk/etc/ssl/certs.pem"):
            try:
                with open(path) as f:
                    text = f.read()
            except OSError:
                continue
            for der in load_pem(text):
                try:
                    _roots.setdefault(subject_of(der), []).append(der)
                except Exception:
                    continue
    return _roots


def add_root(pem_text):
    for der in load_pem(pem_text):
        c = Certificate(der)
        roots().setdefault(c.subject_raw, []).append(c)


def parse_roots(pem_text):
    """{subject: [Certificate]} for a PEM bundle (a context's own trust)."""
    out = {}
    for der in load_pem(pem_text):
        c = Certificate(der)
        out.setdefault(c.subject_raw, []).append(c)
    return out


def verify_chain(chain, host, now=None, extra=None):
    """chain: [leaf, intermediates...] as Certificates. Raises ValueError.
    extra: more trusted roots ({subject: [Certificate]}), e.g. a context's own."""
    leaf = chain[0]
    if host and not leaf.matches(host):
        raise ValueError("certificate is for %s, not %s" % (leaf.dns_names or leaf.subject, host))
    if now:
        for c in chain:
            if not (c.not_before <= now <= c.not_after):
                raise ValueError("certificate %s expired or not yet valid" % c.subject.get("CN"))
    store = roots()
    for i, cert in enumerate(chain):
        for root in list(store.get(cert.issuer_raw, ())) + list((extra or {}).get(cert.issuer_raw, ())):
            if root.der == cert.der or cert.verify_signed_by(root):
                return True
        if i + 1 >= len(chain):
            break
        if chain[i + 1].subject_raw != cert.issuer_raw or not cert.verify_signed_by(chain[i + 1]):
            raise ValueError("broken chain at " + repr(cert))
    raise ValueError("no trusted root for " + repr(chain[-1]))
