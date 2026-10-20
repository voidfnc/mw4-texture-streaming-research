"""upstream.py - how the tools talk to the texture CDN: finding a good edge address, identifying ourselves, and backing off politely.

The game's host name is usually overridden to loopback while a session runs, so the edge address cannot come from the system resolver then. Order of preference:
  1. the system resolver (when the override is off) - your ISP's resolver gives the nearest edge, and the answer is remembered in tools/work/edge_cache.json
  2. that remembered answer (up to a week old)
  3. a direct DNS query (UDP, standard library, no nslookup) to public resolvers
  4. a built-in Akamai address, only as a last resort (it may be far from you, so everything that uses it says so)
`pick()` then downloads a couple of real chunks from each candidate and keeps the fastest one that answers correctly.
"""
import email.utils, http.client, json, os, random, socket, struct, time
from . import paths
from .version import USER_AGENT

FALLBACK_IPS = ('104.120.129.56',)
PUBLIC_RESOLVERS = ('1.1.1.1', '9.9.9.9', '8.8.8.8')
CACHE_MAX_AGE_S = 7 * 86400
MAX_CANDIDATES = 6


def headers(extra=None):
    h = {'Host': paths.HOST, 'User-Agent': USER_AGENT}
    if extra: h.update(extra)
    return h


def probe(ip, port=80, timeout=8):
    """True if the edge answers an HTTP request at all (any status). Link check only; use pick() to judge an edge."""
    try:
        c = http.client.HTTPConnection(ip, port, timeout=timeout); c.request('HEAD', '/', headers=headers()); c.getresponse().read(); c.close(); return True
    except Exception: return False


# ---------------------------------------------------------------- DNS (no nslookup: its output is localised and lists IPv6 first for this host)

def _name_end(buf, i):
    """Offset just after the (possibly compressed) name starting at i."""
    while True:
        n = buf[i]
        if n == 0: return i + 1
        if n & 0xC0 == 0xC0: return i + 2
        i += 1 + n


def dns_a(name, server, timeout=3.0, port=53):
    """IPv4 addresses (A records, following CNAMEs) that `server` returns for `name`. [] on any failure."""
    qid = random.getrandbits(16)
    q = struct.pack('>HHHHHH', qid, 0x0100, 1, 0, 0, 0) + b''.join(bytes([len(p)]) + p.encode('ascii') for p in name.rstrip('.').split('.')) + b'\x00' + struct.pack('>HH', 1, 1)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout); s.sendto(q, (server, port))
            while True:
                buf, _ = s.recvfrom(4096)
                if len(buf) >= 12 and struct.unpack('>H', buf[:2])[0] == qid: break
        return parse_dns_a(buf)
    except (OSError, ValueError, IndexError, struct.error):
        return []


def parse_dns_a(buf):
    _, flags, qd, an, _, _ = struct.unpack('>HHHHHH', buf[:12])
    if flags & 0x000F: return []                                  # rcode != 0
    i = 12
    for _ in range(qd): i = _name_end(buf, i) + 4
    out = []
    for _ in range(an):
        i = _name_end(buf, i); typ, _cls, _ttl, rdlen = struct.unpack('>HHIH', buf[i:i + 10]); i += 10
        if typ == 1 and rdlen == 4: out.append('.'.join(str(b) for b in buf[i:i + 4]))
        i += rdlen
    return out


# ---------------------------------------------------------------- candidates

def _cache_path(): return os.path.join(paths.WORK, 'edge_cache.json')


def remember(ips):
    try:
        os.makedirs(paths.WORK, exist_ok=True)
        with open(_cache_path(), 'w', encoding='utf-8') as f: json.dump(dict(host=paths.HOST, ips=list(ips), time=time.time()), f)
    except OSError: pass


def _cached():
    try:
        with open(_cache_path(), encoding='utf-8') as f: d = json.load(f)
        if d.get('host') == paths.HOST and time.time() - d.get('time', 0) < CACHE_MAX_AGE_S: return [i for i in d.get('ips', []) if isinstance(i, str)]
    except Exception: pass
    return []


def system_edges():
    """IPv4 answers of the system resolver that are not loopback (empty while the hosts override is active)."""
    out = []
    try:
        for ai in socket.getaddrinfo(paths.HOST, 80, socket.AF_INET, socket.SOCK_STREAM):
            ip = ai[4][0]
            if not ip.startswith('127.') and ip not in out: out.append(ip)
    except OSError: pass
    return out


def candidates_info():
    """Edge addresses in the order to try, as [(ip, source)] with source one of system / cache / dns:<resolver> / fallback."""
    if os.environ.get('CCS_EDGE_CANDIDATES'): return [(ip, 'env') for ip in os.environ['CCS_EDGE_CANDIDATES'].split(',') if ip]      # tests only
    out = []
    def add(ip, src):
        if ip not in [o[0] for o in out] and len(out) < MAX_CANDIDATES: out.append((ip, src))
    sysips = system_edges()
    if sysips: remember(sysips)
    for ip in sysips: add(ip, 'system')
    for ip in _cached(): add(ip, 'cache')
    for res in PUBLIC_RESOLVERS:                                   # two from each: different resolvers are mapped to different regions, and measuring picks between them
        for ip in dns_a(paths.HOST, res)[:2]: add(ip, f'dns:{res}')
    for ip in FALLBACK_IPS:
        if ip not in [o[0] for o in out]: out.append((ip, 'fallback'))
    return out


def candidates(): return [ip for ip, _ in candidates_info()]


def is_fallback(ip): return ip in FALLBACK_IPS


def resolve(check=True):
    """-> first usable edge IP (the proxy and Doctor use this; the mirror measures with pick()). With check=True each candidate is probed."""
    c = candidates()
    if check:
        for ip in c:
            if probe(ip): return ip
    return c[0]


# ---------------------------------------------------------------- measuring an edge

def measure_edge(ip, port, tests, timeout=20):
    """Fetch the given real chunks [(path, wire_len)] over one connection. -> dict(ip, ok, secs, mbps, status, error). ok needs HTTP 200 and the exact length."""
    t0 = time.time(); n = 0; status = None
    try:
        c = http.client.HTTPConnection(ip, port, timeout=timeout)
        for path, want in tests:
            c.request('GET', path, headers=headers()); r = c.getresponse(); body = r.read(); status = r.status; n += len(body)
            if r.status != 200 or len(body) != want: c.close(); return dict(ip=ip, ok=False, secs=time.time() - t0, mbps=0.0, status=status, error=f'status={status} len={len(body)} want={want}')
        c.close(); secs = max(time.time() - t0, 1e-6)
        return dict(ip=ip, ok=True, secs=secs, mbps=n * 8 / secs / 1e6, status=status, error=None)
    except Exception as e:
        return dict(ip=ip, ok=False, secs=time.time() - t0, mbps=0.0, status=status, error=str(e) or type(e).__name__)


def pick(cands, port, tests, rounds=1):
    """Measure each candidate IP with `tests`; -> (best_ip or None, [results]). Best = fastest candidate that answered correctly (fallback address loses ties)."""
    res = [measure_edge(ip, port, tests) for ip in cands for _ in range(rounds)]
    ok = [r for r in res if r['ok']]
    if not ok: return None, res
    best = max(ok, key=lambda r: (round(r['mbps'], 1), not is_fallback(r['ip'])))
    return best['ip'], res


def retry_after(hdrs):
    """Seconds to wait from a Retry-After header (delta-seconds or HTTP date); None if absent/unparsable."""
    v = (hdrs or {}).get('Retry-After') if hasattr(hdrs, 'get') else None
    if not v: return None
    try: return max(0.0, float(v))
    except ValueError: pass
    try: return max(0.0, email.utils.parsedate_to_datetime(v).timestamp() - time.time())
    except Exception: return None


def backoff(attempt, base=1.0, cap=60.0):
    """Exponential back-off with jitter: ~base * 2^attempt, capped, +-25 %."""
    d = min(cap, base * 2 ** max(0, attempt)); return d * random.uniform(0.75, 1.25)
