"""Make a SnakeyOS update for GitHub (the Windows Update of SnakeyOS: see pyos/lib/pyos/update.py).

Once, to create the signing key:

    python tools/make_update.py key
        -> ~/.pykernel/update_signing_key.pem   the private key: keep it secret, never commit it
        -> pyos/etc/update_key.pub              the public key: built into the system, commit it

    Then, for GitHub to sign releases by itself, add the private key as a
    repository secret named UPDATE_SIGNING_KEY (Settings > Secrets and
    variables > Actions), and push a tag:  git tag v1.1.0 && git push origin v1.1.0
    (.github/workflows/release-iso.yml makes the ISO and the signed update, and publishes the release).

For each version (by hand, without the workflow):

    python tools/make_update.py build 1.1.0 [--notes NOTES.md] [--key PATH]
        -> dist/pyos-1.1.0.zip, dist/update.json, dist/update.json.sig
    and attach those three files to a GitHub release tagged v1.1.0.

The key can also come from the UPDATE_SIGNING_KEY environment variable (PEM text).
Needs the `cryptography` package (pip install cryptography).
"""
import hashlib
import json
import os
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_HOME = Path.home() / ".pykernel" / "update_signing_key.pem"
PUBLIC = ROOT / "pyos" / "etc" / "update_key.pub"
# what an update carries: the system as the boot image has it (pyfs/ and pyos/ merged)
TOPS = ("lib", "bin", "etc", "apps", "share", "licenses")


def make_key():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    if KEY_HOME.exists():
        sys.exit("%s already exists: a new key would make the computers with the old one refuse updates" % KEY_HOME)
    key = ec.generate_private_key(ec.SECP256R1())
    KEY_HOME.parent.mkdir(parents=True, exist_ok=True)
    KEY_HOME.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    os.chmod(KEY_HOME, 0o600)
    write_public(key)
    print("private key: %s (secret: back it up, never commit it)" % KEY_HOME)
    print("public key:  %s (commit it: the system checks updates with it)" % PUBLIC)
    print("For GitHub to sign releases: add the private key's text as the repository secret UPDATE_SIGNING_KEY.")


def write_public(key):
    from cryptography.hazmat.primitives import serialization
    point = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    PUBLIC.write_text(point.hex() + "\n")


def load_key(path=None):
    from cryptography.hazmat.primitives import serialization
    pem = os.environ.get("UPDATE_SIGNING_KEY")
    if path:
        pem = Path(path).read_text()
    elif not pem:
        if not KEY_HOME.exists():
            sys.exit("no signing key: run  python tools/make_update.py key  first (or set UPDATE_SIGNING_KEY)")
        pem = KEY_HOME.read_text()
    return serialization.load_pem_private_key(pem.encode(), None)


def files():
    """path in the system -> file in the repository (pyos/ on top of pyfs/, as tools/mkfs.py merges them)."""
    out = {}
    for tree in (ROOT / "pyfs", ROOT / "pyos"):
        for p in sorted(tree.rglob("*")):
            if not p.is_file() or "__pycache__" in p.parts or p.name == "README.md":
                continue
            rel = p.relative_to(tree).as_posix()
            if rel.split("/")[0] in TOPS:
                out[rel] = p
    return out


def build(version, notes_file=None, key_path=None):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    key = load_key(key_path)
    from cryptography.hazmat.primitives import serialization
    shipped = PUBLIC.read_text().strip() if PUBLIC.exists() else ""
    mine = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint).hex()
    if shipped != mine:
        sys.exit("the signing key does not match pyos/etc/update_key.pub: computers would refuse this update")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    name = "snakeyos-%s.zip" % version
    package = dist / name
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, p in files().items():
            data = p.read_bytes()
            if p.suffix in (".py", ".txt", ".json", ".js", ".css", ".html", ".md", ".pub"):
                data = data.replace(b"\r\n", b"\n")
            if rel == "etc/version":
                data = (version + "\n").encode()
            z.writestr(rel, data)
    blob = package.read_bytes()
    notes = Path(notes_file).read_text() if notes_file else ""
    manifest = {"format": 1, "version": version, "package": name, "size": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest(), "date": time.strftime("%Y-%m-%d"),
                "files": len(files()), "notes": notes[:4000]}
    text = json.dumps(manifest, indent=1, sort_keys=True).encode()
    (dist / "update.json").write_bytes(text)
    signature = key.sign(text, ec.ECDSA(hashes.SHA256()))
    (dist / "update.json.sig").write_text(signature.hex() + "\n")
    print("dist/%s (%d KiB), dist/update.json, dist/update.json.sig: attach them to the release v%s"
          % (name, len(blob) >> 10, version))


def main():
    args = sys.argv[1:]
    if not args or args[0] not in ("key", "build"):
        print(__doc__)
        return
    if args[0] == "key":
        make_key()
        return
    if len(args) < 2:
        sys.exit("usage: make_update.py build VERSION [--notes FILE] [--key PATH]")
    version = args[1].lstrip("vV")
    notes = args[args.index("--notes") + 1] if "--notes" in args else None
    key = args[args.index("--key") + 1] if "--key" in args else None
    build(version, notes, key)


if __name__ == "__main__":
    main()
