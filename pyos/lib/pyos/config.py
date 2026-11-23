# PyOS settings, kept on the disk in /disk/etc/pyos.json.
import json

PATH = "/disk/etc/pyos.json"
_values = None


def _load():
    global _values
    if _values is None:
        try:
            with open(PATH) as f:
                _values = json.load(f)
        except (OSError, ValueError):
            _values = {}
    return _values


def get(key, default=None):
    return _load().get(key, default)


def set(key, value):
    _load()[key] = value
    import os
    try:
        os.mkdir("/disk/etc")
    except OSError:
        pass
    try:
        with open(PATH, "w") as f:
            json.dump(_values, f)
    except OSError:
        pass
