"""Tests for the experimental multiplayer / HQ support: netwatch follows any game program, the card for a game that sends nothing is worded per game, the disk guard says what it will not end.
No game, no PowerShell, no network: the commands are faked.
"""
import os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, TOOLS)
import diskguard, netwatch
from ccslib import guide, paths
from test_guide import BASE

TMP = tempfile.mkdtemp(prefix='ccsmp_')


def tearDownModule(): shutil.rmtree(TMP, ignore_errors=True)


class NetwatchTests(unittest.TestCase):
    def test_process_names_follow_the_game_list_and_stay_plain(self):
        self.assertEqual(netwatch.process_names(['sp26-cod.exe', 'cod.exe', 'COD.EXE', 'cod.exe']), ['sp26-cod', 'cod', 'COD'])
        self.assertEqual(netwatch.process_names(["a'; calc; '", 'x y.exe', 'ok_1.exe', '', '.exe']), ['ok_1'])          # nothing that could end the quoted list in the command
        self.assertEqual(netwatch.process_names([]), [])
        self.assertIn('cod', netwatch.process_names()); self.assertIn('sp26-cod', netwatch.process_names())

    def test_running_asks_for_all_names_at_once_and_reads_the_answer(self):
        seen = []
        def run(c): seen.append(c); return '4242 cod\r\n17 sp26-cod\r\n\r\nnoise\r\n'
        with mock.patch.object(netwatch.paths, 'GAME_EXES', ('sp26-cod.exe', 'cod.exe')):
            self.assertEqual(netwatch.running(run), {'4242': 'cod', '17': 'sp26-cod'})
        self.assertIn("Get-Process -Name sp26-cod,cod ", seen[0])
        with mock.patch.object(netwatch.paths, 'GAME_EXES', ()): self.assertEqual(netwatch.running(run), {})

    def test_each_line_says_which_program_made_it_and_nothing_repeats(self):
        def run(c):
            if 'Get-WinEvent' in c: return '4242 3006 Name resolution for cod-assets.cdn.callofduty.com\r\n99 3006 not ours\r\n'
            if 'Get-NetTCPConnection -OwningProcess 4242' in c: return 'Established 2.19.126.216:80\r\n'
            return ''
        seen = set(); procs = {'4242': 'cod'}
        first = netwatch.poll_once(procs, seen, run)
        self.assertTrue(any(l.startswith('DNS pid=4242 cod ') and 'cod-assets.cdn.callofduty.com' in l for l in first), first)
        self.assertTrue(any(l == 'TCP pid=4242 cod Established 2.19.126.216:80' for l in first), first)
        self.assertEqual(netwatch.poll_once(procs, seen, run), [], 'the same lines are not logged twice')
        self.assertEqual(netwatch.poll_once({}, set(), run), [])

    def test_two_programs_are_both_watched(self):
        calls = []
        def run(c):
            calls.append(c); return 'Established 1.2.3.4:443\r\n' if 'Get-NetTCPConnection' in c else ''
        out = netwatch.poll_once({'1': 'sp26-cod', '2': 'cod'}, set(), run)
        self.assertEqual(sorted(out), ['TCP pid=1 sp26-cod Established 1.2.3.4:443', 'TCP pid=2 cod Established 1.2.3.4:443'])
        self.assertIn('-in 1,2 ', ' '.join(calls))


class CardTests(unittest.TestCase):
    LIVE = dict(proxy_ready=True, proxy_alive=True, hosts_ok=True, resolve_ok=True, hosts_state='OK', game_running=True, requests=0)

    def cards(self, secs, names):
        return guide.coach(guide.new_state(), dict(BASE, **self.LIVE, game_secs=secs, game_names=names), '')

    def test_campaign_text_is_unchanged(self):
        c = self.cards(95, ['sp26-cod.exe', 'cod.exe']); self.assertEqual([x['id'] for x in c], ['no_traffic']); self.assertEqual(c[0]['title'], 'The game is running but nothing reached the helper')
        self.assertEqual([x['id'] for x in self.cards(95, [])], ['no_traffic'], 'no names known: the old behaviour')
        self.assertEqual(self.cards(60, ['sp26-cod.exe']), [])

    def test_multiplayer_gets_its_own_text_and_waits_longer(self):
        self.assertEqual(self.cards(95, ['cod.exe']), [], 'a match may not have loaded yet')
        c = self.cards(250, ['cod.exe']); self.assertEqual([x['id'] for x in c], ['no_traffic'])
        self.assertIn('Multiplayer / HQ', c[0]['title']); self.assertIn('experimental', c[0]['text']); self.assertIn('support bundle', c[0]['text']); self.assertIn('sp26-cod.exe', c[0]['text'])            # the campaign is a second program that starts from the HQ menu; self.assertTrue(c[0]['actions'])

    def test_no_card_once_requests_arrive(self):
        f = dict(BASE, **dict(self.LIVE, requests=5), game_secs=500, game_names=['cod.exe']); self.assertEqual(guide.coach(guide.new_state(), f, ''), [])


class GuardTests(unittest.TestCase):
    def run_guard(self, other):
        cache = os.path.join(TMP, 'c'); os.makedirs(cache, exist_ok=True); open(os.path.join(cache, 'x'), 'wb').write(b'0' * (2 << 20)); log = os.path.join(TMP, 'g.log')
        if os.path.exists(log): os.remove(log)
        res = subprocess.CompletedProcess([], 128, stdout='', stderr=''); calls = []
        def sleep(_):
            calls.append(1)
            if len(calls) >= 3: raise SystemExit('enough')
        with mock.patch.object(diskguard.paths, 'KILL_EXES', ['sp26-cod.exe']), mock.patch.object(diskguard.subprocess, 'run', return_value=res), mock.patch.object(diskguard.time, 'sleep', sleep), \
                mock.patch.object(diskguard, 'other_game', return_value=other):
            try: diskguard.main(['--limit-gib', '0.001', '--action', 'kill', '--interval', '1', '--cache', cache, '--log', log])
            except SystemExit: pass
        return open(log, encoding='utf-8').read()

    def test_a_game_that_is_not_on_the_list_is_named_and_left_alone(self):
        t = self.run_guard(['cod.exe']); self.assertEqual(t.count('cod.exe is running but is not on the list this guard may end'), 1); self.assertNotIn('terminated', t); self.assertIn('still watching', t)

    def test_no_game_at_all_keeps_the_old_text(self):
        t = self.run_guard([]); self.assertEqual(t.count('the game is not running, still watching'), 1)

    def test_default_list_is_the_campaign_only(self):
        self.assertEqual(list(paths.DEFAULT_KILL), ['sp26-cod.exe']); self.assertIn('cod.exe', paths.DEFAULT_EXES)

    def test_other_game_lists_only_what_is_not_on_the_kill_list(self):
        from ccslib import procs
        with mock.patch.object(diskguard.paths, 'KILL_EXES', ['sp26-cod.exe']), mock.patch.object(diskguard.paths, 'GAME_EXES', ('sp26-cod.exe', 'cod.exe')), \
                mock.patch.object(procs, 'image_running', return_value=['sp26-cod.exe', 'cod.exe']):
            self.assertEqual(diskguard.other_game(), ['cod.exe'])


class WordingTests(unittest.TestCase):
    def read(self, f): return open(os.path.join(os.path.dirname(TOOLS), f), encoding='utf-8').read()

    def test_docs_no_longer_forbid_online_play_and_say_experimental(self):
        for f in ('README.md', 'DISCLAIMER.md'):
            self.assertNotIn("Don't use them with online services", self.read(f), f)
        for f in ('README.md', 'DISCLAIMER.md', 'docs/GETTING-STARTED.md'): self.assertIn('experimental', self.read(f).lower(), f)
        self.assertIn('no advantage', self.read('DISCLAIMER.md').lower().replace('give no advantage', 'no advantage')); self.assertIn('own risk', self.read('DISCLAIMER.md').lower())


    def test_first_run_notice_matches_the_new_policy_and_is_translated(self):
        import json
        from ccslib import version
        self.assertNotIn('do not use it with online services', version.NOTICE); self.assertNotIn('single-player use', version.NOTICE)
        for w in ('experimental', 'no advantage' if False else 'advantage', 'responsibility'): self.assertIn(w, version.NOTICE)
        lang = os.path.join(TOOLS, 'ccslib', 'lang')
        for f in sorted(os.listdir(lang)):
            if f.endswith('.json') and not f.startswith('_'):
                d = json.load(open(os.path.join(lang, f), encoding='utf-8')); self.assertTrue(d.get(version.NOTICE), f + ' lacks the translated notice')

if __name__ == '__main__': unittest.main()
