# init: services that start at boot, restart when they die, and a cron.
#
# A service is a Python file in /etc/services or /disk/etc/services. It runs
# as a process (kernel.proc). Its first line may say how:
#     # service: restart=always  after=net
# Cron jobs live in /disk/etc/crontab, one per line:
#     */5 * * * *  /disk/bin/backup.py
#     @boot        /disk/bin/hello.py
import os
from kernel import proc, sched, log, timer

DIRS = ("/etc/services", "/disk/etc/services")
CRONTAB = "/disk/etc/crontab"
services = {}      # name -> {"path", "pid", "restart", "starts", "enabled"}


def _options(path):
    opts = {"restart": "no"}
    try:
        with open(path) as f:
            first = f.readline()
    except OSError:
        return opts
    if "service:" in first:
        for word in first.split("service:", 1)[1].split():
            if "=" in word:
                k, v = word.split("=", 1)
                opts[k] = v
    return opts


def discover():
    for d in DIRS:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            if name.endswith(".py"):
                key = name[:-3]
                path = d + "/" + name
                opts = _options(path)
                services.setdefault(key, {"path": path, "pid": None, "starts": 0, "enabled": True})
                services[key].update(path=path, restart=opts.get("restart", "no"))
    return services


def start(name):
    s = services[name]
    if s["pid"] and s["pid"] in proc.table and proc.table[s["pid"]].state != proc.ZOMBIE:
        return s["pid"]
    s["pid"] = proc.spawn(s["path"], [name], name=name)
    s["starts"] += 1
    s["enabled"] = True
    log.info("service %s started (pid %d)" % (name, s["pid"]))
    return s["pid"]


def stop(name):
    s = services[name]
    s["enabled"] = False
    if s["pid"] in proc.table:
        try:
            proc.kill(s["pid"], proc.SIGTERM)
        except OSError:
            pass


def restart(name):
    stop(name)
    start(name)


def status():
    rows = ["SERVICE          PID   STATE     STARTS  RESTART"]
    for name, s in sorted(services.items()):
        p = proc.table.get(s["pid"])
        state = "running" if p and p.state != proc.ZOMBIE else ("stopped" if not s["enabled"] else "exited")
        rows.append("%-16s %-5s %-9s %-7d %s" % (name, s["pid"] or "-", state, s["starts"], s.get("restart", "no")))
    return "\n".join(rows)


# ---- cron ----

def _match(field, value):
    if field == "*":
        return True
    for part in field.split(","):
        if part.startswith("*/"):
            if value % int(part[2:]) == 0:
                return True
        elif "-" in part:
            a, b = part.split("-")
            if int(a) <= value <= int(b):
                return True
        elif int(part) == value:
            return True
    return False


def crontab():
    jobs = []
    try:
        with open(CRONTAB) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 5 if not line.startswith("@") else 1)
                if line.startswith("@"):
                    jobs.append((parts[0], None, parts[1]))
                else:
                    jobs.append(("cron", parts[:5], parts[5]))
    except OSError:
        pass
    return jobs


def _run_job(command):
    args = command.split()
    try:
        proc.spawn(args[0], args, name="cron:" + args[0].rsplit("/", 1)[-1])
    except OSError as e:
        log.warn("cron: %s: %s" % (command, e))


_last_minute = None
_next_check = 0


def _on_tick():
    global _next_check
    if timer.ms() < _next_check:
        return
    _next_check = timer.ms() + 1000
    try:
        _supervise()
    except Exception as e:
        log.warn("init: %r" % e)


def _supervise():
    """Restarts services that died, and runs cron jobs on the minute."""
    global _last_minute
    import time
    if True:
        for name, s in services.items():
            p = proc.table.get(s["pid"])
            dead = s["pid"] and (p is None or p.state == proc.ZOMBIE)
            if dead and s["enabled"] and s.get("restart") in ("always", "on-failure"):
                code = p.status if p else None
                if s["restart"] == "always" or code:
                    log.warn("service %s exited (%s); restarting" % (name, code))
                    if p is not None and p.ppid == proc.init.pid:
                        proc.table.pop(p.pid, None)
                    start(name)
        t = time.localtime()
        minute = t[:5]
        if minute != _last_minute:
            _last_minute = minute
            for kind, fields, command in crontab():
                if kind == "cron" and _match(fields[0], t[4]) and _match(fields[1], t[3]) and \
                        _match(fields[2], t[2]) and _match(fields[3], t[1]) and _match(fields[4], (t[6] + 1) % 7):
                    _run_job(command)


def boot():
    discover()
    for name, s in services.items():
        try:
            start(name)
        except Exception as e:
            log.error("service %s: %r" % (name, e))
    for kind, _, command in crontab():
        if kind == "@boot":
            _run_job(command)
    timer.subscribe(_on_tick)
