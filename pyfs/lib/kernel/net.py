# The network stack, in Python: Ethernet, ARP, IPv4, ICMP, UDP, TCP,
# DHCP and DNS. The `socket` module (/lib/socket.py) is a thin face on top.
#
#   net.up()                  find the card, ask DHCP for an address
#   net.ping('10.0.2.2')      ICMP echo, returns the round-trip in ms
#   net.resolve('example.com')
#
# Frames come in from the card on every poll(): a timer callback
# polls 100 times a second, and anything that waits (connect, recv) polls too.
import struct
import _thread
import time
from kernel import log, timer

ETH_IP, ETH_ARP = 0x0800, 0x0806
PROTO_ICMP, PROTO_TCP, PROTO_UDP = 1, 6, 17
BROADCAST = b"\xff" * 6
MTU = 1500
MSS = 1460

nic = None
mac = b""
ip = 0                 # addresses are 32-bit ints internally
mask = 0
gateway = 0
dns_servers = []
hostname = "pykernel"
arp_table = {}         # ip -> mac
stats = {"rx": 0, "tx": 0, "rx_bytes": 0, "tx_bytes": 0, "dropped": 0}


class _RLock:
    """A lock the same thread may take again (poll() can run inside send())."""

    def __init__(self):
        self._lock = _thread.allocate_lock()
        self.owner, self.depth = None, 0

    def __enter__(self):
        me = _thread.get_ident()
        if self.owner != me:
            self._lock.acquire()
            self.owner = me
        self.depth += 1

    def try_enter(self):
        me = _thread.get_ident()
        if self.owner != me:
            if not self._lock.acquire(0):
                return False
            self.owner = me
        self.depth += 1
        return True

    def __exit__(self, *exc):
        if self.depth == 1:
            self.owner = None
            self.depth = 0
            self._lock.release()
        else:
            self.depth -= 1


_lock = _RLock()
_poller = None
_dhcp_task = None
_ident = 0


# ---- helpers ----

def aton(text):
    a, b, c, d = (int(x) for x in text.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def ntoa(n):
    return "%d.%d.%d.%d" % (n >> 24, (n >> 16) & 255, (n >> 8) & 255, n & 255)


def checksum(data, initial=0):
    if len(data) & 1:
        data = bytes(data) + b"\x00"
    s = initial + sum(struct.unpack("!%dH" % (len(data) // 2), data))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def _pseudo(src, dst, proto, length):
    return sum(struct.unpack("!6H", struct.pack("!IIBBH", src, dst, 0, proto, length)))


def _now():
    return timer.ms()


# ---- link layer ----

def _send_eth(dst_mac, ethertype, payload):
    frame = dst_mac + mac + struct.pack("!H", ethertype) + payload
    if len(frame) < 60:
        frame += bytes(60 - len(frame))
    for _ in range(50):
        if nic.send(frame):
            stats["tx"] += 1
            stats["tx_bytes"] += len(frame)
            return True
        time.sleep_ms(1)
    stats["dropped"] += 1
    return False


def _arp(op, target_mac, target_ip):
    pkt = struct.pack("!HHBBH6sI6sI", 1, ETH_IP, 6, 4, op, mac, ip, target_mac, target_ip)
    _send_eth(BROADCAST if op == 1 else target_mac, ETH_ARP, pkt)


def _on_arp(pkt):
    if len(pkt) < 28:
        return
    _, _, _, _, op, smac, sip, _, tip = struct.unpack_from("!HHBBH6sI6sI", pkt)
    if sip:
        arp_table[sip] = smac
    if op == 1 and tip == ip and ip:
        _arp(2, smac, sip)


def resolve_mac(addr, timeout_ms=3000):
    if addr == 0xFFFFFFFF or (mask and addr | mask == 0xFFFFFFFF):
        return BROADCAST
    hop = addr if (addr & mask) == (ip & mask) else gateway
    if hop in arp_table:
        return arp_table[hop]
    deadline = _now() + timeout_ms
    while _now() < deadline:
        _arp(1, bytes(6), hop)
        for _ in range(25):
            poll()
            if hop in arp_table:
                return arp_table[hop]
            time.sleep_ms(10)
    raise OSError(113, "no ARP reply from %s" % ntoa(hop))       # EHOSTUNREACH


# ---- IPv4 ----

def send_ip(dst, proto, payload, src=None):
    global _ident
    if src is None:
        src = ip
    _ident = (_ident + 1) & 0xFFFF
    header = struct.pack("!BBHHHBBHII", 0x45, 0, 20 + len(payload), _ident, 0x4000, 64, proto, 0, src, dst)
    header = header[:10] + struct.pack("!H", checksum(header)) + header[12:]
    return _send_eth(resolve_mac(dst), ETH_IP, header + payload)


def _on_ip(pkt):
    if len(pkt) < 20 or pkt[0] >> 4 != 4:
        return
    ihl = (pkt[0] & 15) * 4
    total = struct.unpack_from("!H", pkt, 2)[0]
    proto = pkt[9]
    src, dst = struct.unpack_from("!II", pkt, 12)
    if dst != ip and dst != 0xFFFFFFFF and ip and (dst | mask) != 0xFFFFFFFF:
        return
    body = pkt[ihl:total]
    if proto == PROTO_ICMP:
        _on_icmp(src, body)
    elif proto == PROTO_UDP:
        _on_udp(src, dst, body)
    elif proto == PROTO_TCP:
        _on_tcp(src, body)


# ---- ICMP ----

_echo = {}     # (id, seq) -> arrival time


def _on_icmp(src, body):
    if len(body) < 8:
        return
    kind = body[0]
    if kind == 8:                                       # echo request -> reply
        reply = b"\x00\x00\x00\x00" + body[4:]
        reply = reply[:2] + struct.pack("!H", checksum(reply)) + reply[4:]
        send_ip(src, PROTO_ICMP, reply)
    elif kind == 0:
        ident, seq = struct.unpack_from("!HH", body, 4)
        _echo[(ident, seq)] = _now()


def ping(host, seq=1, timeout_ms=2000, size=32):
    """Round-trip time in ms to `host`, or None if no reply came."""
    dst = resolve(host)
    ident = 0x5059
    body = struct.pack("!BBHHH", 8, 0, 0, ident, seq) + bytes(range(size))
    body = body[:2] + struct.pack("!H", checksum(body)) + body[4:]
    start = _now()
    send_ip(dst, PROTO_ICMP, body)
    while _now() - start < timeout_ms:
        poll()
        if (ident, seq) in _echo:
            return _echo.pop((ident, seq)) - start
        time.sleep_ms(2)
    return None


# ---- UDP ----

udp_ports = {}            # port -> UDPEndpoint
_next_port = 49152


def ephemeral_port():
    global _next_port
    while True:
        _next_port = 49152 + (_next_port - 49152 + 1) % 16000
        if _next_port not in udp_ports and not any(c.lport == _next_port for c in tcp_conns.values()):
            return _next_port


class UDPEndpoint:
    def __init__(self, port=0):
        self.port = port or ephemeral_port()
        if self.port in udp_ports:
            raise OSError(98, "port in use")            # EADDRINUSE
        self.queue = []
        udp_ports[self.port] = self

    def sendto(self, data, dst, dport):
        n = len(data)
        header = struct.pack("!HHHH", self.port, dport, 8 + n, 0)
        csum = checksum(header + data, _pseudo(ip, dst, PROTO_UDP, 8 + n)) or 0xFFFF
        send_ip(dst, PROTO_UDP, header[:6] + struct.pack("!H", csum) + data)
        return n

    def recvfrom(self, timeout_ms=None):
        deadline = None if timeout_ms is None else _now() + timeout_ms
        while not self.queue:
            poll()
            if self.queue:
                break
            if deadline is not None and _now() >= deadline:
                raise OSError(110, "timed out")
            time.sleep_ms(5)
        return self.queue.pop(0)

    def close(self):
        udp_ports.pop(self.port, None)


def _on_udp(src, dst, body):
    if len(body) < 8:
        return
    sport, dport, length = struct.unpack_from("!HHH", body)
    ep = udp_ports.get(dport)
    if ep is not None:
        ep.queue.append((bytes(body[8:length]), (ntoa(src), sport)))


# ---- TCP ----

FIN, SYN, RST, PSH, ACK = 0x01, 0x02, 0x04, 0x08, 0x10
CLOSED, LISTEN, SYN_SENT, SYN_RCVD, ESTABLISHED, FIN_WAIT_1, FIN_WAIT_2, CLOSE_WAIT, CLOSING, LAST_ACK, TIME_WAIT = range(11)
STATE_NAMES = ("CLOSED", "LISTEN", "SYN_SENT", "SYN_RCVD", "ESTABLISHED", "FIN_WAIT_1", "FIN_WAIT_2",
               "CLOSE_WAIT", "CLOSING", "LAST_ACK", "TIME_WAIT")
WINDOW = 32768
RTO_MS = 600

tcp_conns = {}            # (lport, rip, rport) -> TCPConn
tcp_listeners = {}        # lport -> TCPListener


def _isn():
    return (time.ticks_us() * 4 + _now()) & 0xFFFFFFFF


def _seq_lt(a, b):
    return ((a - b) & 0xFFFFFFFF) > 0x7FFFFFFF


class TCPConn:
    def __init__(self, lport, rip, rport):
        self.lport, self.rip, self.rport = lport, rip, rport
        self.state = CLOSED
        self.snd_una = self.snd_nxt = _isn()
        self.rcv_nxt = 0
        self.snd_wnd = WINDOW
        self.rx = bytearray()
        self.unacked = []            # [(seq, flags, data, sent_at, tries)]
        self.out = bytearray()       # waiting for window
        self.fin_received = False
        self.error = None
        self.ooo = {}                # out-of-order segments: seq -> data
        self.listener = None
        tcp_conns[(lport, rip, rport)] = self

    # -- output --
    def _segment(self, flags, data=b"", seq=None):
        if seq is None:
            seq = self.snd_nxt
        opts = b""
        if flags & SYN:
            opts = struct.pack("!BBH", 2, 4, MSS)
        header = struct.pack("!HHIIBBHHH", self.lport, self.rport, seq, self.rcv_nxt if flags & ACK else 0,
                             (5 + len(opts) // 4) << 4, flags, max(0, WINDOW - len(self.rx)), 0, 0) + opts
        seg = header + data
        csum = checksum(seg, _pseudo(ip, self.rip, PROTO_TCP, len(seg)))
        seg = seg[:16] + struct.pack("!H", csum) + seg[18:]
        send_ip(self.rip, PROTO_TCP, seg)

    def _emit(self, flags, data=b""):
        seq = self.snd_nxt
        self._segment(flags, data, seq)
        length = len(data) + (1 if flags & (SYN | FIN) else 0)
        if length:
            self.unacked.append([seq, flags, bytes(data), _now(), 1])
            self.snd_nxt = (self.snd_nxt + length) & 0xFFFFFFFF

    def _flush(self):
        while self.out and self.state in (ESTABLISHED, CLOSE_WAIT):
            in_flight = (self.snd_nxt - self.snd_una) & 0xFFFFFFFF
            room = min(self.snd_wnd, WINDOW) - in_flight
            if room <= 0:
                return
            n = min(MSS, room, len(self.out))
            chunk = bytes(self.out[:n])
            self.out = self.out[n:]
            self._emit(ACK | PSH, chunk)

    def _retransmit(self, now):
        for entry in self.unacked:
            seq, flags, data, sent, tries = entry
            if now - sent > RTO_MS * min(tries, 8):
                if tries > 12:
                    self._fail(110)
                    return
                self._segment(flags, data, seq)
                entry[3], entry[4] = now, tries + 1

    def _fail(self, err):
        self.error = err
        self.state = CLOSED
        self._forget()

    def _forget(self):
        tcp_conns.pop((self.lport, self.rip, self.rport), None)

    # -- input --
    def _input(self, seq, ack, flags, wnd, data, opts):
        if flags & RST:
            self._fail(104 if self.state != SYN_SENT else 111)       # ECONNRESET / ECONNREFUSED
            return
        if self.state == SYN_SENT:
            if flags & SYN and flags & ACK and ack == self.snd_nxt:
                self.rcv_nxt = (seq + 1) & 0xFFFFFFFF
                self.snd_una = ack
                self.unacked.clear()
                self.snd_wnd = wnd
                self.state = ESTABLISHED
                self._segment(ACK)
            return
        if self.state == SYN_RCVD and flags & ACK and ack == self.snd_nxt:
            self.state = ESTABLISHED
            self.snd_una = ack
            self.unacked.clear()
            if self.listener:
                self.listener.ready.append(self)
        if flags & ACK:
            if not _seq_lt(self.snd_nxt, ack) and _seq_lt(self.snd_una, ack) or ack == self.snd_una:
                self.snd_una = ack
                self.unacked = [e for e in self.unacked
                                if _seq_lt(ack, (e[0] + len(e[2]) + (1 if e[1] & (SYN | FIN) else 0)) & 0xFFFFFFFF)
                                or ack == e[0]]
                self.snd_wnd = wnd
            if self.state == FIN_WAIT_1 and ack == self.snd_nxt:
                self.state = FIN_WAIT_2
            elif self.state == CLOSING and ack == self.snd_nxt:
                self.state = TIME_WAIT
            elif self.state == LAST_ACK and ack == self.snd_nxt:
                self.state = CLOSED
                self._forget()
                return
        if data or flags & FIN:
            if seq == self.rcv_nxt:
                self.rx += data
                self.rcv_nxt = (self.rcv_nxt + len(data)) & 0xFFFFFFFF
                while self.rcv_nxt in self.ooo:                 # stitch in early arrivals
                    d = self.ooo.pop(self.rcv_nxt)
                    self.rx += d
                    self.rcv_nxt = (self.rcv_nxt + len(d)) & 0xFFFFFFFF
                if flags & FIN:
                    self.rcv_nxt = (self.rcv_nxt + 1) & 0xFFFFFFFF
                    self.fin_received = True
                    if self.state in (ESTABLISHED, SYN_RCVD):
                        self.state = CLOSE_WAIT
                    elif self.state == FIN_WAIT_1:
                        self.state = CLOSING
                    elif self.state == FIN_WAIT_2:
                        self.state = TIME_WAIT
            elif _seq_lt(self.rcv_nxt, seq) and len(self.ooo) < 64 and data:
                self.ooo[seq] = bytes(data)
            self._segment(ACK)
        self._flush()

    # -- the calls behind the socket API --
    def connect(self, timeout_ms=10000):
        self.state = SYN_SENT
        self._emit(SYN)
        deadline = _now() + timeout_ms
        while self.state == SYN_SENT:
            poll()
            if _now() > deadline:
                self._fail(110)
            time.sleep_ms(2)
        if self.state != ESTABLISHED:
            raise OSError(self.error or 111, "connection failed")

    def send(self, data):
        if self.error:
            raise OSError(self.error)
        if self.state not in (ESTABLISHED, CLOSE_WAIT):
            raise OSError(32, "not connected")                 # EPIPE
        with _lock:
            self.out += data
            self._flush()
        # keep the queue bounded: wait while a lot is waiting to go out
        while len(self.out) > 4 * WINDOW and not self.error:
            poll()
            time.sleep_ms(2)
        return len(data)

    def recv(self, n, timeout_ms=None):
        deadline = None if timeout_ms is None else _now() + timeout_ms
        while not self.rx and not self.fin_received and not self.error:
            poll()
            if self.rx or self.fin_received:
                break
            if deadline is not None and _now() >= deadline:
                raise OSError(110, "timed out")
            time.sleep_ms(2)
        if not self.rx and self.error and self.error != 104:
            raise OSError(self.error)
        with _lock:
            chunk = bytes(self.rx[:n])
            was_full = len(self.rx) > WINDOW // 2
            self.rx = self.rx[n:]
            if was_full and self.state in (ESTABLISHED, FIN_WAIT_1, FIN_WAIT_2):
                self._segment(ACK)                           # window update
        return chunk

    def close(self):
        with _lock:
            if self.state in (ESTABLISHED, SYN_RCVD):
                self._flush()
                self.state = FIN_WAIT_1
                self._emit(FIN | ACK)
            elif self.state == CLOSE_WAIT:
                self._flush()
                self.state = LAST_ACK
                self._emit(FIN | ACK)
            elif self.state in (SYN_SENT, LISTEN):
                self.state = CLOSED
                self._forget()
        self.closed_at = _now()


class TCPListener:
    def __init__(self, port, backlog=5):
        if port in tcp_listeners:
            raise OSError(98, "port in use")
        self.port, self.backlog = port, backlog
        self.ready = []
        tcp_listeners[port] = self

    def accept(self, timeout_ms=None):
        deadline = None if timeout_ms is None else _now() + timeout_ms
        while not self.ready:
            poll()
            if self.ready:
                break
            if deadline is not None and _now() >= deadline:
                raise OSError(110, "timed out")
            time.sleep_ms(5)
        return self.ready.pop(0)

    def close(self):
        tcp_listeners.pop(self.port, None)


def _on_tcp(src, seg):
    if len(seg) < 20:
        return
    sport, dport, seq, ack, off, flags, wnd = struct.unpack_from("!HHIIBBH", seg)
    hlen = (off >> 4) * 4
    data = seg[hlen:]
    opts = seg[20:hlen]
    conn = tcp_conns.get((dport, src, sport))
    if conn is None:
        listener = tcp_listeners.get(dport)
        if listener and flags & SYN and not flags & ACK and len(listener.ready) < listener.backlog:
            conn = TCPConn(dport, src, sport)
            conn.listener = listener
            conn.rcv_nxt = (seq + 1) & 0xFFFFFFFF
            conn.snd_wnd = wnd
            conn.state = SYN_RCVD
            conn._emit(SYN | ACK)
        elif not flags & RST:                       # nobody here: reset
            tmp = TCPConn(dport, src, sport)
            tmp.rcv_nxt = (seq + len(data) + (1 if flags & (SYN | FIN) else 0)) & 0xFFFFFFFF
            tmp._segment(RST | ACK, b"", ack if flags & ACK else 0)
            tmp._forget()
        return
    conn._input(seq, ack, flags, wnd, bytes(data), opts)


# ---- the poll loop ----

_last_timers = 0


def poll():
    """Take every frame from the card and run it through the stack."""
    global _last_timers
    if nic is None:
        return
    with _lock:
        for frame in nic.recv():
            stats["rx"] += 1
            stats["rx_bytes"] += len(frame)
            if len(frame) < 14:
                continue
            kind = (frame[12] << 8) | frame[13]
            try:
                if kind == ETH_IP:
                    _on_ip(memoryview(frame)[14:])
                elif kind == ETH_ARP:
                    _on_arp(frame[14:])
            except Exception as e:                 # a bad packet must not kill the stack
                stats["dropped"] += 1
                log.debug("net: dropped packet: %r" % e)
        now = _now()
        if now - _last_timers >= 100:
            _last_timers = now
            for conn in list(tcp_conns.values()):
                conn._retransmit(now)
                if conn.state == TIME_WAIT and now - getattr(conn, "closed_at", now) > 2000:
                    conn.state = CLOSED
                    conn._forget()


def _on_tick():
    """Called by the timer 100 times a second (no thread of its own). If a
    thread is inside the stack right now, skip this tick. A plain callback,
    not a generator: an exception aimed at the interrupted thread (kill,
    Ctrl-C) passes through without stopping the network."""
    # skip if anyone is inside the stack, even half way through entering or
    # leaving it (this callback may be running on that very thread)
    if nic is None or _lock.depth or _lock._lock.locked() or not _lock.try_enter():
        return
    try:
        poll()
    except Exception as e:
        log.warn("net poll: %r" % e)
    finally:
        _lock.__exit__()


# ---- DHCP ----

def dhcp_steps(timeout_ms=6000):
    """DHCP as a generator: each `yield` waits a little. Drive it with
    dhcp() (blocking) or kernel.sched (in the background)."""
    global ip, mask, gateway
    xid = _isn()
    ep = UDPEndpoint(68)
    saved, ip = ip, 0
    try:
        def message(kind, extra=b""):
            body = struct.pack("!BBBBIHHIIII", 1, 1, 6, 0, xid, 0, 0x8000, 0, 0, 0, 0) + mac + bytes(10) + bytes(192)
            opts = b"\x63\x82\x53\x63" + bytes([53, 1, kind]) + extra
            opts += bytes([12, len(hostname)]) + hostname.encode() + b"\x37\x03\x01\x03\x06\xff"
            return body + opts

        def answers(kind):
            for data, _ in ep.queue:
                if len(data) >= 240 and struct.unpack_from("!I", data, 4)[0] == xid:
                    opts = _dhcp_options(data[240:])
                    if opts.get(53, b"\x00")[0] == kind:
                        ep.queue.clear()
                        return struct.unpack_from("!I", data, 16)[0], opts
            ep.queue.clear()
            return None

        got = None
        for attempt in range(3):
            ep.sendto(message(1), 0xFFFFFFFF, 67)                                   # DISCOVER
            deadline = _now() + timeout_ms // 3
            while _now() < deadline:
                yield 20
                got = answers(2)                                                  # OFFER
                if got:
                    break
            if got:
                break
        if not got:
            raise OSError(110, "no DHCP offer")
        offered, opts = got
        server = opts.get(54, b"")
        request = message(3, bytes([50, 4]) + struct.pack("!I", offered) + (bytes([54, 4]) + server if server else b""))
        got = None
        for attempt in range(3):
            ep.sendto(request, 0xFFFFFFFF, 67)                                     # REQUEST
            deadline = _now() + timeout_ms // 3
            while _now() < deadline:
                yield 20
                got = answers(5)                                                  # ACK
                if got:
                    break
            if got:
                break
        if not got:
            raise OSError(110, "no DHCP acknowledgement")
        address, opts = got
        mask = struct.unpack("!I", opts[1])[0] if 1 in opts else 0xFFFFFF00
        gateway = struct.unpack_from("!I", opts[3])[0] if 3 in opts else 0
        if 6 in opts:
            dns_servers[:] = [struct.unpack_from("!I", opts[6], i)[0] for i in range(0, len(opts[6]), 4)]
        ip = address
    finally:
        if not ip:
            ip = saved
        ep.close()


def dhcp(timeout_ms=6000):
    """Ask the network for an address (blocking). Returns it as text."""
    for delay in dhcp_steps(timeout_ms):
        poll()
        time.sleep_ms(delay)
    return ntoa(ip)


def _dhcp_options(raw):
    opts, i = {}, 0
    while i < len(raw) and raw[i] != 255:
        if raw[i] == 0:
            i += 1
            continue
        opts[raw[i]] = bytes(raw[i + 2:i + 2 + raw[i + 1]])
        i += 2 + raw[i + 1]
    return opts


def configure(address, netmask="255.255.255.0", gw=None, dns=None):
    """Static configuration instead of DHCP."""
    global ip, mask, gateway
    ip, mask = aton(address), aton(netmask)
    gateway = aton(gw) if gw else 0
    if dns:
        dns_servers[:] = [aton(dns)]


# ---- DNS ----

_dns_cache = {}
hosts = {"localhost": 0x7F000001}


def resolve(name, timeout_ms=3000):
    """Hostname (or dotted address) -> 32-bit address."""
    if isinstance(name, int):
        return name
    parts = name.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return aton(name)
    if name in hosts:
        return hosts[name]
    hit = _dns_cache.get(name)
    if hit and hit[1] > _now():
        return hit[0]
    if not dns_servers:
        raise OSError(-2, "no DNS server")
    qid = _isn() & 0xFFFF
    query = struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    for label in parts:
        query += bytes([len(label)]) + label.encode()
    query += b"\x00\x00\x01\x00\x01"
    ep = UDPEndpoint()
    try:
        for server in dns_servers * 2:
            ep.sendto(query, server, 53)
            try:
                data, _ = ep.recvfrom(timeout_ms)
            except OSError:
                continue
            if struct.unpack_from("!H", data)[0] != qid:
                continue
            answer = _dns_answer(data)
            if answer:
                _dns_cache[name] = (answer[0], _now() + min(answer[1], 3600) * 1000)
                return answer[0]
            raise OSError(-2, "name not found: " + name)
    finally:
        ep.close()
    raise OSError(-3, "DNS timed out")


def _skip_name(data, i):
    while True:
        n = data[i]
        if n == 0:
            return i + 1
        if n & 0xC0 == 0xC0:
            return i + 2
        i += n + 1


def _dns_answer(data):
    _, flags, qd, an = struct.unpack_from("!HHHH", data)
    if flags & 0xF:
        return None
    i = 12
    for _ in range(qd):
        i = _skip_name(data, i) + 4
    for _ in range(an):
        i = _skip_name(data, i)
        kind, cls, ttl, length = struct.unpack_from("!HHIH", data, i)
        i += 10
        if kind == 1 and length == 4:
            return struct.unpack_from("!I", data, i)[0], ttl
        i += length
    return None


# ---- bring-up ----

def probe_nic():
    from kernel import virtio_net, e1000, rtl8139
    for driver in (virtio_net, e1000, rtl8139):
        try:
            card = driver.probe()
        except Exception as e:
            log.warn("net: %s probe failed: %r" % (driver.__name__, e))
            continue
        if card:
            return card
    return None


def up(use_dhcp=True):
    """Find the card, start the poller, configure an address."""
    global nic, mac, _poller
    if nic is None:
        nic = probe_nic()
        if nic is None:
            raise OSError(19, "no network card")
        mac = nic.mac
        timer.subscribe(_on_tick)
        _poller = _on_tick
    if use_dhcp and not ip:
        if _dhcp_task is not None and _dhcp_task in _sched_tasks():
            deadline = _now() + 10000                    # the boot-time DHCP is still running
            while _dhcp_task in _sched_tasks() and _now() < deadline:
                time.sleep_ms(20)
        if not ip:
            dhcp()
    return ntoa(ip)


def _sched_tasks():
    from kernel import sched
    return sched.tasks


def up_background(on_done=None):
    """Start the card and run DHCP as a background task; returns at once."""
    up(use_dhcp=False)
    from kernel import sched

    def task():
        try:
            yield from dhcp_steps()
            if on_done:
                on_done(None)
        except OSError as e:
            if on_done:
                on_done(e)

    global _dhcp_task
    _dhcp_task = sched.spawn(task, name="dhcp")
    return _dhcp_task


def mac_text():
    return ":".join("%02x" % b for b in mac)


def summary():
    if nic is None:
        return "network: down (no card, or net.up() not called)"
    lines = ["%s  %s  mac %s" % ("eth0", nic.name, mac_text()),
             "  inet %s  netmask %s  gateway %s" % (ntoa(ip), ntoa(mask), ntoa(gateway)),
             "  dns %s" % (", ".join(ntoa(d) for d in dns_servers) or "-"),
             "  rx %d packets (%d bytes)   tx %d packets (%d bytes)   dropped %d" % (
                 stats["rx"], stats["rx_bytes"], stats["tx"], stats["tx_bytes"], stats["dropped"])]
    return "\n".join(lines)


def connections():
    rows = []
    for port in tcp_listeners:
        rows.append("tcp  0.0.0.0:%d  *  LISTEN" % port)
    for c in tcp_conns.values():
        rows.append("tcp  %s:%d  %s:%d  %s" % (ntoa(ip), c.lport, ntoa(c.rip), c.rport, STATE_NAMES[c.state]))
    for port in udp_ports:
        rows.append("udp  0.0.0.0:%d  *" % port)
    return "\n".join(rows)
