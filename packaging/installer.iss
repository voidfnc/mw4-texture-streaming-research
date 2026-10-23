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
; for all users by default (Program Files, one administrator prompt): the program itself runs as administrator, so its files should be somewhere other programs of the user cannot
; replace. The first screen offers "for me only" (no administrator rights, files in the user's own profile) as an option.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\MW4 Texture Streaming
DisableProgramGroupPage=yes
DisableDirPage=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile={#NoticeFile}
ShowLanguageDialog=yes
UsePreviousLanguage=no
LanguageDetectionMethod=uilanguage
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

; The wizard speaks the Windows display language when it is one of these and shows a language list first (ShowLanguageDialog), so it can be changed. The choice is also saved
; for the program (language.txt in the install folder; the program uses it while its own Language setting is on Automatic). The licence stays in English on purpose.
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"; InfoBeforeFile: "{#SourcePath}\setup-info.txt"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"; InfoBeforeFile: "{#SourcePath}\setup-info.ru.txt"
Name: "chinesesimplified"; MessagesFile: "{#SourcePath}\lang\ChineseSimplified.isl"; InfoBeforeFile: "{#SourcePath}\setup-info.zh-CN.txt"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"; InfoBeforeFile: "{#SourcePath}\setup-info.es.txt"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"; InfoBeforeFile: "{#SourcePath}\setup-info.fr.txt"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"; InfoBeforeFile: "{#SourcePath}\setup-info.de.txt"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"; InfoBeforeFile: "{#SourcePath}\setup-info.pt-BR.txt"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"; InfoBeforeFile: "{#SourcePath}\setup-info.tr.txt"
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"; InfoBeforeFile: "{#SourcePath}\setup-info.pl.txt"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"; InfoBeforeFile: "{#SourcePath}\setup-info.ja.txt"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"; InfoBeforeFile: "{#SourcePath}\setup-info.ko.txt"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"; InfoBeforeFile: "{#SourcePath}\setup-info.it.txt"

#include "lang\messages.iss"

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; GroupDescription: "{cm:TaskGroup}"
Name: "restoreicon"; Description: "{cm:TaskRestore}"; GroupDescription: "{cm:TaskGroup}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\MW4 Texture Streaming\MW4 Texture Streaming"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autoprograms}\MW4 Texture Streaming\Restore hosts"; Filename: "{app}\Restore hosts.bat"; WorkingDir: "{app}"
Name: "{autoprograms}\MW4 Texture Streaming\Start here"; Filename: "{app}\START HERE.txt"
Name: "{autoprograms}\MW4 Texture Streaming\Uninstall"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MW4 Texture Streaming"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{autodesktop}\Restore hosts"; Filename: "{app}\Restore hosts.bat"; WorkingDir: "{app}"; Tasks: restoreicon

[UninstallDelete]
Type: files; Name: "{app}\language.txt"

[Run]
; shellexec: the program asks for administrator rights (its manifest), which a plain start from this per-user setup could not do
Filename: "{app}\{#AppExe}"; Description: "{cm:RunStart}"; Flags: shellexec postinstall skipifsilent
Filename: "{app}\START HERE.txt"; Description: "{cm:RunQuick}"; Flags: shellexec postinstall skipifsilent unchecked

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

function MakeSafe(const Uninstalling: Boolean): Boolean;
var
  Status, Done: Integer;
  Msg: String;
begin
  Result := True;
  if Uninstalling then Msg := 'ActiveUninstall' else Msg := 'ActiveUpdate';
  if not Prep('status', Status) then Exit;
  if Status = 0 then Exit;
  if MsgBox(CustomMessage(Msg), mbConfirmation, MB_YESNO) <> IDYES then
  begin
    Result := False;
    Exit;
  end;
  if (Status and 2) <> 0 then Prep('stop-helpers', Done);
  if (Status and 1) <> 0 then
  begin
    if (not Prep('remove-hosts', Done)) or (Done <> 0) then
      Result := MsgBox(CustomMessage('HostsFail'), mbError, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not MakeSafe(False) then Result := CustomMessage('Cancelled');
end;

function InitializeUninstall(): Boolean;
begin
  Result := MakeSafe(True);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep <> usPostUninstall then Exit;
  Data := ExpandConstant('{localappdata}\MW4TextureStreaming');
  if (not UninstallSilent) and DirExists(Data) then
    if MsgBox(FmtMessage(CustomMessage('DeleteData'), [Data]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(Data, True, True, True);
end;

// The language chosen on the first page becomes the program's language while its own setting is on Automatic (the program reads language.txt next to its exe).
function ProgramLanguage(): String;
var
  L: String;
begin
  L := ActiveLanguage();
  if L = 'russian' then Result := 'ru'
  else if L = 'chinesesimplified' then Result := 'zh-CN'
  else if L = 'spanish' then Result := 'es'
  else if L = 'french' then Result := 'fr'
  else if L = 'german' then Result := 'de'
  else if L = 'brazilianportuguese' then Result := 'pt-BR'
  else if L = 'turkish' then Result := 'tr'
  else if L = 'polish' then Result := 'pl'
  else if L = 'japanese' then Result := 'ja'
  else if L = 'korean' then Result := 'ko'
  else if L = 'italian' then Result := 'it'
  else Result := 'en';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SaveStringToFile(ExpandConstant('{app}\language.txt'), ProgramLanguage(), False);
end;
