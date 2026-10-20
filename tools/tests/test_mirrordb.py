"""Tests for reading the mirror index when the folder is not writable for this user (ccslib/mirrordb.py) and for every place that reads it.
A real read-only folder cannot be made reliably from a test (an administrator ignores it), so the one SQLite error that a read-only WAL folder produces ("unable to open
database file" when the side files cannot be created) is injected for the normal open; the immutable fallback then runs against a real database."""
import os, shutil, sqlite3, sys, tempfile, unittest
from unittest import mock

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, TOOLS)
from ccslib import doctor, mirrordb, pack, paths, report

TMP = tempfile.mkdtemp(prefix='ccsmirdb_')
REAL_CONNECT = sqlite3.connect


def tearDownModule(): shutil.rmtree(TMP, ignore_errors=True)


def make_mirror(name, rows=3):
    """A folder with a WAL index: a path with spaces and brackets, as Program Files (x86) has."""
    d = os.path.join(TMP, name, 'Program Files (x86)', 'mirror'); os.makedirs(d)
    c = REAL_CONNECT(os.path.join(d, 'index.sqlite')); c.execute('pragma journal_mode=wal')
    c.execute('create table chunks(id integer primary key, wire integer, raw integer, flag integer, prio integer, status integer, etag text, cod_key text, ts integer, pkgs text)')
    for i in range(rows): c.execute('insert into chunks(id, wire, raw, flag, status, etag, cod_key) values(?,?,?,?,?,?,?)', (i + 1, 100 + i, 200, 1, 1, f'e{i}:x', f'key{i}'))
    c.commit(); c.close()
    for side in ('-wal', '-shm'):                                                   # what a read-only folder looks like: the side files are not there
        try: os.remove(os.path.join(d, 'index.sqlite' + side))
        except OSError: pass
    return d


def not_writable(real=REAL_CONNECT):
    """sqlite3.connect that fails the way a read-only folder does for the normal and the mode=ro open, and works for immutable=1."""
    def connect(target, *a, **k):
        if isinstance(target, str) and 'immutable=1' not in target: raise sqlite3.OperationalError('unable to open database file')
        return real(target, *a, **k)
    return connect


class Opener(unittest.TestCase):
    def test_a_normal_open_just_works_and_is_read_only(self):
        d = make_mirror('o1'); c = mirrordb.connect_read(os.path.join(d, 'index.sqlite'))
        self.assertEqual(c.execute('select count(*) from chunks where status=1').fetchone()[0], 3)
        with self.assertRaises(sqlite3.OperationalError): c.execute('insert into chunks(id) values(99)')
        c.close()

    def test_a_folder_that_cannot_be_written_falls_back_to_a_read_only_view(self):
        d = make_mirror('o2')
        with mock.patch.object(sqlite3, 'connect', side_effect=not_writable()):
            c = mirrordb.connect_read(os.path.join(d, 'index.sqlite')); self.assertEqual(c.execute('select count(*) from chunks').fetchone()[0], 3); c.close()
        self.assertEqual(sorted(os.listdir(d)), ['index.sqlite'], 'nothing was created in the folder')

    def test_other_errors_are_not_hidden_by_the_fallback(self):
        d = make_mirror('o3'); db = os.path.join(d, 'index.sqlite')
        def locked(target, *a, **k): raise sqlite3.OperationalError('database is locked')
        with mock.patch.object(sqlite3, 'connect', side_effect=locked):
            with self.assertRaises(sqlite3.OperationalError) as e: mirrordb.connect_read(db)
        self.assertIn('locked', str(e.exception))
        bad = os.path.join(d, 'bad.sqlite')
        with open(bad, 'wb') as f: f.write(b'this is not a database' * 50)
        with self.assertRaises(sqlite3.DatabaseError): mirrordb.connect_read(bad)
        with self.assertRaises(sqlite3.Error): mirrordb.connect_read(os.path.join(d, 'missing.sqlite'))

    def test_writable_folder_check(self):
        d = os.path.join(TMP, 'w1'); os.makedirs(d)
        self.assertTrue(mirrordb.writable(d)); self.assertTrue(mirrordb.writable(os.path.join(d, 'not', 'there', 'yet')), 'judged by the nearest folder that exists')
        self.assertEqual(os.listdir(d), [], 'the probe file is removed again')
        with mock.patch('builtins.open', side_effect=PermissionError('denied')): self.assertFalse(mirrordb.writable(d))


class Readers(unittest.TestCase):
    def setUp(self):
        self.addCleanup(paths.reload)

    def test_the_doctor_the_pack_check_and_reports_read_it_through_the_fallback(self):
        d = make_mirror('r1')
        with mock.patch.object(paths, 'MIRROR', d), mock.patch.object(sqlite3, 'connect', side_effect=not_writable()):
            total, rows = doctor._mirror_rows(); self.assertEqual(total, 3); self.assertEqual(len(rows), 3)
            self.assertEqual(pack.stored_status(), {1: 1, 2: 1, 3: 1}); self.assertEqual(report.load_mirror_ids(), {1, 2, 3})

    def test_the_proxy_loads_the_stored_chunk_keys_through_the_fallback(self):
        d = make_mirror('r2'); import ccsproxy
        with mock.patch.object(ccsproxy, 'LOG', os.path.join(TMP, 'proxy.log'), create=True), mock.patch.object(ccsproxy, 'MKEY', {}), mock.patch.object(sqlite3, 'connect', side_effect=not_writable()):
            ccsproxy.load_mirror(d); self.assertEqual(ccsproxy.MKEY[1], ('e0', 'key0')); self.assertEqual(len(ccsproxy.MKEY), 3)

    def test_the_proxy_says_so_and_carries_on_when_the_index_is_really_unreadable(self):
        d = os.path.join(TMP, 'r3'); os.makedirs(d); import ccsproxy
        with open(os.path.join(d, 'index.sqlite'), 'wb') as f: f.write(b'not a database' * 100)
        with mock.patch.object(ccsproxy, 'LOG', os.path.join(TMP, 'proxy3.log'), create=True), mock.patch.object(ccsproxy, 'MKEY', {}):
            ccsproxy.load_mirror(d); self.assertEqual(ccsproxy.MKEY, {})
        with open(os.path.join(TMP, 'proxy3.log'), encoding='utf-8') as f: self.assertIn('index unreadable', f.read())

    def test_the_locations_check_tells_a_read_only_mirror_from_a_missing_one(self):
        d = make_mirror('r4')
        with mock.patch.object(paths, 'MIRROR', d), mock.patch.object(mirrordb, 'writable', return_value=False):
            row = next(r for r in paths.validate() if r['name'] == 'Mirror folder'); self.assertEqual(row['level'], 'warn'); self.assertIn('read it but not write', row['detail'])
        with mock.patch.object(paths, 'MIRROR', os.path.join(TMP, 'ghost')), mock.patch.object(mirrordb, 'writable', return_value=False):
            row = next(r for r in paths.validate() if r['name'] == 'Mirror folder'); self.assertEqual(row['level'], 'info'); self.assertIn('cannot create', row['detail'])
        with mock.patch.object(paths, 'MIRROR', d): self.assertEqual(next(r for r in paths.validate() if r['name'] == 'Mirror folder')['level'], 'ok')


if __name__ == '__main__':
    unittest.main()
