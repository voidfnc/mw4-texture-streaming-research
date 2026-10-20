"""GUI interaction tests: build the real window (tkinter) and drive its handlers without a human. Dialogs are patched; everything uses the temp
work dir / hosts file from test_ccs (never the real settings, hosts file or game folders)."""
import gc, json, os, shutil, sys, tempfile, time, unittest
import test_ccs                                    # sets CCS_WORK / CCS_HOSTS_PATH before ccslib is imported
from test_ccs import TMP, WIN_HOSTS, put
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog
sys.path.insert(0, test_ccs.TOOLS)
from ccslib import config, doctor, guide, paths, procs, report, session, shortcut, proxyctl
import ccsgui


def setUpModule():
    os.makedirs(TMP, exist_ok=True); paths.ensure_dirs()


def walk(w):
    yield w
    for c in w.winfo_children(): yield from walk(c)


def texts_of(w): return [x.cget('text') for x in walk(w) if x.winfo_class() in ('Label', 'TLabel', 'TButton', 'Button')]


def button(w, text): return next(x for x in walk(w) if x.winfo_class() == 'TButton' and x.cget('text') == text)


class GuiTests(unittest.TestCase):
    def setUp(self):
        try: os.remove(paths.SETTINGS_FILE)
        except OSError: pass
        paths.reload(); put(WIN_HOSTS)
        self.calls = []
        self.patches = {}
        for mod, name, fn in ((messagebox, 'askyesno', lambda *a, **k: True), (messagebox, 'askyesnocancel', lambda *a, **k: False), (messagebox, 'showinfo', lambda *a, **k: self.calls.append(('info', a))),
                              (messagebox, 'showerror', lambda *a, **k: self.calls.append(('error', a)))):
            self.patches[(mod, name)] = getattr(mod, name); setattr(mod, name, fn)
        self.app = ccsgui.App(); self.app.withdraw(); self.app.update()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        try: self.app.stop_poll.set(); self.app.destroy()
        except Exception: pass
        self.app = None; gc.collect()                  # free the Tk variables here, on the main thread (a later test's worker thread would otherwise crash Tcl)
        for (mod, name), fn in self.patches.items(): setattr(mod, name, fn)
        try: os.remove(paths.SETTINGS_FILE)
        except OSError: pass
        paths.reload()

    def newest(self): return max(report.list_reports(), key=os.path.getmtime)          # reports of earlier tests share the temp dir

    def pump(self, secs=0.3):
        t0 = time.time()
        while time.time() - t0 < secs: self.app.update(); time.sleep(0.02)

    def game_dir(self):
        d = tempfile.mkdtemp(prefix='gamegui_', dir=TMP); os.makedirs(os.path.join(d, 'cod26')); open(os.path.join(d, 'cod26', 'a_cdn.xpak'), 'wb').write(b'0'); return d

    def pack_game(self, name):
        from test_pack import fake_game
        g = fake_game(tempfile.mkdtemp(prefix='gamepk_', dir=TMP)); c = config.load(); c['paths'].update(game_root=g, mirror_dir=os.path.join(TMP, name)); config.save(c); self.app.cfg = c; return g

    def test_texture_pack_tab_estimate_level_links_caps_and_profiles(self):
        self.pack_game('mir_pk1'); app = self.app
        app.pack_refresh(); self.pump(1.5); pl = app._pack_plan
        self.assertEqual((pl['scope'], pl['level'], pl['total']['chunks']), ('sp', 'ultra', 7)); self.assertIn('7 chunks', app.pk_est.cget('text')); self.assertIn('GiB total', app.pk_rb['standard'].cget('text'))
        app.pk_level.set('standard'); app._pack_level_changed(); self.pump(1.5)
        self.assertEqual(app.pk_est.cget('text').split(',')[0], '3 chunks'); self.assertEqual(app.pv['max_raw_mib'].get(), '4'); self.assertEqual(app.mv['tier'].get(), '4')
        self.assertEqual(str(app.pe['max_raw_mib'].cget('state')), 'disabled'); self.assertEqual(str(app.me['tier'].cget('state')), 'disabled'); self.assertEqual(json.load(open(paths.SETTINGS_FILE))['pack']['level'], 'standard')
        app.pk_scope.set('all'); app._pack_scope_changed(); self.pump(1.5); self.assertEqual(app._pack_plan['total']['chunks'], 5); self.assertEqual(sorted(app._pack_plan['missing']), ['dmz', 'hq'])
        self.assertTrue(any('no chunk list' in app.pk_tree.item(i)['values'][0] for i in app.pk_tree.get_children()))
        app.profile.set('Ultra (4K class)'); app._profile_changed(); self.pump(1.0); self.assertEqual(app.pk_level.get(), 'ultra'); self.assertEqual(app.pv['max_raw_mib'].get(), '4096')           # profile level shows through
        self.assertIn('profile', app.pk_lvnote.cget('text'))
        app.pk_level.set('standard'); app._pack_level_changed(); self.assertEqual(app.cfg['profile'], 'Default')                                                                      # a manual choice leaves the profile
        app.pk_num['limit_mbps'].set('x'); self.assertRaises(ValueError, app._pack_collect); app._pack_collect(soft=True)                                                          # bad numbers are rejected on start, ignored by the live refresh

    def test_texture_pack_start_confirms_and_passes_scope_level_limits(self):
        self.pack_game('mir_pk2'); app = self.app; seen = {}
        import ccslib.mirrorctl as mc; old = mc.start; mc.start = lambda **kw: (seen.update(kw) or dict(pid=1)); self.addCleanup(setattr, mc, 'start', old)
        app.pk_scope.set('all'); app.pk_level.set('high'); app.pk_num['limit_mbps'].set('2'); app.pk_num['daily_gib'].set('5'); app._pack_level_changed(); app.do_pack_start()
        self.assertEqual((seen['scope'], seen['tier'], seen['budget_gib'], seen['limit_mbps'], seen['daily_gib'], seen['workers']), ('all', 8.0, 0, 2.0, 5.0, 4))
        seen.clear(); orig = messagebox.askyesno; messagebox.askyesno = lambda *a, **k: False; app.do_pack_start(); messagebox.askyesno = orig; self.assertEqual(seen, {})                      # declining the size prompt starts nothing
        app.pk_scope.set('custom')
        for v in app.pk_pkgs.values(): v.set(False)
        app.do_pack_start(); self.assertTrue(any(c[0] == 'error' and 'package' in c[1][1] for c in self.calls))                                                                         # custom needs a package

    def test_bulk_notice_is_asked_once_and_decline_starts_nothing(self):
        from ccslib import version
        self.pack_game('mir_pk3'); app = self.app; seen = {}; asked = []
        import ccslib.mirrorctl as mc; old = mc.start; mc.start = lambda **kw: (seen.update(kw) or dict(pid=1)); self.addCleanup(setattr, mc, 'start', old)
        orig = messagebox.askyesno
        def ask(title, *a, **k): asked.append(title); return not title.startswith('Bulk')
        messagebox.askyesno = ask; self.addCleanup(setattr, messagebox, 'askyesno', orig)
        app.cfg['bulk_ack'] = ''; app.do_pack_start(); self.assertEqual(seen, {}); self.assertEqual(asked, ['Bulk download - please read'])           # declined: nothing starts
        messagebox.askyesno = lambda *a, **k: True; app.do_pack_start(); self.assertTrue(seen); self.assertEqual(app.cfg['bulk_ack'], version.__version__)
        seen.clear(); asked.clear(); messagebox.askyesno = ask; app.do_pack_start(); self.assertNotIn('Bulk download - please read', asked)        # accepted once: only the size confirmation remains

    def test_progress_text_states(self):
        base = dict(ok=10, fail=0, queued=100, left=90, retry=0, bytes=2**30, budget_gib=5.0, mibps=3.0, free_gib=100, now=time.time(), started=time.time() - 10, limit_mbps=0)
        v = ccsgui.App._prog_view
        self.assertIn('DAILY QUOTA REACHED', v(dict(base, state='quota-wait', used_today_gib=5.0, resume_at=time.time() + 3600), True)[1])
        self.assertIn('NO CONNECTION', v(dict(base, state='offline-wait'), True)[1]); self.assertIn('cap 2 Mbps', v(dict(base, state='running', limit_mbps=2.0), True)[1])
        txt = v(dict(base, state='running', mibps_now=11.9, edge='203.0.113.7', edge_note='built-in fallback address (may be far from you)'), True)[1]      # rolling speed, in Mbps too, and where it comes from
        self.assertIn('11.9 MiB/s (100 Mbps)', txt); self.assertIn('via 203.0.113.7', txt); self.assertIn('[built-in fallback address', txt); self.assertIn('3.0 MiB/s (25 Mbps)', v(dict(base, state='running'), True)[1])
        self.assertIn('verifying', v(None, False, dict(done=5, total=10, bad=1), True)[1]); self.assertEqual(v(None, False)[1], 'no run in progress'); self.assertIn('last run done', v(dict(base, state='done'), False)[1])

    def test_first_run_notice_shows_once_per_version(self):
        from ccslib import version
        self.app.cfg['notice_ack'] = ''; self.calls.clear(); self.app._first_run_notice()
        self.assertEqual([c[0] for c in self.calls], ['info']); self.assertIn('Research / proof of concept', self.calls[0][1][1]); self.assertEqual(json.load(open(paths.SETTINGS_FILE))['notice_ack'], version.__version__)
        self.calls.clear(); self.app._first_run_notice(); self.assertEqual(self.calls, [])

    def test_all_tabs_exist(self):
        self.assertEqual(list(self.app.tabs), ['Dashboard', 'Proxy', 'Texture pack', 'Mirror', 'Cache', 'Game', 'Doctor', 'Report', 'Hosts / DNS', 'Logs', 'Settings'])

    def test_setup_banner_until_game_folder_saved_then_cleared(self):
        self.app.show_validation(); self.assertIn('SETUP NEEDED', self.app.setup_banner.cget('text'))
        g = self.game_dir(); self.app.pv_loc['game_root'].set(g); self.app.pv_loc['mirror_dir'].set(os.path.join(TMP, 'mir_gui')); self.app.save_locations(); self.pump()
        self.assertEqual(self.app.setup_banner.cget('text'), ''); self.assertTrue(paths.CONFIGURED); self.assertEqual(paths.GAME_ROOT, os.path.normpath(g))
        self.assertEqual(json.load(open(paths.SETTINGS_FILE))['paths']['game_root'], g)             # persisted for every CLI tool
        self.assertIn(os.path.normpath(os.path.join(TMP, 'mir_gui')), self.app.pv_eff['mirror_dir'].cget('text'))

    def test_save_locations_rejects_missing_folder(self):
        self.app.pv_loc['game_root'].set(os.path.join(TMP, 'nope')); self.app.save_locations()
        self.assertTrue(any(c[0] == 'error' for c in self.calls)); self.assertFalse(paths.CONFIGURED)

    def test_browse_sets_entry(self):
        old = filedialog.askdirectory; filedialog.askdirectory = lambda **k: os.path.join(TMP, 'picked')
        try: self.app._browse('cache_dir', 'dir')
        finally: filedialog.askdirectory = old
        self.assertEqual(self.app.pv_loc['cache_dir'].get(), os.path.normpath(os.path.join(TMP, 'picked')))

    def test_profile_save_apply_delete(self):
        old = simpledialog.askstring; simpledialog.askstring = lambda *a, **k: 'my profile'
        try: self.app.profile_save_as()
        finally: simpledialog.askstring = old
        self.assertIn('my profile', config.load()['profiles']); self.assertIn('my profile', self.app.prof_cb.cget('values')); self.assertEqual(config.load()['profile'], 'my profile')
        self.assertIn('Saved profile', self.app.prof_desc.cget('text'))
        self.app.profile_delete(); self.assertNotIn('my profile', config.load()['profiles']); self.assertEqual(config.load()['profile'], 'Default')
        self.app.profile.set('Default'); self.app.profile_delete(); self.assertTrue(any(c[0] == 'info' for c in self.calls))        # built-ins are protected

    def test_settings_roundtrip_and_shortcut_button(self):
        self.app.sv[('guard', 'limit_gib')].set('77'); self.app.sv_action.set('warn'); self.app.sv_log.set('9'); self.app.sv_exit.set('remove'); self.app.save_settings()
        c = config.load(); self.assertEqual((c['guard']['limit_gib'], c['guard']['action'], c['log_max_mb'], c['hosts']['on_exit']), (77, 'warn', 9, 'remove'))
        old = shortcut.create; shortcut.create = lambda *a, **k: os.path.join(TMP, 'fake.lnk')
        try: self.app.make_shortcut()
        finally: shortcut.create = old
        self.pump(0.2)
        self.assertIn('desktop shortcut created', open(self.app.gui_log_path, encoding='utf-8').read())

    def test_poller_and_status_lights(self):
        t0 = time.time()
        while time.time() - t0 < 12 and 't' not in self.app.snap: self.pump(0.2)
        self.assertIn('t', self.app.snap); self.pump(1.2)
        self.assertEqual(self.app.lights['hosts'][1].cget('text'), 'ABSENT'); self.assertEqual(self.app.lights['proxy'][1].cget('text'), 'stopped')

    def test_doctor_rows_and_fix_buttons(self):
        res = doctor.run_all(config.load()); self.app._show_doctor(res); self.app.update()
        buttons = [w for w in self.app.doc_frame.winfo_children() if isinstance(w, tk.Widget) and w.winfo_class() == 'TButton']
        self.assertTrue(any('apply hosts' in b.cget('text') for b in buttons))                  # hosts absent -> Fix: apply hosts (UAC)
        self.assertTrue(any('start proxy' in b.cget('text') for b in buttons))                  # proxy stopped -> Fix: start proxy

    def test_report_generation_from_log_and_view(self):
        lg = os.path.join(paths.WORK, 'ccsproxy.log')
        open(lg, 'w', encoding='utf-8').write('09:00:00 START 2026-10-21 pid=1\n09:00:00 index: 1 chunk ids\n09:00:01 GET /pc/iw9_3/23/aa/00000000000000aa_00000010_1 -> 200 16B MIRROR\n')
        self.app._make_report(-1); self.pump(0.5)
        files = [self.newest()]; rep = json.load(open(files[-1])); self.assertEqual(rep['requests']['chunk_gets'], 1)
        self.assertIn('Session report', self.app.rep_txt.get('1.0', 'end'))
        self.app._refresh_runs(); self.assertTrue(self.app.run_cb.cget('values')); self.assertTrue(self.app.saved_cb.cget('values'))
        self.app.saved_var.set(os.path.basename(files[-1])[:-5]); self.app._view_saved(); self.assertIn('Requests', self.app.rep_txt.get('1.0', 'end'))

    def test_auto_report_triggers_when_game_exits(self):
        self.app.stop_poll.set(); time.sleep(1.2)                                                # freeze the poller so we control the snapshot
        json.dump(dict(started=time.time()), open(os.path.join(paths.RUN, 'session.json'), 'w'))
        calls = []; self.app.bg = lambda label, fn, *a: calls.append((label, a))
        stat = dict(req=5, ok=5, skip=0, miss=0, err=0, retry=0, cliabort=0, mirror=5, bytes=0, mbytes=80)
        self.app._game_prev = True
        self.app.snap = dict(t=time.time(), hosts='OK', resolve=dict(ok=True), game=[], owners=[], free=100.0, pproc=dict(alive=True, pid=1), gproc=dict(alive=False), mproc=dict(alive=False),
                             pstat=dict(pid=1, now=time.time(), started=time.time() - 60, stat=stat, hist={}, recent=[], mirror_ids=3, args={}), session=dict(started=1))
        self.app._refresh()
        self.assertEqual([c[0] for c in calls], ['report']); self.assertEqual(calls[0][1], (-1, None, True))          # no launch start seen -> whole proxy run
        self.assertEqual(self.app.lights['game'][1].cget('text'), 'closed'); self.assertEqual(self.app.cnt['req'].cget('text'), '5')

    def test_auto_report_needs_no_live_proxy_and_is_not_duplicated(self):
        self.app.stop_poll.set(); time.sleep(1.2)
        calls = []; self.app.bg = lambda label, fn, *a: calls.append((label, a)); self.app._game_prev = True
        self.app.snap = dict(t=time.time(), hosts='OK', resolve=dict(ok=True), game=[], owners=[], free=100.0, pproc=dict(alive=False), gproc=dict(alive=False), mproc=dict(alive=False), pstat=None)
        self.app._refresh(); self.assertEqual([c[0] for c in calls], ['report'])             # session already stopped (proxy gone) when the game finally exits: still reported from the log
        lg = os.path.join(paths.WORK, 'ccsproxy.log'); day = '2026-10-22'
        def req(tod, cid): return f'{tod} GET /pc/iw9_3/23/{cid & 0xff:02x}/{cid:016x}_00000010_1 -> 200 16B MIRROR'
        open(lg, 'w', encoding='utf-8').write('\n'.join(['10:00:00 START ' + day + ' pid=1', '10:00:00 index: 1 chunk ids', req('10:00:10', 0xc1), req('10:00:11', 0xc2)]) + '\n')
        n0 = len(report.list_reports()); self.app._make_report(-1, None, True); n1 = len(report.list_reports()); self.assertEqual(n1, n0 + 1)
        self.app._make_report(-1, None, True); self.assertEqual(len(report.list_reports()), n1)                      # same run, same request count: skipped
        self.app._report_key = None; self.app._make_report(-1, None, True); self.assertEqual(len(report.list_reports()), n1)   # also after a GUI restart (newest saved report covers it)
        open(lg, 'a', encoding='utf-8').write(req('10:05:00', 0xc3) + '\n'); self.app._make_report(-1, None, True); self.assertEqual(len(report.list_reports()), n1 + 1)   # new traffic -> new report

    def test_stop_session_does_not_repeat_the_game_launch_report(self):
        self.app.stop_poll.set(); time.sleep(1.2)
        lg = os.path.join(paths.WORK, 'ccsproxy.log'); day = '2026-10-23'
        def req(tod, cid): return f'{tod} GET /pc/iw9_3/23/{cid & 0xff:02x}/{cid:016x}_00000010_1 -> 200 16B MIRROR'
        open(lg, 'w', encoding='utf-8').write('\n'.join(['10:00:00 START ' + day + ' pid=1', '10:00:00 index: 1 chunk ids', req('10:00:10', 0xd1), req('10:00:11', 0xd2)]) + '\n')
        win = (time.mktime((2026, 10, 23, 9, 59, 0, 0, 0, -1)), time.mktime((2026, 10, 23, 10, 2, 0, 0, 0, -1)))      # the game launch holds every request of the run
        n0 = len(report.list_reports()); self.app._make_report(-1, win, True); n1 = len(report.list_reports()); self.assertEqual(n1, n0 + 1)
        self.app._make_report(-1, None, True); self.assertEqual(len(report.list_reports()), n1)                          # Stop session right after the game exited: nothing new, no second copy
        open(lg, 'a', encoding='utf-8').write(req('10:05:00', 0xd3) + '\n'); self.app._make_report(-1, None, True); self.assertEqual(len(report.list_reports()), n1 + 1)   # more traffic -> a new report

    def test_report_and_doctor_text_carry_no_numbers_from_the_authors_own_runs(self):
        import inspect
        from ccslib import report as rp, doctor as dc
        for src in (inspect.getsource(rp), inspect.getsource(dc)): self.assertNotIn('runs 1-3 of', src); self.assertNotIn('in run 10', src)

    # ---------------------------------------------------------------- guided setup
    def _snap(self, **kw):
        base = dict(t=time.time(), hosts='ABSENT', resolve=dict(ok=False), game=[], owners=[], free=200.0, pproc=dict(alive=False), gproc=dict(alive=False), pstat=None, mproc=dict(alive=False))
        base.update(kw); self.app.snap = base

    def _live(self, req=0, game=()):
        return dict(hosts='OK', resolve=dict(ok=True), game=list(game), pproc=dict(alive=True, pid=7), pstat=dict(pid=7, stat=dict(req=req)))

    def _freeze(self): self.app.stop_poll.set(); time.sleep(1.2)

    def test_guide_is_offered_once_to_a_new_user_and_declining_is_remembered(self):
        from ccslib import version
        asked = []; messagebox.askyesno = lambda *a, **k: (asked.append(a), True)[1]
        self.app.cfg['notice_ack'] = version.__version__; self.assertFalse(paths.CONFIGURED)
        self.assertEqual(self.app.guide_frame.winfo_manager(), '')                                                      # hidden until someone says yes
        self.app._first_run_notice(); self.assertEqual(len(asked), 1)
        st = self.app._guide_state(); self.assertTrue(st['enabled']); self.assertEqual(st['offered'], version.__version__); self.assertEqual(self.app.guide_frame.winfo_manager(), 'pack')
        self.assertTrue(json.load(open(paths.SETTINGS_FILE))['guide']['enabled']); self.app._first_run_notice(); self.assertEqual(len(asked), 1)           # never asked twice
        self.app.guide_toggle(False); self.app.cfg['guide']['offered'] = ''; messagebox.askyesno = lambda *a, **k: (asked.append(a), False)[1]
        self.app._offer_guide(); self.assertEqual(len(asked), 2); st = self.app._guide_state(); self.assertFalse(st['enabled']); self.assertTrue(st['offered']); self.assertEqual(self.app.guide_frame.winfo_manager(), '')

    def test_guide_is_not_offered_to_someone_who_already_set_up_the_game_folder(self):
        asked = []; messagebox.askyesno = lambda *a, **k: (asked.append(a), True)[1]
        self.app.cfg['paths']['game_root'] = self.game_dir(); config.save(self.app.cfg); self.assertTrue(paths.CONFIGURED)
        self.app._first_run_notice(); self.assertEqual(asked, []); self.assertFalse(self.app._guide_state()['enabled'])

    def test_guide_panel_walks_through_the_first_run_and_persists(self):
        from ccslib import guide
        app = self.app; self._freeze(); app.guide_toggle(True); st = lambda: {r['id']: r['status'] for r in guide.evaluate(app._guide_state(), app._guide_facts())}
        self._snap(); app._guide_tick(); self.assertEqual(list(app._guide_lbl), ['path', 'folder', 'preflight', 'session', 'game', 'after']); self.assertEqual(st()['path'], 'current')
        app.guide_do('choose_offline'); self.assertEqual(list(app._guide_lbl), ['path', 'folder', 'preflight', 'pack', 'session', 'game', 'after']); self.assertEqual(app._guide_state()['path'], 'offline')
        g = self.game_dir(); self.assertTrue(app._apply_game_folder(g)); self.assertEqual(os.path.normcase(paths.GAME_ROOT), os.path.normcase(os.path.normpath(g)))
        self.assertEqual(st()['folder'], 'done'); self.assertEqual(json.load(open(paths.SETTINGS_FILE))['paths']['game_root'], os.path.normpath(g)); self.assertEqual(app.pv_loc['game_root'].get(), os.path.normpath(g))
        app.guide_do('skip:pack'); self._snap(); app._guide_tick(); self.assertEqual(st()['session'], 'current')
        self._snap(**self._live()); app._guide_tick(); self.assertEqual(app._guide_state()['ms'], ['session']); self.assertEqual(st()['game'], 'current')
        self._snap(**self._live(req=120, game=['sp26-cod.exe'])); app._guide_tick(); self.assertEqual(app._guide_state()['ms'], ['session', 'game']); self.assertIn('120', app._guide_lbl['game'].cget('text'))
        self._snap(); app._guide_tick(); self.assertEqual(app._guide_state()['ms'], ['session', 'game', 'after']); self.assertTrue(guide.all_passed(guide.evaluate(app._guide_state(), app._guide_facts())))
        saved = json.load(open(paths.SETTINGS_FILE))['guide']; self.assertEqual((saved['path'], saved['ms'], saved['skipped'], saved['enabled']), ('offline', ['session', 'game', 'after'], ['pack'], True))   # survives a restart
        app.guide_do('restart'); self.assertEqual((app._guide_state()['ms'], app._guide_state()['skipped'], app._guide_state()['path']), ([], [], 'offline'))

    def test_guide_buttons_use_the_normal_handlers(self):
        app = self.app; calls = []
        app.do_start = lambda: calls.append('start'); app.do_stop = lambda: calls.append('stop'); app.do_doctor = lambda: calls.append('doctor')
        for a in ('start_session', 'stop_session', 'doctor'): app.guide_do(a)
        self.assertEqual(calls, ['start', 'stop', 'doctor']); self.assertEqual(app.nb.index('current'), app.nb.index(app.tabs['Doctor']))
        app.guide_do('goto_pack'); self.assertEqual(app.nb.index('current'), app.nb.index(app.tabs['Texture pack'])); app.guide_do('goto_report'); self.assertEqual(app.nb.index('current'), app.nb.index(app.tabs['Report']))
        app.guide_do('no_such_action')                                                                                    # unknown actions are ignored, not fatal

    def test_find_game_folder_shows_what_was_found_and_sets_nothing_by_itself(self):
        from unittest import mock
        from ccslib import guide
        g = self.game_dir(); got = []; self.app._guide_choose_folder = lambda found: got.append(found)
        with mock.patch.object(guide, 'find_game_folders', return_value=[dict(path=g, score=3, source='test')]): self.app.guide_find_folder(); self.pump(1.2)
        self.assertEqual(got, [[dict(path=g, score=3, source='test')]]); self.assertFalse(paths.CONFIGURED)                  # the chooser decides; nothing was applied
        got.clear()
        with mock.patch.object(guide, 'find_game_folders', side_effect=RuntimeError('disk gone')): self.app.guide_find_folder(); self.pump(1.2)
        self.assertEqual(got, [[]])                                                                                       # a failing search shows the empty chooser (Browse still works)

    def test_a_folder_that_does_not_look_like_the_game_is_used_only_after_a_yes(self):
        from ccslib import guide
        app = self.app; odd = tempfile.mkdtemp(prefix='oddfolder_', dir=TMP); asked = []
        messagebox.askyesno = lambda *a, **k: (asked.append(a), False)[1]
        self.assertFalse(app._apply_game_folder(odd)); self.assertEqual(len(asked), 1); self.assertFalse(paths.CONFIGURED)
        messagebox.askyesno = lambda *a, **k: (asked.append(a), True)[1]
        self.assertTrue(app._apply_game_folder(odd)); self.assertTrue(paths.CONFIGURED); st = app._guide_state(); self.assertEqual(st['confirmed_root'], os.path.normpath(odd))
        f = app._guide_facts(); self.assertEqual(f['folder_score'], 0); self.assertTrue(guide.folder_ok(st, f))                  # accepted on the user's word
        self.calls.clear(); self.assertFalse(app._apply_game_folder(os.path.join(TMP, 'does_not_exist'))); self.assertEqual([c[0] for c in self.calls], ['error'])
        app.guide_do('choose_quick'); self.assertEqual(app._guide_state()['confirmed_root'], os.path.normpath(odd))          # other actions keep it

    def test_confirm_anyway_button_marks_the_current_folder(self):
        from ccslib import guide
        app = self.app; odd = tempfile.mkdtemp(prefix='oddfolder_', dir=TMP); app.cfg['paths']['game_root'] = odd; config.save(app.cfg)
        f = app._guide_facts(); self.assertFalse(guide.folder_ok(app._guide_state(), f)); app.guide_do('confirm_anyway'); self.assertTrue(guide.folder_ok(app._guide_state(), app._guide_facts()))

    def test_panel_redraws_only_when_the_layout_changes(self):
        app = self.app; app.guide_toggle(True)
        row = lambda st, detail, acts=(): dict(id='game', n=1, title='Play', status=st, detail=detail, actions=list(acts), skippable=False, done=st == 'done', running=False, skipped=False)
        s = app._guide_state(); app._guide_render(s, [row('current', 'Game detected. 1 texture pieces')]); first = app.guide_body.winfo_children()[0]
        app._guide_render(s, [row('current', 'Game detected. 2 texture pieces')]); self.assertIs(app.guide_body.winfo_children()[0], first); self.assertIn('2 texture', app._guide_lbl['game'].cget('text'))   # text only
        app._guide_render(s, [row('done', 'Done')]); self.assertIsNot(app.guide_body.winfo_children()[0], first)                  # status changed: rebuilt

    def test_panel_shows_the_latest_problem_until_something_succeeds(self):
        app = self.app; self._freeze(); app.guide_toggle(True); self._snap()
        problem = lambda: [w.cget('text') for w in app.guide_body.winfo_children() if w.winfo_class() == 'Label' and w.cget('text').startswith('Last problem')]
        app._guide_tick(); self.assertEqual(problem(), [])
        app.say('Session NOT ready: hosts override not applied:   permission denied', 'ERR'); app._guide_tick()
        self.assertEqual(len(problem()), 1); self.assertIn('Session NOT ready: hosts override not applied: permission denied', problem()[0])            # whitespace tidied
        app.say('Session READY: session running', 'OK'); app._guide_tick(); self.assertEqual(problem(), [])                                           # a success clears it
        app._guide_last = (time.time() - 700, 'old problem'); app._guide_tick(); self.assertEqual(problem(), [])                                      # and it expires

    def test_folder_chooser_lists_candidates_and_uses_only_the_selected_one(self):
        app = self.app; used = []; app._apply_game_folder = lambda p: used.append(p) or True
        found = [dict(path='C:\\A\\One', score=3, source='x'), dict(path='D:\\B\\Two', score=1, source='y')]
        def find(w, cls): return [w] if w.winfo_class() == cls else [x for c in w.winfo_children() for x in find(c, cls)]
        def open_chooser(f):
            before = set(app.winfo_children()); app._guide_choose_folder(f); app.update(); return [w for w in app.winfo_children() if w not in before and w.winfo_class() == 'Toplevel'][0]
        dlg = open_chooser(found); lb = find(dlg, 'Listbox')[0]
        self.assertEqual(lb.size(), 2); self.assertIn('C:\\A\\One', lb.get(0)); self.assertIn('looks complete', lb.get(0)); self.assertEqual(lb.curselection(), (0,))      # best one preselected
        lb.selection_clear(0, 'end'); lb.selection_set(1); [b for b in find(dlg, 'TButton') if b.cget('text') == 'Use selected'][0].invoke(); app.update()
        self.assertEqual(used, ['D:\\B\\Two']); self.assertFalse(dlg.winfo_exists())
        dlg = open_chooser([]); use = [b for b in find(dlg, 'TButton') if b.cget('text') == 'Use selected'][0]
        self.assertIn('disabled', use.state()); use.invoke(); self.assertEqual(used, ['D:\\B\\Two']); [b for b in find(dlg, 'TButton') if b.cget('text') == 'Cancel'][0].invoke(); self.assertEqual(used, ['D:\\B\\Two'])

    def test_tooltip_survives_a_widget_that_was_rebuilt(self):
        from tkinter import ttk
        b = ttk.Button(self.app.tabs['Dashboard'], text='x'); tip = ccsgui.Tip(b, 'hello'); b.destroy(); tip._show(); self.assertIsNone(tip.win)                         # no exception in the Tk callback

    def test_a_null_guide_setting_does_not_stop_the_window_opening(self):
        data = json.load(open(paths.SETTINGS_FILE)) if os.path.exists(paths.SETTINGS_FILE) else {}
        data['guide'] = None; json.dump(data, open(paths.SETTINGS_FILE, 'w'))
        a = ccsgui.App(); a.withdraw(); a.update(); self.assertEqual(a.guide_frame.winfo_manager(), ''); self.assertEqual(a._guide_state(), guide.new_state()); a.stop_poll.set(); a.destroy()

    def test_port_owner_names_in_the_facts(self):
        app = self.app; self._freeze()
        self._snap(owners=[dict(pid=5, name='?')]); self.assertEqual(app._guide_facts()['blocked_by'], 'another program')
        self._snap(owners=[dict(pid=5, name='other.exe')]); self.assertEqual(app._guide_facts()['blocked_by'], 'other.exe')
        self._snap(owners=[dict(pid=7, name='python.exe')], pproc=dict(alive=True, pid=7)); self.assertEqual(app._guide_facts()['blocked_by'], '')               # our own proxy is not a blocker
        self._snap(owners=[dict(pid=7, name='python.exe'), dict(pid=9, name='x.exe')], pproc=dict(alive=True, pid=7)); self.assertEqual(app._guide_facts()['blocked_by'], 'python.exe')

    def test_a_failing_guide_never_breaks_the_refresh_loop(self):
        from unittest import mock
        from ccslib import guide
        app = self.app; self._freeze(); app.cfg['guide']['enabled'] = True; self._snap(hosts='OK', resolve=dict(ok=True))
        with mock.patch.object(guide, 'evaluate', side_effect=RuntimeError('boom')):
            app._refresh(); app._refresh()                                                                                  # raises nothing
        self.assertEqual(app._guide_err, 'boom')

    def test_guide_button_and_settings_checkbox_toggle_the_panel(self):
        app = self.app
        def buttons(w): return [w.cget('text')] if w.winfo_class() == 'TButton' else [t for c in w.winfo_children() for t in buttons(c)]
        self.assertIn('Guide', buttons(app.tabs['Dashboard']))
        app.guide_toggle(); self.assertEqual((app.guide_frame.winfo_manager(), app.sv_guide.get()), ('pack', True)); self.assertTrue(json.load(open(paths.SETTINGS_FILE))['guide']['enabled'])
        app.guide_toggle(); self.assertEqual((app.guide_frame.winfo_manager(), app.sv_guide.get()), ('', False))
        app.guide_toggle(True); app.guide_toggle(True); self.assertEqual(app.guide_frame.winfo_manager(), 'pack')

    def test_game_launch_window_reports_and_run_list(self):
        import datetime
        lg = os.path.join(paths.WORK, 'ccsproxy.log'); day = '2026-10-21'
        def req(tod, cid): return f'{tod} GET /pc/iw9_3/23/{cid & 0xff:02x}/{cid:016x}_00000010_1 -> 200 16B MIRROR'
        open(lg, 'w', encoding='utf-8').write('\n'.join(['09:00:00 START ' + day + ' pid=1', '09:00:00 index: 1 chunk ids', req('09:00:10', 0xa1), req('09:00:11', 0xa2),
                                                         req('09:10:00', 0xb1), req('09:10:01', 0xb2), req('09:10:02', 0xb3)]) + '\n')
        e = lambda hms: datetime.datetime.strptime(f'{day} {hms}', '%Y-%m-%d %H:%M:%S').timestamp()
        json.dump([dict(start=e('09:00:05'), end=e('09:00:30')), dict(start=e('09:09:55'), end=e('09:10:30'))], open(os.path.join(paths.WORK, 'game_runs.json'), 'w'))
        self.app._refresh_runs(); labels = list(self.app._run_opts); self.assertEqual(len(labels), 3)                       # whole proxy run + 2 launches
        self.assertTrue(labels[1].startswith('#0  launch 1') and labels[2].startswith('#0  launch 2'))
        seg, win = self.app._run_opts[labels[2]]; self.assertEqual(seg, 0)
        self.app._make_report(seg, win); self.pump(0.3)
        rep = json.load(open(self.newest())); self.assertEqual(rep['requests']['chunk_gets'], 3); self.assertEqual(rep['window']['from'], '09:09:55')     # only launch 2's requests
        self.app.run_var.set(labels[1]); self.assertEqual(self.app._sel_run(), self.app._run_opts[labels[1]])
        self.app._make_report(*self.app._sel_run()); self.assertEqual(json.load(open(self.newest()))['requests']['chunk_gets'], 2)

    def test_game_runs_recorded_by_poller_transitions(self):
        self.app.stop_poll.set(); time.sleep(1.2)
        try: os.remove(self.app._runs_file())
        except OSError: pass
        self.app.game_start = time.time() - 30; win = self.app._game_ended()
        self.assertEqual(len(self.app._load_game_runs()), 1); self.assertGreater(win[1] - win[0], 29); self.assertIsNone(self.app._game_ended())      # no start seen -> no window

    def test_mirror_and_cache_views_render(self):
        self.app._show_mirror(dict(rows=[dict(prio=1, status='ok', chunks=10, wire=2**30, raw=2**31)], stored=10, stored_gib=1.0, cod_key=9)); self.assertEqual(len(self.app.m_tree.get_children()), 1)
        now = time.time(); self.app._refresh_mirror_live(dict(mproc=dict(alive=True), mprog=dict(state='running', ok=50, fail=1, retry=2, queued=100, left=49, bytes=2**30, budget_gib=90, mibps=5.0, now=now, started=now - 10, free_gib=100)))
        self.assertGreater(float(self.app.m_bar['value']), 400); self.assertIn('running', self.app.m_lbl.cget('text'))
        self.app._show_cache(dict(shards=[dict(name='cache_0_2.xpak', counter=3, records=5, unique=5, data_size=2**30, key='ab')], total_bytes=2**30, active=1, records=5, unique=5, dup_ratio=1.0, setting_gb=64), [])
        self.assertEqual(len(self.app.c_tree.get_children()), 1); self.assertEqual(self.app.c_sum['setting'].cget('text'), '64')

    def test_close_with_nothing_running_exits_without_prompt(self):
        self.app.stop_poll.set(); self.pump(0.2); asked = []
        messagebox.askyesnocancel = lambda *a, **k: asked.append(1)
        destroyed = []; real = self.app.destroy; self.app.destroy = lambda: (destroyed.append(1), real())
        self.app.snap = dict(hosts='ABSENT'); self.app.on_close()
        self.assertEqual(asked, []); self.assertEqual(destroyed, [1])                               # no prompt, window closed


    # ---------------------------------------------------------------- simple view, spotlight, words, before/after test, coaching
    def tab_states(self): return {n: str(self.app.nb.tab(f, 'state')) for n, f in self.app.tabs.items()}

    def test_simple_view_hides_the_advanced_parts_and_full_view_brings_them_back(self):
        app = self.app; app.update(); dash = app.tabs['Dashboard']
        self.assertTrue(all(s == 'normal' for s in self.tab_states().values())); self.assertEqual(app.btn_view.cget('text'), 'Simple view')
        app._goto('Cache'); app.set_simple(True); app.update()
        self.assertEqual(sorted(n for n, s in self.tab_states().items() if s == 'normal'), sorted(guide.SIMPLE_TABS)); self.assertEqual(app.nb.index('current'), app.nb.index(dash))      # a hidden tab that was open is left
        self.assertEqual((app.prof_box.winfo_manager(), app.spark_box.winfo_manager(), app.prof_desc.winfo_manager(), app.simple_note.winfo_manager()), ('', '', '', 'pack'))
        self.assertEqual(sorted(k for k, c in app.cnt_cells.items() if c.winfo_manager() == 'grid'), sorted(guide.SIMPLE_COUNTERS)); self.assertEqual(app.cnt_lbl['req'].cget('text'), 'Pieces requested')
        self.assertEqual((app.btn_view.cget('text'), app.sv_simple.get()), ('Full view', True)); self.assertTrue(json.load(open(paths.SETTINGS_FILE))['guide']['simple'])
        app.cfg['notice_ack'] = 'x'; a2 = ccsgui.App(); a2.withdraw(); a2.update()                                                       # a restart keeps the choice
        try: self.assertEqual(sorted(n for n, f in a2.tabs.items() if str(a2.nb.tab(f, 'state')) == 'normal'), sorted(guide.SIMPLE_TABS))
        finally: a2.stop_poll.set(); a2.destroy()
        app.guide_do('view'); app.update(); self.assertTrue(all(s == 'normal' for s in self.tab_states().values()))
        self.assertEqual((app.prof_box.winfo_manager(), app.spark_box.winfo_manager(), app.prof_desc.winfo_manager(), app.simple_note.winfo_manager()), ('pack', 'pack', 'pack', ''))
        self.assertEqual(len([c for c in app.cnt_cells.values() if c.winfo_manager() == 'grid']), 12); self.assertEqual(app.cnt_lbl['req'].cget('text'), 'Requests'); self.assertEqual(app.btn_view.cget('text'), 'Simple view')
        slaves = dash.pack_slaves(); self.assertLess(slaves.index(app.cnt_box), slaves.index(app.spark_box))                              # the graph comes back in its old place
        app.sv_simple.set(True); app.set_simple(app.sv_simple.get()); self.assertTrue(app._guide_state()['simple'])                      # the Settings checkbox does the same

    def test_goto_brings_a_hidden_tab_back_instead_of_failing(self):
        app = self.app; app.set_simple(True); app._goto('Logs')
        self.assertEqual(str(app.nb.tab(app.tabs['Logs'], 'state')), 'normal'); self.assertEqual(app.nb.index('current'), app.nb.index(app.tabs['Logs']))

    def test_the_offer_turns_simple_view_on_with_the_guide_and_no_turns_both_off(self):
        from ccslib import version
        self.app.cfg['notice_ack'] = version.__version__; self.app._first_run_notice()
        self.assertEqual((self.app._guide_state()['enabled'], self.app._guide_state()['simple']), (True, True)); self.assertEqual(str(self.app.nb.tab(self.app.tabs['Proxy'], 'state')), 'hidden')
        self.app.cfg['guide'] = guide.new_state(); messagebox.askyesno = lambda *a, **k: False; self.app._offer_guide(); self.app.set_simple(False)
        self.assertEqual((self.app._guide_state()['enabled'], self.app._guide_state()['simple']), (False, False)); self.assertTrue(all(s == 'normal' for s in self.tab_states().values()))

    def test_spotlight_highlights_one_control_and_clears_it(self):
        app = self.app; app._spot('btn_start'); self.assertEqual(str(app.btn_start.cget('style')), 'Spot.TButton'); app._spot('tab:Texture pack')
        self.assertEqual(str(app.btn_start.cget('style')), 'Accent.TButton'); self.assertTrue(app.nb.tab(app.tabs['Texture pack'], 'text').startswith('\u25b6'))
        app._spot(None); self.assertEqual(app.nb.tab(app.tabs['Texture pack'], 'text'), 'Texture pack')
        app._spot('btn_stop'); self.assertEqual(str(app.btn_stop.cget('style')), 'Spot.TButton'); app._spot('btn_stop'); app._spot('no_such_control'); self.assertEqual(str(app.btn_stop.cget('style')), 'TButton')   # unknown names are harmless
        app._spot(None)

    def test_the_guide_spotlights_the_step_it_is_on_and_stops_when_hidden(self):
        app = self.app; self._freeze(); g = self.game_dir(); app.guide_toggle(True); app._apply_game_folder(g); app.guide_do('choose_quick'); self._snap(); app._guide_tick()
        self.assertEqual((app._spot_key, str(app.btn_start.cget('style'))), ('btn_start', 'Spot.TButton'))
        self._snap(**self._live()); app._guide_tick(); self.assertIsNone(app._spot_key); self.assertEqual(str(app.btn_start.cget('style')), 'Accent.TButton')       # session running: nothing to press
        self._snap(); app._guide_tick(); self.assertEqual(app._spot_key, 'btn_start'); app.guide_toggle(False); self.assertIsNone(app._spot_key); self.assertEqual(str(app.btn_start.cget('style')), 'Accent.TButton')

    def test_words_dialog_lists_every_term_and_opens_once(self):
        app = self.app; d = app.show_glossary(); app.update(); self.assertIs(app.show_glossary(), d)
        body = next(x for x in walk(d) if x.winfo_class() == 'Text').get('1.0', 'end')
        for term, text in guide.GLOSSARY: self.assertIn(term, body); self.assertIn(text[:30], body)
        d.destroy(); self.assertIsNot(app.show_glossary(), d); app.guide_do('glossary')

    def test_hover_help_and_simple_view_cover_what_the_window_really_has(self):
        app = self.app
        self.assertEqual(sorted(guide.LIGHT_HELP), sorted(app.lights)); self.assertEqual(sorted(guide.COUNTER_HELP), sorted(app.cnt)); self.assertTrue(set(guide.SIMPLE_TABS) <= set(app.tabs))
        self.assertEqual(sorted(app.cnt_cells), sorted(app.cnt)); self.assertTrue(all(w.bind('<Enter>') for w in walk(app.cnt_cells['req']) if w.winfo_class() in ('TFrame', 'TLabel')))

    def test_before_after_test_walks_the_steps_calls_the_normal_handlers_and_resumes(self):
        app = self.app; calls = []; app.do_hosts_remove = lambda: calls.append('remove'); app.do_start = lambda: calls.append('start')
        real = os.startfile; os.startfile = lambda p: calls.append(('open', p)); self.addCleanup(setattr, os, 'startfile', real)
        d = app.show_abtest(); app.update(); self.assertIs(app.show_abtest(), d); head = lambda: next(t for t in texts_of(d) if t.startswith('Step '))
        self.assertEqual(head(), 'Step 1 of 4: Pick a spot'); self.assertTrue(button(d, 'Back').instate(['disabled'])); self.assertEqual([t for t in texts_of(d) if t in ('Start session', 'Switch the tool off (Restore hosts)')], [])
        button(d, 'Next').invoke(); self.assertEqual((head(), app._guide_state()['ab']), ('Step 2 of 4: Before: tool off', 1)); button(d, 'Switch the tool off (Restore hosts)').invoke()
        button(d, 'Next').invoke(); self.assertTrue(head().startswith('Step 3')); button(d, 'Start session').invoke(); self.assertEqual(calls, ['remove', 'start'])
        button(d, 'Back').invoke(); self.assertTrue(head().startswith('Step 2')); button(d, 'Next').invoke(); button(d, 'Next').invoke(); self.assertTrue(head().startswith('Step 4'))
        button(d, 'Open the screenshots folder').invoke(); self.assertEqual(calls[-1], ('open', guide.ab_dir())); self.assertTrue(os.path.isdir(guide.ab_dir()))
        self.assertEqual(button(d, 'Done').cget('text'), 'Done'); button(d, 'Done').invoke(); app.update(); self.assertFalse(d.winfo_exists())
        d2 = app.show_abtest(); self.assertIsNot(d2, d); self.assertTrue(next(t for t in texts_of(d2) if t.startswith('Step ')).startswith('Step 4'))                  # resumes where it was left
        d2.destroy(); app.cfg['guide']['ab'] = 99; self.assertEqual(guide.clean_state(app.cfg['guide'])['ab'], 99); d3 = app.show_abtest(); self.assertTrue(next(t for t in texts_of(d3) if t.startswith('Step ')).startswith('Step 4')); d3.destroy()

    def test_a_known_failure_gets_a_plain_card_with_working_buttons(self):
        app = self.app; self._freeze(); calls = []; app.do_start = lambda: calls.append('start'); app.do_hosts_apply = lambda: calls.append('apply'); app.guide_toggle(True); self._snap(); app._guide_tick()
        self.assertNotIn('Windows refused to change the hosts file', texts_of(app.guide_body))
        app.say('Session NOT ready: hosts override not applied:   permission denied', 'ERR'); app._guide_tick(); t = texts_of(app.guide_body)
        self.assertIn('Windows refused to change the hosts file', t); self.assertIn('Try again', t); self.assertTrue(any(x.startswith('Last problem') for x in t))
        button(app.guide_body, 'Try again').invoke(); self.assertEqual(calls, ['start'])
        app.say('Session READY: session running', 'OK'); app._guide_tick(); self.assertNotIn('Windows refused to change the hosts file', texts_of(app.guide_body))          # a success clears it
        app.guide_do('apply_hosts'); self.assertEqual(calls, ['start', 'apply'])
        app.guide_toggle(True); st = app._guide_state(); st['ms'] = ['session']; app._guide_save(st); self._snap(hosts='ABSENT', pproc=dict(alive=True, pid=7)); app._guide_tick()
        self.assertIn('The hosts entry is gone', texts_of(app.guide_body)); self.assertIn('Put it back (UAC)', texts_of(app.guide_body))

    def test_what_happened_is_shown_after_the_session_ends_and_hidden_while_one_runs(self):
        app = self.app; self._freeze(); app.guide_toggle(True)
        self._snap(**self._live(req=345, game=['sp26-cod.exe'])); app._guide_tick(); self.assertEqual(app._guide_state()['ms'], ['session', 'game']); self.assertNotIn('What happened', texts_of(app.guide_body))
        self._snap(); app._guide_tick(); st = app._guide_state(); self.assertEqual(st['ms'], ['session', 'game', 'after']); self.assertEqual(st['summary']['req'], 345)
        t = texts_of(app.guide_body); self.assertIn('What happened', t); self.assertTrue(any('345 texture pieces' in x for x in t)); self.assertIn('Before/after test', t)
        self.assertEqual(json.load(open(paths.SETTINGS_FILE))['guide']['summary']['req'], 345)                                                           # kept for the next start
        self._snap(**self._live(req=5)); app._guide_tick(); self.assertNotIn('What happened', texts_of(app.guide_body))                                    # a new session is running: not the old numbers
        app.guide_do('restart'); self.assertEqual(app._guide_state()['summary'], {})

    def test_the_selftest_window_shows_no_first_run_dialogs(self):
        from unittest import mock
        from ccslib import version
        self.app.cfg['notice_ack'] = version.__version__; self.app.cfg['guide']['offered'] = 'x'                                      # the window from setUp shares the event loop: keep it quiet
        asked = []; messagebox.askyesno = lambda *a, **k: (asked.append(a), True)[1]
        with mock.patch.object(ccsgui.App, '_poller', lambda self: None):
            a = ccsgui.App(selftest=True); a.withdraw()
            try:
                t0 = time.time()
                while time.time() - t0 < 1.6: a.update(); time.sleep(0.02)
            finally: a.stop_poll.set(); a.destroy()
        self.assertEqual((asked, self.calls), ([], []))                                                                         # nobody to answer: nothing is asked

    def test_the_panel_is_filled_in_right_away_not_after_the_first_poll(self):
        from unittest import mock
        self.app.guide_toggle(True)
        with mock.patch.object(ccsgui.App, '_poller', lambda self: None):
            a = ccsgui.App(); a.withdraw()
            try:
                t0 = time.time()
                while time.time() - t0 < 0.7: a.update(); time.sleep(0.02)
                self.assertTrue(a._guide_lbl); self.assertEqual(a.snap, {})
            finally: a.stop_poll.set(); a.destroy()


def tearDownModule():
    gc.collect(); shutil.rmtree(TMP, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
