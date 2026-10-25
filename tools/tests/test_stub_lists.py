"""Tests for the Xbox / Microsoft Store layout: the chunk lists ship as `*_cdn_stub.xpak`. A stub stands in for a missing full list; a full list always wins; nothing else changes.
Fake game folders only; the real game folder, mirror and hosts file are never touched.
"""
import os, shutil, sys, tempfile, unittest

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, TOOLS)
import cdnxpak
from ccslib import doctor, guide, pack, paths
from test_pack import fake_game, make_list, MiB

TMP = tempfile.mkdtemp(prefix='ccsstub_')


def tearDownModule(): shutil.rmtree(TMP, ignore_errors=True)


def to_stub(root):
    """Rename every list of a fake game folder to its Xbox name."""
    for d in ('cod26', 'sp26'):
        for fn in os.listdir(os.path.join(root, d)):
            if fn.endswith('_cdn.xpak'): os.rename(os.path.join(root, d, fn), os.path.join(root, d, fn[:-len('_cdn.xpak')] + '_cdn_stub.xpak'))
    return root


class FindTests(unittest.TestCase):
    def test_resolve_prefers_the_full_list_and_falls_back_to_the_stub(self):
        r = os.path.join(TMP, 'resolve'); make_list(os.path.join(r, 'sp26', 'sp26_cdn_stub.xpak'), [(0x1, 10, MiB, 1)])
        self.assertEqual(cdnxpak.resolve(r, 'sp26/sp26_cdn.xpak'), os.path.join(r, 'sp26', 'sp26_cdn_stub.xpak'))
        make_list(os.path.join(r, 'sp26', 'sp26_cdn.xpak'), [(0x2, 10, MiB, 1)])
        self.assertEqual(cdnxpak.resolve(r, 'sp26/sp26_cdn.xpak'), os.path.join(r, 'sp26', 'sp26_cdn.xpak'))
        self.assertIsNone(cdnxpak.resolve(r, 'cod26/mp26_cdn.xpak'))
        self.assertTrue(cdnxpak.is_stub('X:/a/b_cdn_stub.xpak')); self.assertFalse(cdnxpak.is_stub('X:/a/b_cdn.xpak'))

    def test_find_all_lists_a_stub_only_when_its_full_twin_is_missing(self):
        r = os.path.join(TMP, 'findall')
        make_list(os.path.join(r, 'sp26', 'sp26_cdn.xpak'), [(1, 10, MiB, 1)]); make_list(os.path.join(r, 'sp26', 'sp26_cdn_stub.xpak'), [(2, 10, MiB, 1)])      # both: the full one counts
        make_list(os.path.join(r, 'sp26', 'boot_cdn_stub.xpak'), [(3, 10, MiB, 1)]); make_list(os.path.join(r, 'cod26', 'mp26_cdn.xpak'), [(4, 10, MiB, 1)])
        got = [os.path.relpath(p, r).replace(os.sep, '/') for p in cdnxpak.find_all(r)]
        self.assertEqual(sorted(got), ['cod26/mp26_cdn.xpak', 'sp26/boot_cdn_stub.xpak', 'sp26/sp26_cdn.xpak'])

    def test_a_folder_with_no_lists_and_odd_names(self):
        r = os.path.join(TMP, 'none'); os.makedirs(os.path.join(r, 'sp26'))
        open(os.path.join(r, 'sp26', 'sp26_stub.xpak'), 'w').close(); open(os.path.join(r, 'sp26', 'x_cdn.xpak.bak'), 'w').close()
        self.assertEqual(cdnxpak.find_all(r), []); self.assertEqual(cdnxpak.find_all(os.path.join(r, 'missing')), [])

    def test_a_game_folder_with_brackets_still_works(self):
        r = os.path.join(TMP, 'game [x86]'); make_list(os.path.join(r, 'sp26', 'sp26_cdn_stub.xpak'), [(1, 10, MiB, 1)])
        self.assertEqual(len(cdnxpak.find_all(r)), 1)


class SameResultTests(unittest.TestCase):
    """The same install in the stub form gives exactly what the normal form gives."""
    @classmethod
    def setUpClass(cls):
        cls.full = fake_game(os.path.join(TMP, 'full')); cls.stub = to_stub(fake_game(os.path.join(TMP, 'stub')))

    def test_available_catalogue_plan_and_fingerprint_match(self):
        self.assertEqual({k: len(v) for k, v in pack.available(self.full).items()}, {k: len(v) for k, v in pack.available(self.stub).items()})
        self.assertEqual(pack.catalogue(pack.scope_mask('all'), self.full), pack.catalogue(pack.scope_mask('all'), self.stub))
        a = pack.plan('all', root=self.full, mirror_dir=os.path.join(TMP, 'm1')); b = pack.plan('all', root=self.stub, mirror_dir=os.path.join(TMP, 'm2'))
        for k in ('total', 'levels', 'by_pkg', 'packages', 'missing'): self.assertEqual(a[k], b[k], k)
        self.assertEqual(sorted(pack.fingerprint(self.full)), sorted(pack.fingerprint(self.stub)))
        self.assertTrue(pack.available(self.stub)['sp'] and pack.available(self.stub)['mp'] and not pack.available(self.stub)['hq'])

    def test_the_folder_picker_counts_stub_lists(self):
        self.assertEqual(guide.score_folder(self.stub), 3); self.assertEqual(guide.score_folder(self.full), 3)
        e = os.path.join(TMP, 'dirs_only'); os.makedirs(os.path.join(e, 'sp26')); self.assertEqual(guide.score_folder(e), 2)

    def test_proxy_index_reads_a_stub(self):
        import ccsproxy
        old = (ccsproxy.ROOT, ccsproxy.log); ccsproxy.RAW.clear(); ccsproxy.log = lambda *a, **k: None
        try:
            ccsproxy.ROOT = self.stub; ccsproxy.load_index(); stub_ids = dict(ccsproxy.RAW); ccsproxy.RAW.clear()
            ccsproxy.ROOT = self.full; ccsproxy.load_index(); full_ids = dict(ccsproxy.RAW)
        finally: ccsproxy.ROOT, ccsproxy.log = old; ccsproxy.RAW.clear()
        self.assertTrue(stub_ids); self.assertEqual(stub_ids, full_ids)


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.old = (paths.GAME_ROOT, paths.CONFIGURED)

    def tearDown(self): paths.GAME_ROOT, paths.CONFIGURED = self.old

    def row(self, root):
        paths.GAME_ROOT, paths.CONFIGURED = root, True
        return next(r for r in doctor.check_locations() if r['name'] == 'CDN chunk lists')

    def test_stub_lists_are_ok_and_named(self):
        r = self.row(to_stub(fake_game(os.path.join(TMP, 'doc_stub'))))
        self.assertEqual(r['level'], 'ok'); self.assertIn('4 chunk list files', r['detail']); self.assertIn('4 of them', r['detail'])

    def test_normal_lists_keep_their_text(self):
        r = self.row(fake_game(os.path.join(TMP, 'doc_full'))); self.assertEqual(r['level'], 'ok'); self.assertEqual(r['detail'], '4 *_cdn.xpak files under cod26/ and sp26/')

    def test_no_lists_still_warns(self):
        d = os.path.join(TMP, 'doc_none'); os.makedirs(os.path.join(d, 'sp26')); r = self.row(d); self.assertEqual(r['level'], 'warn'); self.assertIn('none found', r['detail'])


if __name__ == '__main__': unittest.main()
