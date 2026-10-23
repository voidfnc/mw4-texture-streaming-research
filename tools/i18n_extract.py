#!/usr/bin/env python3
"""i18n_extract.py - list the English strings of the window (the keys of every language file) and check the language files against them.

  python tools/i18n_extract.py            writes tools/ccslib/lang/_source.json (the list of keys, sorted)
  python tools/i18n_extract.py --check    lists keys a language misses and placeholder mistakes (exit 1 on a mistake)
  python tools/i18n_extract.py --missing de   writes the keys 'de' still lacks, as JSON {english: ""}, to stdout

A key is a string literal (or an f-string, with {0}, {1} ... for its parts) in the window's code that reads like text for people. Logs (say / print / logging),
docstrings, comments, file paths, regexes and identifiers are left out.
"""
import ast, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LANG = os.path.join(HERE, 'ccslib', 'lang')
FILES = ['ccsgui.py'] + [os.path.join('ccslib', f) for f in ('home.py', 'homeui.py', 'guide.py', 'ui.py', 'doctor.py', 'gamefix.py', 'pack.py', 'upstream.py', 'uninstall.py', 'shortcut.py',
                                                              'session.py', 'cachectl.py', 'selfcheck.py', 'logtail.py')]
SKIP_CALLS = {'say', 'print', 'debug', 'info', 'warning', 'error', 'write', 'log', 'startswith', 'endswith', 'get', 'pop', 'setdefault', 'index', 'find', 'count', 'split', 'rsplit', 'strip', 'lstrip',
              'rstrip', 'join', 'replace', 'encode', 'decode', 'open', 'exists', 'isfile', 'isdir', 'getenv', 'compile', 'match', 'search', 'sub', 'findall', 'fullmatch', 'tag_configure',
              'bind', 'protocol', 'style', 'run', 'Popen', 'check_output', 'call', 'tag_add', 'tag_config', 'getattr', 'hasattr', 'setattr', 'register', 'query', 'resource', 'iconbitmap',
              'wm_attributes', 'attributes', 'format_map', 'dumps', 'loads', 'load', 'dump', 'ArgumentParser', 'add_argument', 'add_parser', 'Variable', 'StringVar', 'IntVar', 'BooleanVar'}


# short words the window shows as state values (they would be skipped as 'one lower-case word')
EXTRA = ('closed', 'off', 'stopped', 'running', 'none', 'calculating...', '{0} free', 'Not needed')


def _skip(s):
    if len(s) < 3 or len(s) > 700 or not re.search(r'[A-Za-z]{2}', s): return True
    if ' ' not in s.strip() and not re.match(r'^[A-Z\u00c0-\u024f]', s): return True                                                  # one lower-case word: a key / option / identifier
    if re.match(r'^(<|--|-[a-z]\b|\\|%|\.|#[0-9a-fA-F]{3,8}$|https?:|[A-Za-z]:\\|HK[A-Z]{2}|SOFTWARE)', s): return True
    if re.search(r'\\[dwsbDWSB]|\(\?[:=!<]|\[\^|\.\*|^\^|\$$|\|\|', s): return True                                                  # regex
    if re.search(r'^\s*(import |def |class |SELECT |if |for )', s): return True
    if s.isupper() and ' ' not in s: return True
    if re.fullmatch(r'[A-Za-z0-9_]+\.[A-Za-z0-9_.]+', s): return True                                                              # a file name / dotted name
    if re.fullmatch(r'[A-Za-z0-9_]+', s) and not s[0].isupper(): return True
    if re.fullmatch(r'[A-Z][A-Za-z0-9_]*\.[A-Z]?[A-Za-z]*', s): return True                                                        # a ttk style name (Accent.TButton)
    return False


def _fstring(node):
    out = ''; n = 0
    for v in node.values:
        if isinstance(v, ast.Constant): out += str(v.value)
        else: out += '{%d}' % n; n += 1
    return out


class V(ast.NodeVisitor):
    def __init__(self): self.keys = set()

    def visit_Expr(self, node):                                                                                                    # docstrings and bare statements
        if isinstance(node.value, ast.Constant): return
        self.generic_visit(node)

    def visit_Call(self, node):
        f = node.func; name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ''
        if name in SKIP_CALLS:
            if isinstance(f, ast.Attribute) and not isinstance(f.value, ast.Constant): self.visit(f.value)                         # {...}.get(x): the table is text, `', '.join` is not
            args = list(node.args) + [k.value for k in node.keywords]
            if name in ('get', 'pop', 'setdefault'): self.visit_default(args[1:])                                                    # d.get(key, 'a default text')
            for a in args:                                                                                                         # `say("...")`: the argument is not UI text, a nested call still is
                if not isinstance(a, (ast.Constant, ast.JoinedStr)): self.visit(a)
            return
        self.generic_visit(node)

    def visit_Subscript(self, node):                                                                                               # d['key']
        self.visit(node.value)
        if not isinstance(node.slice, (ast.Constant, ast.JoinedStr)): self.visit(node.slice)

    def visit_Compare(self, node):                                                                                                 # x == 'name': a comparison, not text
        for c in [node.left] + node.comparators:
            if not isinstance(c, ast.Constant): self.visit(c)

    def visit_Constant(self, node):
        if isinstance(node.value, str) and not _skip(node.value): self.keys_add(node.value)

    def keys_add(self, s): self.keys.add(s)

    def visit_default(self, nodes):
        for a in nodes:
            if isinstance(a, (ast.Constant, ast.JoinedStr)): self.visit(a)

    def visit_JoinedStr(self, node):
        s = _fstring(node); plain = re.sub(r'\{\d+\}', '', s)
        if len(plain) >= 6 and not _skip(re.sub(r'\{\d+\}', 'x', s)): self.keys.add(s)
        for v in node.values:                                                                                                      # a nested conditional inside {...}
            if isinstance(v, ast.FormattedValue): self.visit(v.value)


def extract(root=None):
    root = root or HERE; keys = set(EXTRA)
    for f in FILES:
        p = os.path.join(root, f)
        if not os.path.isfile(p): continue
        v = V(); v.visit(ast.parse(open(p, encoding='utf-8').read())); keys |= v.keys
    return sorted(keys)


def source_keys():
    try: return json.load(open(os.path.join(LANG, '_source.json'), encoding='utf-8'))
    except (OSError, ValueError): return []


def placeholders(s): return sorted(re.findall(r'\{\d+\}', s))


def check(code, keys=None):
    """-> (missing keys, mistakes) for lang/<code>.json."""
    keys = keys or source_keys(); d = json.load(open(os.path.join(LANG, code + '.json'), encoding='utf-8'))
    missing = [k for k in keys if not d.get(k)]; bad = [(k, d[k]) for k in keys if d.get(k) and placeholders(k) != placeholders(d[k])]
    return missing, bad


def main(argv):
    try: sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError): pass
    if argv[:1] == ['--check']:
        rc = 0; keys = source_keys()
        for f in sorted(os.listdir(LANG)):
            if f.endswith('.json') and not f.startswith('_'):
                m, b = check(f[:-5], keys); print(f'{f[:-5]:6} keys={len(keys)} missing={len(m)} bad_placeholders={len(b)}')
                for k, v in b[:5]: print('   ', repr(k), '->', repr(v))
                rc |= bool(b)
        return rc
    if argv[:1] == ['--missing']:
        m, _ = check(argv[1]) if os.path.exists(os.path.join(LANG, argv[1] + '.json')) else (source_keys(), [])
        print(json.dumps({k: '' for k in m}, ensure_ascii=False, indent=0)); return 0
    keys = extract(); os.makedirs(LANG, exist_ok=True)
    json.dump(keys, open(os.path.join(LANG, '_source.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print(f'{len(keys)} strings -> {os.path.join(LANG, "_source.json")}'); return 0


if __name__ == '__main__': sys.exit(main(sys.argv[1:]))
