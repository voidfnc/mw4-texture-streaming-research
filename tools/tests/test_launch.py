"""Tests for how the app starts its helpers (ccslib/launch.py), the packaged-app entry point (ccs.py) and the installer hooks (ccslib/uninstall.py).
Everything runs against temp folders and a temp hosts file (CCS_WORK / CCS_HOSTS_PATH); the real hosts file and settings are never touched."""
import json, os, shutil, subprocess, sys, tempfile, time, unittest

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, TOOLS)
from ccslib import launch, paths, version

TMP = tempfile.mkdtemp(prefix='ccslaunch_')
CCS = os.path.join(TOOLS, 'ccs.py')


def tearDownModule(): shutil.rmtree(TMP, ignore_errors=True)


def env_for(name):
    d = tempfile.mkdtemp(prefix=name + '_', dir=TMP); hosts = os.path.join(d, 'hosts'); open(hosts, 'w').write('127.0.0.1 localhost\r\n')
    return dict(os.environ, CCS_WORK=os.path.join(d, 'work'), CCS_HOSTS_PATH=hosts, PYTHONIOENCODING='utf-8'), hosts


def ccs(env, *args, timeout=120):
    r = subprocess.run([sys.executable, CCS, *args], capture_output=True, text=True, errors='replace', env=env, timeout=timeout); return r.returncode, r.stdout, r.stderr


class ArgvTests(unittest.TestCase):
    def test_source_runs_the_script_with_the_same_python(self):
        a = launch.argv_for('ccsproxy', '--port', 80, frozen=False, executable='C:\\py\\python.exe')
        self.assertEqual(a, ['C:\\py\\python.exe', os.path.join(paths.TOOLS, 'ccsproxy.py'), '--port', '80'])

    def test_packaged_build_calls_the_console_exe_with_the_tool_name(self):
        d = tempfile.mkdtemp(dir=TMP); gui = os.path.join(d, launch.GUI_EXE); cli = os.path.join(d, launch.CLI_EXE); open(gui, 'w').close(); open(cli, 'w').close()
        self.assertEqual(launch.argv_for('ccsmirror', 'run', 3, frozen=True, executable=gui), [cli, '--ccs-run', 'ccsmirror', 'run', '3'])
        self.assertEqual(launch.gui_argv(frozen=True, executable=gui), [gui])
        self.assertEqual(launch.cli_exe(True, gui), cli)

    def test_every_tool_name_is_known_and_unknown_names_are_refused(self):
        for n in launch.TOOLS: self.assertTrue(os.path.exists(os.path.join(TOOLS, n + '.py')), n)           # no tool listed that does not exist
        for n in launch.INTERNAL: launch.argv_for(n, frozen=True, executable='x.exe')
        for bad in ('', 'ccsgui', '../ccsproxy', 'evil'):
            with self.assertRaises(ValueError): launch.argv_for(bad)

    def test_helpers_are_started_through_argv_for(self):
        import re
        for f in ('ccslib/proxyctl.py', 'ccslib/mirrorctl.py', 'ccslib/session.py', 'ccshosts.py', 'ccsgui.py'):
            src = open(os.path.join(TOOLS, f), encoding='utf-8').read()
            self.assertIsNone(re.search(r"\[paths\.PY,|\[sys\.executable, os\.path", src), f)               # nothing may still build "python script.py" by hand

    def test_gui_argv_from_source_names_the_script(self):
        a = launch.gui_argv(frozen=False, executable=sys.executable); self.assertTrue(a[-1].endswith('ccsgui.py'))


class WorkDirTests(unittest.TestCase):
    def test_where_settings_go(self):
        d = tempfile.mkdtemp(dir=TMP); local = os.path.join(d, 'Local')
        self.assertEqual(paths.default_work(False, d, {}), os.path.join(d, 'work'))                                       # from source: tools/work
        self.assertEqual(paths.default_work(True, d, {'LOCALAPPDATA': local}), os.path.join(local, 'MW4TextureStreaming'))  # installed: survives updates and uninstalls
        open(os.path.join(d, 'portable.txt'), 'w').close(); self.assertEqual(paths.default_work(True, d, {'LOCALAPPDATA': local}), os.path.join(d, 'data'))     # the zip
        self.assertEqual(paths.default_work(True, d, {'CCS_WORK': 'X:\\w', 'LOCALAPPDATA': local}), 'X:\\w')              # an override always wins
        self.assertEqual(paths.default_work(False, d, {'CCS_WORK': 'X:\\w'}), 'X:\\w')


class DispatcherTests(unittest.TestCase):
    def test_version_and_unknown_tool(self):
        env, _ = env_for('v'); c, out, _ = ccs(env, '--version'); self.assertEqual((c, out.strip()), (0, version.USER_AGENT))
        c, _, err = ccs(env, '--ccs-run', 'nonsense'); self.assertEqual(c, 2); self.assertIn('unknown tool', err)
        c, _, err = ccs(env, '--ccs-run'); self.assertEqual(c, 2); self.assertIn('usage', err)

    def test_a_tool_runs_with_its_arguments_and_exit_code(self):
        env, hosts = env_for('t'); c, out, _ = ccs(env, '--ccs-run', 'ccshosts', 'status', '--json'); res = json.loads(out); self.assertEqual((c, res['state']), (0, 'ABSENT'))
        c, out, _ = ccs(env, '--ccs-run', 'ccshosts', 'apply', '--no-flush'); self.assertEqual(c, 0); self.assertIn('cod-assets.cdn.callofduty.com', open(hosts).read())
        c, _, err = ccs(env, '--ccs-run', 'ccsproxy', '--no-such-flag'); self.assertEqual(c, 2); self.assertIn('unrecognized arguments', err)               # argparse's exit code comes through
        c, out, _ = ccs(env, '--ccs-run', 'ccsproxy', '--version'); self.assertEqual((c, out.strip().split('\n')[0]), (0, version.USER_AGENT.split(' ')[0]))

    def test_a_tool_started_by_argv_for_behaves_like_the_dispatcher(self):
        env, _ = env_for('a'); r = subprocess.run(launch.argv_for('ccshosts', 'status', '--json'), capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(json.loads(r.stdout)['state'], 'ABSENT')


class UninstallPrepTests(unittest.TestCase):
    def test_status_exit_code_reports_hosts_and_helpers(self):
        env, hosts = env_for('u'); prep = lambda *a: ccs(env, '--ccs-run', 'uninstall-prep', *a)
        c, out, _ = prep('status', '--json'); s = json.loads(out); self.assertEqual((c, s['hosts_present'], s['helpers_running']), (0, False, []))
        self.assertTrue(s['data_dir'].endswith('work'))
        ccs(env, '--ccs-run', 'ccshosts', 'apply', '--no-flush'); c, out, _ = prep('status', '--json'); self.assertEqual((c, json.loads(out)['hosts_present']), (1, True))
        code = ("import sys; sys.path.insert(0, %r); from ccslib import procs, paths; import time; "
                "procs.start('dummy', [sys.executable, '-c', 'import time; time.sleep(120)'], paths.WORK + '/dummy.out')") % TOOLS
        subprocess.run([sys.executable, '-c', code], env=env, check=True, timeout=60)
        try:
            c, out, _ = prep('status', '--json'); s = json.loads(out); self.assertEqual((c, s['helpers_running']), (3, ['dummy']))                 # both bits
            c, out, _ = prep('stop-helpers'); self.assertEqual(c, 0); self.assertIn('dummy', out)
            c, out, _ = prep('status', '--json'); self.assertEqual((c, json.loads(out)['helpers_running']), (1, []))
            c, out, _ = prep('remove-hosts'); self.assertEqual(c, 0); self.assertNotIn('cod-assets', open(hosts).read())                       # our block is gone, the user's lines stay
            self.assertIn('localhost', open(hosts).read())
            c, out, _ = prep('remove-hosts'); self.assertEqual((c, out.strip()), (0, 'hosts: nothing to remove'))                                # nothing to do is not an error
            c, out, _ = prep('status', '--json'); self.assertEqual(c, 0)
        finally:
            prep('stop-helpers')

    def test_lines_added_by_hand_are_not_ours_to_remove(self):
        env, hosts = env_for('f'); open(hosts, 'a').write('127.0.0.1 cod-assets.cdn.callofduty.com\r\n'); prep = lambda *a: ccs(env, '--ccs-run', 'uninstall-prep', *a)
        c, out, _ = prep('status', '--json'); s = json.loads(out); self.assertEqual((c, s['hosts_state'], s['hosts_present']), (0, 'FOREIGN', False))
        c, out, _ = prep('remove-hosts'); self.assertEqual((c, out.strip()), (0, 'hosts: nothing to remove')); self.assertIn('cod-assets', open(hosts).read())

    def test_unknown_subcommand_is_an_error(self):
        env, _ = env_for('x'); c, _, err = ccs(env, '--ccs-run', 'uninstall-prep', 'format-c'); self.assertEqual(c, 2)


class WindowTests(unittest.TestCase):
    def test_the_window_holds_a_named_mutex_the_installer_can_see(self):
        import ctypes
        sys.path.insert(0, TOOLS); import ccsgui
        k = ctypes.windll.kernel32; k.OpenMutexW.restype = ctypes.c_void_p
        self.assertFalse(k.OpenMutexW(0x00100000, False, ccsgui.MUTEX_NAME))                                              # not there yet (SYNCHRONIZE access)
        ccsgui.hold_mutex(); h = k.OpenMutexW(0x00100000, False, ccsgui.MUTEX_NAME); self.assertTrue(h); k.CloseHandle(ctypes.c_void_p(h))

    def test_main_is_callable_with_arguments(self):
        import inspect; sys.path.insert(0, TOOLS); import ccsgui
        self.assertEqual(list(inspect.signature(ccsgui.main).parameters), ['argv'])

    def test_selfcheck_starts_and_stops_its_helpers_and_refuses_when_a_session_runs(self):
        env, _ = env_for('s'); c, out, _ = ccs(env, '--ccs-run', 'selfcheck', timeout=180); self.assertEqual(c, 0, out); self.assertIn('all fine', out); self.assertIn('shortcut starts', out)
        code = ("import sys; sys.path.insert(0, %r); from ccslib import procs, paths; "
                "procs.start('proxy', [sys.executable, '-c', 'import time; time.sleep(120)'], paths.WORK + '/p.out')") % TOOLS
        subprocess.run([sys.executable, '-c', code], env=env, check=True, timeout=60)
        try:
            c, out, _ = ccs(env, '--ccs-run', 'selfcheck'); self.assertEqual(c, 4); self.assertIn('stop it first', out)                                    # never stops somebody's real session
            c, out, _ = ccs(env, '--ccs-run', 'uninstall-prep', 'status', '--json'); self.assertEqual(json.loads(out)['helpers_running'], ['proxy'])
        finally:
            ccs(env, '--ccs-run', 'uninstall-prep', 'stop-helpers')


if __name__ == '__main__':
    unittest.main()
