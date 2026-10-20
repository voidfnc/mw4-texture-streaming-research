#!/usr/bin/env python3
"""test_installer.py - installs the built Setup.exe silently (per user, into a temp folder), checks the result, upgrades over it with the hosts block switched on, uninstalls,
and checks that nothing is left behind. Used by CI and by hand:

  python packaging/test_installer.py packaging/out/MW4-Texture-Streaming-<version>-Setup.exe

It never touches the real hosts file or settings: CCS_HOSTS_PATH and CCS_WORK point at temp files, and the installer's own hooks inherit them. The only things outside the
temp folder are the ones a real install makes (Start menu folder, desktop shortcut, uninstall entry), and they are removed again by the uninstall that this test runs.
"""
import json, os, shutil, subprocess, sys, tempfile, time, winreg

APPID = '{6B0F1F2E-7D3A-4C58-9E21-4A9D5C7B3E10}_is1'                       # installer.iss AppId
APP = 'MW4 Texture Streaming'


def check(ok, what, detail=''):
    print(('  ok   ' if ok else '  FAIL ') + what)
    if not ok:
        if detail: print('--- output ---\n' + detail.strip()[-3000:] + '\n--------------')
        raise SystemExit(f'installer test failed: {what}')


def uninstall_entry():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Uninstall' + '\\' + APPID) as k:
            return dict(version=winreg.QueryValueEx(k, 'DisplayVersion')[0], uninstall=winreg.QueryValueEx(k, 'UninstallString')[0], where=winreg.QueryValueEx(k, 'InstallLocation')[0])
    except OSError:
        return None


def shell_folder(name):
    return subprocess.run(['powershell', '-NoProfile', '-Command', f"[Environment]::GetFolderPath('{name}')"], capture_output=True, text=True, timeout=30).stdout.strip()


def main():
    if len(sys.argv) != 2 or not os.path.exists(sys.argv[1]): sys.exit(__doc__)
    setup = os.path.abspath(sys.argv[1]); tmp = tempfile.mkdtemp(prefix='ccs-inst-'); app = os.path.join(tmp, 'program files', APP)         # a path with spaces, as real ones have
    hosts = os.path.join(tmp, 'hosts'); open(hosts, 'w').write('127.0.0.1 localhost\r\n'); data = os.path.join(tmp, 'data')
    env = dict(os.environ, CCS_HOSTS_PATH=hosts, CCS_WORK=data, PYTHONIOENCODING='utf-8')
    if uninstall_entry(): sys.exit('an installed copy exists already: uninstall it first so this test does not touch it')
    menu = os.path.join(os.environ['APPDATA'], 'Microsoft', 'Windows', 'Start Menu', 'Programs', APP); desk = os.path.join(shell_folder('Desktop'), APP + '.lnk')
    def install(tag):
        r = subprocess.run([setup, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', f'/DIR={app}', f'/LOG={os.path.join(tmp, tag + ".log")}'], env=env, timeout=300); return r.returncode
    try:
        print('install'); check(install('install') == 0, 'setup exits 0 (silent, per user, no administrator rights)')
        exe, cli = os.path.join(app, APP + '.exe'), os.path.join(app, 'ccs-cli.exe')
        for rel in (APP + '.exe', 'ccs-cli.exe', 'README.md', 'LICENSE', 'DISCLAIMER.md', 'Restore hosts.bat', 'START HERE.txt', os.path.join('docs', 'GETTING-STARTED.md')): check(os.path.exists(os.path.join(app, rel)), f'installed: {rel}')
        check(not os.path.exists(os.path.join(app, 'portable.txt')), 'no portable.txt (an installed copy keeps its data in the local app data folder)')
        e = uninstall_entry(); check(bool(e) and e['version'] and os.path.normcase(e['where'].rstrip('\\')) == os.path.normcase(app), f"uninstall entry (Apps & features) for version {e and e['version']}")
        check(os.path.isdir(menu) and os.path.exists(os.path.join(menu, APP + '.lnk')) and os.path.exists(os.path.join(menu, 'Restore hosts.lnk')), 'Start menu entries')
        check(os.path.exists(desk), 'desktop shortcut (the default task)')
        r = subprocess.run([cli, '--version'], capture_output=True, text=True, env=env, timeout=60); check(e['version'] in r.stdout, 'the installed program runs and reports the same version')
        r = subprocess.run([cli, '--ccs-run', 'selfcheck'], capture_output=True, text=True, env=env, timeout=180); check(r.returncode == 0 and 'all fine' in r.stdout, 'the installed program starts its helpers (selfcheck)', r.stdout + r.stderr)

        print('upgrade over it while the hosts block is on')
        subprocess.run([cli, '--ccs-run', 'ccshosts', 'apply', '--no-flush'], env=env, timeout=60, capture_output=True); check('cod-assets' in open(hosts).read(), 'precondition: hosts block present')
        check(install('upgrade') == 0, 'setup over an existing install exits 0')
        check('cod-assets' not in open(hosts).read() and 'localhost' in open(hosts).read(), 'setup put the hosts file back before replacing files (and kept other lines)')
        check(os.path.exists(exe) and uninstall_entry() is not None, 'still installed after the upgrade')

        print('uninstall with the hosts block on')
        subprocess.run([cli, '--ccs-run', 'ccshosts', 'apply', '--no-flush'], env=env, timeout=60, capture_output=True); os.makedirs(data, exist_ok=True); open(os.path.join(data, 'gui_settings.json'), 'w').write('{}')
        uninstall = e['uninstall'].strip('"'); r = subprocess.run([uninstall, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], env=env, timeout=300); check(r.returncode == 0, 'uninstaller exits 0')
        for _ in range(40):                                                   # the uninstaller finishes by deleting itself, a moment after it exits
            if not os.path.exists(app): break
            time.sleep(0.5)
        check(not os.path.exists(app), 'program folder is gone')
        check(uninstall_entry() is None, 'uninstall entry is gone'); check(not os.path.exists(menu), 'Start menu folder is gone'); check(not os.path.exists(desk), 'desktop shortcut is gone')
        check('cod-assets' not in open(hosts).read() and 'localhost' in open(hosts).read(), 'the hosts block was removed by the uninstaller (other lines kept)')
        check(os.path.exists(os.path.join(data, 'gui_settings.json')), 'settings are kept by a silent uninstall (they are only deleted when the user says yes)')
        print('all installer checks passed')
    finally:
        e = uninstall_entry()
        if e:
            subprocess.run([e['uninstall'].strip('"'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], env=env, timeout=300); time.sleep(3)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
