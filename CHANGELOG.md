# Changelog

## Unreleased

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
- 23 new tests (161 in total).

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
Fixes from a user report (non-English Windows, hosts file protected).

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
