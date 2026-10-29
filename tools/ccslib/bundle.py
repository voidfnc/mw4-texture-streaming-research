"""bundle.py - one-click support bundle: everything needed to analyse a run, in a single zip (tools/work/bundles/)."""
import json, os, platform, re, sys, time, zipfile
from . import config, doctor, hosts, paths, procs, proxyctl, report

_USER_DIR = re.compile(r'(?i)(?<![A-Za-z0-9_])([A-Za-z]:(?:\\\\|\\|/)Users(?:\\\\|\\|/))[^\\/"*?<>|:\r\n]+')


def scrub(text):
    """The text with the Windows user name taken out (C:\\Users\\<name>\\... -> C:\\Users\\<user>\\..., also in its JSON-escaped form): a bundle is meant to be attached to a public issue."""
    text = _USER_DIR.sub(lambda m: m.group(1) + '<user>', text)
    name = os.path.basename(os.path.expanduser('~'))
    return re.sub(r'(?i)(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])', '<user>', text) if len(name) >= 4 else text


def _add(z, arc, path):
    """A file of ours into the zip as scrubbed text."""
    with open(path, encoding='utf-8', errors='replace') as f: z.writestr(arc, scrub(f.read()))


def _hosts_summary(text):
    """Our block and the lines that name the CDN host, nothing else: the rest of the hosts file is the user's own business."""
    p = hosts.parse(text); lines = p['lines']; keep = set()
    if p['span']: keep |= set(range(p['span'][0], p['span'][1] + 1))
    keep |= {i for i, _, _ in p['foreign']}
    return '\n'.join([lines[i] for i in sorted(keep)] + [f'# ({len(lines) - len(keep)} other lines of the hosts file are not included)']) + '\n'


def _tail(path, n=20000):
    return '\n'.join(procs.tail_lines(path, n))


def make(cfg=None):
    cfg = cfg or config.load(); out_dir = os.path.join(paths.WORK, 'bundles'); os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, time.strftime('ccs-support-%Y%m%d-%H%M%S.zip'))
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, p in (('proxy.log', proxyctl.PROXY_LOG), ('diskguard.log', proxyctl.GUARD_LOG), ('ccsmirror.log', proxyctl.MIRROR_LOG), ('ccsgui.log', os.path.join(paths.WORK, 'ccsgui.log')),
                        ('netwatch.log', os.path.join(paths.WORK, 'netwatch.log'))):
            if os.path.exists(p): z.writestr('logs/' + name, scrub(_tail(p)))
        for fn in (proxyctl.PROXY_STATS, proxyctl.GUARD_STATS, os.path.join(paths.RUN, 'session.json'), os.path.join(paths.WORK, 'gui_settings.json')):
            if os.path.exists(fn): _add(z, 'state/' + os.path.basename(fn), fn)
        try:
            st = hosts.status(); z.writestr('state/hosts.txt', json.dumps(dict(state=st['state'], block=st['block'], foreign=st['foreign'], resolver=hosts.resolve_check()), indent=1))
            z.writestr('state/hosts-file.txt', _hosts_summary(hosts.read()[0]))
        except Exception as e: z.writestr('state/hosts.txt', f'error: {e}')
        try: z.writestr('state/resolver.txt', scrub(json.dumps(hosts.resolver_report(), indent=1, default=str)))
        except Exception as e: z.writestr('state/resolver.txt', f'error: {e}')
        try: z.writestr('state/doctor.txt', scrub(doctor.format_results(doctor.run_all(cfg))))
        except Exception as e: z.writestr('state/doctor.txt', f'error: {e}')
        z.writestr('state/processes.json', scrub(json.dumps({n: procs.status(n) for n in ('proxy', 'guard', 'netwatch')}, indent=1, default=str)))
        z.writestr('state/env.txt', scrub(f'python {sys.version}\n{platform.platform()}\nadmin={procs.is_admin()}\ngame={procs.image_running(*paths.GAME_EXES)}\n'))
        try:        # the game folder's drive and the game setup, without paths: why the cache link can or cannot be made
            from . import gamefix
            gs = gamefix.status(check_game=False); z.writestr('state/game_setup.json', json.dumps({k: gs.get(k) for k in ('applicable', 'ok', 'limited', 'config_ok', 'keys', 'link_state', 'link_unsupported', 'fs')}, indent=1))
        except Exception as e: z.writestr('state/game_setup.json', f'error: {e}')
        try: z.writestr('state/network.txt', scrub(json.dumps(doctor.network_report(), indent=1, default=str)))
        except Exception as e: z.writestr('state/network.txt', f'error: {e}')
        try:        # the game's own cache: per-shard sizes and record counts (no file names of the user's, no content)
            from . import cachectl
            z.writestr('state/cache.txt', scrub(json.dumps(cachectl.summary(), indent=1, default=str)))
        except Exception as e: z.writestr('state/cache.txt', f'error: {e}')
        z.writestr('state/player_config.json', json.dumps(report.player_config(), indent=1))
        z.writestr('state/runs.txt', '\n'.join(f"#{s['idx']} {s.get('date')} {s['first']}-{s['last']} requests={s['nreq']}" for s in report.segments()))
        for fn in report.list_reports()[-3:]:
            _add(z, 'reports/' + os.path.basename(fn), fn); md = fn[:-5] + '.md'
            if os.path.exists(md): _add(z, 'reports/' + os.path.basename(md), md)
    return out
