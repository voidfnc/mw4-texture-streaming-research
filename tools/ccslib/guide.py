"""guide.py - the optional guided setup for first-time users.

Two halves, both free of any GUI code so they can be tested on their own:

  * finding the game folder: look in the usual places and *offer* what looks like the game (structure only, no folder names assumed); the user always confirms
    and can browse to any folder, even one that does not look right
  * the checklist: `evaluate(state, facts)` turns the real state of the PC (facts) plus what the user already did (state, stored in the settings) into the list of
    steps with a status each. Steps finish by themselves when their check passes; nothing here changes anything on the PC.

state (stored under "guide" in gui_settings.json):
  enabled         show the panel on the Dashboard
  path            '' | 'quick' | 'offline'   what the user chose in step 1
  ms              milestones reached (session / game / after); they stay reached when the session is stopped afterwards
  skipped         steps the user skipped (pack / game / after)
  confirmed_root  a game folder the user said to use although it did not look like one
  offered         version for which the first-run offer was shown
  simple          Simple view: hide the advanced tabs and the detailed counters
  summary         numbers of the last finished session (requests, from the mirror, ...), for the "what happened" explanation
  ab              the step the before/after test is on
"""
import copy, glob, os, re, time
from . import paths

STEP_IDS = ('path', 'folder', 'preflight', 'pack', 'session', 'game', 'after')
SKIPPABLE = ('pack', 'game', 'after')
DEFAULT_STATE = dict(enabled=False, path='', ms=[], skipped=[], confirmed_root='', offered='', simple=False, summary={}, ab=0)
PATHS = ('quick', 'offline')

TITLES = dict(path='Choose how to start', folder='Find your game folder', preflight='Check this PC', pack='Texture pack (optional)', session='Start the session',
              game='Play', after='When you are done')
PATH_TEXT = dict(
    quick='Quick fix (recommended): no big download. The game streams its texture pieces through a small helper on this PC while you play.',
    offline='Offline copy: download the texture pack once (about 54 to 82 GB) and play from disk. Good for slow or metered connections.')
PATH_SHORT = 'Quick fix (recommended): no big download, the game streams its textures while you play. Offline copy: download the pack once (54 to 82 GB) and play from disk.'
MIN_FREE_GIB = dict(quick=2.0, offline=20.0)
GAME_REQUESTS = 20            # a game start asks for hundreds of pieces; the Doctor's own checks ask for one or two
SKIP_DIRS = {'windows', '$recycle.bin', 'system volume information', 'programdata', 'recovery', 'perflogs', 'appdata'}


def numbers(d):
    """The number-valued entries of a dict (anything else is dropped)."""
    return {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)} if isinstance(d, dict) else {}


def new_state(**kw):
    s = copy.deepcopy(DEFAULT_STATE); s.update(kw); return s


def clean_state(st):
    """A well-formed copy of whatever was stored (missing or wrong-typed keys fall back to the defaults)."""
    s = new_state()
    if isinstance(st, dict):
        for k, d in DEFAULT_STATE.items():
            v = st.get(k, d)
            if isinstance(d, bool): s[k] = bool(v)
            elif isinstance(d, str): s[k] = v if isinstance(v, str) else d
            elif isinstance(d, list): s[k] = [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
            elif isinstance(d, dict): s[k] = numbers(v)
            elif isinstance(d, int): s[k] = max(0, v) if isinstance(v, int) and not isinstance(v, bool) else d
    if s['path'] not in ('',) + PATHS: s['path'] = ''
    return s


# ------------------------------------------------------------------------------------------------ finding the game folder

def score_folder(root):
    """0 = does not look like the game, 1 = a known game process name is in it, 2 = it has a cod26/ or sp26/ folder, 3 = and the CDN chunk lists are there too."""
    try:
        if not root or not os.path.isdir(root): return 0
        has_dir = any(os.path.isdir(os.path.join(root, d)) for d in ('cod26', 'sp26'))
        has_exe = any(os.path.isfile(os.path.join(root, e)) for e in paths.GAME_EXES)
        if not has_dir and not has_exe: return 0
        if not has_dir: return 1
        lists = glob.glob(os.path.join(root, 'cod26', '*_cdn.xpak')) + glob.glob(os.path.join(root, 'sp26', '*_cdn.xpak'))
        return 3 if lists else 2
    except OSError:
        return 0


def parse_libraryfolders(text):
    """Library folders listed in Steam's libraryfolders.vdf."""
    return [m.replace('\\\\', '\\') for m in re.findall(r'"path"\s+"((?:[^"\\]|\\.)*)"', text or '')]


def steam_common_dirs(roots=None):
    """Existing <library>\\steamapps\\common folders. `roots` = Steam install folders to start from (default: registry and the usual places). Never raises."""
    if roots is None:
        roots = []
        try:
            import winreg
            for hive, sub, name in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'), (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
                                    (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath')):
                try:
                    with winreg.OpenKey(hive, sub) as k: roots.append(str(winreg.QueryValueEx(k, name)[0]))
                except OSError: pass
        except ImportError: pass
        for env in ('ProgramFiles(x86)', 'ProgramFiles'):
            if os.environ.get(env): roots.append(os.path.join(os.environ[env], 'Steam'))
    libs = []
    for r in roots:
        libs.append(r)
        try:
            with open(os.path.join(r, 'steamapps', 'libraryfolders.vdf'), encoding='utf-8', errors='replace') as f: libs += parse_libraryfolders(f.read())
        except OSError: pass
    out = []
    for lib in libs:
        c = os.path.normpath(os.path.join(lib, 'steamapps', 'common'))
        if os.path.isdir(c) and os.path.normcase(c) not in [os.path.normcase(x) for x in out]: out.append(c)
    return out


def fixed_drives():
    """Roots of the fixed (non-network, non-removable) drives."""
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives(); out = []
        for i in range(26):
            if mask >> i & 1:
                root = f'{chr(65 + i)}:\\'
                if ctypes.windll.kernel32.GetDriveTypeW(root) == 3: out.append(root)
        return out
    except Exception:
        return [os.path.abspath(os.sep)]


def _subdirs(path):
    try:
        with os.scandir(path) as it: return [e.path for e in it if e.is_dir(follow_symlinks=False) and e.name.lower() not in SKIP_DIRS]
    except OSError:
        return []


def find_game_folders(drives=None, steam_roots=None, extra=(), deadline_s=4.0, clock=time.time):
    """Candidate game folders, best first: [{path, score, source}]. Looks at the configured folder, the folders around this tool, Steam libraries and the usual
    places on every fixed drive (the drive root, Games, Program Files, one folder level deeper). Judged by what is inside, not by name. Gives up after deadline_s."""
    t0 = clock(); seen = set(); out = []
    def late(): return clock() - t0 > deadline_s
    def consider(p, source):
        key = os.path.normcase(os.path.abspath(p))
        if key in seen: return
        seen.add(key); sc = score_folder(p)
        if sc: out.append(dict(path=os.path.normpath(p), score=sc, source=source))
    if paths.CONFIGURED: consider(paths.GAME_ROOT, 'current setting')
    p = paths.TOOLS
    for _ in range(3):
        p = os.path.dirname(p); consider(p, 'this tool\'s folder')
    for e in extra: consider(e, 'given')
    for common in steam_common_dirs(steam_roots):
        for d in _subdirs(common):
            if late(): break
            consider(d, 'Steam library')
    listed = set()
    def scan(base, depth, source):
        key = os.path.normcase(os.path.abspath(base))
        if depth == 0 or late() or key in listed: return
        listed.add(key)
        for d in _subdirs(base):
            if late(): return
            consider(d, source)
            common = os.path.join(d, 'steamapps', 'common')          # a Steam library anywhere on the way
            if os.path.isdir(common): scan(common, 1, 'Steam library')
            scan(d, depth - 1, source)
    for drv in (fixed_drives() if drives is None else drives):
        for name in ('Games', 'Program Files', 'Program Files (x86)'): scan(os.path.join(drv, name), 2, name)
        scan(drv, 2, 'drive ' + (os.path.splitdrive(drv)[0] or drv))
    order = {'current setting': 0, "this tool's folder": 1, 'given': 2, 'Steam library': 3}
    out.sort(key=lambda c: (-c['score'], order.get(c['source'], 9), c['path'].lower()))
    return out


def describe_candidate(c):
    how = {3: 'looks complete', 2: 'has the game folders, but no chunk lists', 1: 'has a game program, but not the usual folders'}.get(c['score'], '')
    return f"{c['path']}   -   {how}   ({c['source']})"


# ------------------------------------------------------------------------------------------------ the checklist

def live_session(f): return bool(f.get('proxy_ready') and f.get('hosts_ok') and f.get('resolve_ok'))


def advance(state, f):
    """New state with the milestones the facts prove (idempotent; milestones never go away on their own)."""
    s = clean_state(state); ms = set(s['ms']); had_after = 'after' in ms
    if live_session(f): ms.add('session')
    if 'session' in ms and live_session(f) and ((f.get('game_seen') and f.get('requests', 0) > 0) or f.get('requests', 0) >= GAME_REQUESTS): ms.add('game')      # a game program we do not know by name is not recognised, but the traffic proves it
    if 'session' in ms and ('game' in ms or 'game' in s['skipped']) and not f.get('proxy_alive'): ms.add('after')
    s['ms'] = [x for x in ('session', 'game', 'after') if x in ms]
    if 'after' in ms and not f.get('proxy_alive') and numbers(f.get('last_stat')) and (not had_after or numbers(f.get('last_stat')) != s['summary']): s['summary'] = numbers(f.get('last_stat'))   # what the session just ended with
    return s


def skip(state, step):
    s = clean_state(state)
    if step in SKIPPABLE and step not in s['skipped']: s['skipped'].append(step)
    return s


def restart(state):
    """Run the guide again from the session step (keeps the chosen path, the game folder confirmation and the on/off setting)."""
    s = clean_state(state); s['ms'] = []; s['skipped'] = []; s['summary'] = {}; return s


def same_path(a, b):
    return bool(a) and bool(b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def folder_ok(state, f):
    return bool(f.get('configured') and f.get('folder_exists') and (f.get('folder_score', 0) >= 1 or same_path(state.get('confirmed_root'), f.get('folder_root'))))


def evaluate(state, f):
    """-> [dict(id, n, title, status, detail, actions, skippable)]; status = done | running | skipped | current | todo. Steps that do not apply are left out."""
    st = clean_state(state); ms = set(st['ms']); sk = set(st['skipped']); path = st['path']; live = live_session(f)
    rows = []
    def add(id, done, detail, actions=(), running=False):
        rows.append(dict(id=id, n=len(rows) + 1, title=TITLES[id], done=bool(done), running=bool(running) and not done, skipped=id in sk and not done, detail=detail,
                         actions=list(actions), skippable=id in SKIPPABLE))
    # 1 path
    add('path', path in PATHS, PATH_SHORT if not path else PATH_TEXT[path].split(':')[0] + ' chosen.', [('choose_quick', 'Quick fix'), ('choose_offline', 'Offline copy')] if not path else [])
    # 2 folder
    fok = folder_ok(st, f)
    if fok:
        sc = f.get('folder_score', 0); note = '' if sc >= 3 else ' Some expected files were not found; the quick fix does not need them, the offline copy does.'
        d, a = f"Game folder: {f.get('folder_root', '')}.{note}", [('find_folder', 'Change...')]
    elif not f.get('configured'): d, a = 'I do not know where the game is yet. I will look in the usual places and you confirm what I find. You can also browse to it.', [('find_folder', 'Find my game folder')]
    elif not f.get('folder_exists'): d, a = f"That folder does not exist: {f.get('folder_root', '')}", [('find_folder', 'Find my game folder')]
    else: d, a = f"{f.get('folder_root', '')} does not look like the game folder (no cod26 or sp26 inside). Pick another one, or use it anyway if you know it is right.", [('find_folder', 'Find my game folder'), ('confirm_anyway', 'Use it anyway')]
    add('folder', fok, d, a)
    # 3 preflight
    problems = []
    if f.get('blocked_by'): problems.append(f"port {f.get('port', 80)} is in use by {f['blocked_by']} (the Doctor can free it)")
    free = f.get('free_gib'); need = MIN_FREE_GIB.get(path or 'quick', 2.0)
    if free is not None and free < need: problems.append(f'only {free:.0f} GiB free on this drive (about {need:g} GiB needed)')
    if f.get('game_running') and not live: problems.append('the game is running: close it, start the session, then launch it again')
    setup = f.get('game_setup') == 'needed'
    if setup: problems.append('the game folder needs one small setup so the game uses the streamed textures (online mode and a cache link)')
    pdone = live or 'session' in ms or (fok and not problems)
    acts = ([('game_setup', 'Set up the game')] if setup else []) + ([('doctor', 'Open the Doctor')] if problems and (not setup or len(problems) > 1) else [])
    add('preflight', pdone, 'Port, disk space, the game folder setup and the game being closed all look fine.' if not problems else 'Needs attention: ' + '; '.join(problems) + '.', acts)
    # 4 pack (offline path only)
    if path == 'offline':
        tot, got = f.get('pack_total'), f.get('pack_stored')
        complete = bool(tot) and got is not None and got >= tot
        if complete: d = f'All {tot:,} texture pieces are on disk.'
        elif f.get('mirror_alive'):
            rt = f.get('pack_run_total')      # live progress of the run that is going now (the plan above only refreshes when a run ends)
            d = (f"Downloading... {f.get('pack_run_done') or 0:,} of {rt:,} pieces in this run. " if rt else 'Downloading... ') + 'You can pause and resume in the Texture pack tab, and carry on with the next steps meanwhile.'
        else: d = 'Choose how much to download and press Download (campaign only is about 54 to 82 GB; pause and resume any time). Or skip it and build the copy later.'
        add('pack', complete, d, [('goto_pack', 'Open Texture pack')] if not complete else [], running=bool(f.get('mirror_alive')))
    # 5 session
    if live: d, a = 'The session is running: the helper is up and the hosts file points the game at it.', [('stop_session', 'Stop session')]
    elif f.get('proxy_alive'): d, a = 'Starting... if this stays red, open the Doctor.', [('doctor', 'Open the Doctor')]
    elif 'session' in ms: d, a = 'The session ran and is stopped now.', []
    else:
        d = ('Press Start session. Windows will show its permission prompt, because the hosts file is protected. This tool adds one marked block to it and backs the file up first; '
             '"Restore hosts" undoes it.'); a = [('start_session', 'Start session')]
    add('session', live or 'session' in ms, d, a if not (live or 'session' in ms) else [])
    # 6 game
    if not live and 'game' not in ms: d, a = 'The session is not running. Start it first, then launch the game.', [('start_session', 'Start session')]
    elif f.get('game_running'): d, a = f"Game detected. {f.get('requests', 0):,} texture pieces delivered so far. Keep this window open while you play.", []
    elif f.get('game_seen') and f.get('requests', 0) == 0: d, a = 'The game ran but asked for nothing through the helper. The Doctor can tell you why; or skip this step.', [('doctor', 'Open the Doctor')]
    elif 'game' in ms: d, a = f"Done: {f.get('requests', 0)} texture pieces were delivered to the game." if f.get('requests') else 'The game was delivered its texture pieces.', []
    else: d, a = 'Launch the game normally now. Leave this window open while you play.', []
    add('game', 'game' in ms, d, a)
    # 7 after
    if 'after' in ms: d, a = 'Stopped. Your session report is in the Report tab.', [('goto_report', 'Open the report')]
    elif 'game' in ms or 'game' in sk: d, a = 'When you are done playing, press Stop session. You will be asked whether to put the hosts file back.', [('stop_session', 'Stop session')] if live else []
    else: d, a = 'After you quit the game.', []
    add('after', 'after' in ms, d, a)
    # statuses: the first step that is neither done, running nor skipped is the current one
    cur_found = False
    for r in rows:
        if r['done']: r['status'] = 'done'
        elif r['skipped']: r['status'] = 'skipped'
        elif r['running']: r['status'] = 'running'
        elif not cur_found: r['status'] = 'current'; cur_found = True
        else: r['status'] = 'todo'
    return rows


def all_passed(rows): return all(r['status'] in ('done', 'skipped', 'running') for r in rows)


# ------------------------------------------------------------------------------------------------ Simple view, words, spotlight

SIMPLE_TABS = ('Dashboard', 'Texture pack', 'Doctor', 'Report', 'Settings')           # what Simple view keeps; every other tab is hidden until Full view
SIMPLE_COUNTERS = ('req', 'upok', 'err', 'sess')                                      # and of the Dashboard counters
SIMPLE_COUNTER_LABELS = dict(req='Pieces requested', upok='From the internet', err='Errors', sess='Session time')

GLOSSARY = (
    ('Session', 'The time between "Start session" and "Stop session". While it runs, the helper is up and the hosts entry sends the game\'s texture requests to it.'),
    ('Helper (proxy)', 'A small program on this PC that answers the game\'s texture requests. It gets each piece from your copy on disk if you have one, otherwise from the internet.'),
    ('Hosts file', 'A Windows file that can override where a web address points. This tool adds one marked block to it so the game talks to the helper. "Restore hosts" takes the block out again, and a backup is made first.'),
    ('UAC prompt', 'The Windows window that asks "Do you want to allow this app to make changes?". The program shows it once, when it starts, because it edits the protected hosts file and the game folder. Answer Yes to continue.'),
    ('CDN', 'The servers the game downloads its textures from.'),
    ('Edge', 'One particular CDN server address. The tool measures a few and uses the fastest.'),
    ('Texture piece (chunk)', 'The game streams its textures in many small pieces. Each request from the game is for one piece.'),
    ('Streaming', 'Loading textures while you play instead of all at the start. What the game asks for depends on where you are and what it decides to show.'),
    ('Quick fix', 'No big download. The helper fetches the pieces the game asks for while you play.'),
    ('Offline copy (mirror)', 'A copy of the texture pieces on your own drive (about 54 to 82 GB). The game is served from it, so playing needs little or no internet.'),
    ('Detail level', 'A cut-off for very large pieces (the highest-detail versions). Ultra serves everything; Standard leaves the largest out, and the game keeps the smaller version.'),
    ('Connections (workers)', 'How many downloads run at the same time when building an offline copy. More is not always faster; the default is a safe starting point.'),
    ('Requests per second (req/s)', 'How often the tool asks the CDN for a piece. It is capped so it does not hammer the servers.'),
    ('Doctor', 'A checklist that tests everything this tool depends on (port, hosts entry, folders, internet) and offers a safe fix for each failing check.'),
    ('Game cache', 'The folder where the game keeps pieces it has already received (xpak_cache). The game recreates it if it is missing.'),
    ('Game setup', 'Two small changes in the game folder so the game uses the textures it is sent: its Steam emulator is set to online mode, and sp26\\xpak_cache is linked to the cache the game fills. Done once, after you confirm.'),
    ('Disk guard', 'Watches the game cache and stops the game if it grows past the limit you set, so the drive cannot fill up.'),
    ('Report', 'After a session the tool writes a summary of what the game asked for and what was delivered. It is found in the Report tab.'),
)

LIGHT_HELP = dict(
    hosts='Hosts: whether this tool\'s entry is in the Windows hosts file. OK means the game\'s texture requests are sent to the helper on this PC.',
    resolve='Resolver: what Windows answers when asked for the game\'s content address. "loopback" means it points at this PC (the redirect works). "not ours" means it does not (yet).',
    proxy='Proxy (the helper): the small program that hands the game its texture pieces. Green while it runs and answers.',
    port='Port: the helper listens on port 80, the normal web port. Red means another program is already using it.',
    mirror='Mirror: your local copy of texture pieces, and how many pieces it holds. "off" is normal with the quick fix.',
    guard='Guard: the disk guard watches the game cache and stops the game if it grows past your limit.',
    game='Game: whether the game is running right now.',
    disk='Disk: free space on the game\'s drive.')

COUNTER_HELP = dict(
    req='Requests: how many texture pieces the game has asked for since the session started.',
    mirror='From mirror: pieces served from your local copy.',
    upok='Upstream OK: pieces fetched from the internet (the CDN).',
    err='Errors: requests that failed even after retries. A few are normal, the game asks again.',
    retry='Retries: times the helper had to try the internet again for a piece.',
    cliabort='Client aborts: the game closed a request before the piece was fully sent. Normal when it changes its mind.',
    skip='Tier-skipped: pieces left out on purpose by your detail level. The game keeps the smaller version.',
    miss='Misses / 404: pieces that were not available (for example a gap in an offline copy).',
    mgib='Mirror GiB: data served from your local copy.',
    ugib='Upstream GiB: data fetched from the internet.',
    rps='Requests per second over the last 12 seconds.',
    sess='Session time: how long the helper has been running.')


def spot(rows, f):
    """Which control to highlight for the step the user is on: 'btn_start' | 'btn_stop' | 'btn_doctor' | 'tab:<name>' | None. Pure; the window does the highlighting."""
    cur = next((r for r in rows if r['status'] == 'current'), None)
    if not cur: return None
    i = cur['id']; live = live_session(f)
    if i == 'pack': return 'tab:Texture pack'
    if i == 'preflight' and any(a[0] == 'doctor' for a in cur['actions']): return 'btn_doctor'
    if i in ('session', 'game') and not live and not f.get('proxy_alive'): return 'btn_start'
    if i == 'after' and live and not f.get('game_running'): return 'btn_stop'          # not while the game is still being played
    return None


# ------------------------------------------------------------------------------------------------ when something goes wrong

def _has(text, *words): return any(w in text for w in words)


def coach(state, f, last=''):
    """Plain-language help for what is going wrong now: [dict(id, title, text, actions)], at most two. `last` = the last warning or error the tool printed.
    Nothing here acts on its own; the buttons call the usual handlers."""
    st = clean_state(state); low = ' '.join(str(last or '').lower().split()); cards = []
    def card(id, title, text, actions): cards.append(dict(id=id, title=title, text=text, actions=list(actions)))
    if 'session' in st['ms'] and f.get('proxy_alive') and not f.get('hosts_ok'):
        card('hosts_lost', 'The hosts entry is gone', 'The helper is running, but the hosts file no longer points the game at it, so the game goes straight to the internet. Security software sometimes removes it. '
             'Put it back, and if it keeps disappearing allow this tool in your security software.', [('apply_hosts', 'Put it back (UAC)'), ('doctor', 'Open the Doctor')])
    live = live_session(f)
    if live and f.get('game_running') and f.get('requests', 0) == 0 and f.get('game_secs', 0) >= 90:
        card('no_traffic', 'The game is running but nothing reached the helper', 'Most often the game was started before the session. Close it and launch it again. '
             'Otherwise a VPN, "secure DNS" or security software may be bypassing the hosts file. The Doctor tests exactly that.', [('doctor', 'Open the Doctor')])
    if f.get('free_gib') is not None and f['free_gib'] < 5 and (live or f.get('game_running')):
        card('disk_low', 'Very little disk space left', f"Only {f['free_gib']:.1f} GiB free. The game cache grows while you play, and the disk guard will stop the game at its limit. Free some space on the drive.", [])
    if last and not any(c['id'] in ('hosts_lost',) for c in cards):
        if _has(low, 'denied', 'errno 13', 'winerror 5', 'not permitted'):
            card('hosts_denied', 'Windows refused to change the hosts file', 'Press the button and answer Yes on the Windows prompt. If it is refused again, security software with hosts-file protection is the usual cause: '
                 'allow this tool in it (or pause it briefly), and check the file is not read-only. Nothing was changed.', [('start_session', 'Try again'), ('doctor', 'Open the Doctor')])
        elif _has(low, 'cancel', 'declined', 'uac'):
            card('uac_cancelled', 'The Windows permission prompt was closed', 'The hosts file is protected, so Windows asks before any change. Press the button and answer Yes.', [('start_session', 'Try again')])
        elif _has(low, 'timed out', 'unreachable', 'getaddrinfo', 'connection refused', 'no route', 'upstream', 'cdn'):
            card('cdn_unreachable', 'The game\'s servers did not answer', 'Check your internet connection and any VPN or firewall. The Doctor shows which address the helper tried.', [('doctor', 'Open the Doctor')])
        elif _has(low, 'port 80', 'address already in use', 'is in use by'):
            card('port_busy', 'Another program is using the port', 'The helper needs port 80 for itself. The Doctor shows which program has it and can free it.', [('doctor', 'Open the Doctor')])
        elif _has(low, 'game folder', 'does not look like'):
            card('wrong_folder', 'That does not look like the game folder', 'Look for the folder that holds cod26 or sp26, or let the tool look for it.', [('find_folder', 'Find my game folder')])
        elif _has(low, 'not ready'):
            card('not_ready', 'The session did not come up', 'The Doctor lists which check failed and offers a fix for each one.', [('doctor', 'Open the Doctor')])
    return cards[:2]


# ------------------------------------------------------------------------------------------------ what happened, and a way to check

def explain(summary):
    """The short "what happened" text for a finished session: a list of lines (empty when nothing is known)."""
    s = numbers(summary); req = int(s.get('req', 0))
    if not s: return []
    if req == 0:
        return ['Nothing reached the helper during the last session, so the game was not served by it.', 'The Doctor can tell you why (most often the game was already running when the session started).']
    mir, up, err, skip = int(s.get('mirror', 0)), int(s.get('upok', 0)), int(s.get('err', 0)), int(s.get('skip', 0))
    mins = int(s.get('secs', 0) // 60)
    out = [f"The game asked for {req:,} texture pieces" + (f' in about {mins} min' if mins >= 1 else '') + '. ' +
           (f'{mir:,} came from your offline copy and {up:,} from the internet.' if mir else f'{up:,} were fetched from the internet.')]
    bits = ['No failed requests.' if not err else f'{err:,} requests failed (the game asks again, a few are normal).']
    if skip: bits.append(f'{skip:,} pieces were left out on purpose by your detail level.')
    out.append(' '.join(bits))
    out.append('That is what the tool can see: which pieces the game asked for and that they were delivered. How the picture looks is decided by the game, so to judge it on your PC use the before/after test.')
    return out


AB_STEPS = (
    dict(id='spot', title='Pick a spot', text='Choose a place in the game you can come back to: somewhere with plenty of distant or detailed surfaces, at the same time of day. '
         'Keep the graphics settings the same for the whole test, and close the game. Optional for a strict comparison: rename the game cache folder (xpak_cache) before each run, the game makes a new one.', action=None),
    dict(id='before', title='Before: tool off', text='Press the button to put the hosts file back (no redirect). Launch the game, go to your spot, wait five minutes so the textures settle, and take a screenshot. '
         'Save it as before-1 in the folder the last step opens.', action=('hosts_remove', 'Switch the tool off (Restore hosts)')),
    dict(id='after', title='After: tool on', text='Close the game. Press Start session, launch the game, go to the same spot, wait the same time and take a screenshot. Save it as after-1.', action=('start_session', 'Start session')),
    dict(id='compare', title='Compare', text='Put the two screenshots side by side at full size and look at distant surfaces, signs and small details. Some setups show a difference and some do not; this test tells you for yours. '
         'Open the Report tab to see what the game asked for in the "after" run.', action=('open_shots', 'Open the screenshots folder')),
)


def ab_view(stage, summary=None):
    """-> dict(n, total, title, text, action, first, last) for step `stage` (clamped) of the before/after test."""
    i = min(max(int(stage) if isinstance(stage, int) else 0, 0), len(AB_STEPS) - 1); s = AB_STEPS[i]; text = s['text']
    if s['id'] == 'compare' and explain(summary): text += ' Last session: ' + explain(summary)[0]
    return dict(n=i + 1, total=len(AB_STEPS), title=s['title'], text=text, action=s['action'], first=i == 0, last=i == len(AB_STEPS) - 1)


def ab_dir(): return os.path.join(paths.WORK, 'ab-test')
