"""Shared paths/constants for the CCS tooling (ccsgui.py, ccshosts.py, ccs*.py tools, tests).

Locations are CONFIGURED, not hard-coded: the GUI (Game tab) stores them in tools/work/gui_settings.json under "paths":
  game_root   folder that contains the game (cod26/, sp26/ *_cdn.xpak lists, xpak_cache/ ...)
  cache_dir   engine stream cache (default <game_root>/xpak_cache)
  mirror_dir  chunk mirror (default <game_root>/mirror) - can live on another drive
  player_cfg  player config file (default %LOCALAPPDATA%\\Activision\\Call of Duty\\players\\s.1.0.cod26.txt)
  game_exes   process names that mean "game running"; kill_exes = what diskguard may terminate
Every CLI tool imports this module, so they follow the same settings. If game_root is not configured the tools fall back to the
layout they ship in (tools/ inside the game folder) and CONFIGURED stays False - the GUI then asks for setup.

Environment overrides (tests / one-off use): CCS_GAME_ROOT, CCS_CACHE_DIR, CCS_MIRROR_DIR, CCS_PLAYER_CFG, CCS_HOSTS_PATH, CCS_WORK.
"""
import json, os, sys

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))           # where these scripts live
WORK = os.environ.get('CCS_WORK') or os.path.join(TOOLS, 'work')                  # logs, pid files, settings, reports, hosts backups
RUN = os.path.join(WORK, 'run')
HOSTS_BACKUPS = os.path.join(WORK, 'hosts-backups')
SESSIONS = os.path.join(WORK, 'sessions')
SETTINGS_FILE = os.path.join(WORK, 'gui_settings.json')
HOST = 'cod-assets.cdn.callofduty.com'
DEFAULT_EXES = ['sp26-cod.exe', 'cod.exe']
DEFAULT_KILL = ['sp26-cod.exe']
PY = sys.executable

# filled by reload()
CONFIGURED = False
GAME_ROOT = ROOT = XPAK_CACHE = MIRROR = PLAYER_CFG = ''
GAME_EXES = tuple(DEFAULT_EXES); KILL_EXES = tuple(DEFAULT_KILL)
SOURCES = {}          # which setting each location came from: 'env' | 'settings' | 'derived' | 'fallback'


def user_paths():
    try: return dict(json.load(open(SETTINGS_FILE, encoding='utf-8')).get('paths') or {})
    except Exception: return {}


def default_player_cfg():
    return os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Activision', 'Call of Duty', 'players', 's.1.0.cod26.txt')


def _names(v, default):
    if isinstance(v, str): v = [x.strip() for x in v.replace(';', ',').split(',')]
    v = [x for x in (v or []) if x]
    return tuple(v) if v else tuple(default)


def reload(override=None):
    """Re-read the settings file (or `override`, a paths dict) and recompute every location."""
    global CONFIGURED, GAME_ROOT, ROOT, XPAK_CACHE, MIRROR, PLAYER_CFG, GAME_EXES, KILL_EXES
    u = dict(override) if override is not None else user_paths(); env = os.environ; src = {}
    gr = env.get('CCS_GAME_ROOT') or u.get('game_root') or ''
    src['game_root'] = 'env' if env.get('CCS_GAME_ROOT') else ('settings' if u.get('game_root') else 'fallback')
    CONFIGURED = src['game_root'] != 'fallback'
    if not gr: gr = os.path.abspath(os.path.join(TOOLS, '..'))
    GAME_ROOT = ROOT = os.path.normpath(gr)
    def pick(key, envname, derived):
        v = env.get(envname) or u.get(key)
        src[key] = 'env' if env.get(envname) else ('settings' if u.get(key) else 'derived')
        return os.path.normpath(v) if v else derived
    XPAK_CACHE = pick('cache_dir', 'CCS_CACHE_DIR', os.path.join(GAME_ROOT, 'xpak_cache'))
    MIRROR = pick('mirror_dir', 'CCS_MIRROR_DIR', os.path.join(GAME_ROOT, 'mirror'))
    PLAYER_CFG = pick('player_cfg', 'CCS_PLAYER_CFG', default_player_cfg())
    GAME_EXES = _names(u.get('game_exes'), DEFAULT_EXES); KILL_EXES = _names(u.get('kill_exes'), DEFAULT_KILL)
    SOURCES.clear(); SOURCES.update(src)


def detect_game_root():
    """Best guess for the game folder: the parent of tools/ if it looks like one (never used silently by the GUI - it is offered)."""
    p = os.path.abspath(os.path.join(TOOLS, '..'))
    return p if looks_like_game(p) else ''


def looks_like_game(root):
    return bool(root) and os.path.isdir(root) and (any(os.path.isdir(os.path.join(root, d)) for d in ('cod26', 'sp26')) or any(os.path.exists(os.path.join(root, e)) for e in GAME_EXES))


def validate():
    """-> list of dict(name, level ok|warn|fail, detail) for the configured locations (read-only)."""
    import glob
    out = []; add = lambda n, l, d: out.append(dict(name=n, level=l, detail=d))
    if not CONFIGURED: add('Game folder', 'fail', 'not configured yet (Game tab -> Locations). Tools would fall back to the folder they live in: ' + GAME_ROOT)
    elif not os.path.isdir(GAME_ROOT): add('Game folder', 'fail', f'does not exist: {GAME_ROOT}')
    else: add('Game folder', 'ok', GAME_ROOT)
    lists = glob.glob(os.path.join(GAME_ROOT, 'cod26', '*_cdn.xpak')) + glob.glob(os.path.join(GAME_ROOT, 'sp26', '*_cdn.xpak'))
    add('CDN chunk lists', 'ok' if lists else 'warn', f'{len(lists)} *_cdn.xpak files under cod26/ and sp26/' if lists else 'none found under cod26/ or sp26/. The proxy still works without them; the mirror and the detail-level cap need them (wrong game folder?)')
    exes = [e for e in GAME_EXES if os.path.exists(os.path.join(GAME_ROOT, e))]
    add('Game executable', 'ok' if exes else 'info', ', '.join(exes) if exes else f'none of {", ".join(GAME_EXES)} in the folder (process names are matched, so this is only informational)')
    add('Engine cache', 'ok' if os.path.isdir(XPAK_CACHE) else 'warn', XPAK_CACHE + ('' if os.path.isdir(XPAK_CACHE) else '  (missing - the game creates it on first run)'))
    add('Mirror folder', 'ok' if os.path.isdir(MIRROR) else 'warn', MIRROR + ('' if os.path.isdir(MIRROR) else '  (missing - created by the first mirror run)'))
    add('Player config', 'ok' if os.path.isfile(PLAYER_CFG) else 'warn', PLAYER_CFG + ('' if os.path.isfile(PLAYER_CFG) else '  (not found - settings snapshot in reports will be empty)'))
    return out


def hosts_path():
    return os.environ.get('CCS_HOSTS_PATH') or os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'drivers', 'etc', 'hosts')


def ensure_dirs():
    for d in (WORK, RUN, HOSTS_BACKUPS, SESSIONS):
        os.makedirs(d, exist_ok=True)


reload()
