@echo off
rem Builds and tests the installer and the portable zip: packaging\out\*.  One command, about three minutes.
rem  - needs Python 3.12 on PATH and Inno Setup 6 (winget install JRSoftware.InnoSetup)
rem  - the first run makes a throw-away build environment in %TEMP% (pinned PyInstaller, hashes checked); your own Python is not changed
setlocal
set VENV=%TEMP%\mw4-build-venv
if not exist "%VENV%\Scripts\python.exe" (
  python -m venv "%VENV%" || exit /b 1
  "%VENV%\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check --require-hashes -r "%~dp0requirements-build.txt" || exit /b 1
)
rem files of an earlier version would otherwise be tested (and offered to release.py) too
del /q "%~dp0out\*-Setup.exe" "%~dp0out\*-portable.zip" "%~dp0out\SHA256SUMS.txt" 2>nul
"%VENV%\Scripts\python.exe" -W ignore "%~dp0build.py" %* || exit /b 1
for %%f in ("%~dp0out\*-Setup.exe") do python "%~dp0test_installer.py" "%%f" || exit /b 1
echo.
echo Done. Files are in %~dp0out
echo Next: python packaging\release.py --dry-run
