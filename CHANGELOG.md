# Changelog

## Unreleased
- **Docs:** `docs/FINDINGS.md` has a new section 9 on the game folder settings (online mode and the cache link) with what was observed in one session, what was not tested separately, and
  what is still unchecked. No program change. (One older changelog line no longer refers to where a fix came from.)

## 0.2.5-beta
**The installer installs for all users by default.** "For me only" stays an option on its first screen.

- **Program Files by default.** The program runs as administrator, so its files should be somewhere only an administrator can change: setup now asks for one Windows permission prompt and
  installs into Program Files for all users (uninstall entry and shortcuts for everyone). "For me only" installs into your own profile without administrator rights, as before; the
  README's *Administrator rights* section says what that choice means. Silent installs: all users is the default, `/CURRENTUSER` for the current user only. If you switch from one to the
  other, uninstall the old copy first.
- **The installer test covers both.** `packaging\build.bat` installs, upgrades (with the hosts block on) and uninstalls once for the current user and once for all users (when the build
  window is elevated), and refuses to run if shortcuts of a real installed copy are in the way.
- The installer's four README screenshots are retaken for this version; the program's screenshots are still from 0.2.3-beta.

## 0.2.4-beta
**The program runs as administrator by default.** It asks for permission once, when it starts, instead of per action.

- **Elevated from the start.** `MW4 Texture Streaming.exe` now carries an administrator manifest, so Windows shows the permission prompt (UAC) when it opens and the program then
  writes to the hosts file, the game folder and a mirror inside Program Files without asking again. That also removes a whole class of "cannot write" problems for a game in
  Program Files. If the prompt is declined the program still starts and asks per hosts-file change, as before. From source, `ccsgui.py` relaunches itself elevated once;
  `CCS_NO_ELEVATE=1` or `--no-elevate` keeps it unelevated. `ccs-cli.exe` (helpers, command line, setup's hooks) is unchanged and does not ask.
- **Setup and uninstall still work.** Setup starts the program with `shellexec` so the prompt can appear, and `uninstall-prep stop-helpers` asks Windows for permission when the helpers
  were started by the elevated window (an unelevated process cannot end them); `procs.stop` no longer forgets a helper it could not end.
- **Docs:** a new *Administrator rights* section in the README says what the rights are used for and notes that an elevated program in a folder other programs of yours can write to
  (the per-user install folder) could be replaced; install for all users if that matters to you. The README screenshots are from 0.2.3-beta (the windows did not change).

## 0.2.3-beta
**One fix: the mirror index can be read from a folder you cannot write to.** Nothing else changes.

- **A mirror in a folder you cannot write to is read correctly.** The mirror index could not be opened by a normal (non-administrator) user when the mirror sat in a folder only an
  administrator can write to, such as inside Program Files: the Doctor showed *Mirror: unable to open database file*, the proxy started with no stored chunk keys, and the
  session was reported as not ready. The proxy, the Doctor, the texture pack check and the reports now read the index without writing next to it (`ccslib/mirrordb.py`).
  The Doctor's *Mirror folder* row says when a folder is read-only for you, and *Download* in the Texture pack tab explains it instead of failing later.

## 0.2.2-beta
**Game setup: a better undo and a few smaller gaps closed.** No other change.

- **Game setup: a better undo.** It puts only the two settings back (to their earlier values, or removes them if they were not there; a settings file that did not exist is removed),
  so other edits to `configs.main.ini` since then stay. It asks Windows for permission when the game folder needs it, and the Doctor's *Game setup* row has an *Undo the game setup*
  button after a setup made by this tool.
- The game-running check also knows the default game process names when the setting was edited, and the setup is not offered when the engine cache folder setting points at
  `sp26\xpak_cache` itself.

## 0.2.1-beta
**Game setup: helps the game use the textures it is sent.** One new check and one-click fix, nothing else changes.

- **Game setup check and fix.** Some repacks run the game's Steam emulator in offline mode and the game looks for its cache in `sp26\xpak_cache` while the engine fills
  `xpak_cache` in the game folder, so streamed textures can arrive without ever showing. The Doctor has a new *Game setup* row and the guide's *Check this PC* step asks for it
  when it is needed; *Set up the game* (one click, after a confirmation) sets `offline=0` and `disable_lan_only=1` in `sp26\steam_settings\configs.main.ini` (a copy of the
  original is kept next to it, other lines are left alone) and makes `sp26\xpak_cache` a folder link (junction) to `xpak_cache`. A real folder in the way is renamed aside, never
  deleted. Nothing is changed while the game runs, applying twice changes nothing, and Windows is asked for permission only when the game folder needs it. A link of your own at `sp26\xpak_cache`, a read-only settings file or a failed link step are
  reported in plain words and left as they were (a moved-aside folder is put back).
  Command line: `ccs-cli.exe --ccs-run gamefix status | apply | undo`.

## 0.2.0-beta
**An installer, a portable zip, and no Python needed.** From this version each release offers a Windows setup program, a portable zip, and the source as before.

- **`MW4-Texture-Streaming-<version>-Setup.exe`**: a setup wizard (Inno Setup). It installs for the current user by default, with no administrator rights; "for all users" is an
  option on its first screen. It shows the notice and licence, says what it will and will not do, adds Start menu entries and an optional desktop shortcut, and registers an
  uninstall entry. It never touches the hosts file. Settings, logs and reports stay in `%LOCALAPPDATA%\MW4TextureStreaming`, separate from the program.
- **Hosts-safe update and uninstall.** If a session is running or the hosts override is on, setup and the uninstaller stop the helpers and take the override out first (Windows asks
  once), and ask before deleting your settings. A texture mirror and the game folder are never deleted. Silent switches: `/VERYSILENT /DIR= /MERGETASKS=`.
- **Portable zip**: unzip anywhere, nothing is installed, settings stay in a `data` folder next to the program.
- **Same program inside**: `MW4 Texture Streaming.exe` (the window) and `ccs-cli.exe` (the helpers and every command-line tool: `ccs-cli.exe --ccs-run ccsproxy ...`). The helpers
  are started through one function (`ccslib/launch.py`), so running from source behaves exactly as before.
- **Releases are one command**: `packaging\build.bat` builds the program, the zip and the installer, smoke-tests the result and installs, upgrades (with the hosts block on) and
  uninstalls the Setup.exe on the build PC; `python packaging/release.py` then makes a draft GitHub release (files, checksums, notes from this changelog). There is no CI pipeline.
  The version is read from `tools/ccslib/version.py` only, and the release script refuses files from another version.
- New: `ccs-cli.exe --ccs-run selfcheck` (starts and stops the proxy and disk guard and makes a shortcut, without touching the hosts file) and `uninstall-prep` (what the installer calls).
- The window has an icon, and holds a named mutex so the installer knows it is open.
- Fixed: a Python warning in `netwatch.py`.
- 28 new tests (196 in total): launcher and dispatcher, uninstall hooks, selfcheck, version and packaging consistency (the installer script, build script, spec, release script and requirements must agree with the code and the version).

## 0.1.3-beta
Guided setup for first-time users, plus the fixes found while building it. Nothing changes for people who already have it running; the guide is optional.

- Session reports and the Doctor no longer print numbers from the author's own test runs ("runs 1-3 of 2026-10-19/20", "64 GB in run 10"). They looked like a comparison
  against your own history and were not.
- Pressing *Stop session* right after the game exited no longer writes a second copy of the report when the first one already covers the whole launch.
- Two new tests (101 in total).
- **Guided setup (optional).** A checklist on the Dashboard for first-time users, offered once on the first start and available any time from the *Guide* button or
  *Settings -> Help*. It follows the real state of the PC (game folder, port, disk, session, requests) and ticks each step off by itself. *Find my game folder* looks in
  the folder around the tool, Steam libraries and the usual places on every fixed drive, judges folders by what is inside rather than by name, and always asks you to
  confirm; any folder can be chosen by hand.
- First-run fixes found while building it: the proxy no longer crashes at start when there is no mirror yet (it used to die on the missing `index.sqlite`), and the
  Doctor reports a missing mirror as information instead of a failure unless the profile needs the mirror.
- The red *SETUP NEEDED* bar on the Dashboard is hidden once setup is complete (it used to stay as an empty red strip).
- A game folder without the `*_cdn.xpak` chunk lists no longer blocks *Start session*: the Doctor and the folder check warn instead (the proxy works without them; the
  mirror and the detail-level cap need them).
- Tooltip and layout hardening. 37 new tests (138 in total).
- **Simple view.** One button (or *Settings -> Help*) hides the advanced tabs, the profile picker, the graph and most counters; the first-run offer turns it on with the guide.
- **Spotlight, hover help and *Words*.** The control for the current step is highlighted, every status light and counter explains itself on hover, and a plain-language list of
  the terms is one click away (and in the new `docs/GETTING-STARTED.md`).
- **Help cards** for the usual failures (refused hosts write, closed permission prompt, busy port, vanished hosts entry, no traffic, unreachable CDN, low disk), with a button each.
- **What happened** summary after a session, and a four-step **before/after test** to compare the game with and without the tool on your own PC.
- Fixes: the guide showed "Press Start session" on a finished session step, the panel was empty for the first second after start, a stray control character in the README
  (`tools\restore-hosts.bat` was printed wrong). `--selftest` no longer shows the first-run dialogs.
- 30 new tests (168 in total).
- README screenshots (`docs/images/`, regenerated with `tools/make_screenshots.py` for each release), and a test that
  keeps the README and this changelog in step with the version number.
- The Proxy tab no longer prints the author's own test-run numbers under the size histogram.

## 0.1.2-beta
Fixes for slow mirror downloads (a user on a 100 Mbit/s line saw about 1 Mbit/s).

- The mirror no longer depends on one built-in CDN address. While the hosts override is on, the old code asked `nslookup` for the edge address and could not read
  the answer (this host lists IPv6 first, and the labels are translated on non-English Windows), so every run silently used a fixed address that can be far away.
  Now: the system resolver's answer is remembered (`tools/work/edge_cache.json`), otherwise the tool asks public resolvers directly over UDP, and before a run it
  downloads two small real chunks from each candidate and keeps the fastest one that answers correctly. A server that answers 403 or the wrong length is rejected.
- A stall watchdog: with *My line speed* set, if the rate stays under 20 % of it for a minute (and it is not a cap, a quota, a lost link or a 429), the edge
  addresses are measured again and the run switches if another one is clearly better. At most once every three minutes.
- If only the built-in fallback address is left, the log, the Texture pack tab and the Doctor say so.
- The progress line shows a rolling 30-second speed in MiB/s **and Mbps** (100 Mbps is about 11.9 MiB/s) and the edge address in use.
- The "Connections" hint now matches the code (automatic is 4, not 12).
- 8 new tests (99 in total). The GUI tests free their Tk objects on the main thread, which fixes an occasional crash of the combined test run.

## 0.1.1-beta
Fixes for non-English Windows and a protected hosts file.

- Start session, Doctor and proxy start no longer crash with `'NoneType' object has no attribute 'splitlines'`. Output of `netstat` and other Windows tools is now
  decoded tolerantly, and the port check no longer depends on the English word `LISTENING`.
- A refused hosts write now says what happened ("the file was not changed") and points at the likely cause (read-only attribute, security software) instead of
  claiming a failed rollback. Tooltips on the Hosts tab buttons and a Troubleshooting section in `docs/USAGE.md` explain the fix.
- Two new tests (91 in total).

## 0.1.0-beta
First public-ready beta.

- Hosts manager with a marked block, backups, read-back check and rollback.
- Loopback proxy with mirror origin, offline mode, detail-level cap, live statistics.
- Resumable, verified chunk mirror with scope (campaign / everything / custom packages), detail level (standard, high, ultra), bandwidth cap, daily quota,
  waiting out lost connections, `plan`, `verify --all`, `prune`.
- Control window: session start/stop, Texture pack tab, cache tools, doctor, per-launch session reports, logs.
- Polite client behaviour: User-Agent naming the tool, back-off on HTTP 429/503 (honours Retry-After), 4 connections and 50 requests/s by default, edge address
  from public DNS.
- Bulk-download notice that must be accepted once per version (GUI dialog, or `--accept-notice` on the command line).
- 89 tests that run without the game.
