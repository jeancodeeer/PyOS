# pygame for PyKernel.
#
# The same API as pygame 2 (Surface, Rect, display, draw, event, key,
# mouse, time, font, image, transform, sprite, mixer), written for this
# kernel: the screen is the video card's linear framebuffer (kernel/video.py),
# input comes straight from the keyboard and mouse drivers, and the pixel
# work is done by the _gfx C module. Real pygame is a C extension on top of
# SDL and CPython, which this kernel does not have.
#
#   import pygame
#   pygame.init()
#   screen = pygame.display.set_mode((640, 480))
#   ...
#   pygame.quit()                        # back to the text console
#
# Differences: there is no window, so Ctrl+Q posts QUIT; Ctrl+C interrupts
# the program; sound is silent; fonts are the 8x16 VGA font, scaled; images
# load from BMP and PNG. If a program ends without pygame.quit(), the
# console goes back to text mode by itself.
from pygame.constants import *
from pygame.rect import Rect, FRect
from pygame.color import Color
from pygame.surface import Surface, error
from pygame import display, draw, event, font, image, key, mixer, mouse, sprite, time, transform
from pygame import math
from pygame.math import Vector2, Vector3
from pygame import constants, locals

class version:
    ver = "2.6.0-pykernel"
    vernum = (2, 6, 0)
    SDL = None


ver = version.ver
SDL = None
IS_CE = False

_init = False


def init():
    """Start pygame. Returns (modules that started, modules that failed)."""
    global _init
    font.init()
    mixer.init()
    _init = True
    return (5, 0)


def quit():
    global _init
    display.quit()
    font.quit()
    mixer.quit()
    _init = False


def get_init():
    return _init


def get_error():
    return ""


def set_error(msg):
    pass


def get_sdl_version(linked=True):
    return (2, 0, 0)


def register_quit(fn):
    pass


def encode_string(obj, encoding="utf8", errors="strict", etype=None):
    return obj.encode(encoding) if isinstance(obj, str) else obj


def encode_file_path(obj, etype=None):
    return encode_string(obj)
