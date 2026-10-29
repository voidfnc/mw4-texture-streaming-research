"""report.py - post-run analysis of a proxy session (replaces the scratch inv*.py scripts).

Input : tools/work/ccsproxy.log (several proxy runs are concatenated; a run starts at its `START`/`mirror:`/`index:` header lines),
        the CDN catalogue (cod26/*_cdn.xpak + sp26/*_cdn.xpak), the mirror index, optional engine-cache snapshots (before/after).
Output: dict (JSON-able) + markdown, saved to tools/work/sessions/.

Answers, per run: what did the game request (tiers, >4 MiB = 4K-class demand), from where was it served, how much of it did the engine
already hold in xpak_cache (re-request rate), were there mirror gaps / errors, how did the cache grow, which graphics settings were active.
"""
import collections, datetime, glob, json, os, re, sqlite3, sys, time
from . import mirrordb, paths

TIERS = [('<=64K', 2**16), ('<=256K', 2**18), ('<=1M', 2**20), ('<=4M', 2**22), ('<=8M', 2**23), ('<=16M', 2**24), ('>16M', None)]
TIER_NAMES = [t[0] for t in TIERS]
_REQ = re.compile(r'^(\d\d):(\d\d):(\d\d) (GET|HEAD) /pc/iw9_3/23/[0-9a-f]{2}/([0-9a-f]{16})_([0-9a-f]{8})_([01]) -> (\d+) (\d+)B(?: (MIRROR)| raw=\S+ range=(\S+))?')
_EVT = re.compile(r'^(\d\d):(\d\d):(\d\d) (SKIP-TIER|RETRY|ERR-UPSTREAM|CLIENT-ABORT|MISS-OFFLINE|BUDGET|FAIL)\b(.*)')
_STATS = re.compile(r"^\d\d:\d\d:\d\d stats (\{.*\})")
_HDR = re.compile(r'^\d\d:\d\d:\d\d (START|mirror:|index:)')
CFG_KEYS = re.compile(r'^(TextureQuality|ResolutionMultiplier|Resolution|DLSSPerfModeMP|AATechniquePreferredMP|AATechniquePreferred|GraphicsQuality|DynamicSceneResolution|AbsoluteTargetResolution|'
                      r'.*(Stream|Cache|Download).*)@')


def tier_of(raw):
    if raw is None: return 'unknown'
    for n, lim in TIERS:
        if lim is None or raw <= lim: return n


# ------------------------------------------------------------------------------------------------ log parsing
def segments(log_path=None):
    """Split the proxy log into runs. -> list of dict(idx, header[], lines[], date, first, last, nreq)"""
    p = log_path or os.path.join(paths.WORK, 'ccsproxy.log')
    segs = []; pending = []; cur = None
    files = [f'{p}.{i}' for i in (3, 2, 1)] + [p]          # rotated copies (logrot) are older runs; rotation only happens between runs
    for fn in files:
        try: f = open(fn, encoding='utf-8', errors='replace')
        except OSError: continue
        with f:
            for line in f:
                line = line.rstrip('\n')
                m = _HDR.match(line)
                if m:
                    if m.group(1) in ('START', 'mirror:'): pending.append(line); continue
                    cur = dict(idx=len(segs), header=pending + [line], lines=[], date=None); segs.append(cur); pending = []
                    for h in cur['header']:
                        d = re.search(r'START (\d{4}-\d\d-\d\d)', h)
                        if d: cur['date'] = d.group(1)
                    continue
                if cur is not None: cur['lines'].append(line)
    for s in segs:
        s['nreq'] = sum(1 for l in s['lines'] if _REQ.match(l))
        ts = [l[:8] for l in s['lines'] if re.match(r'^\d\d:\d\d:\d\d ', l)]
        s['first'] = ts[0] if ts else None; s['last'] = ts[-1] if ts else None
    return segs


_SKIP = re.compile(r'SKIP-TIER (GET|HEAD) /pc/iw9_3/23/[0-9a-f]{2}/([0-9a-f]{16})_([0-9a-f]{8})_[01] raw=([\d.]+)MiB')


def skip_stats(seg):
    """Chunks withheld by the detail level (proxy tier cap -> HTTP 404): requests, unique ids, repeat asks (a retry storm would show here), GiB not downloaded. None if none."""
    c = collections.Counter(); wire = {}; raw = {}
    for l in seg['lines']:
        m = _SKIP.search(l)
        if m and m.group(1) == 'GET': i = int(m.group(2), 16); c[i] += 1; wire[i] = int(m.group(3), 16); raw[i] = float(m.group(4))
    if not c: return None
    return dict(requests=sum(c.values()), unique=len(c), repeats=sum(c.values()) - len(c), max_repeats=max(c.values()), withheld_gib=round(sum(wire.values()) / 2**30, 3),
                top=[dict(id=f'{i:016x}', raw_mib=raw[i], asked=n) for i, n in c.most_common(8)])


def _sec(h, m, s): return int(h) * 3600 + int(m) * 60 + int(s)


def parse_segment(seg):
    reqs = []; events = collections.Counter(); last_stats = None; day = 0; prev = -1
    for l in seg['lines']:
        m = _REQ.match(l)
        if m:
            t = _sec(*m.group(1, 2, 3))
            if t < prev - 600: day += 1
            prev = t
            reqs.append(dict(t=t + day * 86400, method=m.group(4), id=int(m.group(5), 16), wire=int(m.group(6), 16), flag=int(m.group(7)), status=int(m.group(8)), n=int(m.group(9)),
                             src='mirror' if m.group(10) else 'upstream', range=(m.group(11) or '-') if not m.group(10) else '-'))
            continue
        m = _EVT.match(l)
        if m: events[m.group(4)] += 1; continue
        m = _STATS.match(l)
        if m:
            try: last_stats = eval(m.group(1), {'__builtins__': {}})      # the proxy prints a plain dict repr
            except Exception: pass
    return reqs, events, last_stats


# ------------------------------------------------------------------------------------------------ inputs
_CAT = None; _CAT_ROOT = None


def load_catalogue():
    """id -> dict(raw, size) over all shipped *_cdn.xpak lists (cached per configured game folder)."""
    global _CAT, _CAT_ROOT
    if _CAT is None or _CAT_ROOT != paths.ROOT:
        sys.path.insert(0, paths.TOOLS); import cdnxpak
        _CAT = {}; _CAT_ROOT = paths.ROOT
        for fn in paths.chunk_lists(paths.ROOT):
            for r in cdnxpak.parse(fn): _CAT.setdefault(r['id'], dict(raw=r['raw'], size=r['size']))
    return _CAT


def load_mirror_ids():
    db = os.path.join(paths.MIRROR, 'index.sqlite')
    if not os.path.exists(db): return None
    c = mirrordb.connect_read(db, timeout=10)
    try: return {sid & (2**64 - 1) for (sid,) in c.execute('select id from chunks where status=1')}
    finally: c.close()


def snapshot_cache(cache_dir=None):
    """Engine cache index snapshot: ids + per-shard header facts. Read-only; may race with a running game (labelled by caller)."""
    sys.path.insert(0, paths.TOOLS); import xpakrec, struct
    ids = set(); records = 0; shards = []
    for fn in sorted(glob.glob(os.path.join(glob.escape(cache_dir or paths.XPAK_CACHE), 'cache_*_2.xpak'))):
        try:
            recs = xpakrec.parse(fn); d = open(fn, 'rb').read(0x1000)
            shards.append(dict(name=os.path.basename(fn), counter=struct.unpack_from('<I', d, 8)[0], records=len(recs), key=d[0x130:0x138].hex()))
            records += len(recs); ids.update(r['id'] for r in recs)
        except Exception as e:
            shards.append(dict(name=os.path.basename(fn), error=str(e)))
    return dict(taken=time.time(), records=records, unique=len(ids), ids=[hex(i) for i in sorted(ids)], shards=shards)


def save_snapshot(snap, path):
    os.makedirs(os.path.dirname(path), exist_ok=True); json.dump(snap, open(path, 'w'))


def load_snapshot(path):
    try: return json.load(open(path))
    except Exception: return None


def seg_start_epoch(seg):
    """Epoch of the run's first header line (needs the START date line; older runs have none -> None)."""
    m = re.match(r'^(\d\d):(\d\d):(\d\d) ', seg['header'][0]) if seg.get('header') else None
    if not (m and seg.get('date')): return None
    try: return datetime.datetime.strptime(f"{seg['date']} {m.group(1)}:{m.group(2)}:{m.group(3)}", '%Y-%m-%d %H:%M:%S').timestamp()
    except ValueError: return None


def scale_of(seg, epoch):
    """Convert an epoch to the time scale of parse_segment()'s request times (seconds since midnight of the run's START date)."""
    e0 = seg_start_epoch(seg)
    if e0 is None: return None
    m = re.match(r'^(\d\d):(\d\d):(\d\d) ', seg['header'][0])
    return _sec(*m.group(1, 2, 3)) + (epoch - e0)


def baseline_for(seg, window_s=900, t0=None):
    """The cache snapshot the GUI took right before this run's proxy started (tools/work/sessions/baseline-*.json), if any.
    With t0 (epoch of a game launch) it returns the latest snapshot taken before that launch (<= 12 h earlier)."""
    if t0 is not None: window_s = 12 * 3600
    else: t0 = seg_start_epoch(seg)
    if t0 is None: return None
    best = None
    for fn in glob.glob(os.path.join(glob.escape(paths.SESSIONS), 'baseline-*.json')):
        s = load_snapshot(fn)
        if s and t0 - window_s <= s['taken'] <= t0 + 5 and (best is None or s['taken'] > best['taken']): best = s
    return best


def _ids(snap): return {int(x, 16) for x in snap['ids']} if snap else None


def player_config(path=None):
    out = {}
    try:
        for l in open(path or paths.PLAYER_CFG, encoding='utf-8', errors='replace'):
            if l.startswith('//') or '=' not in l: continue
            k, v = l.split('=', 1)
            if CFG_KEYS.match(k.strip()): out[k.strip().split(';')[0]] = v.split('//')[0].strip()
    except OSError: pass
    return out


# ------------------------------------------------------------------------------------------------ analysis
def build(seg, catalogue=None, mirror_ids=None, baseline=None, post=None, cfg=None, window=None):
    """window = (epoch_from, epoch_to): analyse only the requests of one game launch inside this proxy run (needs the run's START date)."""
    reqs, events, last_stats = parse_segment(seg)
    cat = catalogue if catalogue is not None else load_catalogue()
    win = None
    if window and seg_start_epoch(seg) is not None:
        a, b = scale_of(seg, window[0]), scale_of(seg, window[1]); reqs = [r for r in reqs if a <= r['t'] <= b]; last_stats = None; events = collections.Counter()
        win = dict(**{'from': time.strftime('%H:%M:%S', time.localtime(window[0])), 'to': time.strftime('%H:%M:%S', time.localtime(window[1]))}, note='request counts/bytes are windowed; proxy event counters (RETRY...) are not')
    gets = [r for r in reqs if r['method'] == 'GET' and r['range'] == '-']
    probes = [r for r in reqs if not (r['method'] == 'GET' and r['range'] == '-')]
    ok = [r for r in gets if r['status'] == 200]
    by_id = collections.Counter(r['id'] for r in gets)
    uids = set(by_id)
    rep = dict(version=2, generated=time.strftime('%Y-%m-%d %H:%M:%S'), segment=seg['idx'], date=seg.get('date'), first=seg.get('first'), last=seg.get('last'),
               header=[h.split(' ', 1)[1] if ' ' in h else h for h in seg['header']])
    if win: rep['window'] = win; rep['first'] = win['from']; rep['last'] = win['to']
    if reqs:
        ts = [r['t'] for r in reqs]; rep['active_s'] = max(ts) - min(ts)
        per_s = collections.Counter(ts); rep['peak_rps'] = max(per_s.values()); rep['avg_rps_active'] = round(len(reqs) / max(1, rep['active_s']), 2)
    rep['requests'] = dict(total=len(reqs), chunk_gets=len(gets), probes=len(probes), ok=len(ok), unique_ids=len(uids), repeated_ids=sum(1 for c in by_id.values() if c > 1),
                           extra_repeat_requests=sum(c - 1 for c in by_id.values()), max_repeats=max(by_id.values()) if by_id else 0)
    rep['served'] = dict(mirror=sum(1 for r in ok if r['src'] == 'mirror'), upstream=sum(1 for r in ok if r['src'] == 'upstream'),
                         mirror_bytes=sum(r['n'] for r in ok if r['src'] == 'mirror'), upstream_bytes=sum(r['n'] for r in ok if r['src'] == 'upstream'),
                         non200=dict(collections.Counter(r['status'] for r in gets if r['status'] != 200)))
    rep['events'] = dict(events)
    if not win:
        sk = skip_stats(seg)
        if sk: rep['skips'] = sk
    # throughput (the engine paces its downloads: sustained ~9-10 MiB/s observed) and a per-minute timeline with the big-chunk count
    if gets:
        t_first = min(r['t'] for r in gets); per10 = collections.Counter(); tl = collections.OrderedDict()
        for r in gets:
            per10[(r['t'] - t_first) // 10] += r['n']; mn = (r['t'] - t_first) // 60
            row = tl.setdefault(mn, [0, 0, 0]); row[0] += 1; row[1] += r['n']
            if cat.get(r['id'], {}).get('raw', 0) > 4 * 2**20: row[2] += 1
        v = sorted(x / 2**20 / 10 for x in per10.values())
        rep['throughput_mibps_10s'] = dict(p50=round(v[len(v) // 2], 1), p90=round(v[int(len(v) * .9)], 1), max=round(v[-1], 1))
        rep['timeline'] = [dict(minute=m, requests=a, mib=round(b / 2**20), big=c) for m, (a, b, c) in sorted(tl.items())]
    # tiers: unique requested ids vs catalogue
    req_t = collections.Counter(); cat_t = collections.Counter(); unknown = []
    for i in uids:
        c = cat.get(i)
        if c: req_t[tier_of(c['raw'])] += 1
        else: unknown.append(i)
    for c in cat.values(): cat_t[tier_of(c['raw'])] += 1
    rep['tiers'] = {t: dict(requested=req_t.get(t, 0), catalogue=cat_t.get(t, 0), pct=round(100 * req_t.get(t, 0) / cat_t[t], 2) if cat_t.get(t) else 0.0) for t in TIER_NAMES}
    big = sorted(((cat[i]['raw'], i) for i in uids if i in cat and cat[i]['raw'] > 4 * 2**20), reverse=True)
    rep['over_4mib'] = dict(ids=len(big), top=[dict(id=f'{i:016x}', raw_mib=round(raw / 2**20, 2), requests=by_id[i]) for raw, i in big[:20]])
    rep['unknown_ids'] = len(unknown)
    # mirror gaps: requested ids not stored in the mirror
    if mirror_ids is not None: rep['mirror_gaps'] = dict(ids=sum(1 for i in uids if i in mirror_ids), missing=[f'{i:016x}' for i in sorted(uids) if i not in mirror_ids][:50], missing_count=sum(1 for i in uids if i not in mirror_ids))
    # engine cache: re-request rate + growth
    b = _ids(baseline); p = _ids(post)
    if b is not None and uids:
        pre = len(uids & b); rep['cache'] = dict(baseline_records=baseline['records'], baseline_unique=baseline['unique'], requested_already_in_cache=pre, requested_pct_already_in_cache=round(100 * pre / len(uids), 1))
        if p is not None: rep['cache'].update(post_records=post['records'], post_unique=post['unique'], new_unique_ids=len(p - b), requested_now_in_cache=len(uids & p),
                                              dup_ratio=round(post['records'] / max(1, post['unique']), 2), record_growth=post['records'] - baseline['records'])
        if p is not None and b and len(b - p) > len(b) / 2:       # most of what the cache held at the start is gone: it was emptied or replaced while the session ran
            rep['cache']['note'] = (f'the cache was emptied or replaced during this run: {round(100 * len(b - p) / len(b))}% of the ids it held at the start are gone, '
                                    'so the "already in cache" figure describes the old cache, not what the game had to work with')
    elif p is not None:
        rep['cache'] = dict(post_records=post['records'], post_unique=post['unique'], dup_ratio=round(post['records'] / max(1, post['unique']), 2), note='no baseline snapshot for this run')
    if last_stats: rep['proxy_stats_last'] = last_stats
    rep['config'] = cfg if cfg is not None else player_config()
    return rep


# ------------------------------------------------------------------------------------------------ output
def _gib(n): return f'{n / 2**30:.2f} GiB'


def to_markdown(rep, prev=None):
    r = rep['requests']; s = rep['served']; L = []
    title = f"# Session report - run #{rep['segment']}{' (game launch)' if rep.get('window') else ''} {rep.get('date') or ''} {rep.get('first') or ''}-{rep.get('last') or ''}"
    L += [title.strip(), '', f"_generated {rep['generated']}_", '']
    if rep.get('header'): L += ['```', *rep['header'][:6], '```', '']
    L += ['## Requests', '', '| metric | value |', '|---|---|',
          f"| total requests | {r['total']:,} (chunk GETs {r['chunk_gets']:,}, probes/HEAD/range {r['probes']:,}) |",
          f"| unique chunk ids | {r['unique_ids']:,} |",
          f"| ids requested more than once | {r['repeated_ids']:,} (+{r['extra_repeat_requests']:,} extra requests, max {r['max_repeats']}x) |",
          f"| served from mirror / upstream | {s['mirror']:,} ({_gib(s['mirror_bytes'])}) / {s['upstream']:,} ({_gib(s['upstream_bytes'])}) |",
          f"| non-200 GETs | {s['non200'] or 'none'} |", f"| events | {rep['events'] or 'none'} |"]
    if 'active_s' in rep: L.append(f"| active time / peak / avg req/s | {rep['active_s'] // 60:.0f} min / {rep['peak_rps']} / {rep['avg_rps_active']} |")
    if rep.get('window'): L += ['', f"_window: one game launch ({rep['window']['from']}-{rep['window']['to']}) inside proxy run #{rep['segment']}; {rep['window']['note']}_"]
    if rep.get('skips'):
        k = rep['skips']; L += ['', f"**Detail level cap active:** {k['requests']} requests for {k['unique']} ids above the cap were answered 404 ({k['withheld_gib']} GiB not downloaded); "
                                f"asked again {k['repeats']}x in total (max {k['max_repeats']}x per id - high values would mean the engine keeps retrying)."]
        for x in k['top'][:5]: L.append(f"- `{x['id']}` {x['raw_mib']} MiB x{x['asked']}")
    if 'throughput_mibps_10s' in rep: x = rep['throughput_mibps_10s']; L += ['', f"Sustained throughput (10 s windows): median {x['p50']} / p90 {x['p90']} / max {x['max']} MiB/s"]
    L += ['', '## Tier demand (unique ids requested vs catalogue)', '', '| tier | requested | catalogue | % |', '|---|---:|---:|---:|']
    for t in TIER_NAMES: x = rep['tiers'][t]; L.append(f"| {t} | {x['requested']:,} | {x['catalogue']:,} | {x['pct']} |")
    ob = rep['over_4mib']; L += ['', f"**>4 MiB ids requested: {ob['ids']}** (4K-class demand indicator)"]
    for x in ob['top'][:10]: L.append(f"- `{x['id']}` {x['raw_mib']} MiB x{x['requests']}")
    if rep.get('unknown_ids'): L.append(f"\nIds not in the CDN catalogue: {rep['unknown_ids']}")
    if rep.get('timeline'):
        L += ['', '## Timeline (per minute)', '', '| min | requests | MiB | ids >4 MiB |', '|---:|---:|---:|---:|'] + [f"| {x['minute']} | {x['requests']} | {x['mib']} | {x['big']} |" for x in rep['timeline']]
    if 'mirror_gaps' in rep:
        g = rep['mirror_gaps']; L += ['', f"## Mirror coverage", '', f"requested ids missing from the mirror: **{g['missing_count']}**" + (f" (first: {', '.join(g['missing'][:8])})" if g['missing_count'] else ' (mirror covers everything the game asked for)')]
    if 'cache' in rep:
        c = rep['cache']; L += ['', '## Engine cache (xpak_cache)', '']
        for k, v in c.items(): L.append(f"- {k}: {v}")
    if rep.get('config'): L += ['', '## Active graphics/streaming settings (player config)', ''] + [f"- {k} = {v}" for k, v in sorted(rep['config'].items())]
    if prev:
        L += ['', f"## Change vs previous report ({prev.get('generated')}, run #{prev.get('segment')})", '', '| metric | previous | this |', '|---|---:|---:|']
        for lab, f in (('chunk GETs', lambda x: x['requests']['chunk_gets']), ('unique ids', lambda x: x['requests']['unique_ids']), ('>4 MiB ids', lambda x: x['over_4mib']['ids']),
                       ('mirror-served', lambda x: x['served']['mirror']), ('upstream-served', lambda x: x['served']['upstream']),
                       ('% requested already in cache', lambda x: x.get('cache', {}).get('requested_pct_already_in_cache', '-'))):
            try: L.append(f"| {lab} | {f(prev)} | {f(rep)} |")
            except Exception: pass
    return '\n'.join(L) + '\n'


def _dir(): os.makedirs(paths.SESSIONS, exist_ok=True); return paths.SESSIONS


def list_reports():
    return sorted(f for f in glob.glob(os.path.join(glob.escape(_dir()), '*.json')) if not os.path.basename(f).startswith('baseline-'))


def _stamp(rep): return (rep.get('date') or time.strftime('%Y-%m-%d')).replace('-', '') + '-' + (rep.get('first') or time.strftime('%H:%M:%S')).replace(':', '')[:4]


def previous_report(rep):
    """The saved report chronologically before `rep` (by run stamp), for the diff table."""
    me = _stamp(rep); best = None
    for fn in list_reports():
        if os.path.basename(fn).split('-run')[0] < me: best = fn
    try: return json.load(open(best, encoding='utf-8')) if best else None
    except Exception: return None


def save(rep, prev=None):
    stamp = _stamp(rep)
    base = os.path.join(_dir(), f"{stamp}-run{rep['segment']}"); n = 1
    while os.path.exists(base + '.json'): n += 1; base = os.path.join(_dir(), f"{stamp}-run{rep['segment']}-{n}")
    json.dump(rep, open(base + '.json', 'w', encoding='utf-8'), indent=1)
    open(base + '.md', 'w', encoding='utf-8').write(to_markdown(rep, prev))
    return base + '.md', base + '.json'


def latest_report():
    r = list_reports()
    try: return json.load(open(r[-1], encoding='utf-8')) if r else None
    except Exception: return None
