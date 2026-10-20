# Disclaimer

**Research / proof of concept.** This repository contains source code and written methods only.

- It contains **no Activision files**: no game assets, game binaries, CDN content, keys, chunk catalogues or extracted data. None of that is, or will be,
  distributed here. Please don't attach any of it to issues or pull requests.
- The tools read files from *your own installation* and request only publicly reachable, unauthenticated URLs that the game itself requests.
- They do not patch, hook or read the memory of the game, its launcher, drivers or anti-cheat, and they do not bypass licensing, DRM or authentication.
- They are meant for offline, single-player use on your own computer. Don't use them with online services.

**Use at your own risk.** Downloading game content in bulk, changing your hosts file and sending the game's traffic through a local proxy may go against the
game's terms of service or the law where you live, and could lead to action against your account. Checking that and complying with it is up to you. The game's license terms restrict reverse engineering, modifying game data and using unauthorized third-party software, and the
publisher's security policies describe account suspensions for violations; research and interoperability exceptions exist in some countries but differ from place to place. Nothing in this repository is legal advice.

**Bulk downloads.** The mirror feature copies game content (texture chunks) from the publisher's CDN to your disk, up to the whole pack. That content remains the
publisher's property. The tool needs the chunk lists from *your own* installation (none are shipped here), asks you to accept a notice before the first run, and is
deliberately gentle on the servers (few connections, rate limit, User-Agent, back-off). You are responsible for having the right to use that content, for keeping it on
your own machine and for not sharing, re-hosting or selling it. If the publisher or a court asks for a feature to be removed or changed, it will be.

**Takedowns and changes.** This repository can change or disappear at any time, for example after a request from a rights holder. Mirrors and forks are not
endorsed.

**No affiliation.** This project is not affiliated with, endorsed by or sponsored by Activision Publishing, Inc. or its affiliates. "Call of Duty", "Modern
Warfare" and related names are trademarks of their owners and are used here for identification only.

**No warranty.** The software is provided "as is", without warranty of any kind (see [LICENSE](LICENSE)). The license covers the code and notes in this
repository only and grants no rights to any game, asset, binary, network content or trademark of Activision Publishing, Inc. or its affiliates.
