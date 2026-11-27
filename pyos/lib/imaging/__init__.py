# Image decoders written in Python: JPEG (baseline) and GIF. PNG and BMP
# are in pygame.image; WebP comes from the kernel (libwebp, in machine code).
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
    try:
        import _media
    except ImportError:                       # not on PyKernel (a PC running the browser's tests)
        import io
        return pygame.image.load(io.BytesIO(data), "x.webp")
    import media
    media.init()                              # the decoder's memory
    w, h, pixels = _media.webp(data)
    return pygame.Surface((w, h), pygame.SRCALPHA, _buf=bytearray(pixels))
