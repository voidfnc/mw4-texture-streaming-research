"""Tests for the game setup (ccslib/gamefix.py): the settings-file edit, the cache link, apply / undo, and how the Doctor and the guide use it.
Everything runs in temp folders that look like a game folder; the real game folder is never touched and no game process is looked at."""
import copy, json, os, shutil, stat, subprocess, sys, tempfile, unittest
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


NO_LINKS = (False, 'exFAT')


class DriveWithoutLinks(Quiet):
    """exFAT and FAT32 drives cannot hold a folder link: Windows answers 'Incorrect function' (WinError 1). The settings change is still made, the link is left out and
    the reason is said plainly; nothing is renamed or removed for a link that cannot be made."""
    def setUp(self):
        super().setUp(); p = mock.patch.object(gamefix, 'link_support', return_value=NO_LINKS); p.start(); self.addCleanup(p.stop)

    def test_only_the_settings_change_is_made_and_the_reason_is_given(self):
        root = make_game('n1'); L = gamefix.layout(root); self.assertEqual(gamefix.state(root), 'needed'); r = gamefix.apply(root)
        self.assertEqual(r['done'], ['configs.main.ini']); self.assertTrue(r['status']['ok'] and r['status']['limited']); self.assertEqual(gamefix.state(root), 'limited')
        self.assertFalse(os.path.lexists(L['link']), 'no link, no folder either'); self.assertEqual(gamefix.state_fs(root), ('limited', 'exFAT'))
        msg = gamefix._message(r); self.assertIn('cannot hold folder links', msg); self.assertIn('exFAT', msg); self.assertIn('configs.main.ini', msg)
        again = gamefix.apply(root); self.assertEqual(again['done'], []); self.assertIn('already', gamefix._message(again)); self.assertIn('exFAT', gamefix._message(again))

    def test_a_real_folder_with_files_is_not_moved_aside_for_a_link_that_cannot_be_made(self):
        root = make_game('n2', link='dir'); L = gamefix.layout(root); gamefix.apply(root)
        self.assertEqual(slurp(os.path.join(L['link'], 'old.xpak'), 'rb'), b'old'); self.assertFalse(os.path.exists(os.path.join(L['sp26'], gamefix.ASIDE_NAME)))
        self.assertEqual(gamefix.state(root), 'limited')

    def test_when_nothing_else_is_missing_the_link_alone_is_not_a_problem(self):
        root = make_game('n3', config='[main::connectivity]\noffline=0\ndisable_lan_only=1\n'); s = gamefix.status(root)
        self.assertEqual((s['ok'], s['limited'], s['problems']), (True, True, [])); self.assertIn('NTFS', gamefix.describe(s))
        self.assertEqual(gamefix.apply(root)['done'], [])

    def test_undo_after_a_limited_setup_restores_the_file_and_has_no_link_to_remove(self):
        root = make_game('n4'); L = gamefix.layout(root); gamefix.apply(root); r = gamefix.undo(root)
        self.assertEqual(r['done'], ['configs.main.ini']); self.assertEqual(slurp(L['config']), '[main::connectivity]\noffline=1\n'); self.assertEqual(gamefix.state(root), 'needed')

    def test_the_drive_is_looked_at_only_when_a_link_would_have_to_be_made(self):
        ok = make_game('n6')
        with mock.patch.object(gamefix, 'link_support', return_value=(True, 'NTFS')): gamefix.apply(ok)
        with mock.patch.object(gamefix, 'link_support', side_effect=AssertionError('a finished link needs no probe')): self.assertEqual(gamefix.state(ok), 'ok')

    def test_the_doctor_row_warns_and_the_checklist_does_not_pass(self):
        root = make_game('n7')
        with mock.patch.object(gamefix.paths, 'GAME_ROOT', root):
            gamefix.apply(root); r = doctor.check_game_setup(); self.assertEqual(r['level'], 'warn'); self.assertEqual(r['fix'], ('game_undo', None)); self.assertIn('NTFS', r['detail']); self.assertIn('HD textures need', r['detail'])
        f = dict(configured=True, folder_root='C:\\g', folder_exists=True, folder_score=3, port=80, free_gib=100, game_setup='limited')
        pre = next(x for x in guide.evaluate(guide.new_state(path='quick'), f) if x['id'] == 'preflight')
        self.assertFalse(pre['done'], 'the setup is required: without the link HD textures cannot work'); self.assertIn('NTFS', pre['detail']); self.assertEqual(pre['actions'], [('doctor', 'Open the Doctor')], 'no Set up button: there is nothing it could do')
    def test_the_command_line_reports_a_limited_setup_as_done(self):
        root = make_game('n8'); res = os.path.join(TMP, 'n8.json'); self.assertEqual(gamefix.main(['apply', '--root', root, '--result-file', res]), 0)
        d = json.load(open(res, encoding='utf-8')); self.assertTrue(d['ok']); self.assertIn('cannot hold folder links', d['message'])

    def test_there_is_no_skip_for_the_setup(self):
        from ccslib import home
        self.assertNotIn('skip_setup', home.ACTIONS)
        f = dict(configured=True, folder_root='C:\\g', folder_exists=True, folder_score=3, port=80, free_gib=100, game_setup='needed', setup_skipped=True)       # an old settings value is ignored
        self.assertFalse(next(x for x in guide.evaluate(guide.new_state(path='quick'), f) if x['id'] == 'preflight')['done'])

class LinkFailures(Quiet):
    """The drive probe can say yes (or not know) and the link still fail: the errors must say which change they belong to."""
    def setUp(self):
        super().setUp(); p = mock.patch.object(gamefix, 'link_support', return_value=(True, 'NTFS')); p.start(); self.addCleanup(p.stop)

    def test_windows_incorrect_function_from_the_link_becomes_a_limited_setup_and_everything_is_put_back(self):
        e = OSError(1, 'Incorrect function', None, 1)
        for how in ('dir', 'empty'):
            root = make_game('f1' + how, link=how); L = gamefix.layout(root)
            with mock.patch('_winapi.CreateJunction', side_effect=e): r = gamefix.apply(root)
            self.assertEqual(r['done'], ['configs.main.ini'], how); self.assertIn('cannot hold folder links', gamefix._message(r)); self.assertTrue(os.path.isdir(L['link']), how + ': the folder is back')
            self.assertFalse(os.path.exists(os.path.join(L['sp26'], gamefix.ASIDE_NAME)))
            if how == 'dir': self.assertEqual(slurp(os.path.join(L['link'], 'old.xpak'), 'rb'), b'old')
            self.assertEqual(r['aside'], '')

    def test_make_junction_names_the_drive_problem(self):
        root = make_game('f2'); L = gamefix.layout(root)
        with mock.patch('_winapi.CreateJunction', side_effect=OSError(1, 'Incorrect function', None, 1)), self.assertRaises(gamefix.LinkUnsupported) as c: gamefix.make_junction(L['link'], L['target'])
        self.assertIn('cannot hold folder links', str(c.exception)); self.assertIn('Incorrect function', str(c.exception))
        with mock.patch('_winapi.CreateJunction', side_effect=OSError(5, 'Access is denied', None, 5)), self.assertRaises(PermissionError): gamefix.make_junction(L['link'], L['target'])
        with mock.patch('_winapi.CreateJunction', side_effect=OSError(3, 'The system cannot find the path', None, 3)), self.assertRaises(OSError) as c: gamefix.make_junction(L['link'], L['target'])
        self.assertNotIsInstance(c.exception, gamefix.LinkUnsupported)

    def test_another_link_error_names_the_change_and_says_the_settings_file_was_changed(self):
        root = make_game('f3'); L = gamefix.layout(root)
        with mock.patch.object(gamefix, 'make_junction', side_effect=OSError('boom')), self.assertRaises(OSError) as c: gamefix.apply(root)
        m = str(c.exception); self.assertIn('the settings file was changed', m); self.assertIn('sp26\\xpak_cache could not be made', m); self.assertIn('boom', m)
        self.assertEqual(gamefix.read_keys(slurp(L['config']))['offline'], '0', 'the settings change stands (and Undo takes it back)')
        root = make_game('f3b', config='[main::connectivity]\noffline=0\ndisable_lan_only=1\n')
        with mock.patch.object(gamefix, 'make_junction', side_effect=OSError('boom')), self.assertRaises(OSError) as c: gamefix.apply(root)
        self.assertNotIn('settings file was changed', str(c.exception))

    def test_a_failing_settings_write_names_the_file(self):
        root = make_game('f4')
        with mock.patch.object(gamefix, '_write', side_effect=OSError('disk full')), self.assertRaises(OSError) as c: gamefix.apply(root)
        self.assertIn('could not change configs.main.ini: disk full', str(c.exception))
        with mock.patch.object(gamefix, '_write', side_effect=PermissionError('denied')), self.assertRaises(PermissionError): gamefix.apply(make_game('f4b'))

    def test_the_text_for_windows_error_1_says_what_it_usually_means(self):
        t = gamefix.friendly(OSError(1, 'Incorrect function', None, 1)); self.assertIn('Incorrect function', t); self.assertIn('does not support', t)
        self.assertEqual(gamefix.friendly(OSError('plain')), 'plain')

    def test_the_text_for_a_corrupted_folder_points_at_chkdsk(self):
        for code in gamefix.ERRORS_CORRUPT:
            t = gamefix.friendly(OSError(code, 'The file or directory is corrupted and unreadable', None, code))
            self.assertIn('chkdsk', t); self.assertIn(str(code), t); self.assertIn('cannot repair', t)

    def test_a_corrupted_folder_fails_cleanly_instead_of_with_windows_raw_text(self):
        corrupt = OSError(1392, 'The file or directory is corrupted and unreadable', None, 1392)
        for how in ('dir', 'empty'):
            root = make_game('fc' + how, link=how)
            with mock.patch.object(os, 'rmdir', side_effect=corrupt) if how == 'empty' else mock.patch.object(os, 'rename', side_effect=corrupt):
                with self.assertRaises(OSError) as c: gamefix.apply(root)
            self.assertIn('chkdsk', str(c.exception)); self.assertNotIn('WinError', str(c.exception))
        root = make_game('fc_mkdir', link='dir')
        with mock.patch.object(os, 'makedirs', side_effect=corrupt), self.assertRaises(OSError) as c: gamefix.apply(root)
        self.assertIn('chkdsk', str(c.exception))
        root = make_game('fc_junction', link='dir')
        with mock.patch.object(gamefix, 'make_junction', side_effect=corrupt), self.assertRaises(OSError) as c: gamefix.apply(root)
        self.assertIn('chkdsk', str(c.exception))


class DriveProbe(unittest.TestCase):
    def test_the_real_probe_knows_this_drive_and_never_raises(self):
        sup, fs = gamefix.link_support(TMP); self.assertIn(sup, (True, None)); self.assertIsInstance(fs, str)          # the temp folder is on an NTFS drive here
        self.assertEqual(gamefix.link_support(os.path.join(TMP, 'not', 'there')), (sup, fs), 'a folder that does not exist yet is judged by its nearest existing parent')
        self.assertEqual(gamefix.link_support('Z:\\no\\such\\drive')[0] in (None, False), True)

    def test_the_probe_reads_the_reparse_point_flag(self):
        self.assertEqual(gamefix.FILE_SUPPORTS_REPARSE_POINTS, 0x80)


class RealExfatDrive(unittest.TestCase):
    """Opt-in (CCS_TEST_EXFAT=1, needs administrator rights): makes a 64 MB virtual disk formatted exFAT, mounts it, runs the game setup on a folder there, then removes the disk."""
    @unittest.skipUnless(os.environ.get('CCS_TEST_EXFAT') == '1' and procs.is_admin(), 'set CCS_TEST_EXFAT=1 and run as administrator')
    def test_the_game_setup_on_a_real_exfat_volume(self):
        vhd = os.path.join(TMP, 'exfat.vhd'); script = os.path.join(TMP, 'dp.txt')
        def dp(text):
            put(script, text); return subprocess.run(['diskpart', '/s', script], capture_output=True, text=True, errors='replace').stdout
        try:
            free = [x for x in 'ZYXWVUTSRQPONMLKJIHGFED' if not os.path.exists(x + ':\\')]; drive = free[0]
            out = dp(f'create vdisk file="{vhd}" maximum=64 type=fixed\nselect vdisk file="{vhd}"\nattach vdisk\ncreate partition primary\nformat fs=exfat quick label=CCSTEST\nassign letter={drive}\n')
            self.assertTrue(os.path.isdir(drive + ':\\'), out)
            root = os.path.join(drive + ':\\', 'Game'); st = os.path.join(root, 'sp26', 'steam_settings'); os.makedirs(st); put(os.path.join(st, 'configs.main.ini'), '[main::connectivity]\noffline=1\n')
            os.makedirs(os.path.join(root, 'xpak_cache'))
            sup, fs = gamefix.link_support(root); self.assertEqual((sup, fs.lower()), (False, 'exfat'))
            L = gamefix.layout(root)
            with self.assertRaises(gamefix.LinkUnsupported): gamefix.make_junction(L['link'], L['target'])              # without the probe: Windows' own answer, WinError 1
            with mock.patch.object(procs, 'image_running', return_value=[]): r = gamefix.apply(root)
            self.assertEqual(r['done'], ['configs.main.ini']); self.assertEqual(gamefix.state(root), 'limited'); self.assertIn('exFAT', gamefix._message(r))
        finally:
            dp(f'select vdisk file="{vhd}"\ndetach vdisk\n')


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
