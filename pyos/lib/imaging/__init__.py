# Image decoders written in Python: JPEG (baseline), GIF and WebP. PNG and
# BMP are in pygame.image.
# Each load() returns a pygame Surface.


def load(path_or_bytes, name=""):
    data = path_or_bytes
    if isinstance(data, str):
        name = data
        with open(data, "rb") as f:
            data = f.read()
    if data[:2] == b"\xff\xd8":
        from imaging import jpeg
        return jpeg.decode(data)
    if data[:4] == b"GIF8":
        from imaging import gif
        return gif.decode(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return webp(data)
    head = bytes(data[:600]).lstrip()
    if head.startswith((b"<svg", b"<?xml", b"<!--")) and b"<svg" in bytes(data[:4000]):
        from imaging import svg
        return svg.render_text(data)
    import io
    import pygame
    return pygame.image.load(io.BytesIO(data), name)


def webp(data):
    """A WebP picture (the web's most common format today), transparency included."""
    import pygame
    from imaging import webpdec
    w, h, pixels = webpdec.decode(data)
    return pygame.Surface((w, h), pygame.SRCALPHA, _buf=pixels)
