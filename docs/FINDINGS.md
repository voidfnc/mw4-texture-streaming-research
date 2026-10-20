# Findings

Notes from tracking down why on-demand texture streaming never worked on my PC, and what the engine does once it does. Everything here comes from one Windows
machine and the single-player campaign, so treat the numbers as observations, not as a benchmark. Things I did not manage to verify are marked as such.

## 1. The symptom

With texture quality maxed out and on-demand streaming set to its best option, the campaign still looked soft: floors, props and character clothing showed the
low-resolution mips that ship with the game. The streaming cache folder (`xpak_cache`) contained empty data files and did not grow while I played.

## 2. Finding the cause

I did this in three passes, each ruling something out.

**Is the game even trying?** Yes. The Windows DNS-Client operational log shows bursts of lookups for `cod-assets.cdn.callofduty.com` whenever a new area loads.

**Does anything leave the machine?** No. A `pktmon` capture on the network adapters showed the lookups but zero SYN packets to ports 80 or 443 from the game.
Nothing was being blocked, because nothing was being sent.

**Why not?** The lookups were IPv6-only, with the "V4-mapped" flag set, so the resolver answered with an IPv4 address dressed up as `::ffff:a.b.c.d`. On Windows
an IPv6 socket has `IPV6_V6ONLY` turned on by default, and with that flag on, `connect()` to a mapped address fails immediately with WinError 10049. I reproduced
the failure with a small Python test, and showed that turning the flag off makes the same connect work. That matches what the game does: it asks, gets an
answer it cannot use, and silently gives up.

## 3. The workaround

Two small pieces, both on the data path and neither touching the game:

1. A hosts-file entry that maps the CDN name to `::1` and `127.0.0.1`.
2. A local proxy on port 80 that accepts the game's requests and forwards them to the real CDN over IPv4.

With those in place the unmodified game connected within a few minutes and the cache started filling. The first half-hour of play produced 3,197 requests (about
1.5 GB) and the proxy log showed the engine asking for plain `GET`s with occasional range requests.

## 4. What the engine asks for

The CDN objects are addressed as `/pc/iw9_3/23/{id & 0xff, 2 hex}/{id, 16 hex}_{size, 8 hex}_{flag}`. The size in the URL is the exact byte length of the object,
which makes it easy to check a download. Each object carries the compressed texture data plus a header; the chunk lists that ship with the game give, per id, the
compressed size and the decoded ("raw") size. For block-compressed textures the raw size tells you roughly how big the image piece is: 1 MiB is about 1024x1024, 4
MiB is 2048x2048, 16 MiB is 4096x4096.

In the single-player lists that is about 103,600 chunks and 82 GiB, of which roughly 54 GiB are chunks of 4 MiB or smaller. The chunk lists of all packages
together come to about 153,000 unique chunks and 111 GiB.

How much of that the game actually requests depends on the content, not just on the settings. In one clean 23-minute session at 2560x1440
the game made 16,453 requests for 11.1 GiB. Only 571 distinct chunks were above 4 MiB (a bit over 3 % of the requests), but by my estimate they were roughly a
quarter of the bytes. Three of
them were above 16 MiB (two of 55 MiB, one of 23 MiB). In another, shorter session it asked for 151 distinct chunks of that size. The demand arrives in bursts when the player
enters a new area or a cutscene starts.

The engine paces its own downloads. Even when the proxy served from a local disk and answered a 47 MiB burst in a second, the sustained rate over 10-second
windows stayed around 6 to 10 MiB/s. The proxy was not the bottleneck.

## 5. The engine's cache

The cache is a set of 32 shard slots, each a pair of files: an index (`cache_N_2.xpak`, with 20-byte records of id, size, offset and raw size, sorted by id) and a
data file (`cache_N_2.xpakdata`) holding the CDN objects verbatim at 4 KiB-aligned offsets. A shard holds roughly 2 GiB of data. A 32-byte value near the start of
each index changes with every commit and I could not work out how it is derived.

The odd thing: the engine requests many chunks it already has. In several sessions between 40 % and 70 % of the requested ids were already present in the cache
index from earlier runs, and some ids were fetched up to eight times. I have not found out whether the engine ignores its cache, evicts aggressively, or fails to
validate what is on disk. If you know, I'd like to hear it.

## 6. Hiding the big chunks (detail level)

The proxy can answer HTTP 404 for chunks above a size limit. The engine then keeps the smaller mip it already has. I use this as a "detail level": standard (up to
4 MiB), high (up to 8 MiB) or ultra (no limit). It is a cut-off for texture data, not a render resolution; what the game draws still depends on its own streaming
budget. I only have a few early observations of the engine's reaction to refusals (no stalls that I noticed), so this part is the least tested. The report tool
counts refused requests and how often the same id is asked for again, which is how a retry storm would show up.

## 7. What I could not verify

- **That textures look better.** Cutscenes looked clearly sharper to me once streaming worked, and character close-ups showed fine detail (skin pores, beard
  hair) that I had not seen before. I did not do a controlled comparison with identical frames, and I could not map chunk ids back to image names, so I cannot say
  which surfaces got which chunks.
- **Hand-built caches.** I wrote a throw-away tool that builds cache shards from a mirror in the engine's format. I never got far enough to show that the engine
  accepts such a cache (the commit value mentioned above is the likely obstacle), and the tool is not part of this release.
- **A second machine.** The IPv6-only behaviour is reproduced on one PC and one ISP. Reports from other setups would help a lot.
- **Online modes.** I only used the single-player campaign and did not look at what the game's online connections carry (see section 9: with the Steam settings in online mode
  the game opens several outbound HTTPS connections).
- **An occasional crash** in the campaign (once, in the user-interface layer of one mission) did not recur in later sessions and I have no evidence it is related.

## 8. Reproducing

1. Check whether you are affected: run the DNS-Client capture and `pktmon` as in [ISSUE-ipv6-cdn-lookup.md](ISSUE-ipv6-cdn-lookup.md).
2. Install the toolkit as described in the README. If the game folder has a `sp26\steam_settings` folder, let the Doctor's *Game setup* row set it up
   (section 9), then start a session from the control window and play. The *Report* tab writes a summary after every game launch.
3. Compare the report's tier table and cache section with your own numbers.

## 9. A second layer: the game folder settings

On my PC, even with the proxy working, I could see requests being answered while the result in the game was
not what I expected. Two things in the game folder looked wrong:

- **The Steam settings were in offline mode.** `sp26\steam_settings\configs.main.ini` had `offline=1`.
- **Two cache locations.** The cache lived in `xpak_cache` in the game's root folder, and there was no `sp26\xpak_cache`, the folder next to the game's executable.

I changed both together: `offline=0` and `disable_lan_only=1` in that file, and `sp26\xpak_cache` as a directory junction to `xpak_cache`. The toolkit's *Game setup* does exactly this
(with a backup of the settings file and an undo). I did not test the two changes separately, so I cannot say which one matters, or whether both do.

What I saw in one session afterwards (2560x1440, the single-player campaign, a complete local mirror of all 103,631 chunks, about 44 active minutes):

- With the settings online, the game opened four outbound HTTPS connections, a listener on a local port and a UDP socket. I did not look at what they carry.
- The game made 4,543 requests (4,505 distinct chunks), all answered from the mirror (4.32 GiB), with no errors and no chunk missing from the mirror. 378 distinct chunks were above 4 MiB:
  187 in the 8 MiB class and 191 in the 16 MiB class, none above 16 MiB. The earlier sessions in section 4 had different content and a different length, so the request counts are
  not comparable.
- Only a few requests a minute (one burst of 81) in the first twelve minutes (menus and shader preload), then 470 to 600 requests a minute for about five minutes when I loaded into gameplay,
  then mostly 30 to 200 a minute. A first launch of about two minutes in the same sitting sent no requests at all, so reaching gameplay may be needed before streaming starts; I have not tested that.
- The engine cache grew by 4,500 distinct ids, and 4,489 of the 4,505 requested ids were in it afterwards. By eye the textures looked as expected during play; as in section 7, this is not
  a controlled comparison.

What I have not checked: whether a second session asks for fewer chunks now that the cache holds them (the report's "already in cache" figure will show it), whether the same two changes help
on a machine whose game folder has no `sp26\steam_settings`, and whether the online mode has any other effect on the game.
