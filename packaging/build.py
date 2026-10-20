#!/usr/bin/env python3
"""build.py - builds the packaged app: the program folder, the portable zip, the installer and the checksums.

  python packaging/build.py                   everything (the installer only when Inno Setup 6 is installed)
  python packaging/build.py --no-installer    program folder + zip
  python packaging/build.py --skip-smoke      skip the checks of the built program (not recommended)

Needs PyInstaller in the Python that runs this. Use packaging\\build.bat, which makes a throw-away environment in %TEMP% with the pinned, hash-checked versions
(your own Python is not changed), runs this, and then runs test_installer.py.
The version comes from tools/ccslib/version.py and nowhere else: file names, the exe's version resource and the installer all read it from there.
Output goes to packaging/out/ (not tracked).
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE); TOOLS = os.path.join(REPO, 'tools')
APP = 'MW4 Texture Streaming'
DOCS = ('GETTING-STARTED.md', 'USAGE.md', 'TEXTURE-PACK.md', 'ARCHITECTURE.md', 'FINDINGS.md', 'ISSUE-ipv6-cdn-lookup.md')       # published docs only, never local notes
TOP = ('README.md', 'LICENSE', 'DISCLAIMER.md', 'CHANGELOG.md')


def read_version():
    m = re.search(r"__version__\s*=\s*'([^']+)'", open(os.path.join(TOOLS, 'ccslib', 'version.py'), encoding='utf-8').read()); return m.group(1)


def numeric(v):
    n = [int(x) for x in re.findall(r'\d+', v.split('-')[0])][:4]; return tuple(n + [0] * (4 - len(n)))


def version_info(v, original, description):
    t = numeric(v); return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [StringStruct('CompanyName', 'voidfnc'), StringStruct('FileDescription', '{description}'),
    StringStruct('FileVersion', '{v}'), StringStruct('InternalName', '{original[:-4]}'), StringStruct('LegalCopyright', 'MIT License'),
    StringStruct('OriginalFilename', '{original}'), StringStruct('ProductName', 'MW4 Texture Streaming Toolkit'), StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""


def run(argv, **kw):
    print('>', ' '.join(str(a) for a in argv)); r = subprocess.run(argv, **kw)
    if r.returncode != 0: sys.exit(f'failed ({r.returncode}): {argv[0]}')
    return r


def freeze(out, v):
    work = os.path.join(out, 'work'); dist = os.path.join(out, 'dist')
    for d in (work, dist): shutil.rmtree(d, ignore_errors=True)
    os.makedirs(work); gui, cli = (os.path.join(work, n) for n in ('version_gui.txt', 'version_cli.txt'))
    open(gui, 'w', encoding='utf-8').write(version_info(v, APP + '.exe', 'MW4 Texture Streaming Toolkit')); open(cli, 'w', encoding='utf-8').write(version_info(v, 'ccs-cli.exe', 'MW4 Texture Streaming Toolkit (command line)'))
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', dist, '--workpath', os.path.join(work, 'pyi'), os.path.join(HERE, 'ccs.spec')],
        env=dict(os.environ, CCS_VERSION_GUI=gui, CCS_VERSION_CLI=cli))
    app = os.path.join(dist, APP)
    if not os.path.exists(os.path.join(app, APP + '.exe')): sys.exit('PyInstaller finished but the program is not where expected')
    return app


def assemble(app):
    """Add the files people need next to the program: docs, licence, the undo script, a start page. Published files only."""
    for f in TOP: shutil.copy2(os.path.join(REPO, f), app)
    os.makedirs(os.path.join(app, 'docs'), exist_ok=True)
    for f in DOCS: shutil.copy2(os.path.join(REPO, 'docs', f), os.path.join(app, 'docs'))
    for f in ('Restore hosts.bat', 'START HERE.txt'): shutil.copy2(os.path.join(HERE, f), app)


def check(ok, what):
    print(('  ok   ' if ok else '  FAIL ') + what)
    if not ok: sys.exit(f'smoke test failed: {what}')


def smoke(app, v):
    """Run the built program the way a user's PC would, against temp settings and a temp hosts file (the real ones are never touched)."""
    cli = os.path.join(app, 'ccs-cli.exe'); gui = os.path.join(app, APP + '.exe'); tmp = tempfile.mkdtemp(prefix='ccs-smoke-'); hosts = os.path.join(tmp, 'hosts')
    open(hosts, 'w').write('127.0.0.1 localhost\r\n'); env = dict(os.environ, CCS_WORK=os.path.join(tmp, 'work'), CCS_HOSTS_PATH=hosts, PYTHONIOENCODING='utf-8')
    def call(*a, e=env, t=120): r = subprocess.run([cli, *a], capture_output=True, text=True, errors='replace', env=e, timeout=t); return r.returncode, r.stdout, r.stderr
    print('smoke test of', app)
    c, out, _ = call('--version'); check(c == 0 and v in out, f'--version prints {v}')
    c, out, _ = call('--ccs-run', 'ccshosts', 'status', '--json'); check(c == 0 and json.loads(out)['state'] == 'ABSENT', 'hosts editor runs inside the program')
    c, out, _ = call('--ccs-run', 'ccsproxy', '--no-such-flag'); check(c == 2, 'a tool exit code comes through (argparse: 2)')
    c, out, _ = call('--ccs-run', 'nonsense'); check(c == 2, 'unknown tool is refused')
    call('--ccs-run', 'ccshosts', 'apply', '--no-flush'); c, out, _ = call('--ccs-run', 'uninstall-prep', 'status'); check(c == 1, 'uninstall-prep sees our hosts block (exit 1)')
    c, out, _ = call('--ccs-run', 'uninstall-prep', 'remove-hosts'); check(c == 0 and 'cod-assets' not in open(hosts).read(), 'uninstall-prep removes it and leaves the other lines')
    local = os.path.join(tmp, 'Local'); os.makedirs(local); e2 = {k: x for k, x in env.items() if k != 'CCS_WORK'}; e2['LOCALAPPDATA'] = local
    c, out, _ = call('--ccs-run', 'uninstall-prep', 'status', '--json', e=e2); check(json.loads(out)['data_dir'] == os.path.join(local, 'MW4TextureStreaming'), 'settings live in the local app data folder, not in the program folder')
    c, out, _ = call('--ccs-run', 'selfcheck', t=180); check(c == 0 and 'all fine' in out, 'the built program starts its own helpers and makes a shortcut (selfcheck)')
    fake = os.path.join(tmp, 'game'); os.makedirs(os.path.join(fake, 'sp26', 'steam_settings')); os.makedirs(os.path.join(fake, 'xpak_cache'))
    open(os.path.join(fake, 'sp26', 'steam_settings', 'configs.main.ini'), 'w').write('[main::connectivity]\noffline=1\n')
    c, out, _ = call('--ccs-run', 'gamefix', 'status', '--root', fake); check(c == 1 and 'offline mode' in out, 'game setup sees an offline game folder')
    if 'sp26-cod.exe' in subprocess.run(['tasklist'], capture_output=True, text=True, errors='replace').stdout.lower(): print('  skip game setup apply/undo: the game is running (it refuses to change anything then, as it should)')
    else:
        c, out, _ = call('--ccs-run', 'gamefix', 'apply', '--root', fake); c2, _, _ = call('--ccs-run', 'gamefix', 'status', '--root', fake); check(c == 0 and c2 == 0, 'game setup applies (settings file + cache link)')
        c, out, _ = call('--ccs-run', 'gamefix', 'undo', '--root', fake); check(c == 0 and not os.path.lexists(os.path.join(fake, 'sp26', 'xpak_cache')), 'game setup undoes it and leaves the real cache')
    port = 18000 + os.getpid() % 1000; log = os.path.join(tmp, 'proxy.log')
    p = subprocess.Popen([cli, '--ccs-run', 'ccsproxy', '--port', str(port), '--offline', '--log', log, '--stats-json', os.path.join(tmp, 'stats.json')], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        up = False
        for _ in range(60):
            try: up = 'stat' in json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/__ccs/stats', timeout=2)); break
            except Exception: time.sleep(0.5)
        check(up, 'the proxy starts from the built program and answers its stats endpoint')
    finally:
        p.terminate(); p.wait(15)
    c, out, err = call('--selftest', t=90); line = out.strip().splitlines()[-1] if out.strip() else ''
    check(c == 0 and line.startswith('{') and 'hosts' in json.loads(line), 'the control window builds and polls (--selftest)')
    g = subprocess.Popen([gui], env=env, cwd=tmp)
    try:
        time.sleep(6); check(g.poll() is None, 'the windowed program stays open'); check(os.path.isdir(os.path.join(tmp, 'work')), 'it created its data folder')
    finally:
        subprocess.run(['taskkill', '/PID', str(g.pid), '/T', '/F'], capture_output=True); time.sleep(1)
    shutil.rmtree(tmp, ignore_errors=True)


def make_zip(app, path):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, _, files in os.walk(app):
            for f in files:
                full = os.path.join(root, f); z.write(full, os.path.join(APP, os.path.relpath(full, app)))
        z.writestr(os.path.join(APP, 'portable.txt'), 'This file makes the program keep its settings, logs and reports in the "data" folder next to it (nothing is written elsewhere).\r\nDelete it to use the normal location.\r\n')


def find_iscc():
    for p in (shutil.which('iscc'), os.path.expandvars(r'%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe'), os.path.expandvars(r'%ProgramFiles%\Inno Setup 6\ISCC.exe'), os.path.expandvars(r'%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe')):
        if p and os.path.exists(p): return p
    return None


def notice_file(out):
    """The text of the installer's 'accept' page: the short research notice, then the licence."""
    sys.path.insert(0, TOOLS); from ccslib import version
    import textwrap
    lic = open(os.path.join(REPO, 'LICENSE'), encoding='utf-8').read()
    text = textwrap.fill(version.NOTICE, 90) + '\n\nSee DISCLAIMER.md in the program folder for the full text.\n\n' + lic
    p = os.path.join(out, 'work', 'notice.txt'); open(p, 'w', encoding='ascii', errors='replace', newline='').write(text.replace('\r\n', '\n').replace('\n', '\r\n')); return p


def make_installer(iscc, app, out, v):
    run([iscc, '/Qp', f'/DAppVersion={v}', f'/DNumericVersion={".".join(map(str, numeric(v)))}', f'/DSourceDir={app}', f'/DOutputDir={out}', f'/DRepoDir={REPO}',
         f'/DNoticeFile={notice_file(out)}', os.path.join(HERE, 'installer.iss')])
    exe = os.path.join(out, f'MW4-Texture-Streaming-{v}-Setup.exe')
    if not os.path.exists(exe): sys.exit('Inno Setup finished but the installer is not where expected')
    return exe


def release_notes(v):
    """The CHANGELOG section for version v: the text of the GitHub release."""
    t = open(os.path.join(REPO, 'CHANGELOG.md'), encoding='utf-8').read()
    m = re.search(r'^## ' + re.escape(v) + r'[ \t]*\r?\n(.*?)(?=^## |\Z)', t, re.M | re.S)
    if not m: sys.exit(f'CHANGELOG.md has no section "## {v}"')
    return m.group(1).strip().replace('\r\n', '\n') + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument('--out', default=os.path.join(HERE, 'out'))
    ap.add_argument('--no-installer', action='store_true'); ap.add_argument('--skip-smoke', action='store_true')
    ap.add_argument('--expect-tag', help='stop unless this git tag is "v" + the version in version.py (release.py relies on the same rule: a release is always the version in version.py)')
    ap.add_argument('--notes', help='also write the release notes (the CHANGELOG section of this version) to this file'); a = ap.parse_args(argv)
    v = read_version(); out = os.path.abspath(a.out); os.makedirs(out, exist_ok=True); print('version', v)
    if a.expect_tag and a.expect_tag != 'v' + v: sys.exit(f'tag {a.expect_tag} does not match the version in tools/ccslib/version.py ({v}): expected v{v}')
    if a.notes: open(a.notes, 'w', encoding='utf-8', newline='\n').write(release_notes(v))
    app = freeze(out, v); assemble(app)
    if not a.skip_smoke: smoke(app, v)
    files = []; z = os.path.join(out, f'MW4-Texture-Streaming-{v}-win64-portable.zip'); make_zip(app, z); files.append(z)
    if not a.no_installer:
        iscc = find_iscc()
        if iscc: files.append(make_installer(iscc, app, out, v))
        else: print('Inno Setup 6 not found: skipping the installer (winget install JRSoftware.InnoSetup)')
    with open(os.path.join(out, 'SHA256SUMS.txt'), 'w', encoding='utf-8', newline='\n') as f:
        for p in files: f.write(f'{hashlib.sha256(open(p, "rb").read()).hexdigest()}  {os.path.basename(p)}\n')
    print('\n'.join(f'{os.path.basename(p)}  {os.path.getsize(p) / 2**20:.1f} MiB' for p in files))


if __name__ == '__main__':
    main()
