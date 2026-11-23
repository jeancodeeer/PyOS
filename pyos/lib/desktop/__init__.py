# The PyKernel desktop: windows, a dock and applications, in pygame.
#
#   desktop()        (a console command) or  import desktop; desktop.run()
# Ctrl+Q leaves it and returns to the text console.


def run():
    import gc
    import pygame
    from kernel import mm
    # windows are pixel buffers: give the Python heap more room if RAM allows
    more_memory(48 << 20)
    from desktop import wm, splash, theme
    pygame.init()
    screen = pygame.display.set_mode(theme.SCREEN)
    splash.splash(screen, [("Fuentes", _fonts), ("Fondo de pantalla", _wallpaper), ("Aplicaciones", _apps),
                           ("Sonido", _chime)])
    splash.login(screen)
    wm.WindowManager().run()


def more_memory(want):
    """Move free RAM into the Python heap until `want` bytes are free there
    (as long as the machine keeps some RAM for drivers and programs)."""
    import gc
    from kernel import mm
    gc.collect()
    while gc.mem_free() < want and mm.free_bytes() > (128 << 20):
        try:
            mm.grow_heap(32)
        except MemoryError:
            return


def _fonts():
    from desktop import ui
    for size, bold in ((13, False), (13, True), (15, False), (44, True)):
        ui.font(size, bold).size("PyKernel")


def _wallpaper():
    from desktop import wm
    wm._cached_wallpaper = wm.wallpaper()


def _apps():
    from desktop import apps, icons
    for name in apps.DOCK:
        icons.icon(name, 44)
        icons.icon(name, 52)


def _chime():
    from kernel import sound
    if sound.card is None:
        sound.init()
    if sound.card:
        sound.play_wav("/share/sounds/arranque.wav")
