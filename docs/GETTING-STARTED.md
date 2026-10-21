# Getting started

This page is for someone who just wants the game to stream its textures and finds the control window busy. It uses plain words and no command line. Every
term that is not obvious is explained at the bottom.

## What this does, in three sentences

On some PCs the game's texture streamer never connects to the server it downloads textures from, so you play on the low-resolution textures that shipped with the
game. This tool puts a small helper on your PC and tells Windows to send those requests to it; the helper gets the texture pieces and hands them to the game.
What the tool can show you is which pieces the game asked for and that they were delivered. How the picture looks is decided by the game, so on this page there is
also a short test to compare it on your own PC.

## Install

Download from the [Releases page](https://github.com/voidfnc/mw4-texture-streaming-research/releases) and pick one:

- **The installer** (`...-Setup.exe`, recommended): double-click, accept the notice, press Next and Install. It installs for all users by default (in Program Files, with one Windows permission prompt);
  "for me only" is an option on its first screen and needs no administrator rights. The program asks for administrator permission each time it starts (the *UAC prompt*): answer Yes. It adds a Start menu entry (and a desktop shortcut if you leave that ticked) and a normal uninstall entry in
  *Apps & features*. It does not touch your hosts file or your game folder.
- **The portable zip** (`...-portable.zip`): unzip it anywhere and double-click `MW4 Texture Streaming.exe`. Nothing is installed, and your settings stay in a `data` folder next to it.
- **From source**, if you prefer to run the code yourself: see the README.

Windows may show "Windows protected your PC" because the files are not code-signed yet. Choose *More info*, then *Run anyway*. To uninstall, use *Apps & features* (or the Uninstall entry
in the Start menu); if the hosts override is on at that moment, the uninstaller takes it out first and asks before it deletes your settings.

## Before you start

- Windows 10 or 11, 64-bit, and the game installed. The installer and the zip need no Python; running from source needs Python 3.10 or newer.
- Close the game. The session has to be started first, then the game.
- A few GiB of free disk space for the quick fix. The offline copy needs a lot more (about 54 to 82 GB).

Start the window from the Start menu or the desktop shortcut (zip: double-click `MW4 Texture Streaming.exe`; from source: `python tools\ccsgui.py`). On the very first start it asks whether you want the guided setup. Say yes: it also
switches on *Simple view*, which tucks the advanced tabs away.

## The guided setup, step by step

A checklist at the top of the Dashboard. Each step ticks itself when the real state of your PC says it is done, and the control to press next is highlighted in amber.

1. **Choose how to start.** *Quick fix* needs no big download: the helper fetches texture pieces while you play. *Offline copy* downloads the whole texture pack once and
   plays from disk, which suits a slow or metered connection. If you are unsure, take the quick fix; you can build an offline copy later, and a button on this step switches between the two at any time.
   Either way the program has to run a session whenever you play: the offline copy replaces the download, not the helper.
2. **Find your game folder.** Press *Find my game folder*. The tool looks in the folder around itself, in your game libraries and in the usual places on every drive, and
   shows what looks like the game. It never picks one for you: choose the right one, or press *Browse...* and point at any folder. If the folder does not look like the
   game, you can still say *Use it anyway*.
3. **Check this PC.** Port 80 free, enough disk space, the game closed, and the game folder set up to use streamed textures. If something is in the way it says what, and the
   *Doctor* button can fix most of it. If the game folder needs its one-time setup, press *Set up the game* and confirm (see [Game setup](USAGE.md#game-setup-online-mode-and-the-cache-link)); it
   keeps a copy of what it changes.
4. **Texture pack** (offline copy only). Press *Download* in the Texture pack tab. You can pause and resume at any time, and carry on with the next steps while it runs, or skip it.
5. **Start the session.** Press *Start session*. The tool adds one marked block to the protected hosts file and keeps a backup (it can, because the program was started with
   administrator rights). *Restore hosts* takes the block out again.
6. **Play.** Launch the game and leave the tool window open. The step ticks when the game has been delivered its texture pieces.
7. **When you are done.** Press *Stop session*. The tool writes a report (Report tab) and shows a short *What happened* summary.

*Start over* runs the checklist again, *Hide* closes it, and the *Guide* button on the Dashboard (or *Settings, Help*) brings it back.

## Simple view and Full view

*Simple view* keeps five tabs (Dashboard, Texture pack, Doctor, Report, Settings), the profile picker is hidden, and the Dashboard shows four counters instead of twelve.
The *Full view* button in the guide header (or the checkbox in *Settings, Help*) shows everything again. Nothing is lost by switching: only the display changes.

Hover over a status light or a counter to read what it means. The *Words* button opens the list at the bottom of this page.

## When something goes wrong

The guide shows a short card with the likely cause and a button, plus the last problem as the tool printed it. The usual ones:

| What you see | What it means | What to do |
|---|---|---|
| "Windows refused to change the hosts file" | The hosts file is protected, and a security program or the read-only flag blocked the write. Nothing was changed. | Press *Try again* and answer Yes on the prompt. If it is refused again, allow the tool in your security software (or pause it briefly), and check the file is not read-only. |
| "The Windows permission prompt was closed" | The UAC prompt was dismissed (when the program started, or later if you declined it then and it asks per change). | Press *Try again* and answer Yes, or close the program and start it again. |
| "Another program is using the port" | Something else listens on port 80, so the game would talk to it instead of the helper. | Open the *Doctor*: it names the program and can stop it. |
| "The hosts entry is gone" | The helper runs, but the entry that sends the game to it was removed (security software sometimes does this). | *Put it back*, and allow the tool in the security software. |
| "The game is running but nothing reached the helper" | The game was probably started before the session, or a VPN / secure-DNS setting bypasses the hosts file. | Close the game and launch it again after *Start session*, then open the *Doctor*. |
| "The game's servers did not answer" | No internet, or a VPN / firewall in the way. | Check the connection, then the *Doctor*. |

## What happened after the session

When you stop the session the guide shows how many texture pieces the game asked for, where they came from (the internet or your offline copy), and whether any
requests failed. A few failures are normal: the game asks again. That summary is what the tool can see. It does not say how the picture looks.

## Before/after test (optional)

To find out whether it changes anything on your PC, compare the same place in the game with and without the tool. The *Before/after test* button in the guide
(or *Settings, Help*) walks you through four steps and remembers where you stopped:

1. **Pick a spot** you can come back to, with plenty of distant or detailed surfaces, at the same time of day. Keep the graphics settings the same for the whole test. For a strict comparison, rename the game cache folder before each run (the game makes a new one).
2. **Before: tool off.** *Restore hosts* puts the hosts file back, so there is no redirect. Launch the game, go to your spot, wait five minutes, take a screenshot.
3. **After: tool on.** Close the game, press *Start session*, launch, go to the same spot, wait the same time, take a screenshot.
4. **Compare** the two screenshots at full size, looking at distant surfaces and small details. *Open the screenshots folder* gives you a place to keep them.

Some setups show a difference and some do not. The test tells you which it is for yours.

## Words used in this tool

**Session**  
The time between "Start session" and "Stop session". While it runs, the helper is up and the hosts entry sends the game's texture requests to it.

**Helper (proxy)**  
A small program on this PC that answers the game's texture requests. It gets each piece from your copy on disk if you have one, otherwise from the internet.

**Hosts file**  
A Windows file that can override where a web address points. This tool adds one marked block to it so the game talks to the helper. "Restore hosts" takes the block out again, and a backup is made first.

**UAC prompt**  
The Windows window that asks "Do you want to allow this app to make changes?". The program shows it once, when it starts, because it edits the protected hosts file and the game folder. Answer Yes to continue.

**CDN**  
The servers the game downloads its textures from.

**Edge**  
One particular CDN server address. The tool measures a few and uses the fastest.

**Texture piece (chunk)**  
The game streams its textures in many small pieces. Each request from the game is for one piece.

**Streaming**  
Loading textures while you play instead of all at the start. What the game asks for depends on where you are and what it decides to show.

**Quick fix**  
No big download. The helper fetches the pieces the game asks for while you play.

**Offline copy (mirror)**  
A copy of the texture pieces on your own drive (about 54 to 82 GB). The game is served from it, so playing needs little or no internet. The helper still has to run while you play: without it the game cannot reach the copy.

**Detail level**  
A cut-off for very large pieces (the highest-detail versions). Ultra serves everything; Standard leaves the largest out, and the game keeps the smaller version.

**Connections (workers)**  
How many downloads run at the same time when building an offline copy. More is not always faster; the default is a safe starting point.

**Requests per second (req/s)**  
How often the tool asks the CDN for a piece. It is capped so it does not hammer the servers.

**Doctor**  
A checklist that tests everything this tool depends on (port, hosts entry, folders, internet) and offers a safe fix for each failing check.

**Game cache**  
The folder where the game keeps pieces it has already received (xpak_cache). The game recreates it if it is missing.

**Game setup**  
Two small changes in the game folder so the game uses the textures it is sent: its Steam settings are set to online mode, and sp26\xpak_cache is linked to the cache the game fills. Done once, after you confirm.

**Disk guard**  
Watches the game cache and stops the game if it grows past the limit you set, so the drive cannot fill up.

**Report**  
After a session the tool writes a summary of what the game asked for and what was delivered. It is found in the Report tab.
