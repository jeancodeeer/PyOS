# Playing a video or a song: decode a little ahead, keep the pictures in
# step with the sound.
#
#   p = Player("/disk/Videos/a.mp4")     MP4 / M4A / MOV (H.264 + AAC), or MP3
#   p.play(); p.pause(); p.seek(30.0)
#   p.update()        call it often (each frame of the desktop): True when a new picture is ready
#   p.draw(surface, rect)
#
# The clock is the sound card's: the time of the samples already heard. A
# video without sound (or a machine without a sound card) uses the timer.
import time
from media import mp3 as _mp3
from media import aac as _aac
from media import h264 as _h264
import media
from media import mp4

AUDIO_AHEAD = 1.0          # seconds of sound decoded ahead of the speakers
LATE = 0.3                 # a picture this late is decoded but not shown


class Player:
    def __init__(self, path):
        media.init()
        self.path = path
        self.movie = None
        self.video = self.audio = None          # mp4 tracks
        self.vdec = self.adec = None
        self.mp3 = None                         # (file, decoder) for an MP3
        self.duration = 0.0
        self.width = self.height = 0
        self.playing = False
        self.base = 0.0                         # media time where the clock started
        self.started = 0                        # ticks_ms when it started (timer clock)
        self.vi = self.ai = 0                   # next video / audio sample
        self.shown = -1.0                       # time of the picture on screen
        self.ended = False
        self.error = None
        self.title = path.split("?")[0].rsplit("/", 1)[-1] or path
        low = path.lower().split("?")[0]
        if low.endswith(".mp3"):
            self._open_mp3(path)
        else:
            self._open_mp4(path)

    # ---- opening ----
    def _open_mp4(self, path):
        m = self.movie = mp4.open_file(path)
        self.duration = m.duration
        if m.video and m.video.codec in ("avc1", "avc3"):
            self.video = m.video
            self.vdec = _h264.H264()
            self.vdec.decode(m.video.headers)
            self.width, self.height = m.video.width, m.video.height
        elif m.video:
            self.error = "este vídeo usa el códec %s; SnakeyOS reproduce H.264" % m.video.codec
        if m.audio and m.audio.codec == "mp4a" and m.audio.config:
            self.audio = m.audio
            self.adec = _aac.AAC(m.audio.config)
        if not self.video and not self.audio:
            raise ValueError(self.error or "el archivo no tiene vídeo H.264 ni sonido AAC")

    def _open_mp3(self, path):
        if path.startswith(("http://", "https://")):
            from media.net import HttpFile
            f = HttpFile(path)
            size = f.size
        else:
            import os
            f = open(path, "rb")
            size = os.stat(path)[6]
        self.mp3 = {"file": f, "dec": _mp3.MP3(), "buf": b"", "size": size, "pos": 0, "rate": 44100,
                    "frame_bytes": 0}
        head = f.read(16384)
        f.seek(0)
        dec = _mp3.MP3()
        pcm, used = dec.decode(head)
        rate, chans = dec.format()
        dec.close()
        frame_samples = len(pcm) // (2 * chans) if pcm else 1152
        self.mp3["rate"] = rate
        if used:
            self.duration = size / float(used) * frame_samples / rate

    # ---- the clock ----
    def _sound(self):
        try:
            from kernel import sound
            return sound if sound.card else None
        except ImportError:
            return None

    def clock(self):
        if not self.playing:
            return self.base
        s = self._sound()
        if s is not None and (self.audio or self.mp3):
            return self.base + s.stream_position()
        return self.base + time.ticks_diff(time.ticks_ms(), self.started) / 1000.0

    # ---- controls ----
    def play(self):
        if self.ended:
            self.seek(0.0)
        self.playing = True
        self.started = time.ticks_ms()

    def pause(self):
        if self.playing:
            self.base = self.clock()
            self.playing = False
            s = self._sound()
            if s:
                s.stop()

    def toggle(self):
        self.pause() if self.playing else self.play()

    def seek(self, t):
        t = max(0.0, min(t, max(0.0, self.duration - 0.05)))
        was = self.playing
        s = self._sound()
        if s:
            s.stop()
        self.base, self.ended = t, False
        if self.video:
            target = self.video.index_at(t)
            key = self.video.key_before(target)
            for i in range(key, target):               # decode from the key frame, quietly
                self.vdec.decode(self.video.read(i))
            self.vi = target
        if self.audio:
            self.ai = self.audio.index_at(t)
        if self.mp3:
            pos = int(t / max(0.001, self.duration) * self.mp3["size"])
            self.mp3["file"].seek(pos)
            self.mp3["pos"], self.mp3["buf"] = pos, b""
        self.started = time.ticks_ms()
        self.playing = was

    def close(self):
        s = self._sound()
        if s and self.playing:
            s.stop()
        self.playing = False
        for d in (self.vdec, self.adec):
            if d:
                d.close()
        if self.mp3:
            self.mp3["dec"].close()
            self.mp3["file"].close()
        if self.movie:
            self.movie.close()

    # ---- the work ----
    def _feed_audio(self, s):
        while s.queued_seconds() < AUDIO_AHEAD:
            if self.audio and self.ai < self.audio.count():
                pcm = self.adec.decode(self.audio.read(self.ai))
                self.ai += 1
                if pcm:
                    rate, chans = self.adec.format()
                    s.feed(pcm, rate, chans, 16)
            elif self.mp3:
                m = self.mp3
                if len(m["buf"]) < 4096:
                    more = m["file"].read(16384)
                    m["buf"] += more
                    if not more and not m["buf"]:
                        return False
                pcm, used = m["dec"].decode(m["buf"])
                if not used:
                    m["buf"] = b""                      # nothing decodable left
                    return False
                m["buf"] = m["buf"][used:]
                m["pos"] += used
                if pcm:
                    rate, chans = m["dec"].format()
                    s.feed(pcm, rate, chans, 16)
            else:
                return False
        return True

    def update(self):
        """Decode what is due. True when there is a new picture to show."""
        if not self.playing:
            return False
        s = self._sound()
        more_sound = self._feed_audio(s) if s is not None else False
        if s is not None and not more_sound and (self.audio or self.mp3):
            s.stream_end()                              # the last bit of sound must play too
        now = self.clock()
        new = False
        if self.video:
            v = self.video
            while self.vi < v.count() and v.times[self.vi] <= now:
                got = self.vdec.decode(v.read(self.vi))
                if got and now - v.times[self.vi] < LATE or self.vi + 1 >= v.count():
                    new = True
                    self.shown = v.times[self.vi]
                self.vi += 1
        done_video = not self.video or self.vi >= self.video.count()
        if now >= self.duration or (done_video and not more_sound and not (s and s.busy())):
            if now >= self.duration - 0.05 or not (self.audio or self.mp3):
                self.ended = True
                self.base = self.duration
                self.playing = False
        return new

    def draw(self, surface, rect):
        """The current picture, as big as fits in rect (keeping its shape). False if none."""
        if not self.vdec:
            return False
        x0, y0, w0, h0 = rect
        cx, cy, cw, ch = self.vdec.crop()
        if not cw or not ch:
            return False
        scale = min(w0 / float(cw), h0 / float(ch))
        w, h = max(1, int(cw * scale)), max(1, int(ch * scale))
        x, y = x0 + (w0 - w) // 2, y0 + (h0 - h) // 2
        sw, sh = surface.get_size()
        return self.vdec.draw(surface._buf, sw, sh, x, y, min(w, sw - x), min(h, sh - y))
