# Getting started

This page is for someone who just wants the game to stream its textures. It uses plain words and no command line. Every
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
- A few GiB of free disk space for streaming while you play. An offline copy needs a lot more (about 54 to 82 GB).

Start the window from the Start menu or the desktop shortcut (zip: double-click `MW4 Texture Streaming.exe`; from source: `python tools\ccsgui.py`). Windows asks for permission once (the *UAC prompt*): answer Yes.

## The first start, step by step

The window shows one thing at a time and always the next thing to do. Nothing is changed without a click, and every screen has a hover tip.

1. **Before you start.** A short notice about what this project is and is not, once per version. Read it and press *I understand, continue*.
2. **Let's find your game.** The tool looks in the folder around itself, in your game libraries and in the usual places on every drive, and shows what looks like the game. It never picks one for you: press
   *Yes, use this one*, or *Choose another folder* and point at any folder. If the folder does not look like the game, you can still say *Use it anyway*.
3. **How should textures load?** *While I play* needs no big download: the helper fetches texture pieces as the game asks for them. *Download them once* saves the whole texture pack (about 54 to 82 GB) and plays from disk,
   which suits a slow or metered connection. If you are unsure, take *While I play*; you can build an offline copy later, and *Settings* switches between the two at any time. Either way the program has to be on
   whenever you play: the offline copy replaces the download, not the helper.
4. **One small change in your game folder** (only when it is needed). Port, disk space and the game being closed are checked for you. If the game folder needs its one-time setup, press *Make the change*
   and read [Game setup](USAGE.md#game-setup-online-mode-and-the-cache-link); a copy of what is changed is kept and it can be undone.

## Every day

1. Press **Turn on HD textures**. The tool adds one marked block to the protected hosts file and keeps a backup (it can, because the program was started with administrator rights). *Turn off* takes it out again.
2. Start your game as usual and leave the tool window open. The ring shows how many textures have been delivered, with the speed, how many requests failed and where the textures come from.
3. When you are done playing, press **Turn off when you are done**. The tool writes a report and shows a short summary: how many textures the game asked for and that they were delivered.

*Done* gets you back to the first screen. *See the full report* opens the report, and *Compare before / after* starts the test further down.

If you chose *Download them once*, open *Settings, Offline copy* to start the download. You can pause and resume at any time and keep playing or doing something else meanwhile.

## Settings and Advanced mode

*Settings* (top right) slides in a panel with *How textures load*, *Offline copy*, *Game folder*, *One-time game setup*, *Check my PC*, *What do the words mean?*, *Reports and logs*, *Before / after test*, *Reduce motion* and
*Advanced mode*. *Advanced mode* shows every page of the program behind a side navigation (Live view, Textures, Game and PC, Setup). Each page opens with its name and one line saying what it is for. Nothing is lost by
switching between Home and Advanced mode: only the display changes. Hover over a status light, a counter or a card to read what it means. The *words* list is at the bottom of this page.

## When something goes wrong

The Home screen shows a short card with the likely cause and a button. The usual ones:

| What you see | What it means | What to do |
|---|---|---|
| "Windows refused to change the hosts file" | The hosts file is protected, and a security program or the read-only flag blocked the write. Nothing was changed. | Press *Try again* and answer Yes on the prompt. If it is refused again, allow the tool in your security software (or pause it briefly), and check the file is not read-only. |
| "The Windows permission prompt was closed" | The UAC prompt was dismissed (when the program started, or later if you declined it then and it asks per change). | Press *Try again* and answer Yes, or close the program and start it again. |
| "Another program is using the port" | Something else listens on port 80, so the game would talk to it instead of the helper. | Open *Check my PC* (the Doctor): it names the program and can stop it. |
| "The hosts entry is gone" | The helper runs, but the entry that sends the game to it was removed (security software sometimes does this). | *Put it back*, and allow the tool in the security software. |
| "The game is running but nothing reached the helper" | The game was probably started before the session, or a VPN / secure-DNS setting bypasses the hosts file. | Close the game and launch it again after *Turn on HD textures*, then open *Check my PC*. |
| "The game's servers did not answer" | No internet, or a VPN / firewall in the way. | Check the connection, then *Check my PC*. |

## What happened after the session

When you turn it off, the Home screen shows how many texture pieces the game asked for, where they came from (the internet or your offline copy), and whether any
requests failed. A few failures are normal: the game asks again. That summary is what the tool can see. It does not say how the picture looks.

## Before/after test (optional)

To find out whether it changes anything on your PC, compare the same place in the game with and without the tool. *Compare before / after* on the last screen
(or *Settings, Before / after test*) walks you through four steps and remembers where you stopped:

1. **Pick a spot** you can come back to, with plenty of distant or detailed surfaces, at the same time of day. Keep the graphics settings the same for the whole test. For a strict comparison, rename the game cache folder before each run (the game makes a new one).
2. **Before: tool off.** The test's button puts the hosts file back (the same as *Turn off*), so there is no redirect. Launch the game, go to your spot, wait five minutes, take a screenshot.
3. **After: tool on.** Close the game, press *Turn on HD textures*, launch, go to the same spot, wait the same time, take a screenshot.
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
