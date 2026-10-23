# Contributing

## Translations

Each language is one file, `tools/ccslib/lang/<code>.json`: `{"English text": "translation"}`. Text built from parts uses `{0}`, `{1}` in order of appearance (the translation may reorder them).
Keep line breaks, `{n}` placeholders and technical tokens (GiB, CDN, file names) as they are. Run `python tools\i18n_extract.py --check` to see missing strings and placeholder mistakes, and
`python tools\i18n_extract.py --missing de` to list what a language still lacks. After changing window text, run `python tools\i18n_extract.py` to refresh `lang/_source.json` and add the new strings to every
language (a missing one just shows in English). `CCS_LANG=<code>` starts the program in that language. A new language also needs its code in `ccslib/i18n.py` and an installer entry (`packaging/installer.iss`).

Thanks for looking. A few ground rules, mostly to keep the project on the right side of the line it has drawn for itself:

- **Never attach game files**, chunk lists (`*_cdn.xpak`), cache files, mirror contents, decoded textures or screenshots that show them (an ordinary frame of the running game, like the two in the README, is fine when nothing personal is visible: no paths, names or addresses). If a capture is needed to
  explain a bug, describe it or trim it to the lines that matter.
- The tools stay on the data and network path. Pull requests that patch or hook the game, read its memory, touch drivers or anti-cheat, or get around licensing or
  login will be closed.
- Be considerate to the CDN: no change should raise the default request rate or connection count, or remove the User-Agent or the back-off on 429/503.
- Standard library only. If you really need a dependency, open an issue first.
- Run `python -m unittest discover -s tools/tests` before sending a change. The tests use fake chunk lists and a fake CDN on localhost, never the real game or
  server.
- The program itself needs only the standard library. Making a release (build PC with Python 3.12 and Inno Setup 6, `winget install JRSoftware.InnoSetup`): bump the version in
  `tools/ccslib/version.py` (the only place it lives), add a `## <version>` section to `CHANGELOG.md`, update the README header, regenerate the screenshots
  (`python tools\make_screenshots.py` and `python packaging\shoot_installer.py <Setup.exe>`), merge to `main`, then `packaging\build.bat` (about three minutes: builds, smoke-tests,
  installs / upgrades / uninstalls the installer) and `python packaging\release.py` (a **draft** release; read it on GitHub and press Publish). Tests check that the README, changelog and
  screenshots name the current version, and `release.py` refuses stale files or source that is not on `origin/main`.
- Python 3.10+, Windows paths and behaviour first. Linux/Wine reports are interesting but not supported yet.

Useful reports: another PC where the IPv6-only lookup shows up (or does not), which Windows version and ISP type, and what *Check my PC* says (Settings; it is the Doctor page in Advanced mode).
