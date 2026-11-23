# Image decoders written in Python: JPEG (baseline) and GIF. PNG and BMP
# are in pygame.image. Each load() returns a pygame Surface.


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
    import io
    import pygame
    return pygame.image.load(io.BytesIO(data), name)
