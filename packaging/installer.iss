; Inno Setup script. Wraps the PyInstaller folder in one Setup.exe.
;
; Installs per user, under %LOCALAPPDATA%\Programs, so no admin prompt and no
; Program Files. The program's own files (config, calibration, logs, samples)
; live in %LOCALAPPDATA%\BDO Autoroute Track and survive an uninstall on
; purpose: a reinstall should not cost a calibration.
;
; Compiled by build-exe.cmd with /DMyAppVersion=<version>.

#define MyAppName "BDO Autoroute Track"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppExeName "BDO Autoroute Track.exe"
#define MyAppPublisher "delCatta"
#define MyAppURL "https://github.com/delCatta/bdo-autoroute-track"

[Setup]
AppId={{7E1D3B6C-5C0A-4B0E-9C7C-2A5F8E6B1D42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases/latest
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=BDO-Autoroute-Track-Setup-{#MyAppVersion}
SetupIconFile=..\assets\boat.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put a shortcut on the Desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Open {#MyAppName}"; Flags: nowait postinstall skipifsilent
