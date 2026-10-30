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
import difflib, glob, json, os, re, shutil, socket, stat, subprocess, time
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
    try: raw = open(p, 'rb').read()
    except FileNotFoundError: return '', '\r\n'               # no hosts file at all (some tweak and "debloat" tools delete it): the same as an empty one; apply creates it
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):                   # saved as UTF-16 (Notepad's "Unicode"): Windows does not read such a file, and it is written back as UTF-8
        try: text = raw.decode('utf-16')
        except UnicodeDecodeError: text = raw.decode('latin-1')
    else:
        try: text = raw.decode('utf-8')
        except UnicodeDecodeError: text = raw.decode('latin-1')
    crlf = text.count('\r\n')
    nl = '\r\n' if crlf >= text.count('\n') - crlf and crlf else ('\n' if '\n' in text else '\r\n')
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
    nl = '\r\n' if '\r\n' in text or not text else '\n'
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
    """Copy of the hosts file into the backup folder; None when there is no hosts file to copy."""
    p = path or paths.hosts_path(); paths.ensure_dirs()
    if not os.path.exists(p): return None
    dst = os.path.join(paths.HOSTS_BACKUPS, f"hosts.{time.strftime('%Y%m%d-%H%M%S')}{tag}")
    n = 1
    while os.path.exists(dst): n += 1; dst = f"{dst.rsplit('.', 1)[0]}.{time.strftime('%Y%m%d-%H%M%S')}{tag}-{n}"
    shutil.copy2(p, dst)
    return dst


def _backup_key(p):
    """Newest first: the time in the name, then the number added when several backups share a second (-2, ... -10: by value, not as text)."""
    m = re.match(r'hosts\.(\d{8}-\d{6})(?:.*?-(\d+))?$', os.path.basename(p))
    return (m.group(1), int(m.group(2) or 1)) if m else (os.path.basename(p), 0)


def list_backups():
    return sorted(glob.glob(os.path.join(glob.escape(paths.HOSTS_BACKUPS), 'hosts.*')), key=_backup_key, reverse=True)


def _denied_hint(p):
    """Why a write to the hosts file may be refused even when running as admin."""
    try:
        if os.stat(p).st_file_attributes & stat.FILE_ATTRIBUTE_READONLY:
            return f'the hosts file has the read-only attribute set (clear it with: attrib -r "{p}")'
    except (OSError, AttributeError): pass
    return 'something is blocking writes to it - usually security software with hosts-file protection (pause it, or allow python.exe), or a changed file ACL'


def friendly(e, path=None):
    """The reason a hosts-file read or write failed, in words (Windows' own text for a refused read is only 'Permission denied')."""
    p = path or paths.hosts_path()
    if isinstance(e, PermissionError): return f'Windows refused access to {p} ({e}); {_denied_hint(p)}'
    return str(e)


def write(new_text, path=None):
    """Backup, write in place, read back and verify; roll back on mismatch. Returns the backup path (None when there was no hosts file: it is created, and removed again on a failure)."""
    p = path or paths.hosts_path()
    old = open(p, 'rb').read() if os.path.exists(p) else None
    bk = backup(p)
    data = new_text.encode('utf-8')
    if old is None:
        try: os.makedirs(os.path.dirname(p), exist_ok=True)
        except OSError as e: raise HostsError(f'the hosts file does not exist and its folder could not be created ({p}): {e}')
    try: f = open(p, 'wb')
    except PermissionError as e:       # refused before anything was truncated: nothing to roll back
        raise HostsError(f'cannot write {p} ({e}); {_denied_hint(p)}. The file was not changed; backup at {bk}')
    except OSError as e:
        raise HostsError(f'cannot write {p} ({e})')
    try:
        with f: f.write(data)
        if open(p, 'rb').read() != data: raise HostsError('read-back mismatch')
    except Exception as e:
        try:
            if old is None: os.remove(p)
            else:
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
    p = path or paths.hosts_path()
    if not os.path.exists(p): return dict(changed=False, backup=None)          # no hosts file: nothing of ours in it
    text, _ = read(p); new = compute(text, 'remove')
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


def file_facts(path=None):
    """What a hosts file looks like to Windows, without its content: size, attributes, encoding, line count -> dict."""
    p = path or paths.hosts_path(); out = dict(exists=os.path.exists(p))
    if not out['exists']: return out
    try:
        raw = open(p, 'rb').read(); attrs = getattr(os.stat(p), 'st_file_attributes', 0)
        enc = 'utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8 with a byte order mark' if raw[:3] == b'\xef\xbb\xbf' else None
        if enc is None:
            try: raw.decode('utf-8'); enc = 'ascii or utf-8'
            except UnicodeDecodeError: enc = 'another code page'
        out.update(size=len(raw), lines=raw.count(b'\n'), encoding=enc, nul_bytes=raw.count(b'\0'), readonly=bool(attrs & stat.FILE_ATTRIBUTE_READONLY), hidden=bool(attrs & stat.FILE_ATTRIBUTE_HIDDEN), system=bool(attrs & stat.FILE_ATTRIBUTE_SYSTEM))
    except OSError as e: out['error'] = str(e)
    return out


def diagnose(path=None):
    """Why Windows may answer from DNS although our block is in the hosts file. -> a sentence, or None when the file looks fine (then something outside the file is overriding it)."""
    f = file_facts(path)
    if not f.get('exists'): return 'the hosts file does not exist'
    if f.get('encoding') == 'utf-16' or f.get('nul_bytes'):
        return 'the hosts file is saved as UTF-16 (or holds NUL bytes), which Windows does not read; Apply writes it as plain UTF-8 and keeps a backup of the old one'
    return None


def resolver_report(path=None):
    """Everything about name resolution that decides whether the hosts block takes effect, for the support bundle (no file content, no personal data)."""
    from . import procs
    p = path or paths.hosts_path()
    return dict(hosts_file=file_facts(p), file_in_use_is_default=os.path.normcase(os.path.normpath(p)) == os.path.normcase(os.path.normpath(os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'drivers', 'etc', 'hosts'))),
                data_base_path=paths.database_path(), dns_client_service_running=procs.service_running('Dnscache') if os.name == 'nt' else None, resolver=resolve_check(), diagnosis=diagnose(p),
                permissions=acl_facts(p) if os.name == 'nt' else None, windows=resolver_extra() if os.name == 'nt' else None)


# SIDs of the groups the DNS Client service (it runs as Network Service) is a member of: a read right for any of them lets it read the hosts file
_DNS_READERS = {'S-1-1-0': 'Everyone', 'S-1-5-32-545': 'Users', 'S-1-5-11': 'Authenticated Users', 'S-1-5-20': 'Network Service'}
_SID_NAMES = dict(_DNS_READERS, **{'S-1-5-18': 'SYSTEM', 'S-1-5-19': 'Local Service', 'S-1-5-32-544': 'Administrators', 'S-1-5-32-546': 'Guests'})
_READ_WORDS = {'FullControl', 'Modify', 'ReadAndExecute', 'Read', 'ReadData', 'ListDirectory'}


def _rights_read(rights):
    """Does a FileSystemRights text (or number, for generic rights) include the right to read the file's content?"""
    r = str(rights).strip()
    try: return bool(int(r) & 0xFFFFFFFF & (0x80000000 | 0x10000000 | 0x1 | 0x20000))
    except ValueError: pass
    return any(w.strip() in _READ_WORDS for w in r.split(','))


def acl_can_read(entries):
    """entries: [{sid, type, rights}] of the hosts file -> True when the DNS Client service may read it, False when nothing grants it or a deny takes it away."""
    allow = any(e.get('type') == 'Allow' and e.get('sid') in _DNS_READERS and _rights_read(e.get('rights')) for e in entries)
    deny = any(e.get('type') == 'Deny' and e.get('sid') in _DNS_READERS and _rights_read(e.get('rights')) for e in entries)
    return allow and not deny


def _ps_json(script, timeout=25):
    """Run a PowerShell snippet that returns an object -> parsed JSON; dict(error=...) on a failure."""
    try:
        r = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script + ' | ConvertTo-Json -Depth 4 -Compress'], capture_output=True, text=True, errors='replace', timeout=timeout, creationflags=0x08000000)
        return json.loads(r.stdout) if r.stdout.strip() else ([] if not r.stderr.strip() else dict(error=r.stderr.strip()[:200]))      # an empty list prints nothing
    except Exception as e: return dict(error=str(e))


def acl_facts(path=None, ps=None):
    """Who may do what with the hosts file, by well-known group (no account names), and whether the DNS Client service can read it. None when it cannot be told (not Windows, no PowerShell)."""
    p = path or paths.hosts_path(); q = p.replace("'", "''")
    d = (ps or _ps_json)("$a = Get-Acl -LiteralPath '" + q + "'; @{protected = [bool]$a.AreAccessRulesProtected; entries = @($a.Access | ForEach-Object { @{sid = $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value; type = [string]$_.AccessControlType; rights = [string]$_.FileSystemRights; inherited = [bool]$_.IsInherited} })}")
    if not isinstance(d, dict) or 'entries' not in d: return None
    es = d['entries'] if isinstance(d['entries'], list) else [d['entries']]
    es = [e for e in es if isinstance(e, dict)]
    return dict(inheritance_blocked=bool(d.get('protected')), dns_client_can_read=acl_can_read(es),
                entries=[dict(who=_SID_NAMES.get(e.get('sid'), 'another account'), type=e.get('type'), rights=e.get('rights'), inherited=bool(e.get('inherited'))) for e in es])


def repair_acl(path=None):
    """Put the hosts file's permissions back to what its folder gives (a copy of the old ones is kept next to the hosts backups). Needs administrator rights."""
    p = path or paths.hosts_path(); paths.ensure_dirs()
    keep = os.path.join(paths.HOSTS_BACKUPS, time.strftime('hostsacl.%Y%m%d-%H%M%S.txt'))
    s = subprocess.run(['icacls', p, '/save', keep], capture_output=True, text=True, errors='replace', timeout=30, creationflags=0x08000000)
    if s.returncode != 0: raise HostsError(f'could not save the current permissions ({(s.stdout + s.stderr).strip()[:200]}); nothing was changed')
    r = subprocess.run(['icacls', p, '/reset'], capture_output=True, text=True, errors='replace', timeout=30, creationflags=0x08000000)
    if r.returncode != 0: raise HostsError(f'icacls /reset failed: {(r.stdout + r.stderr).strip()[:200]}; the old permissions are saved in {keep}')
    return dict(changed=True, saved=keep)


VPN_DNS_SECURITY = ('nord', 'openvpn', 'expressvpn', 'protonvpn', 'wireguard', 'mullvad', 'surfshark', 'cyberghost', 'privateinternetaccess', 'windscribe', 'tailscale', 'zerotier', 'cloudflarewarp', 'adguard', 'nextdns',
                    'kaspersky', 'avp', 'avast', 'avg', 'norton', 'mcafee', 'bitdefender', 'vsserv', 'ekrn', 'malwarebytes', 'sophos', 'webroot', 'spybot', 'pdanet', 'proxifier', 'sandboxie', 'acrylic', 'simplednscrypt')


def resolver_extra(ps=None):
    """For the support bundle: how Windows itself answers for the CDN name (DNS Client cache entry, a second lookup path), the name-resolution layers installed, and the names of VPN, DNS or security services present."""
    run = ps or _ps_json; h = paths.HOST
    out = dict(dns_client_cache=run("@(Get-DnsClientCache -Entry '" + h + "' -ErrorAction SilentlyContinue | Select-Object Entry,Type,Status,Data)"),
               dotnet_lookup=run("@([System.Net.Dns]::GetHostAddresses('" + h + "') | ForEach-Object { $_.IPAddressToString })"),
               namespace_providers=run("@(Get-ChildItem 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\WinSock2\\Parameters\\NameSpace_Catalog5\\Catalog_Entries' -ErrorAction SilentlyContinue | ForEach-Object { $p = Get-ItemProperty $_.PSPath; @{library = [string]$p.LibraryPath; enabled = $p.Enabled} })"),
               nrpt_policies=run("@(Get-DnsClientNrptPolicy -ErrorAction SilentlyContinue).Count"))
    sv = run("@(Get-Service | Select-Object Name,Status)")
    if isinstance(sv, list): out['vpn_dns_security_services'] = sorted(f"{s.get('Name')}: {s.get('Status')}" for s in sv if isinstance(s, dict) and any(k in str(s.get('Name', '')).lower() for k in VPN_DNS_SECURITY))
    else: out['vpn_dns_security_services'] = sv
    return out


def resolve_check(timeout=3.0):
    """What the system resolver returns for HOST per family. -> {'v4': [...], 'v6': [...], 'ok': bool}"""
    res = {}
    for key, fam in (('v4', socket.AF_INET), ('v6', socket.AF_INET6)):
        try: res[key] = sorted({a[4][0] for a in socket.getaddrinfo(paths.HOST, 80, fam, socket.SOCK_STREAM)})
        except Exception as e: res[key] = [f'ERR {e}']
    res['ok'] = res['v4'] == ['127.0.0.1'] and res['v6'] == ['::1']
    return res
