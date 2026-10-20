"""pack.py - the texture pack model shared by ccsmirror.py, the GUI, doctor and config: packages, scope, detail level, size estimate.

  scope  = WHICH chunk lists are mirrored   'sp' (campaign: sp26 + boot, the default) | 'all' (every *_cdn.xpak) | 'custom' (explicit package list)
  level  = HOW BIG a chunk may be (raw/decoded size = texture-detail cut-off, not a render resolution)
           standard <= 4 MiB (2048^2 BC7, "1440p class") | high <= 8 MiB | ultra = no cap ("4K class")
The same level drives the mirror download cap and the proxy serve cap (config.effective), so what is served never exceeds what was mirrored.
The chunk lists (*_cdn.xpak) come from the user's own game install; nothing is bundled.
"""
import os, shutil, sqlite3, sys, time
from . import mirrordb, paths

sys.path.insert(0, paths.TOOLS)
import cdnxpak                                                                     # noqa: E402

# package key -> (bit, label, list files relative to the game root)
PACKAGES = {
    'sp':     (1,  'SP campaign (sp26)',   ('sp26/sp26_cdn.xpak', 'sp26/ww_sp26_cdn.xpak')),
    'boot':   (2,  'Boot / shared start',  ('sp26/boot_cdn.xpak', 'cod26/boot_cdn.xpak')),
    'common': (4,  'Common (common26)',    ('cod26/common26_cdn.xpak', 'cod26/ww_common26_cdn.xpak')),
    'mp':     (8,  'Multiplayer (mp26)',   ('cod26/mp26_cdn.xpak',)),
    'dmz':    (16, 'DMZ (dmz26)',          ('cod26/dmz26_cdn.xpak',)),
    'hq':     (32, 'HQ (codhq)',           ('cod26/codhq_cdn.xpak',)),
}
ORDER = tuple(PACKAGES)                                                            # an id that is in several lists is attributed to the first one in this order
SCOPES = {'sp': ('sp', 'boot'), 'all': ORDER}
LEVELS = {'standard': 4.0, 'high': 8.0, 'ultra': 4096.0}                           # max raw MiB
LEVEL_LABELS = {'standard': 'Standard HD (<= 4 MiB, 1440p class)', 'high': 'High (<= 8 MiB)', 'ultra': 'Ultra (no cap, 4K class)'}
MiB = 2**20; GiB = 2**30


def bit(pkg): return PACKAGES[pkg][0]


def scope_packages(scope, packages=None):
    """-> tuple of package keys for a scope name ('sp' | 'all' | 'custom'); custom uses `packages` (list or comma string); unknown keys are ignored."""
    if scope in SCOPES: return SCOPES[scope]
    if isinstance(packages, str): packages = [x.strip() for x in packages.split(',')]
    return tuple(k for k in ORDER if k in (packages or ()))


def scope_mask(scope, packages=None):
    m = 0
    for k in scope_packages(scope, packages): m |= bit(k)
    return m


def level_mib(level):
    """level name -> max raw MiB. A bare number (str/float) is accepted as 'advanced' value; unknown names fall back to ultra."""
    if level in LEVELS: return LEVELS[level]
    try: return float(level)
    except (TypeError, ValueError): return LEVELS['ultra']


def level_of_mib(mib):
    for k, v in LEVELS.items():
        if abs(v - float(mib)) < 1e-6: return k
    return None


def list_files(pkg): return PACKAGES[pkg][2]


def available(root=None):
    """-> {pkg: [existing list files]} for the game folder (a package with no files is unavailable on this install)."""
    root = root or paths.GAME_ROOT; out = {}
    for k in ORDER: out[k] = [f for f in list_files(k) if os.path.exists(os.path.join(root, *f.split('/')))]
    return out


def fingerprint(root=None, pkgs=ORDER):
    """list name -> 'size:mtime' (stored in the mirror meta so a changed game build is noticed)."""
    root = root or paths.GAME_ROOT; out = {}
    for k in pkgs:
        for f in list_files(k):
            p = os.path.join(root, *f.split('/'))
            if os.path.exists(p): st = os.stat(p); out[f] = f'{st.st_size}:{int(st.st_mtime)}'
    return out


def catalogue(mask, root=None):
    """Parse the chunk lists of the packages in `mask` -> {id: dict(wire, raw, flag, bits, first)}; `bits` = every selected package containing the id,
    `first` = the package it is attributed to. Pure file reads, no network."""
    root = root or paths.GAME_ROOT; cat = {}
    for k in ORDER:
        b = bit(k)
        if not mask & b: continue
        for f in list_files(k):
            p = os.path.join(root, *f.split('/'))
            if not os.path.exists(p): continue
            for r in cdnxpak.parse(p):
                c = cat.get(r['id'])
                if c is None: cat[r['id']] = dict(wire=r['size'], raw=r['raw'], flag=r['flag'], bits=b, first=k)
                else: c['bits'] |= b
    return cat


def stored_status(mirror_dir=None):
    """-> {unsigned id: status} from the mirror index ({} when there is none). 1 = stored, 0 pending, 2 failed, 3 = 404."""
    db = os.path.join(mirror_dir or paths.MIRROR, 'index.sqlite')
    if not os.path.exists(db): return {}
    c = mirrordb.connect_read(db, timeout=10)
    try: return {(i & (2**64 - 1)): s for i, s in c.execute('select id, status from chunks')}
    finally: c.close()


def free_gib(mirror_dir=None):
    d = mirror_dir or paths.MIRROR
    while d and not os.path.isdir(d):
        n = os.path.dirname(d)
        if n == d: break
        d = n
    try: return shutil.disk_usage(d or paths.ROOT).free / GiB
    except OSError: return 0.0


def _bucket():
    return dict(chunks=0, gib=0.0, stored=0, stored_gib=0.0, pending=0, pending_gib=0.0)


def _add(b, wire, st):
    b['chunks'] += 1; b['gib'] += wire / GiB
    if st == 1: b['stored'] += 1; b['stored_gib'] += wire / GiB
    elif st in (None, 0, 2): b['pending'] += 1; b['pending_gib'] += wire / GiB          # status 3 (CDN 404) is neither stored nor downloadable


def plan(scope='sp', packages=None, level='ultra', root=None, mirror_dir=None, line_mbps=0.0, cat=None, status=None):
    """Size estimate for a scope + level, no network. Returns a JSON-able dict:
      packages / missing (unavailable lists) / level / tier_mib, total + stored + pending (chunks, GiB), levels{standard,high,ultra} (same buckets for every level),
      by_pkg{pkg: bucket} (ids attributed to their first package), free_gib, need_gib (pending of the chosen level + 2 %), eta_h (at line_mbps) and fits (free > need)."""
    pk = scope_packages(scope, packages); mask = scope_mask(scope, packages); root = root or paths.GAME_ROOT
    cat = cat if cat is not None else catalogue(mask, root); status = status if status is not None else stored_status(mirror_dir)
    av = available(root); missing = [k for k in pk if not av.get(k)]
    levels = {k: _bucket() for k in LEVELS}; by_pkg = {k: _bucket() for k in pk}; cap = level_mib(level) * MiB
    for i, c in cat.items():
        st = status.get(i)
        for lv, mib in LEVELS.items():
            if c['raw'] <= mib * MiB: _add(levels[lv], c['wire'], st)
        if c['raw'] <= cap and c['first'] in by_pkg: _add(by_pkg[c['first']], c['wire'], st)
    sel = levels[level] if level in levels else None
    if sel is None:                                                                           # custom MiB value
        sel = _bucket()
        for i, c in cat.items():
            if c['raw'] <= cap: _add(sel, c['wire'], status.get(i))
    need = sel['pending_gib'] * 1.02; fr = free_gib(mirror_dir)
    eta = (sel['pending_gib'] * 8 * 1024 / line_mbps / 3600) if line_mbps and line_mbps > 0 else None
    return dict(scope=scope, packages=list(pk), missing=missing, level=level, tier_mib=level_mib(level), total=sel, levels=levels, by_pkg=by_pkg,
                free_gib=round(fr, 1), need_gib=round(need, 2), eta_h=None if eta is None else round(eta, 2), fits=fr > need + 0.5)


def describe(pl):
    """One-paragraph text of a plan() result for the GUI / CLI."""
    t = pl['total']; s = f"{t['chunks']:,} chunks, {t['gib']:.1f} GiB; stored {t['stored']:,} ({t['stored_gib']:.1f} GiB); to download {t['pending']:,} chunks, {t['pending_gib']:.1f} GiB"
    s += f"; free on the mirror drive {pl['free_gib']:.0f} GiB" + ('' if pl['fits'] else '  - NOT ENOUGH SPACE')
    if pl['eta_h'] is not None: s += f"; ETA {pl['eta_h']:.1f} h at the entered line speed"
    if pl['missing']: s += '; chunk lists missing on this install for: ' + ', '.join(pl['missing'])
    return s


def mirror_coverage(scope, packages, level, root=None, mirror_dir=None):
    """Doctor helper: -> (pending chunks, pending GiB, stored chunks, total chunks) for scope+level; None when the mirror has no index."""
    if not os.path.exists(os.path.join(mirror_dir or paths.MIRROR, 'index.sqlite')): return None
    p = plan(scope, packages, level, root, mirror_dir); t = p['total']
    return t['pending'], t['pending_gib'], t['stored'], t['chunks']
