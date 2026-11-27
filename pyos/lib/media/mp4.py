# Reading MP4 files (and .m4a, .mov): where every video frame and every
# piece of sound is inside the file.
#
# An MP4 is a tree of "boxes": 4 bytes of size, 4 letters of type, then
# the contents (more boxes, or data). "moov" describes the tracks, "mdat"
# holds the coded frames. For each track, the sample tables (stbl) say how
# big each frame is, which chunk of the file it is in, and when it plays.
#
#   m = mp4.open_file("/disk/Videos/a.mp4")
#   m.video.width, m.video.height, m.duration
#   for t, data, key in m.video.frames(start_time): ...   data: Annex B for H.264
#   for t, data, _ in m.audio.frames(start_time): ...     data: one raw AAC frame
import struct

START = b"\x00\x00\x00\x01"


class Track:
    def __init__(self, kind):
        self.kind = kind                 # "video" or "audio"
        self.codec = ""                  # "avc1", "mp4a"...
        self.timescale = 1000
        self.duration = 0.0
        self.width = self.height = 0
        self.config = b""                # avcC (H.264) or AudioSpecificConfig (AAC)
        self.nal_len = 4
        self.headers = b""               # SPS and PPS in Annex B (sent before the first frame)
        self.rate = self.channels = 0
        self.offsets = []                # file position of each sample
        self.sizes = []
        self.times = []                  # start of each sample, in seconds
        self.sync = None                 # sample numbers that are key frames (None: all)
        self.file = None

    def count(self):
        return len(self.sizes)

    def index_at(self, t):
        """The sample playing at time t (binary search)."""
        lo, hi = 0, len(self.times)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.times[mid] <= t:
                lo = mid + 1
            else:
                hi = mid
        return max(0, lo - 1)

    def key_before(self, i):
        """The last key frame at or before sample i (decoding has to start there)."""
        if not self.sync:
            return i
        best = 0
        for s in self.sync:
            if s <= i:
                best = s
            else:
                break
        return best

    def read(self, i):
        f = self.file
        f.seek(self.offsets[i])
        data = f.read(self.sizes[i])
        if self.kind == "video" and self.codec == "avc1":
            return to_annexb(data, self.nal_len)
        return data


def to_annexb(data, nal_len=4):
    """MP4 keeps each NAL unit after its length; decoders want 00 00 00 01 before it."""
    out = []
    i, n = 0, len(data)
    while i + nal_len <= n:
        size = int.from_bytes(data[i:i + nal_len], "big")
        i += nal_len
        out.append(data[i:i + size])
        i += size
    return START + START.join(out) if out else b""


class Movie:
    def __init__(self):
        self.video = None
        self.audio = None
        self.duration = 0.0
        self.file = None

    def close(self):
        if self.file:
            self.file.close()
            self.file = None


def _boxes(data, start=0, end=None):
    """(type, body start, body end) of the boxes in data[start:end]."""
    end = len(data) if end is None else end
    i = start
    while i + 8 <= end:
        size, kind = struct.unpack_from(">I4s", data, i)
        head = 8
        if size == 1:
            size = struct.unpack_from(">Q", data, i + 8)[0]
            head = 16
        elif size == 0:
            size = end - i
        if size < head or i + size > end:
            break
        yield kind, i + head, i + size
        i += size


def _find(data, start, end, path):
    """The body of the box at path (b"mdia/minf/stbl") inside data[start:end]."""
    for name in path.split(b"/"):
        for kind, s, e in _boxes(data, start, end):
            if kind == name:
                start, end = s, e
                break
        else:
            return None
    return start, end


def open_file(path):
    """path: a file name, a web address (read piece by piece), or an open file."""
    if hasattr(path, "read"):
        f = path
    elif path.startswith(("http://", "https://")):
        from media.net import HttpFile
        f = HttpFile(path)
    else:
        f = open(path, "rb")
    try:
        moov = None
        pos = 0
        while True:                                      # the top-level boxes: find "moov"
            f.seek(pos)
            head = f.read(16)
            if len(head) < 8:
                break
            size, kind = struct.unpack_from(">I4s", head)
            if size == 1:
                size = struct.unpack_from(">Q", head, 8)[0]
            elif size == 0:
                break
            if kind == b"moov":
                f.seek(pos)
                moov = f.read(size)
                break
            if size < 8:
                break
            pos += size
        if moov is None:
            raise ValueError("no es un MP4 (no tiene 'moov')")
        movie = parse_moov(moov)
        movie.file = f
        for t in (movie.video, movie.audio):
            if t:
                t.file = f
        return movie
    except Exception:
        f.close()
        raise


def parse_moov(data):
    movie = Movie()
    body = _find(data, 0, len(data), b"moov")
    for kind, s, e in _boxes(data, body[0], body[1]):
        if kind != b"trak":
            continue
        track = _parse_trak(data, s, e)
        if track is None:
            continue
        if track.kind == "video" and movie.video is None:
            movie.video = track
        elif track.kind == "audio" and movie.audio is None:
            movie.audio = track
        movie.duration = max(movie.duration, track.duration)
    return movie


def _parse_trak(data, s, e):
    mdia = _find(data, s, e, b"mdia")
    if not mdia:
        return None
    hdlr = _find(data, mdia[0], mdia[1], b"hdlr")
    handler = data[hdlr[0] + 8:hdlr[0] + 12] if hdlr else b""
    kind = {b"vide": "video", b"soun": "audio"}.get(handler)
    if kind is None:
        return None
    t = Track(kind)
    mdhd = _find(data, mdia[0], mdia[1], b"mdhd")
    if mdhd:
        if data[mdhd[0]] == 1:
            t.timescale, dur = struct.unpack_from(">IQ", data, mdhd[0] + 20)
        else:
            t.timescale, dur = struct.unpack_from(">II", data, mdhd[0] + 12)
        t.timescale = t.timescale or 1000
        t.duration = dur / float(t.timescale)
    stbl = _find(data, mdia[0], mdia[1], b"minf/stbl")
    if not stbl:
        return None
    tables = {kind_: (bs, be) for kind_, bs, be in _boxes(data, stbl[0], stbl[1])}
    if b"stsd" in tables:
        _parse_stsd(data, tables[b"stsd"], t)
    _parse_tables(data, tables, t)
    return t


def _parse_stsd(data, box, t):
    s, e = box
    entry = s + 8                                        # version/flags, count
    size, codec = struct.unpack_from(">I4s", data, entry)
    t.codec = codec.decode()
    inner = entry + 8
    if t.kind == "video":
        t.width, t.height = struct.unpack_from(">HH", data, inner + 24)
        children = inner + 78
        for kind, bs, be in _boxes(data, children, entry + size):
            if kind == b"avcC":
                _parse_avcc(data[bs:be], t)
    else:
        t.channels, bits, _, _, rate = struct.unpack_from(">HHHHI", data, inner + 16)
        t.rate = rate >> 16
        for kind, bs, be in _boxes(data, inner + 28, entry + size):
            if kind == b"esds":
                t.config = _esds_config(data[bs + 4:be])


def _parse_avcc(c, t):
    t.config = c
    t.nal_len = (c[4] & 3) + 1
    i = 6
    parts = []
    for _ in range(c[5] & 31):                           # sequence parameter sets
        n = struct.unpack_from(">H", c, i)[0]
        parts.append(c[i + 2:i + 2 + n])
        i += 2 + n
    count = c[i]
    i += 1
    for _ in range(count):                               # picture parameter sets
        n = struct.unpack_from(">H", c, i)[0]
        parts.append(c[i + 2:i + 2 + n])
        i += 2 + n
    t.headers = START + START.join(parts)


def _esds_config(d):
    """The AudioSpecificConfig inside an esds box (descriptor tag 5)."""
    i = 0
    while i < len(d):
        tag = d[i]
        i += 1
        size = 0
        for _ in range(4):                               # sizes use 7 bits per byte
            b = d[i]
            i += 1
            size = (size << 7) | (b & 0x7F)
            if not b & 0x80:
                break
        if tag == 3:                                     # ES descriptor: id, flags
            flags = d[i + 2]
            i += 3
            if flags & 0x80:
                i += 2
            if flags & 0x40:
                i += 1 + d[i]
            if flags & 0x20:
                i += 2
            continue
        if tag == 4:                                     # decoder config: 13 bytes, then tag 5 inside
            i += 13
            continue
        if tag == 5:
            return bytes(d[i:i + size])
        i += size
    return b""


def _parse_tables(data, tables, t):
    # sample sizes
    if b"stsz" in tables:
        s, _ = tables[b"stsz"]
        fixed, count = struct.unpack_from(">II", data, s + 4)
        t.sizes = [fixed] * count if fixed else list(struct.unpack_from(">%dI" % count, data, s + 12))
    elif b"stz2" in tables:
        s, _ = tables[b"stz2"]
        field, count = data[s + 7], struct.unpack_from(">I", data, s + 8)[0]
        if field == 16:
            t.sizes = list(struct.unpack_from(">%dH" % count, data, s + 12))
        else:
            t.sizes = list(data[s + 12:s + 12 + count])
    n = len(t.sizes)
    # chunk offsets
    chunks = []
    if b"stco" in tables:
        s, _ = tables[b"stco"]
        count = struct.unpack_from(">I", data, s + 4)[0]
        chunks = struct.unpack_from(">%dI" % count, data, s + 8)
    elif b"co64" in tables:
        s, _ = tables[b"co64"]
        count = struct.unpack_from(">I", data, s + 4)[0]
        chunks = struct.unpack_from(">%dQ" % count, data, s + 8)
    # which samples are in which chunk
    runs = []
    if b"stsc" in tables:
        s, _ = tables[b"stsc"]
        count = struct.unpack_from(">I", data, s + 4)[0]
        runs = [struct.unpack_from(">III", data, s + 8 + 12 * k) for k in range(count)]
    offsets = []
    k = 0
    for r, (first, per_chunk, _) in enumerate(runs):
        last = runs[r + 1][0] - 1 if r + 1 < len(runs) else len(chunks)
        for chunk in range(first, last + 1):
            if chunk - 1 >= len(chunks):
                break
            pos = chunks[chunk - 1]
            for _ in range(per_chunk):
                if k >= n:
                    break
                offsets.append(pos)
                pos += t.sizes[k]
                k += 1
    t.offsets = offsets
    t.sizes = t.sizes[:len(offsets)]
    # times
    times = []
    if b"stts" in tables:
        s, _ = tables[b"stts"]
        count = struct.unpack_from(">I", data, s + 4)[0]
        now = 0
        scale = float(t.timescale)
        for k in range(count):
            samples, delta = struct.unpack_from(">II", data, s + 8 + 8 * k)
            for _ in range(samples):
                times.append(now / scale)
                now += delta
    t.times = times[:len(t.offsets)]
    while len(t.times) < len(t.offsets):
        t.times.append(t.times[-1] if t.times else 0.0)
    # key frames
    if b"stss" in tables:
        s, _ = tables[b"stss"]
        count = struct.unpack_from(">I", data, s + 4)[0]
        t.sync = [v - 1 for v in struct.unpack_from(">%dI" % count, data, s + 8)]
