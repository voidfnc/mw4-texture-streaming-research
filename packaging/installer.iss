; Inno Setup 6 script for the all-in-one installer. Built by packaging/build.py, which passes:
;   /DAppVersion=<x.y.z-tag>   /DNumericVersion=<x.y.z.0>   /DSourceDir=<built program folder>   /DOutputDir=<where the Setup.exe goes>   /DRepoDir=<repository>   /DNoticeFile=<notice + licence text>
; The version is never typed in this file: it comes from tools/ccslib/version.py through build.py.
#ifndef AppVersion
  #error Build this through packaging/build.py (it passes the version and the folders).
#endif

#define AppName "MW4 Texture Streaming Toolkit"
#define AppExe "MW4 Texture Streaming.exe"
#define CliExe "ccs-cli.exe"
#define Repo "https://github.com/voidfnc/mw4-texture-streaming-research"

[Setup]
AppId={{6B0F1F2E-7D3A-4C58-9E21-4A9D5C7B3E10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=voidfnc
AppPublisherURL={#Repo}
AppSupportURL={#Repo}/issues
AppUpdatesURL={#Repo}/releases
VersionInfoVersion={#NumericVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} setup
; per user by default (no administrator rights needed); the first screen offers "for all users" as an option
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\MW4 Texture Streaming
DisableProgramGroupPage=yes
DisableDirPage=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile={#NoticeFile}
InfoBeforeFile={#SourcePath}\setup-info.txt
SetupIconFile={#RepoDir}\packaging\app.ico
UninstallDisplayIcon={app}\{#AppExe}
OutputDir={#OutputDir}
OutputBaseFilename=MW4-Texture-Streaming-{#AppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; the window holds this mutex while it is open, so setup and uninstall ask for it to be closed first
AppMutex=MW4TextureStreamingToolkit-Running
CloseApplications=yes
RestartApplications=no
SetupMutex=MW4TextureStreamingSetup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "restoreicon"; Description: "Add a ""&Restore hosts"" shortcut to the desktop (an emergency undo)"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\MW4 Texture Streaming\MW4 Texture Streaming"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autoprograms}\MW4 Texture Streaming\Restore hosts"; Filename: "{app}\Restore hosts.bat"; WorkingDir: "{app}"
Name: "{autoprograms}\MW4 Texture Streaming\Start here"; Filename: "{app}\START HERE.txt"
Name: "{autoprograms}\MW4 Texture Streaming\Uninstall"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MW4 Texture Streaming"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{autodesktop}\Restore hosts"; Filename: "{app}\Restore hosts.bat"; WorkingDir: "{app}"; Tasks: restoreicon

[Run]
; shellexec: the program asks for administrator rights (its manifest), which a plain start from this per-user setup could not do
Filename: "{app}\{#AppExe}"; Description: "Start MW4 Texture Streaming"; Flags: shellexec postinstall skipifsilent
Filename: "{app}\START HERE.txt"; Description: "Read the quick start"; Flags: shellexec postinstall skipifsilent unchecked

[Code]
// The program can leave two things behind: helper processes (proxy, disk guard, ...) and the hosts-file block that points the game at them.
// Before files are replaced or removed, both are put back, using the program's own tested "uninstall-prep" commands (exit codes: 1 = hosts block present, 2 = helper running).
function Cli(): String;
begin
  Result := ExpandConstant('{app}\{#CliExe}');
end;

function Prep(const Command: String; var Code: Integer): Boolean;
begin
  Result := FileExists(Cli()) and Exec(Cli(), '--ccs-run uninstall-prep ' + Command, '', SW_HIDE, ewWaitUntilTerminated, Code);
  if not Result then Code := 0;
end;

function MakeSafe(const Doing: String): Boolean;
var
  Status, Done: Integer;
begin
  Result := True;
  if not Prep('status', Status) then Exit;
  if Status = 0 then Exit;
  if MsgBox('MW4 Texture Streaming is active (a session is running, or its hosts-file entry is on).' + #13#10#13#10 +
            'To ' + Doing + ' safely, setup will stop it and put your hosts file back. Windows may ask for permission.' + #13#10#13#10 + 'Continue?',
            mbConfirmation, MB_YESNO) <> IDYES then
  begin
    Result := False;
    Exit;
  end;
  if (Status and 2) <> 0 then Prep('stop-helpers', Done);
  if (Status and 1) <> 0 then
  begin
    if (not Prep('remove-hosts', Done)) or (Done <> 0) then
      Result := MsgBox('The hosts file could not be put back (permission was declined, or the file is protected).' + #13#10#13#10 +
                       'Without that, the game may keep being sent to a program that is no longer running. You can fix it later with "Restore hosts" in the Start menu.' + #13#10#13#10 +
                       'Continue anyway?', mbError, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not MakeSafe('update') then Result := 'Setup was cancelled: nothing was changed.';
end;

function InitializeUninstall(): Boolean;
begin
  Result := MakeSafe('uninstall');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep <> usPostUninstall then Exit;
  Data := ExpandConstant('{localappdata}\MW4TextureStreaming');
  if (not UninstallSilent) and DirExists(Data) then
    if MsgBox('Also delete your settings, logs and reports?' + #13#10#13#10 + Data + #13#10#13#10 +
              'A texture mirror you built and your game folder are never deleted. Choose No to keep your settings for a later reinstall.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(Data, True, True, True);
end;
