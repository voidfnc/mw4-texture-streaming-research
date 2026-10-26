# Changelog

## 0.4.4-beta
**Fix: step 3 of the setup could fail with a raw Windows error on a damaged game-folder file system.**

- **Fix: step 3 ("one small change in your game folder") could fail with a raw Windows message ("The file or directory is corrupted and unreadable").** This happens when Windows itself can no
  longer read that folder's file system data, usually because the drive was also written to by another operating system. The tool cannot repair this, so it now says so plainly and points at `chkdsk <drive>: /f`
  (run from an administrator command prompt) instead of showing Windows' bare error text. The new text is translated into all languages.

## 0.4.3-beta
**Multiplayer / HQ (`cod.exe`): experimental support so people can test it, and a fix for port 80 held by Windows itself.**

- **Fix: "Terminate System (pid 4)" did nothing.** When Windows itself holds port 80 (the System process, pid 4, which is the web server driver behind IIS and other Windows web services), the Doctor offered
  *stop port owner* for it, Windows refused, and the fix still reported success. Now:
  - a port owner that is part of Windows (System, `svchost.exe`, the core service hosts) is never offered for ending;
  - the Doctor says that Windows itself holds the port and names the running Windows web services that may be the reason (World Wide Web Publishing Service / IIS, SQL Server Reporting Services, Web Deployment
    Agent, BranchCache), and offers *stop web service (UAC)* for the first one after a confirmation; it says how to start it again (`sc start <name>`);
  - when no known service is running it explains instead, with the administrator command that shows which program uses the port;
  - a fix reports success only when the port is really free afterwards; failures say which program could not be ended and why;
  - the home screen and the failed-start message say "Windows" instead of "another program" in this case.
  The new texts are translated into all languages.

- **netwatch follows any game program.** It was tied to `sp26-cod.exe`; it now watches every name in the game process list (default `sp26-cod.exe` and `cod.exe`) and says which program made each DNS lookup or connection.
  With it on, a support bundle shows what the multiplayer / HQ game connects to.
- **A card for multiplayer / HQ.** When only `cod.exe` is running and nothing has reached the helper, the card now says that this is experimental, that requests may start only when a match or map loads, and how to
  send a useful report. It waits 4 minutes instead of 90 seconds before appearing. The campaign text is unchanged.
- **The disk guard never ends the multiplayer game by default.** It still ends `sp26-cod.exe` at the limit. If only a game program that is not on its list is running, the log says it is warning only.
- **The first-run notice is updated and translated.** It said "offline / single-player use only, do not use it with online services". It now says the tool only delivers texture files the game asks for, gives no
  advantage over other players, was built and tested on the campaign, that multiplayer and HQ are experimental, and that using a local proxy during online play is at the user's own risk. It was English only until now;
  it is translated into all languages. (The notice is shown once per version, so people see the new text with the next release.)
- **Wording.** The README and the disclaimer no longer say single-player only: the tools deliver only texture files the game requests and give no gameplay advantage. Multiplayer / HQ is called experimental and
  untested, with the same use-at-your-own-risk notice. New section *Testing multiplayer / HQ* in the getting-started guide.

## 0.4.2-beta
**The Xbox / Microsoft Store version: its chunk lists are found.**

- **Fix: "CDN chunk lists: none found" on the Xbox / Microsoft Store version.** That build ships the chunk lists as `*_cdn_stub.xpak` (for example `sp26_cdn_stub.xpak`) instead of `*_cdn.xpak`, so the
  program found no lists: the offline copy and the texture pack had nothing to plan from, and the helper could not apply the detail-level cap. The program now uses a `_stub` list whenever the normal list
  of that package is not there; a normal list always wins, so installs that have them behave exactly as before. Nothing has to be copied or renamed by hand any more, and nothing is written to the game
  folder. The Doctor row says how many lists were found and how many are in the stub form (translated into all languages).

## 0.4.1-beta
**The game setup on drives that cannot hold folder links, a clearer step 3, a picture-cache fix and a round of fixes from a code audit.**

- **Fix: "[WinError 1] Incorrect function" in the game setup, now explained.** The setup makes `sp26\xpak_cache` a folder link (a junction), and exFAT and FAT32 drives cannot hold one: Windows answers
  "Incorrect function". HD textures need both setup changes (online mode and the link), so the game folder has to be on an NTFS drive. The program now looks at the drive first. On a drive without links it
  makes the online-mode change, leaves the link out and never moves a folder aside for it, and step 3 of the first-run setup becomes *HD textures cannot work on this drive*: it names the drive's file system,
  says to move the game to an NTFS drive, and offers *Choose another folder* for its new place. Settings shows *Not possible on this drive*, the Doctor row warns, and the checklist does not pass. Other errors
  now say which change failed ("could not change configs.main.ini: ...", "the settings file was changed, but the cache link sp26\xpak_cache could not be made: ...") and explain Windows' bare error 1.
- **Step 3 stays required.** There is deliberately no *Skip* button: without the setup the game does not use the textures the helper sends.
- **Fix: `image "pyimageNN" doesn't exist` in the window's log.** The window keeps its computed pictures in a cache that dropped the oldest ones once it held 600. The oldest are the permanent ones
  (logo, icons, buttons), so a long session could free one a canvas item still showed. Pictures that are on screen are now kept, however old; only unused ones are dropped.
- **Proxy.** A byte range (`Range: bytes=a-b`, `a-`, `-n`) of a chunk is now served from the mirror, also in offline mode, where it used to be answered with a 404; a range that cannot be satisfied gets a
  416. A game that cancelled a request while the mirror was answering was counted as a mirror miss and the chunk was fetched from the CDN (or refused in offline mode); it is now only counted as a cancelled
  request. A `HEAD` request that went to the CDN reported a size of 0.
- **Mirror download.** The CDN's `Retry-After` on a 429 or 503 is now honoured (it was read from the wrong object and always ignored).
- **Disk guard.** In *end the game* mode it logged "terminated" even when `taskkill` failed, and then stopped watching. It now says what happened (ended / not running / refused, with Windows' answer), keeps
  watching unless the game was really ended, and does not repeat the same line every few seconds.
- **Helper start-up.** A helper that exits within a fraction of a second (a bad argument, an import error) was recorded as running, so Start session waited 90 seconds. It is now reported as not started,
  and the log tail is shown.
- **Hosts file.** A stray `ccs-managed` start marker left by hand no longer makes *Put it back* delete the lines between it and our block. A hand-added loopback line that also names other hosts
  (`127.0.0.1 localhost cod-assets...`) keeps the other names; only our host name is taken off it.
- **Check my PC** judges the session by the settings it was started with (a profile's own port, offline mode and guard limit), not by the base settings.
- **Support bundle.** The Windows user name is taken out of every file (`C:\Users\<user>\...`, also in JSON), the hosts file is reduced to our block and the lines naming the game's host (the rest is
  not included), and a new `state/game_setup.json` shows the game drive's file system and the setup state (no paths), which is what the first question about a setup error is.
- **Check my PC no longer counts as game traffic.** Its own test request to the helper was counted, so right after *Turn on HD textures* Home could say "1 textures delivered" and the checklist could mark
  "the game used the helper" before the game had started. That request is now marked and left out of the counters, the recent list and the log.
- **Window.** One failing dialog or message no longer stops the activity log and leaves Start / Stop and Home's button disabled until a restart (the loop that handles them survives an error, and a worker
  waiting for a dialog is always released). The log readers survive a log that is rotated or locked at that moment. Tooltip timers are cancelled when their widget goes away (no more "invalid command
  name" dialog). Home no longer sits on "Turning on..." with no way out when a helper runs without a finished session; it offers *Turn on HD textures* again. Going back from *Use only this copy* to
  *While I play* switches the proxy back from offline mode (it stayed offline, so every chunk missing from the mirror was a 404).
- **Folder names with square brackets** (for example `Game [Edition]`): the chunk lists, the cache views, the saved reports and the proxy's index were looked up with patterns that read `[...]` as a
  character class and found nothing. Backing up or restoring the cache checks the free space of the drive the cache is on (it checked the program's drive).
- **A Russian walkthrough video.** The same walkthrough in Russian (about seven minutes): the 0.4.0-beta window in Russian, Russian captions and a Russian computer-generated voice. It is attached to the 0.4.0-beta
  release as `MW4-Texture-Streaming-Walkthrough-ru.mp4` and embedded in the README, which also has a short note at the top, in Russian, about what is and is not available in Russian (the window and the installer are; the
  written documentation is still English only).
- **Release script** stops when `git fetch` or `git rev-parse` cannot answer, instead of comparing two empty answers.
- **Tests.** About 45 new cases (drive without links, link errors, the required step 3, the cache limit, the proxy fixes, the hosts and guard fixes, the bundle) and an opt-in test on a real exFAT virtual disk
  (`CCS_TEST_EXFAT=1`, needs administrator rights).

## 0.4.0-beta
**Twelve languages, and "See the full report" now shows the report.**

- **Languages.** English, Russian, Chinese (Simplified), Spanish, French, German, Portuguese (Brazil), Turkish, Polish, Japanese, Korean and Italian. Settings has a *Language* row (Automatic follows the language chosen in
  the installer, else the Windows display language); changing it restarts the window and leaves a running session alone. Logs, saved reports, file names and tool names stay English on purpose. Missing text falls
  back to English, so an untranslated line never breaks the window. The translations are machine drafts and have not been proofread: corrections welcome.
- **Installer.** The setup wizard shows a language list first (preselected from Windows), translates its own pages, task names, prompts and the "what this setup does" text (the licence stays English), and saves the choice as
  the program's default language (`language.txt` next to the program, removed on uninstall). Simplified Chinese uses a wizard file written for this project (`packaging/lang/ChineseSimplified.isl`).
- **Under the hood.** `tools/ccslib/i18n.py` (the English text is the key; templates for text built from parts; one hook translates every widget, canvas and dialog `text=`), `tools/ccslib/lang/<code>.json`, and
  `tools/i18n_extract.py` (lists the strings, `--check` finds missing keys and broken placeholders). A test fails when window text changes without the list being updated. `CCS_LANG=de` forces a language.
- **Fix: *See the full report* opened an empty page.** The Report tab was only filled when a report was written during that run of the window; after a restart, or when the stop-time report was skipped because a saved
  one already covered the run, it stayed blank. It now shows the newest saved report (selected in the *Saved* list), writes one from the proxy log if there is traffic but no report yet, and otherwise says there is no report yet.

## 0.3.0-beta
**A new main window.** Everyday use is one screen with one button; every old tab is still there in Advanced mode.

- **Home screen.** *Turn on HD textures*, start the game, *Turn off*. A ring shows the state (off, turning on, on, playing, done, needs attention), a step strip says where you are, and three cards show the game folder, how textures load and the free
  space. While you play it shows the textures delivered, the speed, failed requests, where they come from and a three-minute graph. Problems appear as a card that says what happened and has the button that fixes it. Every part has a hover tip.
- **First start in three questions.** The research notice (a full screen now, not a dialog), where the game is, how textures should load, and, only if needed, the one-time game setup. The old yes/no offer of the checklist now appears only when Advanced mode is opened first.
- **Settings panel.** Slides in from the right: how textures load, the offline copy, game folder, game setup state, Check my PC, the word list, reports, the before/after test, reduced motion, Advanced mode.
- **Offline copy page.** A progress ring and bar, pieces and gigabytes, speed and time left, Pause and Resume, *How much* and *Detail level*, and *Use only this copy* when the download is complete. It drives the same downloader as the Texture pack tab, with the same notices.
- **Advanced mode.** Every tab kept, now behind a side navigation grouped as Live, Textures, Game and PC, Setup. Each page has a title and one line saying what it is for, long texts wrap to the window, a page taller than the window scrolls, and the check boxes, radio buttons, lists and buttons use the
  same dark look. The Dashboard's profile and action rows no longer run off the side.
- **Look and feel.** Anti-aliased rounded shapes, line icons and a progress ring drawn by the program itself (still no extra libraries). The program tells Windows it scales itself, so it is sharp at 125 and 150 percent (`CCS_NO_DPI=1` turns that off). *Reduce motion*
  in Settings stops the animations, and the Windows animation switch is honoured.
- **Under the hood.** New `tools/ccslib/ui.py` (the drawing kit), `home.py` (what each screen says, as plain data, fully tested) and `homeui.py` (the screens). The window cancels its timers when it closes. About 50 new tests (323 in total).
- **Docs.** README, USAGE, GETTING-STARTED, ARCHITECTURE and TEXTURE-PACK describe the new window, and so do the installer's start page and its "what setup does" text. The program screenshots and the four installer pages are new, and the walkthrough video now shows the new window.

## 0.2.6-beta
**You can switch between the quick fix and the offline copy, and the offline copy's text now says the program still has to run.**

- **Step 1 of the guided setup can be changed.** The choice between *Quick fix* and *Offline copy* could not be undone before: *Start over* keeps it on purpose, and a finished step 1 showed no
  buttons. It now has one button that switches to the other path (*Use offline copy* or *Use quick fix*), and the checklist follows (the Texture pack step appears or goes away). The choice
  only shapes the checklist: with the Default profile the helper serves an offline copy you already have first, whichever path is chosen.
- **The offline copy needs a session too.** The helper has to run every time you play (*Start session*, then the game), because the game still asks for its textures through it; the copy
  replaces the download, not the helper. The path texts, the glossary, the Texture pack tab and the docs say so. The Texture pack tab also names the folder the copy is kept in (it was only
  in the Game tab, which Simple view hides), and the hover text of the *Mirror* light explains that "off" while a session runs means no copy was found there.
- **Docs:** USAGE has a section on using an offline copy you have already downloaded; the README has two new troubleshooting entries (the offline copy and the program, and counters that stay at
  zero until a mission has loaded) and a link to a narrated walkthrough video (attached to the release). The README shows two in-game frames (`docs/ingame/`, with the game folder path covered in
  the first and no metadata in either), and `docs/FINDINGS.md` has a section 9 on the game folder settings (online mode and the cache link): what was observed in one session, what was not
  tested separately, and what is still unchecked.
- **Wording:** the program's own messages about the game's Steam settings use the same neutral wording as the docs (the 0.2.5-beta files still use the older wording in a few messages). One older
  changelog line no longer refers to where a fix came from.
- The screenshots in the README are unchanged (program windows from 0.2.3-beta, installer pages from 0.2.5-beta): this version changes one button and some text.

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

- **Game setup check and fix.** In some game folders the Steam settings put the game in offline mode and the game looks for its cache in `sp26\xpak_cache` while the engine fills
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
Fixes for slow mirror downloads (about 1 Mbit/s on a 100 Mbit/s line).

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
