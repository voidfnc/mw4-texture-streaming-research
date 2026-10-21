# Architecture

How the pieces fit together and what each of them is allowed to touch.

```
 game  --(name lookup: CDN host)-->  hosts file (marked override -> 127.0.0.1 / ::1)
 game  --(HTTP GET /pc/iw9_3/23/..)--> ccsproxy.py (loopback, port 80)
                                          |-- detail-level cap  --> 404 for chunks above the cap
                                          |-- local mirror      --> chunk file from disk (+ stored ETag header)
                                          '-- upstream CDN      --> only for chunks the mirror lacks (unless offline mode)
 ccsmirror.py --(HTTP GET, polite client)--> CDN edge  ==> mirror/objects/..  (+ index.sqlite)
 ccsgui.py  = control window over all of the above, plus doctor, cache tools and reports
```

## Design constraints

These are on purpose and are the reason the project can be described as research on the network and data path:

- The game, its launcher, its drivers and its anti-cheat are never patched, hooked or inspected at runtime. No process memory is read.
- Only public, unauthenticated URLs are requested, and only ones of the exact shape the game itself uses. There is no login handling and no token handling.
- The proxy listens on loopback only and forwards only that URL shape.
- The hosts editor touches only a marked block (and loopback lines for the one CDN name), backs the file up first, verifies by reading it back and rolls back on
  a mismatch. It never replaces a mapping to a non-loopback address unless told to with `--force`.
- Nothing is written outside the folders you configure. The tools never ship, host or upload game data.

## Components

| File | Role |
|---|---|
| `tools/ccshosts.py`, `ccslib/hosts.py` | hosts-file manager (status, diff, apply, remove, verify, flush, backups, restore) |
| `tools/ccsproxy.py` | forwarding proxy; stats at `GET /__ccs/stats` (loopback only); `--origin` mirror, `--offline`, `--max-raw-mib` cap |
| `tools/ccsmirror.py` | mirror: `init`, `plan`, `run`, `status`, `verify`, `prune`, `retry-failed`; SQLite index; object files named like the CDN path |
| `tools/diskguard.py` | watches the size of the engine cache and warns or ends the game process at a limit you set |
| `tools/ccsreport.py`, `ccslib/report.py` | reads the proxy log and builds a per-run or per-launch report (tier demand, throughput, cache re-requests) |
| `tools/ccslib/pack.py` | the "texture pack" model: packages, scope, detail level, size estimates |
| `tools/ccslib/upstream.py` | how we talk to the CDN: edge lookup (system resolver, remembered answer, direct DNS query) and a timed pick between candidates, User-Agent, Retry-After parsing, back-off |
| `tools/ccslib/ui.py` | the look of the window, standard library only (no image library): colour and size tokens scaled for the display, anti-aliased rounded shapes and glows computed as PNGs, and the widgets built from them (buttons, cards, the status ring, the step strip, the side navigation, one shared animation timer that reduce-motion switches off) |
| `tools/ccslib/home.py` | the Home screen as a function with no GUI code: `build(state, facts)` returns what to show (mode, ring, headline, buttons, cards, numbers), plus the offline copy page, the Settings rows and the hover texts. Tested as tables (`tests/test_home.py`) |
| `tools/ccslib/homeui.py` | draws a Home view with the widgets of `ui.py`: the stage, the first-start steps, the Settings panel that slides in and the offline copy page |
| `tools/ccsgui.py` | tkinter control window: Home (drawn by `homeui.py`) and Advanced mode (every tab behind a side navigation). It runs as administrator by default (the packaged program's manifest asks for it, a source run relaunches itself elevated once, see `wants_elevation`); children are detached processes tracked by pid files with creation-time checks and inherit its rights, so `uninstall-prep stop-helpers` elevates when it must |
| `tools/ccs.py`, `ccslib/launch.py` | the packaged app's one entry point and the single function (`argv_for`) that starts every helper: `python script.py` from source, `ccs-cli.exe --ccs-run <tool>` when packaged |
| `ccslib/gamefix.py` | the game setup (online mode in the game's Steam settings, `sp26\xpak_cache` junction to `xpak_cache`): pure text edit, status / apply / undo, tested on temp folders; run as `--ccs-run gamefix` |
| `ccslib/uninstall.py`, `ccslib/selfcheck.py` | the installer's hooks (stop helpers, remove our hosts block, report state by exit code) and an end-to-end check of the helper start-up, both tested without touching the real hosts file |
| `packaging/` | `build.bat` / `build.py` (PyInstaller program folder, portable zip, Inno Setup installer, smoke tests, checksums), `installer.iss`, `test_installer.py` (install, upgrade, uninstall), `release.py` (draft GitHub release), pinned build requirements |
| `tools/ccslib/guide.py` | the guided setup logic, with no GUI code in it: finding the game folder, the milestones and checklist as a function of facts about the PC, the spotlight target, help cards, the "what happened" text, the before/after test steps and the glossary. Home and the older checklist in Advanced mode both draw from it, so it is tested as tables (`tests/test_guide.py`) |
| `tools/netwatch.py`, `tools/cachewatch.py` | read-only observers (DNS/TCP log of the game, install-tree snapshot) |
| `tools/cdnxpak.py`, `tools/xpakrec.py` | parsers for the shipped chunk lists and for the engine's cache index |

Configuration lives in `tools/work/gui_settings.json`; every command-line tool reads it too, so the GUI and the CLI always agree on where things are.
Environment variables `CCS_GAME_ROOT`, `CCS_CACHE_DIR`, `CCS_MIRROR_DIR`, `CCS_PLAYER_CFG`, `CCS_WORK` and `CCS_HOSTS_PATH` override it for one-off use and tests.

## Formats worth knowing

**Chunk URL**: `/pc/iw9_3/23/{id & 0xff:02x}/{id:016x}_{size:08x}_{flag}`. `size` is the exact object length in bytes, so a full download can be checked against the
URL itself; the response ETag is the MD5 of the body (older objects use `md5:timestamp`).

**Chunk lists**: the game ships `*_cdn.xpak` files with 20-byte records starting at offset `0x8000`: id (u64), `size << 1 | flag` (u32), zero (u32), raw size (u32).
`ccslib/pack.py` reads these from *your* install to know what exists; they are never copied into this repository.

**Mirror**: `mirror/objects/{id & 0xff:02x}/{id:016x}_{size:08x}_{flag}` holds the verbatim response bodies, `mirror/index.sqlite` has one row per chunk (status,
ETag, package bits, priority).

**Engine cache** (observed, not documented by the vendor): per shard an index file with a double-buffered table of 20-byte records `[id u64][size << 1 | flag u32]
[offset >> 7 u32][raw size u32]` sorted by id, and a data file with the objects stored verbatim at 4 KiB-aligned offsets. See [FINDINGS.md](FINDINGS.md) for what
is still unknown.
