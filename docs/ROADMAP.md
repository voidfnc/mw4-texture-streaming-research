# Roadmap: a download that needs no Python

_Status: planned, nothing built yet. Written for version 0.1.3-beta._

Today you need Python 3.10+ to run the toolkit. The goal of the next release is a portable Windows zip that anyone can unzip and double-click, with no Python, no
pip and no console window. This page is the plan, so it is easy to pick up later or to review.

## What users should experience

1. Download `MW4-Texture-Streaming-<version>-win64.zip` from the Releases page and unzip it anywhere.
2. Double-click `MW4 Texture Streaming.exe`.
3. The guided setup offers itself, finds the game folder, ticks the steps, and shows the Windows permission prompt for the hosts file.
4. `Restore hosts.bat` next to the exe is the always-working undo, and `START HERE.txt` has five lines.

## Options considered

| Option | Verdict |
|---|---|
| PyInstaller, one folder (not one file), windowed | **Chosen.** About 10 MB zipped. The code is standard-library only, so nothing exotic has to be bundled. |
| Embeddable Python zip plus our scripts | No. It ships without tkinter, so the window would not open. |
| Nuitka | Later, if antivirus flags the PyInstaller build. Slower builds. |
| Installer (Inno Setup / MSIX) | Later. A portable zip needs no admin and no registry, which suits a tool that touches the hosts file. |
| A `Start (needs Python).bat` that offers `winget install Python` | **Kept as the fallback** for people who prefer to run from source. |

## Code changes needed

The app starts its helpers (proxy, mirror, disk guard, hosts editor, netwatch) by running `python script.py`. Inside a frozen exe there is no `python`, so:

- One launcher function in `ccslib`, for example `argv_for('ccsproxy', args)`. From source it returns `[python, script, ...]`; frozen it returns `[exe, '--ccs-run', 'ccsproxy', ...]`.
- A small dispatcher entry point (`ccs.py`): no arguments opens the window, `--ccs-run NAME` runs that tool's `main`. The tool modules go into PyInstaller's `hiddenimports`.
- The elevated hosts step runs the same exe as `--ccs-run ccshosts`.
- When frozen, settings, logs and reports live in `%LOCALAPPDATA%\MW4TextureStreaming` (the unzip folder may be read-only, and this survives updating the zip). `CCS_WORK` still overrides it.
- The desktop shortcut and `Restore hosts.bat` point at the exe instead of python.
- Tests: the source-mode suite stays as it is; add tests that simulate `sys.frozen` for `argv_for` and that run the dispatcher as a real subprocess.

## Build and release automation (GitHub Actions)

- Triggered by pushing a tag such as `v0.2.0-beta`.
- Run the tests, build with PyInstaller (UPX off, since it triggers antivirus), then smoke-test the built exe: `--selftest`, `--ccs-run ccsproxy` against a fake origin, and the first-run dialog.
- Output: the zip, `SHA256SUMS` and a build-provenance attestation, attached to a **draft** release that is reviewed before it goes public.
- Built on the clean runner and not on a developer PC, so no local paths or user names end up inside the exe. Actions are pinned to full commit SHAs.

## Windows warnings and antivirus

A new unsigned exe that edits the hosts file and runs a local proxy will meet SmartScreen ("Windows protected your PC") and may be flagged by some antivirus engines.

1. README section with the "More info, Run anyway" steps, the SHA256 and a VirusTotal link; proper exe metadata (product name, description); a submission to Microsoft's false-positive portal.
2. Code signing through a free open-source signing programme (for example SignPath Foundation), once approved. This removes the "unknown publisher" warning.
3. Fallback: run from source with Python, where every line is visible.

## Making it easy for non-technical users

- A **Download** box at the top of the README with three steps and screenshots (no game imagery).
- A friendly crash screen with "Copy support info" instead of a window that vanishes.
- An update check that is opt-in and off by default; it only says that a newer version exists.
- The version is in the window title and in `--version`.

## Testing before it goes public

- Windows Sandbox (a clean VM without Python) with the zip mounted: exactly what a stranger gets.
- Cases: a path with spaces and a non-ASCII user name, a non-English Windows, no administrator rights, port 80 in use, Restore hosts with the window closed.
- One real run with the game: requests flow, hosts apply and restore, the report is written.

## Phases

| Phase | Work | Output |
|---|---|---|
| R1 | `argv_for`, dispatcher, data folder, shortcut and restore fixes, tests | a PR with no change in behaviour when run from source |
| R2 | PyInstaller spec, icon, exe metadata, `START HERE.txt`, `Restore hosts.bat`, `packaging/` | a local build to test in Windows Sandbox |
| R3 | Release workflow, smoke tests, checksums, attestation | a test tag produces a draft release |
| R4 | README Download section, release notes, SmartScreen guidance | docs |
| R5 | Sandbox and real-PC test pass | a go/no-go list |
| R6 | Tag `v0.2.0-beta`, review the draft, publish | the first packaged release |

Open questions: whether to apply for free code signing before the first release, and the version number for it (0.2.0-beta is proposed, since a packaged build is a bigger step than 0.1.4).
