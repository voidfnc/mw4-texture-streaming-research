"""mirrorctl.py - control the resumable chunk mirror (tools/ccsmirror.py) as a detached child process."""
import json, os, subprocess, sys
from . import launch, paths, procs

PROGRESS = os.path.join(paths.RUN, 'mirror_progress.json')
OUTFILE = os.path.join(paths.RUN, 'mirror.out')


def stopfile(): return os.path.join(paths.MIRROR, 'STOP')       # resolved at call time: the mirror folder is configurable


def run_argv(workers=4, tier=4096, budget_gib=0, min_free_gib=40, max_rps=50, retries=4, scope=None, packages=None, limit_mbps=0, daily_gib=0, link_wait_s=0, line_mbps=0):
    a = launch.argv_for('ccsmirror') + ['run', '--workers', str(int(workers)), '--tier', str(tier), '--budget-gib', str(budget_gib), '--min-free-gib', str(min_free_gib),
         '--max-rps', str(max_rps), '--retries', str(int(retries)), '--progress-json', PROGRESS, '--stop-file', stopfile(), '--accept-notice']      # the GUI shows the notice before it starts a run
    if scope: a += ['--scope', scope]
    if scope == 'custom' and packages: a += ['--packages', packages if isinstance(packages, str) else ','.join(packages)]
    if limit_mbps and float(limit_mbps) > 0: a += ['--limit-mbps', str(limit_mbps)]
    if daily_gib and float(daily_gib) > 0: a += ['--daily-gib', str(daily_gib)]
    if line_mbps and float(line_mbps) > 0: a += ['--line-mbps', str(line_mbps)]
    if link_wait_s and float(link_wait_s) > 0: a += ['--link-wait-s', str(link_wait_s)]
    return a


def pack_kwargs(cfg):
    """Texture-pack run settings from the effective config (scope/level/limits); budget 0 = automatic."""
    from . import config
    e = config.effective(cfg); pk = e['pack']; m = e['mirror']
    return dict(workers=int(pk.get('workers') or 0) or (4 if float(pk.get('limit_mbps') or 0) > 0 else int(m['workers'])), tier=m['tier'], budget_gib=0, min_free_gib=m['min_free_gib'],
                max_rps=m['max_rps'], retries=m['retries'], scope=pk['scope'], packages=pk.get('packages'), limit_mbps=pk.get('limit_mbps') or 0, daily_gib=pk.get('daily_gib') or 0,
                link_wait_s=pk.get('link_wait_s') or 0, line_mbps=pk.get('line_mbps') or 0)


def start(**kw):
    if procs.status('mirror')['alive']: return procs.status('mirror')
    try: os.remove(stopfile())
    except OSError: pass
    return procs.start('mirror', run_argv(**kw), OUTFILE)


def pause():
    """Ask the run to stop cleanly (in-flight objects finish). Returns True if a run was alive."""
    if not procs.status('mirror')['alive']: return False
    os.makedirs(paths.MIRROR, exist_ok=True); open(stopfile(), 'w').write('stop')
    return True


def kill(): return procs.stop('mirror')


def progress():
    try: return json.load(open(PROGRESS, encoding='utf-8'))
    except Exception: return None


def status():
    """Per-priority table + stored totals, via `ccsmirror.py status --json` (None if the mirror is not initialised)."""
    if not os.path.exists(os.path.join(paths.MIRROR, 'index.sqlite')): return None
    r = subprocess.run(launch.argv_for('ccsmirror', 'status', '--json'), capture_output=True, text=True, timeout=120, creationflags=procs.CREATE_NO_WINDOW)
    try: return json.loads(r.stdout)
    except Exception: return None


VERIFY_PROGRESS = os.path.join(paths.RUN, 'mirror_verify.json')


def verify_progress():
    try: return json.load(open(VERIFY_PROGRESS, encoding='utf-8'))
    except Exception: return None


def oneshot(args, out=None):
    """Run `ccsmirror.py <args>` detached (verify / retry-failed / init). Output goes to tools/work/run/mirror_<cmd>.out."""
    name = 'mirror-' + args[0]
    return procs.start(name, launch.argv_for('ccsmirror', *args), out or os.path.join(paths.RUN, f'mirror_{args[0]}.out'))
