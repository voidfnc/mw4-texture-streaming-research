"""Tests for Warzone support (#75): the Warzone package (never in "all"), list names in the Doctor and the support bundle, which list a requested piece is in (proxy),
and Download what I played (requested.txt -> ccsmirror run --played, side files included). Fake game folders and a fake CDN on localhost only; no game data.
"""
import hashlib, http.client, json, os, shutil, socket, sqlite3, struct, subprocess, sys, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, TOOLS)
import cdnxpak                                                                         # noqa: E402
from ccslib import doctor, home, pack, played                                         # noqa: E402
MiB = 2**20
TMP = tempfile.mkdtemp(prefix='ccswz_')
FOLDER = '3d52ba191ccf221b8e5fd305bb0fd4cb'


def tearDownModule(): shutil.rmtree(TMP, ignore_errors=True)


def make_list(path, recs):
    os.makedirs(os.path.dirname(path), exist_ok=True); d = bytearray(0x8000)
    for i, wire, raw, flag in recs: d += struct.pack('<QIII', i, (wire << 1) | flag, 0, raw)
    open(path, 'wb').write(bytes(d))


def W(i): return 100 + (i & 0xff)


def game(root, stub=False):
    """A small install with the names CB0217 (Steam) and Cynersi (Xbox) posted: the known lists, wz26 + wz26_tr + ww_mp26, a language list and an empty language stub."""
    suf = '_cdn_stub.xpak' if stub else '_cdn.xpak'; rec = lambda i, raw=1 * MiB: (i, W(i), raw, 1)
    make_list(os.path.join(root, 'sp26', 'sp26' + suf), [rec(0x101), rec(0x102)])
    make_list(os.path.join(root, 'sp26', 'boot' + suf), [rec(0x107, 64 * 1024)])
    make_list(os.path.join(root, 'cod26', 'common26' + suf), [rec(0x201)])
    make_list(os.path.join(root, 'cod26', 'mp26' + suf), [rec(0x301)])
    make_list(os.path.join(root, 'cod26', 'ww_mp26' + suf), [rec(0x302)])
    make_list(os.path.join(root, 'cod26', 'wz26' + suf), [rec(0x201), rec(0x501), rec(0x502, 6 * MiB), rec(0x503)])        # 0x201 is shared with common26
    make_list(os.path.join(root, 'cod26', 'wz26_tr' + suf), [rec(0x601, 40 * 1024), rec(0x602, 40 * 1024)])
    make_list(os.path.join(root, 'cod26', 'deu_wz26' + suf), [rec(0x701)])
    os.makedirs(os.path.join(root, 'cod26'), exist_ok=True); open(os.path.join(root, 'cod26', 'fra_wz26' + suf), 'wb').close()   # 0 KB: a language that is not installed
    return root


def chunk(i): return f'/pc/iw9_3/23/{i & 0xff:02x}/{i:016x}_{W(i):08x}_1'
def sidep(i): return f'/pc/iw9_3/23/tr/{FOLDER}/{i:016x}_{W(i):08x}_1'


class FakeCdn(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    seen = []
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.count('_') < 2: self.send_response(404); self.send_header('Content-Length', '0'); self.end_headers(); return
        FakeCdn.seen.append(self.path); wire = int(self.path.rsplit('_', 2)[1], 16); body = bytes([wire & 0xff]) * wire
        self.send_response(200); self.send_header('Content-Length', str(wire)); self.send_header('ETag', f'"{hashlib.md5(body).hexdigest()}"'); self.send_header('x-amz-meta-cod-key', 'k1')
        self.end_headers(); self.wfile.write(body)
    do_HEAD = do_GET


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


class PackageTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.root = game(os.path.join(TMP, 'g1')); cls.xbox = game(os.path.join(TMP, 'g1x'), stub=True)

    def test_warzone_is_a_package_of_its_own_and_never_part_of_everything(self):
        self.assertEqual(pack.ORDER[-1], 'wz'); self.assertNotIn('wz', pack.scope_packages('all')); self.assertIn('wz', pack.scope_packages('custom', 'wz,sp'))
        self.assertEqual(pack.scope_packages('all'), ('sp', 'boot', 'common', 'mp', 'dmz', 'hq'), 'the whole pack is what it was before Warzone existed')
        self.assertIn('cod26/ww_mp26_cdn.xpak', pack.list_files('mp'))
        for r in (self.root, self.xbox):
            self.assertEqual(pack.available(r)['wz'], ['cod26/wz26_cdn.xpak'])
            pl = pack.plan('custom', ['wz'], 'ultra', root=r, mirror_dir=os.path.join(TMP, 'nomir'))
            self.assertEqual(pl['total']['chunks'], 4); self.assertEqual(pack.plan('custom', ['common', 'wz'], 'ultra', root=r, mirror_dir=os.path.join(TMP, 'nomir'))['by_pkg']['wz']['chunks'], 3, 'a piece Warzone shares is counted once, under common')
            self.assertEqual(pack.plan('all', None, 'ultra', root=r, mirror_dir=os.path.join(TMP, 'nomir'))['total']['chunks'], 6)

    def test_an_empty_stub_is_not_installed_content(self):
        r = os.path.join(TMP, 'g_empty'); game(r, stub=True); os.remove(os.path.join(r, 'cod26', 'wz26_cdn_stub.xpak')); open(os.path.join(r, 'cod26', 'wz26_cdn_stub.xpak'), 'wb').close()
        self.assertEqual(pack.available(r)['wz'], []); self.assertIn('wz', pack.plan('custom', ['wz'], 'ultra', root=r, mirror_dir=os.path.join(TMP, 'nomir'))['missing'])
        self.assertFalse(cdnxpak.has_records(os.path.join(r, 'cod26', 'fra_wz26_cdn_stub.xpak'))); self.assertTrue(cdnxpak.has_records(os.path.join(r, 'cod26', 'mp26_cdn_stub.xpak')))

    def test_list_kinds_from_the_names_people_posted(self):
        kinds = {cdnxpak.stem(p): pack.list_kind(p) for p in cdnxpak.find_all(self.xbox)}
        self.assertEqual(kinds, {'sp26': 'known', 'boot': 'known', 'common26': 'known', 'mp26': 'known', 'ww_mp26': 'known', 'wz26': 'known', 'wz26_tr': 'side', 'deu_wz26': 'language', 'fra_wz26': 'language'})
        for n in ('jp_mp26', 'jpf_common26', 'kof_wz26', 'sna_common26'): self.assertEqual(pack.list_kind(f'cod26/{n}_cdn_stub.xpak'), 'language', n)
        for n in ('ww_common26', 'ww_sp26', 'codhq', 'dmz26'): self.assertEqual(pack.list_kind(f'cod26/{n}_cdn.xpak'), 'known', n)
        self.assertEqual(pack.list_kind('cod26/zz99_cdn.xpak'), 'unknown'); self.assertEqual(pack.package_of('cod26/wz26_cdn_stub.xpak'), 'wz'); self.assertIsNone(pack.package_of('cod26/wz26_tr_cdn.xpak'))

    def test_lists_report_and_text_name_every_list_with_its_size(self):
        rows = {r['file']: r for r in played.lists_report(self.root)}
        self.assertEqual(len(rows), 9); self.assertEqual((rows['cod26/wz26_cdn.xpak']['records'], rows['cod26/wz26_cdn.xpak']['kind'], rows['cod26/wz26_cdn.xpak']['package']), (4, 'known', 'wz'))
        self.assertTrue(rows['cod26/fra_wz26_cdn.xpak']['empty']); self.assertAlmostEqual(rows['cod26/wz26_cdn.xpak']['standard_gib'] * 2**30, sum(W(i) for i in (0x201, 0x501, 0x503)), delta=0.01 * 2**30)
        t = played.lists_text(played.lists_report(self.root)); self.assertIn('cod26/wz26_tr_cdn.xpak', t); self.assertIn('(empty)', t); self.assertNotIn(TMP, t, 'names relative to the game folder only')

    def test_doctor_names_warzone_and_the_other_lists(self):
        rows = {r['name']: r for r in doctor.check_list_names(cdnxpak.find_all(self.xbox))}
        self.assertIn('Download what I played', rows['Warzone']['detail']); self.assertEqual(rows['Warzone']['level'], 'info')
        d = rows['Other chunk lists']['detail']; self.assertIn('wz26_tr', d); self.assertIn('1 lists of other game languages', d); self.assertIn('1 empty (not installed): fra_wz26', d)
        self.assertEqual(doctor.check_list_names(cdnxpak.find_all(os.path.join(TMP, 'nothing-here'))), [])


class FingerprintTests(unittest.TestCase):
    def test_new_lists_of_this_version_are_not_a_game_update(self):
        r = game(os.path.join(TMP, 'g_fp')); os.remove(os.path.join(r, 'cod26', 'ww_mp26_cdn.xpak')); os.remove(os.path.join(r, 'cod26', 'wz26_cdn.xpak'))
        old = pack.fingerprint(r); loaded = pack.scope_mask('all')                     # what 0.4.13 stored for a whole-pack copy
        make_list(os.path.join(r, 'cod26', 'ww_mp26_cdn.xpak'), [(0x302, W(0x302), MiB, 1)]); make_list(os.path.join(r, 'cod26', 'wz26_cdn.xpak'), [(0x501, W(0x501), MiB, 1)])
        self.assertFalse(pack.lists_differ(old, r, loaded), 'ww_mp26 joining Multiplayer and a Warzone list nobody chose are not a game update')
        self.assertTrue(pack.lists_differ(old, r, loaded | pack.bit('wz')), 'once Warzone is chosen, its list appearing is new content')
        make_list(os.path.join(r, 'sp26', 'sp26_cdn.xpak'), [(0x101, W(0x101), MiB, 1)]); os.utime(os.path.join(r, 'sp26', 'sp26_cdn.xpak'), (1, 1))
        self.assertTrue(pack.lists_differ(old, r, loaded), 'a changed list still is'); self.assertTrue(pack.lists_differ(None, r, loaded))


class RequestedFileTests(unittest.TestCase):
    def test_read_and_count_what_the_copy_lacked(self):
        d = tempfile.mkdtemp(dir=TMP); mir = os.path.join(d, 'mirror'); f = os.path.join(d, 'requested.txt')
        open(f, 'w', encoding='utf-8').write('\n'.join([f'{chunk(0x501)} {MiB} wz26', f'{chunk(0x501)} {MiB} wz26', f'{chunk(0x502)} {6 * MiB} wz26', f'{chunk(0x9f0)} - -',
                                                        f'{sidep(0x601)} 40960 wz26_tr', 'junk line', f'{chunk(0x101)} {MiB} sp26', '']))
        rs = played.read_requested(f); self.assertEqual(len(rs), 5); self.assertEqual([r['side'] for r in rs].count(True), 1)
        self.assertEqual(next(r for r in rs if r['id'] == 0x9f0)['raw'], None)
        p = played.local_file(dict(id=0x101, wire=W(0x101), flag=1, side=False), mir); os.makedirs(os.path.dirname(p)); open(p, 'wb').write(b'x' * W(0x101))      # already in the copy
        u = played.played_missing('ultra', mir, f); s = played.played_missing('standard', mir, f)
        self.assertEqual((u['n'], s['n']), (4, 3), 'stored pieces and pieces above the level are left out'); self.assertEqual(u['by_list'], {'wz26': 2, 'in no list': 1, 'wz26_tr': 1})
        self.assertEqual(played.played_missing('ultra', mir, os.path.join(d, 'none.txt'))['n'], 0)

    def test_home_offers_it_only_when_there_is_something(self):
        pl = dict(total=dict(chunks=10, pending=0, stored=10, gib=1.0, pending_gib=0.0), fits=True, free_gib=100)
        v = home.download_view(pl, played=dict(n=12, gib=0.1)); self.assertIn(('pack_played', 'Download what I played (102 MB)'), v['secondary']); self.assertIn('pack_played', home.ACTIONS)
        self.assertNotIn('pack_played', [a for a, _ in home.download_view(pl, played=dict(n=0, gib=0))['secondary']])
        self.assertEqual(dict(home.download_view(pl)['scope']['options'])['all'], 'Everything but Warzone')


class DownloadWhatIPlayedTests(unittest.TestCase):
    def setUp(self):
        self.root = game(tempfile.mkdtemp(prefix='game_', dir=TMP)); self.dir = tempfile.mkdtemp(prefix='mir_', dir=TMP); self.work = tempfile.mkdtemp(prefix='work_', dir=TMP)
        self.env = dict(os.environ, CCS_GAME_ROOT=self.root, CCS_MIRROR_DIR=self.dir, CCS_WORK=self.work, CCS_ACCEPT_NOTICE='1')
        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), FakeCdn); threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.addCleanup(self.srv.shutdown)
        self.pj = os.path.join(self.dir, 'prog.json')

    def run_played(self, *extra):
        return subprocess.run([sys.executable, os.path.join(TOOLS, 'ccsmirror.py'), 'run', '--played', '--scope', 'sp', '--workers', '2', '--min-free-gib', '0', '--max-rps', '1000', '--retries', '1',
                               '--upstream-ip', '127.0.0.1', '--upstream-port', str(self.srv.server_address[1]), '--progress-json', self.pj, *extra], capture_output=True, text=True, env=self.env, timeout=120)

    def stored(self): return sorted(r[0] for r in sqlite3.connect(os.path.join(self.dir, 'index.sqlite')).execute('select id from chunks where status=1'))

    def test_it_stores_exactly_what_the_game_asked_for_warzone_and_side_files_included(self):
        open(os.path.join(self.work, 'requested.txt'), 'w', encoding='utf-8').write('\n'.join([f'{chunk(0x501)} {MiB} wz26', f'{chunk(0x502)} {6 * MiB} wz26', f'{chunk(0x9f0)} - -', f'{sidep(0x601)} 40960 wz26_tr']) + '\n')
        r = self.run_played('--level', 'standard'); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.stored(), [0x501, 0x9f0], 'the Warzone piece and the unlisted one; the 6 MiB piece is above Standard; nothing of the campaign scope')
        sf = os.path.join(self.dir, 'side', 'tr', FOLDER, f'{0x601:016x}_{W(0x601):08x}_1'); self.assertEqual(os.path.getsize(sf), W(0x601))
        self.assertIn(['x-amz-meta-cod-key', 'k1'], json.load(open(sf + '.h.json')), 'kept with its headers, as the proxy serves them')
        self.assertIn('by list:', r.stdout); p = json.load(open(self.pj)); self.assertEqual((p['state'], p['queued'], p['fail']), ('done', 3, 0))
        FakeCdn.seen.clear(); r = self.run_played('--level', 'standard'); self.assertEqual(r.returncode, 0); self.assertEqual(json.load(open(self.pj))['queued'], 0); self.assertEqual(FakeCdn.seen, [], 'a second press fetches nothing')
        r = self.run_played('--level', 'ultra'); self.assertIn(0x502, self.stored(), 'a higher level picks up the big one')
        self.assertEqual(pack.plan('sp', None, 'ultra', root=self.root, mirror_dir=self.dir)['total']['stored'], 0, 'the campaign pack is untouched')


class ProxyListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = game(os.path.join(TMP, 'g_px')); cls.mir = os.path.join(TMP, 'mir_px'); os.makedirs(cls.mir, exist_ok=True)
        cls.up = ThreadingHTTPServer(('127.0.0.1', 0), FakeCdn); threading.Thread(target=cls.up.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls): cls.up.shutdown()

    def run_proxy(self, *extra):
        port = free_port(); d = tempfile.mkdtemp(dir=TMP); log = os.path.join(d, 'ccsproxy.log')
        p = subprocess.Popen([sys.executable, os.path.join(TOOLS, 'ccsproxy.py'), '--port', str(port), '--upstream-ip', '127.0.0.1', '--upstream-port', str(self.up.server_address[1]), '--log', log, '--origin', self.mir, *extra],
                             stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=dict(os.environ, CCS_GAME_ROOT=self.root, CCS_WORK=d))
        self.addCleanup(p.kill); t0 = time.time()
        while time.time() - t0 < 60:
            if os.path.exists(log) and 'READY' in open(log, encoding='utf-8').read(): return port, log, os.path.join(d, 'requested.txt')
            self.assertIsNone(p.poll(), 'proxy exited early'); time.sleep(0.2)
        self.fail('proxy did not become READY')

    def get(self, port, path):
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=10); c.request('GET', path); r = c.getresponse(); r.read(); return r.status

    def test_offline_misses_are_noted_with_their_list_once(self):
        port, log, req = self.run_proxy('--offline')
        for pth in (chunk(0x501), chunk(0x501), sidep(0x601), chunk(0x9f1), '/pc/other/thing.json'): self.assertEqual(self.get(port, pth), 404)
        lines = open(req, encoding='utf-8').read().splitlines()
        self.assertEqual(lines, [f'{chunk(0x501)} {MiB} wz26', f'{sidep(0x601)} 40960 wz26_tr', f'{chunk(0x9f1)} - -'], 'one line per piece, with its raw size and list; not the non-piece path')
        t = open(log, encoding='utf-8').read(); self.assertIn('list=wz26_tr (side file)', t); self.assertRegex(t, r'raw=1048576 list=wz26\n'); self.assertIn('in 8 lists', t, 'the empty language stub holds no ids')

    def test_online_fetches_are_noted_with_their_list(self):
        port, log, req = self.run_proxy()
        self.assertEqual(self.get(port, chunk(0x503)), 200); self.assertEqual(self.get(port, sidep(0x602)), 200)
        self.assertEqual(open(req, encoding='utf-8').read().splitlines(), [f'{chunk(0x503)} {MiB} wz26', f'{sidep(0x602)} 40960 wz26_tr'])
        t0 = time.time()
        while 'kept in side/' not in open(log, encoding='utf-8').read() and time.time() - t0 < 5: time.sleep(0.1)          # the log line is written after the reply
        self.assertIn('list=wz26_tr kept in side/', open(log, encoding='utf-8').read())


if __name__ == '__main__':
    unittest.main()
