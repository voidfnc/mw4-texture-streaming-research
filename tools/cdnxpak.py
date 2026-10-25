#!/usr/bin/env python3
"""cdnxpak — parse `*_cdn.xpak` (KAPI type 4) chunk lists, and find them in a game folder.

The Xbox / Microsoft Store build ships the same lists as `*_cdn_stub.xpak`; `resolve` and `find_all` treat a stub as the list of its package when the full file is absent.

Record (20 B, from 0x8000): [u64 id][u32 (size<<1)|flag][u32 0][u32 rawsize]
size = total CDN object bytes, flag = URL suffix (_0/_1), rawsize = decoded bytes.
"""
import struct, sys, glob, os

FULL = '_cdn.xpak'; STUB = '_cdn_stub.xpak'


def resolve(root, rel):
    """The chunk list `rel` ('sp26/sp26_cdn.xpak', relative to the game folder) -> its path: that file, else its '_cdn_stub' twin (Xbox build); None when neither exists."""
    p = os.path.join(root, *rel.split('/'))
    if os.path.isfile(p): return p
    if rel.endswith(FULL):
        q = os.path.join(root, *(rel[:-len(FULL)] + STUB).split('/'))
        if os.path.isfile(q): return q
    return None


def find_all(root, subdirs=('cod26', 'sp26')):
    """Every chunk list under the game folder's cod26/ and sp26/: the `*_cdn.xpak` files, plus the `*_cdn_stub.xpak` files whose full twin is not there. Sorted per folder."""
    out = []
    for d in subdirs:
        base = os.path.join(glob.escape(root), d)
        full = sorted(glob.glob(os.path.join(base, '*' + FULL))); have = {os.path.normcase(f) for f in full}
        out += full + sorted(s for s in glob.glob(os.path.join(base, '*' + STUB)) if os.path.normcase(s[:-len(STUB)] + FULL) not in have)
    return out


def is_stub(path): return path.lower().endswith(STUB)

def parse(fn):
    d = open(fn, 'rb').read(); recs = []; p = 0x8000
    while p + 20 <= len(d):
        i, x, z, raw = struct.unpack_from('<QIII', d, p)
        if z != 0 or i == 0 or (x >> 1) == 0 or raw == 0: break
        recs.append(dict(id=i, size=x >> 1, flag=x & 1, raw=raw)); p += 20
    return recs
if __name__ == '__main__':
    for fn in sys.argv[1:]:
        r = parse(fn)
        print(os.path.basename(fn), len(r), "chunks", sum(x['size'] for x in r), "B compressed", sum(x['raw'] for x in r), "B raw")
