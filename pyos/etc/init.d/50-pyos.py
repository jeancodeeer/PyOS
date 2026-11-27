# SnakeyOS starts here. PyKernel runs every /etc/init.d/*.py at boot; this one
# adds SnakeyOS's commands to the console and, if asked, opens the desktop.
#
#   desktop          the SnakeyOS desktop
#   browse(url)      the web browser
#   jeancode         the AI chat app, full screen
#   apps             the installed apps;  install_app(url_or_path)
#   pyos_autostart(False)  boot into the text console from now on (True: the desktop, the default)
#
# SnakeyOS boots into the desktop, like any desktop system, unless the kernel's
# command line says "console" (GRUB's second entry, or a machine without a
# screen such as the tests) or pyos_autostart(False) was used.
from kernel.shell import command
from kernel import log
import pyos
from pyos import config


@command("the SnakeyOS desktop: windows, apps, web browser (Ctrl+Q returns here)", "desktop")
def desktop(boot=False):
    import desktop as d
    d.run(boot)


@command("the SnakeyOS web browser", "browse('https://example.com/')")
def browse(url="about:home"):
    import desktop as d
    from desktop import wm
    wm.START = [("browser", url)]
    d.run()


@command("JeanCode: chat with AI models, full screen (pygame)",
         "jeancode\n  F2 API and key   F3 model   F4 history   Esc stop   Ctrl+Q back")
def jeancode():
    from jeancode import app
    app.main()


@command("a guided tour: SnakeyOS shows every app by itself, with subtitles", "tour()")
def tour(speed=1.0, only=None):
    from pyos import tour as t
    t.run(speed, only)


@command("SnakeyOS apps: built in, and the .py apps in /apps and /disk/apps")
def apps():
    from desktop import apps as a
    for name in a.names():
        info = a.info(name)
        print("  %-12s %-16s %s" % (name, info["label"], info.get("path", "built in")))


@command("install a SnakeyOS app (.py) from a URL or a file", "install_app('https://host/notas.py')")
def install_app(source=None):
    from desktop import apps as a
    if source is None:
        print("usage: install_app('https://.../app.py')  or  install_app('/usb/app.py')")
        return
    print("installed:", a.install(source))


@command("boot straight into the SnakeyOS desktop (True) or the console (False)", "pyos_autostart(True)")
def pyos_autostart(on=True):
    config.set("autostart", bool(on))
    print("SnakeyOS will start in the %s" % ("desktop" if on else "console"))


log.info(pyos.banner(), echo=True)
from kernel import cmdline
if config.get("autostart", True) and not cmdline.has("console"):
    desktop(boot=True)
