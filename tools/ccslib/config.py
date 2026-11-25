"""config.py - GUI settings + profiles in tools/work/gui_settings.json (missing keys fall back to DEFAULTS).

"paths" holds the configurable locations (see paths.py); saving settings re-reads them (paths.reload()).
A profile is a set of overrides applied on top of the base settings when a session starts: {'proxy': {...}, 'guard': {...}, 'watchers': {...}}.
"""
import copy, json, os
from . import pack, paths

DEFAULTS = dict(
    profile='Default',
    paths=dict(game_root='', cache_dir='', mirror_dir='', player_cfg='', game_exes='', kill_exes=''),   # '' = not set / derived (see paths.py)
    proxy=dict(max_raw_mib=4096, budget_gib=120, retries=3, origin=True, offline=False, upstream_ip='', port=80, keep=True),   # keep = pieces fetched while playing are written into the offline copy (when there is one)
    guard=dict(enabled=True, limit_gib=100, action='kill', interval=5),
    hosts=dict(on_exit='ask'),            # ask | keep | remove  (what to do with the hosts override when the session is stopped / GUI closed)
    watchers=dict(netwatch=False),
    mirror=dict(workers=4, tier=4096, budget_gib=0, min_free_gib=40, max_rps=50, retries=4),
    # texture pack (Texture pack tab): scope = which chunk lists, level = detail cut-off; with link_caps the level also sets mirror.tier and proxy.max_raw_mib (see effective())
    pack=dict(scope='sp', packages=['sp'], level='ultra', link_caps=True, limit_mbps=0, daily_gib=0, workers=0, line_mbps=50, link_wait_s=0, keep_free_gib=20),   # keep_free_gib: a download stops (and says so) before the drive has less than this free
    profiles={},                          # user-defined profiles (name -> overrides), saved from the Dashboard
    log_max_mb=25,                        # rotate a log at session start when it is larger (0 = never); 3 old copies are kept
    keep_running_on_close=False,
    bulk_ack='',                          # version of the bulk-download notice the user accepted
    guide=dict(enabled=False, path='', ms=[], skipped=[], confirmed_root='', offered='', simple=False, summary={}, ab=0),     # optional guided setup (see guide.py)
    notice_ack='',                        # version of the research/responsibility notice the user has seen
    ui=dict(reduce_motion=False, language='auto'),   # language: 'auto' (follow Windows) or a code from i18n.CODES;         # look and feel: no animations when True (Windows' own animation switch is honoured too)
)

# "Play only from my offline copy" is the base setting proxy.offline, not a profile: profiles leave it alone (only the research profiles below set it on purpose),
# so changing the detail level or picking another profile can no longer switch a player back to the internet (issue #77).
BUILTIN_PROFILES = {
    'Default': dict(proxy=dict(origin=True)),                                # mirror first; upstream for misses unless "offline only" is on
    'Offline test': dict(proxy=dict(origin=True, offline=True)),             # mirror only; any miss is a 404 so a mirror gap shows immediately
    'Capture': dict(proxy=dict(origin=False, offline=False)),                # no mirror: everything from the CDN (new-content runs)
    'Standard HD (1440p class)': dict(proxy=dict(origin=True), pack=dict(level='standard')),   # chunks > 4 MiB raw are withheld (404): the engine keeps the smaller mip
    'Ultra (4K class)': dict(proxy=dict(origin=True), pack=dict(level='ultra')),
}
OLD_OFFLINE_PROFILE = 'Slow link - offline mirror'                          # up to 0.4.12: offline-only was this profile; load() turns it into the setting
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
    return migrate(cfg)


def migrate(cfg):
    """Settings from older versions: the "Slow link - offline mirror" profile becomes proxy.offline on + the Default profile, and a saved profile no longer carries
    proxy.offline (a profile saved while online used to switch an offline player back to the internet)."""
    if cfg.get('profile') == OLD_OFFLINE_PROFILE: cfg['proxy']['offline'] = True; cfg['proxy']['origin'] = True; cfg['profile'] = 'Default'
    for prof in (cfg.get('profiles') or {}).values():
        if isinstance(prof, dict) and isinstance(prof.get('proxy'), dict): prof['proxy'].pop('offline', None)
    (cfg.get('profiles') or {}).pop(OLD_OFFLINE_PROFILE, None)
    return cfg


def offline_only(cfg):
    """True when the session serves only from the offline copy (nothing goes to the internet)."""
    return bool(effective_proxy(cfg).get('offline'))


def set_offline_only(cfg, on):
    """Turn "play only from my offline copy" on or off (base setting; the mirror is always used when it is on)."""
    cfg['proxy']['offline'] = bool(on)
    if on: cfg['proxy']['origin'] = True
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
    e = effective(cfg); out = {sec: dict(e[sec]) for sec in SECTIONS if sec != 'pack'}; out['pack'] = dict(level=e['pack']['level'])
    out['proxy'].pop('offline', None); return out                           # offline-only stays the player's own setting, whatever profile is picked later
