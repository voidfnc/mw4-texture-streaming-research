"""Tests for the guided setup logic (ccslib/guide.py): finding the game folder, the checklist states, the milestones, and the first-run behaviour it relies on.
No GUI, no network; temp folders only.
"""
import copy, os, shutil, sys, tempfile, unittest
from unittest import mock

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, TOOLS)
from ccslib import config, doctor, guide, paths

TMP = tempfile.mkdtemp(prefix='ccsguide_')


def tearDownModule(): shutil.rmtree(TMP, ignore_errors=True)


def touch(p, data='x'):
    with open(p, 'w') as f: f.write(data)


def game(root, dirs=('sp26',), lists=True, exe=None):
    os.makedirs(root, exist_ok=True)
    for d in dirs: os.makedirs(os.path.join(root, d), exist_ok=True)
    if lists and dirs: touch(os.path.join(root, dirs[0], f'{dirs[0]}_cdn.xpak'))
    if exe: touch(os.path.join(root, exe))
    return root


BASE = dict(configured=True, folder_root='C:\\Somewhere\\Game', folder_exists=True, folder_score=3, blocked_by='', port=80, free_gib=200.0, game_running=False,
            proxy_ready=False, proxy_alive=False, hosts_ok=False, resolve_ok=False, hosts_state='ABSENT', requests=0, game_seen=False, pack_total=None, pack_stored=None, mirror_alive=False)
LIVE = dict(proxy_ready=True, proxy_alive=True, hosts_ok=True, resolve_ok=True, hosts_state='OK')


def F(**kw):
    d = dict(BASE); d.update(kw); return d


def status(rows): return {r['id']: r['status'] for r in rows}
def row(rows, i): return next(r for r in rows if r['id'] == i)
def acts(r): return [a for a, _ in r['actions']]


class StateTests(unittest.TestCase):
    def test_clean_state_is_defensive(self):
        d = guide.new_state()
        self.assertEqual(guide.clean_state(None), d); self.assertEqual(guide.clean_state('junk'), d); self.assertEqual(guide.clean_state({}), d)
        s = guide.clean_state(dict(path='warp', ms='session', skipped=[1, 'pack', None], enabled='yes', confirmed_root=5, offered=None, extra=1))
        self.assertEqual((s['path'], s['ms'], s['skipped'], s['enabled'], s['confirmed_root'], s['offered']), ('', [], ['pack'], True, '', ''))
        self.assertNotIn('extra', s)
        self.assertIsNot(guide.new_state()['ms'], guide.new_state()['ms'])                                   # no shared mutable defaults
        self.assertEqual(config.DEFAULTS['guide'], guide.DEFAULT_STATE)                                      # the settings default and the logic agree

    def test_milestones_are_sticky_and_idempotent(self):
        s = guide.advance(guide.new_state(path='quick'), F(**LIVE)); self.assertEqual(s['ms'], ['session'])
        self.assertEqual(guide.advance(s, F(**LIVE)), s)                                                     # idempotent
        self.assertEqual(guide.advance(s, F())['ms'], ['session'])                                           # the session ending does not undo it
        s2 = guide.advance(s, F(**LIVE, requests=40, game_running=True, game_seen=True)); self.assertEqual(s2['ms'], ['session', 'game'])
        s3 = guide.advance(s2, F()); self.assertEqual(s3['ms'], ['session', 'game', 'after'])               # proxy gone after the game
        self.assertEqual(guide.advance(s3, F(**LIVE))['ms'], ['session', 'game', 'after'])                  # a new session does not clear it (Start over does)

    def test_game_milestone_rules(self):
        s = guide.advance(guide.new_state(), F(**LIVE))
        self.assertNotIn('game', guide.advance(s, F(**LIVE, requests=1))['ms'])                              # the Doctor's own check asks for a piece or two
        self.assertNotIn('game', guide.advance(s, F(**LIVE, game_seen=True, requests=0))['ms'])              # game seen but nothing delivered yet
        self.assertIn('game', guide.advance(s, F(**LIVE, game_seen=True, requests=1))['ms'])
        self.assertIn('game', guide.advance(s, F(**LIVE, requests=guide.GAME_REQUESTS))['ms'])               # game program not recognised by name: the traffic proves it
        self.assertNotIn('after', guide.advance(s, F())['ms'])                                               # stopped before any game: not "after"

    def test_after_needs_a_session_and_a_finished_game_or_a_skip(self):
        s = guide.advance(guide.new_state(), F(**LIVE)); s = guide.skip(s, 'game')
        self.assertIn('after', guide.advance(s, F())['ms'])
        self.assertNotIn('after', guide.advance(s, F(**LIVE))['ms'])                                         # still running
        self.assertNotIn('after', guide.advance(guide.skip(guide.new_state(), 'game'), F())['ms'])           # never had a session

    def test_skip_and_restart(self):
        s = guide.new_state(path='offline', confirmed_root='C:\\x', enabled=True, offered='1', ms=['session', 'game'])
        self.assertEqual(guide.skip(s, 'folder')['skipped'], []); self.assertEqual(guide.skip(s, 'bogus')['skipped'], [])
        k = guide.skip(guide.skip(s, 'pack'), 'pack'); self.assertEqual(k['skipped'], ['pack'])
        r = guide.restart(k); self.assertEqual((r['ms'], r['skipped'], r['path'], r['confirmed_root'], r['enabled'], r['offered']), ([], [], 'offline', 'C:\\x', True, '1'))


class ChecklistTests(unittest.TestCase):
    def test_new_user_sees_one_current_step_and_no_pack_step(self):
        rows = guide.evaluate(guide.new_state(), F(configured=False, folder_exists=False, folder_score=0))
        self.assertEqual([r['id'] for r in rows], ['path', 'folder', 'preflight', 'session', 'game', 'after']); self.assertEqual([r['n'] for r in rows], [1, 2, 3, 4, 5, 6])
        self.assertEqual(status(rows), dict(path='current', folder='todo', preflight='todo', session='todo', game='todo', after='todo'))
        self.assertEqual(acts(row(rows, 'path')), ['choose_quick', 'choose_offline'])
        self.assertEqual(sum(r['status'] == 'current' for r in rows), 1)

    def test_quick_path_in_order(self):
        s = guide.new_state(path='quick')
        r = guide.evaluate(s, F(configured=False, folder_exists=False, folder_score=0)); self.assertEqual(status(r)['path'], 'done'); self.assertEqual(status(r)['folder'], 'current'); self.assertEqual(acts(row(r, 'folder')), ['find_folder'])
        r = guide.evaluate(s, F()); self.assertEqual(status(r), dict(path='done', folder='done', preflight='done', session='current', game='todo', after='todo')); self.assertEqual(acts(row(r, 'session')), ['start_session'])
        s = guide.advance(s, F(**LIVE)); r = guide.evaluate(s, F(**LIVE)); self.assertEqual(status(r)['session'], 'done'); self.assertEqual(status(r)['game'], 'current')
        r = guide.evaluate(s, F(**LIVE, game_running=True, game_seen=True)); self.assertIn('Game detected', row(r, 'game')['detail']); self.assertEqual(status(r)['game'], 'current')
        f = F(**LIVE, game_running=True, game_seen=True, requests=300); s = guide.advance(s, f); r = guide.evaluate(s, f)
        self.assertEqual(status(r)['game'], 'done'); self.assertEqual(status(r)['after'], 'current'); self.assertEqual(acts(row(r, 'after')), ['stop_session'])
        s = guide.advance(s, F()); r = guide.evaluate(s, F()); self.assertTrue(guide.all_passed(r)); self.assertEqual({v for v in status(r).values()}, {'done'}); self.assertEqual(acts(row(r, 'after')), ['goto_report'])

    def test_session_stopped_before_playing_asks_to_start_again(self):
        s = guide.advance(guide.new_state(path='quick'), F(**LIVE)); r = guide.evaluate(s, F())
        self.assertEqual(status(r)['game'], 'current'); self.assertEqual(acts(row(r, 'game')), ['start_session']); self.assertIn('not running', row(r, 'game')['detail'])

    def test_game_ran_but_nothing_came_through(self):
        s = guide.advance(guide.new_state(path='quick'), F(**LIVE)); f = F(**LIVE, game_seen=True, requests=0); r = guide.evaluate(s, f)
        self.assertEqual(status(r)['game'], 'current'); self.assertEqual(acts(row(r, 'game')), ['doctor']); self.assertTrue(row(r, 'game')['skippable'])
        r = guide.evaluate(guide.skip(s, 'game'), f); self.assertEqual(status(r)['game'], 'skipped'); self.assertEqual(status(r)['after'], 'current')

    def test_folder_step_states(self):
        s = guide.new_state(path='quick')
        r = guide.evaluate(s, F(configured=False, folder_exists=False, folder_score=0, folder_root='')); self.assertIn('do not know where', row(r, 'folder')['detail'])
        r = guide.evaluate(s, F(folder_exists=False, folder_score=0)); self.assertIn('does not exist', row(r, 'folder')['detail']); self.assertEqual(status(r)['folder'], 'current')
        r = guide.evaluate(s, F(folder_score=0)); self.assertEqual(status(r)['folder'], 'current'); self.assertEqual(acts(row(r, 'folder')), ['find_folder', 'confirm_anyway'])
        same = guide.new_state(path='quick', confirmed_root=BASE['folder_root'].lower() + '\\')                                            # same folder, different spelling
        self.assertEqual(status(guide.evaluate(same, F(folder_score=0)))['folder'], 'done')
        other = guide.new_state(path='quick', confirmed_root='C:\\Elsewhere'); self.assertEqual(status(guide.evaluate(other, F(folder_score=0)))['folder'], 'current')
        for sc, word in ((1, 'not found'), (2, 'not found'), (3, '')):
            d = row(guide.evaluate(s, F(folder_score=sc)), 'folder'); self.assertEqual(d['status'], 'done'); self.assertEqual('not found' in d['detail'], bool(word))   # lenient: a partial match is accepted
        self.assertEqual(status(guide.evaluate(s, F(folder_score=1)))['preflight'], 'done')

    def test_preflight_problems_are_named(self):
        s = guide.new_state(path='quick')
        r = guide.evaluate(s, F(blocked_by='other.exe')); self.assertEqual(status(r)['preflight'], 'current'); self.assertIn('other.exe', row(r, 'preflight')['detail']); self.assertEqual(acts(row(r, 'preflight')), ['doctor'])
        self.assertEqual(status(guide.evaluate(s, F(free_gib=1.5)))['preflight'], 'current'); self.assertEqual(status(guide.evaluate(s, F(free_gib=3.0)))['preflight'], 'done')
        self.assertEqual(status(guide.evaluate(guide.new_state(path='offline'), F(free_gib=10.0)))['preflight'], 'current')                       # the offline copy needs room
        self.assertEqual(status(guide.evaluate(s, F(free_gib=None)))['preflight'], 'done')                                                         # unknown yet: not a problem
        r = guide.evaluate(s, F(game_running=True)); self.assertEqual(status(r)['preflight'], 'current'); self.assertIn('game is running', row(r, 'preflight')['detail'])
        self.assertEqual(status(guide.evaluate(s, F(**LIVE, game_running=True)))['preflight'], 'done')                                           # session already up: fine
        self.assertEqual(status(guide.evaluate(s, F(configured=False, folder_exists=False, folder_score=0)))['preflight'], 'todo')

    def test_offline_path_pack_step(self):
        s = guide.new_state(path='offline'); r = guide.evaluate(s, F())
        self.assertEqual([x['id'] for x in r], ['path', 'folder', 'preflight', 'pack', 'session', 'game', 'after']); self.assertEqual(status(r)['pack'], 'current'); self.assertTrue(row(r, 'pack')['skippable'])
        r = guide.evaluate(s, F(pack_total=1000, pack_stored=10, mirror_alive=True, pack_run_done=25, pack_run_total=990)); self.assertEqual(status(r)['pack'], 'running'); self.assertEqual(status(r)['session'], 'current')   # a long download does not hold up the rest
        self.assertIn('25 of 990 pieces in this run', row(r, 'pack')['detail']); self.assertIn('Downloading...', row(guide.evaluate(s, F(mirror_alive=True)), 'pack')['detail'])      # no live numbers yet: still sensible
        r = guide.evaluate(s, F(pack_total=1000, pack_stored=1000)); self.assertEqual(status(r)['pack'], 'done'); self.assertEqual(acts(row(r, 'pack')), [])
        r = guide.evaluate(guide.skip(s, 'pack'), F()); self.assertEqual(status(r)['pack'], 'skipped'); self.assertEqual(status(r)['session'], 'current')
        self.assertNotIn('pack', [x['id'] for x in guide.evaluate(guide.new_state(path='quick'), F())])

    def test_exactly_one_current_step_whatever_the_facts(self):
        import itertools
        for path, live, game, req, run in itertools.product(('', 'quick', 'offline'), (False, True), (False, True), (0, 3, 50), (False, True)):
            f = F(**(LIVE if live else {}), game_seen=game, requests=req, game_running=run, mirror_alive=run); s = guide.advance(guide.new_state(path=path), f)
            rows = guide.evaluate(s, f); cur = [r['id'] for r in rows if r['status'] == 'current']
            self.assertLessEqual(len(cur), 1, (path, live, game, req, run, cur)); self.assertEqual(len(cur) == 0, guide.all_passed(rows), (path, live, game, req, run))
            self.assertEqual([r['n'] for r in rows], list(range(1, len(rows) + 1)))


class FolderFinderTests(unittest.TestCase):
    def test_parse_libraryfolders(self):
        vdf = '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"C:\\\\Program Files (x86)\\\\Steam"\n\t\t"label"\t\t""\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"D:\\\\SteamLibrary"\n\t}\n}\n'
        self.assertEqual(guide.parse_libraryfolders(vdf), ['C:\\Program Files (x86)\\Steam', 'D:\\SteamLibrary']); self.assertEqual(guide.parse_libraryfolders(''), []); self.assertEqual(guide.parse_libraryfolders(None), [])

    def test_score_folder(self):
        root = os.path.join(TMP, 'score'); self.assertEqual(guide.score_folder(os.path.join(root, 'nope')), 0); self.assertEqual(guide.score_folder(''), 0); self.assertEqual(guide.score_folder(None), 0)
        self.assertEqual(guide.score_folder(game(os.path.join(root, 'empty'), dirs=(), lists=False)), 0)
        self.assertEqual(guide.score_folder(game(os.path.join(root, 'exe_only'), dirs=(), lists=False, exe=paths.GAME_EXES[0])), 1)
        self.assertEqual(guide.score_folder(game(os.path.join(root, 'dirs_only'), dirs=('cod26',), lists=False)), 2)
        self.assertEqual(guide.score_folder(game(os.path.join(root, 'full'), dirs=('sp26',), lists=True)), 3)

    def test_finds_the_game_wherever_it_is_and_whatever_the_folder_is_called(self):
        t = os.path.join(TMP, 'find'); steam = os.path.join(t, 'steamroot'); lib = os.path.join(t, 'OtherLib')
        os.makedirs(os.path.join(steam, 'steamapps')); touch(os.path.join(steam, 'steamapps', 'libraryfolders.vdf'), '"libraryfolders" { "1" { "path" "%s" } }' % lib.replace('\\', '\\\\'))
        game(os.path.join(lib, 'steamapps', 'common', 'Whatever Name'))                                     # in a Steam library that is only known from libraryfolders.vdf
        game(os.path.join(t, 'drive', 'Games', 'my own folder'))                                            # under Games
        game(os.path.join(t, 'drive', 'Stuff', 'Title'), dirs=('cod26',), lists=False)                      # two levels under the drive root, no chunk lists
        game(os.path.join(t, 'drive', 'oldgame'), dirs=(), lists=False, exe=paths.GAME_EXES[0])             # only a game program name matches
        game(os.path.join(t, 'drive', 'Program Files', 'Pub', 'Game'))                                       # Program Files, one vendor level down
        os.makedirs(os.path.join(t, 'drive', 'decoy', 'inner')); touch(os.path.join(t, 'drive', 'decoy', 'readme.txt'))
        found = guide.find_game_folders(drives=[os.path.join(t, 'drive')], steam_roots=[steam])
        got = {os.path.normcase(c['path']): c for c in found}; want = lambda *p: os.path.normcase(os.path.normpath(os.path.join(t, *p)))
        for p, sc in ((('OtherLib', 'steamapps', 'common', 'Whatever Name'), 3), (('drive', 'Games', 'my own folder'), 3), (('drive', 'Stuff', 'Title'), 2),
                      (('drive', 'oldgame'), 1), (('drive', 'Program Files', 'Pub', 'Game'), 3)):
            self.assertIn(want(*p), got, p); self.assertEqual(got[want(*p)]['score'], sc, p)
        self.assertNotIn(want('drive', 'decoy'), got)
        mine = [c for c in found if os.path.normcase(c['path']).startswith(os.path.normcase(t))]; self.assertEqual([c['score'] for c in mine], sorted((c['score'] for c in mine), reverse=True))   # best first
        self.assertEqual(len({os.path.normcase(c['path']) for c in found}), len(found))                       # nothing listed twice
        self.assertIn('looks complete', guide.describe_candidate(got[want('drive', 'Games', 'my own folder')])); self.assertIn('no chunk lists', guide.describe_candidate(got[want('drive', 'Stuff', 'Title')]))

    def test_includes_the_current_setting_and_the_extra_folders_and_never_raises_on_unreadable_roots(self):
        t = os.path.join(TMP, 'cur'); g = game(os.path.join(t, 'g1')); h = game(os.path.join(t, 'g2'))
        with mock.patch.object(paths, 'CONFIGURED', True), mock.patch.object(paths, 'GAME_ROOT', g):
            found = guide.find_game_folders(drives=[os.path.join(t, 'no such drive')], steam_roots=[os.path.join(t, 'no steam')], extra=[h, os.path.join(t, 'ghost')])
        srcs = {os.path.normcase(c['path']): c['source'] for c in found}; self.assertEqual(srcs[os.path.normcase(g)], 'current setting'); self.assertEqual(srcs[os.path.normcase(h)], 'given')

    def test_search_gives_up_at_the_deadline_with_what_it_has(self):
        t = os.path.join(TMP, 'slow'); [game(os.path.join(t, 'Games', f'g{i}')) for i in range(30)]
        ticks = iter(range(0, 10 ** 6, 3))                                                                  # every clock read is 3 s later
        found = guide.find_game_folders(drives=[t], steam_roots=[], deadline_s=4.0, clock=lambda: next(ticks))
        self.assertLess(len([c for c in found if c['source'] == 'Games']), 30)                              # stopped early, no exception

    def test_fixed_drives_and_steam_dirs_do_not_raise(self):
        self.assertIsInstance(guide.fixed_drives(), list); self.assertIsInstance(guide.steam_common_dirs(), list); self.assertEqual(guide.steam_common_dirs([]), [])


class FirstRunTests(unittest.TestCase):
    def test_a_game_folder_without_chunk_lists_does_not_block_starting_a_session(self):
        # the guide accepts such a folder (the quick fix does not need the lists), so the session start must not refuse it either
        g = game(os.path.join(TMP, 'nolists'), dirs=('sp26',), lists=False); self.addCleanup(paths.reload)
        paths.reload(override=dict(game_root=g)); v = {r['name']: r for r in paths.validate()}
        self.assertEqual(v['Game folder']['level'], 'ok'); self.assertEqual(v['CDN chunk lists']['level'], 'warn'); self.assertIn('proxy still works', v['CDN chunk lists']['detail'])
        self.assertEqual([r['name'] for r in paths.validate() if r['level'] == 'fail'], [])
        paths.reload(override=dict(game_root=os.path.join(TMP, 'ghost'))); self.assertEqual([r['name'] for r in paths.validate() if r['level'] == 'fail'], ['Game folder'])     # a missing folder still does


    def test_doctor_treats_a_missing_mirror_as_normal_unless_the_profile_needs_it(self):
        empty = os.path.join(TMP, 'nomirror'); os.makedirs(empty); cfg = copy.deepcopy(config.DEFAULTS)
        with mock.patch.object(paths, 'MIRROR', empty):
            r = doctor.check_mirror(cfg); self.assertEqual(r['level'], 'info'); self.assertIn('no mirror yet', r['detail'])
            off = copy.deepcopy(config.DEFAULTS); off['profile'] = 'Slow link - offline mirror'; self.assertEqual(doctor.check_mirror(off)['level'], 'fail')        # an offline profile serves from the mirror only
            cap = copy.deepcopy(config.DEFAULTS); cap['profile'] = 'Capture'; cap['proxy']['origin'] = False; self.assertEqual(doctor.check_mirror(cap)['level'], 'info')


if __name__ == '__main__':
    unittest.main()
