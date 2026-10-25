"""cachectl.py - inspect / back up / restore the engine's xpak_cache.

Hard rules: nothing here touches xpak_cache while the game is running (CacheBusy), every destructive step keeps a copy
(restore renames the current cache aside first).
"""
import glob, os, shutil, struct, sys, time
from . import paths, procs, report


class CacheBusy(Exception):
    pass


def _need_closed():
    g = procs.image_running(*paths.GAME_EXES)
    if g: raise CacheBusy('game is running (' + ', '.join(g) + ') - close it first')


def dir_size(d):
    t = 0
    for dp, _, fn in os.walk(d):
        for f in fn:
            try: t += os.path.getsize(os.path.join(dp, f))
            except OSError: pass
    return t


def shards(cache_dir=None):
    """Per-shard facts (read-only): counter, record count, unique ids, data bytes, key prefix, sizes. May race with a running game."""
    sys.path.insert(0, paths.TOOLS); import xpakrec
    out = []
    for fn in sorted(glob.glob(os.path.join(glob.escape(cache_dir or paths.XPAK_CACHE), 'cache_*_2.xpak')), key=lambda p: int(os.path.basename(p).split('_')[1])):
        row = dict(name=os.path.basename(fn), size=os.path.getsize(fn))
        try:
            d = open(fn, 'rb').read(0x1000); recs = xpakrec.parse(fn)
            row.update(counter=struct.unpack_from('<I', d, 8)[0], records=len(recs), unique=len({r['id'] for r in recs}), key=d[0x130:0x138].hex(),
                       data_end=struct.unpack_from('<Q', d, 0x798)[0], data_size=os.path.getsize(fn + 'data') if os.path.exists(fn + 'data') else 0,
                       wire=sum(r['size'] for r in recs))
        except Exception as e: row['error'] = str(e)
        out.append(row)
    return out


def summary(cache_dir=None):
    sh = shards(cache_dir); ids = set(); rec = 0
    sys.path.insert(0, paths.TOOLS); import xpakrec
    for s in sh:
        if 'error' not in s and s['records']:
            ids.update(r['id'] for r in xpakrec.parse(os.path.join(cache_dir or paths.XPAK_CACHE, s['name']))); rec += s['records']
    return dict(shards=sh, records=rec, unique=len(ids), dup_ratio=round(rec / len(ids), 2) if ids else 0.0, total_bytes=dir_size(cache_dir or paths.XPAK_CACHE),
                active=sum(1 for s in sh if s.get('records')), setting_gb=settings_gb(cache_dir))


def settings_gb(cache_dir=None):
    """xpak_settings.bin dword[4] = cache size in GB as recorded by the engine (None if unreadable)."""
    try:
        d = open(os.path.join(cache_dir or paths.XPAK_CACHE, 'xpak_settings.bin'), 'rb').read(32)
        return struct.unpack_from('<I', d, 16)[0]
    except Exception: return None


def backups():
    """[(name, path, bytes, mtime)] of xpak_cache.* sibling directories, newest first."""
    out = []
    for p in glob.glob(glob.escape(paths.XPAK_CACHE) + '.*'):
        if os.path.isdir(p): out.append((os.path.basename(p), p, dir_size(p), os.path.getmtime(p)))
    return sorted(out, key=lambda x: -x[3])


def _free():
    """Free bytes on the drive the cache (and so its backups) lives on: `cache_dir` can put it on another drive than the tools."""
    d = os.path.dirname(os.path.abspath(paths.XPAK_CACHE))
    while d and not os.path.isdir(d):
        up = os.path.dirname(d)
        if up == d: break
        d = up
    return shutil.disk_usage(d or paths.ROOT).free


def backup(tag='gui'):
    _need_closed()
    size = dir_size(paths.XPAK_CACHE); free = _free()
    if size + 5 * 2**30 > free: raise OSError(f'not enough free disk: need {size / 2**30:.1f} GiB + 5 GiB headroom, have {free / 2**30:.1f} GiB')
    dst = f"{paths.XPAK_CACHE}.bak_{tag}_{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copytree(paths.XPAK_CACHE, dst); return dst


def restore(name):
    """Make `xpak_cache` equal to backup `name`. The current cache is renamed aside (xpak_cache.replaced_<stamp>), not deleted."""
    _need_closed()
    src = os.path.join(os.path.dirname(paths.XPAK_CACHE), name)
    if not os.path.isdir(src) or os.path.basename(src) == 'xpak_cache' or not os.path.basename(src).startswith('xpak_cache.'): raise ValueError(f'not a cache backup: {name}')
    size = dir_size(src)
    if size + 5 * 2**30 > _free(): raise OSError('not enough free disk to copy the backup back')
    aside = f"{paths.XPAK_CACHE}.replaced_{time.strftime('%Y%m%d-%H%M%S')}"
    if os.path.exists(paths.XPAK_CACHE): os.rename(paths.XPAK_CACHE, aside)
    try: shutil.copytree(src, paths.XPAK_CACHE)
    except Exception:
        shutil.rmtree(paths.XPAK_CACHE, ignore_errors=True)
        if os.path.exists(aside): os.rename(aside, paths.XPAK_CACHE)          # roll back
        raise
    return aside


def delete_backup(name):
    """Permanently delete a sibling backup directory (caller must have confirmed). Never touches xpak_cache itself."""
    if not name.startswith('xpak_cache.'): raise ValueError('only xpak_cache.* backup directories can be deleted here')
    p = os.path.join(os.path.dirname(paths.XPAK_CACHE), name)
    if not os.path.isdir(p): raise ValueError('no such backup')
    shutil.rmtree(p)
