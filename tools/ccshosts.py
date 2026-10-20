#!/usr/bin/env python3
"""ccshosts - manage ONLY the CCS block of the hosts file (the texture-CDN loopback override).

  python tools/ccshosts.py status [--json]
  python tools/ccshosts.py diff apply|remove          # preview, no write
  python tools/ccshosts.py apply [--force]            # needs admin; add --elevate to get a UAC prompt
  python tools/ccshosts.py remove                     # needs admin; restores normal DNS for the CDN host
  python tools/ccshosts.py verify                     # what the system resolver returns (v4/v6)
  python tools/ccshosts.py flush
  python tools/ccshosts.py backups | restore-backup NAME

Common: --elevate (re-run via UAC), --result-file PATH (JSON result; used by the GUI because an elevated child cannot pipe).
Exit codes: 0 ok, 1 error, 3 not admin / UAC declined.
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ccslib import hosts, launch, procs, paths


def main(argv=None):
    ap = argparse.ArgumentParser(prog='ccshosts', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('status', 'diff', 'apply', 'remove', 'verify', 'flush', 'backups', 'restore-backup'))
    ap.add_argument('arg', nargs='?')
    ap.add_argument('--json', action='store_true'); ap.add_argument('--force', action='store_true'); ap.add_argument('--no-flush', action='store_true')
    ap.add_argument('--elevate', action='store_true'); ap.add_argument('--result-file')
    a = ap.parse_args(argv)
    writes = a.cmd in ('apply', 'remove', 'flush', 'restore-backup')
    if writes and a.elevate and not procs.is_admin() and not os.environ.get('CCS_HOSTS_PATH'):
        rf = a.result_file or os.path.join(paths.RUN, 'hosts-result.json'); paths.ensure_dirs()
        if os.path.exists(rf): os.remove(rf)
        sub = launch.argv_for('ccshosts', a.cmd) + ([a.arg] if a.arg else []) + (['--force'] if a.force else []) + (['--no-flush'] if a.no_flush else []) + ['--result-file', rf]
        code = procs.run_elevated(sub)
        if code is None: print('UAC declined'); return 3
        try: print(open(rf, encoding='utf-8').read())
        except OSError: pass
        return code
    res = dict(cmd=a.cmd, ok=True)
    try:
        if a.cmd == 'status': res.update(hosts.status())
        elif a.cmd == 'diff':
            t, _ = hosts.read(); res['diff'] = hosts.diff(t, hosts.compute(t, a.arg or 'apply', a.force))
        elif a.cmd == 'apply': res.update(hosts.apply(force=a.force, flush=not a.no_flush))
        elif a.cmd == 'remove': res.update(hosts.remove(flush=not a.no_flush))
        elif a.cmd == 'verify': res.update(hosts.resolve_check())
        elif a.cmd == 'flush': res['flushed'] = hosts.flush_dns()
        elif a.cmd == 'backups': res['backups'] = hosts.list_backups()
        elif a.cmd == 'restore-backup': res.update(hosts.restore_backup(a.arg, flush=not a.no_flush))
        if a.cmd in ('apply', 'remove', 'restore-backup'): res['state'] = hosts.status()['state']
    except PermissionError as e:
        res.update(ok=False, error=f'permission denied (run as admin or use --elevate): {e}')
    except Exception as e:
        res.update(ok=False, error=str(e))
    if a.result_file:
        paths.ensure_dirs(); json.dump(res, open(a.result_file, 'w', encoding='utf-8'))
    if a.json or a.result_file: print(json.dumps(res))
    else:
        if res.get('diff') is not None: print(res['diff'] or '(no change)')
        else:
            for k, v in res.items():
                if k not in ('cmd', 'ok'): print(f'{k}: {v}')
        if not res['ok']: print('ERROR:', res['error'])
    if not res['ok']: return 3 if 'permission' in res['error'] else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
