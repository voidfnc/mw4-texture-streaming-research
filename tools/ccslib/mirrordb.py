"""mirrordb.py - opening the mirror index (index.sqlite) for reading.

The index is a WAL database. SQLite normally has to create two small side files next to it (index.sqlite-shm / -wal) even to read it, so opening it fails with "unable
to open database file" when the folder is one this user cannot write to, for example a mirror inside Program Files that an administrator built earlier while the program
now runs as a normal user. For readers (the proxy, the Doctor, the texture pack check, reports) there is a fallback: an immutable read-only view of the main file. It is
used only for that one error, so a real lock or a corrupt file is still reported as such. Writers (ccsmirror) are not affected: they need a writable folder anyway.
"""
import os, pathlib, sqlite3


def _uri(db, query):
    return pathlib.Path(os.path.abspath(db)).as_uri() + query


def connect_read(db, timeout=10):
    """A read-only connection to the index file `db`. Raises sqlite3.Error when it cannot be read at all."""
    if not os.path.isfile(db): raise sqlite3.OperationalError(f'no index file: {db}')                  # an immutable open of a missing file would read as an empty database
    last = None
    for query in ('?mode=ro', '?immutable=1'):
        c = None
        try:
            c = sqlite3.connect(_uri(db, query), uri=True, timeout=timeout); c.execute('select count(*) from sqlite_master').fetchone(); return c
        except sqlite3.OperationalError as e:
            last = e
            if c is not None: c.close()
            if 'unable to open' not in str(e): raise
    raise last


def writable(folder):
    """Can this user create a file in `folder` (or, when it does not exist yet, in the nearest folder above it that does)? os.access is no use for this on Windows."""
    d = os.path.abspath(folder)
    while d and not os.path.isdir(d):
        up = os.path.dirname(d)
        if up == d: return False
        d = up
    probe = os.path.join(d, f'.ccs-write-test-{os.getpid()}')
    try:
        with open(probe, 'wb'): pass
        os.remove(probe); return True
    except OSError:
        return False
