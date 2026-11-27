# Sound: play samples, WAV files and tones on the sound card.
#
#   sound.beep(440, 300)              a tone: frequency (Hz), length (ms)
#   sound.play_wav('/share/sounds/hola.wav')
#   sound.play(pcm_bytes, rate=22050, channels=1, bits=16)
#   sound.stop();  sound.volume(60);  sound.busy()
#
# The card (ac97.py or hda.py) plays a ring of small buffers by itself. A timer
# callback keeps the buffers it has already played filled with what comes
# next, so long sounds stream without holding up Python.
import struct
from kernel import arch as _arch   # ARM64: C versions of the viper functions
import math
import micropython
from kernel import timer, log

card = None
_queue = bytearray()        # 16-bit stereo samples still to hand to the card
_filled = 0                 # how many buffers we have filled ahead
_playing = False
_next = 0                   # the next ring slot to fill


def init():
    """Find a sound card: AC'97 or Intel HD Audio (both play a ring of buffers)."""
    global card
    from kernel import ac97, hda
    card = None
    for driver in (ac97, hda):
        try:
            card = driver.probe()
        except Exception as e:
            log.warn("sound: %s: %r" % (driver.__name__, e))
        if card:
            break
    if card:
        timer.subscribe(_on_tick)
        log.info("sound: %s at %d Hz" % (card.name, card.rate))
    return card


@micropython.viper
def _widen(src: ptr8, n: int, dst: ptr8, channels: int, bits: int):
    """n input frames -> 16-bit stereo little-endian in dst."""
    o = 0
    i = 0
    for k in range(n):
        if bits == 8:
            lo = 0
            hi = int(src[i]) - 128
            if hi < 0:
                hi += 256
            i += 1
            dst[o] = lo
            dst[o + 1] = hi
            if channels == 2:
                hi = int(src[i]) - 128
                if hi < 0:
                    hi += 256
                i += 1
            dst[o + 2] = lo
            dst[o + 3] = hi
        else:
            dst[o] = src[i]
            dst[o + 1] = src[i + 1]
            if channels == 2:
                i += 2
            dst[o + 2] = src[i]
            dst[o + 3] = src[i + 1]
            i += 2
        o += 4
_widen = _arch.fast(_widen, 'sound_widen')


@micropython.viper
def _stretch(src: ptr32, n: int, dst: ptr32, out_n: int, rate: int, target: int):
    k = 0
    while k < out_n:
        dst[k] = src[k * rate // target]
        k += 1
_stretch = _arch.fast(_stretch, 'sound_stretch')


def _resample(data, rate):
    """Nearest-neighbour rate change of 16-bit stereo samples (frames of 4 bytes)."""
    target = card.rate
    if rate == target:
        return data
    frames = len(data) // 4
    out_frames = frames * target // rate
    out = bytearray(out_frames * 4)
    _stretch(data, frames, out, out_frames, rate, target)
    return out


def play(data, rate=48000, channels=2, bits=16):
    """Queue raw PCM samples (replaces what was playing)."""
    if card is None:
        return False
    frames = len(data) // (channels * bits // 8)
    pcm = bytearray(frames * 4)
    _widen(data, frames, pcm, channels, bits)
    if card.set_rate(rate) != rate:
        pcm = _resample(pcm, rate)
    stop()
    global _queue
    _queue = pcm
    _start()
    return True


# ---- streaming: players add sound bit by bit (a video, a long song) ----

_stream = {"rate": 0, "fed": 0, "on": False, "ending": False}   # the stream a player is feeding


def stream_begin(rate=44100):
    """Start a new stream (a song, a video, or after jumping in it)."""
    stop()
    _stream["rate"] = card.set_rate(rate) if card else rate
    _stream["fed"] = 0
    _stream["on"] = True
    _stream["ending"] = False


def stream_end():
    """No more sound will come: play what is queued, even a last part-filled buffer."""
    _stream["ending"] = True
    if card is not None and not _playing and _queue:
        _start()


def feed(data, rate=44100, channels=2, bits=16):
    """Add PCM samples after what is already queued (does not stop the sound).
    The card only gets whole buffers, so no silence slips in between pieces."""
    global _queue
    if card is None or not data:
        return False
    if not _stream["on"]:
        stream_begin(rate)
    frames = len(data) // (channels * bits // 8)
    pcm = bytearray(frames * 4)
    _widen(data, frames, pcm, channels, bits)
    if _stream["rate"] != rate:
        pcm = _resample(pcm, rate)
    _stream["fed"] += len(pcm) // 4
    _queue += pcm
    if not _playing and len(_queue) >= 4 * card.BUF_BYTES:     # a little ahead before starting
        _start()
    return True


def queued_seconds():
    """Sound handed in but not heard yet (in the queue and in the card's ring)."""
    if card is None or not _playing:
        return len(_queue) / 4.0 / max(1, _stream["rate"] or 44100)
    ahead = (_next - card.current()) % card.BUFFERS
    return (len(_queue) + ahead * card.BUF_BYTES) / 4.0 / (_stream["rate"] or 44100)


def stream_position():
    """Seconds of the stream already heard (the clock of a video player)."""
    rate = _stream["rate"] or 44100
    return max(0.0, _stream["fed"] / float(rate) - queued_seconds())


def _start():
    global _playing, _next, _filled
    card.stop()
    _next = 0
    _filled = 0
    for _ in range(card.BUFFERS - 1):            # fill the whole ring before starting
        if not _fill_one():
            break
    if _filled:
        card.set_last(_filled - 1)
        card.start()
        _playing = True


def _fill_one():
    """Copy the next piece of the queue into the next ring slot."""
    global _queue, _next, _filled
    if not _queue:
        return False
    if _stream["on"] and not _stream["ending"] and len(_queue) < card.BUF_BYTES:
        return False                                 # wait for a whole buffer
    chunk = _queue[:card.BUF_BYTES]
    _queue = _queue[card.BUF_BYTES:]
    buf = card.bufs[_next]
    buf[:len(chunk)] = chunk
    if len(chunk) < card.BUF_BYTES:
        buf[len(chunk):] = bytes(card.BUF_BYTES - len(chunk))
    _next = (_next + 1) % card.BUFFERS
    _filled += 1
    return True


def _on_tick():
    """Keep the ring ahead of the card while there is more to play."""
    global _playing
    if not _playing or card is None:
        return
    cur = card.current()
    ahead = (_next - cur) % card.BUFFERS
    while _queue and ahead < card.BUFFERS - 2:
        if not _fill_one():                      # a stream waiting for a whole buffer
            break
        card.set_last(_next - 1)
        ahead += 1
    if not card.running():
        if _queue and (len(_queue) >= card.BUF_BYTES or _stream["ending"] or not _stream["on"]):
            _start()                             # the card ran dry while sound was coming: go on
        elif not _queue:
            _playing = False


def stop():
    global _queue, _playing
    _queue = bytearray()
    _playing = False
    _stream["on"] = False
    if card:
        card.stop()


def busy():
    return _playing


def volume(percent):
    if card:
        card.volume(percent)


def tone(freq, ms, vol=0.4, rate=22050, shape="sine"):
    """PCM bytes (16-bit mono) of a tone."""
    n = rate * ms // 1000
    out = bytearray(2 * n)
    amp = int(32767 * vol)
    step = 2 * math.pi * freq / rate
    for i in range(n):
        if shape == "square":
            v = amp if (i * freq * 2 // rate) % 2 == 0 else -amp
        else:
            v = int(amp * math.sin(i * step))
        fade = min(1.0, i / 200, (n - i) / 200)                # no clicks at the ends
        struct.pack_into("<h", out, 2 * i, int(v * fade))
    return out


def beep(freq=880, ms=150, vol=0.4):
    return play(tone(freq, ms, vol), 22050, 1, 16)


def read_wav(path_or_bytes):
    """(pcm bytes, rate, channels, bits) of a PCM WAV file."""
    data = path_or_bytes
    if isinstance(data, str):
        with open(data, "rb") as f:
            data = f.read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    i, fmt = 12, None
    while i + 8 <= len(data):
        kind, size = data[i:i + 4], struct.unpack_from("<I", data, i + 4)[0]
        body = data[i + 8:i + 8 + size]
        if kind == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", body)
        elif kind == b"data":
            if fmt is None or fmt[0] != 1:
                raise ValueError("only uncompressed PCM WAV")
            return body, fmt[2], fmt[1], fmt[5]
        i += 8 + size + (size & 1)
    raise ValueError("WAV without data")


def play_wav(path_or_bytes):
    pcm, rate, channels, bits = read_wav(path_or_bytes)
    return play(pcm, rate, channels, bits)


def melody(notes, tempo=120):
    """notes: [('C4', 1), ('E4', 0.5), ...] as names and beats; plays them all."""
    names = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    beat = 60000 // tempo
    pcm = bytearray()
    for name, beats in notes:
        ms = int(beat * beats)
        if name in ("-", "R"):
            pcm += bytes(2 * (22050 * ms // 1000))
            continue
        semis = names[name[0].upper()] + (1 if "#" in name else 0) + 12 * (int(name[-1]) - 4)
        pcm += tone(440 * 2 ** (semis / 12), ms)
    return play(pcm, 22050, 1, 16)
