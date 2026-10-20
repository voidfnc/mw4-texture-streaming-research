"""Tests that keep the packaging files consistent with the code and with the version: the version lives in tools/ccslib/version.py only, and the installer script, the build
script, the exe names, the mutex, the workflow and the build requirements must agree with it and with each other. File checks only: nothing is built or installed here
(packaging/build.py and packaging/test_installer.py do that, in CI and by hand)."""
import importlib.util, os, re, subprocess, sys, tempfile, unittest

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
REPO = os.path.abspath(os.path.join(TOOLS, '..'))
PKG = os.path.join(REPO, 'packaging')
sys.path.insert(0, TOOLS)
from ccslib import launch, version


def read(*p): return open(os.path.join(REPO, *p), encoding='utf-8').read()


def load(name, *p):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, *p)); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


@unittest.skipUnless(os.path.isdir(PKG), 'not a full checkout')
class VersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.build = load('ccs_build', 'packaging', 'build.py')

    def test_the_build_reads_the_version_from_version_py_and_nowhere_else(self):
        self.assertEqual(self.build.read_version(), version.__version__)
        self.assertEqual(self.build.numeric('0.1.3-beta'), (0, 1, 3, 0)); self.assertEqual(self.build.numeric('1.2'), (1, 2, 0, 0)); self.assertEqual(self.build.numeric('2.0.1.7-rc1'), (2, 0, 1, 7))
        info = self.build.version_info(version.__version__, 'x.exe', 'd'); self.assertIn(f"StringStruct('ProductVersion', '{version.__version__}')", info); self.assertIn(str(self.build.numeric(version.__version__)), info)

    def test_no_version_number_is_typed_into_the_installer_script(self):
        iss = read('packaging', 'installer.iss'); self.assertIsNone(re.search(r'\d+\.\d+\.\d+', iss), 'a literal version in installer.iss')
        for token in ('AppVersion={#AppVersion}', 'VersionInfoVersion={#NumericVersion}', 'OutputBaseFilename=MW4-Texture-Streaming-{#AppVersion}-Setup'): self.assertIn(token, iss)

    def test_release_notes_come_from_the_changelog_section_of_the_current_version(self):
        notes = self.build.release_notes(version.__version__); self.assertTrue(notes.strip()); self.assertNotIn('\n## ', notes); self.assertIn(notes.strip().splitlines()[0], read('CHANGELOG.md'))
        with self.assertRaises(SystemExit): self.build.release_notes('9.9.9')

    def test_a_tag_that_does_not_match_the_version_stops_the_build(self):
        out = tempfile.mkdtemp(prefix='ccsbuild_')
        r = subprocess.run([sys.executable, os.path.join(PKG, 'build.py'), '--out', out, '--expect-tag', 'v0.0.0'], capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0); self.assertIn('does not match', r.stderr + r.stdout)
        self.assertNotIn('PyInstaller', r.stdout)                                                          # it stopped before building anything


@unittest.skipUnless(os.path.isdir(PKG), 'not a full checkout')
class ConsistencyTests(unittest.TestCase):
    def test_names_agree_between_code_installer_spec_and_scripts(self):
        iss, spec = read('packaging', 'installer.iss'), read('packaging', 'ccs.spec')
        self.assertIn(f'#define AppExe "{launch.GUI_EXE}"', iss); self.assertIn(f'#define CliExe "{launch.CLI_EXE}"', iss)
        self.assertIn(f"name='{launch.GUI_EXE[:-4]}'", spec); self.assertIn(f"name='{launch.CLI_EXE[:-4]}'", spec)
        sys.path.insert(0, TOOLS); import ccsgui
        self.assertIn(f'AppMutex={ccsgui.MUTEX_NAME}', iss)                                                # the window holds this mutex; setup and uninstall look for it
        self.assertIn(launch.CLI_EXE, read('packaging', 'Restore hosts.bat')); self.assertIn(launch.GUI_EXE, read('packaging', 'START HERE.txt'))
        self.assertTrue(os.path.exists(os.path.join(PKG, 'app.ico')))

    def test_installer_test_and_installer_use_the_same_app_id(self):
        guid = re.search(r'AppId=\{(\{[0-9A-F-]{36}\})', read('packaging', 'installer.iss')).group(1); self.assertIn(guid + '_is1', read('packaging', 'test_installer.py'))

    def test_the_hooks_the_installer_calls_exist_with_the_exit_codes_it_expects(self):
        iss = read('packaging', 'installer.iss')
        for cmd in ('status', 'stop-helpers', 'remove-hosts'): self.assertIn(f"'{cmd}'", iss)
        self.assertIn('(Status and 2)', iss); self.assertIn('(Status and 1)', iss)
        from ccslib import uninstall
        self.assertEqual((uninstall.HOSTS_PRESENT, uninstall.HELPERS_RUNNING), (1, 2))
        self.assertIn('uninstall-prep', launch.INTERNAL)

    def test_spec_hidden_imports_follow_the_launcher(self):
        self.assertIn('launch.TOOLS', read('packaging', 'ccs.spec')); self.assertIn('launch.INTERNAL', read('packaging', 'ccs.spec'))

    def test_build_requirements_are_exact_and_hashed(self):
        reqs = [l for l in read('packaging', 'requirements-build.txt').split('\n') if l and not l.startswith('#')]
        names = [l for l in reqs if '==' in l]; hashes = [l for l in reqs if '--hash=sha256:' in l]
        self.assertTrue(names); self.assertEqual(len(names), len(hashes))
        for l in names: self.assertRegex(l, r'^[A-Za-z0-9_.-]+==\d[\w.]* \\$')
        for l in hashes: self.assertRegex(l.strip(), r'^--hash=sha256:[0-9a-f]{64}$')

    def test_the_workflow_pins_every_action_to_a_commit_and_checks_the_tag(self):
        wf = read('.github', 'workflows', 'release.yml')
        for line in re.findall(r'uses:\s*(\S+)', wf): self.assertRegex(line, r'@[0-9a-f]{40}$', line)
        self.assertIn('--require-hashes -r packaging/requirements-build.txt', wf); self.assertIn('--expect-tag', wf); self.assertIn('--draft', wf)     # tags make a draft, never a published release
        self.assertIn('test_installer.py', wf)

    def test_only_published_docs_are_packed_next_to_the_program(self):
        build = load('ccs_build2', 'packaging', 'build.py')
        for f in build.DOCS: self.assertTrue(os.path.exists(os.path.join(REPO, 'docs', f)), f)
        tracked = subprocess.run(['git', 'ls-files', 'docs'], cwd=REPO, capture_output=True, text=True).stdout.split()
        if tracked: self.assertEqual({os.path.basename(t) for t in tracked if t.endswith('.md')}, set(build.DOCS))             # a new public doc must be added to the package, and nothing else gets in

    def test_packaging_files_are_not_dropped_by_the_whitelist(self):
        ignore = read('.gitignore')
        for line in ('!/packaging/', '/packaging/out/'): self.assertIn(line, ignore)


if __name__ == '__main__':
    unittest.main()
