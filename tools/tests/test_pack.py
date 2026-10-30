"""Tests for the texture-pack feature: scope / detail level / plan, mirror run extras (limit, quota, link wait, verify --all, prune), proxy cap-before-mirror.
All against a fake game folder with hand-made *_cdn.xpak lists and a fake CDN on localhost; the real game folder, mirror and hosts file are never touched.
"""
import hashlib, http.client, json, os, shutil, socket, sqlite3, struct, subprocess, sys, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, TOOLS)
from ccslib import pack, config
MiB = 2**20
TMP = tempfile.mkdtemp(prefix='ccspack_')


def tearDownModule(): shutil.rmtree(TMP, ignore_errors=True)


def make_list(path, recs):
    os.makedirs(os.path.dirname(path), exist_ok=True); d = bytearray(0x8000)
    for i, wire, raw, flag in recs: d += struct.pack('<QIII', i, (wire << 1) | flag, 0, raw)
    open(path, 'wb').write(bytes(d))


def W(i): return 100 + (i & 0xff)


def fake_game(root):
    rec = lambda i, raw: (i, W(i), raw, 1)
    make_list(os.path.join(root, 'sp26', 'sp26_cdn.xpak'), [rec(0x101, 1 * MiB), rec(0x102, 4 * MiB), rec(0x103, 5 * MiB), rec(0x104, 8 * MiB), rec(0x105, 9 * MiB), rec(0x106, 20 * MiB)])
    make_list(os.path.join(root, 'sp26', 'boot_cdn.xpak'), [rec(0x107, 64 * 1024)])
    make_list(os.path.join(root, 'cod26', 'common26_cdn.xpak'), [rec(0x103, 5 * MiB), rec(0x201, 2 * MiB), rec(0x202, 6 * MiB)])        # 0x103 is shared with sp26
    make_list(os.path.join(root, 'cod26', 'mp26_cdn.xpak'), [rec(0x301, 3 * MiB), rec(0x302, 12 * MiB)])                                # no dmz26 / codhq lists on this "install"
    return root


class FakeCdn(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *a): pass
    def do_GET(self):
        wire = int(self.path.rsplit('_', 2)[1], 16); body = bytes([wire & 0xff]) * wire
        self.send_response(200); self.send_header('Content-Length', str(wire)); self.send_header('ETag', f'"{hashlib.md5(body).hexdigest()}"'); self.end_headers(); self.wfile.write(body)
    do_HEAD = do_GET


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


class PackModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.root = fake_game(os.path.join(TMP, 'game_model')); cls.mir = os.path.join(TMP, 'mir_model')

    def test_scope_and_level_helpers(self):
        self.assertEqual(pack.scope_packages('sp'), ('sp', 'boot')); self.assertEqual(pack.scope_packages('all'), pack.ORDER)
        self.assertEqual(pack.scope_packages('custom', 'mp,common,bogus'), ('common', 'mp')); self.assertEqual(pack.scope_mask('custom', ['hq']), pack.bit('hq'))
        self.assertEqual([pack.level_mib(x) for x in ('standard', 'high', 'ultra')], [4.0, 8.0, 4096.0]); self.assertEqual(pack.level_mib('16'), 16.0); self.assertEqual(pack.level_mib('nonsense'), 4096.0)
        self.assertEqual(pack.level_of_mib(8), 'high'); self.assertIsNone(pack.level_of_mib(6))

    def test_plan_sp_and_all_numbers(self):
        sp = pack.plan('sp', None, 'ultra', root=self.root, mirror_dir=self.mir)
        self.assertEqual({k: v['chunks'] for k, v in sp['levels'].items()}, dict(standard=3, high=5, ultra=7)); self.assertEqual(sp['missing'], [])
        al = pack.plan('all', None, 'standard', root=self.root, mirror_dir=self.mir, line_mbps=10)
        self.assertEqual({k: v['chunks'] for k, v in al['levels'].items()}, dict(standard=5, high=8, ultra=11))
        self.assertEqual(al['total']['chunks'], 5); self.assertEqual(al['missing'], ['dmz', 'hq'])                                      # lists absent on this install are reported, not invented
        self.assertEqual({k: v['chunks'] for k, v in pack.plan('all', None, 'ultra', root=self.root, mirror_dir=self.mir)['by_pkg'].items()}, dict(sp=6, boot=1, common=2, mp=2, dmz=0, hq=0))   # 0x103 is attributed to sp, not common
        want = sum(W(i) for i in (0x101, 0x102, 0x107, 0x201, 0x301)) / 2**30
        self.assertAlmostEqual(al['total']['gib'], want, places=9); self.assertAlmostEqual(al['eta_h'], want * 8 * 1024 / 10 / 3600, places=6)
        self.assertEqual(sp['total']['pending'], 7)                                                                                    # no mirror index yet -> nothing stored

    def test_plan_counts_stored_and_custom(self):
        m = os.path.join(TMP, 'mir_stored'); os.makedirs(m); c = sqlite3.connect(os.path.join(m, 'index.sqlite'))
        c.execute('create table chunks(id integer primary key, wire integer, raw integer, flag integer, prio integer, status integer default 0)')
        for i, st in ((0x101, 1), (0x102, 1), (0x103, 2), (0x107, 3)): c.execute('insert into chunks(id,wire,status) values (?,?,?)', (i, W(i), st))
        c.commit(); c.close()
        p = pack.plan('sp', None, 'ultra', root=self.root, mirror_dir=m)
        self.assertEqual((p['total']['stored'], p['total']['pending']), (2, 4))                       # 101,102 stored; 103 failed -> pending again; 107 is a CDN 404 -> neither; 104..106 pending
        cu = pack.plan('custom', ['mp'], 'standard', root=self.root, mirror_dir=m); self.assertEqual((cu['total']['chunks'], cu['packages']), (1, ['mp']))


class MirrorCliBase(unittest.TestCase):
    def setUp(self):
        self.root = fake_game(tempfile.mkdtemp(prefix='game_', dir=TMP)); self.dir = tempfile.mkdtemp(prefix='mir_', dir=TMP); self.work = tempfile.mkdtemp(prefix='work_', dir=TMP)
        self.env = dict(os.environ, CCS_GAME_ROOT=self.root, CCS_MIRROR_DIR=self.dir, CCS_WORK=self.work, CCS_ACCEPT_NOTICE='1')
        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), FakeCdn); threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.addCleanup(self.srv.shutdown)
        self.pj = os.path.join(self.dir, 'prog.json'); self.sf = os.path.join(self.dir, 'STOP')

    def cli(self, *a, wait=True, timeout=120):
        cmd = [sys.executable, os.path.join(TOOLS, 'ccsmirror.py'), *a]
        if wait: return subprocess.run(cmd, capture_output=True, text=True, env=self.env, timeout=timeout)
        return subprocess.Popen(cmd, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def run_args(self, *extra, port=None):
        return ['run', '--workers', '4', '--min-free-gib', '0', '--max-rps', '1000', '--retries', '1', '--upstream-ip', '127.0.0.1', '--upstream-port', str(port or self.srv.server_address[1]),
                '--progress-json', self.pj, '--stop-file', self.sf, *extra]

    def status(self): return json.loads(self.cli('status', '--json').stdout)
    def stored_ids(self): return sorted(r[0] for r in sqlite3.connect(os.path.join(self.dir, 'index.sqlite')).execute('select id from chunks where status=1'))


class MirrorScopeTests(MirrorCliBase):
    def test_scope_level_upgrade_path_and_auto_budget(self):
        r = self.cli(*self.run_args('--scope', 'sp', '--level', 'standard')); self.assertEqual(r.returncode, 0, r.stderr + r.stdout)      # no --budget-gib: automatic
        self.assertEqual(self.stored_ids(), [0x101, 0x102, 0x107]); self.assertEqual(json.load(open(self.pj))['state'], 'done')
        self.assertEqual(self.cli(*self.run_args('--scope', 'all', '--level', 'standard')).returncode, 0)
        self.assertEqual(self.stored_ids(), [0x101, 0x102, 0x107, 0x201, 0x301])                                                         # only the extra packages' <= 4 MiB chunks were added
        self.assertEqual(json.load(open(self.pj))['queued'], 2)
        self.assertEqual(self.cli(*self.run_args('--scope', 'all', '--level', 'ultra')).returncode, 0)                                  # upgrade: only the missing big chunks are fetched
        self.assertEqual(len(self.stored_ids()), 11); self.assertEqual(json.load(open(self.pj))['queued'], 6)
        st = self.status(); self.assertEqual(st['packages']['common']['chunks'], 3); self.assertEqual(st['packages']['sp']['stored'], 6); self.assertEqual(st['levels']['standard']['stored'], 5)
        self.assertEqual(self.cli('verify', '--all').stdout.strip().splitlines()[-1], 'verified 11 objects, 0 bad')

    def test_custom_scope_and_status_text(self):
        self.assertEqual(self.cli(*self.run_args('--scope', 'custom', '--packages', 'mp', '--level', 'ultra')).returncode, 0)
        self.assertEqual(self.stored_ids(), [0x301, 0x302]); out = self.cli('status').stdout; self.assertIn('package mp', out); self.assertIn('stored <= standard', out)
        self.assertNotEqual(self.cli('init', '--scope', 'custom').returncode, 0)                                                         # custom needs --packages

    def test_plan_cli_json_matches_model(self):
        d = json.loads(self.cli('plan', '--scope', 'all', '--level', 'high', '--json').stdout)
        self.assertEqual((d['level'], d['tier_mib'], d['total']['chunks'], d['missing']), ('high', 8.0, 8, ['dmz', 'hq']))

    def test_v1_index_is_migrated_and_kept(self):
        c = sqlite3.connect(os.path.join(self.dir, 'index.sqlite'))
        c.execute('create table chunks(id integer primary key, wire integer, raw integer, flag integer, prio integer, status integer default 0, etag text, cod_key text, ts real)')
        c.execute('insert into chunks(id,wire,raw,flag,prio,status,etag) values (?,?,?,?,?,1,?)', (0x101, W(0x101), 1 * MiB, 1, 1, 'keepme')); c.commit(); c.close()
        self.assertEqual(self.cli('init', '--scope', 'sp').returncode, 0)
        c = sqlite3.connect(os.path.join(self.dir, 'index.sqlite'))
        self.assertEqual(c.execute('select status, etag, pkgs from chunks where id=?', (0x101,)).fetchone(), (1, 'keepme', pack.bit('sp')))          # status kept, package bit added
        self.assertEqual(c.execute('select count(*) from chunks').fetchone()[0], 7); self.assertEqual(c.execute("select value from meta where key='scope'").fetchone()[0], 'sp')

    def test_missing_lists_reported_by_init(self):
        r = self.cli('init', '--scope', 'all'); self.assertIn('missing for: dmz, hq', r.stdout)


class MirrorUpdateTests(MirrorCliBase):
    def test_a_game_update_adds_new_chunks_to_the_next_download(self):
        self.assertEqual(self.cli(*self.run_args('--scope', 'sp', '--level', 'ultra')).returncode, 0); self.assertEqual(len(self.stored_ids()), 7)
        self.assertIs(pack.lists_changed(self.dir, self.root), False)
        make_list(os.path.join(self.root, 'sp26', 'sp26_cdn.xpak'), [(i, W(i), 1 * MiB, 1) for i in (0x101, 0x102, 0x103, 0x104, 0x105, 0x106, 0x108)])      # the update added 0x108
        self.assertIs(pack.lists_changed(self.dir, self.root), True)
        r = self.cli(*self.run_args('--scope', 'sp', '--level', 'ultra')); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.stored_ids()), 8); self.assertIn(0x108, self.stored_ids()); self.assertIn('chunk lists changed', r.stdout)
        self.assertIs(pack.lists_changed(self.dir, self.root), False)
        self.assertEqual(self.cli(*self.run_args('--scope', 'sp', '--level', 'ultra')).returncode, 0); self.assertEqual(json.load(open(self.pj))['queued'], 0)

    def test_lists_changed_is_none_without_an_index_or_a_record(self):
        self.assertIsNone(pack.lists_changed(os.path.join(TMP, 'no-mirror-here'), self.root))

    def test_chunks_outside_the_lists_that_the_game_asked_for_are_downloaded_too(self):
        self.assertEqual(self.cli(*self.run_args('--scope', 'sp', '--level', 'ultra')).returncode, 0)
        path = f'/pc/iw9_3/23/{0x9f0 & 0xff:02x}/{0x9f0:016x}_{W(0x9f0):08x}_1'
        open(os.path.join(self.work, 'unlisted.txt'), 'w', encoding='utf-8').write(path + '\nnot a chunk path\n' + path + '\n')
        out = self.cli('fetch-requested').stdout; self.assertIn('1 new chunk(s) queued', out)
        self.assertIn('nothing new', self.cli('fetch-requested').stdout)
        self.assertEqual(self.cli(*self.run_args('--scope', 'sp', '--level', 'ultra')).returncode, 0)
        self.assertIn(0x9f0, self.stored_ids()); self.assertEqual(os.path.getsize(os.path.join(self.dir, 'objects', f'{0x9f0 & 0xff:02x}', f'{0x9f0:016x}_{W(0x9f0):08x}_1')), W(0x9f0))
        self.assertEqual(pack.plan('sp', None, 'ultra', root=self.root, mirror_dir=self.dir)['total']['chunks'], 7, 'the plan still counts only what the lists name')

    def test_a_download_picks_up_what_the_proxy_noted_without_a_separate_step(self):
        path = f'/pc/iw9_3/23/{0x9f1 & 0xff:02x}/{0x9f1:016x}_{W(0x9f1):08x}_1'
        open(os.path.join(self.work, 'unlisted.txt'), 'w', encoding='utf-8').write(path + '\n')
        self.assertEqual(self.cli(*self.run_args('--scope', 'sp', '--level', 'standard')).returncode, 0); self.assertIn(0x9f1, self.stored_ids())


class MirrorMaintenanceTests(MirrorCliBase):
    def fill(self): self.assertEqual(self.cli(*self.run_args('--scope', 'all', '--level', 'ultra')).returncode, 0)

    def test_prune_dry_run_then_delete_and_cap_skips_refetch(self):
        self.fill(); d = json.loads(self.cli('prune', '--above-tier', '4', '--json').stdout)
        self.assertEqual((d['chunks'], d['dry_run'], d['deleted']), (6, True, 0)); self.assertEqual(len(self.stored_ids()), 11)         # dry run changes nothing
        d = json.loads(self.cli('prune', '--above-tier', '4', '--yes', '--json').stdout); self.assertEqual((d['deleted'], d['dry_run']), (6, False))
        self.assertEqual(self.stored_ids(), [0x101, 0x102, 0x107, 0x201, 0x301])
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'objects', '03', f'{0x103:016x}_{W(0x103):08x}_1')))
        self.assertEqual(self.cli(*self.run_args('--scope', 'all', '--level', 'standard')).returncode, 0); self.assertEqual(json.load(open(self.pj))['queued'], 0)   # the cap keeps them out

    def test_verify_all_fix_and_redownload(self):
        self.fill(); victim = os.path.join(self.dir, 'objects', '02', f'{0x102:016x}_{W(0x102):08x}_1'); open(victim, 'r+b').write(b'\x00\x01')
        r = self.cli('verify', '--all', '--progress-json', self.pj); self.assertIn('verified 11 objects, 1 bad', r.stdout); self.assertEqual(json.load(open(self.pj))['bad'], 1)
        self.assertEqual(len(self.stored_ids()), 11)                                                                                       # without --fix nothing is changed
        r = self.cli('verify', '--all', '--fix'); self.assertIn('reset 1 bad', r.stdout); self.assertEqual(len(self.stored_ids()), 10)
        self.fill(); self.assertEqual(len(self.stored_ids()), 11); self.assertIn('0 bad', self.cli('verify', '--all').stdout)

    def test_limit_mbps_slows_the_run(self):
        make_list(os.path.join(self.root, 'sp26', 'sp26_cdn.xpak'), [(0x400 + k, 4000 + k, 1 * MiB, 1) for k in range(25)])                  # 25 objects of ~4 KB = ~100 KB
        make_list(os.path.join(self.root, 'sp26', 'boot_cdn.xpak'), [(0x7f0, 100, 1000, 1)])
        t0 = time.time(); self.assertEqual(self.cli(*self.run_args('--scope', 'sp')).returncode, 0); fast = time.time() - t0
        shutil.rmtree(self.dir); os.makedirs(self.dir); t0 = time.time()
        r = self.cli(*self.run_args('--scope', 'sp', '--limit-mbps', '0.4')); slow = time.time() - t0                                       # 0.4 Mbit/s = 50 KB/s -> >= ~2 s for 100 KB
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertGreaterEqual(slow, fast + 1.2, (fast, slow)); self.assertEqual(len(self.stored_ids()), 26)
        self.assertEqual(json.load(open(self.pj))['limit_mbps'], 0.4)

    def test_daily_quota_waits_and_pauses_cleanly(self):
        make_list(os.path.join(self.root, 'sp26', 'sp26_cdn.xpak'), [(0x400 + k, 1000 + k, 1 * MiB, 1) for k in range(40)])                  # 40 objects of ~1 KB = ~40 KB
        make_list(os.path.join(self.root, 'sp26', 'boot_cdn.xpak'), [(0x7f0, 100, 1000, 1)])
        pr = self.cli(*self.run_args('--scope', 'sp', '--daily-gib', str(15000 / 2**30), '--workers', '2'), wait=False); st = None; t0 = time.time()
        while time.time() - t0 < 40:
            time.sleep(0.4)
            try: st = json.load(open(self.pj))
            except Exception: continue
            if st['state'] == 'quota-wait': break
        self.assertEqual(st['state'], 'quota-wait'); self.assertIsNotNone(st['resume_at']); self.assertGreater(st['resume_at'], time.time())
        t0 = time.time(); got = 0
        while time.time() - t0 < 10 and got < 10: time.sleep(0.3); got = len(self.stored_ids())
        self.assertTrue(10 <= got < 41, got)
        open(self.sf, 'w').write('stop'); pr.wait(timeout=60); self.assertEqual(json.load(open(self.pj))['state'], 'paused')
        used = sqlite3.connect(os.path.join(self.dir, 'index.sqlite')).execute("select value from meta where key='quota_used'").fetchone()
        self.assertIsNotNone(used); self.assertGreater(int(used[0]), 10000)                                                                # today's usage survives a restart

    def test_dead_link_waits_and_keeps_chunks_pending(self):
        dead = free_port(); r = self.cli(*self.run_args('--scope', 'sp', '--link-wait-s', '2', '--retries', '0', port=dead), timeout=90)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn('LINK DOWN', r.stdout); self.assertEqual(json.load(open(self.pj))['state'], 'offline')
        st = self.status(); self.assertEqual(st['stored'], 0); self.assertEqual(sum(x['chunks'] for x in st['rows'] if x['status'] == 'failed'), 0)       # nothing was recorded as failed


class BulkNoticeTests(MirrorCliBase):
    def test_run_refuses_until_the_notice_is_accepted_once(self):
        env = {k: v for k, v in self.env.items() if k != 'CCS_ACCEPT_NOTICE'}; cmd = [sys.executable, os.path.join(TOOLS, 'ccsmirror.py'), *self.run_args('--scope', 'sp')]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60); self.assertEqual(r.returncode, 3); self.assertIn('BULK DOWNLOAD', r.stdout); self.assertFalse(os.path.exists(os.path.join(self.dir, 'index.sqlite')))      # refused before touching the mirror
        r = subprocess.run(cmd + ['--accept-notice'], capture_output=True, text=True, env=env, timeout=120); self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertEqual(len(self.stored_ids()), 7)
        self.assertTrue(os.path.exists(os.path.join(self.work, 'bulk_ack.json')))
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120); self.assertEqual(r.returncode, 0)                    # accepted once, not asked again
        self.assertNotEqual(subprocess.run([sys.executable, os.path.join(TOOLS, 'ccsmirror.py'), 'plan', '--scope', 'sp'], capture_output=True, text=True, env=env, timeout=60).returncode, 3)   # plan never needs it


class PoliteClientTests(MirrorCliBase):
    def test_user_agent_is_sent_and_429_makes_everyone_back_off(self):
        seen = []; state = dict(n=0)
        class Flaky(FakeCdn):
            def do_GET(self):
                seen.append(self.headers.get('User-Agent')); state['n'] += 1
                if state['n'] <= 2:
                    self.send_response(429); self.send_header('Retry-After', '1'); self.send_header('Content-Length', '0'); self.end_headers(); return
                FakeCdn.do_GET(self)
        srv = ThreadingHTTPServer(('127.0.0.1', 0), Flaky); threading.Thread(target=srv.serve_forever, daemon=True).start(); self.addCleanup(srv.shutdown)
        t0 = time.time(); r = self.cli(*self.run_args('--scope', 'sp', '--workers', '3', port=srv.server_address[1])); el = time.time() - t0
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertEqual(len(self.stored_ids()), 7)                       # nothing was marked failed because of the 429s
        self.assertIn('slow down', r.stdout); self.assertGreaterEqual(json.load(open(self.pj))['throttled'], 1); self.assertGreaterEqual(el, 1.0)
        self.assertTrue(seen and all(u and u.startswith('mw4-texture-streaming-toolkit/') for u in seen), seen[:3])

    def test_help_carries_the_notice_and_version(self):
        out = self.cli('--help').stdout; self.assertIn('Research / proof of concept', out); self.assertIn('--version', out)
        self.assertIn('mw4-texture-streaming-toolkit/', self.cli('--version').stdout)


class UpstreamUnitTests(unittest.TestCase):
    def setUp(self):
        from ccslib import upstream
        old = upstream._cache_path; upstream._cache_path = lambda: os.path.join(TMP, 'edge_cache_unit.json'); self.addCleanup(setattr, upstream, '_cache_path', old)      # never the real tools/work

    def test_retry_after_parsing_and_backoff_bounds(self):
        from ccslib import upstream
        self.assertEqual(upstream.retry_after({'Retry-After': '7'}), 7.0); self.assertIsNone(upstream.retry_after({})); self.assertIsNone(upstream.retry_after({'Retry-After': 'soon'}))
        self.assertTrue(0 <= upstream.retry_after({'Retry-After': 'Wed, 21 Oct 2015 07:28:00 GMT'}) <= 0.01)                             # a date in the past -> 0
        for k in range(8): d = upstream.backoff(k, base=1.0, cap=10.0); self.assertTrue(0.7 <= d <= 12.6, (k, d))

    def test_candidates_skip_loopback_and_end_with_the_fallback(self):
        from ccslib import upstream
        import socket as sk, subprocess as sp
        og, orun = sk.getaddrinfo, sp.run
        odns = upstream.dns_a; seen = []
        sk.getaddrinfo = lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 80))]                                                             # hosts override active: the name resolves to us
        upstream.dns_a = lambda name, server, **k: (seen.append(server), ['203.0.113.9'])[1]                                             # a public resolver answers
        try:
            if os.path.exists(upstream._cache_path()): os.remove(upstream._cache_path())
            c = upstream.candidates()
        finally: sk.getaddrinfo, sp.run, upstream.dns_a = og, orun, odns
        self.assertNotIn('127.0.0.1', c); self.assertEqual(c[0], '203.0.113.9'); self.assertEqual(c[-1], upstream.FALLBACK_IPS[-1]); self.assertEqual(seen, list(upstream.PUBLIC_RESOLVERS))                                # every public resolver is asked: they map to different regions

    def test_system_answer_is_remembered_and_beats_public_dns_once_the_override_hides_it(self):
        from ccslib import upstream
        import socket as sk
        og, odns = sk.getaddrinfo, upstream.dns_a
        if os.path.exists(upstream._cache_path()): os.remove(upstream._cache_path())
        sk.getaddrinfo = lambda *a, **k: [(2, 1, 6, '', ('198.51.100.20', 80))]                                                          # override off: the ISP resolver gives the nearest edge
        upstream.dns_a = lambda *a, **k: ['203.0.113.9']
        try:
            first = upstream.candidates_info()
            sk.getaddrinfo = lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 80))]                                                          # override on
            later = upstream.candidates_info()
        finally: sk.getaddrinfo, upstream.dns_a = og, odns
        self.assertEqual(first[0], ('198.51.100.20', 'system')); self.assertEqual(later[0], ('198.51.100.20', 'cache')); self.assertEqual(later[1], ('203.0.113.9', 'dns:1.1.1.1'))
        self.assertEqual(later[-1], (upstream.FALLBACK_IPS[-1], 'fallback')); self.assertTrue(upstream.is_fallback(upstream.FALLBACK_IPS[0]))

    def test_stale_cache_is_ignored(self):
        from ccslib import upstream
        upstream.remember(['198.51.100.20']); self.assertEqual(upstream._cached(), ['198.51.100.20'])
        with open(upstream._cache_path()) as f: d = json.load(f)
        d['time'] -= upstream.CACHE_MAX_AGE_S + 5
        with open(upstream._cache_path(), 'w') as f: json.dump(d, f)
        self.assertEqual(upstream._cached(), [])

    def test_dns_a_parses_cname_chain_ipv6_noise_and_compressed_names(self):
        from ccslib import upstream
        def name(n): return b''.join(bytes([len(p)]) + p.encode() for p in n.split('.')) + b'\x00'
        q = name('cod-assets.cdn.callofduty.com') + struct.pack('>HH', 1, 1)
        rr = lambda typ, data, nm=b'\xc0\x0c': nm + struct.pack('>HHIH', typ, 1, 60, len(data)) + data                                  # name = pointer to the question
        msg = struct.pack('>HHHHHH', 7, 0x8180, 1, 4, 0, 0) + q + rr(5, name('a1991.dscv.akamai.net')) + rr(28, bytes(16)) + rr(1, bytes([104, 120, 129, 56])) + rr(1, bytes([104, 120, 129, 42]))
        self.assertEqual(upstream.parse_dns_a(msg), ['104.120.129.56', '104.120.129.42'])                                                # AAAA ignored, order kept
        self.assertEqual(upstream.parse_dns_a(struct.pack('>HHHHHH', 7, 0x8183, 1, 0, 0, 0) + q), [])                                   # NXDOMAIN
        self.assertEqual(upstream.parse_dns_a(b'\x00' * 12), [])

    def test_dns_a_round_trip_against_a_local_udp_server(self):
        from ccslib import upstream
        srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); srv.bind(('127.0.0.1', 0)); port = srv.getsockname()[1]
        def serve():
            req, addr = srv.recvfrom(512); i = 12
            while req[i]: i += 1 + req[i]
            q = req[12:i + 5]; ans = b'\xc0\x0c' + struct.pack('>HHIH', 1, 1, 60, 4) + bytes([192, 0, 2, 55])
            srv.sendto(req[:2] + struct.pack('>HHHHH', 0x8180, 1, 1, 0, 0) + q + ans, addr)
        threading.Thread(target=serve, daemon=True).start(); self.addCleanup(srv.close)
        self.assertEqual(upstream.dns_a('cod-assets.cdn.callofduty.com', '127.0.0.1', timeout=3, port=port), ['192.0.2.55'])
        self.assertEqual(upstream.dns_a('x.example', '127.0.0.1', timeout=0.3, port=free_port()), [])                                   # nobody answers -> [] instead of an exception

    def test_measure_edge_accepts_only_a_correct_answer_and_pick_prefers_the_fastest(self):
        from ccslib import upstream
        class Slow(FakeCdn):
            def do_GET(self): time.sleep(0.4); FakeCdn.do_GET(self)
        class Deny(FakeCdn):
            def do_GET(self): self.send_response(403); self.send_header('Content-Length', '0'); self.end_headers()
        servers = {}
        for k, h in (('fast', FakeCdn), ('slow', Slow), ('deny', Deny)):
            servers[k] = ThreadingHTTPServer(('127.0.0.1', 0), h); threading.Thread(target=servers[k].serve_forever, daemon=True).start(); self.addCleanup(servers[k].shutdown)
        tests = [(f'/pc/iw9_3/23/01/0000000000000101_{W(0x101):08x}_1', W(0x101))]
        r = {k: upstream.measure_edge('127.0.0.1', s.server_address[1], tests) for k, s in servers.items()}
        self.assertTrue(r['fast']['ok'] and r['slow']['ok']); self.assertFalse(r['deny']['ok']); self.assertIn('403', r['deny']['error']); self.assertGreater(r['slow']['secs'], r['fast']['secs'])
        self.assertFalse(upstream.measure_edge('127.0.0.1', free_port(), tests)['ok'])                                                  # refused connection
        self.assertFalse(upstream.measure_edge('127.0.0.1', servers['fast'].server_address[1], [(tests[0][0], W(0x101) + 1)])['ok'])   # wrong length is not a good edge
        om = upstream.measure_edge
        upstream.measure_edge = lambda ip, port, t, **k: dict(ip=ip, ok=ip != '10.0.0.3', secs=1.0, mbps={'10.0.0.1': 5.0, '10.0.0.2': 80.0, '10.0.0.3': 999.0, upstream.FALLBACK_IPS[0]: 80.0}[ip], status=200, error=None)
        try:
            self.assertEqual(upstream.pick(['10.0.0.1', '10.0.0.2', '10.0.0.3'], 80, tests)[0], '10.0.0.2')                              # fastest that is also valid
            self.assertEqual(upstream.pick([upstream.FALLBACK_IPS[0], '10.0.0.2'], 80, tests)[0], '10.0.0.2')                            # tie: the built-in address loses
            self.assertIsNone(upstream.pick(['10.0.0.3'], 80, tests)[0])
        finally: upstream.measure_edge = om


class EdgeSelectionCliTests(MirrorCliBase):
    def test_run_measures_candidates_picks_a_working_one_and_logs_it(self):
        self.env['CCS_EDGE_CANDIDATES'] = f'127.0.0.2,127.0.0.1'                                                                          # 127.0.0.2: nothing listens there -> rejected
        args = [a for a in self.run_args('--scope', 'sp') if a not in ('--upstream-ip', '127.0.0.1')]
        r = self.cli(*args); self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertEqual(len(self.stored_ids()), 7)
        log = open(os.path.join(self.work, 'ccsmirror.log'), encoding='utf-8').read()
        self.assertIn('edge test 127.0.0.2 (env): rejected', log); self.assertRegex(log, r'edge test 127\.0\.0\.1 \(env\): [\d.]+ Mbit/s'); self.assertIn('run: upstream=127.0.0.1 ', log)
        p = json.load(open(self.pj)); self.assertEqual(p['edge'], '127.0.0.1'); self.assertEqual(p['edge_note'], ''); self.assertIn('mibps_now', p)

    def test_run_says_so_when_only_the_fallback_edge_is_left(self):
        self.env['CCS_EDGE_CANDIDATES'] = '127.0.0.2'
        import ccslib.upstream as up; self.assertFalse(up.is_fallback('127.0.0.2'))
        args = [a for a in self.run_args('--scope', 'sp', '--retries', '0', '--link-wait-s', '2') if a not in ('--upstream-ip', '127.0.0.1')]
        r = self.cli(*args, timeout=90); log = open(os.path.join(self.work, 'ccsmirror.log'), encoding='utf-8').read()
        self.assertIn('no edge address passed the test', json.load(open(self.pj)).get('edge_note', '')); self.assertIn('rejected', log)

    def test_stall_watchdog_decision(self):
        sys.path.insert(0, TOOLS); import ccsmirror
        s = ccsmirror.stalled; base = dict(elapsed=200, since_check=400, line_mbps=100, limit_mbps=0, rate_mbps=5.0, throttled=False, state='running')
        self.assertTrue(s(**base))                                                                                                        # 5 Mbit/s on a 100 Mbit/s line
        for k, v in (('rate_mbps', 25.0), ('elapsed', 60), ('since_check', 30), ('line_mbps', 0), ('throttled', True), ('state', 'quota-wait'), ('limit_mbps', 10.0)):
            self.assertFalse(s(**dict(base, **{k: v})), k)                                                                               # healthy, too early, just checked, unknown line, 429 pause, quota, user cap


class QuotaUnitTests(unittest.TestCase):
    def test_quota_rolls_over_at_midnight_and_persists(self):
        sys.path.insert(0, TOOLS); import ccsmirror
        now = [time.mktime((2026, 10, 20, 23, 59, 0, 0, 0, -1))]; q = ccsmirror.Quota(1000, None, clock=lambda: now[0])
        q.add(600); self.assertFalse(q.exceeded()); q.add(500); self.assertTrue(q.exceeded())
        self.assertGreater(q.resume_at(), now[0]); self.assertLess(q.resume_at() - now[0], 70)                                              # resumes 00:00:05
        self.assertFalse(q.roll()); now[0] += 120; self.assertTrue(q.roll()); self.assertFalse(q.exceeded()); self.assertEqual(q.used, 0)
        c = sqlite3.connect(':memory:'); ccsmirror.ensure_schema(c); q.add(300); q.save(c)
        q2 = ccsmirror.Quota(1000, c, clock=lambda: now[0]); self.assertEqual(q2.used, 300)
        q3 = ccsmirror.Quota(1000, c, clock=lambda: now[0] + 86400); self.assertEqual(q3.used, 0)                                          # another day -> stored usage ignored


class ProxyCapTests(unittest.TestCase):
    def test_cap_applies_before_the_mirror_and_repeat_skips_are_counted(self):
        root = fake_game(os.path.join(TMP, 'game_proxy')); mir = os.path.join(TMP, 'mir_proxy'); os.makedirs(mir); c = sqlite3.connect(os.path.join(mir, 'index.sqlite'))
        c.execute('create table chunks(id integer primary key, wire integer, raw integer, flag integer, prio integer, status integer default 0, etag text, cod_key text, ts real)')
        for i in (0x101, 0x104):                       # 1 MiB (under the cap) and 8 MiB (over a 4 MiB cap) objects, both in the mirror
            o = os.path.join(mir, 'objects', f'{i & 0xff:02x}'); os.makedirs(o); open(os.path.join(o, f'{i:016x}_{W(i):08x}_1'), 'wb').write(b'm' * W(i))
            c.execute('insert into chunks(id,wire,raw,flag,prio,status,etag) values (?,?,?,?,?,1,?)', (i, W(i), 0, 1, 0, 'e')); c.commit()
        c.close(); port = free_port(); log = os.path.join(TMP, 'proxycap.log'); env = dict(os.environ, CCS_GAME_ROOT=root, CCS_WORK=os.path.join(TMP, 'pwork'))
        p = subprocess.Popen([sys.executable, os.path.join(TOOLS, 'ccsproxy.py'), '--port', str(port), '--upstream-ip', '127.0.0.1', '--upstream-port', '9', '--log', log, '--origin', mir, '--max-raw-mib', '4', '--offline'],
                             env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT); self.addCleanup(p.kill); t0 = time.time()
        while time.time() - t0 < 60 and not (os.path.exists(log) and 'READY' in open(log, encoding='utf-8').read()): time.sleep(0.2)
        def get(i):
            k = http.client.HTTPConnection('127.0.0.1', port, timeout=10); k.request('GET', f'/pc/iw9_3/23/{i & 0xff:02x}/{i:016x}_{W(i):08x}_1'); r = k.getresponse(); b = r.read(); return r.status, b
        self.assertEqual(get(0x101), (200, b'm' * W(0x101)))
        self.assertEqual(get(0x104)[0], 404); self.assertEqual(get(0x104)[0], 404)                                                          # 8 MiB chunk is in the mirror but above the cap
        k = http.client.HTTPConnection('127.0.0.1', port, timeout=10); k.request('GET', '/__ccs/stats'); d = json.loads(k.getresponse().read())
        self.assertEqual((d['stat']['skip'], d['stat']['mirror']), (2, 1)); self.assertEqual((d['skips']['n'], d['skips']['unique'], d['skips']['repeat']), (2, 1, 1)); self.assertEqual(d['skips']['top'][0], [f'{0x104:016x}', 2])


class ConfigPackTests(unittest.TestCase):
    def cfg(self):
        import copy; return copy.deepcopy(config.DEFAULTS)

    def test_default_pack_section_reproduces_todays_behaviour(self):
        e = config.effective(self.cfg()); self.assertEqual((e['pack']['scope'], e['pack']['level']), ('sp', 'ultra')); self.assertEqual((e['mirror']['tier'], e['proxy']['max_raw_mib']), (4096.0, 4096.0))

    def test_level_drives_both_caps_unless_unlinked(self):
        c = self.cfg(); c['pack']['level'] = 'standard'; e = config.effective(c); self.assertEqual((e['mirror']['tier'], e['proxy']['max_raw_mib']), (4.0, 4.0))
        c['pack']['level'] = 'high'; self.assertEqual(config.effective(c)['proxy']['max_raw_mib'], 8.0)
        c['pack'].update(link_caps=False); c['proxy']['max_raw_mib'] = 16; c['mirror']['tier'] = 32; e = config.effective(c); self.assertEqual((e['proxy']['max_raw_mib'], e['mirror']['tier']), (16, 32))

    def test_builtin_level_profiles_and_snapshot(self):
        c = self.cfg(); c['profile'] = 'Standard HD (1440p class)'; self.assertEqual(config.effective(c)['proxy']['max_raw_mib'], 4.0)
        c['profile'] = 'Ultra (4K class)'; c['pack']['level'] = 'standard'; self.assertEqual(config.effective(c)['proxy']['max_raw_mib'], 4096.0)       # a profile level wins over the saved one
        c['profile'] = 'Slow link - offline mirror'; e = config.effective(c); self.assertTrue(e['proxy']['offline'] and e['proxy']['origin']); self.assertEqual(e['pack']['level'], 'standard')
        snap = config.snapshot_profile(c); self.assertEqual(snap['pack'], dict(level='standard'))                                                                # only the level is part of a saved profile

    def test_mirrorctl_pack_args(self):
        from ccslib import mirrorctl
        c = self.cfg(); c['pack'].update(scope='custom', packages=['mp', 'common'], level='high', limit_mbps=3.5, daily_gib=20, link_wait_s=600)
        a = mirrorctl.run_argv(**mirrorctl.pack_kwargs(c))
        self.assertEqual(a[a.index('--scope') + 1], 'custom'); self.assertEqual(a[a.index('--packages') + 1], 'mp,common'); self.assertEqual(a[a.index('--tier') + 1], '8.0')
        self.assertEqual((a[a.index('--budget-gib') + 1], a[a.index('--limit-mbps') + 1], a[a.index('--daily-gib') + 1], a[a.index('--link-wait-s') + 1], a[a.index('--workers') + 1]), ('0', '3.5', '20', '600', '4'))
        d = mirrorctl.run_argv(**mirrorctl.pack_kwargs(self.cfg())); self.assertNotIn('--limit-mbps', d); self.assertEqual(d[d.index('--workers') + 1], '4')


class ReportSkipTests(unittest.TestCase):
    def test_skip_stats(self):
        from ccslib import report
        seg = dict(lines=['11:00:00 SKIP-TIER GET /pc/iw9_3/23/aa/00000000000000aa_00000400_1 raw=8.0MiB', '11:00:01 SKIP-TIER GET /pc/iw9_3/23/aa/00000000000000aa_00000400_1 raw=8.0MiB',
                          '11:00:01 SKIP-TIER HEAD /pc/iw9_3/23/bb/00000000000000bb_00000400_1 raw=9.0MiB', '11:00:02 SKIP-TIER GET /pc/iw9_3/23/cc/00000000000000cc_00000400_1 raw=12.0MiB'])
        k = report.skip_stats(seg); self.assertEqual((k['requests'], k['unique'], k['repeats'], k['max_repeats']), (3, 2, 1, 2)); self.assertEqual(k['top'][0]['id'], '00000000000000aa')
        self.assertIsNone(report.skip_stats(dict(lines=['11:00:00 GET /x -> 200'])))


if __name__ == '__main__': unittest.main()
