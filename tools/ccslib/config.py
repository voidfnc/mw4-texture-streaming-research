"""config.py - GUI settings + profiles in tools/work/gui_settings.json (missing keys fall back to DEFAULTS).

"paths" holds the configurable locations (see paths.py); saving settings re-reads them (paths.reload()).
A profile is a set of overrides applied on top of the base settings when a session starts: {'proxy': {...}, 'guard': {...}, 'watchers': {...}}.
"""
import copy, json, os
from . import pack, paths

DEFAULTS = dict(
    profile='Default',
    paths=dict(game_root='', cache_dir='', mirror_dir='', player_cfg='', game_exes='', kill_exes=''),   # '' = not set / derived (see paths.py)
    proxy=dict(max_raw_mib=4096, budget_gib=120, retries=3, origin=True, offline=False, upstream_ip='', port=80),
    guard=dict(enabled=True, limit_gib=100, action='kill', interval=5),
    hosts=dict(on_exit='ask'),            # ask | keep | remove  (what to do with the hosts override when the session is stopped / GUI closed)
    watchers=dict(netwatch=False),
    mirror=dict(workers=4, tier=4096, budget_gib=0, min_free_gib=40, max_rps=50, retries=4),
    # texture pack (Texture pack tab): scope = which chunk lists, level = detail cut-off; with link_caps the level also sets mirror.tier and proxy.max_raw_mib (see effective())
    pack=dict(scope='sp', packages=['sp'], level='ultra', link_caps=True, limit_mbps=0, daily_gib=0, workers=0, line_mbps=50, link_wait_s=0),
    profiles={},                          # user-defined profiles (name -> overrides), saved from the Dashboard
    log_max_mb=25,                        # rotate a log at session start when it is larger (0 = never); 3 old copies are kept
    keep_running_on_close=False,
    bulk_ack='',                          # version of the bulk-download notice the user accepted
    guide=dict(enabled=False, path='', ms=[], skipped=[], confirmed_root='', offered='', simple=False, summary={}, ab=0),     # optional guided setup (see guide.py)
    notice_ack='',                        # version of the research/responsibility notice the user has seen
)

BUILTIN_PROFILES = {
    'Default': dict(proxy=dict(origin=True, offline=False)),                 # mirror first, upstream for misses
    'Offline test': dict(proxy=dict(origin=True, offline=True)),             # mirror only; any miss is a 404 so a mirror gap shows immediately
    'Capture': dict(proxy=dict(origin=False, offline=False)),                # no mirror: everything from the CDN (new-content runs)
    'Standard HD (1440p class)': dict(proxy=dict(origin=True), pack=dict(level='standard')),   # chunks > 4 MiB raw are withheld (404): the engine keeps the smaller mip
    'Ultra (4K class)': dict(proxy=dict(origin=True), pack=dict(level='ultra')),
    'Slow link - offline mirror': dict(proxy=dict(origin=True, offline=True)),   # play only from the local mirror; nothing goes to the internet
}
PROFILES = BUILTIN_PROFILES                                                  # kept for older callers (names only)
SECTIONS = ('proxy', 'guard', 'watchers', 'pack')


def _path(): return os.path.join(paths.WORK, 'gui_settings.json')


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict): _merge(base[k], v)
        else: base[k] = v
    return base


def load():
    cfg = copy.deepcopy(DEFAULTS)
    try: _merge(cfg, json.load(open(_path(), encoding='utf-8')))
    except Exception: pass
    return cfg


def save(cfg):
    paths.ensure_dirs(); tmp = _path() + '.tmp'
    json.dump(cfg, open(tmp, 'w', encoding='utf-8'), indent=2); os.replace(tmp, _path())
    paths.reload()                                                           # locations may have changed


def all_profiles(cfg):
    p = copy.deepcopy(BUILTIN_PROFILES); p.update({k: v for k, v in (cfg.get('profiles') or {}).items() if k not in BUILTIN_PROFILES}); return p


def effective(cfg):
    """Copy of cfg with the selected profile's overrides applied to proxy / guard / watchers."""
    out = copy.deepcopy(cfg); prof = all_profiles(cfg).get(cfg.get('profile'), {})
    for sec in SECTIONS: out[sec].update(prof.get(sec, {}))
    pk = out['pack']
    if pk.get('link_caps', True):                       # one detail level drives both caps: what is served never exceeds what was mirrored
        mib = pack.level_mib(pk.get('level')); out['proxy']['max_raw_mib'] = mib; out['mirror']['tier'] = mib
    return out


def effective_proxy(cfg): return effective(cfg)['proxy']


def snapshot_profile(cfg):
    """Current effective proxy/guard/watchers values as a profile dict (for 'Save as profile')."""
    e = effective(cfg); out = {sec: dict(e[sec]) for sec in SECTIONS if sec != 'pack'}; out['pack'] = dict(level=e['pack']['level']); return out
