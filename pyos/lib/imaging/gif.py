# GIF decoder (first frame): LZW in Python, transparency kept.
import pygame
from pygame.constants import SRCALPHA


def _lzw(data, min_size, npixels):
    clear, end = 1 << min_size, (1 << min_size) + 1
    size = min_size + 1
    table = [bytes([i]) for i in range(clear)] + [b"", b""]
    out = bytearray()
    prev = None
    acc = nbits = 0
    i = 0
    n = len(data)
    while len(out) < npixels:
        while nbits < size:
            if i >= n:
                return out
            acc |= data[i] << nbits
            nbits += 8
            i += 1
        code = acc & ((1 << size) - 1)
        acc >>= size
        nbits -= size
        if code == clear:
            size = min_size + 1
            table = table[:clear + 2]
            prev = None
            continue
        if code == end:
            break
        if prev is None:
            entry = table[code]
        elif code < len(table):
            entry = table[code]
            table.append(prev + entry[:1])
        else:
            entry = prev + prev[:1]
            table.append(entry)
        out += entry
        prev = entry
        if len(table) == (1 << size) and size < 12:
            size += 1
    return out


def decode(data):
    data = bytes(data)
    if data[:4] != b"GIF8":
        raise ValueError("not a GIF")
    w, h = data[6] | (data[7] << 8), data[8] | (data[9] << 8)
    flags = data[10]
    i = 13
    gct = None
    if flags & 0x80:
        n = 3 << ((flags & 7) + 1)
        gct = data[i:i + n]
        i += n
    transparent = None
    surf = pygame.Surface((w, h), SRCALPHA)
    surf.fill((0, 0, 0, 0))
    while i < len(data):
        b = data[i]
        if b == 0x21:                                       # extension
            label = data[i + 1]
            i += 2
            if label == 0xF9 and data[i] >= 4 and data[i + 1] & 1:
                transparent = data[i + 4]
            while data[i]:
                i += data[i] + 1
            i += 1
        elif b == 0x2C:                                     # image
            x0, y0 = data[i + 1] | (data[i + 2] << 8), data[i + 3] | (data[i + 4] << 8)
            fw, fh = data[i + 5] | (data[i + 6] << 8), data[i + 7] | (data[i + 8] << 8)
            f = data[i + 9]
            i += 10
            palette = gct
            if f & 0x80:
                n = 3 << ((f & 7) + 1)
                palette = data[i:i + n]
                i += n
            interlaced = f & 0x40
            min_size = data[i]
            i += 1
            chunks = bytearray()
            while data[i]:
                chunks += data[i + 1:i + 1 + data[i]]
                i += data[i] + 1
            pixels = _lzw(chunks, min_size, fw * fh)
            rows = list(range(fh))
            if interlaced:
                rows = list(range(0, fh, 8)) + list(range(4, fh, 8)) + list(range(2, fh, 4)) + list(range(1, fh, 2))
            buf = surf._buf
            for src_row, y in enumerate(rows):
                if y0 + y >= h:
                    continue
                for x in range(fw):
                    k = src_row * fw + x
                    if k >= len(pixels) or x0 + x >= w:
                        break
                    c = pixels[k]
                    if c == transparent or palette is None:
                        continue
                    o = ((y0 + y) * w + x0 + x) * 4
                    buf[o] = palette[3 * c + 2]
                    buf[o + 1] = palette[3 * c + 1]
                    buf[o + 2] = palette[3 * c]
                    buf[o + 3] = 255
            return surf
        else:
            break
    return surf


def load(path):
    with open(path, "rb") as f:
        return decode(f.read())
