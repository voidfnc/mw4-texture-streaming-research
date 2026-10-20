"""Tests for the game setup (ccslib/gamefix.py): the settings-file edit, the cache link, apply / undo, and how the Doctor and the guide use it.
Everything runs in temp folders that look like a game folder; the real game folder is never touched and no game process is looked at."""
import copy, json, os, shutil, stat, sys, tempfile, unittest
from unittest import mock

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, TOOLS)
from ccslib import config, doctor, gamefix, guide, launch, procs, session

TMP = tempfile.mkdtemp(prefix='ccsgamefix_')


def tearDownModule(): shutil.rmtree(TMP, ignore_errors=True)


def put(path, data, mode='w'):
    with open(path, mode, **({'newline': ''} if 'b' not in mode else {})) as f: f.write(data)


def slurp(path, mode='r'):
    with open(path, mode, **({'newline': ''} if 'b' not in mode else {})) as f: return f.read()


def make_game(name, config='[main::connectivity]\noffline=1\n', cache=True, link=None):
    """A folder with sp26/steam_settings (and the cache at the root); `link`: None | 'dir' | 'file' | 'other'."""
    root = os.path.join(TMP, name); st = os.path.join(root, 'sp26', 'steam_settings'); os.makedirs(st)
    if config is not None: put(os.path.join(st, 'configs.main.ini'), config)
    if cache: os.makedirs(os.path.join(root, 'xpak_cache')); put(os.path.join(root, 'xpak_cache', 'cache_0_2.xpak'), b'x', 'wb')
    lk = os.path.join(root, 'sp26', 'xpak_cache')
    if link == 'dir': os.makedirs(lk); put(os.path.join(lk, 'old.xpak'), b'old', 'wb')
    elif link == 'empty': os.makedirs(lk)
    elif link == 'file': put(lk, 'x')
    elif link == 'other': other = os.path.join(root, 'elsewhere'); os.makedirs(other); gamefix.make_junction(lk, other)
    return root


class Quiet(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(procs, 'image_running', return_value=[]); p.start(); self.addCleanup(p.stop)


class SettingsText(unittest.TestCase):
    def check(self, text):
        out = gamefix.set_keys(text); k = gamefix.read_keys(out)
        self.assertEqual((k['offline'], k['disable_lan_only']), ('0', '1')); self.assertEqual(gamefix.set_keys(out), out, 'a second pass must change nothing'); return out

    def test_the_default_offline_file_is_fixed(self):
        self.assertEqual(self.check('[main::connectivity]\noffline=1\n'), '[main::connectivity]\noffline=0\ndisable_lan_only=1\n')

    def test_an_empty_or_unrelated_file_gets_the_section(self):
        self.assertEqual(gamefix.read_keys(self.check('')), dict(offline='0', disable_lan_only='1'))
        out = self.check('[other]\na=1\n'); self.assertTrue(out.startswith('[other]\na=1\n')); self.assertIn('[main::connectivity]', out)
        self.assertIn('\n[main::connectivity]', self.check('[other]\na=1'))                                    # no newline at the end of the file

    def test_other_lines_comments_and_sections_survive(self):
        text = '[main::connectivity]\r\n; keep me\r\noffline=1\r\nfoo=2\r\n\r\n[other]\r\nz=1\r\n'
        out = self.check(text)
        self.assertEqual(out, '[main::connectivity]\r\n; keep me\r\noffline=0\r\nfoo=2\r\ndisable_lan_only=1\r\n\r\n[other]\r\nz=1\r\n')

    def test_a_header_alone_and_a_header_with_a_comment(self):
        self.assertEqual(self.check('[main::connectivity]'), '[main::connectivity]\r\noffline=0\r\ndisable_lan_only=1\r\n')
        out = self.check('[main::connectivity] ; the network\noffline=1\n'); self.assertEqual(out.count('[main::connectivity]'), 1)

    def test_case_spaces_and_a_bom(self):
        self.assertEqual(self.check('[Main::Connectivity]\ndisable_lan_only = 0\nOffline = 1\n'), '[Main::Connectivity]\ndisable_lan_only=1\noffline=0\n')
        self.assertTrue(self.check('\ufeff[main::connectivity]\noffline=1\n').startswith('\ufeff[main::connectivity]'))

    def test_a_commented_key_is_not_a_setting(self):
        self.assertEqual(gamefix.read_keys('[main::connectivity]\n;offline=0\n'), {})
        self.assertIn('\noffline=0\n', self.check('[main::connectivity]\n;offline=1\n'))

    def test_the_same_key_in_another_section_is_left_alone(self):
        out = self.check('[a]\noffline=1\n[main::connectivity]\nfoo=1\n'); self.assertIn('[a]\noffline=1\n', out)


class Status(Quiet):
    def test_the_usual_layout_needs_the_setup(self):
        s = gamefix.status(make_game('s1'))
        self.assertTrue(s['applicable']); self.assertFalse(s['ok']); self.assertEqual(s['link_state'], 'missing'); self.assertEqual(len(s['problems']), 2)
        self.assertIn('offline mode', s['problems'][0]); self.assertEqual(gamefix.state(s['root']), 'needed')

    def test_not_the_layout_it_is_about(self):
        root = os.path.join(TMP, 's2'); os.makedirs(os.path.join(root, 'sp26'))
        s = gamefix.status(root); self.assertFalse(s['applicable']); self.assertEqual(gamefix.state(root), 'na'); self.assertEqual(gamefix.describe(s), s['why'])
        self.assertEqual(gamefix.state(os.path.join(TMP, 'does-not-exist')), 'na')

    def test_the_checklist_timer_never_starts_a_process(self):
        """state() is called from the window's refresh loop every few seconds: it must not look for the game (that starts tasklist)."""
        root = make_game('s4')
        with mock.patch.object(procs, 'image_running', side_effect=AssertionError('tasklist was started')): self.assertEqual(gamefix.state(root), 'needed')

    def test_a_cache_folder_setting_that_points_at_the_link_itself_is_not_this_layout(self):
        root = make_game('s5'); link = gamefix.layout(root)['link']
        with mock.patch.object(gamefix.paths, 'XPAK_CACHE', link):
            s = gamefix.status(root); self.assertFalse(s['applicable']); self.assertIn('cache folder setting', s['why']); self.assertEqual(gamefix.state(root), 'na')
            with self.assertRaises(gamefix.NotApplicable): gamefix.apply(root)
        with mock.patch.object(gamefix.paths, 'XPAK_CACHE', os.path.join(root, 'xpak_cache')): self.assertTrue(gamefix.status(root)['applicable'])

    def test_the_default_game_names_count_even_when_the_setting_was_edited(self):
        root = make_game('s6'); seen = []
        def fake(*exes): seen.extend(exes); return []
        with mock.patch.object(gamefix.paths, 'GAME_EXES', ('mygame.exe',)), mock.patch.object(procs, 'image_running', side_effect=fake): gamefix.status(root)
        self.assertEqual(sorted(seen), sorted(['mygame.exe', 'sp26-cod.exe', 'cod.exe']))

    def test_it_never_raises_on_a_broken_config(self):
        root = make_game('s3', config=None); self.assertEqual(gamefix.status(root)['keys'], {}); self.assertEqual(gamefix.state(root), 'needed')

    def test_link_states(self):
        for how, want in (('dir', 'dir'), ('file', 'file'), ('other', 'wrong'), (None, 'missing')):
            L = gamefix.layout(make_game('ls_' + str(how), link=how)); self.assertEqual(gamefix.link_state(L['link'], L['target']), want, how)
        L = gamefix.layout(make_game('ls_broken', link='other')); shutil.rmtree(os.path.join(L['root'], 'elsewhere')); self.assertEqual(gamefix.link_state(L['link'], L['target']), 'broken')
        L = gamefix.layout(make_game('ls_gone')); gamefix.apply(L['root']); shutil.rmtree(L['target']); self.assertEqual(gamefix.link_state(L['link'], L['target']), 'broken', 'our own link, cache folder deleted')


class Apply(Quiet):
    def test_apply_sets_both_and_is_idempotent(self):
        root = make_game('a1'); r = gamefix.apply(root); L = gamefix.layout(root)
        self.assertEqual(r['done'], ['configs.main.ini', 'sp26\\xpak_cache']); self.assertTrue(r['status']['ok']); self.assertEqual(gamefix.state(root), 'ok')
        self.assertTrue(gamefix.is_reparse(L['link'])); self.assertTrue(os.path.exists(os.path.join(L['link'], 'cache_0_2.xpak')), 'the game sees the cache through the link')
        self.assertEqual(slurp(L['backup']), '[main::connectivity]\noffline=1\n', 'the original is kept')
        again = gamefix.apply(root); self.assertEqual(again['done'], []); self.assertIn('already', gamefix._message(again))

    def test_a_file_written_through_the_link_lands_in_the_real_cache(self):
        root = make_game('a2'); gamefix.apply(root); L = gamefix.layout(root)
        put(os.path.join(L['link'], 'new.xpak'), b'n', 'wb'); self.assertTrue(os.path.exists(os.path.join(root, 'xpak_cache', 'new.xpak')))

    def test_the_backup_is_made_once_and_keeps_the_very_first_original(self):
        root = make_game('a3'); gamefix.apply(root); L = gamefix.layout(root)
        put(L['config'], '[main::connectivity]\noffline=1\nx=2\n'); gamefix.apply(root)             # the setting was changed back (and a line added) by something else
        self.assertEqual(slurp(L['backup']), '[main::connectivity]\noffline=1\n', 'the backup is still the very first original'); self.assertEqual(gamefix.state(root), 'ok')

    def test_a_missing_cache_folder_is_created_and_a_missing_config_is_written(self):
        root = make_game('a4', config=None, cache=False); gamefix.apply(root); L = gamefix.layout(root)
        self.assertTrue(os.path.isdir(L['target'])); self.assertEqual(gamefix.read_keys(slurp(L['config'])), dict(offline='0', disable_lan_only='1'))
        self.assertEqual(slurp(L['backup'], 'rb'), b'', 'an empty backup records that there was no settings file')

    def test_an_empty_real_folder_is_replaced_and_one_with_files_is_moved_aside_not_deleted(self):
        root = make_game('a5', link='empty'); self.assertEqual(gamefix.apply(root)['aside'], ''); self.assertEqual(gamefix.state(root), 'ok')
        root = make_game('a6', link='dir'); r = gamefix.apply(root); self.assertTrue(r['status']['ok']); self.assertEqual(slurp(os.path.join(r['aside'], 'old.xpak'), 'rb'), b'old')
        self.assertIn('is now', gamefix._message(r))

    def test_a_users_own_link_elsewhere_is_left_alone_and_the_reason_is_given(self):
        root = make_game('a7', link='other'); other = os.path.join(root, 'elsewhere'); put(os.path.join(other, 'keep.txt'), 'k')
        with self.assertRaises(OSError) as c: gamefix.apply(root)
        self.assertIn('your own setup', str(c.exception)); self.assertNotIn(type(c.exception), (PermissionError,))
        self.assertTrue(os.path.exists(os.path.join(other, 'keep.txt'))); self.assertEqual(slurp(gamefix.layout(root)['config']), '[main::connectivity]\noffline=1\n', 'nothing was changed')
        self.assertIn('did not make', ' '.join(gamefix.undo(root)['notes'])); self.assertTrue(gamefix.is_reparse(gamefix.layout(root)['link']), 'undo leaves a link it did not make')

    def test_a_broken_link_and_our_own_link_to_a_deleted_cache_are_made_again(self):
        root = make_game('a7b', link='other'); shutil.rmtree(os.path.join(root, 'elsewhere')); gamefix.apply(root); self.assertEqual(gamefix.state(root), 'ok')
        root = make_game('a7c'); gamefix.apply(root); shutil.rmtree(os.path.join(root, 'xpak_cache')); self.assertEqual(gamefix.state(root), 'needed'); gamefix.apply(root); self.assertEqual(gamefix.state(root), 'ok')

    def test_a_failed_link_puts_the_real_folder_back(self):
        root = make_game('a7d', link='dir'); L = gamefix.layout(root)
        with mock.patch.object(gamefix, 'make_junction', side_effect=OSError('no reparse points here')):
            with self.assertRaises(OSError): gamefix.apply(root)
        self.assertEqual(slurp(os.path.join(L['link'], 'old.xpak'), 'rb'), b'old', 'the real folder is back where it was'); self.assertFalse(os.path.exists(os.path.join(L['sp26'], gamefix.ASIDE_NAME)))

    def test_a_read_only_settings_file_is_refused_cleanly(self):
        root = make_game('a7e', link='dir'); L = gamefix.layout(root)
        os.chmod(L['config'], stat.S_IREAD); self.addCleanup(os.chmod, L['config'], stat.S_IWRITE)
        with self.assertRaises(OSError) as c: gamefix.apply(root)
        self.assertNotIsInstance(c.exception, PermissionError, 'no Windows prompt for something rights cannot fix'); self.assertIn('read-only', str(c.exception))
        self.assertEqual(sorted(os.listdir(L['settings'])), ['configs.main.ini'], 'no temporary or backup file is left behind')
        self.assertTrue(os.path.isdir(L['link']) and not gamefix.is_reparse(L['link']))

    def test_a_file_in_the_way_is_refused_and_nothing_is_changed(self):
        root = make_game('a8', link='file')
        with self.assertRaises(OSError): gamefix.apply(root)
        self.assertEqual(slurp(gamefix.layout(root)['config']), '[main::connectivity]\noffline=1\n')

    def test_nothing_changes_while_the_game_runs(self):
        root = make_game('a9')
        with mock.patch.object(procs, 'image_running', return_value=['sp26-cod.exe']):
            with self.assertRaises(gamefix.GameBusy): gamefix.apply(root)
            with self.assertRaises(gamefix.GameBusy): gamefix.undo(root)
        self.assertEqual(gamefix.state(root), 'needed')

    def test_a_binary_or_utf16_settings_file_is_refused_untouched(self):
        root = make_game('a11'); L = gamefix.layout(root)
        with open(L['config'], 'wb') as f: f.write('[main::connectivity]\noffline=1\n'.encode('utf-16'))
        with self.assertRaises(OSError): gamefix.apply(root)
        self.assertEqual(slurp(L['config'], 'rb'), '[main::connectivity]\noffline=1\n'.encode('utf-16')); self.assertFalse(os.path.lexists(L['link']))

    def test_not_applicable_raises(self):
        with self.assertRaises(gamefix.NotApplicable): gamefix.apply(os.path.join(TMP, 'nowhere'))

    def test_a_permission_error_is_passed_on_so_the_caller_can_elevate(self):
        root = make_game('a10')
        with mock.patch.object(gamefix, 'make_junction', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError): gamefix.apply(root)


class Undo(Quiet):
    def test_undo_restores_the_file_and_removes_only_the_link(self):
        root = make_game('u1'); gamefix.apply(root); L = gamefix.layout(root); r = gamefix.undo(root)
        self.assertEqual(r['done'], ['configs.main.ini', 'sp26\\xpak_cache']); self.assertEqual(slurp(L['config']), '[main::connectivity]\noffline=1\n')
        self.assertFalse(os.path.lexists(L['link'])); self.assertTrue(os.path.exists(os.path.join(root, 'xpak_cache', 'cache_0_2.xpak')), 'the real cache is untouched')
        self.assertFalse(os.path.exists(L['backup'])); self.assertEqual(gamefix.undo(root)['done'], [])

    def test_undo_puts_back_only_our_two_keys_and_keeps_edits_made_since(self):
        root = make_game('u3', config='[main::connectivity]\noffline=1\n[other]\na=1\n'); L = gamefix.layout(root); gamefix.apply(root)
        put(L['config'], slurp(L['config']) + '[mine]\nx=2\n'); gamefix.undo(root)
        self.assertEqual(slurp(L['config']), '[main::connectivity]\noffline=1\n[other]\na=1\n[mine]\nx=2\n')

    def test_undo_removes_a_key_that_was_not_there_before_and_a_file_that_was_not_there_before(self):
        root = make_game('u4', config='[main::connectivity]\nfoo=1\n'); L = gamefix.layout(root); gamefix.apply(root); gamefix.undo(root)
        self.assertEqual(slurp(L['config']), '[main::connectivity]\nfoo=1\n')
        root = make_game('u5', config=None); L = gamefix.layout(root); gamefix.apply(root); self.assertTrue(os.path.exists(L['config'])); r = gamefix.undo(root)
        self.assertFalse(os.path.exists(L['config'])); self.assertFalse(os.path.exists(L['backup'])); self.assertEqual(r['done'], ['configs.main.ini', 'sp26\\xpak_cache'])

    def test_undo_refuses_a_read_only_file_and_changes_nothing(self):
        root = make_game('u6'); L = gamefix.layout(root); gamefix.apply(root); os.chmod(L['config'], stat.S_IREAD); self.addCleanup(os.chmod, L['config'], stat.S_IWRITE)
        with self.assertRaises(OSError) as c: gamefix.undo(root)
        self.assertNotIsInstance(c.exception, PermissionError); self.assertTrue(os.path.exists(L['backup'])); self.assertTrue(gamefix.is_reparse(L['link']))

    def test_undo_asks_for_rights_the_same_way_apply_does(self):
        root = make_game('u7'); gamefix.apply(root); seen = []
        def fake_elevated(argv, wait_s=120):
            seen.append(argv); put(argv[argv.index('--result-file') + 1], json.dumps(dict(ok=True, message='restored: elevated'))); return 0
        run = tempfile.mkdtemp(dir=TMP)
        with mock.patch.object(gamefix.paths, 'RUN', run), mock.patch.object(gamefix, 'undo', side_effect=PermissionError('denied')), mock.patch.object(procs, 'run_elevated', side_effect=fake_elevated):
            self.assertEqual(gamefix.undo_elevating(root, say=lambda *_: None), (True, 'restored: elevated'))
        self.assertEqual(seen[0][seen[0].index('gamefix') + 1], 'undo')

    def test_undo_leaves_a_real_folder_alone(self):
        root = make_game('u2', link='dir'); r = gamefix.undo(root); self.assertTrue(os.path.isdir(gamefix.layout(root)['link'])); self.assertTrue(r['notes'])


class Command(Quiet):
    def run_main(self, *args):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): code = gamefix.main(list(args))
        return code, buf.getvalue()

    def test_status_apply_undo_through_the_command_line(self):
        root = make_game('c1'); code, out = self.run_main('status', '--root', root); self.assertEqual(code, 1); self.assertIn('offline mode', out)
        code, out = self.run_main('apply', '--root', root, '--json'); res = json.loads(out); self.assertEqual((code, res['ok']), (0, True)); self.assertEqual(res['done'], ['configs.main.ini', 'sp26\\xpak_cache'])
        code, out = self.run_main('status', '--root', root); self.assertEqual(code, 0)
        code, out = self.run_main('undo', '--root', root); self.assertEqual(code, 0); self.assertIn('restored', out)

    def test_exit_codes_for_the_two_refusals_and_a_result_file(self):
        root = make_game('c2'); rf = os.path.join(TMP, 'res.json')
        with mock.patch.object(procs, 'image_running', return_value=['sp26-cod.exe']): code, _ = self.run_main('apply', '--root', root, '--result-file', rf)
        self.assertEqual(code, 1); self.assertFalse(json.loads(slurp(rf))['ok'])
        with mock.patch.object(gamefix, 'make_junction', side_effect=PermissionError('denied')): code, _ = self.run_main('apply', '--root', root)
        self.assertEqual(code, 3)

    def test_the_packaged_and_the_source_command_lines_exist(self):
        self.assertIn('gamefix', launch.INTERNAL)
        self.assertEqual(launch.argv_for('gamefix', 'apply', frozen=True, executable='C:\\p\\x.exe')[1:], ['--ccs-run', 'gamefix', 'apply'])
        a = launch.argv_for('gamefix', 'apply', frozen=False, executable='py.exe'); self.assertEqual(a[0], 'py.exe'); self.assertTrue(a[1].endswith('ccs.py')); self.assertEqual(a[2:], ['--ccs-run', 'gamefix', 'apply'])
        self.assertTrue(os.path.exists(a[1]))

    def test_the_elevated_command_line_keeps_a_path_with_spaces_and_brackets_in_one_piece(self):
        root = os.path.join(TMP, 'Program Files (x86)', 'Call of Duty Modern Warfare 4'); os.makedirs(os.path.join(root, 'sp26', 'steam_settings'))
        put(os.path.join(root, 'sp26', 'steam_settings', 'configs.main.ini'), '[main::connectivity]\noffline=1\n'); seen = []
        def fake(argv, wait_s=120):
            seen.append(argv); put(argv[argv.index('--result-file') + 1], json.dumps(dict(ok=True, message='x'))); return 0
        with mock.patch.object(gamefix.paths, 'RUN', tempfile.mkdtemp(dir=TMP)), mock.patch.object(gamefix, 'apply', side_effect=PermissionError('denied')), mock.patch.object(procs, 'run_elevated', side_effect=fake):
            gamefix.apply_elevating(root, say=lambda *_: None)
        argv = seen[0]; self.assertEqual(argv[argv.index('--root') + 1], os.path.normpath(root))
        import subprocess
        self.assertIn('"' + os.path.normpath(root) + '"', subprocess.list2cmdline(argv[1:]), 'quoted as one argument for the elevated process')

    def test_the_elevated_path_reads_the_result_file(self):
        root = make_game('c3'); p = mock.patch.object(gamefix.paths, 'RUN', tempfile.mkdtemp(dir=TMP)); p.start(); self.addCleanup(p.stop)
        def fake_elevated(argv, wait_s=120):
            rf = argv[argv.index('--result-file') + 1]; put(rf, json.dumps(dict(ok=True, message='changed: elevated'))); return 0
        with mock.patch.object(gamefix, 'apply', side_effect=PermissionError('denied')), mock.patch.object(procs, 'run_elevated', side_effect=fake_elevated):
            self.assertEqual(gamefix.apply_elevating(root, say=lambda *_: None), (True, 'changed: elevated'))
        with mock.patch.object(gamefix, 'apply', side_effect=PermissionError('denied')), mock.patch.object(procs, 'run_elevated', return_value=None):
            ok, msg = gamefix.apply_elevating(root, say=lambda *_: None); self.assertFalse(ok); self.assertIn('declined', msg)


class UsedByTheApp(Quiet):
    def test_the_doctor_row_warns_offers_the_fix_and_turns_green(self):
        root = make_game('d1')
        with mock.patch.object(gamefix.paths, 'GAME_ROOT', root):
            r = doctor.check_game_setup(); self.assertEqual((r['level'], r['fix']), ('warn', ('game_fix', None))); self.assertIn('offline mode', r['detail'])
            self.assertTrue(session.run_fix(copy.deepcopy(config.DEFAULTS), ('game_fix', None), lambda *_: None)[0])
            r = doctor.check_game_setup(); self.assertEqual((r['level'], r['fix']), ('ok', ('game_undo', None)))
            self.assertTrue(session.run_fix(copy.deepcopy(config.DEFAULTS), ('game_undo', None), lambda *_: None)[0]); self.assertEqual(doctor.check_game_setup()['level'], 'warn')
        with mock.patch.object(gamefix.paths, 'GAME_ROOT', os.path.join(TMP, 'nowhere')): self.assertEqual(doctor.check_game_setup()['level'], 'info')

    def test_no_fix_button_while_the_game_runs(self):
        root = make_game('d2')
        with mock.patch.object(gamefix.paths, 'GAME_ROOT', root), mock.patch.object(procs, 'image_running', return_value=['sp26-cod.exe']):
            r = doctor.check_game_setup(); self.assertIsNone(r['fix']); self.assertIn('close the game', r['detail'])

    def test_the_checklist_asks_for_the_setup_and_finishes_when_it_is_done(self):
        f = dict(configured=True, folder_root='C:\\g', folder_exists=True, folder_score=3, port=80, free_gib=100, game_setup='needed')
        pre = next(r for r in guide.evaluate(guide.new_state(path='quick'), f) if r['id'] == 'preflight')
        self.assertFalse(pre['done']); self.assertEqual(pre['actions'], [('game_setup', 'Set up the game')]); self.assertIn('streamed textures', pre['detail'])
        for v in ('ok', 'na', None):
            pre = next(r for r in guide.evaluate(guide.new_state(path='quick'), dict(f, game_setup=v)) if r['id'] == 'preflight'); self.assertTrue(pre['done'], v)
        f2 = dict(f, blocked_by='nginx.exe'); pre = next(r for r in guide.evaluate(guide.new_state(path='quick'), f2) if r['id'] == 'preflight')
        self.assertEqual([a[0] for a in pre['actions']], ['game_setup', 'doctor'])


if __name__ == '__main__':
    unittest.main()
