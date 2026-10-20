"""gamefix.py - the two small settings in the game folder that let the game use the textures it streams.

  1. The game's Steam settings (sp26/steam_settings/configs.main.ini) are set to offline mode. The game then never asks for additional content, so the pieces
     the helper delivers are not used. Fix: [main::connectivity] offline=0 and disable_lan_only=1.
  2. The engine fills <game folder>/xpak_cache, but the game looks for its cache in sp26/xpak_cache. Fix: sp26/xpak_cache becomes a directory junction (a folder
     link, no administrator rights needed for the link itself) to <game folder>/xpak_cache.

  ccs-cli.exe --ccs-run gamefix status [--json]     what is set now (exit 0 = nothing to do or not applicable, 1 = a change is needed)
  ccs-cli.exe --ccs-run gamefix apply               make both changes (asks Windows for permission when the game folder needs it)
  ccs-cli.exe --ccs-run gamefix undo                put the settings file back from the copy made before the first change, remove the link
  From source: python tools/ccs.py --ccs-run gamefix <command>

Safe by design: the settings file is copied once to configs.main.ini.mw4ts-backup before the first edit and all other lines in it are kept; a real sp26/xpak_cache
folder is renamed aside (sp26/xpak_cache.before-link), never deleted; nothing is touched while the game is running; applying twice changes nothing the second time.
"""
import argparse, json, os, re, shutil, stat, subprocess, sys, time
from . import launch, paths, procs

SECTION = 'main::connectivity'
WANT = (('offline', '0'), ('disable_lan_only', '1'))
CONFIG_NAME = 'configs.main.ini'
BACKUP_NAME = CONFIG_NAME + '.mw4ts-backup'
ASIDE_NAME = 'xpak_cache.before-link'


class GameBusy(Exception):
    pass


class NotApplicable(Exception):
    pass


def layout(root=None):
    """The paths this module works with, for a game folder."""
    root = os.path.normpath(root or paths.GAME_ROOT); sp = os.path.join(root, 'sp26'); st = os.path.join(sp, 'steam_settings')
    return dict(root=root, sp26=sp, settings=st, config=os.path.join(st, CONFIG_NAME), backup=os.path.join(st, BACKUP_NAME), link=os.path.join(sp, 'xpak_cache'),
                target=os.path.join(root, 'xpak_cache'))


# ------------------------------------------------------------------------------------------------ the settings file (pure text functions)

_SECTION_RE = re.compile(r'^\s*\[(.*?)\]\s*(?:[;#].*)?$')


def _split(text):
    bom = text.startswith('﻿'); body = text[1:] if bom else text
    return bom, body.splitlines(keepends=True)


def read_keys(text):
    """{key: value} of [main::connectivity] (keys lower-cased; the last one wins)."""
    out = {}; inside = False
    for line in _split(text)[1]:
        m = _SECTION_RE.match(line.rstrip('\r\n'))
        if m: inside = m.group(1).strip().lower() == SECTION; continue
        if inside and '=' in line and not line.lstrip().startswith((';', '#')):
            k, v = line.split('=', 1); out[k.strip().lower()] = v.strip()
    return out


def keys_ok(keys):
    return all(keys.get(k) == v for k, v in WANT)


def set_keys(text, want=WANT, drop=()):
    """`text` with the `want` keys (default: offline=0 and disable_lan_only=1) set in [main::connectivity] and the `drop` keys removed from it. Other lines, comments, other
    sections, the line endings and a BOM are kept."""
    bom, lines = _split(text); nl = '\r\n' if '\r\n' in text else ('\n' if '\n' in text else '\r\n'); wd = dict(want); dropped = {k.lower() for k in drop}
    out = []; inside = found = False; seen = set(); start = 0
    def close_section():
        """Add the keys the section did not have, after its last non-blank line."""
        add = [f'{k}={v}{nl}' for k, v in want if k not in seen]
        if not add: return
        at = len(out)
        while at > start and not out[at - 1].strip(): at -= 1
        if at >= start and not out[at - 1].endswith(('\n', '\r')): out[at - 1] += nl
        out[at:at] = add
    for line in lines:
        m = _SECTION_RE.match(line.rstrip('\r\n'))
        if m:
            if inside: close_section()
            inside = m.group(1).strip().lower() == SECTION; found = found or inside; seen = set(); start = len(out) + 1
            out.append(line); continue
        if inside and '=' in line and not line.lstrip().startswith((';', '#')):
            k = line.split('=', 1)[0].strip().lower()
            if k in wd: out.append(f'{k}={wd[k]}' + (line[len(line.rstrip('\r\n')):] or nl)); seen.add(k); continue
            if k in dropped: continue
        out.append(line)
    if inside: close_section()
    if not found and want:
        if out and not out[-1].endswith(('\n', '\r')): out[-1] += nl
        out += [f'[{SECTION}]{nl}'] + [f'{k}={v}{nl}' for k, v in want]
    return ('\ufeff' if bom else '') + ''.join(out)


def restore_keys(text, original):
    """`text` with the two keys back to what `original` (their values before the setup, from read_keys of the backup) had; a key that was not there is removed again.
    Everything else in `text`, including edits made since, stays."""
    return set_keys(text, want=[(k, original[k]) for k, _ in WANT if k in original], drop=[k for k, _ in WANT if k not in original])


def only_headers(text):
    """True when `text` has nothing but blank lines and section headers."""
    return all(not l.strip() or _SECTION_RE.match(l.strip()) for l in _split(text)[1])


def _read(path):
    with open(path, 'rb') as f: return f.read().decode('utf-8', 'surrogateescape')


def _write(path, text):
    """Replace `path` with `text` through a temporary file. A read-only file is refused (with a plain OSError: asking for administrator rights would not help)."""
    if os.path.exists(path) and not os.access(path, os.W_OK): raise OSError(f'{os.path.basename(path)} is read-only: clear the read-only attribute (file properties) and try again')
    tmp = path + '.tmp'
    try:
        with open(tmp, 'wb') as f: f.write(text.encode('utf-8', 'surrogateescape'))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.remove(tmp)


def _backup_once(path, backup):
    """Keep the original the first time only (an empty backup file means the settings file did not exist). Written through a temporary name, so an interrupted copy is
    never mistaken for a backup."""
    if os.path.exists(backup): return
    tmp = backup + '.tmp'
    if os.path.exists(path): shutil.copy2(path, tmp)
    else: open(tmp, 'wb').close()
    os.replace(tmp, backup)


# ------------------------------------------------------------------------------------------------ the cache link

def is_reparse(p):
    """True for a junction or symbolic link (without following it)."""
    try: return bool(os.lstat(p).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError): return False


def link_state(link, target):
    """'ok' | 'missing' | 'wrong' (a working link to somewhere else) | 'broken' (a link to nothing) | 'dir' (a real folder) | 'file'."""
    if not os.path.lexists(link): return 'missing'
    if is_reparse(link):
        if not os.path.exists(link): return 'broken'
        try: return 'ok' if os.path.exists(target) and os.path.samefile(link, target) else 'wrong'
        except OSError: return 'wrong'
    return 'dir' if os.path.isdir(link) else 'file'


def make_junction(link, target):
    """Directory junction `link` -> `target`. Raises PermissionError when the folder needs administrator rights."""
    try:
        import _winapi; _winapi.CreateJunction(target, link)
    except ImportError:
        r = subprocess.run(['cmd', '/c', 'mklink', '/J', link, target], capture_output=True, text=True, errors='replace', creationflags=procs.CREATE_NO_WINDOW)
        if r.returncode != 0:
            msg = (r.stdout + r.stderr).strip()
            raise (PermissionError if 'denied' in msg.lower() else OSError)(msg or 'mklink failed')
    except OSError as e:
        if getattr(e, 'winerror', 0) == 5: raise PermissionError(str(e)) from e
        raise


def _empty(d):
    try: return not os.listdir(d)
    except OSError: return False


# ------------------------------------------------------------------------------------------------ status / apply / undo

def status(root=None, check_game=True):
    """What is set now (read-only, never raises): dict(applicable, why, ok, config_ok, link_state, problems, ...). `applicable` is False when this is not the layout the
    two settings are about (no sp26/steam_settings next to the game). `check_game` looks for a running game (starts `tasklist`, so the window's own timer skips it)."""
    L = layout(root); s = dict(L, applicable=False, why='', ok=True, config_ok=True, keys={}, problems=[], game_running=False, link_state='missing')
    if not os.path.isdir(L['settings']):
        s['why'] = 'no sp26/steam_settings folder in the game folder, so nothing to set up'; return s
    if os.path.normcase(os.path.normpath(paths.XPAK_CACHE)) == os.path.normcase(L['link']):
        s['why'] = 'the engine cache folder setting points at sp26\\xpak_cache itself, so it is not linked to anything else (change that setting first)'; return s
    s['applicable'] = True
    if check_game:
        try: s['game_running'] = bool(procs.image_running(*dict.fromkeys(tuple(paths.GAME_EXES) + tuple(paths.DEFAULT_EXES))))
        except Exception: pass
    try: s['keys'] = read_keys(_read(L['config'])) if os.path.exists(L['config']) else {}
    except OSError as e: s['keys'] = {}; s['problems'].append(f'cannot read {CONFIG_NAME}: {e}')
    s['config_ok'] = keys_ok(s['keys'])
    if not s['config_ok']:
        off = s['keys'].get('offline')
        s['problems'].append(f"the game's Steam settings are in offline mode ({CONFIG_NAME}: offline=1)" if off == '1' else
                             f'{CONFIG_NAME} does not set online mode (offline=0)' if off != '0' else f'{CONFIG_NAME} is missing disable_lan_only=1')
    s['link_state'] = link_state(L['link'], L['target'])
    if s['link_state'] != 'ok':
        s['problems'].append({'missing': 'sp26\\xpak_cache does not exist, so the game does not look in the cache the helper fills',
                              'wrong': 'sp26\\xpak_cache is a link to somewhere other than the game cache (' + os.path.realpath(L['link']) + ')',
                              'broken': 'sp26\\xpak_cache is a link to a folder that no longer exists',
                              'dir': 'sp26\\xpak_cache is a separate folder, not the cache the helper fills',
                              'file': 'sp26\\xpak_cache is a file'}[s['link_state']])
    s['ok'] = s['config_ok'] and s['link_state'] == 'ok'
    return s


def state(root=None):
    """'ok' | 'needed' | 'na' - the short answer for the guide and the Doctor."""
    s = status(root, check_game=False); return 'na' if not s['applicable'] else ('ok' if s['ok'] else 'needed')


def apply(root=None):
    """Make both changes. -> dict(done=[...], aside='' , status=...). Raises NotApplicable, GameBusy, PermissionError, OSError. Idempotent."""
    s = status(root)
    if not s['applicable']: raise NotApplicable(s['why'])
    if s['ok']: return dict(done=[], aside='', status=s)
    if s['game_running']: raise GameBusy('the game is running: close it, then apply the game setup')
    if s['link_state'] == 'file': raise OSError(f"{s['link']} is a file, not a folder: move it away first")
    if s['link_state'] == 'wrong': raise OSError(f"sp26\\xpak_cache is already a link, to {os.path.realpath(s['link'])}: that is your own setup, so it was left alone. Remove that link if you want this tool to set it up")
    text = ''
    if not s['config_ok']:                                                                              # checked before anything is changed
        text = _read(s['config']) if os.path.exists(s['config']) else ''
        if '\x00' in text: raise OSError(f'{CONFIG_NAME} is not a plain text file (UTF-16?): edit it by hand, see docs/USAGE.md')
        if os.path.exists(s['config']) and not os.access(s['config'], os.W_OK): raise OSError(f'{CONFIG_NAME} is read-only: clear the read-only attribute (file properties) and try again')
    done = []; aside = ''
    if not s['config_ok']:
        _backup_once(s['config'], s['backup']); _write(s['config'], set_keys(text)); done.append(CONFIG_NAME)
    if s['link_state'] != 'ok':
        os.makedirs(s['target'], exist_ok=True)
        if s['link_state'] == 'broken': os.rmdir(s['link'])                                           # removes the link only
        elif s['link_state'] == 'dir':
            if _empty(s['link']): os.rmdir(s['link'])
            else:
                aside = os.path.join(s['sp26'], ASIDE_NAME)
                if os.path.exists(aside): aside += time.strftime('-%Y%m%d-%H%M%S')
                try: os.rename(s['link'], aside)
                except PermissionError as e:
                    if getattr(e, 'winerror', 0) == 32: raise OSError(f'sp26\\xpak_cache is in use by another program (is the game still closing?): {e}') from e   # asking for rights would not help
                    raise
        try: make_junction(s['link'], s['target'])
        except BaseException:
            if aside and not os.path.lexists(s['link']):
                try: os.rename(aside, s['link'])                                                         # put the folder back where it was
                except OSError: pass
            raise
        done.append('sp26\\xpak_cache')
    return dict(done=done, aside=aside, status=status(root))


def undo(root=None):
    """Put the two settings back to what they were before (from the backup; edits made since to other lines stay) and remove the link (only a link, never a real
    folder). -> dict(done=[...], notes=[...])."""
    s = status(root)
    if not s['applicable']: raise NotApplicable(s['why'])
    if s['game_running']: raise GameBusy('the game is running: close it first')
    done = []; notes = []
    if os.path.exists(s['backup']):
        text = _read(s['config']) if os.path.exists(s['config']) else ''
        if '\x00' in text: raise OSError(f'{CONFIG_NAME} is not a plain text file (UTF-16?): edit it by hand, see docs/USAGE.md')
        was = _read(s['backup']); new = restore_keys(text, read_keys(was))
        if os.path.exists(s['config']) and new != text and not os.access(s['config'], os.W_OK): raise OSError(f'{CONFIG_NAME} is read-only: clear the read-only attribute (file properties) and try again')
        if os.path.exists(s['config']) and not was.strip() and only_headers(new): os.remove(s['config'])        # it did not exist before: it does not exist now
        elif new != text: _write(s['config'], new)
        os.remove(s['backup']); done.append(CONFIG_NAME)
    else: notes.append('no backup of ' + CONFIG_NAME + ' was found, so it was left as it is')
    if s['link_state'] == 'ok' and is_reparse(s['link']): os.rmdir(s['link']); done.append('sp26\\xpak_cache')
    elif s['link_state'] in ('wrong', 'broken'): notes.append('sp26\\xpak_cache is a link this tool did not make, so it was left as it is')
    elif s['link_state'] == 'dir': notes.append('sp26\\xpak_cache is a real folder, so it was left as it is')
    aside = os.path.join(s['sp26'], ASIDE_NAME)
    if os.path.isdir(aside): notes.append(f'the folder that was in the way is still at {aside}; rename it back to xpak_cache if you want it')
    return dict(done=done, notes=notes, status=status(root))


def describe(s):
    """One line for the Doctor / the guide."""
    if not s['applicable']: return s['why']
    if s['ok']: return 'online mode is set and sp26\\xpak_cache is linked to the game cache'
    return '; '.join(s['problems']) + (' (close the game first)' if s['game_running'] else '')


def run_elevating(cmd, root=None, say=print):
    """Run `apply` or `undo`; when the game folder needs administrator rights run the same command elevated (one Windows prompt). -> (ok, message)."""
    try: r = (apply if cmd == 'apply' else undo)(root)
    except (NotApplicable, GameBusy) as e: return False, str(e)
    except PermissionError:
        rf = os.path.join(paths.RUN, 'gamefix-result.json'); paths.ensure_dirs()
        if os.path.exists(rf): os.remove(rf)
        say('game setup: the game folder needs administrator rights, asking Windows for permission')
        argv = launch.argv_for('gamefix', cmd, '--root', layout(root)['root'], '--result-file', rf); code = procs.run_elevated(argv)
        if code is None: return False, 'permission was declined: nothing was changed'
        try:
            with open(rf, encoding='utf-8') as f: res = json.load(f)
        except (OSError, ValueError): return False, f'the elevated run ended with code {code} and no result'
        return bool(res.get('ok')), res.get('message') or res.get('error') or ''
    except OSError as e: return False, str(e)
    return True, _message(r) if cmd == 'apply' else _undo_message(r)


def apply_elevating(root=None, say=print): return run_elevating('apply', root, say)


def undo_elevating(root=None, say=print): return run_elevating('undo', root, say)


def _undo_message(r):
    return ('restored: ' + ', '.join(r['done']) if r['done'] else 'nothing to undo') + ''.join('; ' + n for n in r['notes'])


def _message(r):
    msg = ('changed: ' + ', '.join(r['done'])) if r['done'] else 'already set up, nothing to change'
    return msg + (f" (the folder that was in the way is now {r['aside']})" if r.get('aside') else '')


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gamefix', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('status', 'apply', 'undo')); ap.add_argument('--root'); ap.add_argument('--json', action='store_true'); ap.add_argument('--result-file')
    a = ap.parse_args(argv); res = dict(cmd=a.cmd, ok=True, message='')
    try:
        if a.cmd == 'status': s = status(a.root); res.update(status=s, message=describe(s), ok=s['ok'] or not s['applicable'])
        elif a.cmd == 'apply': r = apply(a.root); res.update(message=_message(r), done=r['done'], aside=r['aside'], ok=True)
        else: r = undo(a.root); res.update(message=_undo_message(r), done=r['done'])
    except PermissionError as e: res.update(ok=False, error=f'permission denied (run as administrator): {e}', message=str(e))
    except (NotApplicable, GameBusy, OSError) as e: res.update(ok=False, error=str(e), message=str(e))
    if a.result_file:
        paths.ensure_dirs()
        with open(a.result_file, 'w', encoding='utf-8') as f: json.dump(res, f, default=str)
    if a.json: print(json.dumps(res, default=str))
    else: print(res['message'] if res['ok'] or a.cmd == 'status' else 'ERROR: ' + res.get('error', ''))
    if a.cmd == 'status': return 0 if res['ok'] else 1
    if not res['ok']: return 3 if 'permission' in res.get('error', '') else 1
    return 0
