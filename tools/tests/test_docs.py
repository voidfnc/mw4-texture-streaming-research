"""Tests for the public documentation: the version number appears where it should, links and images exist, the screenshots are valid files, and the screenshot
tool's PNG writer is correct. No GUI, no network."""
import os, re, struct, subprocess, sys, unittest, zlib

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
REPO = os.path.abspath(os.path.join(TOOLS, '..'))
sys.path.insert(0, TOOLS)
from ccslib import version
import make_screenshots


def read(*p): return open(os.path.join(REPO, *p), encoding='utf-8').read()


def tracked_markdown():
    try: out = subprocess.run(['git', 'ls-files', '*.md'], cwd=REPO, capture_output=True, text=True, timeout=30).stdout.split()
    except (OSError, subprocess.SubprocessError): out = []
    return [f for f in out if os.path.isfile(os.path.join(REPO, f))]


def slug(heading): return re.sub(r'[^\w\- ]', '', re.sub(r'[`*_]', '', heading).strip().lower()).replace(' ', '-')


def decode_png(data):
    assert data[:8] == b'\x89PNG\r\n\x1a\n'; pos = 8; idat = b''; ihdr = None
    while pos < len(data):
        n, tag = struct.unpack('>I4s', data[pos:pos + 8]); body = data[pos + 8:pos + 8 + n]; crc = struct.unpack('>I', data[pos + 8 + n:pos + 12 + n])[0]
        assert zlib.crc32(tag + body) & 0xffffffff == crc, tag
        if tag == b'IHDR': ihdr = struct.unpack('>IIBBBBB', body)
        elif tag == b'IDAT': idat += body
        pos += 12 + n
    return ihdr, zlib.decompress(idat)


class VersionTests(unittest.TestCase):
    def test_readme_and_changelog_name_the_current_version(self):
        base = version.__version__.split('-')[0]; readme = read('README.md')
        self.assertRegex(readme.split('\n', 4)[2], rf'^Beta {re.escape(base)}\b', 'the README header line shows an old version')
        heads = re.findall(r'^## (.+)$', read('CHANGELOG.md'), re.M)
        top = heads[0] if heads[0] != 'Unreleased' else heads[1]
        self.assertEqual(top, version.__version__, 'the newest CHANGELOG section is not the current version')
        self.assertIn(f'Screenshots of version **{version.__version__}**', readme, 'regenerate the screenshots (python tools\\make_screenshots.py) and update the README note')

    def test_user_agent_and_title_use_the_same_version(self):
        self.assertIn(version.__version__, version.USER_AGENT)


class LinkTests(unittest.TestCase):
    def test_every_relative_link_and_image_in_the_public_docs_exists(self):
        files = tracked_markdown()
        if not files: self.skipTest('not a git checkout')
        for f in files:
            text = read(f); base = os.path.dirname(f)
            for m in re.finditer(r'!?\[[^\]]*\]\(([^)\s]+)\)', text):
                url = m.group(1)
                if url.startswith(('http://', 'https://', 'mailto:')): continue
                path, _, anchor = url.partition('#'); target = os.path.normpath(os.path.join(base, path)) if path else f
                self.assertTrue(os.path.exists(os.path.join(REPO, target)), f'{f}: broken link {url}')
                if anchor and target.endswith('.md'):
                    heads = {slug(h) for h in re.findall(r'^#+\s+(.*)$', read(target), re.M)}; self.assertIn(anchor, heads, f'{f}: no heading for {url}')

    def test_no_control_characters_in_the_docs(self):
        for f in tracked_markdown() + ['README.md']:
            data = open(os.path.join(REPO, f), 'rb').read(); self.assertIsNone(re.search(rb'\r(?!\n)|[\x00-\x08\x0b\x0c\x0e-\x1f]', data), f)      # e.g. an unescaped "\r" turning a path into garbage

    def test_the_docs_that_are_linked_are_not_dropped_by_the_whitelist(self):
        ignore = read('.gitignore')
        for name in ('GETTING-STARTED.md', 'ROADMAP.md'): self.assertIn(f'!/docs/{name}', ignore)
        self.assertIn('!/docs/images/', ignore)


class ScreenshotTests(unittest.TestCase):
    def test_png_writer_round_trips(self):
        w, h = 7, 5; rgb = bytes((x * 31 + y * 17 + c * 5) & 255 for y in range(h) for x in range(w) for c in range(3))
        ihdr, raw = decode_png(make_screenshots.png_bytes(w, h, rgb)); self.assertEqual(ihdr, (w, h, 8, 2, 0, 0, 0))
        out = bytearray(); stride = w * 3
        for y in range(h):
            row = raw[y * (stride + 1):(y + 1) * (stride + 1)]; self.assertEqual(row[0], 1); line = bytearray(row[1:])
            for i in range(3, stride): line[i] = (line[i] + line[i - 3]) & 255            # undo the Sub filter
            out += line
        self.assertEqual(bytes(out), rgb)

    def test_shipped_screenshots_are_valid_and_small_and_all_used(self):
        folder = os.path.join(REPO, 'docs', 'images')
        if not os.path.isdir(folder): self.skipTest('no screenshots')
        readme = read('README.md'); names = sorted(os.listdir(folder))
        self.assertEqual(sorted(n[:-4] for n in names), sorted(make_screenshots.SHOTS))                     # exactly the ones the tool makes
        for n in names:
            data = open(os.path.join(folder, n), 'rb').read(); ihdr, raw = decode_png(data)
            self.assertGreaterEqual(ihdr[0], 800); self.assertLess(len(data), 400 * 1024, n); self.assertIn(f'docs/images/{n}', readme)


if __name__ == '__main__':
    unittest.main()
