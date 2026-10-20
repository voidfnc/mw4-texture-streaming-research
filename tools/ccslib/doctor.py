"""doctor.py - preflight checks. Each check -> dict(name, level 'ok'|'warn'|'fail'|'info', detail). Never raises, never writes."""
import http.client, os, random, shutil, sqlite3, sys
from . import config, hosts, mirrordb, pack, paths, procs, proxyctl, upstream


def _c(name, level, detail, fix=None):
    """fix = (action, arg) understood by session.run_fix, or None."""
    return dict(name=name, level=level, detail=detail, fix=fix)


def check_hosts():
    try: st = hosts.status()
    except Exception as e: return [_c('Hosts override', 'fail', f'cannot read hosts file: {e}')]
    s = st['state']; out = []
    if s == 'ABSENT': out.append(_c('Hosts override', 'fail', 'not present - the game resolves the CDN host IPv6-only and never connects (Hosts tab -> Apply)', ('hosts_apply', None)))
    elif s == 'FOREIGN': out.append(_c('Hosts override', 'warn', 'present as hand-added lines outside the managed block (works; Apply adopts them into the block)'))
    elif s == 'PARTIAL': out.append(_c('Hosts override', 'fail', 'managed block is missing the ::1 or 127.0.0.1 line', ('hosts_apply', None)))
    elif s == 'MIXED': out.append(_c('Hosts override', 'warn', 'managed block plus duplicate hand-added lines (Apply cleans this up)'))
    else: out.append(_c('Hosts override', 'ok', 'managed block present (::1 + 127.0.0.1)'))
    r = hosts.resolve_check()
    out.append(_c('Resolver', 'ok' if r['ok'] else ('fail' if s in ('OK', 'FOREIGN', 'MIXED') else 'warn'),
                  f"v4={r['v4']} v6={r['v6']}" + ('' if r['ok'] else ' (expected 127.0.0.1 / ::1; try Flush DNS)'),
                  ('flush_dns', None) if not r['ok'] and s in ('OK', 'FOREIGN', 'MIXED') else None))
    return out


def check_port(cfg):
    port = cfg['proxy']['port']; own = procs.status('proxy'); owners = procs.port_owner(port)
    if not owners: return _c(f'Port {port}', 'ok' if not own['alive'] else 'fail', 'free' if not own['alive'] else 'proxy process alive but not listening')
    if own['alive'] and all(o['pid'] == own['pid'] for o in owners): return _c(f'Port {port}', 'ok', f"owned by our proxy (pid {own['pid']})")
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
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=5); c.request('HEAD', f'/pc/iw9_3/23/{i & 0xff:02x}/{i:016x}_{wire:08x}_{flag}'); r = c.getresponse(); r.read(); c.close()
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


def check_upstream():
    try:
        ip, src = upstream.candidates_info()[0]; c = http.client.HTTPConnection(ip, 80, timeout=4); c.request('HEAD', '/', headers=upstream.headers()); r = c.getresponse(); r.read(); c.close()
        if src == 'fallback':
            return _c('Upstream CDN', 'warn', f'only the built-in fallback edge {ip} was found (no system or DNS answer); it may be far from you and slow. Remove the hosts override once, '
                                              'let the tool look the name up, and it will remember the nearest edge')
        return _c('Upstream CDN', 'ok', f'edge {ip} ({src}) answers (HTTP {r.status}); the mirror measures the candidates before it downloads')
    except Exception as e:
        return _c('Upstream CDN', 'warn', f'edge not reachable ({e}); mirror-only operation still works')


def check_disk(cfg):
    free = shutil.disk_usage(paths.ROOT).free / 2**30; cache = 0
    for dp, _, fn in os.walk(paths.XPAK_CACHE):
        for f in fn:
            try: cache += os.path.getsize(os.path.join(dp, f))
            except OSError: pass
    cache /= 2**30; lim = cfg['guard']['limit_gib']
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
    if s['ok']: return _c('Game setup', 'ok', gamefix.describe(s), ('game_undo', None) if os.path.exists(s['backup']) and not s['game_running'] else None)   # undo only where this tool made the change
    return _c('Game setup', 'warn', 'streamed textures may not be used by the game until this is set: ' + gamefix.describe(s), None if s['game_running'] else ('game_fix', None))


def check_locations():
    return [_c(r['name'], r['level'], r['detail'], None) for r in paths.validate()]


def run_all(cfg):
    paths.reload(); res = check_locations()
    res += check_hosts(); res.append(check_port(cfg)); res += check_proxy(cfg); res.append(check_mirror(cfg))
    res += check_pack(cfg); res.append(check_upstream()); res.append(check_disk(cfg)); res.append(check_game()); res.append(check_game_setup())
    try:
        import tkinter; res.append(_c('Python', 'ok', f'{sys.version.split()[0]}, tkinter {tkinter.TkVersion}'))
    except Exception as e: res.append(_c('Python', 'warn', f'tkinter missing: {e}'))
    return res


def format_results(res):
    tag = dict(ok='OK  ', warn='WARN', fail='FAIL', info='INFO')
    return '\n'.join(f"[{tag[r['level']]}] {r['name']}: {r['detail']}" for r in res)
