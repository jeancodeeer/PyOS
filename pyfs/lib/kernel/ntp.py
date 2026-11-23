# Set the clock from the network (SNTP, RFC 4330): one UDP packet each way.
import struct
import time
from kernel import net

NTP_EPOCH = 2208988800            # seconds between 1900 and 1970
SERVERS = ["pool.ntp.org", "time.google.com", "time.cloudflare.com"]


def query(server, timeout_ms=3000):
    """Seconds since 1970 according to `server`."""
    ep = net.UDPEndpoint()
    try:
        ep.sendto(b"\x1b" + bytes(47), net.resolve(server), 123)
        data, _ = ep.recvfrom(timeout_ms)
    finally:
        ep.close()
    secs, frac = struct.unpack_from("!II", data, 40)
    return secs - NTP_EPOCH + frac / 2 ** 32


def sync(servers=None):
    """Adjust time.time() to the network clock; returns the correction in seconds."""
    if net.nic is None or not net.ip:
        net.up()
    last = None
    for s in servers or SERVERS:
        try:
            now = query(s)
        except OSError as e:
            last = e
            continue
        before = time.time()
        time._boot_epoch = int(now) - (time.ticks_ms() // 1000)
        return int(now) - before
    raise OSError(110, "no NTP server answered (%s)" % last)
