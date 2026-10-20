"""GUI interaction tests: build the real window (tkinter) and drive its handlers without a human. Dialogs are patched; everything uses the temp
work dir / hosts file from test_ccs (never the real settings, hosts file or game folders)."""
import gc, json, os, shutil, sys, tempfile, time, unittest
import test_ccs                                    # sets CCS_WORK / CCS_HOSTS_PATH before ccslib is imported
from test_ccs import TMP, WIN_HOSTS, put
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog
sys.path.insert(0, test_ccs.TOOLS)
from ccslib import config, doctor, paths, procs, report, session, shortcut, proxyctl
import ccsgui


def setUpModule():
    os.makedirs(TMP, exist_ok=True); paths.ensure_dirs()


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


def tearDownModule():
    gc.collect(); shutil.rmtree(TMP, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
