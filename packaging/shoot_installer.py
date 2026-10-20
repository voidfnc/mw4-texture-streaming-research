#!/usr/bin/env python3
"""shoot_installer.py - captures the installer's wizard pages for the README (docs/images/installer-*.png).

  python packaging/shoot_installer.py packaging/out/MW4-Texture-Streaming-<version>-Setup.exe

It starts the Setup.exe on this PC, walks it by clicking its buttons, grabs each page from the screen and then CANCELS before anything is installed.
The page that shows the install folder (and so a user name) and the "Ready to Install" page are never captured. It sends button clicks to the wizard window (no key presses), so it is safe to keep working; the windows are brought to the front for the grab (about 20 seconds).
Standard library only; run it for every release so the version in the title bar matches (a test checks the README note).
"""
import ctypes, os, subprocess, sys, time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
import make_screenshots as ms

SHOTS = ('installer-0-mode', 'installer-1-license', 'installer-2-info', 'installer-3-options')
u = ctypes.windll.user32
WNDENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
BM_CLICK = 0x00F5


def windows():
    res = []
    def cb(h, _):
        if u.IsWindowVisible(h):
            n = u.GetWindowTextLengthW(h); b = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, b, n + 1); cls = ctypes.create_unicode_buffer(64); u.GetClassNameW(h, cls, 64)
            if b.value: res.append((h, b.value, cls.value))
        return True
    u.EnumWindows(WNDENUM(cb), 0); return res


def children(h):
    res = []
    def cb(c, _):
        n = u.GetWindowTextLengthW(c); b = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(c, b, n + 1); res.append((c, b.value.replace('&', ''))); return True
    u.EnumChildWindows(h, WNDENUM(cb), 0); return res


def click(h, label):
    """Press the button (or radio) whose caption starts with `label` by sending it a click message: no focus or key presses needed, so nothing can land in another program."""
    for c, text in children(h):
        if text.startswith(label) and u.IsWindowEnabled(c): u.SendMessageW(c, BM_CLICK, 0, 0); time.sleep(0.8); return
    raise SystemExit(f'button not found: {label}')


def find(prefix, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for h, t, c in windows():
            if t.startswith(prefix): return h
        time.sleep(0.3)
    raise SystemExit('window not found: ' + prefix)


def rect(h):
    r = wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(h), 9, ctypes.byref(r), ctypes.sizeof(r)) != 0: u.GetWindowRect(wintypes.HWND(h), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def shot(h, name, out):
    u.SetWindowPos(h, wintypes.HWND(-1), 0, 0, 0, 0, 0x0003); time.sleep(0.8)           # topmost, so nothing covers it for the grab
    l, t, r, b = rect(h); w, hh, rgb = ms.grab(l, t, r, b); p = os.path.join(out, name + '.png'); open(p, 'wb').write(ms.png_bytes(w, hh, rgb)); print(f'{name}: {w}x{hh}, {os.path.getsize(p) // 1024} KiB')


def main():
    if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]): sys.exit(__doc__)
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception: pass
    out = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(HERE), 'docs', 'images')); os.makedirs(out, exist_ok=True)
    p = subprocess.Popen([os.path.abspath(sys.argv[1])])
    try:
        mode = None
        for _ in range(40):                                                           # the install-mode question comes first, unless setup goes straight to the wizard
            ws = windows(); mode = next((h for h, t, c in ws if 'Install Mode' in t), None)
            if mode or any(t.startswith('Setup - MW4') for h, t, c in ws): break
            time.sleep(0.5)
        if mode: shot(mode, SHOTS[0], out); click(mode, 'Install for me only')
        h = find('Setup - MW4'); time.sleep(1.0); click(h, 'I accept'); shot(h, SHOTS[1], out)       # the notice and licence page, accepted
        click(h, 'Next'); shot(h, SHOTS[2], out)                                      # what setup does and does not do
        click(h, 'Next')                                                              # install folder page: not captured (it shows a user name)
        click(h, 'Next'); shot(h, SHOTS[3], out)                                      # options
        click(h, 'Next')                                                              # "Ready to Install": not captured; cancel here, nothing is installed
        click(h, 'Cancel'); time.sleep(1.0)                                         # the confirmation box is left open: the process is ended below, nothing was installed
    finally:
        if p.poll() is None: subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True)


if __name__ == '__main__':
    main()
