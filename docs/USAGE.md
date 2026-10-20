# Using the control window

Start it with `tools\ccs-gui.bat` (no console window) or `python tools\ccsgui.py`. It runs **unelevated**; only changes to the hosts file ask for administrator
rights (UAC). Python 3.10+ with tkinter is the only requirement. The first time it opens it shows a short notice about what the tools are and are not. Before the first bulk download (Texture pack or Mirror tab) it shows a second notice
that you have to accept once per version; on the command line the same thing is `ccsmirror.py run ... --accept-notice`.

## First run: tell it where things are (Game tab)

Nothing is assumed. Until the game folder is set, the Dashboard shows a red *SETUP NEEDED* banner and *Start session* refuses.

| Setting | Meaning | If left blank |
|---|---|---|
| Game folder | the folder that contains `cod26\` and `sp26\` (with the `*_cdn.xpak` chunk lists) | not configured |
| Engine cache folder | the game's stream cache (`cache_N_2.xpak`) | `<game folder>\xpak_cache` |
| Mirror folder | where the chunks are stored; can be another drive | `<game folder>\mirror` |
| Player config file | `s.1.0.cod26.txt`, read only, used for the settings snapshot in reports | `%LOCALAPPDATA%\Activision\Call of Duty\players\s.1.0.cod26.txt` |
| Game process names | what counts as "game running" | `sp26-cod.exe, cod.exe` |
| Disk guard may terminate | processes the guard ends at the cache limit | `sp26-cod.exe` |

*Save locations* writes `tools\work\gui_settings.json`. The command-line tools read the same file. For one-off use there are environment variables: `CCS_GAME_ROOT`,
`CCS_CACHE_DIR`, `CCS_MIRROR_DIR`, `CCS_PLAYER_CFG`, `CCS_WORK`, `CCS_HOSTS_PATH`.

## A play session

1. Dashboard: pick a profile and press **Start session**. It applies the hosts override if needed, saves a snapshot of the engine cache, starts the proxy and the
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

## Tabs

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
- Proxy: loopback only, and it forwards only the CDN path shape the game uses.
- Logs are rotated at session start when they pass the size you set (3 older copies are kept).

## Troubleshooting

| Symptom | What to try |
|---|---|
| Red *SETUP NEEDED* | Game tab, set the game folder, *Save locations* |
| Game never streams, hosts light red or amber | Doctor, Fix: apply hosts (UAC). The Hosts tab's *Test resolution* should show `127.0.0.1` and `::1` |
| *Permission denied* when writing the hosts file, even as admin | See [Hosts file: permission denied](#hosts-file-permission-denied) below |
| *'NoneType' object has no attribute 'splitlines'* | Fixed in 0.1.1-beta (a non-English Windows printed text the old code could not decode). Update, or open an issue with the support bundle |
| Mirror downloads are far below your line speed | Look at the `edge test` / `run: upstream=` lines in `tools\work\ccsmirror.log` and at the speed line on the Texture pack tab (it shows MiB/s **and** Mbps and the edge in use). Set *My line speed* so the tool re-checks the edge by itself, try 8 connections, and see [docs/TEXTURE-PACK.md](TEXTURE-PACK.md#download-speed) |
| Port 80 is taken | The Doctor names the owner; the fix asks before ending it |
| Proxy not answering | Doctor, Fix: restart proxy. The traceback is in `tools\work\run\proxy.out` |
| Report missing | Reports are written when the game process exits; if you stopped the session first, press *Generate report* in the Report tab |
| Want help | Doctor, *Export support bundle* (a zip with logs and settings, no game files) and attach it to an issue after checking its contents |

### Hosts file: permission denied

The hosts file is protected on purpose, so a write can be refused even when the window says it runs as admin. The tool writes the file in place, reads it back, and
a refused write leaves it untouched (the message says so and names the backup). Usual causes:

1. **Read-only attribute.** In an admin Command Prompt: `attrib -r "%SystemRoot%\System32\drivers\etc\hosts"`, then try again.
2. **Security software with hosts-file protection** (several antivirus suites have it, Windows Security can too). Pause that protection for a moment, or allow
   `python.exe`, apply the override, and turn it back on.
3. **A changed ACL** on the file (rare). Check the Security tab of the file's properties.

The toolkit never switches off security software and never changes permissions on system files for you; that stays your decision. If you would rather not touch the
hosts file at all, add the two lines the *Hosts* tab shows yourself (`ccshosts.py diff apply` prints them) or use a DNS tool you already trust.

## Command line

| Tool | Purpose |
|---|---|
| `ccshosts.py status \| diff \| apply \| remove \| verify \| flush \| backups \| restore-backup` | hosts manager (`--elevate` asks for UAC) |
| `ccsproxy.py --origin <mirror> [--offline] [--max-raw-mib N]` | the proxy |
| `ccsmirror.py plan \| init \| run \| status \| verify \| prune \| retry-failed` | the mirror |
| `ccsreport.py --list \| --segment N [--from HH:MM:SS --to HH:MM:SS]` | session reports |
| `diskguard.py --limit-gib N --action kill\|warn` | cache size guard |

Every tool has `--help`, and prints the same short notice at the bottom.

## Files the tools write (under `tools/work/`)

| Path | What |
|---|---|
| `gui_settings.json` | settings, locations and your profiles (delete to reset) |
| `run/` | child-process tracking, live stats, tracebacks |
| `ccsproxy.log`, `diskguard.log`, `ccsmirror.log`, `ccsgui.log` | logs |
| `sessions/` | session reports and engine-cache snapshots |
| `game_runs.json` | start and end time of game launches the window has seen |
| `hosts-backups/`, `bundles/` | hosts backups, support bundles |
