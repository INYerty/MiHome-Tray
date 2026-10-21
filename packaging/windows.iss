; SPDX-License-Identifier: GPL-3.0-or-later
#ifndef AppVersion
  #error AppVersion must be supplied by build_installer.py
#endif
#define SourceRoot AddBackslash(SourcePath) + ".."

[Setup]
AppId={{45A39071-5FD2-4D3D-92A2-F5B6E592151B}
AppName=米家快捷控制
AppVersion={#AppVersion}
AppPublisher=MiHome Tray contributors
AppPublisherURL=https://github.com/INYerty/MiHome-Tray
AppSupportURL=https://github.com/INYerty/MiHome-Tray/issues
AppUpdatesURL=https://github.com/INYerty/MiHome-Tray/releases
DefaultDirName={localappdata}\Programs\MiHome-Tray
DefaultGroupName=米家快捷控制
UninstallDisplayIcon={app}\MiHome-Tray.exe
OutputDir={#SourceRoot}\dist
OutputBaseFilename=MiHome-Tray-Setup-{#AppVersion}-x64
SetupIconFile={#SourceRoot}\app\ui\icon.ico
LicenseFile={#SourceRoot}\LICENSE
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
PrivilegesRequired=lowest
WizardStyle=modern
Compression=lzma2/normal
SolidCompression=yes
CloseApplications=yes
CloseApplicationsFilter=MiHome-Tray.exe
RestartApplications=no
Uninstallable=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#SourceRoot}\dist\MiHome-Tray\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\米家快捷控制"; Filename: "{app}\MiHome-Tray.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\米家快捷控制"; Filename: "{app}\MiHome-Tray.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\MiHome-Tray.exe"; Description: "启动米家快捷控制"; Flags: nowait postinstall skipifsilent; Check: not IsAppUpdate
Filename: "{app}\MiHome-Tray.exe"; Flags: nowait; Check: IsAppUpdate

[Code]
function IsAppUpdate: Boolean;
begin
  Result := ExpandConstant('{param:APPUPDATE|0}') = '1';
end;
