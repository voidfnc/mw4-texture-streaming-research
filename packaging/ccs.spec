# PyInstaller spec for the packaged app. Run it through packaging/build.py (which prepares the version resources and the folders this file reads from the environment).
#
# One program, two flavours that share every library file:
#   MW4 Texture Streaming.exe   windowed (no console): the control window, started from the shortcut
#   ccs-cli.exe                 console: the helpers (proxy, mirror, disk guard, hosts editor, ...), command-line use, the installer's hooks
# One folder, not one file: nothing is unpacked to a temp folder at start, which is faster and looks less like malware to antivirus engines. UPX is off for the same reason.
import os

HERE = os.path.dirname(os.path.abspath(SPEC))
TOOLS = os.path.join(os.path.dirname(HERE), 'tools')
VERSION_GUI = os.environ['CCS_VERSION_GUI']
VERSION_CLI = os.environ['CCS_VERSION_CLI']

# modules that are started by name at run time (ccs.py --ccs-run <name>), so PyInstaller cannot see them by reading imports; the list comes from launch.py so it cannot drift
import sys
sys.path.insert(0, TOOLS)
from ccslib import launch
tools = list(launch.TOOLS) + list(launch.INTERNAL.values()) + ['xpakrec', 'cdnxpak', 'ccsgui']

a = Analysis([os.path.join(TOOLS, 'ccs.py')], pathex=[TOOLS], hiddenimports=tools, datas=[(os.path.join(HERE, 'app.ico'), '.')],
             excludes=['numpy', 'PIL', 'pytest', 'unittest.mock', 'test', 'tests'], noarchive=False)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MW4 Texture Streaming', console=False, icon=os.path.join(HERE, 'app.ico'), version=VERSION_GUI, upx=False)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ccs-cli', console=True, icon=os.path.join(HERE, 'app.ico'), version=VERSION_CLI, upx=False)
coll = COLLECT(gui, cli, a.binaries, a.datas, name='MW4 Texture Streaming', upx=False)
