#!/usr/bin/env python3
"""cachewatch - capture what the game writes/contacts during a run.

  python tools/cachewatch.py baseline          # snapshot install tree (sizes+mtimes)
  python tools/cachewatch.py watch [seconds]   # poll: new/changed files, sp26-cod.exe sockets, DNS cache
  python tools/cachewatch.py diff              # new/changed files vs baseline (+ KAPI header dump)

Writes tools/work/cachewatch.json (baseline) and tools/work/cachewatch.log (timeline).
Read-only with respect to the game; no hooks, no injection.
"""
import os, sys, json, time, subprocess, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ccslib import paths            # game folder / work dir come from the GUI settings (Game tab)
ROOT = paths.GAME_ROOT
BASE = os.path.join(paths.WORK, 'cachewatch.json')
LOG = os.path.join(paths.WORK, 'cachewatch.log')
SKIP = ('tools' + os.sep, 'docs' + os.sep)

def snap():
    out = {}
    for dp, dn, fn in os.walk(ROOT):
        rel = os.path.relpath(dp, ROOT) + os.sep
        if rel.startswith(SKIP):
            dn[:] = []
            continue
        dn[:] = [d for d in dn if not os.lstat(os.path.join(dp, d)).st_file_attributes & 0x400]       # do not follow junctions (sp26\xpak_cache is one after the game setup)
        for f in fn:
            p = os.path.join(dp, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out[os.path.relpath(p, ROOT)] = [st.st_size, int(st.st_mtime)]
    return out

def ps(cmd):
    return subprocess.run(['powershell', '-NoProfile', '-Command', cmd], capture_output=True, text=True, timeout=60).stdout

def sockets():
    return ps("Get-Process sp26-cod,cod -ErrorAction SilentlyContinue | ForEach-Object { $p=$_.Id; "
              "Get-NetTCPConnection -OwningProcess $p -ErrorAction SilentlyContinue | "
              "Where-Object {$_.State -ne 'Listen'} | ForEach-Object { \"$p $($_.State) $($_.RemoteAddress):$($_.RemotePort)\" } }").strip()

def dns():
    return ps("Get-DnsClientCache | Where-Object {$_.Entry -match 'callofduty|demonware|embodyvr|akamai|activision'} | "
              "ForEach-Object { \"$($_.Entry) $($_.Data)\" }").strip()

def kapi(p):
    d = open(p, 'rb').read(0x40)
    if d[:4] != b'KAPI':
        return ''
    return f"KAPI ver={struct.unpack_from('<H', d, 4)[0]} type={struct.unpack_from('<I', d, 0x10)[0]} hashes={struct.unpack_from('<I', d, 0x14)[0]}"

def diff(base):
    cur = snap(); rows = []
    for k, v in sorted(cur.items()):
        if k not in base:
            rows.append(('NEW', k, v))
        elif base[k] != v:
            rows.append(('CHG', k, v))
    for k in base:
        if k not in cur:
            rows.append(('DEL', k, base[k]))
    return rows

def log(msg):
    line = time.strftime('%H:%M:%S ') + msg
    print(line, flush=True)
    open(LOG, 'a', encoding='utf-8').write(line + '\n')

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'diff'
    os.makedirs(os.path.dirname(BASE), exist_ok=True)
    if mode == 'baseline':
        json.dump(snap(), open(BASE, 'w'))
        log(f"baseline saved ({len(json.load(open(BASE)))} files)")
    elif mode == 'watch':
        base = json.load(open(BASE)); secs = int(sys.argv[2]) if len(sys.argv) > 2 else 600
        seen = set(); t0 = time.time()
        while time.time() - t0 < secs:
            for tag, k, v in diff(base):
                key = (tag, k, tuple(v))
                if key not in seen:
                    seen.add(key)
                    p = os.path.join(ROOT, k)
                    log(f"{tag} {k} size={v[0]} {kapi(p) if tag != 'DEL' and os.path.exists(p) else ''}")
            s = sockets()
            if s and ('sock', s) not in seen:
                seen.add(('sock', s)); log("SOCKETS\n" + s)
            d = dns()
            if d and ('dns', d) not in seen:
                seen.add(('dns', d)); log("DNS\n" + d)
            time.sleep(3)
    else:
        base = json.load(open(BASE))
        for tag, k, v in diff(base):
            p = os.path.join(ROOT, k)
            print(tag, k, v[0], kapi(p) if tag != 'DEL' and os.path.exists(p) else '')
