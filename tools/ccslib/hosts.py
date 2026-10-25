"""hosts.py - manage ONLY the marked CCS block of the Windows hosts file.

Block:
  # >>> ccs-managed (MW4 texture CDN loopback) >>>
  ::1 cod-assets.cdn.callofduty.com
  127.0.0.1 cod-assets.cdn.callofduty.com
  # <<< ccs-managed <<<

Rules: never touch other lines (except adopting our own hand-added loopback lines for HOST into the block);
timestamped backup before every write; in-place write (keeps the file's ACL) with read-back verify + rollback;
refuse to replace a foreign mapping of HOST to a non-loopback address unless force=True.
"""
import difflib, glob, os, re, shutil, socket, stat, subprocess, time
from . import paths

BEGIN = '# >>> ccs-managed (MW4 texture CDN loopback) >>>'
END = '# <<< ccs-managed <<<'
LOOPBACK = ('::1', '127.0.0.1')
_HOSTLINE = re.compile(r'^\s*([0-9a-fA-F:.]+)\s+(.*?)\s*(#.*)?$')


class HostsError(Exception):
    pass


def read(path=None):
    """-> (text, newline). Decoding is lossless for our purposes (utf-8, falling back to latin-1)."""
    p = path or paths.hosts_path()
    raw = open(p, 'rb').read()
    try: text = raw.decode('utf-8')
    except UnicodeDecodeError: text = raw.decode('latin-1')
    nl = '\r\n' if raw.count(b'\r\n') >= raw.count(b'\n') - raw.count(b'\r\n') and b'\r\n' in raw else ('\n' if b'\n' in raw else '\r\n')
    return text, nl


def _split(text):
    return text.replace('\r\n', '\n').split('\n')


def _maps_host(line):
    s = line.strip()
    if not s or s.startswith('#'): return None
    m = _HOSTLINE.match(s)
    if not m: return None
    names = [n.lower() for n in m.group(2).split()]
    return m.group(1) if paths.HOST in names else None


def parse(text):
    """-> dict(block=[lines] or None, block_span=(i,j) or None, foreign=[(idx, ip, line)], lines=[...])"""
    lines = _split(text)
    span = None; begin = None
    for i, l in enumerate(lines):
        if l.strip() == BEGIN: begin = i                      # the last BEGIN before the first END: a stray BEGIN left by hand must not swallow the lines up to our block
        elif l.strip() == END and begin is not None: span = (begin, i); break
    foreign = []
    for i, l in enumerate(lines):
        if span and span[0] <= i <= span[1]: continue
        ip = _maps_host(l)
        if ip: foreign.append((i, ip, l))
    block = lines[span[0] + 1:span[1]] if span else None
    return dict(block=block, span=span, foreign=foreign, lines=lines)


def state_of(parsed):
    """ABSENT | OK | PARTIAL | FOREIGN (host mapped outside our block, no block) | MIXED (block + foreign lines)"""
    ips = set()
    if parsed['block'] is not None:
        for l in parsed['block']:
            ip = _maps_host(l)
            if ip: ips.add(ip)
    has_block = parsed['block'] is not None
    if has_block:
        s = 'OK' if set(LOOPBACK) <= ips else 'PARTIAL'
        return 'MIXED' if parsed['foreign'] and s == 'OK' else s
    return 'FOREIGN' if parsed['foreign'] else 'ABSENT'


def status(path=None):
    text, nl = read(path); p = parse(text)
    return dict(state=state_of(p), block=p['block'], foreign=[(i + 1, ip, l) for i, ip, l in p['foreign']], path=path or paths.hosts_path())


def _without_host(line):
    """A hand-added line that maps HOST (and maybe other names) -> the same line without HOST, or None when HOST was its only name."""
    m = _HOSTLINE.match(line)
    if not m: return None
    keep = [n for n in m.group(2).split() if n.lower() != paths.HOST]
    return f"{m.group(1)} {' '.join(keep)}" + (f'  {m.group(3)}' if m.group(3) else '') if keep else None


def _block_lines():
    return [BEGIN] + [f'{ip} {paths.HOST}' for ip in LOOPBACK] + [END]


def compute(text, mode, force=False):
    """-> new text for mode 'apply' | 'remove' (not yet written)."""
    p = parse(text); lines = list(p['lines'])
    nl = '\r\n' if '\r\n' in text else '\n'
    bad = [f for f in p['foreign'] if f[1] not in LOOPBACK]
    if mode == 'apply' and bad and not force:
        raise HostsError(f'{paths.HOST} is mapped to a non-loopback address outside our block (line {bad[0][0] + 1}: {bad[0][2].strip()}); refusing without force')
    # drop our existing block and any hand-added loopback lines for HOST (adopted into the block on apply, removed on remove)
    drop = set(); rewrite = {}
    if p['span']: drop |= set(range(p['span'][0], p['span'][1] + 1))
    for i, ip, l in p['foreign']:
        if ip in LOOPBACK or force:
            rest = _without_host(l)                              # other names on the same line (127.0.0.1 localhost HOST) stay mapped
            if rest is None: drop.add(i)
            else: rewrite[i] = rest
    kept = [rewrite.get(i, l) for i, l in enumerate(lines) if i not in drop]
    insert_at = p['span'][0] - sum(1 for d in drop if d < p['span'][0]) if p['span'] else None       # where the block was, after the lines before it were dropped
    if mode == 'apply':
        if insert_at is not None and insert_at <= len(kept):
            kept[insert_at:insert_at] = _block_lines()          # re-create the block where it was
        elif kept and kept[-1] == '':
            kept[-1:-1] = _block_lines()                        # append before the final newline so remove() is an exact inverse
        else:
            kept += _block_lines()
    elif mode != 'remove':
        raise ValueError(mode)
    out = nl.join(kept)
    if not out.endswith(nl): out += nl
    return out


def diff(old, new):
    return ''.join(difflib.unified_diff([l + '\n' for l in _split(old)], [l + '\n' for l in _split(new)], 'hosts (current)', 'hosts (after)', n=1))


def backup(path=None, tag=''):
    p = path or paths.hosts_path(); paths.ensure_dirs()
    dst = os.path.join(paths.HOSTS_BACKUPS, f"hosts.{time.strftime('%Y%m%d-%H%M%S')}{tag}")
    n = 1
    while os.path.exists(dst): n += 1; dst = f"{dst.rsplit('.', 1)[0]}.{time.strftime('%Y%m%d-%H%M%S')}{tag}-{n}"
    shutil.copy2(p, dst)
    return dst


def list_backups():
    return sorted(glob.glob(os.path.join(glob.escape(paths.HOSTS_BACKUPS), 'hosts.*')), reverse=True)


def _denied_hint(p):
    """Why a write to the hosts file may be refused even when running as admin."""
    try:
        if os.stat(p).st_file_attributes & stat.FILE_ATTRIBUTE_READONLY:
            return f'the hosts file has the read-only attribute set (clear it with: attrib -r "{p}")'
    except (OSError, AttributeError): pass
    return 'something is blocking writes to it - usually security software with hosts-file protection (pause it, or allow python.exe), or a changed file ACL'


def write(new_text, path=None):
    """Backup, write in place, read back and verify; roll back on mismatch. Returns the backup path."""
    p = path or paths.hosts_path()
    old = open(p, 'rb').read()
    bk = backup(p)
    data = new_text.encode('utf-8')
    try: f = open(p, 'wb')
    except PermissionError as e:       # refused before anything was truncated: nothing to roll back
        raise HostsError(f'cannot write {p} ({e}); {_denied_hint(p)}. The file was not changed; backup at {bk}')
    try:
        with f: f.write(data)
        if open(p, 'rb').read() != data: raise HostsError('read-back mismatch')
    except Exception as e:
        try:
            with open(p, 'wb') as f: f.write(old)
        except Exception as e2: raise HostsError(f'write failed ({e}) AND rollback failed ({e2}); backup at {bk}')
        raise HostsError(f'write failed, rolled back ({e})')
    return bk


def apply(path=None, force=False, flush=True):
    p = path or paths.hosts_path(); text, _ = read(p); new = compute(text, 'apply', force)
    if new == text:
        if flush: flush_dns()          # unchanged file but a stale resolver cache is the usual reason the check failed
        return dict(changed=False, backup=None)
    bk = write(new, p)
    if flush: flush_dns()
    return dict(changed=True, backup=bk)


def remove(path=None, flush=True):
    p = path or paths.hosts_path(); text, _ = read(p); new = compute(text, 'remove')
    if new == text: return dict(changed=False, backup=None)
    bk = write(new, p)
    if flush: flush_dns()
    return dict(changed=True, backup=bk)


def restore_backup(name, path=None, flush=True):
    """Replace the hosts file with a chosen backup (explicit user action; backs up the current file first)."""
    src = name if os.path.isabs(name) else os.path.join(paths.HOSTS_BACKUPS, name)
    if not os.path.isfile(src): raise HostsError(f'no such backup: {src}')
    new = open(src, 'rb').read().decode('utf-8', 'replace')
    bk = write(new, path or paths.hosts_path())
    if flush: flush_dns()
    return dict(changed=True, backup=bk)


def flush_dns():
    try:
        r = subprocess.run(['ipconfig', '/flushdns'], capture_output=True, text=True, errors='replace', timeout=20, creationflags=0x08000000)
        return r.returncode == 0
    except Exception:
        return False


def resolve_check(timeout=3.0):
    """What the system resolver returns for HOST per family. -> {'v4': [...], 'v6': [...], 'ok': bool}"""
    res = {}
    for key, fam in (('v4', socket.AF_INET), ('v6', socket.AF_INET6)):
        try: res[key] = sorted({a[4][0] for a in socket.getaddrinfo(paths.HOST, 80, fam, socket.SOCK_STREAM)})
        except Exception as e: res[key] = [f'ERR {e}']
    res['ok'] = res['v4'] == ['127.0.0.1'] and res['v6'] == ['::1']
    return res
