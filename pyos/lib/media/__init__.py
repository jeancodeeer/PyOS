# Audio and video for SnakeyOS, all in Python: the MP4 reader (mp4.py), the
# decoders (h264.py, aac.py, mp3.py) and the player that keeps sound and
# pictures in step (player.py).
#
#   from media import player
#   p = player.Player("/disk/Videos/a.mp4")       MP4 (H.264 + AAC) or MP3
#
# init() still hands the kernel's "arena" (RAM outside the Python heap) to
# the JavaScript engine, which allocates from it.

ARENA_MB = 64
_ready = False


def init():
    global _ready
    if _ready:
        return
    import _media
    from kernel import mm
    addr = mm.alloc_contiguous(ARENA_MB * 256, high=True)
    _media.arena(addr, ARENA_MB << 20)
    _ready = True
