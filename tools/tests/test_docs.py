"""Tests for the public documentation: the version number appears where it should, links and images exist, the screenshots are valid files, and the screenshot
tool's PNG writer is correct. No GUI, no network."""
import importlib.util, os, re, struct, subprocess, sys, unittest, zlib

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
        m = re.search(r'Screenshots of version \*\*([^*]+)\*\*', readme); self.assertTrue(m, 'the README has no screenshot version note')
        self.assertIn(m.group(1), heads, 'the screenshot note names a version that is not in the CHANGELOG')     # the pictures may be from an earlier version when the windows did not change

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
        self.assertIn('!/docs/GETTING-STARTED.md', ignore)
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
        readme = read('README.md'); names = sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n)))
        installer = importlib.util.spec_from_file_location('shoot_installer', os.path.join(REPO, 'packaging', 'shoot_installer.py')); si = importlib.util.module_from_spec(installer); installer.loader.exec_module(si)
        self.assertEqual(sorted(n[:-4] for n in names), sorted(make_screenshots.SHOTS + si.SHOTS))          # exactly the ones the two tools make
        for n in names:
            data = open(os.path.join(folder, n), 'rb').read(); ihdr, raw = decode_png(data)
            self.assertGreaterEqual(ihdr[0], 300); self.assertLess(len(data), 400 * 1024, n); self.assertIn(f'docs/images/{n}', readme)
        for lang in sorted(d for d in os.listdir(folder) if os.path.isdir(os.path.join(folder, d))):         # a folder per language: the program's own screenshots in that language
            files = sorted(os.listdir(os.path.join(folder, lang))); self.assertEqual([n[:-4] for n in files], sorted(make_screenshots.SHOTS + si.SHOTS[2:]), lang)          # the language list and the install-mode box are not language-specific
            for n in files:
                data = open(os.path.join(folder, lang, n), 'rb').read(); ihdr, raw = decode_png(data); self.assertGreaterEqual(ihdr[0], 300); self.assertLess(len(data), 400 * 1024, n)


def jpeg_markers(data):
    """The marker codes of a JPEG up to the start of the image data (so any metadata segment shows up)."""
    assert data[:2] == b'\xff\xd8', 'not a JPEG'; pos = 2; out = []
    while pos + 4 <= len(data):
        assert data[pos] == 0xff, 'broken JPEG'; m = data[pos + 1]; out.append(m)
        if m == 0xda: break
        pos += 2 + struct.unpack('>H', data[pos + 2:pos + 4])[0]
    return out


class InGameFrameTests(unittest.TestCase):
    def test_the_in_game_frames_are_clean_valid_and_all_used(self):
        folder = os.path.join(REPO, 'docs', 'ingame')
        if not os.path.isdir(folder): self.skipTest('no in-game frames')
        readme = read('README.md'); names = sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))); self.assertTrue(names)
        for n in names:
            data = open(os.path.join(folder, n), 'rb').read(); marks = jpeg_markers(data)
            self.assertEqual([m for m in marks if 0xe1 <= m <= 0xef or m == 0xfe], [], f'{n} carries metadata (EXIF, comment, ...): re-save it without')
            self.assertLess(len(data), 1536 * 1024, n); self.assertIn(f'docs/ingame/{n}', readme)
            for needle in (b'Exif', b'DODI', b'Program Files', b'C:\\Users'): self.assertNotIn(needle, data, n)

    def test_public_text_keeps_clear_of_forums_other_sources_and_where_a_fix_came_from(self):
        files = [f for f in tracked_markdown()] + ['packaging/setup-info.txt', 'packaging/START HERE.txt']
        if not tracked_markdown(): self.skipTest('not a git checkout')
        bad = re.compile(r'repack|emulator|DODI|forum|rutracker|torrent|a user (on|report)|user report|users? (reported|found)', re.I)
        for f in files:
            for i, line in enumerate(read(*f.split('/')).splitlines(), 1): self.assertIsNone(bad.search(line), f'{f}:{i}: {line.strip()[:100]}')


if __name__ == '__main__':
    unittest.main()
