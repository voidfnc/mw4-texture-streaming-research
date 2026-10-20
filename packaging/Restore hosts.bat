@echo off
rem Emergency undo: removes ONLY the MW4 Texture Streaming override from the hosts file (normal DNS for the CDN host again).
rem Hand-added lines for cod-assets.cdn.callofduty.com are removed too. A backup is written first. Works without the window.
"%~dp0ccs-cli.exe" --ccs-run ccshosts remove --elevate
"%~dp0ccs-cli.exe" --ccs-run ccshosts status
pause
