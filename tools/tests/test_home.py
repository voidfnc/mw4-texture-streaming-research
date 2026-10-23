"""The Home screen's view model (ccslib/home.py): every state, the actions it offers, and the wording. No window needed."""
import re, sys, unittest
import test_ccs                                    # sets CCS_WORK before ccslib is imported
sys.path.insert(0, test_ccs.TOOLS)
from ccslib import guide, home

LIVE = dict(proxy_ready=True, proxy_alive=True, hosts_ok=True, resolve_ok=True)
BANNED = re.compile(r'repack|emulator|DODI|forum|rutracker|torrent|a user (on|report)|user report|users? (reported|found)', re.I)
JARGON = re.compile(r'\b(hosts|proxy|resolver|mirror|cdn|chunks?|tiers?|uac|workers|xpak)\b', re.I)
FOUND = [dict(path=r'D:\Games\Modern Warfare 4', score=3, source='Games')]


def facts(**kw):
    f = dict(configured=True, folder_root=r'D:\Games\Modern Warfare 4', folder_exists=True, folder_score=3, game_setup='ok', blocked_by='', port=80, free_gib=200.0, game_running=False, proxy_ready=False,
             proxy_alive=False, hosts_ok=False, resolve_ok=False, hosts_state='ABSENT', requests=0, pack_total=None, pack_stored=None, mirror_alive=False, pack_run_done=0, pack_run_total=None,
             last_stat=None, game_secs=0, game_seen=False, stat=None, secs=0, mibps=None, spark=[])
    f.update(kw); return f


def state(**kw): return guide.new_state(path='quick', **kw)


def scenarios():
    """name -> view, one per state Home can be in."""
    live_stat = dict(req=4212, mirror=0, ok=4198, err=0, retry=3)
    return {
        'find searching': home.build(guide.new_state(), facts(configured=False, folder_exists=False, folder_score=0), found=None),
        'find found': home.build(guide.new_state(), facts(configured=False, folder_exists=False, folder_score=0), found=FOUND),
        'find none': home.build(guide.new_state(), facts(configured=False, folder_exists=False, folder_score=0), found=[]),
        'find odd folder': home.build(guide.new_state(), facts(folder_score=0)),
        'find missing folder': home.build(guide.new_state(), facts(folder_exists=False, folder_score=0)),
        'choose': home.build(guide.new_state(), facts()),
        'choose offline low space': home.build(guide.new_state(), facts(free_gib=30.0), pick='offline'),
        'setup': home.build(state(), facts(game_setup='needed')),
        'ready': home.build(state(), facts()),
        'ready busy': home.build(state(), facts(), busy=True),
        'starting': home.build(state(), facts(proxy_alive=True), starting=True),
        'waiting': home.build(state(ms=['session']), facts(**LIVE)),
        'playing': home.build(state(ms=['session', 'game']), facts(game_running=True, requests=4212, stat=live_stat, secs=1062, mibps=7.6, spark=[1, 2, 3], **LIVE)),
        'game closed': home.build(state(ms=['session', 'game']), facts(requests=4212, stat=live_stat, **LIVE)),
        'finished': home.build(state(ms=['session', 'game', 'after'], summary=dict(req=4543, err=0, secs=2640)), facts()),
        'problem refused': home.build(state(), facts(), note='Session NOT ready: hosts override not applied: permission denied'),
        'problem cancelled': home.build(state(), facts(), note='the UAC prompt was cancelled'),
        'problem port': home.build(state(), facts(blocked_by='nginx.exe')),
        'problem disk': home.build(state(), facts(free_gib=0.5)),
        'problem game open': home.build(state(), facts(game_running=True)),
        'problem hosts lost': home.build(state(ms=['session']), facts(proxy_alive=True, proxy_ready=True)),
        'playing with alert': home.build(state(ms=['session', 'game']), facts(game_running=True, requests=10, free_gib=3.0, **LIVE)),
        'waiting with alert': home.build(state(ms=['session']), facts(game_running=True, game_secs=120, requests=0, **LIVE)),
    }


class HomeViewTests(unittest.TestCase):
    def test_every_state_maps_to_the_expected_mode(self):
        modes = {k: v['mode'] for k, v in scenarios().items()}
        self.assertEqual(modes, {'find searching': 'find', 'find found': 'find', 'find none': 'find', 'find odd folder': 'find', 'find missing folder': 'find', 'choose': 'choose', 'choose offline low space': 'choose',
                                 'setup': 'setup', 'ready': 'ready', 'ready busy': 'ready', 'starting': 'starting', 'waiting': 'waiting', 'playing': 'playing', 'game closed': 'playing', 'finished': 'finished',
                                 'problem refused': 'problem', 'problem cancelled': 'problem', 'problem port': 'problem', 'problem disk': 'problem', 'problem game open': 'problem', 'problem hosts lost': 'problem',
                                 'playing with alert': 'playing', 'waiting with alert': 'waiting'})

    def test_layouts_and_steps(self):
        s = scenarios()
        for k in ('find found', 'choose', 'setup'): self.assertEqual(s[k]['layout'], 'wizard', k)
        self.assertEqual([s[k]['wizard'] for k in ('find found', 'choose', 'setup')], [(1, 3), (2, 3), (3, 3)])
        for k in ('ready', 'starting', 'waiting', 'playing', 'finished', 'problem refused'): self.assertEqual(s[k]['layout'], 'hero', k)
        self.assertEqual([s[k]['steps'][1] for k in ('ready', 'starting', 'waiting', 'playing', 'finished')], [1, 1, 2, 2, 4])
        self.assertEqual(s['ready']['steps'][0], home.STEP_LABELS); self.assertIsNone(s['problem refused']['steps'])

    def test_the_first_run_screens(self):
        s = scenarios()
        self.assertEqual(s['find searching']['primary'][0], 'find_folder'); self.assertIn('looking', s['find searching']['sub'])
        f = s['find found']; self.assertEqual(f['primary'][:2], ('use_found', 'Yes, use this one')); self.assertEqual(f['secondary'], [('find_folder', 'Choose another folder')])
        self.assertEqual((f['folder']['path'], f['folder']['note'], f['folder']['ok']), (r'D:\Games\Modern Warfare 4', 'Looks complete', True))
        self.assertIn("couldn't find", s['find none']['headline']); self.assertEqual(s['find none']['primary'][0], 'find_folder')
        self.assertEqual(s['find odd folder']['secondary'], [('confirm_anyway', 'Use it anyway')]); self.assertIn("doesn't look right", s['find odd folder']['headline'])
        self.assertIn("isn't there", s['find missing folder']['headline'])
        c = s['choose']; self.assertEqual([x['id'] for x in c['choices']], ['quick', 'offline']); self.assertEqual([x['selected'] for x in c['choices']], [True, False]); self.assertEqual(c['primary'][0], 'choose_quick')
        self.assertEqual(c['choices'][0]['tag'], 'Recommended')
        o = s['choose offline low space']; self.assertEqual([x['selected'] for x in o['choices']], [False, True]); self.assertEqual(o['primary'][0], 'choose_offline')
        self.assertIn(('Not enough free space on this drive', 'bad'), o['choices'][1]['bullets']); self.assertNotIn(('Not enough free space on this drive', 'bad'), c['choices'][1]['bullets'])
        self.assertEqual(s['setup']['primary'][0], 'game_setup'); self.assertEqual(s['setup']['secondary'], [('help', 'What does this do?')])

    def test_a_folder_the_user_confirmed_is_accepted(self):
        f = facts(folder_score=0); st = state(confirmed_root=f['folder_root']); self.assertEqual(home.build(st, f)['mode'], 'ready')

    def test_the_main_screen_flow(self):
        s = scenarios()
        r = s['ready']; self.assertEqual(r['primary'], ('turn_on', 'Turn on HD textures', 'power')); self.assertEqual(r['ring']['kind'], 'off'); self.assertEqual([c['title'] for c in r['cards']], ['Game folder', 'Textures load', 'Free space'])
        self.assertEqual(r['cards'][0]['value'], 'D:\\Games\\Modern Warfare 4'); self.assertEqual(r['cards'][2]['value'], '200 GiB on D:'); self.assertEqual(r['footer'], ('ok', 'Everything checks out'))
        self.assertTrue(s['ready busy']['busy']); st = s['starting']; self.assertEqual((st['ring']['kind'], st['busy']), ('work', True)); self.assertEqual(st['primary'][1], 'Turning on...')
        w = s['waiting']; self.assertEqual((w['ring']['kind'], w['waiting']), ('on', True)); self.assertEqual(w['secondary'], [('turn_off', 'Turn off')]); self.assertIsNone(w['primary'])
        p = s['playing']; self.assertEqual((p['ring']['kind'], p['ring']['big'], p['ring']['small']), ('full', '4,212', 'textures delivered')); self.assertEqual(p['secondary'], [('turn_off', 'Turn off when you are done')])
        self.assertEqual([(k['title'], k['value']) for k in p['kpis']], [('Speed', '7.6'), ('Failed', '0'), ('Loaded from', 'The internet')]); self.assertEqual(p['spark'], [1, 2, 3]); self.assertIn('17:42', p['sub'])
        self.assertEqual(s['game closed']['headline'], 'Game closed'); self.assertEqual(s['game closed']['secondary'], [('turn_off', 'Turn off')])
        fi = s['finished']; self.assertEqual(fi['primary'][:2], ('done', 'Done')); self.assertEqual([a for a, _ in fi['secondary']], ['open_report', 'abtest']); self.assertIn('4,543 textures in about 44 min and every one was delivered', fi['sub'])

    def test_the_source_of_the_textures_is_shown_plainly(self):
        k = lambda mir, ok: home.build(state(ms=['session', 'game']), facts(game_running=True, requests=5, stat=dict(req=5, mirror=mir, ok=ok, err=0, retry=0), **LIVE))['kpis'][2]['value']
        self.assertEqual((k(0, 5), k(5, 5), k(2, 5)), ('The internet', 'Your offline copy', 'Offline copy and internet'))

    def test_problems_say_what_happened_and_offer_a_fix_or_nothing_to_press(self):
        s = scenarios()
        a = s['problem refused']; self.assertEqual(a['headline'], 'Windows blocked the change'); self.assertEqual(a['alert']['title'], 'Windows refused to change the hosts file'); self.assertEqual(a['ring']['kind'], 'warn')
        self.assertEqual([x[0] for x in a['alert']['actions']], ['turn_on', 'open_check']); self.assertEqual(a['footer'][0], 'warn')
        self.assertEqual(s['problem cancelled']['headline'], "Windows didn't get a yes"); self.assertEqual(s['problem cancelled']['alert']['actions'][0][0], 'turn_on')
        self.assertIn('port 80', s['problem port']['alert']['title']); self.assertIn('nginx.exe', s['problem port']['alert']['text']); self.assertEqual(s['problem port']['alert']['actions'], [('open_check', 'Check my PC')])
        self.assertEqual(s['problem disk']['headline'], 'Disk space is low'); self.assertEqual(s['problem disk']['alert']['title'], 'Not much free space'); self.assertEqual(s['problem disk']['alert']['actions'], [])
        self.assertEqual(s['problem game open']['headline'], 'The game is already running')
        self.assertEqual(s['problem hosts lost']['headline'], 'The redirect went missing'); self.assertEqual([x[0] for x in s['problem hosts lost']['alert']['actions']], ['apply_hosts', 'open_check'])
        pa = s['playing with alert']; self.assertEqual(pa['alert']['id'], 'disk_low'); self.assertEqual(pa['footer'][0], 'warn')
        wa = s['waiting with alert']; self.assertEqual(wa['alert']['id'], 'no_traffic'); self.assertEqual(wa['alert']['actions'], [('open_check', 'Check my PC')]); self.assertIn('starting', wa['sub'])

    def test_old_problems_that_cleared_do_not_block_anything(self):
        self.assertEqual(home.build(state(), facts(), note='')['mode'], 'ready')
        self.assertEqual(home.build(state(), facts(), note='some unrelated message')['mode'], 'ready')

    def test_every_action_a_view_offers_is_one_the_window_handles(self):
        seen = set()
        for k, v in scenarios().items():
            acts = ([v['primary'][0]] if v['primary'] else []) + [a for a, _ in v['secondary']] + [a for a, _ in v['links']] + [c['action'] for c in v['cards'] if c['action']]
            if v['alert']: acts += [a for a, _ in v['alert']['actions']]
            acts += ['pick_' + c['id'] for c in v['choices']]
            for a in acts: self.assertIn(a, home.ACTIONS, f'{k}: {a}'); seen.add(a)
        self.assertTrue({'turn_on', 'turn_off', 'find_folder', 'use_found', 'choose_quick', 'game_setup', 'open_check', 'done', 'open_report', 'abtest', 'apply_hosts'} <= seen)

    def test_wording_is_clean_everywhere(self):
        for k, v in scenarios().items():
            for text in home.strings(v): self.assertIsNone(BANNED.search(text), f'{k}: {text}')

    def test_the_main_texts_use_no_jargon(self):
        for k, v in scenarios().items():
            if v['alert']: continue                                          # the problem cards may name the thing that is wrong
            for text in home.strings(v): self.assertIsNone(JARGON.search(text), f'{k}: {text}')

    def test_helpers(self):
        self.assertEqual(home.fmt_dur(0), '0:00'); self.assertEqual(home.fmt_dur(1062), '17:42'); self.assertEqual(home.fmt_dur(3725), '1:02:05'); self.assertEqual(home.fmt_dur(None), '0:00')
        self.assertEqual(home.short_path(r'D:\Games\Modern Warfare 4'), 'D:\\Games\\Modern Warfare 4'); self.assertEqual(home.short_path(r'C:\Program Files (x86)\Steam\steamapps\common\Modern Warfare 4'), 'C:\\...\\common\\Modern Warfare 4')
        self.assertEqual(home.short_path(''), '.')
        t = home.summary_text; self.assertIn('every one was delivered', t(dict(req=10, err=0, secs=30))); self.assertNotIn('in about', t(dict(req=10, err=0, secs=30))); self.assertIn('3 requests failed', t(dict(req=10, err=3, secs=120)))
        self.assertIn("Nothing reached", t(dict(req=0, err=0, secs=1))); self.assertEqual(t({}), 'The session is over.')

    def test_a_bad_state_still_gives_a_view(self):
        v = home.build(None, {}); self.assertIn(v['mode'], ('find', 'choose', 'ready', 'setup'))                    # nothing known: the first-run screen, not an exception
        v = home.build(dict(path='nonsense', ms='x'), facts()); self.assertEqual(v['mode'], 'choose')

    # ---------------------------------------------------------------- the notice, the settings drawer, the offline-copy page, hover help
    def test_the_notice_comes_before_everything_else(self):
        v = home.build(state(), facts(), notice='Research / proof of concept. Text.'); self.assertEqual((v['mode'], v['layout'], v['wizard']), ('notice', 'wizard', None)); self.assertEqual(v['primary'][:2], ('notice_ok', home.NOTICE_BUTTON))
        self.assertEqual((v['notice'], v['cards'], v['links']), ('Research / proof of concept. Text.', [], [])); self.assertEqual(home.build(state(), facts(configured=False, folder_exists=False, folder_score=0), notice='x')['mode'], 'notice')
        self.assertEqual(home.build(state(), facts(), notice='')['mode'], 'ready')

    def test_the_settings_rows_follow_the_state(self):
        rows = lambda st, f, extra=None: {r['label']: r for s in home.build(st, f, extra=extra)['settings'] for r in s['rows']}
        r = rows(state(), facts(game_setup='ok')); self.assertEqual((r['How textures load']['value'], r['Offline copy']['value'], r['One-time game setup']['value'], r['Reduce motion']['value']), ('While I play', 'Not downloaded', 'Done', 'Off'))
        self.assertEqual((r['How textures load']['action'], r['Offline copy']['action'], r['Advanced mode']['action'], r['One-time game setup']['action']), ('switch_path', 'open_download', 'open_advanced', ''))
        n = rows(guide.new_state(path='offline'), facts(game_setup='needed'), dict(motion=True, pack='41% downloaded')); self.assertEqual((n['How textures load']['value'], n['Offline copy']['value'], n['One-time game setup']['action'], n['Reduce motion']['value']), ('From my offline copy', '41% downloaded', 'game_setup', 'On'))
        self.assertEqual(rows(state(), facts(), dict(system_motion=True))['Reduce motion'], dict(icon='refresh', label='Reduce motion', value='On (Windows setting)', action='', tone=''))
        self.assertEqual([s['title'] for s in home.build(state(), facts())['settings']], ['Textures', 'Game', 'Help', 'Look and feel', 'Advanced'])

    def test_hover_help_covers_the_ring_cards_and_numbers(self):
        h = home.help_for(scenarios()['ready']); self.assertIn('Press the button', h['ring']); self.assertEqual(len(h['cards']), 3); self.assertTrue(all(h['cards'])); self.assertIn('turn_on', h['buttons'])
        p = home.help_for(scenarios()['playing']); self.assertEqual(sorted(p['kpis']), ['Failed', 'Loaded from', 'Speed']); self.assertTrue(all(p['kpis'].values()))
        for kind in ('off', 'work', 'on', 'full', 'warn', 'ok'): self.assertTrue(home.HELP['ring'][kind], kind)
        for text in [h['ring'], h['footer'], h['steps']] + list(h['buttons'].values()) + h['cards'] + list(p['kpis'].values()): self.assertIsNone(BANNED.search(text), text); self.assertIsNone(JARGON.search(text), text)

    def test_the_offline_copy_text_for_the_settings_row(self):
        plan = lambda **kw: dict(total=dict(chunks=1000, gib=80.0, stored=kw.get('stored', 0), stored_gib=0, pending=kw.get('pending', 1000), pending_gib=80.0), fits=True, free_gib=400.0, need_gib=80.0)
        self.assertEqual(home.pack_text(None), 'Not downloaded'); self.assertEqual(home.pack_text(plan()), 'Not downloaded'); self.assertEqual(home.pack_text(plan(stored=410, pending=590)), '41% downloaded')
        self.assertEqual(home.pack_text(plan(stored=1000, pending=0)), 'Complete'); self.assertEqual(home.pack_text(plan(stored=410, pending=590), dict(queued=590, ok=100), True), '51% downloaded'); self.assertEqual(home.pack_text(dict(error='x')), 'Not downloaded')

    def test_the_offline_copy_page_in_every_state(self):
        plan = lambda stored=0, pending=1000, fits=True: dict(total=dict(chunks=1000, gib=80.0, stored=stored, stored_gib=0.0, pending=pending, pending_gib=80.0 * pending / 1000), fits=fits, free_gib=400.0, need_gib=80.0)
        d = home.download_view; run = dict(queued=590, ok=100, fail=0, left=490, now=1000.0, started=900.0, mibps=9.4, state='running')
        self.assertEqual(d(None)['mode'], 'loading'); self.assertEqual(d(None)['headline'], 'Working out the size...')
        i = d(plan()); self.assertEqual((i['mode'], i['primary'][:2], i['editable'], i['bar']), ('idle', ('pack_start', 'Start the download'), True, None)); self.assertIn('80 GB to download', i['sub']); self.assertEqual(i['ring']['small'], '80 GB')
        p = d(plan(410, 590)); self.assertEqual((p['mode'], p['primary'][:2], p['ring']['big']), ('paused', ('pack_start', 'Resume'), '41%')); self.assertEqual(p['secondary'], [('pack_verify', 'Check the files')]); self.assertEqual(p['bar']['left'], '410 of 1,000 pieces')
        r = d(plan(410, 590), run, True); self.assertEqual((r['mode'], r['primary'][:2], r['editable'], r['ring']['big']), ('running', ('pack_pause', 'Pause'), False, '51%')); self.assertEqual(r['bar']['left'], '510 of 1,000 pieces'); self.assertEqual(r['bar']['right'], 'About 8 min left at 9.4 MB/s')
        q = d(plan(), dict(run, state='quota-wait'), True); self.assertEqual((q['mode'], q['headline']), ('waiting', "Paused for today's limit")); self.assertEqual(d(plan(), dict(run, state='offline-wait'), True)['headline'], 'Waiting for the internet')
        done = d(plan(1000, 0)); self.assertEqual((done['mode'], done['primary'][:2], done['ring']['kind']), ('done', ('pack_offline', 'Use only this copy'), 'ok')); self.assertIn('1,000 pieces (80 GB)', done['sub'])
        c = d(plan(410, 590), None, False, dict(done=250, total=1000, bad=1), True); self.assertEqual((c['mode'], c['editable'], c['ring']['big']), ('checking', False, '25%')); self.assertIn('Problems so far: 1', c['sub'])
        e = d(dict(error='no lists')); self.assertEqual((e['mode'], e['alert']['id']), ('error', 'plan')); self.assertEqual(d(dict(total=dict(chunks=0, gib=0, stored=0, pending=0)))['alert']['id'], 'nolists')
        n = d(plan(fits=False)); self.assertEqual(n['alert']['id'], 'nospace'); self.assertIsNone(n['primary']); self.assertEqual(n['footer'][0], 'warn'); self.assertIn('Not enough free space', n['alert']['title'])
        s = d(plan(), scope='custom', level='standard'); self.assertTrue(s['scope']['custom']); self.assertEqual((s['scope']['value'], s['level']['value']), ('', 'standard')); self.assertIn('smaller download', s['level']['note'])
        for view in (i, p, r, q, done, c, e, n, s): self.assertTrue(view['links'] == [('back_home', 'Back to Home')])

    def test_the_offline_copy_page_uses_known_actions_and_clean_wording(self):
        plan = dict(total=dict(chunks=1000, gib=80.0, stored=410, stored_gib=0.0, pending=590, pending_gib=47.0), fits=True, free_gib=400.0, need_gib=80.0); run = dict(queued=590, ok=100, fail=0, left=490, now=1000.0, started=900.0, mibps=9.4, state='running')
        views = [home.download_view(None), home.download_view(plan), home.download_view(plan, run, True), home.download_view(dict(total=dict(chunks=1000, gib=80.0, stored=1000, stored_gib=0, pending=0, pending_gib=0), fits=True, free_gib=1.0)),
                 home.download_view(dict(error='x')), home.download_view(plan, None, False, dict(done=1, total=2, bad=0), True)]
        for v in views:
            acts = ([v['primary'][0]] if v['primary'] else []) + [a for a, _ in v['secondary']] + [a for a, _ in v['links']] + [f"set_scope_{o}" for o, _ in v['scope']['options']] + [f"set_level_{o}" for o, _ in v['level']['options']]
            if v['alert']: acts += [a for a, _ in v['alert']['actions']]
            for a in acts: self.assertIn(a, home.ACTIONS, a)
            texts = [v['headline'], v['sub'], v['footer'][1], v['level']['note'], v['ring']['small']] + [x[1] for x in v['secondary']] + ([v['primary'][1]] if v['primary'] else []) + ([v['bar']['left'], v['bar']['right']] if v['bar'] else [])
            for t in texts: self.assertIsNone(BANNED.search(t), t)
            if not v['alert']:
                for t in texts: self.assertIsNone(JARGON.search(t), t)

    def test_every_view_text_including_the_settings_is_clean(self):
        for k, v in scenarios().items():
            for text in home.strings(v): self.assertIsNone(BANNED.search(text), f'{k}: {text}')
        self.assertIsNone(BANNED.search(home.NOTICE_BUTTON))


if __name__ == '__main__':
    unittest.main()
