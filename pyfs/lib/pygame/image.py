# pygame.image: load BMP and PNG files, save BMP.
import struct
from pygame.surface import Surface, error
from pygame.constants import SRCALPHA


def _read(file):
    if hasattr(file, "read"):
        return file.read()
    with open(file, "rb") as f:
        return f.read()


def load(file, namehint=""):
    data = _read(file)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return _load_png(data)
    if data[:2] == b"BM":
        return _load_bmp(data)
    if data[:2] == b"\xff\xd8" or data[:4] == b"GIF8":
        try:
            import imaging                      # the JPEG and GIF decoders (SnakeyOS)
        except ImportError:
            raise error("JPEG and GIF need the imaging module (part of SnakeyOS)")
        return imaging.load(data)
    raise error("unsupported image format (BMP, PNG, JPEG and GIF work)")


def get_extended():
    return True


def get_sdl_image_version(linked=True):
    return None


# ---- BMP ----

def _load_bmp(data):
    offset = struct.unpack_from("<I", data, 10)[0]
    w, h, planes, bpp, comp = struct.unpack_from("<iiHHI", data, 18)
    header = struct.unpack_from("<I", data, 14)[0]
    if comp not in (0, 3):
        raise error("compressed BMP files are not supported")
    flip = h > 0
    h = abs(h)
    palette = []
    if bpp <= 8:
        count = struct.unpack_from("<I", data, 46)[0] or (1 << bpp)
        base = 14 + header
        for i in range(count):
            b, g, r = data[base + i * 4], data[base + i * 4 + 1], data[base + i * 4 + 2]
            palette.append(0xFF000000 | (r << 16) | (g << 8) | b)
    alpha = bpp == 32
    surf = Surface((w, h), SRCALPHA if alpha else 0)
    out = surf._buf
    stride = ((w * bpp + 31) // 32) * 4
    for y in range(h):
        row = offset + (h - 1 - y if flip else y) * stride
        o = y * w * 4
        if bpp == 32:
            out[o:o + w * 4] = data[row:row + w * 4]
        elif bpp == 24:
            for x in range(w):
                i = row + x * 3
                out[o + x * 4:o + x * 4 + 4] = bytes((data[i], data[i + 1], data[i + 2], 255))
        elif bpp in (1, 4, 8):
            per = 8 // bpp
            mask = (1 << bpp) - 1
            for x in range(w):
                byte = data[row + x // per]
                idx = (byte >> ((per - 1 - x % per) * bpp)) & mask
                out[o + x * 4:o + x * 4 + 4] = palette[idx].to_bytes(4, "little")
        else:
            raise error("%d-bit BMP files are not supported" % bpp)
    if alpha and not any(out[3::4]):
        out[3::4] = b"\xff" * (w * h)        # 32-bit BMP without alpha
        surf._flags = 0
    return surf


def save(surface, file, namehint=""):
    w, h = surface._w, surface._h
    size = 54 + w * h * 4
    head = b"BM" + struct.pack("<IHHI", size, 0, 0, 54)
    head += struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 32, 0, w * h * 4, 2835, 2835, 0, 0)
    if hasattr(file, "write"):
        file.write(head)
        file.write(surface._buf)
        return
    with open(file, "wb") as f:
        f.write(head)
        f.write(surface._buf)


# ---- PNG (non-interlaced; grey, RGB, palette, with or without alpha) ----

def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _load_png(data):
    import deflate
    import io
    pos = 8
    idat = []
    palette = trns = None
    while pos < len(data):
        length, kind = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if interlace:
        raise error("interlaced PNG files are not supported")
    if depth != 8:
        raise error("only 8-bit PNG files are supported")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = deflate.DeflateIO(io.BytesIO(b"".join(idat)), deflate.ZLIB).read()
    stride = w * channels
    alpha = ctype in (4, 6) or trns is not None
    surf = Surface((w, h), SRCALPHA if alpha else 0)
    out = surf._buf
    prev = bytearray(stride)
    i = 0
    for y in range(h):
        ftype = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        bpp = channels
        if ftype == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 255
        elif ftype == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif ftype == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 255
        elif ftype == 4:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                up_left = prev[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + _paeth(left, prev[x], up_left)) & 255
        o = y * w * 4
        for x in range(w):
            j = x * channels
            if ctype == 6:
                r, g, b, a = line[j], line[j + 1], line[j + 2], line[j + 3]
            elif ctype == 2:
                r, g, b, a = line[j], line[j + 1], line[j + 2], 255
            elif ctype == 3:
                k = line[j]
                r, g, b = palette[k * 3], palette[k * 3 + 1], palette[k * 3 + 2]
                a = trns[k] if trns is not None and k < len(trns) else 255
            elif ctype == 4:
                r = g = b = line[j]
                a = line[j + 1]
            else:
                r = g = b = line[j]
                a = 255
            out[o + x * 4] = b
            out[o + x * 4 + 1] = g
            out[o + x * 4 + 2] = r
            out[o + x * 4 + 3] = a
        prev = line
    return surf


def tostring(surface, format="RGBA", flipped=False):
    return bytes(surface._buf)


tobytes = tostring


def frombuffer(data, size, format="RGBA"):
    w, h = size
    s = Surface((w, h), SRCALPHA if "A" in format else 0)
    for i in range(w * h):
        if format in ("RGBA", "RGBX"):
            r, g, b, a = data[i * 4], data[i * 4 + 1], data[i * 4 + 2], data[i * 4 + 3]
        elif format == "BGRA":
            b, g, r, a = data[i * 4], data[i * 4 + 1], data[i * 4 + 2], data[i * 4 + 3]
        else:
            r, g, b, a = data[i * 3], data[i * 3 + 1], data[i * 3 + 2], 255
        s._buf[i * 4:i * 4 + 4] = bytes((b, g, r, a if "A" in format else 255))
    return s


fromstring = frombytes = frombuffer
