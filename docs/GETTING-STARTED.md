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

- **The installer** (`...-Setup.exe`, recommended): double-click, pick a language if the preselected one (your Windows language) is not the one you want, accept the notice, press Next and Install. It installs for all users by default (in Program Files, with one Windows permission prompt);
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
| "Windows is using port 80" (System, pid 4) | Windows itself holds the port because a Windows web service (IIS, "World Wide Web Publishing Service", SQL Server Reporting Services and similar) is registered on it. Windows' own process cannot be ended. | Open *Check my PC*: it names the running web service and offers *stop web service* (Windows asks for permission). Start the service again later in `services.msc` if you use it. If no service is named, run `netsh http show servicestate view=requestq` in an administrator command prompt to see which program uses the port. |
| "The hosts entry is gone" | The helper runs, but the entry that sends the game to it was removed (security software sometimes does this). | *Put it back*, and allow the tool in the security software. |
| "The game is running but nothing reached the helper" | The game was probably started before the session, or a VPN / secure-DNS setting bypasses the hosts file. | Close the game and launch it again after *Turn on HD textures*, then open *Check my PC*. |
| "The setup could not be finished ... Incorrect function" (step 3) | The game folder is on a drive that cannot hold folder links (exFAT or FAT32), so the cache link, which HD textures need, cannot be made. Current versions say this on the screen. | Move the game folder to an NTFS drive, then press *Choose another folder* and pick its new place. |
| "... file system data is damaged" / "corrupted and unreadable" (step 3) | Windows itself cannot read that folder's file system data any more, often from the drive being written to by another operating system. This tool cannot repair it. | Close the game and this helper, open an administrator command prompt and run `chkdsk <drive letter>: /f` (it may ask to restart), then open the program again and try step 3. |
| Doctor: "CDN chunk lists: none found" | The game folder has no chunk lists where the program looks. The normal ones are `*_cdn.xpak` files, and the Xbox / Microsoft Store version has `*_cdn_stub.xpak` files instead, which current versions use as well. | Check that the folder you chose is the game folder (it contains `cod26` or `sp26`). On the Xbox version no renaming is needed. |
| "The game's servers did not answer" | No internet, or a VPN / firewall in the way. | Check the connection, then *Check my PC*. |
| Doctor: "Windows network status ... no network connection at all" (textures stay blurry, the request count stops at a few dozen) | The PC has no network adapter that is switched on, so Windows reports no connection. The game checks that and then asks for no textures at all, even though your offline copy is complete. | See *A PC with no network card* below. |
| "start failed: [Errno 2] No such file or directory: '...\drivers\etc\hosts'" / Doctor: "the hosts file itself does not exist on this PC" | Windows has no hosts file at all (some tweak or "debloat" tools delete it). Current versions treat that as an empty file. | Press *Turn on HD textures* (or the Doctor's *Apply*): the file is created with only our marked block. *Turn off* takes the block out again. |
| Doctor: "Resolver" fails although "Hosts override" is OK, and "Resolver diagnosis" says something outside the file overrides it | The block is in the hosts file, but Windows still answers from DNS. Flushing the DNS cache does not help then. The usual causes are security software with hosts-file protection, a VPN or DNS tool that answers name lookups itself, or a group policy. A hosts file saved as UTF-16 is also ignored by Windows (*Apply* now writes it as plain UTF-8 and keeps a backup). | Pause the security software, VPN or DNS tool for a minute and press *Check my PC* again. If it stays red, export the support bundle (Advanced mode, Doctor): `state/resolver.txt` shows what Windows reports about the file and the DNS Client service. |
| Doctor: "Hosts file permissions" fails (the DNS Client service cannot read the hosts file) | Windows ignores a hosts file that its DNS Client service is not allowed to read, so the block in it has no effect. Some tweak or security tools change a file's permissions. | Press *Repair hosts permissions* next to the row (Windows asks for permission once): the permissions go back to the folder default and the old ones are saved next to the hosts backups. Then press *Check my PC* again. |
| Doctor: "Resolver" shows a warning although "Hosts override" is OK, and the permissions row is green | Something outside the hosts file answers this check from DNS (a VPN or DNS program, security software, a group policy), but the game may still use the hosts file. | Start the game as usual. If it has run for five minutes with no texture request, the log says so and why; then pause the VPN, DNS or security software and check again, or export the support bundle (`state/resolver.txt`). |
| After a game update the Texture pack tab shows chunks "not mirrored yet", or the report lists ids "not in any chunk list" | A game update added chunks. The ones in the new lists are fetched when you press **Download** again (what you have is kept). Ids in no list are served live, which is normal, and the next Download stores them too. | Update the game, open the Texture pack tab, press **Download**. |
| Doctor: "Disk guard ... ends the game when the cache folder reaches ... GiB" | The game's cache folder is already close to the guard's limit (the game's own files can start out large), so the guard would end the game early in a long session. | Raise the limit in Advanced mode, Settings (*Disk guard: xpak_cache limit*), or move the game cache to a bigger drive. |

## A PC with no network card

The game only asks for textures while Windows reports some network connection. It does not matter that the pieces are on your own drive: with no adapter at all (no cable, no Wi-Fi, no network card) the game never asks, and the textures stay as they are in the base game.
*Check my PC* shows this as **Windows network status**. The tool itself needs no internet once your offline copy is complete.

What is needed is a network adapter that Windows sees as connected, not a real connection. Windows reports "no network" while an adapter has only an address: it also needs a route toward the internet (a default gateway) before it reports a connection. A virtual adapter with an address and a gateway is the thing to try:

1. Open *Device Manager*, click any entry in the list, then *Action, Add legacy hardware*, *Next*, choose *Install the hardware that I manually select from a list*.
2. Pick *Network adapters*, then the manufacturer *Microsoft* and the adapter *Microsoft KM-TEST Loopback Adapter*, and finish the wizard.
3. In *Network Connections*, open the properties of the new adapter, then *Internet Protocol Version 4*, and give it a fixed address such as `192.168.250.1` with mask `255.255.255.0` and a default gateway on the same subnet such as `192.168.250.254` (nothing has to answer at that address). An address alone is not enough: Windows still reports no network then.
4. Wait about 30 seconds (Windows checks the connection in the background) and open *Check my PC* again: *Windows network status* should now be OK. Restart the game after that; the game reads the status when it starts and when it changes.

This changes network settings on your PC, so it is left to you and nothing in this tool does it for you. The gateway step has not been confirmed on a PC that has no network card at all, so treat it as the next thing to try, not as a promise. To see what Windows reports while you change a setting, this reads the same value the game reads and changes nothing (stop it with Ctrl+C); level 1 means none, 2 local only, 3 internet:

```
$sig = '[StructLayout(LayoutKind.Sequential)] public struct Hint { public int Level; public int Cost; public byte A; public byte O; public byte R; } [DllImport("iphlpapi.dll")] public static extern uint GetNetworkConnectivityHint(out Hint h);'
Add-Type -Namespace Ccs -Name Net -MemberDefinition $sig
while ($true) { $h = New-Object Ccs.Net+Hint; [Ccs.Net]::GetNetworkConnectivityHint([ref]$h) | Out-Null; "{0} level={1} cost={2} ipv4={3}" -f (Get-Date -Format T), $h.Level, $h.Cost, ((Get-NetConnectionProfile | ForEach-Object { $_.IPv4Connectivity }) -join ','); Start-Sleep 3 }
```

The game may have other conditions before it asks for textures that this tool cannot see. Two things help to find out which one applies:

- If the *Windows network status* row still shows its warning after the steps above, check in *Network Connections* that the new adapter shows as *Enabled* and not as *Network cable unplugged*.
- If the row is OK and the game still asks for nothing, export the support bundle (Advanced mode, Doctor) and attach it to an issue: `state/network.txt` shows what Windows reports (the connectivity level, the adapters and their state, no addresses), and `state/cache.txt` shows what the game's own cache holds.

A short session also often asks for little or nothing, because the game keeps what it has already received in its own cache and asks mostly when you reach somewhere new. Play a while, in places you have not been, before you judge.

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

## Testing multiplayer / HQ (experimental)

**On an HQ install** (for example the Steam game *Call of Duty HQ*), `cod.exe` is only the HQ menu. The campaign runs as a second program, `sp26-cod.exe`, which starts when you start the campaign from HQ, and it is that program
that asks for the campaign textures. With only `cod.exe` open the helper sees almost nothing, so a test in the HQ menu proves nothing: start the campaign, play for 15 to 20 minutes, then look at the numbers or export the
support bundle (its *Game* row names the programs that were running).

The campaign (`sp26-cod.exe`) is what this tool was built and tested on. Multiplayer and HQ run as `cod.exe`; the tool detects it, but nobody has confirmed that this part of the game asks the same server for
its textures. If you want to help find out:

1. Open *Advanced mode*, tab *Proxy*, and tick *Start netwatch (DNS/TCP log of the game) with the session*. It needs the Windows DNS client log, which a normal Windows has; see the tool's help if it asks.
2. Turn HD textures on, start the game, play a match or load a map, then look at the number of delivered textures on the home screen.
3. If it stays at zero, open *Doctor*, press *Export support bundle (zip)* and attach it to a bug report (it holds the helper's log and, with netwatch on, the names and addresses the game connected to).
   Nothing from your game folder is in it, and your Windows user name is removed.

**What the maintainer is doing about it.** The multiplayer version of the game is going to be installed and tested with this tool on a private local network, to find out whether multiplayer and HQ ask for their textures
through the same route, what the game does when that route is answered from the mirror, and which fixes the tool needs for it. Results, and any change to the tool that follows, will be added to this guide, to
[FINDINGS](FINDINGS.md) and to the changelog. Until then everything about multiplayer and HQ stays experimental, as above.

The disk guard only ends `sp26-cod.exe` by default. It never ends `cod.exe` during an online match unless you add that name yourself in the settings. Whether the publisher's anti-cheat accepts a changed
hosts file is not something this project can promise; see the [disclaimer](../DISCLAIMER.md).

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
