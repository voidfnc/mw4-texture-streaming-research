"""procs.py - child-process manager for the CCS tools (proxy, diskguard, mirror, watchers).

Children run detached from the GUI (own process group, no console window, stdout/stderr -> log file), tracked by a pid file in
tools/work/run/<name>.pid = {pid, argv, started, ctime}. ctime (kernel creation time) guards against pid reuse, so a restarted
GUI re-adopts live children instead of duplicating or orphaning them. No third-party dependencies (ctypes + tasklist/netstat).
"""
import ctypes, json, os, re, subprocess, time
from ctypes import wintypes
from . import paths

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
_k32 = ctypes.WinDLL('kernel32', use_last_error=True)
_k32.OpenProcess.restype = wintypes.HANDLE
_PROCESS_QUERY_LIMITED = 0x1000
STILL_ACTIVE = 259


def _pidfile(name): return os.path.join(paths.RUN, f'{name}.pid')


def ctime(pid):
    """Kernel creation time (FILETIME int) of a live process, else None."""
    h = _k32.OpenProcess(_PROCESS_QUERY_LIMITED, False, pid)
    if not h: return None
    try:
        c, e, k, u = (wintypes.FILETIME() for _ in range(4)); code = wintypes.DWORD()
        if not _k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != STILL_ACTIVE: return None
        if not _k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)): return None
        return (c.dwHighDateTime << 32) | c.dwLowDateTime
    finally:
        _k32.CloseHandle(h)


def _load(name):
    try: return json.load(open(_pidfile(name), encoding='utf-8'))
    except Exception: return None


def status(name):
    """-> dict(alive, pid, started, argv, log)"""
    d = _load(name)
    if d and d.get('ctime') is not None and ctime(d['pid']) == d.get('ctime'):      # no creation time stored = it was already gone when it was started (None would match any dead pid)
        return dict(alive=True, **{k: d.get(k) for k in ('pid', 'started', 'argv', 'log')})
    return dict(alive=False, pid=None, started=None, argv=None, log=None)


def start(name, argv, log, cwd=None):
    """Start `argv` as `name` unless it is already alive (then returns its status). stdout/stderr append to `log`."""
    st = status(name)
    if st['alive']: return st
    cwd = cwd or paths.TOOLS
    paths.ensure_dirs(); os.makedirs(os.path.dirname(log), exist_ok=True)
    f = open(log, 'ab')
    env = dict(os.environ, PYTHONUNBUFFERED='1')
    p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, env=env,
                         creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW)
    f.close()
    try: p.wait(timeout=0.3)                                          # a child that fails on start-up (bad argument, import error) is gone within this time
    except subprocess.TimeoutExpired: pass
    d = dict(pid=p.pid, argv=argv, started=time.time(), ctime=ctime(p.pid), log=log)
    if p.poll() is not None or d['ctime'] is None:                    # it exited at once (a bad argument, an import error): say so, the caller then reads the log
        _clear(name); return dict(alive=False, **{k: d[k] for k in ('pid', 'started', 'argv', 'log')})
    json.dump(d, open(_pidfile(name), 'w', encoding='utf-8'))
    return dict(alive=True, **{k: d[k] for k in ('pid', 'started', 'argv', 'log')})


def stop(name, wait=3.0):
    """Terminate the process tree; returns True if something was stopped."""
    st = status(name)
    if not st['alive']: _clear(name); return False
    subprocess.run(['taskkill', '/PID', str(st['pid']), '/T', '/F'], capture_output=True, creationflags=CREATE_NO_WINDOW)
    t0 = time.time()
    while time.time() - t0 < wait and ctime(st['pid']) is not None: time.sleep(0.1)
    if ctime(st['pid']) is not None: return False                     # still there (for example it runs elevated and this process does not): keep the record, it is still true
    _clear(name)
    return True


def _clear(name):
    try: os.remove(_pidfile(name))
    except OSError: pass


def image_running(*exes):
    """Names (lowercase) from `exes` that currently have a running process."""
    try:
        out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, errors='replace', timeout=15, creationflags=CREATE_NO_WINDOW).stdout.lower()
    except Exception:
        return []
    return [e for e in exes if f'"{e.lower()}"' in out]


def port_owner(port, addrs=('127.0.0.1', '[::1]')):
    """-> list of dict(addr, pid, name) listening on `port` for the given local addresses (or wildcard)."""
    try:
        out = subprocess.run(['netstat', '-ano', '-p', 'tcp'], capture_output=True, text=True, errors='replace', timeout=15, creationflags=CREATE_NO_WINDOW).stdout
    except Exception:
        return []
    res = []
    for l in (out or '').splitlines():
        # a listening socket has no peer (0.0.0.0:0 / [::]:0); the state word is localised on non-English Windows, so it is not matched
        m = re.match(r'\s*TCP\s+(\S+):(\d+)\s+(?:0\.0\.0\.0|\[::\]):0\s+\S+\s+(\d+)', l)
        if m and int(m.group(2)) == port:
            a = m.group(1)
            if a in addrs or a in ('0.0.0.0', '[::]'):
                res.append(dict(addr=a, pid=int(m.group(3)), name=_pid_name(int(m.group(3)))))
    return res


def _pid_name(pid):
    try:
        out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'], capture_output=True, text=True, errors='replace', timeout=15, creationflags=CREATE_NO_WINDOW).stdout
        m = re.match(r'"([^"]+)"', out.strip())
        return m.group(1) if m else '?'
    except Exception:
        return '?'


def is_admin():
    try: return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception: return False


def run_elevated(argv, wait_s=120):
    """Run `argv` (list) elevated via UAC (hidden window), wait, return exit code. None if the user declined UAC."""
    class SEI(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND), ('lpVerb', wintypes.LPCWSTR),
                    ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR), ('lpDirectory', wintypes.LPCWSTR),
                    ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE), ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR),
                    ('hkeyClass', wintypes.HKEY), ('dwHotKey', wintypes.DWORD), ('hIconOrMonitor', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]
    if is_admin():
        return subprocess.run(argv, capture_output=True, creationflags=CREATE_NO_WINDOW).returncode
    s = SEI(); s.cbSize = ctypes.sizeof(SEI); s.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS
    s.lpVerb = 'runas'; s.lpFile = argv[0]; s.lpParameters = subprocess.list2cmdline(argv[1:]); s.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(s)):
        return None
    _k32.WaitForSingleObject(s.hProcess, int(wait_s * 1000))
    code = wintypes.DWORD(); _k32.GetExitCodeProcess(s.hProcess, ctypes.byref(code)); _k32.CloseHandle(s.hProcess)
    return code.value


def relaunch_elevated(argv):
    """Start `argv` (list) elevated via UAC and do not wait for it. True = started, False = the user declined or Windows refused."""
    try: return ctypes.windll.shell32.ShellExecuteW(None, 'runas', argv[0], subprocess.list2cmdline(argv[1:]), None, 1) > 32
    except Exception: return False


def tail_lines(path, n=200):
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 256 * 1024))
            data = f.read().decode('utf-8', 'replace')
        return data.splitlines()[-n:]
    except OSError:
        return []
