"""upstream.py - how the tools talk to the texture CDN: finding an edge address, identifying ourselves, and backing off politely.

The game's host name is usually overridden to loopback while a session runs, so the edge address is looked up through a public resolver
(not the hosts file). The Akamai address below is only a last resort if every lookup fails.
"""
import email.utils, http.client, random, re, socket, subprocess, time
from . import paths
from .version import USER_AGENT

FALLBACK_IPS = ('104.120.129.56',)
PUBLIC_RESOLVERS = ('1.1.1.1', '9.9.9.9')


def headers(extra=None):
    h = {'Host': paths.HOST, 'User-Agent': USER_AGENT}
    if extra: h.update(extra)
    return h


def probe(ip, port=80, timeout=8):
    """True if the edge answers an HTTP request at all (any status)."""
    try:
        c = http.client.HTTPConnection(ip, port, timeout=timeout); c.request('HEAD', '/', headers=headers()); c.getresponse().read(); c.close(); return True
    except Exception: return False


def candidates():
    """Edge addresses in the order to try: system DNS (unless it points at us), public resolvers, then the built-in fallback."""
    out = []
    try:
        for ai in socket.getaddrinfo(paths.HOST, 80, socket.AF_INET, socket.SOCK_STREAM):
            ip = ai[4][0]
            if not ip.startswith('127.') and ip not in out: out.append(ip)
    except OSError: pass
    for res in PUBLIC_RESOLVERS:
        if len(out) >= 3: break
        try:
            txt = subprocess.run(['nslookup', paths.HOST, res], capture_output=True, text=True, errors='replace', timeout=15).stdout
            for ip in re.findall(r'Address(?:es)?:\s+(\d+\.\d+\.\d+\.\d+)', txt.split('Name:')[-1]):
                if ip not in out: out.append(ip)
        except Exception: pass
    for ip in FALLBACK_IPS:
        if ip not in out: out.append(ip)
    return out


def resolve(check=True):
    """-> first usable edge IP. With check=True each candidate is probed; if none answers the first candidate is returned anyway (the caller retries)."""
    c = candidates()
    if check:
        for ip in c:
            if probe(ip): return ip
    return c[0]


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
