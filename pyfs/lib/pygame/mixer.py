# pygame.mixer on the kernel's sound driver (kernel/sound.py).
# One sound at a time: playing a new one replaces the one playing.
# Sound files: uncompressed WAV. Without a sound card every call still
# works and nothing is heard.
_init = False
_volume = 1.0


def _snd():
    from kernel import sound
    if sound.card is None and _init:
        sound.init()
    return sound


def init(frequency=44100, size=-16, channels=2, buffer=512, *args, **kw):
    global _init
    _init = True
    _snd()


def pre_init(*args, **kw):
    pass


def quit():
    global _init
    stop()
    _init = False


def get_init():
    return (44100, -16, 2) if _init else None


def stop():
    _snd().stop()


def pause():
    stop()


def unpause():
    pass


def fadeout(ms):
    stop()


def set_num_channels(n):
    pass


def get_num_channels():
    return 1


def get_busy():
    return _snd().busy()


class Sound:
    def __init__(self, file=None, buffer=None, **kw):
        from kernel import sound
        if file is not None:
            try:
                self.pcm, self.rate, self.channels, self.bits = sound.read_wav(
                    file if isinstance(file, str) else file.read())
            except (ValueError, OSError):
                # OGG, MP3 or a missing file: a silent sound, so the game still runs
                self.pcm, self.rate, self.channels, self.bits = b"", 22050, 1, 16
        else:
            self.pcm, self.rate, self.channels, self.bits = bytes(buffer or b""), 22050, 1, 16
        self.volume = 1.0

    def play(self, loops=0, maxtime=0, fade_ms=0):
        pcm = self.pcm * (loops + 1) if 0 <= loops < 10 else self.pcm
        _snd().play(pcm, self.rate, self.channels, self.bits)
        return Channel(0)

    def stop(self):
        stop()

    def fadeout(self, ms):
        stop()

    def set_volume(self, value):
        self.volume = value

    def get_volume(self):
        return self.volume

    def get_length(self):
        return len(self.pcm) / (self.rate * self.channels * self.bits // 8)

    def get_num_channels(self):
        return 1

    def get_raw(self):
        return bytes(self.pcm)


class Channel:
    def __init__(self, id=0):
        self.id = id

    def play(self, sound, loops=0, maxtime=0, fade_ms=0):
        sound.play(loops)

    def stop(self):
        stop()

    def get_busy(self):
        return get_busy()

    def set_volume(self, *v):
        pass


def find_channel(force=False):
    return Channel(0)


class _Music:
    def __init__(self):
        self.sound = None
        self.vol = 1.0

    def load(self, file, namehint=""):
        self.sound = Sound(file)

    def play(self, loops=0, start=0.0, fade_ms=0):
        if self.sound:
            self.sound.play(loops)

    def stop(self):
        stop()

    def pause(self):
        stop()

    def unpause(self):
        self.play()

    def fadeout(self, ms):
        stop()

    def set_volume(self, v):
        self.vol = v
        _snd().volume(int(v * 100))

    def get_volume(self):
        return self.vol

    def get_busy(self):
        return get_busy()

    def queue(self, file, namehint="", loops=0):
        self.load(file)


music = _Music()
