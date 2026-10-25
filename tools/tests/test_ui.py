"""The UI kit (ccslib/ui.py): the computed images, the colour helpers and the small widgets."""
import gc, struct, sys, unittest, zlib
import test_ccs                                    # sets CCS_WORK before ccslib is imported
sys.path.insert(0, test_ccs.TOOLS)
import tkinter as tk
from ccslib import ui


def _quiet_variable_del(orig=tk.Variable.__del__):
    """A window that is collected from a worker thread (a garbage collection can start anywhere) makes tkinter print 'main thread is not in main loop' for its variables: harmless, so keep the test log clean."""
    def __del__(self):
        try: orig(self)
        except (RuntimeError, tk.TclError): pass
    return __del__


tk.Variable.__del__ = _quiet_variable_del()


def decode(data):
    """A tiny RGBA PNG decoder (filter 0 only: what ui.png writes) -> (w, h, rows of bytes)."""
    assert data[:8] == b'\x89PNG\r\n\x1a\n'; pos = 8; idat = b''; w = h = 0
    while pos < len(data):
        n, tag = struct.unpack('>I4s', data[pos:pos + 8]); body = data[pos + 8:pos + 8 + n]; assert zlib.crc32(tag + body) & 0xffffffff == struct.unpack('>I', data[pos + 8 + n:pos + 12 + n])[0]
        if tag == b'IHDR': w, h, depth, ctype = struct.unpack('>IIBB', body[:10]); assert (depth, ctype) == (8, 6)
        elif tag == b'IDAT': idat += body
        pos += 12 + n
    raw = zlib.decompress(idat); stride = w * 4; rows = []
    for y in range(h):
        assert raw[y * (stride + 1)] == 0; rows.append(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
    return w, h, rows


def px(rgba, w, x, y): return tuple(rgba[4 * (y * w + x):4 * (y * w + x) + 4])


class ImageTests(unittest.TestCase):
    def test_png_round_trips(self):
        rgba = bytes([10, 20, 30, 255, 1, 2, 3, 128, 0, 0, 0, 0, 255, 255, 255, 255]); w, h, rows = decode(ui.png(2, 2, rgba))
        self.assertEqual((w, h), (2, 2)); self.assertEqual(b''.join(rows), rgba)

    def test_colour_helpers(self):
        self.assertEqual(ui.rgb('#0a0d13'), (10, 13, 19)); self.assertEqual(ui.hexc((10, 13, 19)), '#0a0d13'); self.assertEqual(ui.hexc((300, -5, 1.4)), '#ff0001')
        self.assertEqual(ui.mix('#000000', '#ffffff', .5), '#808080'); self.assertEqual(ui.mix('#102030', '#102030', .7), '#102030'); self.assertEqual(ui.lighten('#000000', 1), '#ffffff'); self.assertEqual(ui.darken('#ffffff', 1), '#000000')

    def test_corners_are_round_and_soft(self):
        w, h, rgba = ui.corner_rgba(12, '#4c8dff', 'tl'); self.assertEqual((w, h), (12, 12)); self.assertEqual(px(rgba, 12, 0, 0)[3], 0)            # outside the arc
        self.assertEqual(px(rgba, 12, 11, 11), (0x4c, 0x8d, 0xff, 255)); self.assertEqual(px(rgba, 12, 11, 0)[3], 255)                                    # inside, and the straight top edge
        edge = [px(rgba, 12, x, y)[3] for y in range(12) for x in range(12)]; self.assertTrue(any(0 < a < 255 for a in edge), 'no soft edge pixels')
        tr = ui.corner_rgba(12, '#4c8dff', 'tr')[2]; self.assertEqual(px(tr, 12, 11, 0)[3], 0); self.assertEqual(px(tr, 12, 0, 11)[3], 255)
        br = ui.corner_rgba(12, '#4c8dff', 'br')[2]; self.assertEqual(px(br, 12, 11, 11)[3], 0); self.assertEqual(px(br, 12, 0, 0)[3], 255)

    def test_pill_has_round_ends_a_gradient_and_a_border(self):
        w, h, rgba = ui.pill_rgba(80, 30, '#4c8dff', '#27d3c0'); self.assertEqual((w, h), (80, 30)); self.assertEqual(px(rgba, w, 0, 0)[3], 0); self.assertEqual(px(rgba, w, 40, 15)[3], 255)
        left, right = px(rgba, w, 20, 15), px(rgba, w, 60, 15); self.assertGreater(right[1], left[1])                                                       # the green channel grows to the right
        b = ui.pill_rgba(80, 30, '#171e2d', None, '#2d3852', 1)[2]; self.assertEqual(px(b, 80, 40, 0)[:3], (0x2d, 0x38, 0x52)); self.assertEqual(px(b, 80, 40, 15)[:3], (0x17, 0x1e, 0x2d))
        sq = ui.pill_rgba(32, 32, '#4c8dff', '#27d3c0', None, 1, 0, 9)[2]; self.assertGreater(px(sq, 32, 0, 0)[3] + 1, 0); self.assertEqual(px(sq, 32, 16, 0)[3], 255); self.assertEqual(px(sq, 32, 0, 0)[3], 0)

    def test_ring_geometry(self):
        size, thick = 120, 10; w, h, rgba = ui.ring_rgba(size, .5, thick, '#4c8dff', '#27d3c0', '#1a2233', '#0f1420', pad=2)
        c = size / 2; R = c - 2 - thick / 2
        top = px(rgba, size, int(c), int(c - R)); self.assertEqual(top[3], 255); self.assertNotEqual(top[:3], (0x1a, 0x22, 0x33))                    # the arc starts at the top, in colour
        right = px(rgba, size, int(c + R), int(c)); self.assertEqual(right[3], 255); self.assertNotEqual(right[:3], (0x1a, 0x22, 0x33))                  # a quarter turn: still arc
        left = px(rgba, size, int(c - R), int(c)); self.assertEqual(left[:3], (0x1a, 0x22, 0x33))                                                         # past the half: the track
        self.assertEqual(px(rgba, size, int(c), int(c))[:3], (0x0f, 0x14, 0x20)); self.assertEqual(px(rgba, size, 0, 0)[3], 0)                           # the inner disc, and nothing outside
        full = ui.ring_rgba(size, 1.0, thick, '#4c8dff', '#27d3c0', '#1a2233', '#0f1420', pad=2)[2]; self.assertNotEqual(px(full, size, int(c - R), int(c))[:3], (0x1a, 0x22, 0x33))
        off = ui.ring_rgba(size, 0.0, thick, '#4c8dff', '#27d3c0', '#1a2233', '#0f1420', pad=2)[2]; self.assertEqual(px(off, size, int(c), int(c - R))[:3], (0x1a, 0x22, 0x33))
        self.assertTrue(decode(ui.png(w, h, rgba))[0] == size)

    def test_ring_halo_is_soft_and_outside_the_stroke(self):
        size = 140; h = ui.ring_rgba(size, 1.0, 10, '#4c8dff', '#27d3c0', '#1a2233', '#0f1420', halo='#27d3c0', halo_a=.4, sigma=6.0)[2]; c = size / 2; pad = 6 * 2.4; R = c - pad - 5
        glow = px(h, size, int(c), int(c - R - 9)); self.assertTrue(0 < glow[3] < 255); self.assertEqual(px(h, size, 0, 0)[3], 0)
        ho = ui.halo_rgba(size, 10, '#27d3c0', 1.0, 6.0); self.assertEqual(ho[0], size); halves = ui.scale_alpha(ho[2], .5)
        a1, a2 = px(ho[2], size, int(c), int(c - R - 6))[3], px(halves, size, int(c), int(c - R - 6))[3]; self.assertTrue(a1 > 0 and abs(a2 - a1 / 2) <= 1); self.assertEqual(len(halves), len(ho[2]))

    def test_every_icon_draws_something_and_stays_inside_its_box(self):
        for name in ui.ICONS:
            w, h, rgba = ui.icon_rgba(name, 24, '#ffffff'); self.assertEqual((w, h, len(rgba)), (24, 24, 24 * 24 * 4)); alpha = rgba[3::4]
            self.assertGreater(sum(1 for a in alpha if a), 15, name); self.assertTrue(any(a >= 200 for a in alpha), name)
        big = ui.icon_rgba('power', 64, '#ffffff', 2.0); self.assertGreater(sum(1 for a in big[2][3::4] if a), 150)

    def test_glow_surrounds_the_pill(self):
        w, h, rgba = ui.glow_rgba(100, 40, 16, '#4c8dff', .3, 8.0, 5); self.assertEqual((w, h), (132, 72)); self.assertEqual(px(rgba, w, 0, 0)[3], 0); self.assertGreater(px(rgba, w, 66, 16 + 40 + 4)[3], 0)

    def test_fonts_and_scale(self):
        self.assertEqual(ui.S(10), 10)
        ui.SCALE = 1.5
        try: self.assertEqual(ui.S(10), 15)
        finally: ui.SCALE = 1.0

    def test_scale_alpha_is_a_plain_multiplication(self):
        src = bytes([1, 2, 3, 200, 4, 5, 6, 0]); out = ui.scale_alpha(src, .5); self.assertEqual(out, bytes([1, 2, 3, 100, 4, 5, 6, 0])); self.assertEqual(ui.scale_alpha(src, 0)[3::4], b'\x00\x00')


class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk(); cls.root.withdraw(); ui.init(cls.root); cls.ticker = ui.Ticker(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy(); cls.root = None; gc.collect()

    def test_button_states_and_invoke(self):
        hits = []; b = ui.Button(self.root, 'Turn on', lambda: hits.append(1), kind='primary', icon_name='power'); b.pack(); self.root.update()
        b.invoke(); self.assertEqual(hits, [1]); self.assertTrue(b.is_enabled()); b.enable(False); b.invoke(); self.assertEqual(hits, [1]); self.assertFalse(b.is_enabled()); b.enable(True)
        w0 = int(b['width']); b.set_text('Turn it on right now'); self.assertGreater(int(b['width']), w0); self.assertEqual(b.text, 'Turn it on right now')
        b.event_generate('<Enter>'); b.event_generate('<Leave>'); b.set_kind('warn'); self.assertEqual(b.kind, 'warn')
        for kind in ui.Button.KINDS:
            x = ui.Button(self.root, 'x', None, kind=kind); x._set(hover=True); x._set(down=True); x._set(has_focus=True); x.enable(False); x.destroy()

    def test_button_keyboard_and_release_inside(self):
        hits = []; b = ui.Button(self.root, 'Go', lambda: hits.append(1)); b.pack(); self.root.update()
        self.assertTrue(b.bind('<Return>') and b.bind('<space>')); self.assertEqual(str(b['takefocus']), '1'); b.invoke(); b.invoke(); self.assertEqual(len(hits), 2)

    def test_panel_follows_its_content(self):
        p = ui.Panel(self.root); p.pack(fill='x'); lab = tk.Label(p.body, text='hello\nthere', bg=ui.CARD); lab.pack(); self.root.update(); self.root.update()
        self.assertGreaterEqual(int(p['height']), lab.winfo_reqheight() + 2 * p.py); lab.configure(text='a\nb\nc\nd'); self.root.update(); p._fit(); self.assertGreaterEqual(int(p['height']), lab.winfo_reqheight() + 2 * p.py)
        p.style(fill=ui.CARD2, border=ui.ACCENT); self.root.update(); p.destroy()
        s = ui.Panel(self.root, shrink=True); s.pack(); tk.Label(s.body, text='short', bg=ui.CARD).pack(); self.root.update(); self.root.update(); self.assertLess(int(s['width']), 200); s.destroy()

    def test_shape_places_and_recolors(self):
        cv = tk.Canvas(self.root, width=100, height=60, bg=ui.BG); cv.pack(); outer, inner = ui.round_box(cv, 0, 0, 100, 60, 14, ui.CARD, ui.LINE); self.assertEqual(len(outer.ids), 7); self.assertEqual(len(inner.ids), 7)
        inner.recolor(ui.CARD2); self.assertEqual(inner.color, ui.CARD2); inner.place(0, 0, 20, 20, 99); self.assertEqual(inner.r, 10); tiny = ui.Shape(cv, 0, 0, 3, 3, 0, ui.CARD); self.assertEqual(len(tiny.ids), 1); cv.destroy()

    def test_ring_sets_every_kind_and_animates_only_what_moves(self):
        r = ui.Ring(self.root, d=100, thick=8, ticker=self.ticker); r.pack(); self.root.update()
        for kind in ui.Ring.TONE: r.set(kind, .4, 'power', '12', 'things'); self.root.update()
        r.set('on', 1, 'power', '', 'ON'); self.assertTrue(r._pulse_on); r.set('off', 0, 'power'); self.assertFalse(r._pulse_on); r.set('work', .28, 'power'); self.assertTrue(r._spin_on); r.set('full', 1, None, '5'); self.assertFalse(r._spin_on)
        self.assertEqual(self.ticker.jobs, {}); r.destroy()

    def test_ticker_runs_jobs_drops_dead_ones_and_can_be_switched_off(self):
        t = ui.Ticker(self.root, fps=50); hits = []; t.add('a', lambda s: hits.append(s)); import time
        end = time.time() + .3
        while time.time() < end: self.root.update(); time.sleep(.01)
        self.assertGreater(len(hits), 2); t.remove('a'); n = len(hits); end = time.time() + .1
        while time.time() < end: self.root.update(); time.sleep(.01)
        self.assertEqual(len(hits), n); t.set_enabled(False); t.add('b', lambda s: hits.append(1)); self.assertEqual(t.jobs, {})
        t.set_enabled(True); t.add('c', lambda s: (_ for _ in ()).throw(tk.TclError('gone'))); end = time.time() + .15
        while time.time() < end: self.root.update(); time.sleep(.01)
        self.assertEqual(t.jobs, {})

    def test_stepper_and_nav_item(self):
        s = ui.Stepper(self.root); s.pack(); s.set(['A', 'B', 'C', 'D'], 1); sig = s.sig; s.set(['A', 'B', 'C', 'D'], 1); self.assertIs(s.sig, sig); s.set(['A', 'B', 'C', 'D'], 4); self.root.update(); s.destroy()
        hits = []; n = ui.NavItem(self.root, 'Doctor', 'shield', lambda: hits.append(1)); n.pack(); n.select(True); n.mark('> '); self.assertEqual(n.lbl.cget('text'), '> Doctor'); n.mark(); self.assertEqual(n.lbl.cget('text'), 'Doctor')
        self.assertTrue(n.bind('<Button-1>') and n.lbl.bind('<Button-1>') and n.img.bind('<Button-1>')); n.command(); self.assertEqual(len(hits), 1); n.destroy()

    def test_images_are_cached_per_key_and_per_root(self):
        calls = []
        def make(): calls.append(1); return 2, 2, bytes(16)
        a = ui.photo(self.root, 'k', make); b = ui.photo(self.root, 'k', make); self.assertIs(a, b); self.assertEqual(len(calls), 1)
        i = ui.icon(self.root, 'check', 16, '#ffffff'); self.assertIs(i, ui.icon(self.root, 'check', 16, '#ffffff')); self.assertEqual(i.width(), 16)
        f = ui.font(self.root, 14); self.assertEqual(f[1], -14); self.assertEqual(len(ui.font(self.root, 20, 'head', True)) >= 2, True)

    def test_the_cache_limit_never_frees_a_picture_that_is_on_screen(self):
        """The animations make a new picture per step; once the cache was full the OLDEST ones were freed, which are the permanent ones (logo, icons): Tk then said
        `image "pyimageNN" doesn't exist` when such an item was touched again."""
        make = lambda: (2, 2, bytes(16)); cv = tk.Canvas(self.root); self.addCleanup(cv.destroy)
        shown = ui.photo(cv, ('shown-forever',), make); name = shown.name; item = cv.create_image(0, 0, image=shown); del shown      # only the cache and the canvas hold it now
        cache = self.root.__dict__['_ui_images']
        for n in range(ui.CACHE_MAX * 2 + 50): ui.photo(cv, ('step', n), make)                       # far past the limit, none of these is shown
        gc.collect()
        self.assertIn(('shown-forever',), cache); self.assertEqual(int(self.root.tk.call('image', 'width', name)), 2)         # still there for Tk
        cv.itemconfigure(item, image=name)                                                          # touching the item is fine (it raised TclError when the picture was gone)
        self.assertLessEqual(len(cache), ui.CACHE_MAX, 'pictures nothing shows are still dropped')
        last = ui.photo(cv, ('last',), make); self.assertIs(ui.photo(cv, ('last',), make), last)    # the newest is kept even when everything else is in use


if __name__ == '__main__':
    unittest.main()
