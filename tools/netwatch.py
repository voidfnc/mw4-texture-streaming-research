#!/usr/bin/env python3
"""netwatch - log DNS queries and TCP connections made by sp26-cod.exe (read-only).
Needs: DNS-Client/Operational log enabled (wevtutil sl Microsoft-Windows-DNS-Client/Operational /e:true).
Usage: python tools/netwatch.py [seconds=1200]   -> tools/work/netwatch.log
"""
import subprocess, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ccslib import paths
LOG = os.path.join(paths.WORK, 'netwatch.log')          # where the control window's Logs tab looks
os.makedirs(paths.WORK, exist_ok=True)
def ps(c):
    return subprocess.run(['powershell', '-NoProfile', '-Command', c], capture_output=True, text=True, timeout=90).stdout
def pid():
    return ps("(Get-Process sp26-cod -ErrorAction SilentlyContinue | select -First 1).Id").strip()
def log(m):
    l = f"{time.strftime('%H:%M:%S')} {m}"; print(l, flush=True); open(LOG, 'a', encoding='utf-8').write(l + '\n')
seen = set(); t0 = time.time(); last = time.time()
span = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
while time.time() - t0 < span:
    p = pid()
    if not p:
        time.sleep(5); continue
    ev = ps(f"Get-WinEvent -FilterHashtable @{{LogName='Microsoft-Windows-DNS-Client/Operational';StartTime=(Get-Date).AddSeconds(-20)}} -ErrorAction SilentlyContinue | ? {{ $_.ProcessId -eq {p} -and $_.Id -in 3006,3008,3010,3020 }} | % {{ \"$($_.Id) $(($_.Message -split '\n')[0])\" }}")
    for l in ev.splitlines():
        if l.strip() and ('dns', l) not in seen: seen.add(('dns', l)); log("DNS pid=" + p + " " + l.strip())
    s = ps(f"Get-NetTCPConnection -OwningProcess {p} -ErrorAction SilentlyContinue | ? {{ $_.RemoteAddress -notmatch '^(0\\.0|127\\.|::|172\\.21\\.176)' }} | % {{ \"$($_.State) $($_.RemoteAddress):$($_.RemotePort)\" }}")
    for l in s.splitlines():
        if l.strip() and ('tcp', l) not in seen: seen.add(('tcp', l)); log("TCP " + l.strip())
    time.sleep(4)
