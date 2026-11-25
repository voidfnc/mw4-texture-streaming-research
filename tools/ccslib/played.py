"""played.py - which chunk lists the game folder has (Doctor, support bundle) and what the game asked for that the offline copy lacked (Download what I played).

The proxy notes every piece it could not serve from the copy in requested.txt: one line `path raw list` per piece (raw / list are '-' when no list on this PC names it).
Chunks live at /pc/iw9_3/23/<xx>/<id>_<wire>_<flag>, Warzone's small side files at /pc/iw9_3/23/tr/<32 hex>/<id>_<wire>_<flag>.
"""
import os, re
from . import mirrordb, paths
from .pack import GiB, LEVELS, MiB, cdnxpak, level_mib, list_kind, package_of

_REPORT_CACHE = {}


def lists_report(root=None):
    """Every chunk list in the game folder with its size (Doctor, support bundle): [dict(file, kind, package, records, gib, standard_gib, high_gib, empty)].
    Names and counts only, nothing of the content. Parsed lists are remembered by size + time, so a second call is quick."""
    root = root or paths.GAME_ROOT; out = []
    for p in cdnxpak.find_all(root):
        rel = os.path.relpath(p, root).replace('\\', '/')
        try: st = os.stat(p); key = (p, st.st_size, int(st.st_mtime))
        except OSError: continue
        row = _REPORT_CACHE.get(key)
        if row is None:
            recs = cdnxpak.parse(p) if cdnxpak.has_records(p) else []
            row = dict(records=len(recs), gib=round(sum(r['size'] for r in recs) / GiB, 2), empty=not recs,
                       standard_gib=round(sum(r['size'] for r in recs if r['raw'] <= LEVELS['standard'] * MiB) / GiB, 2),
                       high_gib=round(sum(r['size'] for r in recs if r['raw'] <= LEVELS['high'] * MiB) / GiB, 2))
            _REPORT_CACHE[key] = row
        out.append(dict(row, file=rel, kind=list_kind(p), package=package_of(p)))
    return out


def lists_text(rows):
    """lists_report() as a plain table (state/lists.txt of the support bundle)."""
    L = [f"{'list':34s} {'kind':9s} {'package':8s} {'pieces':>10s} {'GiB ultra':>10s} {'GiB high':>9s} {'GiB std':>8s}"]
    for r in rows:
        L.append(f"{r['file']:34s} {r['kind']:9s} {r['package'] or '-':8s} {r['records']:>10,} {r['gib']:>10.2f} {r['high_gib']:>9.2f} {r['standard_gib']:>8.2f}" + ('  (empty)' if r['empty'] else ''))
    return '\n'.join(L) + '\n'


REQ_RE = re.compile(r'^(/pc/iw9_3/23/(?:([0-9a-f]{2})|tr/([0-9a-f]{32}))/([0-9a-f]{16})_([0-9a-f]{8})_([01]))(?:\s+(\d+|-))?(?:\s+(\S+))?\s*$')


def requested_file(): return os.path.join(paths.WORK, 'requested.txt')


def read_requested(path=None):
    """-> [dict(path, side, folder, id, wire, flag, raw (None = not known), list)] from requested.txt, one per path (the first line wins)."""
    path = path or requested_file(); out = {}
    try: lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    except OSError: return []
    for ln in lines:
        m = REQ_RE.match(ln.strip())
        if not m or m.group(1) in out: continue
        out[m.group(1)] = dict(path=m.group(1), side=bool(m.group(3)), folder=m.group(3), id=int(m.group(4), 16), wire=int(m.group(5), 16), flag=int(m.group(6)),
                               raw=int(m.group(7)) if m.group(7) and m.group(7) != '-' else None, list=m.group(8) if m.group(8) and m.group(8) != '-' else None)
    return list(out.values())


def local_file(r, mirror_dir=None):
    """Where a requested piece lives in the copy: objects/xx/<name> for a chunk, side/tr/<folder>/<name> for a side file."""
    d = mirror_dir or paths.MIRROR; name = f"{r['id']:016x}_{r['wire']:08x}_{r['flag']}"
    return os.path.join(d, 'side', 'tr', r['folder'], name) if r['side'] else os.path.join(d, 'objects', f"{r['id'] & 0xff:02x}", name)


def gone_ids(mirror_dir=None):
    """Ids the CDN answered 404 for in an earlier download (index status 3): there is nothing to fetch for them."""
    db = os.path.join(mirror_dir or paths.MIRROR, 'index.sqlite')
    if not os.path.exists(db): return set()
    try:
        c = mirrordb.connect_read(db, timeout=10)
        try: return {i & (2**64 - 1) for (i,) in c.execute('select id from chunks where status=3')}
        finally: c.close()
    except Exception: return set()


def played_missing(level='ultra', mirror_dir=None, path=None):
    """Pieces the game asked for that the copy does not have (and that the detail level allows) -> dict(n, gib, items, by_list={name: n}, gone).
    gone = pieces left out because the CDN no longer has them (an earlier download got a 404)."""
    cap = level_mib(level) * MiB; items = []; gone = gone_ids(mirror_dir); ng = 0
    for r in read_requested(path):
        if r['raw'] is not None and r['raw'] > cap: continue
        p = local_file(r, mirror_dir)
        try:
            if os.path.getsize(p) == r['wire']: continue
        except OSError: pass
        if not r['side'] and r['id'] in gone: ng += 1; continue
        items.append(r)
    by = {}
    for r in items:
        k = r['list'] or ('side files' if r['side'] else 'in no list'); by[k] = by.get(k, 0) + 1
    return dict(n=len(items), gib=sum(r['wire'] for r in items) / GiB, items=items, by_list=by, gone=ng)
