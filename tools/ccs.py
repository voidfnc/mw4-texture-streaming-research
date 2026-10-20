#!/usr/bin/env python3
"""ccs.py - the one entry point of the packaged app.

  MW4 Texture Streaming.exe            opens the control window (same as python tools/ccsgui.py)
  ccs-cli.exe --ccs-run <tool> ...     runs one of the built-in tools (ccsproxy, ccsmirror, diskguard, ccshosts, netwatch, ccsreport, uninstall-prep)
  ccs-cli.exe --version                prints the version

Source users do not need this file: python tools/ccsgui.py and the individual scripts work as before.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ccslib import launch, version


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == [launch.RUN_FLAG]:
        if len(argv) < 2: print(f'usage: {launch.RUN_FLAG} <tool> [args]; tools: {", ".join(launch.TOOLS + tuple(launch.INTERNAL))}', file=sys.stderr); return 2
        return launch.run_tool(argv[1], argv[2:])
    if argv[:1] == ['--version']:
        if sys.stdout is not None: print(version.USER_AGENT)
        return 0
    import ccsgui
    ccsgui.main(argv)
    return 0


if __name__ == '__main__':
    sys.exit(main())
