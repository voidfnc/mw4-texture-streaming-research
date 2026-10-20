"""proxyctl.py - build argv for / talk to the ccsproxy and diskguard child processes."""
import json, http.client, os
from . import config, launch, paths, procs

PROXY_LOG = os.path.join(paths.WORK, 'ccsproxy.log')
GUARD_LOG = os.path.join(paths.WORK, 'diskguard.log')
PROXY_STATS = os.path.join(paths.RUN, 'proxy_stats.json')
GUARD_STATS = os.path.join(paths.RUN, 'guard_stats.json')
MIRROR_LOG = os.path.join(paths.WORK, 'ccsmirror.log')


def proxy_argv(cfg):
    p = config.effective_proxy(cfg)
    a = launch.argv_for('ccsproxy') + ['--max-raw-mib', str(p['max_raw_mib']), '--budget-gib', str(p['budget_gib']),
         '--retries', str(p['retries']), '--port', str(p['port']), '--log', PROXY_LOG, '--stats-json', PROXY_STATS]
    if p['origin']: a += ['--origin', paths.MIRROR]
    if p['offline']: a += ['--offline']
    if p['upstream_ip']: a += ['--upstream-ip', p['upstream_ip']]
    return a


def guard_argv(cfg):
    g = config.effective(cfg)['guard']
    return launch.argv_for('diskguard') + ['--limit-gib', str(g['limit_gib']), '--action', g['action'],
            '--interval', str(g['interval']), '--cache', paths.XPAK_CACHE, '--status-json', GUARD_STATS, '--log', GUARD_LOG]


def start_proxy(cfg):
    # the tools write their own log files; stdout/stderr (tracebacks, argparse errors) go to a separate .out file to avoid duplicate lines
    return procs.start('proxy', proxy_argv(cfg), os.path.join(paths.RUN, 'proxy.out'))


def start_guard(cfg):
    return procs.start('guard', guard_argv(cfg), os.path.join(paths.RUN, 'guard.out'))


def fetch_stats(port=80, timeout=0.6):
    """Live snapshot from the proxy's /__ccs/stats endpoint (loopback). None if not answering."""
    try:
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
        c.request('GET', '/__ccs/stats'); r = c.getresponse(); b = r.read(); c.close()
        return json.loads(b) if r.status == 200 else None
    except Exception:
        return None


def read_json(path):
    try: return json.load(open(path, encoding='utf-8'))
    except Exception: return None
