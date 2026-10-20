"""launch.py - how the toolkit starts its own helper programs (proxy, mirror, disk guard, hosts editor, netwatch, report).

From source they are scripts run by the same Python (`python tools/ccsproxy.py ...`). In the packaged app there is no Python to call, so the same tools are
built into the program and started as `ccs-cli.exe --ccs-run ccsproxy ...`; `run_tool()` is the other end of that call. Everything that starts a helper goes
through `argv_for()`, so source and packaged builds behave the same way.
"""
import importlib, os, runpy, sys
from . import paths

RUN_FLAG = '--ccs-run'
CLI_EXE = 'ccs-cli.exe'                                                 # console build of the same program: helpers and command-line use (the GUI exe has no console)
GUI_EXE = 'MW4 Texture Streaming.exe'
TOOLS = ('ccsproxy', 'ccsmirror', 'diskguard', 'ccshosts', 'netwatch', 'ccsreport')
INTERNAL = {'uninstall-prep': 'ccslib.uninstall', 'selfcheck': 'ccslib.selfcheck', 'gamefix': 'ccslib.gamefix'}   # not scripts: small commands the installer and the window call (module must have main(args) -> exit code)
FROZEN = bool(getattr(sys, 'frozen', False))


def cli_exe(frozen=None, executable=None):
    """The console exe next to the running one (packaged build), else the running interpreter."""
    exe = executable or sys.executable
    if FROZEN if frozen is None else frozen:
        c = os.path.join(os.path.dirname(os.path.abspath(exe)), CLI_EXE)
        return c if os.path.exists(c) or executable else exe
    return exe


def argv_for(name, *args, frozen=None, executable=None):
    """Command line that runs tool `name` with `args`. Source: [python, tools/<name>.py, ...]. Packaged: [ccs-cli.exe, --ccs-run, <name>, ...]."""
    if name not in TOOLS and name not in INTERNAL: raise ValueError(f'unknown tool {name!r}')
    a = [str(x) for x in args]; frozen = FROZEN if frozen is None else frozen
    if frozen: return [cli_exe(True, executable), RUN_FLAG, name, *a]
    if name in INTERNAL: return [executable or sys.executable, os.path.join(paths.TOOLS, 'ccs.py'), RUN_FLAG, name, *a]     # no script of its own: the entry point runs it
    return [executable or sys.executable, os.path.join(paths.TOOLS, name + '.py'), *a]


def gui_argv(frozen=None, executable=None):
    """Command line that opens the control window (for shortcuts)."""
    frozen = FROZEN if frozen is None else frozen; exe = executable or sys.executable
    if frozen:                                                          # always the windowed program, also when asked from the console one
        gui = os.path.join(os.path.dirname(os.path.abspath(exe)), GUI_EXE)
        return [gui if os.path.exists(gui) else exe]
    pyw = os.path.join(os.path.dirname(exe), 'pythonw.exe')
    return [pyw if os.path.exists(pyw) else exe, os.path.join(paths.TOOLS, 'ccsgui.py')]


def resource(name):
    """Path of a bundled file (the icon), or '' when it is not there."""
    for base in (paths.TOOLS, getattr(sys, '_MEIPASS', ''), os.path.join(paths.TOOLS, '..', 'packaging')):
        p = os.path.join(base, name) if base else ''
        if p and os.path.exists(p): return os.path.abspath(p)
    return ''


def run_tool(name, args):
    """Run tool `name` in this process as if started from the command line -> exit code."""
    if name in INTERNAL: return int(importlib.import_module(INTERNAL[name]).main(list(args)) or 0)
    if name not in TOOLS:
        print(f'unknown tool {name!r}; known: {", ".join(TOOLS + tuple(INTERNAL))}', file=sys.stderr); return 2
    for s in ('stdout', 'stderr'):                                      # a windowed exe has no console: keep print() from failing
        if getattr(sys, s) is None: setattr(sys, s, open(os.devnull, 'w'))
    sys.argv = [name + '.py', *[str(x) for x in args]]
    try: runpy.run_module(name, run_name='__main__', alter_sys=True)
    except SystemExit as e:
        if e.code is None: return 0
        if isinstance(e.code, int): return e.code
        print(e.code, file=sys.stderr); return 1
    return 0
