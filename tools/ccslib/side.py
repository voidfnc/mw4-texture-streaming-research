"""side.py - the small files Warzone asks for under /pc/iw9_3/23/tr/<32 hex>/<id>_<wire>_<flag> (not at the normal chunk address).

They are kept beside the offline copy in <mirror>/side/tr/<folder>/<name>, with the reply headers that matter (ETag, x-amz-meta-*) in <name>.h.json.
The proxy keeps one when it comes from the internet and serves it from there; ccsmirror's "Download what I played" fetches the ones the game asked for.
"""
import json, os

KEEP = ('etag', 'last-modified', 'accept-ranges', 'cache-control', 'expires')


def keep_headers(pairs):
    """The reply headers worth keeping / forwarding: validators, cache headers and every x-amz-meta-* (the engine reads x-amz-meta-cod-key)."""
    return [(k, v) for k, v in pairs if k.lower() in KEEP or k.lower().startswith('x-amz-meta-')]


def path(mirror, folder, name): return os.path.join(mirror, 'side', 'tr', folder, name)


def load(mirror, folder, name, wire):
    """-> (body, extra headers) of a kept file whose size is `wire`, else None."""
    p = path(mirror, folder, name)
    try:
        if os.path.getsize(p) != wire: return None
        with open(p, 'rb') as fh: body = fh.read()
    except OSError: return None
    try:
        with open(p + '.h.json', encoding='utf-8') as fh: extra = [tuple(x) for x in json.load(fh)]
    except (OSError, ValueError, TypeError): extra = []
    return body, extra


def store(mirror, folder, name, wire, body, extra):
    """Keep a file (whole and of the size in its name only). A folder this user cannot write to is not an error: -> False."""
    if len(body) != wire: return False
    p = path(mirror, folder, name)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + '.h.json.tmp', 'w', encoding='utf-8') as fh: json.dump([[k, v] for k, v in extra], fh)
        os.replace(p + '.h.json.tmp', p + '.h.json')
        with open(p + '.tmp', 'wb') as fh: fh.write(body)
        os.replace(p + '.tmp', p); return True
    except OSError: return False
