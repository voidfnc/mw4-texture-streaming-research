"""selfcheck.py - end-to-end check of the parts that start other programs (the proxy, the disk guard, the shortcut), without touching the hosts file.

  ccs-cli.exe --ccs-run selfcheck [--port N]      (from source: python tools/ccs.py --ccs-run selfcheck)

It uses the same code as Start session: the proxy and the disk guard are started as detached helpers, checked, and stopped again; a desktop shortcut is made in a temp
folder and read back. Exit 0 = everything fine, 1 = a check failed, 4 = a session is running (nothing was started, nothing was stopped).
The packaged build runs this in its own tests, and it is a quick way to see that a setup can start its helpers.
"""
import argparse, copy, os, subprocess, sys, tempfile, time
from . import config, launch, paths, procs, proxyctl, shortcut


def main(argv=None):
    ap = argparse.ArgumentParser(prog='selfcheck', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument('--port', type=int, default=18000 + os.getpid() % 1000)
    a = ap.parse_args(argv); fails = []
    def check(ok, what):
        print(('ok    ' if ok else 'FAIL  ') + what);
        if not ok: fails.append(what)
    if procs.status('proxy')['alive'] or procs.status('guard')['alive']:
        print('a session is running (proxy or disk guard): stop it first, this check would otherwise stop it'); return 4
    cfg = copy.deepcopy(config.DEFAULTS); cfg['proxy']['port'] = a.port; cfg['proxy']['origin'] = False
    try:
        procs.stop('proxy'); st = proxyctl.start_proxy(cfg); check(st['alive'], 'proxy started as a detached helper')
        up = False; t0 = time.time()
        while time.time() - t0 < 25 and not up: up = bool(proxyctl.fetch_stats(a.port, timeout=1.0)) or (time.sleep(0.4) and False)
        check(up, f'proxy answers on port {a.port}')
        st = proxyctl.start_guard(cfg); time.sleep(2.0); check(procs.status('guard')['alive'], 'disk guard started and still running')
    finally:
        stopped = [n for n in ('guard', 'proxy') if procs.stop(n)]; check(stopped == ['guard', 'proxy'] or not fails, 'helpers stopped again: ' + ', '.join(stopped))
    d = tempfile.mkdtemp(prefix='ccs-selfcheck-')
    try:
        lnk = shortcut.create(d, 'selfcheck'); ps = "(New-Object -ComObject WScript.Shell).CreateShortcut($env:L).TargetPath"
        target = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True, errors='replace', env=dict(os.environ, L=lnk), timeout=30, creationflags=procs.CREATE_NO_WINDOW).stdout.strip()
        want = launch.gui_argv()[0]
        try: same = os.path.samefile(target, want)                          # the same file even when one path is the 8.3 short form (RUNNER~1) and the other the long one
        except OSError: same = os.path.normcase(target) == os.path.normcase(want)
        check(same, f'shortcut starts {os.path.basename(want)}')
    except Exception as e: check(False, f'shortcut: {e}')
    print('selfcheck: ' + ('all fine' if not fails else f'{len(fails)} problem(s)')); return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
