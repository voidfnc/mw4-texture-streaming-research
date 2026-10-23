"""Unit tests for the CCS tooling (hosts manager, process manager, config, proxy stats endpoint, diskguard).

  python -m unittest discover -s tools/tests -v        (from the install root)
Everything runs against temp files/ports; the real hosts file and game folders are never touched.
"""
import json, os, shutil, socket, sqlite3, subprocess, sys, tempfile, threading, time, unittest, zipfile, http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, TOOLS)
TMP = tempfile.mkdtemp(prefix='ccstest_')
os.environ['CCS_WORK'] = os.path.join(TMP, 'work')
os.environ['CCS_HOSTS_PATH'] = os.path.join(TMP, 'hosts')
os.environ['CCS_LANG'] = 'en'                       # the tests read the English text
from ccslib import hosts, procs, config, paths, proxyctl

WIN_HOSTS = ('# Copyright (c) 1993-2009 Microsoft Corp.\r\n#\r\n# localhost name resolution is handled within DNS itself.\r\n'
             '#\t127.0.0.1       localhost\r\n#\t::1             localhost\r\n# Added by Docker Desktop\r\n'
             '192.168.50.100 host.docker.internal\r\n# End of section\r\n')


def setUpModule(): paths.ensure_dirs()
def tearDownModule(): shutil.rmtree(TMP, ignore_errors=True)


def put(text):
    open(paths.hosts_path(), 'wb').write(text.encode()); return text


class HostsTests(unittest.TestCase):
    def test_apply_remove_roundtrip_is_byte_identical(self):
        orig = put(WIN_HOSTS)
        r = hosts.apply(flush=False); self.assertTrue(r['changed']); self.assertTrue(os.path.exists(r['backup']))
        now = open(paths.hosts_path(), 'rb').read().decode()
        self.assertIn(hosts.BEGIN, now); self.assertIn(f'::1 {paths.HOST}', now); self.assertIn(f'127.0.0.1 {paths.HOST}', now)
        self.assertTrue(now.startswith(orig[:-2]))                       # everything before our block is untouched
        self.assertEqual(hosts.status()['state'], 'OK')
        self.assertFalse(hosts.apply(flush=False)['changed'])             # idempotent
        hosts.remove(flush=False)
        self.assertEqual(open(paths.hosts_path(), 'rb').read().decode(), orig)
        self.assertEqual(hosts.status()['state'], 'ABSENT')

    def test_crlf_preserved_and_no_trailing_newline_ok(self):
        put('127.0.0.1 a.example\r\n10.0.0.1 b.example')                  # no final newline
        hosts.apply(flush=False); t = open(paths.hosts_path(), 'rb').read()
        self.assertNotIn(b'\n', t.replace(b'\r\n', b''))                  # no bare LF introduced
        self.assertTrue(t.endswith(b'\r\n'))
        hosts.remove(flush=False)
        self.assertEqual(open(paths.hosts_path(), 'rb').read().decode().split(), ['127.0.0.1', 'a.example', '10.0.0.1', 'b.example'])

    def test_adopts_handmade_loopback_lines(self):
        put(WIN_HOSTS + f'::1 {paths.HOST}\r\n127.0.0.1 {paths.HOST}\r\n')
        self.assertEqual(hosts.status()['state'], 'FOREIGN')
        hosts.apply(flush=False); st = hosts.status()
        self.assertEqual(st['state'], 'OK'); self.assertEqual(st['foreign'], [])   # moved into the block, not duplicated
        t = open(paths.hosts_path()).read(); self.assertEqual(t.count(f'127.0.0.1 {paths.HOST}'), 1)
        hosts.remove(flush=False); self.assertEqual(hosts.status()['state'], 'ABSENT')

    def test_read_only_hosts_gives_a_clear_error_and_is_untouched(self):
        import stat
        orig = put(WIN_HOSTS); hp = paths.hosts_path()
        os.chmod(hp, stat.S_IREAD)                                        # the read-only attribute: refused even for an admin
        try:
            with self.assertRaises(hosts.HostsError) as cm: hosts.apply(flush=False)
        finally: os.chmod(hp, stat.S_IWRITE | stat.S_IREAD)
        msg = str(cm.exception)
        self.assertIn('read-only attribute', msg); self.assertIn('was not changed', msg); self.assertNotIn('rollback failed', msg)
        self.assertEqual(open(hp, 'rb').read().decode(), orig)

    def test_refuses_foreign_non_loopback_mapping(self):
        put(WIN_HOSTS + f'203.0.113.9 {paths.HOST}\r\n')
        with self.assertRaises(hosts.HostsError): hosts.apply(flush=False)
        self.assertIn('203.0.113.9', open(paths.hosts_path()).read())     # untouched
        hosts.apply(flush=False, force=True); self.assertNotIn('203.0.113.9', open(paths.hosts_path()).read())

    def test_partial_block_detected(self):
        put(WIN_HOSTS + f'{hosts.BEGIN}\r\n::1 {paths.HOST}\r\n{hosts.END}\r\n')
        self.assertEqual(hosts.status()['state'], 'PARTIAL')
        hosts.apply(flush=False); self.assertEqual(hosts.status()['state'], 'OK')

    def test_other_lines_never_modified(self):
        orig = put(WIN_HOSTS + '10.1.1.1 keepme.example # my note\r\n')
        hosts.apply(flush=False); hosts.remove(flush=False)
        self.assertEqual(open(paths.hosts_path(), 'rb').read().decode(), orig)

    def test_backup_restore(self):
        orig = put(WIN_HOSTS); hosts.apply(flush=False)
        bk = hosts.list_backups()[0]; hosts.restore_backup(bk, flush=False)
        self.assertEqual(open(paths.hosts_path(), 'rb').read().decode(), orig)

    def test_cli_status_and_diff(self):
        put(WIN_HOSTS)
        out = subprocess.run([sys.executable, os.path.join(TOOLS, 'ccshosts.py'), 'diff', 'apply'], capture_output=True, text=True, env=os.environ).stdout
        self.assertIn('+' + hosts.BEGIN, out)
        out = subprocess.run([sys.executable, os.path.join(TOOLS, 'ccshosts.py'), 'status', '--json'], capture_output=True, text=True, env=os.environ).stdout
        self.assertEqual(json.loads(out)['state'], 'ABSENT')


class ProcTests(unittest.TestCase):
    def test_start_status_stop_and_adopt(self):
        log = os.path.join(paths.RUN, 'dummy.out')
        st = procs.start('dummy', [sys.executable, '-c', 'import time;print("hi",flush=True);time.sleep(60)'], log)
        self.assertTrue(st['alive']); pid = st['pid']
        self.assertTrue(procs.status('dummy')['alive'])
        self.assertEqual(procs.start('dummy', ['never'], log)['pid'], pid)   # already alive -> adopted, not duplicated
        time.sleep(0.5); self.assertIn('hi', open(log).read())
        self.assertTrue(procs.stop('dummy')); self.assertFalse(procs.status('dummy')['alive']); self.assertIsNone(procs.ctime(pid))

    def test_stale_pidfile_with_reused_pid_not_adopted(self):
        json.dump(dict(pid=os.getpid(), argv=[], started=0, ctime=12345, log=''), open(os.path.join(paths.RUN, 'fake.pid'), 'w'))
        self.assertFalse(procs.status('fake')['alive'])                      # live pid but wrong creation time

    def test_port_owner(self):
        s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(1); port = s.getsockname()[1]
        try: self.assertTrue(any(o['pid'] == os.getpid() for o in procs.port_owner(port)))
        finally: s.close()

    def test_port_owner_survives_undecodable_and_localised_netstat(self):
        # a non-English Windows prints bytes the ANSI codepage cannot decode: subprocess then returns stdout=None (no exception) -> used to crash with
        # "'NoneType' object has no attribute 'splitlines'" in Start session, Doctor and proxy start
        import subprocess as sp
        from unittest import mock
        none = sp.CompletedProcess([], 0, stdout=None, stderr='')
        with mock.patch.object(procs.subprocess, 'run', return_value=none): self.assertEqual(procs.port_owner(8443), [])
        fr = ('  Proto  Adresse locale   Adresse distante   État   PID\n  TCP    127.0.0.1:8443   0.0.0.0:0   ÉCOUTE   4242\n'
              '  TCP    127.0.0.1:8443   127.0.0.1:50000   ÉTABLI   4242\n')
        with mock.patch.object(procs.subprocess, 'run', return_value=sp.CompletedProcess([], 0, stdout=fr, stderr='')), mock.patch.object(procs, '_pid_name', return_value='x.exe'):
            self.assertEqual(procs.port_owner(8443), [dict(addr='127.0.0.1', pid=4242, name='x.exe')])   # state word ignored, established sockets not listed

    def test_image_running(self):
        self.assertIn('python.exe', procs.image_running('python.exe', 'definitely-not-a-process.exe'))


class ConfigTests(unittest.TestCase):
    def test_defaults_merge_and_profiles(self):
        c = config.load(); self.assertEqual(c['proxy']['port'], 80)
        c['proxy']['budget_gib'] = 7; c['profile'] = 'Offline test'; config.save(c)
        c2 = config.load(); self.assertEqual(c2['proxy']['budget_gib'], 7); self.assertTrue(config.effective_proxy(c2)['offline'])
        self.assertIn('--offline', proxyctl.proxy_argv(c2)); self.assertIn('--origin', proxyctl.proxy_argv(c2))
        c2['profile'] = 'Capture'; a = proxyctl.proxy_argv(c2); self.assertNotIn('--origin', a); self.assertNotIn('--offline', a)


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


class FakeUp(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *a): pass
    def do_GET(self):
        want = int(self.path.rsplit('_', 2)[1], 16); body = b'u' * want
        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.send_header('ETag', '"abc"'); self.end_headers(); self.wfile.write(body)


class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.up_port = free_port(); cls.up = ThreadingHTTPServer(('127.0.0.1', cls.up_port), FakeUp); threading.Thread(target=cls.up.serve_forever, daemon=True).start()
        # tiny mirror: one stored chunk
        cls.mir = os.path.join(TMP, 'mirror'); cid = 0x1234567890abcdef; wire = 16
        os.makedirs(os.path.join(cls.mir, 'objects', f'{cid & 0xff:02x}'))
        open(os.path.join(cls.mir, 'objects', f'{cid & 0xff:02x}', f'{cid:016x}_{wire:08x}_1'), 'wb').write(b'm' * wire)
        c = sqlite3.connect(os.path.join(cls.mir, 'index.sqlite'))
        c.execute('create table chunks(id integer primary key, wire integer, raw integer, flag integer, prio integer, status integer default 0, etag text, cod_key text, ts real)')
        c.execute('insert into chunks(id,wire,raw,flag,prio,status,etag,cod_key) values (?,?,?,?,?,1,?,?)', (cid, wire, 1 << 20, 1, 0, 'deadbeef', 'a0b1c2d3e4f50617')); c.commit(); c.close()
        cls.cid = cid; cls.wire = wire

    def run_proxy(self, *extra):
        port = free_port(); st = os.path.join(TMP, f'stats_{port}.json'); log = os.path.join(TMP, f'px_{port}.log')
        p = subprocess.Popen([sys.executable, os.path.join(TOOLS, 'ccsproxy.py'), '--port', str(port), '--upstream-ip', '127.0.0.1', '--upstream-port', str(self.up_port),
                              '--log', log, '--stats-json', st, '--origin', self.mir] + list(extra), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        self.addCleanup(p.kill)
        t0 = time.time()
        while time.time() - t0 < 90:                         # index load parses the real *_cdn.xpak lists
            if os.path.exists(log) and 'READY' in open(log, encoding='utf-8').read(): return port, st, log
            self.assertIsNone(p.poll(), 'proxy exited early'); time.sleep(0.3)
        self.fail('proxy did not become READY')

    def get(self, port, path, method='GET'):
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=10); c.request(method, path); r = c.getresponse(); b = r.read(); return r.status, b, r

    def test_stats_endpoint_hist_recent_and_json(self):
        port, st, log = self.run_proxy()
        s, b, r = self.get(port, f'/pc/iw9_3/23/{self.cid & 0xff:02x}/{self.cid:016x}_{self.wire:08x}_1')            # mirror hit
        self.assertEqual((s, b), (200, b'm' * 16)); self.assertEqual(r.getheader('x-amz-meta-cod-key'), 'a0b1c2d3e4f50617'); self.assertEqual(r.getheader('ETag'), '"deadbeef"')
        other = 0x00000000000000aa
        s, b, _ = self.get(port, f'/pc/iw9_3/23/aa/{other:016x}_00000020_1'); self.assertEqual((s, len(b)), (200, 32))   # upstream miss path
        s, b, _ = self.get(port, '/__ccs/stats'); d = json.loads(b)
        self.assertEqual(d['stat']['req'], 2); self.assertEqual(d['stat']['mirror'], 1); self.assertEqual(d['stat']['ok'], 2)
        self.assertEqual(d['stat']['mbytes'], 16); self.assertEqual(d['stat']['bytes'], 32)
        self.assertEqual({x['src'] for x in d['recent']}, {'mirror', 'upstream'}); self.assertEqual(d['mirror_ids'], 1)
        self.assertEqual(d['args']['port'], port); self.assertEqual(d['svc_ms']['n'], 2); self.assertTrue(all(x['ms'] is not None and x['ms'] >= 0 for x in d['recent']))   # per-request service time
        self.assertEqual(proxyctl.fetch_stats(port)['stat']['req'], 2)                                           # GUI helper
        t0 = time.time()
        while time.time() - t0 < 6 and not os.path.exists(st): time.sleep(0.2)
        self.assertEqual(json.load(open(st))['stat']['req'], 2)                                                  # --stats-json snapshot
        self.assertNotIn('/__ccs', open(log, encoding='utf-8').read())                                           # status polls are not logged as chunk traffic

    def test_proxy_starts_and_fetches_from_the_cdn_when_there_is_no_mirror_yet(self):
        # a first-time user has no mirror: a missing folder and an empty one must both start fine (this used to crash on index.sqlite) and serve from the upstream
        empty = os.path.join(TMP, 'empty_mirror'); os.makedirs(empty, exist_ok=True)
        for origin in (os.path.join(TMP, 'no_such_mirror'), empty):
            port, st, log = self.run_proxy('--origin', origin)
            self.assertIn('no index in', open(log, encoding='utf-8').read())
            s, b, _ = self.get(port, f'/pc/iw9_3/23/aa/{0xaa:016x}_00000020_1'); self.assertEqual((s, len(b)), (200, 32))
            self.assertEqual(json.loads(self.get(port, '/__ccs/stats')[1])['mirror_ids'], 0)
            self.assertFalse(os.path.exists(os.path.join(origin, 'index.sqlite')))                                   # nothing was created in the user's folder

    def test_offline_mode_404s_misses_but_serves_mirror(self):
        port, st, log = self.run_proxy('--offline')
        self.assertEqual(self.get(port, f'/pc/iw9_3/23/{self.cid & 0xff:02x}/{self.cid:016x}_{self.wire:08x}_1')[0], 200)
        self.assertEqual(self.get(port, '/pc/iw9_3/23/bb/00000000000000bb_00000020_1')[0], 404)
        d = json.loads(self.get(port, '/__ccs/stats')[1]); self.assertEqual(d['stat']['miss'], 1); self.assertEqual(d['stat']['bytes'], 0)
        self.assertIn('MISS-OFFLINE', open(log, encoding='utf-8').read())

    def test_bind_failure_exits_nonzero(self):
        s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(1); port = s.getsockname()[1]
        try:
            p = subprocess.run([sys.executable, os.path.join(TOOLS, 'ccsproxy.py'), '--port', str(port), '--upstream-ip', '127.0.0.1', '--log', os.path.join(TMP, 'bind.log')],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 2); self.assertIn('BIND-FAIL', p.stdout)
        finally: s.close()


class GuardTests(unittest.TestCase):
    def test_warn_mode_reports_hit_and_keeps_running(self):
        cache = os.path.join(TMP, 'cache'); os.makedirs(cache); open(os.path.join(cache, 'x'), 'wb').write(b'0' * (2 << 20))
        st = os.path.join(TMP, 'g.json')
        p = subprocess.Popen([sys.executable, os.path.join(TOOLS, 'diskguard.py'), '--limit-gib', '0.001', '--action', 'warn', '--interval', '0.3', '--cache', cache,
                              '--status-json', st, '--log', os.path.join(TMP, 'g.log')], stdout=subprocess.DEVNULL)
        self.addCleanup(p.kill); t0 = time.time()
        while time.time() - t0 < 10 and not (os.path.exists(st) and json.load(open(st)).get('hit')): time.sleep(0.2)
        d = json.load(open(st)); self.assertTrue(d['hit']); self.assertEqual(d['action'], 'warn'); self.assertIsNone(p.poll())


from ccslib import report, logtail, doctor, session, bundle


def req(t, cid, wire, src='mirror', method='GET', status=200, rng='-'):
    path = f'/pc/iw9_3/23/{cid & 0xff:02x}/{cid:016x}_{wire:08x}_1'
    tail = f'{wire}B MIRROR' if src == 'mirror' else f'{wire}B raw=1 range={rng} total=0.000GiB'
    return f'{t} {method} {path} -> {status} {tail}'


class ReportTests(unittest.TestCase):
    A, B, C, D = 0x100, 0x200, 0x300, 0x400
    CAT = {0x100: dict(raw=2**20, size=500), 0x200: dict(raw=2**22, size=900), 0x300: dict(raw=13 * 2**20, size=5000), 0x400: dict(raw=2**16, size=100)}

    def log(self):
        p = os.path.join(TMP, 'rep.log')
        L = ['10:00:00 old run header', '10:00:00 index: 5 chunk ids',                                     # old-style run: no START line
             req('10:00:01', self.A, 500), '10:00:02 SKIP-TIER GET /pc/iw9_3/23/00/0000000000000300_00001388_1 raw=13.0MiB',
             '11:00:00 START 2026-10-20 pid=1 args=--origin m', '11:00:00 mirror: 3 stored chunks indexed from m', '11:00:00 index: 4 chunk ids',
             '11:00:00 upstream 1.2.3.4  tier<=4096.0MiB  budget=120.0GiB', '11:00:01 READY pid=1 port=80',
             req('23:59:58', self.A, 500), req('23:59:58', self.A, 500), req('23:59:59', self.B, 900),
             req('00:00:01', self.C, 5000, src='upstream'), req('00:00:01', self.D, 100, src='upstream', method='HEAD'), req('00:00:02', 0x999, 50, src='upstream', status=404),
             req('00:00:02', self.A, 100, src='upstream', rng='bytes=0-99', status=206),
             '00:00:03 RETRY 1/4 /pc/iw9_3/23/aa/00000000000000aa_00000010_1: boom', "00:01:00 stats {'req': 7, 'ok': 5}"]
        open(p, 'w', encoding='utf-8').write('\n'.join(L) + '\n'); return p

    def test_segments_split_and_dates(self):
        s = report.segments(self.log())
        self.assertEqual(len(s), 2); self.assertIsNone(s[0]['date']); self.assertEqual(s[1]['date'], '2026-10-20'); self.assertEqual(s[0]['nreq'], 1); self.assertEqual(s[1]['nreq'], 7)
        self.assertEqual(len(s[1]['header']), 3)                           # START + mirror + index lines belong to the run they start
        self.assertAlmostEqual(report.seg_start_epoch(s[1]), __import__('datetime').datetime(2026, 10, 20, 11, 0, 0).timestamp())

    def test_build_metrics(self):
        seg = report.segments(self.log())[1]
        base = dict(taken=0, records=10, unique=2, ids=[hex(self.A), hex(0x777)]); post = dict(taken=1, records=14, unique=4, ids=[hex(self.A), hex(self.B), hex(self.C), hex(0x777)])
        r = report.build(seg, catalogue=self.CAT, mirror_ids={self.A, self.B}, baseline=base, post=post, cfg={})
        q = r['requests']
        self.assertEqual((q['total'], q['chunk_gets'], q['probes'], q['unique_ids'], q['repeated_ids'], q['extra_repeat_requests']), (7, 5, 2, 4, 1, 1))   # midnight wrap handled; HEAD/range are probes
        self.assertEqual(r['active_s'], 4)                                  # 23:59:58 -> 00:00:02 across midnight
        self.assertEqual((r['served']['mirror'], r['served']['upstream']), (3, 1)); self.assertEqual(r['served']['non200'], {404: 1})   # 404 id 0x999 is a GET
        self.assertEqual(r['events'], {'RETRY': 1})
        self.assertEqual(r['over_4mib']['ids'], 1); self.assertEqual(r['over_4mib']['top'][0]['raw_mib'], 13.0)
        self.assertEqual(r['tiers']['<=1M']['requested'], 1); self.assertEqual(r['tiers']['<=4M']['requested'], 1); self.assertEqual(r['unknown_ids'], 1)
        self.assertEqual(r['mirror_gaps']['missing_count'], 2)              # C (upstream) and 0x999 are not in the mirror
        c = r['cache']; self.assertEqual(c['requested_already_in_cache'], 1); self.assertEqual(c['requested_pct_already_in_cache'], 25.0)
        self.assertEqual((c['new_unique_ids'], c['record_growth']), (2, 4))
        md = report.to_markdown(r); self.assertIn('>4 MiB ids requested: 1', md); self.assertIn('requested_pct_already_in_cache: 25.0', md)

    def test_window_scale_timeline_and_baseline_t0(self):
        import datetime
        seg = report.segments(self.log())[1]; e = lambda s: datetime.datetime.strptime(s, '%Y-%m-%d %H:%M:%S').timestamp()
        self.assertEqual(report.scale_of(seg, e('2026-10-21 00:00:01')), 86401)                                  # request clock scale incl. the midnight wrap
        r = report.build(seg, catalogue=self.CAT, cfg={}, window=(e('2026-10-20 23:59:59'), e('2026-10-21 00:00:01')))
        self.assertEqual((r['requests']['total'], r['requests']['chunk_gets'], r['requests']['probes']), (3, 2, 1))   # B + C + the HEAD; the other four fall outside the launch
        self.assertEqual((r['window']['from'], r['window']['to'], r['first'], r['events']), ('23:59:59', '00:00:01', '23:59:59', {}))
        self.assertIn('game launch', report.to_markdown(r))
        full = report.build(seg, catalogue=self.CAT, cfg={})
        self.assertIn('throughput_mibps_10s', full); self.assertEqual(sum(x['requests'] for x in full['timeline']), full['requests']['chunk_gets']); self.assertEqual(sum(x['big'] for x in full['timeline']), 1)
        t0 = e('2026-10-20 12:30:00')
        report.save_snapshot(dict(taken=t0 - 3600, records=1, unique=1, ids=['0x1']), os.path.join(paths.SESSIONS, 'baseline-w1.json'))
        report.save_snapshot(dict(taken=t0 - 60, records=2, unique=2, ids=['0x2']), os.path.join(paths.SESSIONS, 'baseline-w2.json'))
        report.save_snapshot(dict(taken=t0 + 60, records=3, unique=3, ids=['0x3']), os.path.join(paths.SESSIONS, 'baseline-w3.json'))
        self.assertEqual(report.baseline_for(seg, t0=t0)['records'], 2)                                           # latest snapshot taken before the launch, however long before
    def test_save_and_previous(self):
        seg = report.segments(self.log())[1]
        r1 = report.build(seg, catalogue=self.CAT, cfg={}); r1['date'] = '2026-10-19'; m1, j1 = report.save(r1)
        r2 = report.build(seg, catalogue=self.CAT, cfg={}); r2['date'] = '2026-10-20'
        prev = report.previous_report(r2); self.assertEqual(prev['date'], '2026-10-19')
        self.assertIn('Change vs previous report', report.to_markdown(r2, prev)); self.assertTrue(os.path.exists(m1))
        self.assertIsNone(report.previous_report(r1))                       # nothing earlier than the first one

    def test_baseline_for_picks_snapshot_before_start(self):
        seg = report.segments(self.log())[1]; t0 = report.seg_start_epoch(seg)
        report.save_snapshot(dict(taken=t0 - 60, records=1, unique=1, ids=['0x1']), os.path.join(paths.SESSIONS, 'baseline-a.json'))
        report.save_snapshot(dict(taken=t0 - 5000, records=9, unique=9, ids=['0x2']), os.path.join(paths.SESSIONS, 'baseline-b.json'))     # too old
        report.save_snapshot(dict(taken=t0 + 600, records=7, unique=7, ids=['0x3']), os.path.join(paths.SESSIONS, 'baseline-c.json'))      # after the start
        self.assertEqual(report.baseline_for(seg)['records'], 1)
        self.assertNotIn('baseline-a.json', [os.path.basename(x) for x in report.list_reports()])           # snapshots are not reports

    def test_snapshot_empty_dir(self):
        d = os.path.join(TMP, 'emptycache'); os.makedirs(d); s = report.snapshot_cache(d); self.assertEqual((s['records'], s['unique']), (0, 0))


class LogTailTests(unittest.TestCase):
    def test_partial_lines_truncation_and_backfill(self):
        p = os.path.join(TMP, 't.log'); open(p, 'w').write('a\nb\n')
        t = logtail.Tail(p, backfill=10); self.assertEqual(t.read_new(), ['a', 'b']); self.assertEqual(t.read_new(), [])
        open(p, 'a').write('c\nd'); self.assertEqual(t.read_new(), ['c'])                       # 'd' is unfinished
        open(p, 'a').write('e\n'); self.assertEqual(t.read_new(), ['de'])
        open(p, 'w').write('x\n'); self.assertEqual(t.read_new(), ['x'])                        # truncated -> restart from 0
        self.assertEqual(logtail.Tail(os.path.join(TMP, 'nope.log')).read_new(), [])


class DoctorSessionTests(unittest.TestCase):
    def test_fix_hints_and_run_fix(self):
        put(WIN_HOSTS)
        res = doctor.check_hosts(); self.assertEqual(res[0]['level'], 'fail'); self.assertEqual(res[0]['fix'], ('hosts_apply', None))
        s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(1); port = s.getsockname()[1]
        try:
            cfg = config.load(); cfg['proxy']['port'] = port; r = doctor.check_port(cfg)
            self.assertEqual(r['level'], 'fail'); self.assertEqual(r['fix'][0], 'kill_port_owner'); self.assertEqual(r['fix'][1][0][0], os.getpid())
        finally: s.close()
        self.assertEqual(doctor.check_proxy(dict(proxy=dict(port=free_port()), guard={}, profile='Default'))[0]['fix'], ('start_proxy', None))
        self.assertEqual(session.run_fix(config.load(), ('nope', None), lambda m: None)[0], False)

    def test_kill_port_owner_fix_terminates_process(self):
        p = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)']); time.sleep(0.3)
        ok, msg = session.run_fix(config.load(), ('kill_port_owner', [(p.pid, 'python.exe')]), lambda m: None)
        self.assertTrue(ok); p.wait(timeout=10); self.assertIsNotNone(p.poll())

    def test_bundle_contents(self):
        put(WIN_HOSTS); z = zipfile.ZipFile(bundle.make(config.load())); names = z.namelist()
        for n in ('state/hosts.txt', 'state/doctor.txt', 'state/env.txt', 'state/runs.txt', 'state/gui_settings.json'): self.assertIn(n, names)
        self.assertIn('Hosts override', z.read('state/doctor.txt').decode())


from ccslib import cachectl, mirrorctl
import hashlib, struct


class FakeCdn(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'; delay = 0.0
    def log_message(self, *a): pass
    def do_GET(self):
        time.sleep(FakeCdn.delay); wire = int(self.path.rsplit('_', 2)[1], 16); body = bytes([wire & 0xff]) * wire
        self.send_response(200); self.send_header('Content-Length', str(wire)); self.send_header('ETag', f'"{hashlib.md5(body).hexdigest()}"'); self.send_header('x-amz-meta-cod-key', '0011223344556677'); self.end_headers(); self.wfile.write(body)


class MirrorToolTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='mir_', dir=TMP); self.env = dict(os.environ, CCS_MIRROR_DIR=self.dir, CCS_ACCEPT_NOTICE='1')
        c = sqlite3.connect(os.path.join(self.dir, 'index.sqlite'))
        c.execute('create table chunks(id integer primary key, wire integer, raw integer, flag integer, prio integer, status integer default 0, etag text, cod_key text, ts real)')
        self.n = 120
        for i in range(self.n): c.execute('insert into chunks(id,wire,raw,flag,prio) values (?,?,?,?,?)', (0x1000 + i, 40 + i, 4096, 1, 1))
        c.commit(); c.close()
        FakeCdn.delay = 0.0; self.srv = ThreadingHTTPServer(('127.0.0.1', 0), FakeCdn); threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.addCleanup(self.srv.shutdown)
        self.pj = os.path.join(self.dir, 'prog.json'); self.sf = os.path.join(self.dir, 'STOP')

    def cli(self, *a, wait=True):
        cmd = [sys.executable, os.path.join(TOOLS, 'ccsmirror.py'), *a]
        if wait: return subprocess.run(cmd, capture_output=True, text=True, env=self.env, timeout=120)
        return subprocess.Popen(cmd, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def run_args(self): return ['run', '--workers', '4', '--budget-gib', '1', '--min-free-gib', '0', '--max-rps', '1000', '--retries', '1', '--upstream-ip', '127.0.0.1',
                                '--upstream-port', str(self.srv.server_address[1]), '--progress-json', self.pj, '--stop-file', self.sf]

    def status(self): return json.loads(self.cli('status', '--json').stdout)

    def test_full_run_progress_verify(self):
        r = self.cli(*self.run_args()); self.assertEqual(r.returncode, 0, r.stderr)
        p = json.load(open(self.pj)); self.assertEqual((p['state'], p['ok'], p['fail'], p['queued'], p['left']), ('done', self.n, 0, self.n, 0))
        st = self.status(); self.assertEqual(st['stored'], self.n); self.assertEqual(st['cod_key'], self.n)
        o = os.path.join(self.dir, 'objects', '00', f'{0x1000:016x}_{40:08x}_1'); self.assertEqual(open(o, 'rb').read(), bytes([40]) * 40)
        self.assertIn('0 bad', self.cli('verify', '--n', '50').stdout)

    def test_pause_via_stop_file_then_resume(self):
        FakeCdn.delay = 0.25; pr = self.cli(*self.run_args(), wait=False); t0 = time.time()
        while time.time() - t0 < 30 and not os.path.exists(self.pj): time.sleep(0.2)
        time.sleep(1.5); open(self.sf, 'w').write('stop'); pr.wait(timeout=60)
        p = json.load(open(self.pj)); self.assertEqual(p['state'], 'paused'); stored = self.status()['stored']
        self.assertTrue(0 < stored < self.n, stored)
        FakeCdn.delay = 0; r = self.cli(*self.run_args()); self.assertEqual(r.returncode, 0)             # stale STOP file is cleared at start; resume only fetches the rest
        self.assertEqual(self.status()['stored'], self.n); self.assertEqual(json.load(open(self.pj))['queued'], self.n - stored)

    def test_retry_failed_resets_status(self):
        c = sqlite3.connect(os.path.join(self.dir, 'index.sqlite')); c.execute('update chunks set status=2 where id < ?', (0x1000 + 10,)); c.commit(); c.close()
        self.assertEqual(sum(r['chunks'] for r in self.status()['rows'] if r['status'] == 'failed'), 10)
        self.cli('retry-failed'); self.assertEqual(sum(r['chunks'] for r in self.status()['rows'] if r['status'] == 'failed'), 0)

    def test_mirrorctl_argv_and_pause(self):
        a = mirrorctl.run_argv(workers=3, tier=1024, budget_gib=5); self.assertIn('--progress-json', a); self.assertEqual(a[a.index('--workers') + 1], '3')
        old = paths.MIRROR; paths.MIRROR = self.dir
        try:
            self.assertEqual(mirrorctl.stopfile(), self.sf)                                                 # follows the configured mirror folder
            self.assertFalse(mirrorctl.pause()); self.assertFalse(os.path.exists(self.sf))                  # nothing running -> no stop file
        finally: paths.MIRROR = old


def make_shard(path, ids, counter=5, data=b'x' * 8192):
    d = bytearray(0x88000); struct.pack_into('<I', d, 8, counter); d[0x130:0x150] = bytes(range(32))
    for k, i in enumerate(sorted(ids)): struct.pack_into('<QIII', d, 0x8000 + 20 * k, i, (100 << 1) | 1, (k * 4096) >> 7, 200)
    struct.pack_into('<Q', d, 0x788, len(ids)); struct.pack_into('<Q', d, 0x798, 4096 * len(ids)); struct.pack_into('<QQQQ', d, 0x7a0, len(ids), 0x8000, len(ids) * 20, 0)
    open(path, 'wb').write(d); open(path + 'data', 'wb').write(data)


from ccslib import logrot, shortcut


class PathsConfigTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {k: getattr(paths, k) for k in ('GAME_ROOT', 'ROOT', 'XPAK_CACHE', 'MIRROR', 'PLAYER_CFG', 'GAME_EXES', 'KILL_EXES', 'CONFIGURED')}
        self.env = {k: os.environ.pop(k, None) for k in ('CCS_GAME_ROOT', 'CCS_CACHE_DIR', 'CCS_MIRROR_DIR', 'CCS_PLAYER_CFG')}
        self.game = tempfile.mkdtemp(prefix='game_', dir=TMP); os.makedirs(os.path.join(self.game, 'cod26')); open(os.path.join(self.game, 'cod26', 'x_cdn.xpak'), 'wb').write(b'0')
        self.addCleanup(self.restore)

    def restore(self):
        for k, v in self.env.items():
            if v is not None: os.environ[k] = v
        try: os.remove(paths.SETTINGS_FILE)
        except OSError: pass
        paths.reload()

    def test_unconfigured_falls_back_and_flags_setup(self):
        try: os.remove(paths.SETTINGS_FILE)
        except OSError: pass
        paths.reload(); self.assertFalse(paths.CONFIGURED); self.assertEqual(paths.SOURCES['game_root'], 'fallback')
        self.assertEqual(paths.validate()[0]['level'], 'fail')                          # GUI/session refuse to start until the game folder is set

    def test_configured_locations_are_used_everywhere(self):
        mir = os.path.join(TMP, 'bigdrive', 'mirror'); cache = os.path.join(TMP, 'c')
        c = config.load(); c['paths'].update(game_root=self.game, mirror_dir=mir, cache_dir=cache, game_exes='foo.exe; bar.exe', kill_exes='foo.exe'); config.save(c)
        self.assertTrue(paths.CONFIGURED); self.assertEqual((paths.GAME_ROOT, paths.ROOT), (os.path.normpath(self.game),) * 2)
        self.assertEqual(paths.MIRROR, os.path.normpath(mir)); self.assertEqual(paths.XPAK_CACHE, os.path.normpath(cache)); self.assertEqual(paths.GAME_EXES, ('foo.exe', 'bar.exe')); self.assertEqual(paths.KILL_EXES, ('foo.exe',))
        self.assertEqual(paths.SOURCES['mirror_dir'], 'settings'); self.assertEqual(mirrorctl.stopfile(), os.path.join(os.path.normpath(mir), 'STOP'))
        self.assertIn(os.path.normpath(mir), proxyctl.proxy_argv(c))                      # proxy --origin follows the configured mirror
        self.assertIn(os.path.normpath(cache), proxyctl.guard_argv(c))                    # guard watches the configured cache
        v = {r['name']: r for r in paths.validate()}; self.assertEqual(v['Game folder']['level'], 'ok'); self.assertEqual(v['CDN chunk lists']['level'], 'ok'); self.assertEqual(v['Mirror folder']['level'], 'warn')

    def test_derived_locations_follow_game_root_and_env_wins(self):
        c = config.load(); c['paths'].update(game_root=self.game); config.save(c)
        self.assertEqual(paths.XPAK_CACHE, os.path.join(os.path.normpath(self.game), 'xpak_cache')); self.assertEqual(paths.SOURCES['cache_dir'], 'derived')
        os.environ['CCS_CACHE_DIR'] = os.path.join(TMP, 'envcache')
        try: paths.reload(); self.assertEqual(paths.XPAK_CACHE, os.path.normpath(os.path.join(TMP, 'envcache'))); self.assertEqual(paths.SOURCES['cache_dir'], 'env')
        finally: del os.environ['CCS_CACHE_DIR']

    def test_session_start_refuses_when_game_folder_invalid(self):
        c = config.load(); c['paths'].update(game_root=os.path.join(TMP, 'does-not-exist')); config.save(c)
        ok, msg = session.start(config.load(), lambda m: None)
        self.assertFalse(ok); self.assertIn('setup needed', msg); self.assertFalse(procs.status('proxy')['alive'])

    def test_profiles_builtin_user_effective(self):
        c = config.load(); self.assertEqual(set(config.BUILTIN_PROFILES) - set(config.all_profiles(c)), set())
        c['proxy']['budget_gib'] = 11; c['guard']['limit_gib'] = 50; c['profile'] = 'Offline test'
        self.assertTrue(config.effective_proxy(c)['offline']); self.assertEqual(config.effective(c)['proxy']['budget_gib'], 11)
        c['profile'] = 'Default'; prof = config.snapshot_profile(c); prof['guard']['limit_gib'] = 7; prof['proxy']['port'] = 8080
        c['profiles']['mine'] = prof; c['profile'] = 'mine'; e = config.effective(c)
        self.assertEqual((e['guard']['limit_gib'], e['proxy']['port'], e['proxy']['budget_gib']), (7, 8080, 11)); self.assertEqual(c['guard']['limit_gib'], 50)   # base untouched
        c['profiles']['Default'] = dict(proxy=dict(port=1)); self.assertEqual(config.all_profiles(c)['Default']['proxy'].get('port'), None)        # built-ins cannot be shadowed
        self.assertIn('--port', proxyctl.proxy_argv(c)); self.assertEqual(proxyctl.guard_argv(c)[proxyctl.guard_argv(c).index('--limit-gib') + 1], '7')


class LogRotationTests(unittest.TestCase):
    def test_rotate_chain_and_report_reads_rotated_runs(self):
        p = os.path.join(TMP, 'rot.log')
        for gen in range(1, 6):
            open(p, 'w').write(f'gen{gen}\n' * 1000); self.assertTrue(logrot.rotate(p, 100))
        self.assertFalse(os.path.exists(p)); self.assertEqual([open(f'{p}.{i}').read()[:4] for i in (1, 2, 3)], ['gen5', 'gen4', 'gen3'])      # keeps 3 copies, newest first
        self.assertFalse(logrot.rotate(p, 100)); open(p, 'w').write('x'); self.assertFalse(logrot.rotate(p, 100)); self.assertFalse(logrot.rotate(p, 0))
        lg = os.path.join(TMP, 'seg.log'); open(lg + '.1', 'w').write('10:00:00 START 2026-10-01 pid=1\n10:00:00 index: 1 chunk ids\n10:00:01 stats {}\n')
        open(lg, 'w').write('11:00:00 START 2026-10-02 pid=2\n11:00:00 index: 1 chunk ids\n')
        s = report.segments(lg); self.assertEqual([x['date'] for x in s], ['2026-10-01', '2026-10-02']); self.assertEqual([x['idx'] for x in s], [0, 1])

    def test_rotate_all_skips_running_writers(self):
        for n in ('a.log', 'b.log'): open(os.path.join(paths.WORK, n), 'w').write('z' * 2000)
        done = logrot.rotate_all(0.001, skip_running=['b.log']); self.assertIn('a.log', done); self.assertNotIn('b.log', done)


class ShortcutTests(unittest.TestCase):
    def test_creates_lnk(self):
        d = tempfile.mkdtemp(prefix='lnk_', dir=TMP); p = shortcut.create(d); self.assertTrue(p.endswith('CCS Control.lnk') and os.path.getsize(p) > 0)


class CacheCtlTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='cc_', dir=TMP); self.cache = os.path.join(self.root, 'xpak_cache'); os.makedirs(self.cache)
        make_shard(os.path.join(self.cache, 'cache_0_2.xpak'), [1, 2, 3]); make_shard(os.path.join(self.cache, 'cache_1_2.xpak'), [3, 4], counter=9)
        d = bytearray(32768); struct.pack_into('<I', d, 16, 64); open(os.path.join(self.cache, 'xpak_settings.bin'), 'wb').write(d)
        self.old = (paths.XPAK_CACHE, paths.ROOT, procs.image_running); paths.XPAK_CACHE = self.cache; paths.ROOT = self.root; procs.image_running = lambda *e: []
        self.addCleanup(self.restore_globals)

    def restore_globals(self): paths.XPAK_CACHE, paths.ROOT, procs.image_running = self.old

    def test_summary(self):
        s = cachectl.summary(); self.assertEqual((s['records'], s['unique'], s['active'], s['setting_gb']), (5, 4, 2, 64)); self.assertEqual(s['dup_ratio'], 1.25)
        sh = {x['name']: x for x in s['shards']}; self.assertEqual((sh['cache_1_2.xpak']['counter'], sh['cache_0_2.xpak']['records']), (9, 3))

    def test_backup_restore_roundtrip_keeps_replaced_copy(self):
        bk = cachectl.backup('t'); self.assertTrue(os.path.isdir(bk)); self.assertEqual([b[0] for b in cachectl.backups()], [os.path.basename(bk)])
        make_shard(os.path.join(self.cache, 'cache_0_2.xpak'), [9, 10, 11, 12])                                # cache changes after the backup
        aside = cachectl.restore(os.path.basename(bk))
        self.assertEqual(cachectl.summary()['unique'], 4); self.assertTrue(os.path.isdir(aside))               # restored; the modified cache is kept aside, not deleted
        self.assertEqual(cachectl.summary(aside)['records'], 6)

    def test_refuses_while_game_running(self):
        procs.image_running = lambda *e: ['cod.exe']
        for fn in (lambda: cachectl.backup(), lambda: cachectl.restore('xpak_cache.bak_x')):
            with self.assertRaises(cachectl.CacheBusy): fn()

    def test_delete_backup_guard(self):
        bk = os.path.basename(cachectl.backup('d'))
        with self.assertRaises(ValueError): cachectl.delete_backup('xpak_cache')                               # the live cache can never be deleted here
        with self.assertRaises(ValueError): cachectl.delete_backup('..\\evil')
        cachectl.delete_backup(bk); self.assertEqual(cachectl.backups(), [])
        self.assertTrue(os.path.isdir(self.cache))

    def test_restore_rejects_non_backup_names(self):
        with self.assertRaises(ValueError): cachectl.restore('xpak_cache')
        with self.assertRaises(ValueError): cachectl.restore('Windows')


if __name__ == '__main__':
    unittest.main()
