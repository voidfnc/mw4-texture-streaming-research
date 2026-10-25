"""logrot.py - size-based log rotation (name -> name.1 -> name.2 -> name.3), done only while the writing tool is not running."""
import glob, os
from . import paths


def rotate(path, max_bytes, keep=3):
    """Rotate `path` if it exceeds max_bytes. -> True if rotated. Safe to call when the file does not exist."""
    try:
        if max_bytes <= 0 or os.path.getsize(path) <= max_bytes: return False
    except OSError: return False
    for i in range(keep, 0, -1):
        src = path if i == 1 else f'{path}.{i - 1}'; dst = f'{path}.{i}'
        if os.path.exists(src):
            try:
                if os.path.exists(dst): os.remove(dst)
                os.replace(src, dst)
            except OSError: return False
    return True


def rotate_all(max_mb, skip_running=()):
    """Rotate every *.log in the work dir above max_mb. `skip_running` = file basenames whose writer is alive. -> list of rotated names"""
    out = []
    for p in glob.glob(os.path.join(glob.escape(paths.WORK), '*.log')):
        if os.path.basename(p) in skip_running: continue
        if rotate(p, int(max_mb * 2**20)): out.append(os.path.basename(p))
    return out
