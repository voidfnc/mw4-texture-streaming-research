# Changelog

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
