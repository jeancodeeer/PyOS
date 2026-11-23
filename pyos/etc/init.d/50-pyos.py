# PyOS starts here. PyKernel runs every /etc/init.d/*.py at boot; this one
# adds PyOS's commands to the console and, if asked, opens the desktop.
#
#   desktop          the PyOS desktop
#   browse(url)      the web browser
#   jeancode         the AI chat app, full screen
#   apps             the installed apps;  install_app(url_or_path)
#   pyos_autostart(True)   boot straight into the desktop from now on
from kernel.shell import command
from kernel import log
import pyos
from pyos import config


@command("the PyOS desktop: windows, apps, web browser (Ctrl+Q returns here)", "desktop")
def desktop():
    import desktop as d
    d.run()
    from desktop import wm
    if wm.wm is not None and getattr(wm.wm, "after", None) == "jeancode":
        jeancode()


@command("the PyOS web browser", "browse('https://example.com/')")
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


@command("a guided tour: PyOS shows every app by itself, with subtitles", "tour()")
def tour(speed=1.0, only=None):
    from pyos import tour as t
    t.run(speed, only)


@command("PyOS apps: built in, and the .py apps in /apps and /disk/apps")
def apps():
    from desktop import apps as a
    for name in a.names():
        info = a.info(name)
        print("  %-12s %-16s %s" % (name, info["label"], info.get("path", "built in")))


@command("install a PyOS app (.py) from a URL or a file", "install_app('https://host/notas.py')")
def install_app(source=None):
    from desktop import apps as a
    if source is None:
        print("usage: install_app('https://.../app.py')  or  install_app('/usb/app.py')")
        return
    print("installed:", a.install(source))


@command("boot straight into the PyOS desktop (True) or the console (False)", "pyos_autostart(True)")
def pyos_autostart(on=True):
    config.set("autostart", bool(on))
    print("PyOS will start in the %s" % ("desktop" if on else "console"))


log.info(pyos.banner(), echo=True)
if config.get("autostart", False):
    desktop()
