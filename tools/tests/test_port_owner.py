"""Tests for a port that Windows itself holds (the System process, pid 4, behind IIS and other web services): no fix offers to end it, the Doctor says what holds it and can stop the web
service, and a fix never reports success when nothing was freed. Everything is faked: no process is ended, no service is stopped.
"""
import itertools, os, subprocess, sys, types, unittest
from unittest import mock

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, TOOLS)
from ccslib import config, doctor, guide, home, procs, session
from test_guide import BASE

SYSTEM = dict(addr='0.0.0.0', pid=4, name='System')


def cp(out='', rc=0, err=''): return subprocess.CompletedProcess([], rc, stdout=out, stderr=err)


class ProtectedTests(unittest.TestCase):
    def test_windows_itself_is_protected_and_ordinary_programs_are_not(self):
        for o in (dict(pid=4, name='System'), dict(pid=0, name='?'), dict(pid=900, name='svchost.exe'), dict(pid=9, name='LSASS.EXE'), dict(pid=5, name='System')): self.assertTrue(procs.is_protected(o), o)
        for o in (dict(pid=1234, name='nginx.exe'), dict(pid=77, name='python.exe'), dict(pid=88, name='?'), dict(pid=88, name=None)): self.assertFalse(procs.is_protected(o), o)

    def test_service_state_is_read_by_number_so_any_language_works(self):
        self.assertTrue(procs.service_running('W3SVC', lambda *a, **k: cp('SERVICE_NAME: W3SVC\r\n        STATE              : 4  RUNNING\r\n')))
        self.assertTrue(procs.service_running('W3SVC', lambda *a, **k: cp('        STATE              : 4  AUSGEFÜHRT\r\n')))
        self.assertFalse(procs.service_running('W3SVC', lambda *a, **k: cp('        STATE              : 1  STOPPED\r\n')))
        self.assertFalse(procs.service_running('Nope', lambda *a, **k: cp('', 1060, 'The specified service does not exist as an installed service.')))
        def boom(*a, **k): raise OSError('no sc')
        self.assertFalse(procs.service_running('W3SVC', boom))

    def test_only_running_known_services_are_listed(self):
        def run(argv, **k): return cp('        STATE              : 4  RUNNING\r\n' if argv[2] in ('W3SVC', 'PeerDistSvc') else '        STATE              : 1  STOPPED\r\n')
        self.assertEqual(procs.http_services(run), [('W3SVC', 'World Wide Web Publishing Service'), ('PeerDistSvc', 'BranchCache')])


class DoctorPortTests(unittest.TestCase):
    def check(self, owners, services=()):
        cfg = config.load(); cfg['proxy']['port'] = 80
        with mock.patch.object(procs, 'port_owner', return_value=owners), mock.patch.object(procs, 'http_services', return_value=list(services)), mock.patch.object(procs, 'status', return_value=dict(alive=False, pid=None)):
            return doctor.check_port(cfg)

    def test_system_with_a_running_web_service_offers_to_stop_that_service_only(self):
        r = self.check([SYSTEM], [('W3SVC', 'World Wide Web Publishing Service')])
        self.assertEqual(r['level'], 'fail'); self.assertEqual(r['fix'], ('stop_service', 'W3SVC')); self.assertIn('Windows itself', r['detail']); self.assertIn('World Wide Web Publishing Service', r['detail']); self.assertIn('pid 4', r['detail'])

    def test_system_without_a_known_service_explains_instead_of_offering_a_kill(self):
        r = self.check([SYSTEM]); self.assertEqual(r['level'], 'fail'); self.assertIsNone(r['fix']); self.assertIn('netsh http show servicestate', r['detail']); self.assertIn('cannot be ended', r['detail'])

    def test_an_ordinary_program_still_gets_the_old_fix(self):
        r = self.check([dict(addr='127.0.0.1', pid=1234, name='nginx.exe')]); self.assertEqual(r['fix'], ('kill_port_owner', [(1234, 'nginx.exe')])); self.assertIn('taken by nginx.exe pid 1234', r['detail'])

    def test_a_free_port_and_our_own_proxy_are_unchanged(self):
        self.assertEqual(self.check([])['level'], 'ok')


class FixTests(unittest.TestCase):
    def test_a_kill_of_windows_itself_is_refused_and_nothing_is_run(self):
        with mock.patch.object(session.subprocess, 'run') as run, mock.patch.object(procs, 'port_owner', return_value=[SYSTEM]):
            ok, msg = session.run_fix(config.load(), ('kill_port_owner', [(4, 'System')]), lambda m: None)
        self.assertFalse(ok); self.assertIn('part of Windows', msg); run.assert_not_called()

    def test_a_failed_kill_is_not_reported_as_success(self):
        with mock.patch.object(session.subprocess, 'run', return_value=cp('', 1, 'ERROR: The process could not be terminated.')), mock.patch.object(procs, 'port_owner', return_value=[]):
            ok, msg = session.run_fix(config.load(), ('kill_port_owner', [(1234, 'nginx.exe')]), lambda m: None)
        self.assertFalse(ok); self.assertIn('could not free the port', msg); self.assertIn('nginx.exe pid 1234', msg)

    def test_a_kill_that_leaves_the_port_held_is_not_success_either(self):
        owner = dict(addr='0.0.0.0', pid=1234, name='nginx.exe')
        with mock.patch.object(session.subprocess, 'run', return_value=cp()), mock.patch.object(procs, 'port_owner', return_value=[owner]), mock.patch.object(session.time, 'sleep', lambda s: None), \
                mock.patch.object(session.time, 'time', side_effect=itertools.count(0, 2)):
            ok, msg = session.run_fix(config.load(), ('kill_port_owner', [(1234, 'nginx.exe')]), lambda m: None)
        self.assertFalse(ok); self.assertIn('still holds it', msg)

    def test_stop_service_succeeds_only_when_the_port_is_free(self):
        said = []
        with mock.patch.object(procs, 'run_elevated', return_value=0) as el, mock.patch.object(procs, 'service_running', return_value=False), mock.patch.object(procs, 'port_owner', return_value=[]):
            ok, msg = session.run_fix(config.load(), ('stop_service', 'W3SVC'), said.append)
        self.assertTrue(ok); self.assertIn('sc start W3SVC', msg); el.assert_called_once_with(['sc.exe', 'stop', 'W3SVC'])

    def test_stop_service_reports_a_declined_prompt_and_a_port_that_stays_taken(self):
        with mock.patch.object(procs, 'run_elevated', return_value=None):
            ok, msg = session.run_fix(config.load(), ('stop_service', 'W3SVC'), lambda m: None)
        self.assertFalse(ok); self.assertIn('declined', msg)
        with mock.patch.object(procs, 'run_elevated', return_value=0), mock.patch.object(procs, 'service_running', return_value=False), mock.patch.object(procs, 'port_owner', return_value=[SYSTEM]), \
                mock.patch.object(session.time, 'sleep', lambda s: None), mock.patch.object(session.time, 'time', side_effect=itertools.count(0, 10)):
            ok, msg = session.run_fix(config.load(), ('stop_service', 'W3SVC'), lambda m: None)
        self.assertFalse(ok); self.assertIn('still in use', msg)

    def test_only_known_web_services_can_be_stopped(self):
        with mock.patch.object(procs, 'run_elevated') as el:
            ok, msg = session.run_fix(config.load(), ('stop_service', 'WinDefend'), lambda m: None)
        self.assertFalse(ok); el.assert_not_called()


class HomeTests(unittest.TestCase):
    def alert(self, name):
        return home._preflight_alert(guide.new_state(), dict(BASE, blocked_by=name, port=80))

    def test_system_has_its_own_wording(self):
        a = self.alert('System'); self.assertEqual(a['id'], 'port_busy'); self.assertIn('Windows', a['title']); self.assertIn('IIS', a['text']); self.assertEqual([x[0] for x in a['actions']], ['open_check'])

    def test_other_programs_keep_the_old_wording(self):
        a = self.alert('nginx.exe'); self.assertEqual(a['title'], 'Another program is using port 80'); self.assertIn('nginx.exe', a['text'])


if __name__ == '__main__': unittest.main()
