"""i18n.py - the window's languages.

The program's own English text is the key: `t("Turn on")`. A language is one file, lang/<code>.json = {"English text": "translation"}. Text that was built with
an f-string is stored as a template ({0}, {1} ... in order of appearance) and matched back, so "12 GiB on C:" finds "{0} GiB on {1}" and the translation can move the
parts around. Anything missing falls back to the English text, so an untranslated string never breaks the window.

install() hooks tkinter once: every `text=` handed to a widget or a canvas is translated on the way in, so the window code keeps its plain English strings.
Logs, saved reports, tool names and paths are not routed through here on purpose (they stay English so bug reports stay comparable).
"""
import json, os, re, sys, locale

DEFAULT = 'en'
LANGUAGES = (('en', 'English'), ('ru', '\u0420\u0443\u0441\u0441\u043a\u0438\u0439'), ('zh-CN', '\u7b80\u4f53\u4e2d\u6587'), ('es', 'Espa\u00f1ol'), ('fr', 'Fran\u00e7ais'), ('de', 'Deutsch'),
             ('pt-BR', 'Portugu\u00eas (Brasil)'), ('tr', 'T\u00fcrk\u00e7e'), ('pl', 'Polski'), ('ja', '\u65e5\u672c\u8a9e'), ('ko', '\ud55c\uad6d\uc5b4'), ('it', 'Italiano'))
CODES = tuple(c for c, _ in LANGUAGES)
NAMES = dict(LANGUAGES)
AUTO = 'auto'
MIN_LITERAL = 5                       # a template needs at least this many fixed characters, or it would match almost anything
_PRIMARY = {0x19: 'ru', 0x04: 'zh-CN', 0x0a: 'es', 0x0c: 'fr', 0x07: 'de', 0x16: 'pt-BR', 0x1f: 'tr', 0x15: 'pl', 0x11: 'ja', 0x12: 'ko', 0x10: 'it', 0x09: 'en'}   # Windows primary language id -> code
_cur = DEFAULT
_exact = {}
_upper = {}                          # UPPER-CASE spelling of an exact text -> its translation, upper-cased (section titles are drawn in capitals)
_tmpl = {}                           # template text -> translation, for t(template, *args)
_patterns = []                        # (compiled regex, translation) from templates
_cache = {}
_PH = re.compile(r'\{(\d+)\}')


def lang_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(here, 'lang'), os.path.join(getattr(sys, '_MEIPASS', ''), 'ccslib', 'lang')):
        if os.path.isdir(d): return d
    return os.path.join(here, 'lang')


def detect():
    """The language of Windows' display (what the installer also uses); English when it is not one we ship."""
    try:
        import ctypes
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except Exception:
        try: lid = locale.windows_locale and next((k for k, v in locale.windows_locale.items() if v == locale.getdefaultlocale()[0]), 0)
        except Exception: lid = 0
    return _PRIMARY.get((lid or 0) & 0x3ff, DEFAULT)


def installer_language():
    """The language picked in the installer (language.txt next to the program), '' when there is none."""
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), 'language.txt') if getattr(sys, 'frozen', False) else ''
        with open(p, encoding='utf-8-sig') as f: c = f.read().strip()
    except OSError: return ''
    return c if c in CODES else ''


def resolve(setting):
    """The setting ('auto' or a code) -> a code we have. Automatic = the language chosen in the installer, else the Windows display language."""
    env = os.environ.get('CCS_LANG')                                         # CCS_LANG=en|de|... overrides the setting (support, tests)
    if env: setting = env
    if setting in (None, '', AUTO): return installer_language() or detect()
    return setting if setting in CODES else DEFAULT


def _template_regex(key):
    parts = _PH.split(key); rx = ''
    for n, p in enumerate(parts): rx += re.escape(p) if n % 2 == 0 else '(.+?)'
    return re.compile(rx + r'\Z', re.S)


def load(code):
    """-> {english: translation} for a code; {} for English or a missing / broken file."""
    if code == DEFAULT: return {}
    try:
        with open(os.path.join(lang_dir(), f'{code}.json'), encoding='utf-8') as f: d = json.load(f)
    except (OSError, ValueError): return {}
    return {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, str) and v}


def set_language(code):
    global _cur, _exact, _tmpl, _upper, _patterns
    _cur = code if code in CODES else DEFAULT; _cache.clear(); _exact = {}; _tmpl = {}; _upper = {}; _patterns = []
    for k, v in load(_cur).items():
        if _PH.search(k):
            _tmpl[k] = v
            if sum(len(p) for p in _PH.split(k)[::2]) >= MIN_LITERAL: _patterns.append((_template_regex(k), v))
        else: _exact[k] = v
    for k, v in _exact.items():
        if k != k.upper() and len(k) > 2: _upper.setdefault(k.upper(), v.upper())
    return _cur


def current(): return _cur


def t(s, *args):
    """Translate. `args` fill {0}, {1} ... of a template written with t("... {0} ...", x)."""
    if not isinstance(s, str) or not s or _cur == DEFAULT: return s.format(*args) if args and isinstance(s, str) else s
    if args:
        v = _exact.get(s) or _tmpl.get(s) or s
        try: return v.format(*args)
        except (IndexError, KeyError, ValueError): return s.format(*args)
    r = _cache.get(s)
    if r is not None: return r
    r = _exact.get(s)
    if r is None:
        for rx, v in _patterns:
            m = rx.match(s)
            if m:
                try: r = _PH.sub(lambda g: m.group(int(g.group(1)) + 1), v)
                except (IndexError, ValueError): r = None
                if r is not None: break
    if r is None and s == s.upper(): r = _upper.get(s)
    if r is None and s.startswith('▶ '): r = '▶ ' + t(s[2:])                    # a highlighted tab name ("> Report")
    if r is None: r = s
    if len(_cache) < 4000: _cache[s] = r
    return r


# ------------------------------------------------------------------------------------------------ the tkinter hook
_installed = False
_TEXT_KEYS = ('text', 'title', 'message', 'detail')       # widgets, canvas items and the standard dialogs


def install():
    """Translate every widget / canvas `text=` option (once per process)."""
    global _installed
    if _installed: return
    import tkinter
    orig = tkinter.Misc._options

    def _options(self, cnf, kw=None):
        if _cur != DEFAULT:
            if kw:
                kw = dict(kw)
                for k in _TEXT_KEYS:
                    if isinstance(kw.get(k), str): kw[k] = t(kw[k])
            if cnf and isinstance(cnf, dict):
                cnf = dict(cnf)
                for k in _TEXT_KEYS:
                    if isinstance(cnf.get(k), str): cnf[k] = t(cnf[k])
        return orig(self, cnf, kw)
    tkinter.Misc._options = _options
    from tkinter import ttk
    for name in ('add', 'insert', 'tab'):                                                  # a notebook formats its options itself
        def wrap(fn):
            def f(self, *a, **kw):
                if _cur != DEFAULT and isinstance(kw.get('text'), str): kw['text'] = t(kw['text'])
                return fn(self, *a, **kw)
            return f
        setattr(ttk.Notebook, name, wrap(getattr(ttk.Notebook, name)))
    _installed = True


def font_family_for(code, have, default):
    """A font that has the glyphs: Chinese / Japanese / Korean fall back to the Windows UI fonts for those scripts."""
    pick = {'zh-CN': ('Microsoft YaHei UI', 'Microsoft YaHei', 'SimSun'), 'ja': ('Yu Gothic UI', 'Meiryo UI', 'MS UI Gothic'), 'ko': ('Malgun Gothic', 'Gulim')}.get(code)
    if not pick: return default
    return next((f for f in pick if f in have), default)
