"""shortcut.py - create a desktop shortcut that starts CCS Control without a console window (only on explicit user request)."""
import os, subprocess
from . import paths, procs


def create(folder=None, name='CCS Control'):
    """-> path of the .lnk. `folder` defaults to the user's Desktop."""
    py = paths.PY; pyw = os.path.join(os.path.dirname(py), 'pythonw.exe'); target = pyw if os.path.exists(pyw) else py
    script = os.path.join(paths.TOOLS, 'ccsgui.py')
    if folder is None:
        folder = subprocess.run(['powershell', '-NoProfile', '-Command', "[Environment]::GetFolderPath('Desktop')"], capture_output=True, text=True, errors='replace', timeout=30,
                                creationflags=procs.CREATE_NO_WINDOW).stdout.strip()
    if not folder or not os.path.isdir(folder): raise OSError('desktop folder not found')
    lnk = os.path.join(folder, name + '.lnk')
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:CCS_LNK);$s.TargetPath=$env:CCS_TARGET;$s.Arguments='\"'+$env:CCS_SCRIPT+'\"';"
          "$s.WorkingDirectory=$env:CCS_WD;$s.Description='MW4 Texture Streaming Toolkit';$s.Save()")
    r = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True, errors='replace', timeout=30, creationflags=procs.CREATE_NO_WINDOW,
                       env=dict(os.environ, CCS_LNK=lnk, CCS_TARGET=target, CCS_SCRIPT=script, CCS_WD=paths.TOOLS))
    if r.returncode != 0 or not os.path.exists(lnk): raise OSError((r.stderr or r.stdout).strip() or 'shortcut creation failed')
    return lnk
