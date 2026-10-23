#!/usr/bin/env python3
"""shoot_installer.py - captures the installer's wizard pages for the README (docs/images/installer-*.png).

  python packaging/shoot_installer.py packaging/out/MW4-Texture-Streaming-<version>-Setup.exe [out-folder] [language]

language = the name shown in setup's language list: "English" (default) or "Русский" (use docs/images/ru as the folder for it). The buttons are found by the captions of that
language's Inno Setup message file, so the walk works in every language listed in ISL below.

It starts the Setup.exe on this PC, walks it by clicking its buttons, grabs each page from the screen and then CANCELS before anything is installed.
The page that shows the install folder (and so a user name) and the "Ready to Install" page are never captured. It sends button clicks to the wizard window (no key presses), so it is safe to keep working; the windows are
Standard library only; run it for every release so the version in the title bar matches (a test checks the README note).
"""
import ctypes, os, subprocess, sys, time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
import make_screenshots as ms

SHOTS = ('installer-language', 'installer-0-mode', 'installer-1-license', 'installer-2-info', 'installer-3-options')
ISL = {'English': 'Default.isl', 'Русский': os.path.join('Languages', 'Russian.isl')}        # name in setup's list -> Inno Setup's message file (the button captions come from it)
u = ctypes.windll.user32
WNDENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
BM_CLICK = 0x00F5
CB_GETCOUNT, CB_GETLBTEXT, CB_GETLBTEXTLEN, CB_SETCURSEL = 0x146, 0x148, 0x149, 0x14E


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


def inno_dir():
    for d in (os.path.expandvars(r'%LOCALAPPDATA%\Programs\Inno Setup 6'), os.path.expandvars(r'%ProgramFiles(x86)%\Inno Setup 6'), os.path.expandvars(r'%ProgramFiles%\Inno Setup 6')):
        if os.path.isdir(d): return d
    sys.exit('Inno Setup 6 not found')


def messages(isl):
    """{message name: text without & accelerators} of an Inno Setup language file."""
    out = {}
    with open(os.path.join(inno_dir(), isl), encoding='utf-8-sig') as f:
        for ln in f:
            if '=' in ln and not ln.startswith((';', '[')): k, v = ln.rstrip('\r\n').split('=', 1); out[k] = v.replace('&', '')
    return out


def pick_language(h, name):
    """Choose `name` in the language dialog (a combo box); the caller presses OK."""
    combo = []
    def cb(c, _):
        cls = ctypes.create_unicode_buffer(64); u.GetClassNameW(c, cls, 64)
        if 'combobox' in cls.value.lower(): combo.append(c)
        return True
    u.EnumChildWindows(h, WNDENUM(cb), 0)
    if not combo: raise SystemExit('language list not found')
    for i in range(u.SendMessageW(combo[0], CB_GETCOUNT, 0, 0)):
        buf = ctypes.create_unicode_buffer(u.SendMessageW(combo[0], CB_GETLBTEXTLEN, i, 0) + 2); u.SendMessageW(combo[0], CB_GETLBTEXT, i, ctypes.byref(buf))
        if buf.value == name: u.SendMessageW(combo[0], CB_SETCURSEL, i, 0); return
    raise SystemExit('language not in the list: ' + name)


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
    lang = sys.argv[3] if len(sys.argv) > 3 else 'English'; m = messages(ISL[lang]); en = messages(ISL['English'])
    title = m['SetupWindowTitle'].split('%1')[0].strip(' -—')                        # "Setup" / "Установка": the wizard's title starts with it
    nxt, cancel, accept = m['ButtonNext'].rstrip(' >').strip(), m['ButtonCancel'], m['LicenseAccepted'][:10]
    me_only = en['PrivilegesRequiredOverrideCurrentUser'].split(' (')[0]                  # the install-mode question comes in the Windows language (English here)
    p = subprocess.Popen([os.path.abspath(sys.argv[1])])
    try:
        done = set(); wiz = None
        for _ in range(100):                                                          # install mode and language list first (in either order), then the wizard
            ws = windows(); wiz = next((h for h, t, c in ws if t.startswith(title) and 'MW4' in t), None)
            mode = next((h for h, t, c in ws if en['PrivilegesRequiredOverrideTitle'] in t), None); sel = next((h for h, t, c in ws if en['SelectLanguageTitle'] in t), None)
            if wiz: break
            if mode and 'mode' not in done:
                done.add('mode')
                if lang == 'English': shot(mode, SHOTS[1], out)
                click(mode, me_only)
            elif sel and 'lang' not in done:
                done.add('lang'); time.sleep(0.5)
                if lang == 'English': shot(sel, SHOTS[0], out)
                pick_language(sel, lang); click(sel, 'OK')
            time.sleep(0.5)
        if not wiz: raise SystemExit('the wizard did not appear')
        h = wiz; time.sleep(1.0)
        click(h, accept); shot(h, SHOTS[2], out)                                      # the notice and licence page, accepted
        click(h, nxt); shot(h, SHOTS[3], out)                                         # what setup does and does not do
        click(h, nxt)                                                                 # install folder page: not captured (it shows a user name)
        click(h, nxt); shot(h, SHOTS[4], out)                                         # options
        click(h, nxt)                                                                 # "Ready to Install": not captured; cancel here, nothing is installed
        click(h, cancel); time.sleep(1.0)                                             # the confirmation box is left open: the process is ended below, nothing was installed
    finally:
        if p.poll() is None: subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True)


if __name__ == '__main__':
    main()
