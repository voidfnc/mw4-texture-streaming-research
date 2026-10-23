# Using the control window

Start it from the Start menu or desktop shortcut (installer), by double-clicking `MW4 Texture Streaming.exe` (portable zip), or with `tools\ccs-gui.bat` (no console window) or
`python tools\ccsgui.py` (source). It asks for administrator rights when it starts (the Windows UAC prompt; from source it relaunches itself elevated once) and then needs no further prompts for the hosts file, the game folder or a mirror inside Program Files. If you decline, it still starts and asks for each hosts-file change as before. `CCS_NO_ELEVATE=1` or `--no-elevate` keeps a source run unelevated on purpose. The installer and the zip need no Python; from source
you need Python 3.10+ with tkinter. The first time it opens it shows a short notice about what the tools are and are not (a full screen, once per version: press *I understand, continue*). Before the first bulk download (Texture pack or Mirror tab) it shows a second notice
that you have to accept once per version; on the command line the same thing is `ccsmirror.py run ... --accept-notice`.

## Installed, portable or from source

| | Program | Settings, logs, reports (`work` below) | Helpers and command line |
|---|---|---|---|
| Installer | `C:\Program Files\MW4 Texture Streaming` (all users, the default) or `%LOCALAPPDATA%\Programs\MW4 Texture Streaming` ("for me only") | `%LOCALAPPDATA%\MW4TextureStreaming` | `ccs-cli.exe --ccs-run <tool> ...` |
| Portable zip | where you unzipped it | a `data` folder next to the program (because of `portable.txt`) | `ccs-cli.exe --ccs-run <tool> ...` |
| Source | the cloned repository | `tools\work` | `python tools\<tool>.py ...` |

`CCS_WORK` overrides the settings location in all three. Tools you can run with `--ccs-run`: `ccsproxy`, `ccsmirror`, `diskguard`, `ccshosts`, `netwatch`, `ccsreport`, plus `selfcheck` (starts and
stops the proxy and disk guard and makes a shortcut, without touching the hosts file) and `uninstall-prep` (what the installer calls). `ccs-cli.exe --version` prints the version.

**Update:** run the newer Setup.exe over the old one (the zip: unzip over the old folder, keeping `data`). Setup stops the helpers and puts the hosts file back first if a session is on.
**Uninstall:** *Apps & features*. If the hosts override is on, it is removed first; you are asked before settings are deleted; a texture mirror and the game folder are never deleted.
**Silent install** (for scripts): `Setup.exe /VERYSILENT /DIR="D:\Tools\MW4 Texture Streaming" /MERGETASKS="!desktopicon"`; all users is the default (administrator rights needed); add `/CURRENTUSER` for the current user only, without administrator rights. If you change from one to the other, uninstall the old copy first.

## The Home screen

The window opens on Home. It shows one thing at a time, always the next thing to do:

| Screen | What it shows | Button |
|---|---|---|
| Before you start | the research notice, once per version | *I understand, continue* |
| Step 1: find your game | the folder the tool found in the usual places. It judges folders by what is inside (a `cod26` or `sp26` folder, the chunk lists, or a known game program), not by name | *Yes, use this one*, *Choose another folder* (a folder that does not look right is accepted if you say *Use it anyway*) |
| Step 2: how should textures load? | *While I play* (no big download, the default) or *Download them once* (the offline copy, about 54 to 82 GB) | *Continue* |
| Step 3: one small change in your game folder | only when the folder needs the [game setup](#game-setup-online-mode-and-the-cache-link) | *Make the change* |
| Ready when you are | a grey ring, the step strip and three cards (game folder, how textures load, free space) | *Turn on HD textures* |
| HD textures are on | a lit ring that pulses, "waiting for the game" | *Turn off* |
| Playing with HD textures | textures delivered, speed, failed requests, where they come from, a three-minute graph | *Turn off when you are done* |
| All done | what the game asked for and that it was delivered (nothing about how the picture looks) | *Done*, *See the full report*, *Compare before / after* |
| A problem | a card with the likely cause and a button: a refused hosts write, a closed permission prompt, a busy port, a hosts entry that disappeared, a game that runs for a minute and a half without any request reaching the helper, an unreachable CDN, a nearly full disk | the fix |

*Turn on HD textures* is **Start session** and *Turn off* is **Stop session**: the same actions as in Advanced mode (the hosts entry, the helper, the disk guard, the doctor run and the report). Turning off still asks what to do with the
hosts entry when your settings say "ask". Nothing on Home changes anything without a click. Tab moves between the buttons, Enter or Space presses one.

- **Hover help.** The ring, the step strip, the cards, the numbers, the footer line and the main buttons have a tooltip. The *words* list is the same one as at the end of [GETTING-STARTED.md](GETTING-STARTED.md).
- **Settings** (top right) slides in a panel: *How textures load* (switches between the two ways at any time), *Offline copy* (its own page), *Game folder*, *One-time game setup*, *Check my PC* (the Doctor), *What do the words mean?*,
  *Reports and logs*, *Before / after test*, *Reduce motion* and *Advanced mode*. Esc or a click outside closes it.
- **The offline copy page** shows how much of the texture pack is on this PC as a ring and a bar, the pieces and gigabytes, the speed and the time left. *Start the download* / *Resume* / *Pause* use the same downloader as the Texture pack tab (the bulk-download notice and the size
  confirmation are shown first, once per version). Two choices sit below: *How much* (campaign only, or everything; a custom list is set in Advanced mode) and *Detail level* (Standard, High or Ultra, see [TEXTURE-PACK.md](TEXTURE-PACK.md)). They are locked while a download runs. When everything is stored
  the page offers *Use only this copy* (the profile *Slow link - offline mirror*) and *Check the files*.
- **Reduce motion.** The ring pulses and spins and the panel slides while something is happening. *Reduce motion* in Settings turns that off, and the program follows the Windows setting too (Settings, Accessibility, Visual effects, Animation effects).
- **Sharp on any display.** The program tells Windows it scales itself, so text and icons are crisp at 125 or 150 percent. `CCS_NO_DPI=1` keeps Windows' own stretching if a display driver misbehaves.

## Guided setup in Advanced mode (the older checklist)

The Dashboard in Advanced mode still has the optional checklist the earlier versions had. It is switched on or off with the *Guide* button on the Dashboard or in *Settings -> Help*, and the old yes/no offer ("New here?") appears
only when Advanced mode is the first thing opened. The Home screen covers the same steps.

It is a short checklist at the top of the Dashboard. You pick a path first, then each step ticks itself off when the real state of the PC says it is done:

| Step | What it checks | Ticks when |
|---|---|---|
| 1. Choose how to start | your choice | you pick *Quick fix* (no big download) or *Offline copy* (download the texture pack once); a button on the finished step switches to the other one |
| 2. Find your game folder | the game folder setting | the folder exists and looks like the game |
| 3. Check this PC | port 80, free disk space, game closed, [game setup](#game-setup-online-mode-and-the-cache-link) | nothing in the way |
| 4. Texture pack (offline path only) | the mirror | the pack is complete, or a download is running (the next steps do not wait for it), or you skipped it |
| 5. Start the session | proxy and hosts override | the session is running |
| 6. Play | requests reaching the proxy | the game has been delivered its texture pieces |
| 7. When you are done | the session | you stopped it; the report is in the Report tab |

*Find my game folder* looks in the folder around this tool, your Steam libraries and the usual places on every fixed drive (the drive root, `Games`, `Program Files`,
one or two folder levels down). Nothing is set until you pick one. You can always browse to any folder instead.

The guide never changes anything by itself: its buttons run the same actions as the normal ones (*Start session*, *Stop session*, the Doctor, the tabs). If something
goes wrong, the last problem is shown in the panel as well as in the Activity log. *Start over* runs the checklist again from the session step (it keeps your choice of path, which the button on step 1
changes), and *Hide* closes it.

The choice of path only shapes the checklist (the offline path adds step 4 and asks for more free disk space). It does not switch the helper between modes: whether an offline copy is used is decided by the
profile and the mirror folder, see [using an offline copy](#using-an-offline-copy-you-have-already-downloaded).

Around the checklist:

- **Spotlight.** The control the current step points at is highlighted in amber (*Start session*, *Stop session*, *Doctor*) or marked with an arrow (a tab). It is shown only
  while the guide is on, and never for *Stop session* while the game is still running.
- **Simple view** (older display option). The guide's header button (also *Settings -> Help*) hides the advanced tabs (Proxy, Mirror, Cache, Game, Hosts / DNS, Logs), the profile picker, the
  throughput graph and eight of the twelve counters, and names the remaining counters in plainer words. *Full view* shows everything again. The first-run offer turns it on
  together with the guide; it is a display setting only and is kept between runs. A guide button that points at a hidden tab (for example *Open the Doctor*) shows that tab. Entering Advanced mode from Home turns Simple view off.
- **Hover help.** Every status light and counter has a tooltip that says what it means. The *Words* button opens the same plain-language list as the end of
  [GETTING-STARTED.md](GETTING-STARTED.md).
- **Help cards.** For the usual failures the panel shows a short card (cause and a button) above the raw last problem: a refused hosts write, a closed permission prompt, a busy port,
  a hosts entry that disappeared while the helper runs, a game that runs for a minute and a half without any request reaching the helper, an unreachable CDN, a nearly full disk.
- **What happened.** When the session ends, the panel summarises the last session: pieces requested, from the internet or the mirror, failed, left out by the detail level. It
  states what was delivered, not how the picture looks.
- **Before/after test.** A four-step helper (pick a spot, play with the tool off, play with it on, compare screenshots) that uses the normal *Restore hosts* and *Start session*
  buttons and opens a folder for the screenshots (`tools/work/ab-test`). It remembers the step you were on.

## First run: tell it where things are (Game tab)

Nothing is assumed. Until the game folder is set, Home shows *Let's find your game* and, in Advanced mode, the Dashboard shows a red *SETUP NEEDED* banner and *Start session* refuses. These settings are in Advanced mode, *Game* page.

| Setting | Meaning | If left blank |
|---|---|---|
| Game folder | the folder that contains `cod26\` and `sp26\` (with the `*_cdn.xpak` chunk lists) | not configured |
| Engine cache folder | the game's stream cache (`cache_N_2.xpak`) | `<game folder>\xpak_cache` |
| Mirror folder | where the chunks are stored; can be another drive. Building a mirror needs a folder you can write to: inside Program Files that usually means a folder of your own instead | `<game folder>\mirror` |
| Player config file | `s.1.0.cod26.txt`, read only, used for the settings snapshot in reports | `%LOCALAPPDATA%\Activision\Call of Duty\players\s.1.0.cod26.txt` |
| Game process names | what counts as "game running" | `sp26-cod.exe, cod.exe` |
| Disk guard may terminate | processes the guard ends at the cache limit | `sp26-cod.exe` |

*Save locations* writes `tools\work\gui_settings.json`. The command-line tools read the same file. For one-off use there are environment variables: `CCS_GAME_ROOT`,
`CCS_CACHE_DIR`, `CCS_MIRROR_DIR`, `CCS_PLAYER_CFG`, `CCS_WORK`, `CCS_HOSTS_PATH`.

## A play session

1. Home: press **Turn on HD textures**. (Advanced mode, Dashboard: pick a profile and press **Start session**.) It applies the hosts override if needed, saves a snapshot of the engine cache, starts the proxy and the
   disk guard, and runs the doctor.
2. Start the game as you normally do. The status strip should show Proxy, Port and Mirror in green and Game in amber.
3. Quit the game. The window notices and writes a report for that launch (Report tab, saved under `tools\work\sessions\`).
4. **Stop session**, and decide what to do with the hosts override. *Restore hosts* or `tools\restore-hosts.bat` removes it at any time.

| Profile | What it does |
|---|---|
| Default | mirror first; the CDN only for chunks the mirror does not have |
| Offline test | mirror only; a miss is a 404 (shows gaps in the mirror, no network use) |
| Capture | no mirror; everything comes from the CDN |
| Standard HD (1440p class) / Ultra (4K class) | sets the detail level, see [TEXTURE-PACK.md](TEXTURE-PACK.md) |
| Slow link - offline mirror | play only from the mirror; nothing goes to the internet |
| your own | *Save as...* stores the current proxy / guard / watcher settings under a name |

## Using an offline copy you have already downloaded

The copy is served by the same helper as everything else, so nothing changes about a play session: start the program, press **Start session**, launch the game, keep the window open, and press **Stop session**
afterwards. The game asks for its textures at the content server's name and the hosts entry sends that to the helper; without a session the game cannot reach the copy.

1. **Where it is.** The Texture pack tab (Advanced mode) shows *Stored in: ...*. By default that is `mirror` inside the game folder (the pieces are under `mirror\objects`, with an index next to them). The Game tab, *Mirror folder*, changes
   it (Advanced mode); press *Save locations* after changing it. The Texture pack tab's table (*stored* column) shows how many pieces are there.
2. **Which profile.** *Default* serves from the copy first and goes to the internet only for what is missing. *Slow link - offline mirror* (the *Play offline (profile)* button on the Texture pack tab) serves only from the
   copy, so nothing is fetched from the internet and a missing piece is a 404. Restart the session after changing the profile.
3. **How to tell it is used.** The Dashboard's *Mirror* light shows the number of pieces it found (for example `103,631 ids`); *From mirror* counts the pieces served from it, and the *What happened* summary says how many
   came from your offline copy. If the *Mirror* light says "off" while the session runs, no copy was found in the mirror folder: check the folder, and that the profile is not *Capture* (which uses no mirror).
4. **How textures load.** *While I play* or *From my offline copy* (the first-run question, or Settings) only changes what the window shows; the button switches between them at any time.

## Game setup: online mode and the cache link

Streaming only helps if the game then uses what it received. In a game folder that has a `sp26\steam_settings` folder, two things can stop that:

1. The Steam settings are in offline mode (`sp26\steam_settings\configs.main.ini` has `offline=1`), so the game does not ask for additional content.
2. The engine fills `<game folder>\xpak_cache`, but the game looks for its cache in `<game folder>\sp26\xpak_cache`.

The *Doctor* shows a *Game setup* row, and the first-run step *One small change in your game folder* (or the guide's *Check this PC* step) offers it. After you confirm, it:

- sets `offline=0` and `disable_lan_only=1` under `[main::connectivity]` in `configs.main.ini`; the first time, the original is copied to `configs.main.ini.mw4ts-backup`, and every
  other line stays as it was;
- makes `sp26\xpak_cache` a directory junction (a folder link) to `xpak_cache`. If `sp26\xpak_cache` already exists as a real folder with files in it, it is renamed to
  `sp26\xpak_cache.before-link`, not deleted.

It does nothing while the game is running, does nothing the second time, and asks Windows for permission only when the game folder is somewhere that needs it (Program Files, for
example). It is not offered when the game folder has no `sp26\steam_settings` (a different layout). Start the game from its launcher afterwards.

It stops with a plain message, and changes nothing more, when `configs.main.ini` is read-only or not a plain text file, when something else is using `sp26\xpak_cache`, or when
`sp26\xpak_cache` is already a link to somewhere else (that is your own setup, so it is left alone; a link to a folder that no longer exists is replaced). If making the link
fails after a folder was moved aside, the folder is moved back.

```
ccs-cli.exe --ccs-run gamefix status       what is set now (from source: python tools\ccs.py --ccs-run gamefix status)
ccs-cli.exe --ccs-run gamefix apply        make both changes
ccs-cli.exe --ccs-run gamefix undo         put the two settings back to what they were and remove the link (a real folder is never removed)
```

Doing it by hand gives the same result: edit `configs.main.ini` as above, and in a Command Prompt in the game folder run `mklink /J sp26\xpak_cache xpak_cache`.
Online mode means the game no longer reports offline, so it may try to reach the network; if you would rather not, undo it: after a setup made by this tool the
Doctor's *Game setup* row has an *Undo the game setup* button (it asks first, and asks Windows for permission only if needed), or run `undo`. Undo changes only
`offline` and `disable_lan_only` back to their earlier values (or removes them again if they were not there; a settings file that did not exist is removed), so any other edit you made to
the file since stays. It removes `sp26\xpak_cache` only when it is a link to `xpak_cache`, never a real folder.

The setup is not offered when the *Engine cache folder* setting (Game tab) points at `sp26\xpak_cache` itself; change that setting first.

## Advanced mode

*Settings -> Advanced mode* (or the *Advanced mode* link at the bottom of Home) shows every page behind a side navigation: **Live** (Dashboard, Report, Logs), **Textures** (Texture pack, Mirror, Cache), **Game and PC** (Game, Doctor, Hosts / DNS) and
**Setup** (Proxy, Settings). Each page opens with its name and one line saying what it is for; a page taller than the window scrolls. *Home* (top left) goes back. The status strip at the top shows the eight lights (hover for what each means).

- **Dashboard**: live counters, throughput graph, activity log.
- **Proxy**: options (tier cap, budget, retries, port, mirror first, offline), restart, request-size histogram, recent requests.
- **Texture pack**: (asks you to accept the bulk-download notice the first time) scope, detail level, estimate, bandwidth cap, daily limit, download / pause, verify, reclaim space. See [TEXTURE-PACK.md](TEXTURE-PACK.md).
- **Mirror**: the expert view of the same downloader (run, pause, kill, verify, retry failed, re-init lists, progress with ETA, chunks by priority).
- **Cache**: shard table of the engine cache, duplicate ratio, backup and restore (the current cache is renamed aside, never deleted). Writes are refused while the
  game runs.
- **Game**: locations, checks, read-only table of the player config. **Doctor**: all checks with Fix buttons and a support bundle export. **Report**: analyse any
  proxy run or game launch. **Hosts / DNS**: the managed block, a diff preview, backups. **Logs**: merged tail with filters. **Settings**: guard, hosts policy, log
  rotation, desktop shortcut.

## Safety rules the tools follow

- Hosts: only the marked block and loopback lines for the CDN name are touched. A backup is written before every change, the file is read back to verify it, and
  the change is rolled back if the check fails.
- Cache and mirror: no cache writes while the game runs; backup and restore always keep a copy.
- Game setup: asks first, keeps a copy of the settings file, never deletes a folder (a real `sp26\xpak_cache` is renamed), and touches nothing while the game runs.
- Proxy: loopback only, and it forwards only the CDN path shape the game uses.
- Logs are rotated at session start when they pass the size you set (3 older copies are kept).

## Language

Settings (the slide-in panel on Home), *Language*: Automatic, or one of English, Russian, Chinese (Simplified), Spanish, French, German, Portuguese (Brazil), Turkish, Polish, Japanese, Korean, Italian.
Automatic uses the language you picked in the installer, else the Windows display language. A change restarts the window; a running session is not stopped. Logs and saved reports are always English.

## Troubleshooting

| Symptom | What to try |
|---|---|
| Home says *Let's find your game*, or the Dashboard shows a red *SETUP NEEDED* | Let the tool look, or in Advanced mode open the Game page, set the game folder and press *Save locations* |
| Doctor: *Mirror: unable to open database file* (older versions), or *Mirror folder: you can read it but not write to it* | The mirror is in a folder only an administrator can write to (for example inside Program Files). A stored mirror is read as it is, without writing next to it; building or extending one needs a folder you can write to: set another *Mirror folder* in the Game page of Advanced mode |
| The report says the game asked for textures and got them, but they still look low | Doctor, *Game setup* row, Fix: set up the game (see [Game setup](#game-setup-online-mode-and-the-cache-link)); close the game first and start it again afterwards |
| Game never streams, hosts light red or amber | Doctor, Fix: apply hosts (a UAC prompt only if the program is not running as administrator). The Hosts tab's *Test resolution* should show `127.0.0.1` and `::1` |
| *Permission denied* when writing the hosts file, even as admin | See [Hosts file: permission denied](#hosts-file-permission-denied) below |
| *'NoneType' object has no attribute 'splitlines'* | Fixed in 0.1.1-beta (a non-English Windows printed text the old code could not decode). Update, or open an issue with the support bundle |
| Mirror downloads are far below your line speed | Look at the `edge test` / `run: upstream=` lines in `tools\work\ccsmirror.log` and at the speed line on the Texture pack tab (it shows MiB/s **and** Mbps and the edge in use). Set *My line speed* so the tool re-checks the edge by itself, try 8 connections, and see [docs/TEXTURE-PACK.md](TEXTURE-PACK.md#download-speed) |
| First start with no mirror: the proxy would not start, or the Doctor failed on the mirror | Fixed: a missing or empty mirror is normal now (every chunk comes from the CDN until you build one). Update to the latest version |
| Windows says "Windows protected your PC" when you run the installer or the program | The files are not code-signed yet. *More info*, then *Run anyway*; compare the file with `SHA256SUMS.txt` on the release page (`certutil -hashfile <file> SHA256`) if you want to be sure |
| Update or uninstall shows a Windows permission prompt | Normal when a session is on: setup/uninstall first stops the helpers (they run with the program's administrator rights) and takes the hosts override out, which needs your permission. If you decline, it asks whether to go on anyway; *Restore hosts* in the Start menu fixes it later |
| Port 80 is taken | The Doctor names the owner; the fix asks before ending it |
| Proxy not answering | Doctor, Fix: restart proxy. The traceback is in `tools\work\run\proxy.out` |
| Report missing | Reports are written when the game process exits; if you stopped the session first, press *Generate report* in the Report tab |
| Want help | Doctor, *Export support bundle* (a zip with logs and settings, no game files) and attach it to an issue after checking its contents |

### Hosts file: permission denied

The hosts file is protected on purpose, so a write can be refused even when the window says it runs as admin. The tool writes the file in place, reads it back, and
a refused write leaves it untouched (the message says so and names the backup). Usual causes:

1. **Read-only attribute.** In an admin Command Prompt: `attrib -r "%SystemRoot%\System32\drivers\etc\hosts"`, then try again.
2. **Security software with hosts-file protection** (several antivirus suites have it, Windows Security can too). Pause that protection for a moment, or allow
   `MW4 Texture Streaming.exe` and `ccs-cli.exe` (`python.exe` when running from source), apply the override, and turn it back on.
3. **A changed ACL** on the file (rare). Check the Security tab of the file's properties.

The toolkit never switches off security software and never changes permissions on system files for you; that stays your decision. If you would rather not touch the
hosts file at all, add the two lines the *Hosts* tab shows yourself (`ccshosts.py diff apply` prints them) or use a DNS tool you already trust.

## Command line

| Tool | Purpose |
|---|---|
| `ccshosts.py status \| diff \| apply \| remove \| verify \| flush \| backups \| restore-backup` | hosts manager (`--elevate` asks for UAC unless already administrator) |
| `ccsproxy.py --origin <mirror> [--offline] [--max-raw-mib N]` | the proxy |
| `ccsmirror.py plan \| init \| run \| status \| verify \| prune \| retry-failed` | the mirror |
| `ccsreport.py --list \| --segment N [--from HH:MM:SS --to HH:MM:SS]` | session reports |
| `diskguard.py --limit-gib N --action kill\|warn` | cache size guard |
| `ccs.py --ccs-run gamefix status \| apply \| undo` (packaged: `ccs-cli.exe --ccs-run gamefix ...`) | game setup, see above |

Every tool has `--help`, and prints the same short notice at the bottom.

## Files the tools write (under `work`: see the table above; from source `tools/work/`)

| Path | What |
|---|---|
| `gui_settings.json` | settings, locations and your profiles (delete to reset) |
| `run/` | child-process tracking, live stats, tracebacks |
| `ccsproxy.log`, `diskguard.log`, `ccsmirror.log`, `ccsgui.log` | logs |
| `sessions/` | session reports and engine-cache snapshots |
| `game_runs.json` | start and end time of game launches the window has seen |
| `hosts-backups/`, `bundles/` | hosts backups, support bundles |
