#!/usr/bin/env python3
"""diskguard - protect free disk space during a streaming test.
Logs the size of xpak_cache/ every 10 s; if it exceeds the limit it terminates the programs on its list (default: sp26-cod.exe, the campaign;
the multiplayer / HQ program cod.exe is never ended unless it is added to the list) so the drive cannot fill. Locations/process names: GUI Game tab (tools/work/gui_settings.json).

  python tools/diskguard.py [limit_gib=18]                   (legacy positional form)
  python tools/diskguard.py --limit-gib 100 [--action kill|warn] [--status-json PATH] [--interval 10] [--cache DIR]

--action warn only logs LIMIT HIT and keeps watching (the GUI shows it); kill (default) terminates the game and exits.
--status-json: atomic snapshot {pid, cache_gib, free_gib, limit_gib, hit, ts} for the GUI.
"""
import argparse, json, os, sys, time, subprocess, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ccslib import paths            # cache folder, game folder and process names come from the GUI settings (Game tab)
ROOT = paths.GAME_ROOT
LOG = os.path.join(paths.WORK, 'diskguard.log')

def size(c):
    t = 0
    for dp, _, fn in os.walk(c):
        for f in fn:
            try: t += os.path.getsize(os.path.join(dp, f))
            except OSError: pass
    return t

def other_game():
    """Game programs that are running but not on the list this guard may end (the multiplayer / HQ program, by default)."""
    try:
        from ccslib import procs
        kill = {e.lower() for e in paths.KILL_EXES}
        return [e for e in procs.image_running(*paths.GAME_EXES) if e.lower() not in kill]
    except Exception: return []

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('limit', nargs='?', type=float, help='legacy positional limit in GiB')
    ap.add_argument('--limit-gib', type=float); ap.add_argument('--action', choices=('kill', 'warn'), default='kill')
    ap.add_argument('--status-json'); ap.add_argument('--interval', type=float, default=10); ap.add_argument('--cache', default=paths.XPAK_CACHE)
    ap.add_argument('--log', default=LOG)
    a = ap.parse_args(argv)
    limit = (a.limit_gib if a.limit_gib is not None else a.limit if a.limit is not None else 18) * 2**30
    os.makedirs(os.path.dirname(a.log), exist_ok=True)
    def log(line):
        line = f"{time.strftime('%H:%M:%S')} {line}"; print(line, flush=True)
        with open(a.log, 'a', encoding='utf-8') as f: f.write(line + '\n')
    log(f"READY diskguard pid={os.getpid()} limit={limit/2**30:.1f} GiB action={a.action} cache={a.cache}")
    last = -1; hit = False; killed = False; idle_said = False
    while True:
        s = size(a.cache); free = shutil.disk_usage(a.cache if os.path.isdir(a.cache) else ROOT).free
        if s != last:
            log(f"xpak_cache={s/2**30:.3f} GiB free={free/2**30:.1f} GiB"); last = s
        if s > limit and not hit:
            hit = True; where = f"cache {s/2**30:.2f} GiB, free {free/2**30:.1f} GiB"
            if a.action == 'kill':
                out = [(exe, subprocess.run(['taskkill', '/F', '/IM', exe], capture_output=True, text=True, errors='replace')) for exe in paths.KILL_EXES]
                ended = [exe for exe, r in out if r.returncode == 0]
                if ended: killed = True; log(f"LIMIT HIT ({where}) -> {', '.join(ended)} terminated")
                else:
                    idle = all(r.returncode == 128 for _, r in out)                       # taskkill answers 128 when there is no such process
                    other = other_game() if idle else []
                    if not (idle and idle_said):
                        log(f"LIMIT HIT ({where}) -> " + ((f"{', '.join(other)} is running but is not on the list this guard may end (Settings, Disk guard may terminate): warning only, still watching" if other else 'the game is not running, still watching') if idle else 'could not end the game (' + '; '.join(f"{exe}: {(r.stdout + r.stderr).strip()[:120]}" for exe, r in out) + '), still watching'))
                    idle_said = idle; hit = not idle     # not running: look again next time round (it may be started over the limit); a real failure is reported once, not every interval
            else:
                log(f"LIMIT HIT ({where}) -> warn only")
        elif s <= limit: hit = False; idle_said = False
        if a.status_json:
            try:
                tmp = a.status_json + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f: json.dump(dict(pid=os.getpid(), cache_gib=s / 2**30, free_gib=free / 2**30, limit_gib=limit / 2**30, hit=hit, action=a.action, ts=time.time()), f)
                os.replace(tmp, a.status_json)
            except Exception as e: log(f"status-json write failed: {e}")
        if killed: break                                                    # the game was ended: this guard has done its job
        time.sleep(a.interval)

if __name__ == '__main__':
    main()
