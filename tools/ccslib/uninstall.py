"""uninstall.py - what the installer's uninstall (and an upgrade) needs before it removes files, kept in Python so it can be tested.

  ccs-cli.exe --ccs-run uninstall-prep status [--json]   exit code: 1 = our marked block is in the hosts file, 2 = a helper process is running (0 = nothing to do)
  ccs-cli.exe --ccs-run uninstall-prep stop-helpers      stop the proxy, disk guard, mirror and watcher processes this tool started
  ccs-cli.exe --ccs-run uninstall-prep remove-hosts      take our block out of the hosts file (UAC prompt unless already admin); exit 0 = done or nothing to do, 3 = declined, 1 = failed

Nothing here deletes files: the uninstaller removes the program folder itself and asks before touching settings; the mirror and the game folder are never touched.
"""
import argparse, glob, json, os, sys
from . import hosts, paths, procs

HOSTS_PRESENT, HELPERS_RUNNING = 1, 2


def helper_names():
    """Names of helper processes with a pid file (the control window itself is not one)."""
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(paths.RUN, '*.pid')))


def state():
    try: st = hosts.status(); hs = st['state']; ours = bool(st.get('block'))             # only our marked block counts: lines someone added by hand are not ours to remove
    except Exception as e: hs = f'unreadable ({e})'; ours = False
    running = [n for n in helper_names() if procs.status(n)['alive']]
    return dict(hosts_state=hs, hosts_present=ours, helpers_running=running, data_dir=paths.WORK, mirror_dir=paths.MIRROR if paths.CONFIGURED else '')


def main(argv=None):
    ap = argparse.ArgumentParser(prog='uninstall-prep', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('status', 'stop-helpers', 'remove-hosts')); ap.add_argument('--json', action='store_true'); a = ap.parse_args(argv)
    if a.cmd == 'status':
        s = state(); code = (HOSTS_PRESENT if s['hosts_present'] else 0) | (HELPERS_RUNNING if s['helpers_running'] else 0)
        print(json.dumps(s) if a.json else f"hosts: {s['hosts_state']}; helpers running: {', '.join(s['helpers_running']) or 'none'}; data: {s['data_dir']}"); return code
    if a.cmd == 'stop-helpers':
        stopped = [n for n in helper_names() if procs.stop(n)]; print('stopped: ' + (', '.join(stopped) or 'nothing')); return 0
    from . import session                                             # remove-hosts
    if not state()['hosts_present']: print('hosts: nothing to remove'); return 0
    ok, res = session.hosts_cmd('remove', print)
    if ok: print('hosts: removed'); return 0
    print('hosts: ' + str(res.get('error') or res)); return 3 if res.get('error') == 'UAC declined' else 1


if __name__ == '__main__':
    sys.exit(main())
