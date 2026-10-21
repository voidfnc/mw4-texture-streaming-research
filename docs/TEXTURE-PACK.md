# Texture pack: what to mirror and how big

The mirror can hold just the single-player chunks or everything the chunk lists mention, and you can leave out the largest chunks. The offline copy page (Settings, *Offline copy*), the *Texture pack*
page in Advanced mode and the command-line `ccsmirror.py` do the same thing (the page has the most options); this page explains the two choices and what they cost.

> **Before you download:** the chunks are the publisher's content. The tool asks you to accept a notice before the first bulk run (GUI dialog, or `--accept-notice`
> on the command line, once per version): use it only with your own copy of the game, keep the files on your PC, do not share them, and check that this is allowed
> where you live and under the game's terms. See [DISCLAIMER.md](../DISCLAIMER.md).

## Scope: which chunk lists

| Scope | Lists used | Chunks | Size on disk |
|---|---|---:|---:|
| `sp` (default) | campaign + boot | 103,631 | 81.6 GiB |
| `all` | every list the install has (campaign, common, multiplayer, DMZ, HQ) | 153,286 | 110.7 GiB |
| `custom` | the packages you tick | - | - |

The numbers come from the chunk lists of one install and from asking the CDN with `HEAD` requests (8 random chunks from each extra package, all answered
`200`). The lists are read from your own game folder and are never part of this repository. If a list is missing the tool says so and skips that package.

## Detail level: how big a chunk may be

Chunk size is the decoded size of the texture piece. For block-compressed textures 4 MiB is about 2048x2048 and 16 MiB about 4096x4096.

| Level | Cut-off | Campaign only | Everything |
|---|---|---:|---:|
| Standard ("1440p class") | up to 4 MiB | 53.6 GiB | 72.7 GiB |
| High | up to 8 MiB | 60.3 GiB | 81.1 GiB |
| Ultra ("4K class") | no cut-off | 81.6 GiB | 110.7 GiB |

Please read "1440p class" as a rough label for the chunk size, not as a promise about what you will see. The level is a cut-off for texture data; the resolution
the game renders at, and which mips it actually asks for, depend on the engine's own streaming budget and on what is on screen. In my sessions chunks above 4 MiB
were only about 3 % of the requests, but roughly a quarter of the downloaded bytes.

One level drives both sides: the mirror does not download chunks above it, and the proxy answers 404 for them, so a 1440p-class setup never serves a big chunk from
a bigger mirror by accident. You can switch levels later. Going up fetches only what is missing; going down offers to delete the mirror copies above the cut-off
(they can always be downloaded again).

## Download time

Ideal numbers, no overhead (whole pack at Ultra is 110.7 GiB):

| Line speed | Campaign standard (53.6 GiB) | Campaign ultra (81.6 GiB) | Whole pack ultra (110.7 GiB) |
|---|---:|---:|---:|
| 10 Mbps | 12.8 h | 19.5 h | 26.4 h |
| 25 Mbps | 5.1 h | 7.8 h | 10.6 h |
| 50 Mbps | 2.6 h | 3.9 h | 5.3 h |
| 100 Mbps | 1.3 h | 1.9 h | 2.6 h |

## Download speed

What decides how fast the mirror is, in order of importance:

1. **Which edge server you talk to.** The CDN has many servers and the nearest one can be 10 times faster than a far one. Before a run the tool downloads two small
   real chunks from each candidate address and keeps the fastest one that answers correctly; the log shows each test (`edge test ...`) and the pick (`run: upstream=...`).
   The nearest address comes from your system's DNS while the hosts override is **off**, and is remembered for a week in `tools/work/edge_cache.json`. If only
   the built-in fallback address is left, the log and the window say so, because it may be far from you. Turning the override off once and starting a run fixes that.
2. **Connections.** Each connection fetches one chunk at a time, so a long round trip limits it. The default is 4 (the polite setting). On a long-distance link 8
   helps (*Texture pack* tab, *Connections*). There is no hidden bandwidth cap; the only limit you can set yourself is *Download cap*, and `1` there means 1 Mbps.
3. **Units.** The window shows MiB/s and Mbps. A 100 Mbps line is at most about 11.9 MiB/s, and 1 MiB/s is only about 8 Mbps.

If you tell the tool your line speed (*My line speed*), it also watches itself: when the rate stays under 20 % of that for a minute it measures the edges again and
switches if another one is clearly better.

### Connections and requests per second: what to set

Short version: leave *Max req/s* alone and use 8 connections if the default feels slow. More than that rarely helps and is harder on the CDN.

| Your line | Connections | Max req/s | Why |
|---|---|---|---|
| up to about 300 Mbit/s | 4 (default), or 8 on a long route | 50 (default) | The edge you are connected to matters more than either number |
| gigabit | 8 to 12 | 50 to 100 | In short tests on a gigabit line I saw about 63 MiB/s with 4 connections and about 94 MiB/s with 12 |
| anything | do not go above 12 | do not go above 100 | no further gain, and the CDN may start answering 429 |

Why `Max req/s` rarely matters: chunks average about 0.6 MiB (Standard) to 0.8 MiB (Ultra), so the default 50 requests a second is already roughly 230 to 340 Mbit/s.
It only becomes the limit on a very fast line.

Which setting wins: the *Texture pack* tab's *Connections* applies when it is not 0; if it is 0 the *Mirror* tab's *Workers* is used (4 while a *Download cap* is set).
*Max req/s* always comes from the *Mirror* tab. Changes apply when a run starts, so Pause, wait for it to stop, and press Download again.

If the log says `CDN asked to slow down (429/503)`, you have set it too high: every connection then waits, which is slower than a lower setting. Go back down a step.
These figures are rules of thumb from my own tests, not guarantees for your line.

## For slow or metered connections

- `--limit-mbps N` caps the total download rate (shared by all connections), so you can keep using the line.
- `--daily-gib N` pauses until local midnight once the day's allowance is used. The usage survives restarts.
- A dropped connection is waited out: the chunks stay pending instead of being marked failed. `--link-wait-s N` makes the run give up after N seconds if you prefer.
- Everything is resumable. Pause in the GUI (or create the `STOP` file) and run again later.
- Once the mirror is complete you can play with the *Slow link - offline mirror* profile: the proxy serves only from disk, and a missing chunk is a 404, so
  nothing goes to the internet.

The mirror folder can sit on another drive. Copying it to another disk of yours is fine; `verify --all` re-checks every file afterwards. Please don't share it.

## Command line

```
python tools\ccsmirror.py plan   --scope all --level standard --line-mbps 25      # estimate, no network, no writes
python tools\ccsmirror.py run    --scope all --level standard --limit-mbps 8 --daily-gib 30 --workers 4
python tools\ccsmirror.py status
python tools\ccsmirror.py verify --all --fix        # md5/size check of every stored chunk; bad ones go back to pending
python tools\ccsmirror.py prune  --above-tier 4     # dry run; add --yes to delete stored chunks above 4 MiB
```

The mirror is polite by default: 4 connections, 50 requests per second, a User-Agent that names this tool, and back-off when the server answers 429 or 503.
Please leave those alone unless you have a good reason.
