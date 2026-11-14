; AGY Plugin Manager - Inno Setup 6 Installer Script
; Produces standard Windows Setup executable (eliminates PyInstaller --onefile self-extraction false positives)

#ifndef AppVersion
  #define AppVersion "2.3.0"
#endif
#ifndef AppDir
  #define AppDir "..\dist\AGY-Plugin-Manager"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{8E9B7D4A-4B3C-4C12-9F5E-1A2B3C4D5E6F}
AppName=AGY Plugin Manager
AppVersion={#AppVersion}
AppVerName=AGY Plugin Manager v{#AppVersion}
AppPublisher=HaoAn Lab
AppPublisherURL=https://ahmustudyhelper.xyz
AppSupportURL=https://github.com/haoan33/AGY-Plugin-Manager
DefaultDirName={localappdata}\AGY-Plugin-Manager
DisableProgramGroupPage=yes
DefaultGroupName=AGY Plugin Manager
OutputDir={#OutputDir}
OutputBaseFilename=AGY-Plugin-Manager-Setup-v{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\AGY Plugin Manager.exe
UninstallDisplayName=AGY Plugin Manager
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=AGY Plugin Manager.exe,node.exe

[Languages]
Name: "default"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式（AGY Plugin Manager 与 Antigravity (AGY-Launcher)）"; GroupDescription: "快捷方式选项："

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\plugins.example.json"; DestDir: "{app}"; DestName: "plugins.json"; Flags: onlyifdoesntexist

[Icons]
Name: "{autodesktop}\AGY Plugin Manager"; Filename: "{app}\AGY Plugin Manager.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\app.ico"; Comment: "AGY Plugin Manager 控制中心"; Tasks: desktopicon
Name: "{autodesktop}\Antigravity (AGY-Launcher)"; Filename: "{app}\AGY Plugin Manager.exe"; Parameters: "--quick-launch"; WorkingDir: "{app}"; IconFilename: "{code:GetAntigravityIcon}"; Comment: "通过 AGY-Launcher 启动 Antigravity 并自动挂载插件"; Tasks: desktopicon
Name: "{group}\AGY Plugin Manager"; Filename: "{app}\AGY Plugin Manager.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\app.ico"
Name: "{group}\Antigravity (AGY-Launcher)"; Filename: "{app}\AGY Plugin Manager.exe"; Parameters: "--quick-launch"; WorkingDir: "{app}"; IconFilename: "{code:GetAntigravityIcon}"
Name: "{group}\{cm:UninstallProgram,AGY Plugin Manager}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\AGY Plugin Manager.exe"; Description: "安装完成后立即启动 AGY Plugin Manager"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\AGY Plugin Manager.exe"; Parameters: "--stop"; Flags: runhidden; RunOnceId: "StopAgyPlugins"

[Code]
function ExtractExePath(const Raw: string): string;
var
  S: string;
  QPos, EPos: Integer;
begin
  Result := '';
  S := Trim(Raw);
  if S = '' then Exit;
  if S[1] = '"' then
  begin
    Delete(S, 1, 1);
    QPos := Pos('"', S);
    if QPos > 0 then
      S := Copy(S, 1, QPos - 1);
  end
  else
  begin
    EPos := Pos('.exe', LowerCase(S));
    if EPos > 0 then
      S := Copy(S, 1, EPos + 3);
  end;
  if FileExists(S) then
    Result := S;
end;

function GetAntigravityExePath(Param: string): string;
var
  Cand, RegVal: string;
begin
  Result := '';
  Cand := ExpandConstant('{localappdata}\Programs\antigravity\Antigravity.exe');
  if FileExists(Cand) then begin Result := Cand; Exit; end;

  Cand := ExpandConstant('{localappdata}\Programs\Antigravity\Antigravity.exe');
  if FileExists(Cand) then begin Result := Cand; Exit; end;

  Cand := ExpandConstant('{pf}\Antigravity\Antigravity.exe');
  if FileExists(Cand) then begin Result := Cand; Exit; end;

  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\App Paths\Antigravity.exe', '', RegVal) then
  begin
    Cand := ExtractExePath(RegVal);
    if Cand <> '' then begin Result := Cand; Exit; end;
  end;

  if RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\App Paths\Antigravity.exe', '', RegVal) then
  begin
    Cand := ExtractExePath(RegVal);
    if Cand <> '' then begin Result := Cand; Exit; end;
  end;

  if RegQueryStringValue(HKCU, 'Software\Classes\antigravity\shell\open\command', '', RegVal) then
  begin
    Cand := ExtractExePath(RegVal);
    if Cand <> '' then begin Result := Cand; Exit; end;
  end;

  if RegQueryStringValue(HKLM, 'Software\Classes\antigravity\shell\open\command', '', RegVal) then
  begin
    Cand := ExtractExePath(RegVal);
    if Cand <> '' then begin Result := Cand; Exit; end;
  end;
end;

function GetAntigravityIcon(Param: string): string;
var
  ExePath: string;
begin
  ExePath := GetAntigravityExePath('');
  if ExePath <> '' then
    Result := ExePath
  else
    Result := ExpandConstant('{app}\assets\app.ico');
end;

function JsonEscape(const S: string): string;
var
  I: Integer;
begin
  Result := '';
  for I := 1 to Length(S) do
  begin
    if S[I] = '\' then
      Result := Result + '\\'
    else if S[I] = '"' then
      Result := Result + '\"'
    else
      Result := Result + S[I];
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  CfgPath, ExePath, RawText: string;
  Content: AnsiString;
begin
  if CurStep = ssPostInstall then
  begin
    CfgPath := ExpandConstant('{app}\plugins.json');
    ExePath := GetAntigravityExePath('');
    if (ExePath <> '') and FileExists(CfgPath) then
    begin
      if LoadStringFromFile(CfgPath, Content) then
      begin
        RawText := string(Content);
        if Pos('"antigravityExe": ""', RawText) > 0 then
        begin
          StringChangeEx(RawText, '"antigravityExe": ""', '"antigravityExe": "' + JsonEscape(ExePath) + '"', True);
          SaveStringToFile(CfgPath, AnsiString(RawText), False);
        end;
      end;
    end;
  end;
end;
