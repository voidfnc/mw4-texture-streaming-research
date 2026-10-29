"""version.py - version, client identification and the short notice shown by the tools (CLI --help footer, GUI first run)."""
__version__ = '0.4.5-beta'
REPO_URL = 'https://github.com/voidfnc/mw4-texture-streaming-research'
USER_AGENT = f'mw4-texture-streaming-toolkit/{__version__} (+{REPO_URL})'

NOTICE = ('Research / proof of concept. This toolkit ships no game files, assets, keys or CDN content. It only reads files from your own installation and '
          'requests public, unauthenticated URLs that the game itself requests. It does not patch, hook or read the memory of the game, its launcher, drivers or '
          'anti-cheat. It only delivers texture files the game asks for: it does not touch gameplay or other players and gives no advantage over them. It was built and tested on the '
          'single-player campaign; multiplayer and HQ are experimental. Bulk downloads, hosts-file changes and using a local proxy during online play may go against the terms of '
          'service where you live or lead to action against your account - that is your call and your responsibility. Not affiliated with or endorsed by Activision. No warranty (MIT license).')

BULK_NOTICE = ("BULK DOWNLOAD - please read.\n\n"
               "This downloads game content (texture chunks) in bulk from the publisher's CDN. That content is the publisher's property. Use it only with your own copy of the "
               "game, keep it on this PC, and do not share or re-host it. Downloading this way, and changing your hosts file, may go against the game's terms of service or the "
               "law where you live and could lead to action against your account; checking that is your responsibility. The tool is deliberately gentle on the servers "
               "(few connections, rate limit, back-off) - please keep it that way. The authors give no warranty and accept no liability (MIT license); this is not legal advice.")


def _ack_file():
    import os
    from . import paths
    return os.path.join(paths.WORK, 'bulk_ack.json')


def bulk_acknowledged():
    """True if the bulk-download notice of this version was accepted (CCS_ACCEPT_NOTICE=1 also counts, for scripts and tests)."""
    import json, os
    if os.environ.get('CCS_ACCEPT_NOTICE'): return True
    try: return json.load(open(_ack_file(), encoding='utf-8')).get('version') == __version__
    except Exception: return False


def record_bulk_ack():
    import json, os, time
    os.makedirs(os.path.dirname(_ack_file()), exist_ok=True)
    json.dump(dict(version=__version__, time=time.strftime('%Y-%m-%d %H:%M:%S')), open(_ack_file(), 'w', encoding='utf-8'))
