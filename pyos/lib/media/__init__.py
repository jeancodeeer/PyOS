# Audio and video for SnakeyOS: the decoders are machine code inside the kernel
# (the _media module, mpy/modmedia.c); this package reads the files and
# keeps sound and pictures in step.
#
#   from media import player
#   p = player.Player("/disk/Videos/a.mp4")       MP4 (H.264 + AAC) or MP3

ARENA_MB = 128          # RAM the decoders work in (a 1080p H.264 stream needs about 60 MB)
_ready = False


def init():
    """Give the decoders their RAM (once). Taken above 4 GiB when the machine has some."""
    global _ready
    if _ready:
        return
    import _media
    from kernel import mm
    addr = mm.alloc_contiguous(ARENA_MB * 256, high=True)
    _media.arena(addr, ARENA_MB << 20)
    _ready = True
