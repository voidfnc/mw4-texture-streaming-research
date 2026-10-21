#!/usr/bin/env python3
"""make_screenshots.py - regenerate the README screenshots (docs/images/*.png) from the real control window, filled with DEMO data.

  python tools\\make_screenshots.py            writes docs\\images\\*.png
  python tools\\make_screenshots.py --out D:\\shots --only guide-start

Nothing real is shown: the window runs against a throw-away folder (%PUBLIC%\\ccs-demo, removed afterwards) with a fake game folder, its own settings and its own hosts
file, and the numbers are invented. No game is started, the real hosts file and settings are never touched. Windows only, standard library only; run it from a normal
desktop session and leave the mouse and other windows alone for the few seconds it takes (the window is brought to the front and captured from the screen).
Run it again for every release so the screenshots match the version in the title bar.
"""
import argparse, ctypes, math, os, shutil, struct, sys, time, zlib
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = ('first-run', 'home-ready', 'home-playing', 'home-finished', 'settings', 'offline-copy', 'advanced')
ADVANCED = {'advanced': 'Dashboard'}


# ------------------------------------------------------------------------------------------------ PNG + screen grab (no Pillow)

def png_bytes(w, h, rgb):
    """RGB bytes (w*h*3) -> a PNG file, using the 'Sub' filter and zlib (dark flat UIs compress well)."""
    stride = w * 3; raw = bytearray(); zero = bytes(3)
    for y in range(h):
        row = rgb[y * stride:(y + 1) * stride]; raw.append(1); raw += bytes((a - b) & 255 for a, b in zip(row, zero + row[:-3]))
    def chunk(tag, data): return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b'')


def grab(left, top, right, bottom):
    """Copy a rectangle of the screen -> (w, h, rgb bytes)."""
    u, g = ctypes.windll.user32, ctypes.windll.gdi32; w, h = right - left, bottom - top
    u.GetDC.restype = wintypes.HDC; g.CreateCompatibleDC.restype = wintypes.HDC; g.CreateCompatibleBitmap.restype = wintypes.HBITMAP; g.SelectObject.restype = wintypes.HGDIOBJ
    g.CreateCompatibleDC.argtypes = [wintypes.HDC]; g.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]; g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    g.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    g.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    g.DeleteObject.argtypes = [wintypes.HGDIOBJ]; g.DeleteDC.argtypes = [wintypes.HDC]; u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    class BIH(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('w', wintypes.LONG), ('h', wintypes.LONG), ('planes', wintypes.WORD), ('bits', wintypes.WORD), ('comp', wintypes.DWORD),
                    ('img', wintypes.DWORD), ('xp', wintypes.LONG), ('yp', wintypes.LONG), ('used', wintypes.DWORD), ('imp', wintypes.DWORD)]
    screen = u.GetDC(None); mem = g.CreateCompatibleDC(screen); bmp = g.CreateCompatibleBitmap(screen, w, h); g.SelectObject(mem, bmp)
    try:
        if not g.BitBlt(mem, 0, 0, w, h, screen, left, top, 0x00CC0020 | 0x40000000): raise OSError('screen copy failed')
        bi = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0); buf = ctypes.create_string_buffer(w * h * 4)
        if not g.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0): raise OSError('could not read the bitmap')
    finally:
        g.DeleteObject(bmp); g.DeleteDC(mem); u.ReleaseDC(None, screen)
    bgra = buf.raw; rgb = bytearray(w * h * 3); rgb[0::3] = bgra[2::4]; rgb[1::3] = bgra[1::4]; rgb[2::3] = bgra[0::4]
    return w, h, bytes(rgb)


def window_rect(tk_window):
    """Outer rectangle of a Tk window including its title bar (without the shadow)."""
    u = ctypes.windll.user32; u.GetAncestor.restype = wintypes.HWND; hwnd = u.GetAncestor(wintypes.HWND(tk_window.winfo_id()), 2)
    r = wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)) != 0: u.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


# ------------------------------------------------------------------------------------------------ the demo window

def demo_series(now, n=180):
    """A believable 3-minute throughput trace: (time, requests, bytes, requests/s, MiB/s)."""
    out = []; req = 3600; total = 0
    for i in range(n):
        rps = 24 + 9 * math.sin(i / 17.0) + 4 * math.sin(i / 5.0) + (7 if 90 < i < 120 else 0); mibps = rps * 0.62 + 1.0 * math.sin(i / 3.0)
        req += rps; total += mibps * 2 ** 20; out.append((now - (n - i), int(req), int(total), rps, mibps))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='Regenerate the README screenshots with demo data.'); ap.add_argument('--out', default=os.path.join(HERE, '..', 'docs', 'images'))
    ap.add_argument('--only', choices=SHOTS, action='append', help='only this screenshot (repeatable)'); a = ap.parse_args(argv)
    if sys.platform != 'win32': sys.exit('Windows only.')
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception: pass
    demo = os.path.join(os.environ.get('PUBLIC') or os.path.expanduser('~'), 'ccs-demo')
    if os.path.exists(demo): sys.exit(f'{demo} already exists (a previous run?). Remove it and try again.')
    game = os.path.join(demo, 'Games', 'Modern Warfare 4'); os.makedirs(os.path.join(game, 'cod26')); open(os.path.join(game, 'cod26', 'demo_cdn.xpak'), 'wb').write(b'0')
    os.environ['CCS_WORK'] = os.path.join(demo, 'work'); os.environ['CCS_HOSTS_PATH'] = os.path.join(demo, 'hosts'); open(os.environ['CCS_HOSTS_PATH'], 'w').write('127.0.0.1 localhost\n')
    os.environ['CCS_GAME_ROOT'] = game
    sys.path.insert(0, HERE)
    out = os.path.abspath(a.out); os.makedirs(out, exist_ok=True)
    try:
        from ccslib import version
        for name in (a.only or SHOTS): shoot(name, out, game, version)
    finally:
        shutil.rmtree(demo, ignore_errors=True)
    print('version', version.__version__)


def shoot(name, out, game, version):
    import ccsgui
    from ccslib import config, guide, paths, ui
    ui.system_reduces_motion = lambda: False                                              # shown as it runs on a PC with animations on
    app = ccsgui.App(selftest=True); app.geometry(('1200x780' if name in ADVANCED else '1100x760') + '+40+30'); app.stop_poll.set(); time.sleep(1.3)
    try:
        now = time.time(); cfg = app.cfg; cfg['notice_ack'] = version.__version__; cfg['paths']['game_root'] = game; config.save(cfg)
        st = guide.new_state(enabled=False, simple=False, path='' if name == 'first-run' else 'quick', offered=version.__version__)
        base = dict(t=now, hosts='ABSENT', resolve=dict(ok=False), game=[], owners=[], free=412.0, pproc=dict(alive=False), gproc=dict(alive=False), pstat=None, mproc=dict(alive=False))
        live = dict(base, hosts='OK', resolve=dict(ok=True), pproc=dict(alive=True, pid=7412), gproc=dict(alive=True), gstat=dict(cache_gib=12.4, limit_gib=100, hit=False),
                    pstat=dict(pid=7412, now=now, started=now - 1062, hist={'<=64K': 310, '<=256K': 1480, '<=1M': 1710, '<=4M': 640, '<=8M': 58, '<=16M': 14}, recent=[], mirror_ids=0,
                               stat=dict(req=4212, mirror=0, ok=4198, err=0, retry=3, cliabort=21, skip=0, miss=0, bytes=int(2.6 * 2 ** 30), mbytes=0)))
        snap = base; plan = dict(total=dict(chunks=57200, gib=76.0, stored=23455, stored_gib=31.0, pending=33745, pending_gib=45.0), fits=True, free_gib=412.0, need_gib=46.0, eta_h=None, levels={}, by_pkg={}, missing=[], scope='sp', level='ultra')
        if name in ('home-playing', 'advanced'): st['ms'] = ['session', 'game']; snap = dict(live, game=['sp26-cod.exe'])
        elif name == 'home-finished': st['ms'] = ['session', 'game', 'after']; st['summary'] = dict(req=4543, mirror=0, upok=4543, err=0, skip=0, secs=2640)
        elif name == 'offline-copy': snap = dict(base, mproc=dict(alive=True), mprog=dict(queued=33745, ok=7900, fail=0, retry=3, left=25845, now=now, started=now - 840, mibps=9.4, state='running', bytes=int(9.1 * 2 ** 30), budget_gib=80.0, free_gib=412.0))
        app.cfg['guide'] = st; app.snap = snap; app._guide_save(st); app._gfc = None; app.pack_refresh = lambda: None
        app.attributes('-topmost', True); app.lift(); app.focus_force()
        if name in ADVANCED: app.show_page('advanced'); app._goto(ADVANCED[name])
        else:
            app.show_page('home')
            if name == 'offline-copy': app.home_page.show_page('download')
        end = time.time() + 2.6
        while time.time() < end: app.update(); time.sleep(0.03)
        if name in ('home-playing', 'advanced'):                                         # one real pass for the counters, then freeze them and draw the demo trace
            app.series.clear(); app.series.extend(demo_series(now)); app._refresh_counters = lambda ps, s: None
            if name == 'advanced': app._draw_spark(); app.cnt['rps'].configure(text=f'{demo_series(now)[-1][3]:.1f}')
        if name == 'offline-copy': app._pack_plan = plan; app._pack_err = None
        app.act.configure(state='normal'); app.act.delete('1.0', 'end'); app.act.configure(state='disabled')
        for i, (tag, text) in enumerate([('ACC', '--- Start session ---'), ('', 'hosts: apply'), ('', 'proxy: READY'), ('OK', 'Session READY: proxy 80 up, hosts override active'), ('', 'game detected: sp26-cod.exe')]): app._put(app.act, f'14:{15 + i:02d}:08 {text}', tag or None, scroll=False)
        for _ in range(25): app.update(); time.sleep(0.03)
        app._home_tick()
        if name == 'settings': app.home_page.toggle_drawer()
        for _ in range(20): app.update(); time.sleep(0.03)
        l, t, r, b = window_rect(app); b = min(b, app.winfo_rooty() + app.winfo_height()); w, h, rgb = grab(l, t, r, b)          # not below the client area: the frame's edge shows what is behind
        path = os.path.join(out, name + '.png'); open(path, 'wb').write(png_bytes(w, h, rgb)); print(f'{name}: {w}x{h}, {os.path.getsize(path) // 1024} KiB -> {path}')
    finally:
        app.stop_poll.set(); app.destroy()


if __name__ == '__main__':
    main()
