"""doctor.py - preflight checks. Each check -> dict(name, level 'ok'|'warn'|'fail'|'info', detail). Never raises, never writes."""
import http.client, json, os, random, shutil, sqlite3, subprocess, sys
from . import config, hosts, mirrordb, pack, paths, procs, proxyctl, upstream


def _c(name, level, detail, fix=None):
    """fix = (action, arg) understood by session.run_fix, or None."""
    return dict(name=name, level=level, detail=detail, fix=fix)


def check_hosts():
    try: st = hosts.status()
    except Exception as e: return [_c('Hosts override', 'fail', f'cannot read hosts file: {hosts.friendly(e)}')]
    s = st['state']; out = []
    if s == 'ABSENT' and not os.path.exists(st['path']): out.append(_c('Hosts override', 'fail', 'not present, and the hosts file itself does not exist on this PC (some tweak tools delete it) - Apply creates it; the game resolves the CDN host IPv6-only and never connects without it', ('hosts_apply', None)))
    elif s == 'ABSENT': out.append(_c('Hosts override', 'fail', 'not present - the game resolves the CDN host IPv6-only and never connects (Hosts tab -> Apply)', ('hosts_apply', None)))
    elif s == 'FOREIGN': out.append(_c('Hosts override', 'warn', 'present as hand-added lines outside the managed block (works; Apply adopts them into the block)'))
    elif s == 'PARTIAL': out.append(_c('Hosts override', 'fail', 'managed block is missing the ::1 or 127.0.0.1 line', ('hosts_apply', None)))
    elif s == 'MIXED': out.append(_c('Hosts override', 'warn', 'managed block plus duplicate hand-added lines (Apply cleans this up)'))
    else: out.append(_c('Hosts override', 'ok', 'managed block present (::1 + 127.0.0.1)'))
    r = hosts.resolve_check(); applied = s in ('OK', 'FOREIGN', 'MIXED'); acl = None; why = None
    if not r['ok'] and applied:
        try: why = hosts.diagnose(st['path']); acl = hosts.acl_facts(st['path']) if os.name == 'nt' else None
        except Exception: pass
    no_read = bool(acl) and acl.get('dns_client_can_read') is False
    known = bool(why) or no_read              # a cause we can name is a failure; an unexplained mismatch is a warning, because the game may not use the same lookup as this check
    out.append(_c('Resolver', 'ok' if r['ok'] else ('fail' if applied and known else 'warn'),
                  f"v4={r['v4']} v6={r['v6']}" + ('' if r['ok'] else ' (expected 127.0.0.1 / ::1; try Flush DNS)'),
                  ('flush_dns', None) if not r['ok'] and applied else None))
    if no_read:
        out.append(_c('Hosts file permissions', 'fail', 'the hosts file is not readable by the Windows DNS Client service (no read right for Everyone, Users, Authenticated Users or Network Service), so Windows ignores it. '
                      'Repair sets the permissions back to the folder default and keeps a copy of the old ones', ('hosts_acl', None)))
    elif acl and not r['ok']: out.append(_c('Hosts file permissions', 'ok', 'the DNS Client service can read the hosts file'))
    if not r['ok'] and applied:
        out.append(_c('Resolver diagnosis', 'info', 'the hosts file is saved as UTF-16, which Windows does not read; Apply writes it as plain UTF-8 and keeps a backup' if why and 'UTF-16' in why else
                      'the block is in the hosts file but Windows still answers from DNS, so something outside the file is overriding it: security software with hosts-file protection, a VPN or DNS tool that answers name lookups itself, '
                      'or a group policy. Flushing the DNS cache does not help then; pause that software for a minute and check again. The game may still use the hosts file: start it, and the log says if no texture request arrives'
                      if not no_read else 'Windows is not reading the hosts file at all (see the permissions row)'))
    return out


def check_port(cfg):
    port = cfg['proxy']['port']; own = procs.status('proxy'); owners = procs.port_owner(port)
    if not owners: return _c(f'Port {port}', 'ok' if not own['alive'] else 'fail', 'free' if not own['alive'] else 'proxy process alive but not listening')
    if own['alive'] and all(o['pid'] == own['pid'] for o in owners): return _c(f'Port {port}', 'ok', f"owned by our proxy (pid {own['pid']})")
    prot = [o for o in owners if procs.is_protected(o)]
    if prot:                                                       # Windows itself (System, pid 4): it cannot be ended; usually a Windows web service registered the port
        who = ', '.join(f"{o['name']}, pid {o['pid']}" for o in prot); svcs = procs.http_services()
        if svcs: return _c(f'Port {port}', 'fail', f"Port {port} is held by Windows itself ({who}). It cannot be ended like a program, but these Windows web services are running and may be the reason: {', '.join(n for _, n in svcs)}. "
                           'Stopping one frees the port; start it again later in services.msc if you use it.', ('stop_service', svcs[0][0]))
        return _c(f'Port {port}', 'fail', f"Port {port} is held by Windows itself ({who}), which usually means a Windows web service (IIS or similar) is registered on it. It cannot be ended like a program. "
                  'In an administrator command prompt, "netsh http show servicestate view=requestq" shows which program uses it; stop that service in services.msc, then check again.')
    return _c(f'Port {port}', 'fail', 'taken by ' + ', '.join(f"{o['name']} pid {o['pid']} ({o['addr']})" for o in owners), ('kill_port_owner', [(o['pid'], o['name']) for o in owners]))


def _mirror_rows(n=20):
    db = os.path.join(paths.MIRROR, 'index.sqlite')
    if not os.path.exists(db): return None, []
    c = mirrordb.connect_read(db, timeout=5)
    try:
        total = c.execute('select count(*) from chunks where status=1').fetchone()[0]
        ids = [r[0] for r in c.execute('select id from chunks where status=1 limit 5000')]
        rows = [c.execute('select id, wire, flag from chunks where id=?', (i,)).fetchone() for i in random.sample(ids, min(n, len(ids)))]
        return total, rows
    finally: c.close()


def check_mirror(cfg):
    if not cfg['proxy']['origin'] and 'Capture' == cfg.get('profile'): return _c('Mirror', 'info', 'not used by the Capture profile')
    try: total, rows = _mirror_rows()
    except Exception as e: return _c('Mirror', 'fail', f'index unreadable: {e}')
    if total is None:
        if config.effective_proxy(cfg).get('offline'): return _c('Mirror', 'fail', f'{paths.MIRROR}\\index.sqlite missing - this profile serves from the mirror only (build it in the Texture pack tab)')
        return _c('Mirror', 'info', 'no mirror yet - every chunk is fetched from the CDN while you play (fine for a first try); build one later in the Texture pack tab')
    bad = 0
    for sid, wire, flag in rows:
        i = sid & (2**64 - 1); p = os.path.join(paths.MIRROR, 'objects', f'{i & 0xff:02x}', f'{i:016x}_{wire:08x}_{flag}')
        if not (os.path.exists(p) and os.path.getsize(p) == wire): bad += 1
    return _c('Mirror', 'ok' if not bad else 'fail', f'{total} chunks stored; spot check {len(rows) - bad}/{len(rows)} objects present with the right size')


def check_proxy(cfg):
    port = cfg['proxy']['port']; s = proxyctl.fetch_stats(port)
    if not s:
        alive = procs.status('proxy')['alive']
        return [_c('Proxy', 'fail' if alive else 'warn', 'not answering on /__ccs/stats' + ('' if alive else ' (not started)'), ('restart_proxy' if alive else 'start_proxy', None))]
    a = s.get('args', {}); out = [_c('Proxy', 'ok', f"pid {s['pid']}  mirror={'on' if a.get('origin') else 'off'}  offline={bool(a.get('offline'))}  tier<={a.get('max_raw_mib')}MiB  mirror ids={s.get('mirror_ids')}")]
    try:
        total, rows = _mirror_rows(1)
        if rows:
            sid, wire, flag = rows[0]; i = sid & (2**64 - 1)
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=5); c.request('HEAD', f'/pc/iw9_3/23/{i & 0xff:02x}/{i:016x}_{wire:08x}_{flag}', headers={'X-CCS-Probe': '1'}); r = c.getresponse(); r.read(); c.close()
            ok = r.status == 200 and int(r.getheader('Content-Length', -1)) == wire
            out.append(_c('Proxy serves chunk', 'ok' if ok else 'fail', f"HEAD {i:016x} -> {r.status} len={r.getheader('Content-Length')} etag={r.getheader('ETag')} cod-key={r.getheader('x-amz-meta-cod-key')}"))
    except Exception as e:
        out.append(_c('Proxy serves chunk', 'fail', str(e)))
    return out


def check_pack(cfg):
    """Texture pack: does the mirror cover the selected scope + detail level, does the live proxy use that level, is there room to finish?"""
    out = []
    try:
        e = config.effective(cfg); pk = e['pack']; mib = pack.level_mib(pk['level']); lab = pack.LEVEL_LABELS.get(pk['level'], f"{mib:g} MiB")
        if not os.path.exists(os.path.join(paths.MIRROR, 'index.sqlite')): return [_c('Texture pack', 'info', f"{pk['scope']} / {lab}: no mirror index yet (Texture pack tab -> Download)")]
        pl = pack.plan(pk['scope'], pk.get('packages'), pk['level'], line_mbps=0); t = pl['total']
        base = f"scope {pk['scope']} / {lab}: {t['stored']:,} of {t['chunks']:,} chunks stored"
        if pl['missing']: out.append(_c('Texture pack lists', 'warn', 'chunk lists missing on this install: ' + ', '.join(pl['missing'])))
        if pack.lists_changed(): out.append(_c('Chunk lists', 'info', "the game's chunk lists changed since the mirror was last loaded (a game update); Texture pack -> Download adds the new chunks and keeps the ones you have"))
        if not t['pending']: out.append(_c('Texture pack', 'ok', base + ' - complete'))
        else:
            off = bool(e['proxy'].get('offline')); lvl = 'warn' if off else 'info'
            out.append(_c('Texture pack', lvl, base + f"; {t['pending']:,} chunks ({t['pending_gib']:.1f} GiB) not mirrored yet" + (' - OFFLINE profile: these will 404' if off else ' - they come from the internet until the mirror is complete')))
            if not pl['fits']: out.append(_c('Texture pack disk', 'fail', f"needs ~{pl['need_gib']:.0f} GiB, only {pl['free_gib']:.0f} GiB free on the mirror drive"))
        if pk['level'] == 'ultra' and pl['levels']['ultra']['gib'] > 64: out.append(_c('Texture pack vs engine cache', 'info', f"the full set is {pl['levels']['ultra']['gib']:.0f} GiB; the engine cache is capped by the in-game 'Allocated texture cache size' setting, so it may not keep it all - Standard HD fits more easily"))
        s = proxyctl.fetch_stats(e['proxy']['port'])
        if s:
            cap = s.get('args', {}).get('max_raw_mib')
            if cap is not None and pk.get('link_caps', True) and abs(float(cap) - mib) > 1e-6: out.append(_c('Detail level', 'warn', f'proxy runs with a {cap:g} MiB cap but the selected level is {mib:g} MiB - restart the proxy to apply it', ('restart_proxy', None)))
            else: out.append(_c('Detail level', 'ok', f"proxy cap {cap:g} MiB matches the level ({pk['level']})" if cap is not None else 'proxy cap unknown'))
    except Exception as ex: out.append(_c('Texture pack', 'warn', f'could not evaluate: {ex}'))
    return out


def check_upstream(offline=False, complete=False):
    """offline = the profile never uses the internet; complete = the offline copy holds every piece asked for. Either way an unreachable edge is not a problem."""
    try:
        ip, src = upstream.candidates_info()[0]; c = http.client.HTTPConnection(ip, 80, timeout=4); c.request('HEAD', '/', headers=upstream.headers()); r = c.getresponse(); r.read(); c.close()
        if src == 'fallback':
            return _c('Upstream CDN', 'warn', f'only the built-in fallback edge {ip} was found (no system or DNS answer); it may be far from you and slow. Remove the hosts override once, '
                                              'let the tool look the name up, and it will remember the nearest edge')
        return _c('Upstream CDN', 'ok', f'edge {ip} ({src}) answers (HTTP {r.status}); the mirror measures the candidates before it downloads')
    except Exception as e:
        if offline: return _c('Upstream CDN', 'info', f'edge not reachable ({e}); this profile uses only the offline copy, so the internet is not needed')
        if complete: return _c('Upstream CDN', 'info', f'edge not reachable ({e}); the offline copy is complete, so the internet is not needed')
        return _c('Upstream CDN', 'warn', f'edge not reachable ({e}); mirror-only operation still works')


NETWORK_LEVEL_NONE = 1                                  # NetworkConnectivityLevelHintNone: no network connection of any kind (0 = unknown, 2 = local only, 3 = internet, 4 = limited internet, 5 = hidden)


def network_hint():
    """(level, cost) Windows reports (GetNetworkConnectivityHint, the same call the game makes before it asks for any texture), or None where Windows does not offer it."""
    if os.name != 'nt': return None
    try:
        import ctypes

        class Hint(ctypes.Structure):
            _fields_ = [('level', ctypes.c_int), ('cost', ctypes.c_int), ('approaching', ctypes.c_ubyte), ('over', ctypes.c_ubyte), ('roaming', ctypes.c_ubyte)]
        h = Hint()
        if ctypes.windll.iphlpapi.GetNetworkConnectivityHint(ctypes.byref(h)) != 0: return None
        return h.level, h.cost
    except Exception: return None


def network_level():
    """The connectivity level alone (0 unknown, 1 none, 2 local only, 3 internet, 4 limited internet, 5 hidden), or None."""
    h = network_hint(); return None if h is None else h[0]


def _powershell_json(script):
    try:
        r = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script + ' | ConvertTo-Json -Compress'], capture_output=True, text=True, errors='replace', timeout=20, creationflags=0x08000000)
        return json.loads(r.stdout) if r.stdout.strip() else []
    except Exception as e: return dict(error=str(e))


def network_report():
    """For the support bundle: the level and cost Windows reports and the adapters and networks it sees. Names and states only: no addresses, no MAC addresses."""
    h = network_hint()
    return dict(level=None if h is None else h[0], cost=None if h is None else h[1], level_names={0: 'unknown', 1: 'none', 2: 'local_only', 3: 'internet', 4: 'limited_internet', 5: 'hidden'}, cost_names={0: 'unknown', 1: 'unrestricted', 2: 'fixed', 3: 'variable'},
                adapters=_powershell_json('Get-NetAdapter | Select-Object InterfaceDescription,Status,MediaConnectionState,InterfaceType,Virtual'),
                networks=_powershell_json('Get-NetConnectionProfile | Select-Object NetworkCategory,IPv4Connectivity,IPv6Connectivity'),
                default_routes=_powershell_json("@(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).Count"))


def check_network():
    """The game only asks for textures while Windows reports some network connection. A PC with no network adapter reports none, and then no texture is ever requested."""
    lv = network_level()
    if lv is None: return _c('Windows network status', 'info', 'not available on this version of Windows')
    if lv == NETWORK_LEVEL_NONE:
        return _c('Windows network status', 'warn', 'Windows reports no network connection at all (no network adapter that is switched on). The game checks this and then does not ask for any textures, '
                                                    'not even from your offline copy. Give Windows a network adapter that is connected (a virtual one is enough, see "A PC with no network card" in the Getting started guide), then restart the game')
    if lv == 2: return _c('Windows network status', 'ok', 'Windows reports a network connection without internet; the game still asks for textures, and your offline copy answers them')
    return _c('Windows network status', 'ok', 'Windows reports a network connection')


def _cache_gib():
    cache = 0
    for dp, _, fn in os.walk(paths.XPAK_CACHE):
        for f in fn:
            try: cache += os.path.getsize(os.path.join(dp, f))
            except OSError: pass
    return cache / 2**30


def check_guard(cfg):
    """The disk guard ends the game when the cache folder reaches its limit. A cache that starts close to it (the engine's own files can already be large) gets cut short without warning: say so before that."""
    g = cfg['guard']
    if not g.get('enabled') or g.get('action') != 'kill': return None
    cache = _cache_gib(); lim = float(g['limit_gib'])
    if cache < lim * 0.75: return None
    return _c('Disk guard', 'warn', f'the disk guard ends the game when the cache folder reaches {lim:g} GiB. It holds {cache:.0f} GiB now, so about {max(lim - cache, 0):.0f} GiB of new textures are left before that. '
                                    'Raise the limit in Advanced mode, Settings ("Disk guard: xpak_cache limit") for a longer session')


def check_cache():
    """What the game's own cache holds (read-only). Said only when its data files are large but its index lists nothing: then the game may not be able to use any of it."""
    if not os.path.isdir(paths.XPAK_CACHE): return None
    try:
        from . import cachectl
        s = cachectl.summary(); gib = s['total_bytes'] / 2**30
    except Exception: return None
    if s['records'] or gib < 10: return None
    return _c('Game cache', 'info', f'the cache folder holds {gib:.0f} GiB of data files, but its index lists no textures, so the game may not be able to use any of it (a run cut short while the game was writing can leave this). '
                                    'If textures never improve, close the game and rename the folder xpak_cache: the game builds a fresh one')


def check_disk(cfg):
    free = shutil.disk_usage(paths.ROOT).free / 2**30; cache = _cache_gib(); lim = cfg['guard']['limit_gib']
    lvl = 'fail' if free < 20 else 'warn' if free < 60 or cache > lim * 0.9 else 'ok'
    return _c('Disk', lvl, f'free {free:.0f} GiB; xpak_cache {cache:.1f} GiB (guard limit {lim:g} GiB)')


def check_game():
    r = procs.image_running(*paths.GAME_EXES)
    return _c('Game', 'info', ('running: ' + ', '.join(r)) if r else 'not running')


def check_game_setup():
    """Online mode in the game's Steam settings + sp26/xpak_cache linked to the cache the helper fills (see gamefix.py). Quiet when the layout does not apply."""
    from . import gamefix
    s = gamefix.status()
    if not s['applicable']: return _c('Game setup', 'info', gamefix.describe(s))
    if s['limited']: return _c('Game setup', 'warn', gamefix.describe(s), ('game_undo', None) if os.path.exists(s['backup']) and not s['game_running'] else None)    # all that this drive allows is done; there is nothing left to fix
    if s['ok']: return _c('Game setup', 'ok', gamefix.describe(s), ('game_undo', None) if os.path.exists(s['backup']) and not s['game_running'] else None)   # undo only where this tool made the change
    return _c('Game setup', 'warn', 'streamed textures may not be used by the game until this is set: ' + gamefix.describe(s), None if s['game_running'] else ('game_fix', None))


def check_locations():
    out = [_c(r['name'], r['level'], r['detail'], None) for r in paths.validate()]
    if paths.CONFIGURED and os.path.isdir(paths.GAME_ROOT):
        lists = paths.chunk_lists(paths.GAME_ROOT); stubs = sum(1 for f in lists if f.lower().endswith('_cdn_stub.xpak'))
        if stubs: out = [_c(r['name'], r['level'], f'{len(lists)} chunk list files under cod26/ and sp26/ ({stubs} of them in the Xbox "_stub" form)', None) if r['name'] == 'CDN chunk lists' else r for r in out]
    return out


def run_all(cfg):
    cfg = config.effective(cfg)                          # the profile's port, offline and guard values are what the session really uses
    paths.reload(); res = check_locations()
    res += check_hosts(); res.append(check_port(cfg)); res += check_proxy(cfg); res.append(check_mirror(cfg))
    pk = check_pack(cfg); res += pk
    res.append(check_upstream(bool(cfg['proxy'].get('offline')), any(r['name'] == 'Texture pack' and r['level'] == 'ok' for r in pk))); res.append(check_network()); res.append(check_disk(cfg))
    res += [r for r in (check_guard(cfg), check_cache()) if r]
    res.append(check_game()); res.append(check_game_setup())
    try:
        import tkinter; res.append(_c('Python', 'ok', f'{sys.version.split()[0]}, tkinter {tkinter.TkVersion}'))
    except Exception as e: res.append(_c('Python', 'warn', f'tkinter missing: {e}'))
    return res


def format_results(res):
    tag = dict(ok='OK  ', warn='WARN', fail='FAIL', info='INFO')
    return '\n'.join(f"[{tag[r['level']]}] {r['name']}: {r['detail']}" for r in res)
