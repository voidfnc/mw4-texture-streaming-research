#!/usr/bin/env python3
"""release.py - turns what packaging/build.bat built into a DRAFT GitHub release (installer, portable zip, checksums, notes from the changelog).

  packaging\\build.bat                  build and test everything (about 3 minutes)
  python packaging/release.py --dry-run     show what would be uploaded
  python packaging/release.py               create the draft; open it on GitHub, read it, press Publish

It never publishes: a draft is visible only to you until you press the button. It refuses to run when the files are not from the current version, when the working tree
has uncommitted changes, or when HEAD is not what is on origin/main (so a release is always made from published source). The GitHub token comes from your git
credential helper and is never printed.
"""
import argparse, glob, importlib.util, json, mimetypes, os, subprocess, sys, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
API = 'https://api.github.com/repos/voidfnc/mw4-texture-streaming-research'


def load_build():
    spec = importlib.util.spec_from_file_location('ccs_build', os.path.join(HERE, 'build.py')); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def collect(out, v):
    """The files of this version in `out`: installer, zip, checksums. Anything missing (or left over from another version) stops the release."""
    want = [f'MW4-Texture-Streaming-{v}-Setup.exe', f'MW4-Texture-Streaming-{v}-win64-portable.zip', 'SHA256SUMS.txt']
    missing = [w for w in want if not os.path.exists(os.path.join(out, w))]
    if missing: sys.exit(f'not built for version {v}: missing {", ".join(missing)} in {out} (run packaging\\build.bat first)')
    sums = open(os.path.join(out, 'SHA256SUMS.txt'), encoding='utf-8').read()
    if any(w not in sums for w in want[:2]): sys.exit('SHA256SUMS.txt does not list this version\'s files: rebuild')
    return [os.path.join(out, w) for w in want]


def git(*a): return subprocess.run(['git', *a], cwd=REPO, capture_output=True, text=True).stdout.strip()


def token():
    cred = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n', capture_output=True, text=True).stdout
    return dict(l.split('=', 1) for l in cred.splitlines() if '=' in l)['password']


def request(method, url, tok, data=None, ctype='application/json'):
    req = urllib.request.Request(url, method=method, data=data, headers={'Authorization': 'Bearer ' + tok, 'Accept': 'application/vnd.github+json', 'User-Agent': 'mw4-release', 'Content-Type': ctype})
    try:
        with urllib.request.urlopen(req, timeout=600) as r: return json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e: sys.exit(f'GitHub said {e.code}: {e.read().decode("utf-8", "replace")[:300]}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument('--dry-run', action='store_true'); ap.add_argument('--out', default=os.path.join(HERE, 'out'))
    a = ap.parse_args(argv); b = load_build(); v = b.read_version(); tag = 'v' + v; files = collect(os.path.abspath(a.out), v); notes = b.release_notes(v)
    if git('status', '--porcelain'): sys.exit('the working tree has uncommitted changes: commit or stash them, rebuild, then release')
    if subprocess.run(['git', 'fetch', '-q', 'origin', 'main'], cwd=REPO).returncode != 0: sys.exit('could not fetch origin/main (offline?): without it HEAD cannot be compared with the published source')
    head = git('rev-parse', 'HEAD')
    if not head or head != git('rev-parse', 'origin/main'): sys.exit('HEAD is not origin/main: merge your work and update main first, so the release is made from published source')
    print(f'release {tag} ({"pre-release" if "-" in v else "release"}), draft, from {git("rev-parse", "--short", "HEAD")}')
    for f in files: print(f'  {os.path.basename(f)}  {os.path.getsize(f) / 2**20:.1f} MiB')
    print('notes:\n' + notes)
    if a.dry_run: return
    tok = token(); rel = request('POST', API + '/releases', tok, json.dumps(dict(tag_name=tag, target_commitish=git('rev-parse', 'HEAD'), name=tag, body=notes, draft=True, prerelease='-' in v)).encode())
    for f in files:
        name = os.path.basename(f); request('POST', f"https://uploads.github.com/repos/voidfnc/mw4-texture-streaming-research/releases/{rel['id']}/assets?name={urllib.request.quote(name)}", tok,
                                           open(f, 'rb').read(), mimetypes.guess_type(f)[0] or 'application/octet-stream'); print('uploaded', name)
    print('draft created (not published):', rel['html_url'])


if __name__ == '__main__':
    main()
