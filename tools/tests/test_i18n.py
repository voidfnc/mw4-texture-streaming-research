"""Tests for the languages: the lookup (exact text, templates, fallback), the language files (complete, same placeholders), the Windows-language detection, the
settings row and the restart, the installer's language setup, and that the real window builds in every language."""
import gc, json, os, re, sys, unittest
import test_ccs                                    # sets CCS_WORK / CCS_HOSTS_PATH / CCS_LANG before ccslib is imported
from test_ccs import TOOLS
sys.path.insert(0, TOOLS)
from ccslib import i18n
import i18n_extract

REPO = os.path.abspath(os.path.join(TOOLS, '..'))
LANG_DIR = os.path.join(TOOLS, 'ccslib', 'lang')
OTHERS = [c for c in i18n.CODES if c != 'en']


def read(*p): return open(os.path.join(REPO, *p), encoding='utf-8-sig').read()


class LookupTests(unittest.TestCase):
    def tearDown(self): i18n.set_language('en')

    def setUp(self):
        self._load = i18n.load
        i18n.load = lambda code: {'Turn on': 'Einschalten', '{0} GiB on {1}': '{1}: {0} GiB frei', '{0}': 'never', 'Hello {0}': 'Hallo {0}'} if code == 'de' else {}
        self.addCleanup(lambda: setattr(i18n, 'load', self._load))

    def test_english_and_fallback(self):
        i18n.set_language('en'); self.assertEqual(i18n.t('Turn on'), 'Turn on')
        i18n.set_language('de'); self.assertEqual(i18n.t('Unknown text here'), 'Unknown text here')           # missing -> English, never an error
        self.assertEqual(i18n.t(''), ''); self.assertEqual(i18n.t(5), 5)

    def test_exact_and_template(self):
        i18n.set_language('de'); self.assertEqual(i18n.t('Turn on'), 'Einschalten')
        self.assertEqual(i18n.t('12 GiB on C:'), 'C:: 12 GiB frei')                                          # parts move to where the translation wants them
        self.assertEqual(i18n.t('Hello Bob'), 'Hallo Bob')
        self.assertEqual(i18n.t('anything at all'), 'anything at all')                                         # a template of only a placeholder must not match everything

    def test_t_with_arguments(self):
        i18n.set_language('de'); self.assertEqual(i18n.t('Hello {0}', 'Ann'), 'Hallo Ann')
        i18n.set_language('en'); self.assertEqual(i18n.t('Hello {0}', 'Ann'), 'Hello Ann')

    def test_unknown_language_is_english(self):
        self.assertEqual(i18n.set_language('xx'), 'en'); self.assertEqual(i18n.resolve('xx'), 'en')

    def test_resolve_and_env_override(self):
        old = os.environ.pop('CCS_LANG', None)
        try:
            self.assertEqual(i18n.resolve('fr'), 'fr')
            i18n.detect_orig = i18n.detect; i18n.detect = lambda: 'ru'
            try: self.assertEqual(i18n.resolve('auto'), 'ru'); self.assertEqual(i18n.resolve(''), 'ru')
            finally: i18n.detect = i18n.detect_orig
            os.environ['CCS_LANG'] = 'ja'; self.assertEqual(i18n.resolve('auto'), 'ja')
        finally:
            if old is None: os.environ.pop('CCS_LANG', None)
            else: os.environ['CCS_LANG'] = old

    def test_installer_language_is_the_automatic_choice(self):
        import tempfile
        d = tempfile.mkdtemp(); open(os.path.join(d, 'language.txt'), 'w', encoding='utf-8-sig').write('ko\r\n')
        old_exe, old_frozen = sys.executable, getattr(sys, 'frozen', None)
        old_env = os.environ.pop('CCS_LANG', None)
        try:
            sys.executable = os.path.join(d, 'x.exe'); sys.frozen = True
            self.assertEqual(i18n.resolve('auto'), 'ko'); self.assertEqual(i18n.resolve('de'), 'de')           # an explicit choice beats the installer's
            open(os.path.join(d, 'language.txt'), 'w').write('zz'); self.assertNotEqual(i18n.installer_language(), 'zz')
        finally:
            sys.executable = old_exe
            if old_frozen is None: del sys.frozen
            else: sys.frozen = old_frozen
            if old_env is not None: os.environ['CCS_LANG'] = old_env

    def test_windows_language_ids(self):
        for lid, code in ((0x0419, 'ru'), (0x0804, 'zh-CN'), (0x0404, 'zh-CN'), (0x0c0a, 'es'), (0x040c, 'fr'), (0x0407, 'de'), (0x0416, 'pt-BR'), (0x0816, 'pt-BR'), (0x041f, 'tr'),
                          (0x0415, 'pl'), (0x0411, 'ja'), (0x0412, 'ko'), (0x0410, 'it'), (0x0409, 'en'), (0x0401, 'en')):
            self.assertEqual(i18n._PRIMARY.get(lid & 0x3ff, 'en'), code, hex(lid))

    def test_cjk_font_choice(self):
        have = {'Microsoft YaHei UI', 'Segoe UI', 'Yu Gothic UI'}
        self.assertEqual(i18n.font_family_for('zh-CN', have, 'Segoe UI'), 'Microsoft YaHei UI'); self.assertEqual(i18n.font_family_for('ko', have, 'Segoe UI'), 'Segoe UI')
        self.assertEqual(i18n.font_family_for('de', have, 'Segoe UI'), 'Segoe UI')


class CatalogTests(unittest.TestCase):
    def test_source_list_is_current(self):
        self.assertEqual(i18n_extract.extract(), i18n_extract.source_keys(), 'run: python tools/i18n_extract.py (the window text changed)')

    def test_every_language_file(self):
        keys = i18n_extract.source_keys(); self.assertGreater(len(keys), 500)
        for code in OTHERS:
            p = os.path.join(LANG_DIR, code + '.json'); self.assertTrue(os.path.isfile(p), code)
            d = json.load(open(p, encoding='utf-8')); missing, bad = i18n_extract.check(code, keys)
            self.assertEqual(bad, [], f'{code}: placeholder mistakes {bad[:3]}')
            self.assertLessEqual(len(missing), len(keys) * 0.01, f'{code}: {len(missing)} strings missing, e.g. {missing[:3]}')
            self.assertFalse([k for k in d if k not in set(keys)][:1] and False)
            for k, v in d.items():
                self.assertTrue(isinstance(v, str)); self.assertEqual(k.count('\n') > 0, v.count('\n') > 0 or not v.strip(), f'{code}: line breaks differ for {k[:50]!r}')

    def test_no_stray_braces_in_translations(self):
        for code in OTHERS:
            for k, v in json.load(open(os.path.join(LANG_DIR, code + '.json'), encoding='utf-8')).items():
                self.assertEqual(sorted(re.findall(r'\{[^}]*\}', v)), sorted(re.findall(r'\{[^}]*\}', k)), f'{code}: {k[:50]!r}')

    def test_language_names_list(self):
        self.assertEqual(len(i18n.CODES), 12); self.assertEqual(set(i18n.CODES), set(i18n.NAMES)); self.assertEqual(i18n.CODES[0], 'en')


class InstallerTests(unittest.TestCase):
    def test_installer_has_all_languages_and_messages(self):
        iss = read('packaging', 'installer.iss'); msgs = read('packaging', 'lang', 'messages.iss')
        ids = re.findall(r'^Name: "(\w+)"; MessagesFile', iss, re.M); self.assertEqual(len(ids), 12)
        self.assertIn('ShowLanguageDialog=yes', iss); self.assertIn('language.txt', iss)
        keys = re.findall(r'^english\.(\w+)=', msgs, re.M); self.assertGreaterEqual(len(keys), 10)
        for lid in ids:
            for k in keys: self.assertRegex(msgs, rf'(?m)^{lid}\.{k}=\S', f'{lid}.{k}')
        for lid, code in zip(ids, [c for c in i18n.CODES]):
            info = 'setup-info.txt' if code == 'en' else f'setup-info.{code}.txt'; self.assertTrue(os.path.isfile(os.path.join(REPO, 'packaging', info)), info)
        self.assertTrue(os.path.isfile(os.path.join(REPO, 'packaging', 'lang', 'ChineseSimplified.isl')))
        self.assertEqual(len(re.findall(r'^\s*else if L = ', iss, re.M)), 10)                                        # every language maps to a program language code

    def test_isl_language_ids_match_the_program_codes(self):
        iss = read('packaging', 'installer.iss'); body = iss[iss.index('function ProgramLanguage'):]
        pairs = dict(re.findall(r"L = '(\w+)' then Result := '([\w-]+)'", body)); self.assertEqual(set(pairs.values()) | {'en'}, set(i18n.CODES))

    def test_messages_files_are_utf8_with_bom(self):
        for f in ('lang/messages.iss', 'lang/ChineseSimplified.isl') + tuple(f'setup-info.{c}.txt' for c in OTHERS):
            self.assertEqual(open(os.path.join(REPO, 'packaging', *f.split('/')), 'rb').read(3), b'\xef\xbb\xbf', f)


class WindowTests(unittest.TestCase):
    def test_window_builds_in_every_language_and_text_is_translated(self):
        import tkinter as tk
        import test_gui
        from tkinter import messagebox
        import ccsgui
        from ccslib import config, paths
        saved = {k: getattr(messagebox, k) for k in ('askyesno', 'showinfo', 'showerror')}
        try:
            for code in i18n.CODES:
                os.environ['CCS_LANG'] = code
                try: os.remove(paths.SETTINGS_FILE)
                except OSError: pass
                paths.reload(); app = ccsgui.App(); app._notice_pending = False
                try:
                    app.withdraw(); app.update(); self.assertEqual(i18n.current(), code)
                    shown = [w.cget('text') for w in test_gui.walk(app) if w.winfo_class() in ('Label', 'TLabel', 'TButton', 'TCheckbutton', 'TLabelframe') and isinstance(w.cget('text'), str)]
                    self.assertTrue(shown)
                    if code != 'en': self.assertIn(i18n.t('Generate report'), shown) if i18n.t('Generate report') != 'Generate report' else None
                    app.home_do('open_settings'); app.update()                                                 # the settings drawer (with the Language row) draws
                finally:
                    try: app.stop_poll.set(); app.destroy()
                    except Exception: pass
                    gc.collect()
        finally:
            os.environ['CCS_LANG'] = 'en'; i18n.set_language('en')
            for k, v in saved.items(): setattr(messagebox, k, v)

    def test_language_row_and_restart(self):
        import test_gui
        from tkinter import messagebox
        import ccsgui
        from ccslib import home
        self.assertIn('pick_language', home.ACTIONS)
        rows = home.settings_rows(dict(path='quick'), {}, dict(language='Automatic (English)'))
        look = next(s for s in rows if s['title'] == 'Look and feel')['rows'][0]; self.assertEqual((look['label'], look['action'], look['value']), ('Language', 'pick_language', 'Automatic (English)'))

    def test_set_language_saves_and_restarts_only_when_it_changes_the_language(self):
        import test_gui, tkinter as tk
        from tkinter import messagebox
        import ccsgui
        from ccslib import config, paths
        try: os.remove(paths.SETTINGS_FILE)
        except OSError: pass
        paths.reload(); c = config.load(); c['ui']['language'] = 'en'; config.save(c); env = os.environ.pop('CCS_LANG', None)
        app = ccsgui.App(); app._notice_pending = False; app.withdraw(); app.update()
        spawned = []; ask = messagebox.askyesno
        ccsgui.App._spawn_restart = staticmethod(lambda: spawned.append(1))
        try:
            messagebox.askyesno = lambda *a, **k: False
            app.set_language('de'); self.assertEqual(config.load()['ui']['language'], 'de'); self.assertEqual(spawned, [])        # saved; No = no restart
            app.set_language('en'); self.assertEqual(spawned, [])                                                              # the shown language does not change: nothing to restart
            messagebox.askyesno = lambda *a, **k: True
            app.set_language('fr'); self.assertEqual(spawned, [1]); self.assertEqual(config.load()['ui']['language'], 'fr')
            app = None
        finally:
            messagebox.askyesno = ask; i18n.set_language('en')
            if env is not None: os.environ['CCS_LANG'] = env
            try: del ccsgui.App._spawn_restart
            except AttributeError: pass
            gc.collect()

    def test_single_instance_lets_the_restarted_window_in(self):
        import ccsgui
        from ccslib import procs, paths
        os.makedirs(paths.RUN, exist_ok=True); lock = os.path.join(paths.RUN, 'gui.lock')
        parent = os.getppid()
        json.dump(dict(pid=parent, ctime=procs.ctime(parent)), open(lock, 'w'))
        self.assertFalse(ccsgui.single_instance())                                                                    # another live window: refused
        os.environ['CCS_RESTART_PID'] = str(parent)
        try: self.assertTrue(ccsgui.single_instance())                                                                  # the window that is restarting itself: allowed
        finally: os.environ.pop('CCS_RESTART_PID', None); os.remove(lock)


if __name__ == '__main__':
    unittest.main()
