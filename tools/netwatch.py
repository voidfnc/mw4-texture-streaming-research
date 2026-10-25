#!/usr/bin/env python3
"""netwatch - log DNS queries and TCP connections made by the game (read-only): the campaign (sp26-cod.exe) and the multiplayer / HQ program (cod.exe) alike, or whatever
programs are listed as game process names in the settings.
Needs: DNS-Client/Operational log enabled (wevtutil sl Microsoft-Windows-DNS-Client/Operational /e:true).
Usage: python tools/netwatch.py [seconds=1200]   -> tools/work/netwatch.log
"""
import re, subprocess, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ccslib import paths
LOG = os.path.join(paths.WORK, 'netwatch.log')          # where the control window's Logs tab looks


def ps(c):
    return subprocess.run(['powershell', '-NoProfile', '-Command', c], capture_output=True, text=True, timeout=90).stdout


def process_names(exes=None):
    """PowerShell process names of the game programs: 'sp26-cod.exe' -> 'sp26-cod'. A name goes into a command line, so only plain characters pass."""
    out = []
    for e in (paths.GAME_EXES if exes is None else exes):
        n = e[:-4] if str(e).lower().endswith('.exe') else str(e)
        if n and re.fullmatch(r'[A-Za-z0-9_.-]+', n) and n not in out: out.append(n)
    return out


def parse_procs(text):
    """'1234 cod' lines -> {pid: process name}"""
    res = {}
    for l in (text or '').splitlines():
        m = re.match(r'\s*(\d+)\s+(\S+)', l)
        if m: res[m.group(1)] = m.group(2)
    return res


def running(run=ps):
    names = process_names()
    if not names: return {}
    return parse_procs(run("Get-Process -Name " + ','.join(names) + " -ErrorAction SilentlyContinue | ForEach-Object { \"$($_.Id) $($_.ProcessName)\" }"))


def poll_once(procs, seen, run=ps):
    """One look at the running game programs {pid: name} -> the new log lines (DNS lookups and TCP connections), each saying which program made it."""
    out = []
    if not procs: return out
    ids = ','.join(procs)
    ev = run(f"Get-WinEvent -FilterHashtable @{{LogName='Microsoft-Windows-DNS-Client/Operational';StartTime=(Get-Date).AddSeconds(-20)}} -ErrorAction SilentlyContinue | ? {{ $_.ProcessId -in {ids} -and $_.Id -in 3006,3008,3010,3020 }} | % {{ \"$($_.ProcessId) $($_.Id) $(($_.Message -split '\n')[0])\" }}")
    for l in ev.splitlines():
        m = re.match(r'\s*(\d+)\s+(.*)', l)
        if m and m.group(2).strip() and ('dns', l) not in seen: seen.add(('dns', l)); out.append(f"DNS pid={m.group(1)} {procs.get(m.group(1), '?')} {m.group(2).strip()}")
    for p, name in procs.items():
        s = run(f"Get-NetTCPConnection -OwningProcess {p} -ErrorAction SilentlyContinue | ? {{ $_.RemoteAddress -notmatch '^(0\\.0|127\\.|::|172\\.21\\.176)' }} | % {{ \"$($_.State) $($_.RemoteAddress):$($_.RemotePort)\" }}")
        for l in s.splitlines():
            if l.strip() and ('tcp', p, l) not in seen: seen.add(('tcp', p, l)); out.append(f"TCP pid={p} {name} " + l.strip())
    return out


def log(m):
    l = f"{time.strftime('%H:%M:%S')} {m}"; print(l, flush=True); open(LOG, 'a', encoding='utf-8').write(l + '\n')


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.makedirs(paths.WORK, exist_ok=True)
    seen = set(); t0 = time.time(); span = int(argv[0]) if argv else 1200; said = set()
    while time.time() - t0 < span:
        procs = running()
        if not procs:
            time.sleep(5); continue
        for p, n in procs.items():
            if p not in said: said.add(p); log(f"watching {n} (pid {p})")
        for l in poll_once(procs, seen): log(l)
        time.sleep(4)


if __name__ == '__main__': main()
