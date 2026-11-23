# PyOS: the operating system that runs on PyKernel.
#
# PyKernel (pyfs/ in the repository) is the kernel: drivers, memory, network,
# processes, the console. PyOS (pyos/) is what people use on top of it: the
# desktop, the apps, the web browser, fonts, sounds and images.
NAME = "PyOS"
VERSION = "1.0"


def kernel_version():
    from kernel import VERSION as k
    return k


def banner():
    return "%s %s sobre PyKernel %s" % (NAME, VERSION, kernel_version())
