#!/usr/bin/env python3
"""ccsproxy - local forwarding proxy for the public texture CDN, with a size tier and a byte budget.

Why: the game's streamer resolves cod-assets.cdn.callofduty.com as IPv6-only (AF_INET6 + V4MAPPED,
queries logged by DNS-Client); on this IPv4-only machine Windows refuses to connect an IPv6 socket to
a mapped IPv4 address (WinError 10049, no packet ever sent). A hosts entry pointing the name at the
IPv6 loopback lets the unmodified game reach this proxy; the proxy relays to the real Akamai edge.

  python tools/ccsproxy.py [--max-raw-mib 4] [--budget-gib 28] [--upstream-ip A.B.C.D]

* listens on [::1]:80 and 127.0.0.1:80 (needs admin for port 80)
* tier filter: chunks whose decoded size (from the shipped *_cdn.xpak lists) exceeds --max-raw-mib get 404
  (4 MiB ~ <=2048px BC7; use 1 for <=1024px)
* budget: stops serving chunk bodies after --budget-gib of upstream bytes (HTTP 503)
* upstream retry (--retries, default 3, backoff 0.25-2 s) on connection reset, 5xx, or a full-chunk body whose
  length != the wire size encoded in the URL; gives up with 502 (the game re-requests). Client-side aborts
  (game cancelled the request while we wrote) are logged as CLIENT-ABORT, not counted as upstream errors.
* stats line: req ok skip miss err retry cliabort bytes
* logs every request to tools/work/ccsproxy.log; nothing is written to the game folders
"""
import argparse, collections, glob, http.client, json, os, re, socket, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdnxpak
from ccslib import paths, upstream, version            # game folder / work dir come from the GUI settings (tools/work/gui_settings.json), not from hard-coded paths
ROOT = paths.GAME_ROOT
LOG = os.path.join(paths.WORK, 'ccsproxy.log')
HOST = 'cod-assets.cdn.callofduty.com'
PAT = re.compile(r'^/pc/iw9_3/23/([0-9a-f]{2})/([0-9a-f]{16})_([0-9a-f]{8})_([01])$')
lock = threading.Lock(); stat = dict(req=0, ok=0, skip=0, miss=0, err=0, retry=0, cliabort=0, mirror=0, bytes=0, mbytes=0)
RAW = {}
SKIPS = collections.Counter()      # tier-withheld ids -> how often the engine asked again (does a 404 cause a retry storm?)
# observability for the GUI (ccsgui.py): per-tier request histogram + last requests, exposed via GET /__ccs/stats and --stats-json
TIERS = [('<=64K', 2**16), ('<=256K', 2**18), ('<=1M', 2**20), ('<=4M', 2**22), ('<=8M', 2**23), ('<=16M', 2**24), ('>16M', None)]
HIST = {t[0]: 0 for t in TIERS}; RECENT = collections.deque(maxlen=50); SVC = collections.deque(maxlen=2000); T0 = time.time(); ARGS = {}
def tier_of(raw):
    if raw is None: return 'unknown'
    for n, lim in TIERS:
        if lim is None or raw <= lim: return n
def record(path, cid, raw, source, status, nbytes, ms=None):
    with lock:
        t = tier_of(raw)
        if ms is not None: SVC.append(ms)
        if t in HIST: HIST[t] += 1
        RECENT.append(dict(t=round(time.time(), 2), id=f'{cid:016x}' if cid is not None else None, raw=raw, tier=t, src=source, status=status, bytes=nbytes, ms=None if ms is None else round(ms, 1)))
def svc_summary():
    v = sorted(SVC)
    return dict(n=len(v), avg=round(sum(v) / len(v), 2), p95=round(v[int(len(v) * .95)], 2), max=round(v[-1], 2)) if v else dict(n=0, avg=0, p95=0, max=0)

def skip_summary():
    n = sum(SKIPS.values())
    return dict(n=n, unique=len(SKIPS), repeat=n - len(SKIPS), top=[[f'{i:016x}', c] for i, c in SKIPS.most_common(5)])

def snapshot():
    with lock:
        return dict(pid=os.getpid(), skips=skip_summary(), started=T0, now=time.time(), stat=dict(stat), hist=dict(HIST), recent=list(RECENT), svc_ms=svc_summary(), args=ARGS, mirror_ids=len(MKEY), index_ids=len(RAW))
def write_stats(path):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: json.dump(snapshot(), f)
    os.replace(tmp, path)
MKEY = {}      # id -> (etag, cod_key) from mirror/index.sqlite when --origin is used

def load_mirror(origin):
    import sqlite3
    db = os.path.join(origin, 'index.sqlite')
    if not os.path.isfile(db): log(f"mirror: no index in {origin} yet - every chunk comes from the CDN until a mirror is built"); return      # a first-time user has no mirror: not an error
    c = sqlite3.connect(db)
    try:
        for sid, et, ck in c.execute('select id, etag, cod_key from chunks where status=1'):
            MKEY[sid & (2**64 - 1)] = ((et or '').split(':')[0] or None, ck)
    except sqlite3.Error as e: log(f"mirror: index unreadable ({e}) - chunks that are not on disk come from the CDN")
    finally: c.close()
    log(f"mirror: {len(MKEY)} stored chunks indexed from {origin}")

def log(m):
    l = f"{time.strftime('%H:%M:%S')} {m}"
    with lock:
        print(l, flush=True); open(LOG, 'a', encoding='utf-8').write(l + '\n')

def load_index():
    for fn in glob.glob(os.path.join(ROOT, 'cod26', '*_cdn.xpak')) + glob.glob(os.path.join(ROOT, 'sp26', '*_cdn.xpak')):
        for r in cdnxpak.parse(fn):
            RAW[r['id']] = r['raw']
    log(f"index: {len(RAW)} chunk ids")

class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *a): pass
    def reply(self, code, body=b'', ctype='text/plain', extra=()):
        self.send_response(code); self.send_header('Content-Length', str(len(body))); self.send_header('Content-Type', ctype)
        for k, v in extra: self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD': self.wfile.write(body)
    def do_HEAD(self): self.do_GET()
    def ms(self): return (time.perf_counter() - self._t0) * 1000
    def do_GET(self):
        self._t0 = time.perf_counter()
        a = self.server.args; path = self.path.split('?')[0]
        if path == '/__ccs/stats':      # GUI status endpoint (loopback listeners only; never forwarded)
            return self.reply(200, json.dumps(snapshot()).encode(), 'application/json')
        with lock: stat['req'] += 1
        m = PAT.match(path); note = ''
        if m:      # detail level: the cap applies to the mirror too (a 4K mirror must not hand out >cap chunks to a 1440p-class setting)
            cid = int(m.group(2), 16); raw = RAW.get(cid)
            if raw is not None and raw > a.max_raw_mib * 2**20:
                with lock: stat['skip'] += 1; SKIPS[cid] += 1
                record(path, cid, raw, 'skip', 404, 0, ms=self.ms()); log(f"SKIP-TIER {self.command} {path} raw={raw/2**20:.1f}MiB"); return self.reply(404)
        if m and a.origin and not self.headers.get('Range'):
            # offline origin: serve the verbatim CDN object (+ stored ETag / x-amz-meta-cod-key) from the local mirror
            cid = int(m.group(2), 16); wire = int(m.group(3), 16)
            p = os.path.join(a.origin, 'objects', m.group(1), f'{cid:016x}_{wire:08x}_{m.group(4)}')
            try:
                if os.path.getsize(p) == wire:
                    body = open(p, 'rb').read() if self.command == 'GET' else b''
                    et, ck = MKEY.get(cid, (None, None)); extra = [('Accept-Ranges', 'bytes')]
                    if et: extra.append(('ETag', f'"{et}"'))
                    if ck: extra.append(('x-amz-meta-cod-key', ck))
                    if self.command == 'HEAD': self.send_response(200); self.send_header('Content-Length', str(wire)); [self.send_header(k, v) for k, v in extra]; self.end_headers()
                    else: self.reply(200, body, 'application/octet-stream', extra)
                    with lock: stat['mirror'] += 1; stat['ok'] += 1; stat['mbytes'] += wire if self.command == 'GET' else 0
                    record(path, cid, RAW.get(cid), 'mirror', 200, wire, ms=self.ms())
                    return log(f"{self.command} {path} -> 200 {wire}B MIRROR")
            except OSError:
                pass            # not in the mirror -> fall through to the upstream
            except Exception as e:
                with lock: stat['cliabort'] += 1
                return log(f"CLIENT-ABORT {path}: {e}")
        if m:
            if stat['bytes'] > a.budget_gib * 2**30:
                record(path, cid, raw, 'budget', 503, 0, ms=self.ms()); log(f"BUDGET exhausted {stat['bytes']/2**30:.2f} GiB"); return self.reply(503)
            if getattr(a, 'offline', False):      # mirror-only test mode: a mirror gap must show up as a 404, never as a silent upstream fetch
                with lock: stat['miss'] += 1
                record(path, cid, raw, 'offline-miss', 404, 0, ms=self.ms()); log(f"MISS-OFFLINE {self.command} {path} raw={raw}"); return self.reply(404)
            note = f"raw={raw}"
        # chunk objects: the URL carries the wire size, so a full (non-Range) body must match it exactly
        want = int(m.group(3), 16) if m and not self.headers.get('Range') and self.command == 'GET' else None
        hdr = upstream.headers({'Connection': 'close'})
        if self.headers.get('Range'): hdr['Range'] = self.headers['Range']
        r = body = last = None
        for attempt in range(1, a.retries + 2):
            try:
                c = http.client.HTTPConnection(a.upstream_ip, a.upstream_port, timeout=30)
                c.request(self.command, path, headers=hdr); r = c.getresponse(); body = r.read(); c.close()
                if r.status >= 500 or (want is not None and r.status == 200 and len(body) != want):
                    raise IOError(f"bad upstream reply status={r.status} len={len(body)} want={want}")
                break
            except Exception as e:
                last = e; r = None
                with lock: stat['retry'] += 1
                log(f"RETRY {attempt}/{a.retries + 1} {path}: {e}")
                time.sleep(min(0.25 * 2 ** (attempt - 1), 2.0))
        if r is None:
            with lock: stat['err'] += 1
            if m: record(path, int(m.group(2), 16), RAW.get(int(m.group(2), 16)), 'err', 502, 0, ms=self.ms())
            log(f"ERR-UPSTREAM {path}: {last} (gave up after {a.retries + 1} tries)")
            try: self.reply(502)
            except Exception: pass
            return
        # the engine's header table includes `x-amz-meta-cod-key:` (per-chunk 8-byte key sent by the CDN); the old proxy
        # dropped it, so forward every x-amz-meta-* header plus the validators/cache headers unchanged
        extra = [(k, v) for k, v in r.getheaders()
                 if k.lower() in ('content-range', 'etag', 'last-modified', 'accept-ranges', 'cache-control', 'expires')
                 or k.lower().startswith('x-amz-meta-')]
        try:
            self.reply(r.status, body, r.getheader('Content-Type', 'application/octet-stream'), extra)
        except Exception as e:
            # the game closed/cancelled the request while we were writing: not an upstream fault
            with lock: stat['cliabort'] += 1
            log(f"CLIENT-ABORT {path}: {e}")
            self.close_connection = True
            return
        with lock:
            stat['bytes'] += len(body) if self.command == 'GET' else 0
            if r.status in (200, 206): stat['ok'] += 1
            else: stat['miss'] += 1
        if m: record(path, int(m.group(2), 16), RAW.get(int(m.group(2), 16)), 'upstream', r.status, len(body), ms=self.ms())
        log(f"{self.command} {path} -> {r.status} {len(body)}B {note} range={self.headers.get('Range','-')} total={stat['bytes']/2**30:.3f}GiB")

class S6(ThreadingHTTPServer):
    address_family = socket.AF_INET6; daemon_threads = True
    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1); super().server_bind()
class S4(ThreadingHTTPServer): daemon_threads = True

if __name__ == '__main__':
    ap = argparse.ArgumentParser(epilog=version.NOTICE); ap.add_argument('--version', action='version', version=version.USER_AGENT)
    ap.add_argument('--max-raw-mib', type=float, default=4096); ap.add_argument('--budget-gib', type=float, default=120)
    ap.add_argument('--retries', type=int, default=3, help='upstream retries per request (reset/5xx/short body)')
    ap.add_argument('--upstream-port', type=int, default=80)
    ap.add_argument('--origin', help='mirror dir (e.g. mirror/): serve stored chunks from disk first, upstream only for misses')
    ap.add_argument('--upstream-ip')
    ap.add_argument('--offline', action='store_true', help='mirror-only: chunks missing from --origin get 404 instead of an upstream fetch')
    ap.add_argument('--port', type=int, default=80, help='listen port on ::1 and 127.0.0.1 (80 for the game; other values for tests)')
    ap.add_argument('--log', help='log file (default tools/work/ccsproxy.log)')
    ap.add_argument('--stats-json', help='write a stats snapshot here every 2 s (atomic); also served at GET /__ccs/stats')
    a = ap.parse_args()
    if a.log: LOG = os.path.abspath(a.log)
    os.makedirs(os.path.dirname(LOG), exist_ok=True); ARGS = {k: v for k, v in vars(a).items()}
    log(f"START {time.strftime('%Y-%m-%d')} pid={os.getpid()} args={' '.join(sys.argv[1:])}")   # run boundary + date for ccsreport
    if not a.upstream_ip: a.upstream_ip = upstream.resolve(check=False)      # public-resolver lookup (the hosts override points the name at us)
    if a.origin: a.origin = os.path.abspath(a.origin); load_mirror(a.origin)
    load_index(); log(f"upstream {a.upstream_ip}  tier<={a.max_raw_mib}MiB  budget={a.budget_gib}GiB")
    for cls, addr in ((S6, ('::1', a.port)), (S4, ('127.0.0.1', a.port))):
        try: srv = cls(addr, H)
        except OSError as e: log(f"BIND-FAIL {addr}: {e}"); sys.exit(2)
        srv.args = a
        threading.Thread(target=srv.serve_forever, daemon=True).start(); log(f"listening {addr}")
    log(f"READY pid={os.getpid()} port={a.port}")
    last = time.time()
    while True:
        time.sleep(2)
        if a.stats_json:
            try: write_stats(a.stats_json)
            except Exception as e: log(f"stats-json write failed: {e}")
        if time.time() - last >= 60: last = time.time(); log(f"stats {stat}")
