# The PyKernel desktop: windows, a dock and applications, in pygame.
#
#   desktop()        (a console command) or  import desktop; desktop.run()
# Ctrl+Q leaves it and returns to the text console.


def run(boot=False):
    """The desktop. boot: started by the system at power-on, with the boot
    animation and the user screen; otherwise (the desktop command) a short splash."""
    import gc
    import pygame
    from kernel import mm
    # windows are pixel buffers: give the Python heap more room if RAM allows
    more_memory(48 << 20)
    from desktop import wm, splash, theme
    pygame.init()
    try:                                   # time zone, keyboard, mouse... before the user screen
        from pyos import settings
        settings.apply_all(screen=False)
    except Exception:
        pass
    screen = theme.open_screen()
    steps = [("Cargando las fuentes", _fonts), ("Preparando el fondo de pantalla", _wallpaper),
             ("Cargando las aplicaciones", _apps), ("Iniciando el sonido", _chime)]
    if boot:
        steps.insert(0, ("Comprobando la memoria y los discos", _hardware))
        steps.append(("Conectando a la red", _network))
    splash.splash(screen, steps, boot)
    if boot:
        splash.session(screen)
    else:
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
            if not mm.grow_heap(32):
                return                     # the heap grows from its reserve by itself
        except MemoryError:
            return


def _hardware():
    from kernel import mm
    mm.stats()


def _network():
    from kernel import net
    for _ in range(20):                    # DHCP may still be answering: wait up to 1 s
        if getattr(net, "ip", 0):
            return
        import time
        time.sleep_ms(50)


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
