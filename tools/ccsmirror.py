#!/usr/bin/env python3
"""ccsmirror - resumable offline mirror of the streaming chunks from the public texture CDN (SP set by default, whole pack optional).

  python tools/ccsmirror.py init   [--scope sp|all|custom] [--packages sp,common,mp,dmz,hq,boot]   # load chunk lists into mirror/index.sqlite
  python tools/ccsmirror.py plan   [--scope ..] [--level standard|high|ultra | --tier MiB] [--line-mbps N] [--json]   # size / ETA estimate, no network
  python tools/ccsmirror.py run    [--scope ..] [--level ..|--tier MiB] [--workers 4] [--budget-gib N|0=auto] [--min-free-gib 40]
                                   [--limit-mbps N] [--daily-gib N] [--link-wait-s N]
  python tools/ccsmirror.py status [--json]
  python tools/ccsmirror.py verify [--n 200 | --all] [--fix] [--progress-json PATH]    # re-check stored objects (size + md5 vs ETag); --fix resets bad ones to pending
  python tools/ccsmirror.py prune  --above-tier MiB [--yes] [--json]                    # delete stored objects above a detail level (dry run without --yes)
  python tools/ccsmirror.py retry-failed                                                # failed (status 2) -> pending
  run extras: --progress-json PATH (live JSON for the GUI), --stop-file PATH (create it to pause cleanly; default mirror/STOP)

Scope  = which chunk lists (packages) are mirrored; Level = max raw (decoded) chunk size: standard 4 MiB (1440p class, 2048^2 BC7), high 8 MiB, ultra = no cap (4K class).
         Without --scope, `run` works on every row already in the index (legacy behaviour).
Layout:   mirror/objects/{id&ff:02x}/{id:016x}_{wire:08x}_{flag}     (verbatim CDN object bytes)
          mirror/index.sqlite   chunks(id, wire, raw, flag, prio, status, etag, cod_key, ts, pkgs) + meta(key, value)
Priority: 0 = ids the game already requested (from tools/work/ccsproxy.log), 1 = raw <= 4 MiB (1440p class), 2 = rest (4K class)  -> a 1440p-class set is always complete first.
Safety:   verifies len == wire size (from the URL) and md5 == ETag (ETag may be "md5" or legacy "md5:timestamp"; multipart "x-N" is skipped); stops on --budget-gib or
          when free disk < --min-free-gib; <= --workers connections and a request-rate cap (50 req/s by default) far under the CDN's published 2000 req/s. Every request carries a User-Agent that names this tool;
          HTTP 429 / 503 (with Retry-After) makes all workers back off.
          --limit-mbps shares one bandwidth cap over all workers; --daily-gib pauses (state quota-wait) until local midnight; a dead link is waited out (state offline-wait),
          not recorded as failed chunks.
Source:   public unauthenticated CDN host only; the hosts override is bypassed by connecting to the edge IP with a Host header.
"""
import argparse, collections, glob, hashlib, http.client, json, os, random, re, shutil, socket, sqlite3, subprocess, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ccslib import paths, pack, upstream, version      # locations come from the GUI settings (Game tab), not from hard-coded paths
ROOT = paths.GAME_ROOT
HOST = 'cod-assets.cdn.callofduty.com'
MIR = paths.MIRROR; OBJ = os.path.join(MIR, 'objects'); DB = os.path.join(MIR, 'index.sqlite')
LOG = os.path.join(paths.WORK, 'ccsmirror.log')
lock = threading.Lock()

def log(m, echo=True):
    l = f"{time.strftime('%H:%M:%S')} {m}"
    with lock:
        if echo: print(l, flush=True)
        with open(LOG, 'a', encoding='utf-8') as f: f.write(l + '\n')

def opath(i, wire, flag): return os.path.join(OBJ, f'{i & 0xff:02x}', f'{i:016x}_{wire:08x}_{flag}')
def signed(i): return i - 2**64 if i >= 2**63 else i

SCHEMA = 'create table if not exists chunks(id integer primary key, wire integer, raw integer, flag integer, prio integer, status integer default 0, etag text, cod_key text, ts real, pkgs integer)'

def ensure_schema(c):
    """Create / migrate: v1 mirrors (no pkgs column, no meta table) keep every row and status."""
    c.execute(SCHEMA)
    if 'pkgs' not in {r[1] for r in c.execute('pragma table_info(chunks)')}: c.execute('alter table chunks add column pkgs integer')
    c.execute('create table if not exists meta(key text primary key, value text)')
    c.execute('create index if not exists ix_pending on chunks(status, prio, id)'); c.commit()

def db():
    os.makedirs(MIR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=60, check_same_thread=False); c.execute('pragma journal_mode=wal'); c.execute('pragma synchronous=normal'); ensure_schema(c); return c

def meta_get(c, k, d=None):
    r = c.execute('select value from meta where key=?', (k,)).fetchone(); return r[0] if r else d

def meta_set(c, k, v): c.execute('insert or replace into meta(key, value) values (?,?)', (k, str(v)))

def served_ids():
    served = set(); lg = os.path.join(paths.WORK, 'ccsproxy.log')
    if os.path.exists(lg):
        for l in open(lg, encoding='utf-8', errors='replace'):
            m = re.search(r'GET \S+/([0-9a-f]{16})_\S+ -> 200', l)
            if m: served.add(int(m.group(1), 16))
    return served

def load_lists(c, mask):
    """Insert the chunk lists of the packages in `mask` (new ids get a priority, known ids keep status and only gain package bits); adopt objects already on disk."""
    os.makedirs(OBJ, exist_ok=True)
    cat = pack.catalogue(mask, ROOT); served = served_ids()
    new = [(signed(i), c_['wire'], c_['raw'], c_['flag'], 0 if i in served else (1 if c_['raw'] <= 4 * 2**20 else 2), c_['bits']) for i, c_ in cat.items()]
    c.executemany('insert or ignore into chunks(id, wire, raw, flag, prio, pkgs) values (?,?,?,?,?,?)', new)
    c.executemany('update chunks set pkgs = coalesce(pkgs, 0) | ? where id = ?', [(c_['bits'], signed(i)) for i, c_ in cat.items()])
    c.commit()
    ad = 0
    for sid, wire, flag in c.execute('select id, wire, flag from chunks where status=0').fetchall():
        i = sid & (2**64 - 1); p = opath(i, wire, flag)
        if os.path.exists(p) and os.path.getsize(p) == wire:
            c.execute('update chunks set status=1, ts=? where id=?', (time.time(), sid)); ad += 1
    meta_set(c, 'loaded', int(meta_get(c, 'loaded', 0)) | mask); meta_set(c, 'lists', json.dumps(pack.fingerprint(ROOT))); c.commit()
    return len(cat), len(served & set(cat)), ad

def ensure_loaded(c, mask):
    if mask & ~int(meta_get(c, 'loaded', 0)):
        n, s, ad = load_lists(c, mask); log(f'lists loaded for scope mask {mask}: {n} ids, prio0(served)={s}, adopted existing={ad}')

def args_scope(a):
    """-> (scope name or None, packages list/None, mask or None)"""
    sc = getattr(a, 'scope', None)
    if not sc: return None, None, None
    pk = [x for x in (a.packages or '').split(',') if x] if getattr(a, 'packages', None) else None
    if sc == 'custom' and not pk: raise SystemExit('--scope custom needs --packages')
    return sc, pk, pack.scope_mask(sc, pk)

def args_tier(a):
    if getattr(a, 'level', None): return pack.level_mib(a.level)
    return a.tier

def cmd_init(a):
    sc, pk, mask = args_scope(a); sc = sc or 'sp'; mask = mask or pack.scope_mask('sp')
    c = db(); n, s, ad = load_lists(c, mask); meta_set(c, 'scope', sc); c.commit()
    miss = [k for k in pack.scope_packages(sc, pk) if not pack.available().get(k)]
    log(f"init: scope={sc} {n} ids from {', '.join(pack.scope_packages(sc, pk))}, prio0(served)={s}, adopted existing={ad}" + (f"; chunk lists missing for: {', '.join(miss)}" if miss else ''))

def cmd_plan(a):
    sc, pk, mask = args_scope(a)
    pl = pack.plan(sc or 'sp', pk, a.level or pack.level_of_mib(a.tier) or a.tier, line_mbps=a.line_mbps)
    if a.json: print(json.dumps(pl)); return
    print(f"scope {pl['scope']} ({', '.join(pl['packages'])}), level {pl['level']} (<= {pl['tier_mib']:g} MiB raw)\n  " + pack.describe(pl))
    for lv, b in pl['levels'].items(): print(f"  {lv:9s} {b['chunks']:7,} chunks {b['gib']:7.2f} GiB   stored {b['stored']:7,} ({b['stored_gib']:7.2f} GiB)   to download {b['pending']:7,} ({b['pending_gib']:7.2f} GiB)")

RECHECK_S = 180      # seconds between edge re-measurements by the stall watchdog


def stalled(elapsed, since_check, line_mbps, limit_mbps, rate_mbps, throttled, state, recheck_s=RECHECK_S):
    """True when the run is far below the user's line speed for reasons the tool can influence (not a cap, a quota, a lost link or a 429)."""
    if not line_mbps or line_mbps <= 0 or elapsed < 90 or since_check < recheck_s or throttled or state != 'running': return False
    if limit_mbps and limit_mbps <= line_mbps * 0.2: return False
    return rate_mbps < line_mbps * 0.2


def edge_tests(rows):
    """[(path, wire_len)] for pending chunk rows: real objects used to time an edge."""
    return [(f"/pc/iw9_3/23/{(sid & (2**64 - 1)) & 0xff:02x}/{sid & (2**64 - 1):016x}_{wire:08x}_{flag}", wire) for sid, wire, raw, flag, prio in rows]

def choose_edge(port, tests):
    """Measure every candidate edge address with real chunks. -> (ip, note, passed). `note` is non-empty when the address is a poor choice (built-in fallback, or nothing passed)."""
    info = upstream.candidates_info(); src = dict(info); cands = [ip for ip, _ in info]
    if not tests: return cands[0], ('built-in fallback address (may be far from you)' if upstream.is_fallback(cands[0]) else ''), False
    best, res = upstream.pick(cands, port, tests)
    for r in res: log(f"edge test {r['ip']} ({src[r['ip']]}): " + (f"{r['mbps']:.1f} Mbit/s in {r['secs']:.2f} s" if r['ok'] else f"rejected ({r['error']})"))
    if best is None: return cands[0], 'no edge address passed the test, using the first candidate', False
    return best, ('built-in fallback address (may be far from you)' if upstream.is_fallback(best) else ''), True


class Rate:
    def __init__(self, per_s): self.per = 1.0 / per_s; self.t = time.time(); self.l = threading.Lock()
    def wait(self):
        with self.l:
            now = time.time(); self.t = max(self.t + self.per, now); d = self.t - now
        if d > 0: time.sleep(d)

class Limiter:
    """One shared bandwidth cap (bytes/s) for all workers: each read reserves its slice of the timeline and waits for it."""
    def __init__(self, bps, stop): self.bps = float(bps); self.t = time.time(); self.l = threading.Lock(); self.stop = stop
    def take(self, n):
        with self.l:
            now = time.time(); self.t = max(self.t, now) + n / self.bps; d = self.t - now
        if d > 0: self.stop.wait(d)

class Quota:
    """Daily download quota (bytes), reset at local midnight, persisted in the index so a restart does not forget today's usage."""
    def __init__(self, limit, c=None, clock=time.time):
        self.limit = limit; self.clock = clock; self.l = threading.Lock(); self.day = self.today(); self.used = 0
        if c is not None and meta_get(c, 'quota_day') == self.day: self.used = int(meta_get(c, 'quota_used', 0))
    def today(self): return time.strftime('%Y-%m-%d', time.localtime(self.clock()))
    def roll(self):
        with self.l:
            d = self.today()
            if d != self.day: self.day = d; self.used = 0; return True
        return False
    def add(self, n):
        with self.l: self.used += n
    def exceeded(self):
        with self.l: return self.limit > 0 and self.used >= self.limit
    def save(self, c): meta_set(c, 'quota_day', self.day); meta_set(c, 'quota_used', self.used)
    def resume_at(self):
        t = time.localtime(self.clock()); return time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, 0, 0, 5, 0, 0, -1))

class BadObject(Exception): pass          # reply arrived but is wrong (status / length / md5): an object problem, not a link problem

class Throttled(Exception):               # 429 / 503: the CDN asks us to slow down
    def __init__(self, after): super().__init__('throttled'); self.after = after

def read_body(r, lim):
    if lim is None: return r.read()
    parts = []
    while True:
        b = r.read(65536)
        if not b: break
        parts.append(b); lim.take(len(b))
    return b''.join(parts)

def cmd_run(a):
    if not version.bulk_acknowledged():
        if a.accept_notice: version.record_bulk_ack()
        else:
            print(version.BULK_NOTICE + '\n\nRe-run with --accept-notice to confirm (asked once per version).'); sys.exit(3)
    c = db(); sc, pk, mask = args_scope(a); tier = args_tier(a)
    if mask: ensure_loaded(c, mask)
    elif int(meta_get(c, 'loaded', 0)) == 0 and c.execute('select count(*) from chunks').fetchone()[0] == 0: ensure_loaded(c, pack.scope_mask('sp'))
    where = 'status!=1 and raw<=?'; prm = [tier * 2**20]
    if mask: where += ' and (pkgs & ?) != 0'; prm.append(mask)
    rows = c.execute(f'select id, wire, raw, flag, prio from chunks where {where} order by prio, id', prm).fetchall()
    edge = dict(ip=a.upstream_ip, note='', checked=time.time())
    if not edge['ip']:
        trows = c.execute(f'select id, wire, raw, flag, prio from chunks where {where} and status=0 order by abs(wire - 262144) limit 2', prm).fetchall() if rows else []
        edge['ip'], edge['note'], _ = choose_edge(a.upstream_port, edge_tests(trows))
        if edge['note']: log('WARNING: ' + edge['note'] + f" - {edge['ip']}")
    ip = edge['ip']
    qgib = sum(r[1] for r in rows) / 2**30; budget = a.budget_gib if a.budget_gib and a.budget_gib > 0 else qgib * 1.02 + 0.1
    log(f'run: upstream={ip} workers={a.workers} scope={sc or "index"} tier<={tier:g}MiB budget={budget:.1f}GiB{" (auto)" if budget != a.budget_gib else ""} min-free={a.min_free_gib}GiB'
        f'{f" limit={a.limit_mbps:g}Mbps" if a.limit_mbps else ""}{f" daily={a.daily_gib:g}GiB" if a.daily_gib else ""}')
    log(f'queue: {len(rows)} chunks, {qgib:.2f} GiB wire')
    q = list(reversed(rows)); stat = dict(ok=0, fail=0, bytes=0, retry=0, throttled=0); stop = threading.Event(); rate = Rate(a.max_rps)
    lim = Limiter(a.limit_mbps * 1e6 / 8, stop) if a.limit_mbps and a.limit_mbps > 0 else None
    quota = Quota(int(a.daily_gib * 2**30), c) if a.daily_gib and a.daily_gib > 0 else None
    t0 = time.time(); dbl = threading.Lock(); total_q = len(q); linklock = threading.Lock(); link = dict(down_since=None); final = dict(state=None)
    stopf = a.stop_file or os.path.join(MIR, 'STOP')
    try: os.remove(stopf)                                   # stale pause request from a previous run
    except OSError: pass
    def free(): return shutil.disk_usage(MIR if os.path.isdir(MIR) else ROOT).free / 2**30     # the mirror may live on another drive than the game
    def probe(): return upstream.probe(edge['ip'], a.upstream_port)
    hist = collections.deque(maxlen=400)         # (time, bytes) once a second: the rolling speed and the stall watchdog
    def now_rate(window=30):
        if len(hist) < 2: return 0.0
        t1, b1 = hist[-1]; t0_, b0 = next(((t, b) for t, b in hist if t1 - t <= window), hist[0])
        return (b1 - b0) / max(t1 - t0_, 1e-6)
    pen = dict(until=0.0)                       # shared slow-down: set when the CDN answers 429 / 503, honoured by every worker before its next request
    def wait_link():
        """The upstream stopped answering: wait (no chunk is marked failed) until it is back, --link-wait-s expires, or STOP."""
        with linklock:
            k = 0
            while not stop.is_set():
                if probe():
                    if link['down_since']: log(f"LINK UP after {time.time() - link['down_since']:.0f} s"); link['down_since'] = None
                    return True
                if link['down_since'] is None: link['down_since'] = time.time(); log('LINK DOWN - waiting (chunks stay pending)')
                if a.link_wait_s and time.time() - link['down_since'] > a.link_wait_s:
                    log(f'link down for more than {a.link_wait_s:g} s - pausing the run'); final['state'] = 'offline'; stop.set(); return False
                for _ in range(min(5 * 2 ** k, 30)):
                    if stop.is_set() or os.path.exists(stopf): break
                    time.sleep(1)
                k += 1
            return False
    def state():
        if stop.is_set(): return final['state'] or 'stopping'
        if link['down_since']: return 'offline-wait'
        if quota and quota.exceeded(): return 'quota-wait'
        return 'running'
    def progress(st):
        if not a.progress_json: return
        el = max(time.time() - t0, 1e-6)
        try:
            tmp = a.progress_json + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(dict(state=st, pid=os.getpid(), started=t0, now=time.time(), queued=total_q, left=len(q), ok=stat['ok'], fail=stat['fail'], retry=stat['retry'], throttled=stat['throttled'],
                               bytes=stat['bytes'], mibps=stat['bytes'] / el / 2**20, mibps_now=now_rate() / 2**20, edge=edge['ip'], edge_note=edge['note'], free_gib=free(), budget_gib=budget, workers=a.workers, scope=sc, tier_mib=tier,
                               limit_mbps=a.limit_mbps or 0, daily_gib=a.daily_gib or 0, used_today_gib=(quota.used / 2**30) if quota else None,
                               resume_at=quota.resume_at() if quota and quota.exceeded() else None), f)
            os.replace(tmp, a.progress_json)
        except OSError: pass
    def worker(k):
        conn = None; conn_ip = None
        while not stop.is_set():
            while quota and quota.exceeded() and not stop.is_set(): time.sleep(0.5)
            if stop.is_set(): return
            with lock:
                if not q: return
                item = q.pop()
            sid, wire, raw, flag, prio = item
            i = sid & (2**64 - 1); p = opath(i, wire, flag); os.makedirs(os.path.dirname(p), exist_ok=True)
            path = f'/pc/iw9_3/23/{i & 0xff:02x}/{i:016x}_{wire:08x}_{flag}'
            good = None; netfail = False; att = 0; throttles = 0
            while att < a.retries + 1:
                att += 1
                try:
                    d = pen['until'] - time.time()
                    if d > 0: stop.wait(d)
                    rate.wait()
                    if conn is not None and conn_ip != edge['ip']:      # the edge was switched by the watchdog
                        try: conn.close()
                        except Exception: pass
                        conn = None
                    if conn is None: conn_ip = edge['ip']; conn = http.client.HTTPConnection(conn_ip, a.upstream_port, timeout=60)
                    conn.request('GET', path, headers=upstream.headers()); r = conn.getresponse()
                    if r.status in (429, 503): r.read(); raise Throttled(upstream.retry_after(r.headers))
                    body = read_body(r, lim)
                    if r.status == 404: good = ('404', None, None); break
                    et = (r.getheader('ETag') or '').strip('"').split(':')[0]   # legacy objects use "md5:timestamp"
                    if r.status != 200 or len(body) != wire: raise BadObject(f'status={r.status} len={len(body)} want={wire}')
                    if et and '-' not in et and hashlib.md5(body).hexdigest() != et: raise BadObject('md5 != ETag')
                    good = ('ok', et, r.getheader('x-amz-meta-cod-key'), body); netfail = False; break
                except Throttled as e:
                    att -= 1; throttles += 1
                    try: conn.close()
                    except Exception: pass
                    conn = None
                    d = min(300.0, max(1.0, e.after if e.after is not None else upstream.backoff(throttles)))
                    with lock:
                        stat['throttled'] += 1; first = time.time() >= pen['until']; pen['until'] = max(pen['until'], time.time() + d)
                    if first: log(f'CDN asked to slow down (429/503): all workers wait {d:.0f} s')
                    if throttles > 30: log(f'FAIL {path}: throttled 30 times in a row'); break
                    continue
                except Exception as e:
                    netfail = not isinstance(e, BadObject)
                    with lock: stat['retry'] += 1
                    try: conn.close()
                    except Exception: pass
                    conn = None
                    if att > a.retries: log(f'FAIL {path}: {e}')
                    else: time.sleep(min(0.5 * 2 ** (att - 1), 8))
            if good is None and netfail and not probe():
                with lock: q.append(item)                       # the line is down, not the object: keep it pending and wait for the link
                wait_link(); continue
            if good and good[0] == 'ok':
                tmp = p + '.part'
                with open(tmp, 'wb') as f: f.write(good[3])
                os.replace(tmp, p)
                with dbl: c.execute('update chunks set status=1, etag=?, cod_key=?, ts=? where id=?', (good[1], good[2], time.time(), sid))
                with lock: stat['ok'] += 1; stat['bytes'] += wire
                if quota: quota.add(wire)
            else:
                with dbl: c.execute('update chunks set status=? where id=?', (3 if good else 2, sid))   # 3 = 404, 2 = failed
                with lock: stat['fail'] += 1
    def watchdog():
        """Far below the user's line speed for a minute (and not because of a cap, a quota, a link loss or a 429): measure the edges again, switch if one is clearly better."""
        now = time.time()
        if a.upstream_ip or not stalled(now - t0, now - edge['checked'], a.line_mbps, a.limit_mbps, now_rate(60) * 8 / 1e6, now < pen['until'], state()): return
        edge['checked'] = now; cur = edge['ip']
        log(f"slow: {now_rate(60) * 8 / 1e6:.1f} Mbit/s over the last minute (line {a.line_mbps:g}) - measuring the edge addresses again")
        trows = c.execute(f'select id, wire, raw, flag, prio from chunks where {where} and status=0 order by abs(wire - 262144) limit 2', prm).fetchall()
        best, note, passed = choose_edge(a.upstream_port, edge_tests(trows))
        if passed and best != cur: log(f'switching edge {cur} -> {best}'); edge['ip'], edge['note'] = best, note
        else: log(f'staying on {cur}')
    ths = [threading.Thread(target=worker, args=(k,), daemon=True) for k in range(a.workers)]
    for t in ths: t.start()
    last = 0; qstate = None
    try:
        n_tick = 0
        while any(t.is_alive() for t in ths):
            time.sleep(1); n_tick += 1; hist.append((time.time(), stat['bytes'])); watchdog(); progress(state())
            if quota and quota.roll(): log('new day - daily quota reset')
            s = state()
            if s != qstate and {s, qstate} == {'quota-wait', 'running'}: log('daily quota reached - waiting until local midnight (Pause to stop)' if s == 'quota-wait' else 'quota available again - resuming')
            if s != qstate:
                with dbl:
                    if quota: quota.save(c)
                    c.commit()                          # a state change (e.g. quota-wait) is a good moment to make the progress durable
            qstate = s
            if os.path.exists(stopf) and not stop.is_set(): log('STOP file found - finishing in-flight objects and pausing (rerun `run` to resume)'); stop.set()
            if n_tick % 5: continue
            with dbl:
                if quota: quota.save(c)
                c.commit()
            if stat['bytes'] > budget * 2**30: log('BUDGET reached, stopping'); stop.set()
            if free() < a.min_free_gib: log(f'FREE DISK {free():.1f} GiB < {a.min_free_gib}, stopping'); stop.set()
            if time.time() - last > 30:
                last = time.time(); el = time.time() - t0
                log(f"progress ok={stat['ok']} fail={stat['fail']} retry={stat['retry']} {stat['bytes']/2**30:.2f} GiB ({stat['bytes']/el/2**20:.1f} MiB/s) left={len(q)} free={free():.0f} GiB [{s}]")
    except KeyboardInterrupt:
        stop.set(); log('interrupted')
    for t in ths: t.join(timeout=60)
    with dbl:
        if quota: quota.save(c)
        c.commit()
    progress(final['state'] or ('done' if not stop.is_set() else 'paused'))
    log(f"done ok={stat['ok']} fail={stat['fail']} retry={stat['retry']} {stat['bytes']/2**30:.2f} GiB in {(time.time()-t0)/60:.1f} min")

def status_data():
    """-> dict(rows=[{prio,status,chunks,wire,raw}], stored, stored_gib, cod_key, packages={pkg: {chunks, stored, wire_gib, stored_gib}}, levels={level: {stored, stored_gib}}, scope, loaded)"""
    c = db(); names = {0: 'pending', 1: 'ok', 2: 'failed', 3: '404'}
    rows = [dict(prio=p, status=names[s], chunks=n, wire=w or 0, raw=rw or 0) for p, s, n, w, rw in c.execute('select prio, status, count(*), sum(wire), sum(raw) from chunks group by prio, status order by prio, status')]
    n, w = c.execute('select count(*), sum(wire) from chunks where status=1').fetchone()
    pk = {}
    for k in pack.ORDER:
        b = pack.bit(k); r = c.execute('select count(*), sum(wire), sum(status=1), sum(case when status=1 then wire else 0 end) from chunks where (pkgs & ?) != 0', (b,)).fetchone()
        if r[0]: pk[k] = dict(chunks=r[0], wire_gib=(r[1] or 0) / 2**30, stored=r[2] or 0, stored_gib=(r[3] or 0) / 2**30)
    lv = {}
    for k, mib in pack.LEVELS.items():
        r = c.execute('select count(*), sum(wire) from chunks where status=1 and raw<=?', (mib * 2**20,)).fetchone(); lv[k] = dict(stored=r[0] or 0, stored_gib=(r[1] or 0) / 2**30)
    return dict(rows=rows, stored=n, stored_gib=(w or 0) / 2**30, cod_key=c.execute('select count(*) from chunks where status=1 and cod_key is not null').fetchone()[0],
                packages=pk, levels=lv, scope=meta_get(c, 'scope'), loaded=int(meta_get(c, 'loaded', 0)))

def cmd_retry_failed(a):
    c = db(); n = c.execute('update chunks set status=0 where status=2').rowcount; c.commit(); log(f'retry-failed: {n} chunks reset to pending')

def cmd_status(a):
    if a.json: print(json.dumps(status_data())); return
    c = db()
    names = {0: 'pending', 1: 'ok', 2: 'failed', 3: '404'}
    print('status by prio (0=game-requested, 1=<=4MiB, 2=4K class):')
    for prio, st, n, w, rw in c.execute('select prio, status, count(*), sum(wire), sum(raw) from chunks group by prio, status order by prio, status'):
        print(f'  prio {prio} {names[st]:8s} {n:7d} chunks  wire {w/2**30:7.2f} GiB  raw {rw/2**30:7.2f} GiB')
    n, w = c.execute('select count(*), sum(wire) from chunks where status=1').fetchone(); print(f'stored: {n} chunks, {(w or 0)/2**30:.2f} GiB; cod_key present: ' + str(c.execute('select count(*) from chunks where status=1 and cod_key is not null').fetchone()[0]))
    d = status_data()
    for k, v in d['packages'].items(): print(f"  package {k:7s} {v['chunks']:7,} chunks {v['wire_gib']:7.2f} GiB   stored {v['stored']:7,} ({v['stored_gib']:7.2f} GiB)   (an id in several lists counts in each)")
    for k, v in d['levels'].items(): print(f"  stored <= {k:9s} {v['stored']:7,} chunks {v['stored_gib']:7.2f} GiB")

def good_object(wire, flag, et, sid):
    i = sid & (2**64 - 1); p = opath(i, wire, flag)
    try:
        b = open(p, 'rb').read()
        if len(b) != wire or (et and '-' not in et and hashlib.md5(b).hexdigest() != et.split(':')[0]): raise IOError('mismatch')
        return True, p
    except Exception as e: return False, p

def cmd_verify(a):
    c = db(); rows = c.execute('select id, wire, flag, etag from chunks where status=1').fetchall()
    if not a.all: random.shuffle(rows); rows = rows[:a.n]
    bad = []; t0 = time.time(); last = 0
    def prog(st, done):
        if not a.progress_json: return
        try:
            with open(a.progress_json + '.tmp', 'w', encoding='utf-8') as f: json.dump(dict(state=st, pid=os.getpid(), done=done, total=len(rows), bad=len(bad), started=t0, now=time.time()), f)
            os.replace(a.progress_json + '.tmp', a.progress_json)
        except OSError: pass
    for k, (sid, wire, flag, et) in enumerate(rows):
        ok, p = good_object(wire, flag, et, sid)
        if not ok: bad.append((sid, p)); print('BAD', p)
        if time.time() - last > 1: last = time.time(); prog('verifying', k)
    if a.fix and bad:
        for sid, p in bad:
            try: os.remove(p)
            except OSError: pass
            c.execute('update chunks set status=0 where id=?', (sid,))
        c.commit(); print(f'reset {len(bad)} bad objects to pending (run again to re-download)')
    prog('done', len(rows)); print(f'verified {len(rows)} objects, {len(bad)} bad')

def cmd_prune(a):
    c = db(); rows = c.execute('select id, wire, flag from chunks where status=1 and raw>?', (a.above_tier * 2**20,)).fetchall()
    gib = sum(r[1] for r in rows) / 2**30; res = dict(chunks=len(rows), gib=round(gib, 3), deleted=0, above_tier_mib=a.above_tier, dry_run=not a.yes)
    if a.yes:
        for sid, wire, flag in rows:
            try: os.remove(opath(sid & (2**64 - 1), wire, flag))
            except OSError: pass
            c.execute('update chunks set status=0 where id=?', (sid,)); res['deleted'] += 1
        c.commit(); log(f'prune: removed {res["deleted"]} stored objects above {a.above_tier:g} MiB raw ({gib:.2f} GiB); rows reset to pending (a run with a tier cap skips them)', echo=not a.json)
    if a.json: print(json.dumps(res))
    else: print(f"{'removed' if a.yes else 'would remove'} {len(rows)} stored objects above {a.above_tier:g} MiB raw ({gib:.2f} GiB)" + ('' if a.yes else ' - add --yes to delete'))

if __name__ == '__main__':
    ap = argparse.ArgumentParser(epilog=version.NOTICE); ap.add_argument('--version', action='version', version=version.USER_AGENT); sp = ap.add_subparsers(dest='cmd', required=True)
    def scope_args(p):
        p.add_argument('--scope', choices=['sp', 'all', 'custom'], help='which chunk lists (default for init/plan: sp; for run: everything already in the index)')
        p.add_argument('--packages', help='custom scope: comma list of ' + ','.join(pack.ORDER))
    def level_args(p):
        p.add_argument('--level', choices=list(pack.LEVELS), help='detail level = max raw size: standard 4 MiB, high 8 MiB, ultra no cap'); p.add_argument('--tier', type=float, default=4096, help='max raw MiB (overridden by --level)')
    i = sp.add_parser('init'); scope_args(i)
    pl = sp.add_parser('plan'); scope_args(pl); level_args(pl); pl.add_argument('--line-mbps', type=float, default=0); pl.add_argument('--json', action='store_true')
    sp.add_parser('retry-failed'); s = sp.add_parser('status'); s.add_argument('--json', action='store_true')
    r = sp.add_parser('run'); scope_args(r); level_args(r)
    r.add_argument('--upstream-ip', help='tests only: skip edge resolution'); r.add_argument('--upstream-port', type=int, default=80); r.add_argument('--progress-json'); r.add_argument('--stop-file', help='create this file to pause cleanly (default mirror/STOP)'); r.add_argument('--workers', type=int, default=4, help='parallel connections (default 4; be considerate to the CDN)')
    r.add_argument('--budget-gib', type=float, default=0, help='0 = automatic (queue size + 2 %%)'); r.add_argument('--min-free-gib', type=float, default=40)
    r.add_argument('--retries', type=int, default=4); r.add_argument('--max-rps', type=float, default=50, help='request rate cap (default 50/s)')
    r.add_argument('--limit-mbps', type=float, default=0, help='total download cap in Mbit/s shared by all workers (0 = unlimited)')
    r.add_argument('--line-mbps', type=float, default=0, help='your line speed in Mbit/s; if the rate stays under 20 %% of it for a minute the edge addresses are measured again (0 = off)')
    r.add_argument('--daily-gib', type=float, default=0, help='pause after this many GiB per local day (0 = unlimited)')
    r.add_argument('--accept-notice', action='store_true', help='confirm the bulk-download notice (asked once per version; the GUI asks in a dialog)')
    r.add_argument('--link-wait-s', type=float, default=0, help='give up (state offline) when the upstream is unreachable this long; 0 = wait forever')
    v = sp.add_parser('verify'); v.add_argument('--n', type=int, default=200); v.add_argument('--all', action='store_true'); v.add_argument('--fix', action='store_true'); v.add_argument('--progress-json')
    pr = sp.add_parser('prune'); pr.add_argument('--above-tier', type=float, required=True, help='MiB raw: stored objects larger than this are deleted'); pr.add_argument('--yes', action='store_true'); pr.add_argument('--json', action='store_true')
    a = ap.parse_args(); os.makedirs(os.path.dirname(LOG), exist_ok=True)
    {'init': cmd_init, 'plan': cmd_plan, 'run': cmd_run, 'status': cmd_status, 'verify': cmd_verify, 'retry-failed': cmd_retry_failed, 'prune': cmd_prune}[a.cmd](a)
