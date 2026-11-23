# The desktop clipboard: one piece of text shared by every window.
_text = ""


def get():
    return _text


def set(s):
    global _text
    _text = str(s)
