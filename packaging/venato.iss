; Inno Setup script: turns dist\Venato (from packaging\venato.spec) into dist\Venato-Setup.exe.
; Installs for the current user only (no admin prompt) into %LOCALAPPDATA%\Programs\Venato,
; with a Start menu shortcut, an optional desktop shortcut and an uninstaller.
; The user's data (%APPDATA%\Venato) is never touched by installing or uninstalling.
; Build (on Windows):  set VENATO_VERSION=1.1.0  then  iscc packaging\venato.iss

#define AppVersion GetEnv("VENATO_VERSION")
#if AppVersion == ""
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E7B3C5A-4F0E-4D2B-9A51-3C8E2F1D7A44}
AppName=Venato
AppVersion={#AppVersion}
AppVerName=Venato {#AppVersion}
AppPublisher=Venato
AppPublisherURL=https://github.com/spencertomj1-hue/arete-app
DefaultDirName={localappdata}\Programs\Venato
DefaultGroupName=Venato
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Venato-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\Venato.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Venato\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Venato"; Filename: "{app}\Venato.exe"
Name: "{autodesktop}\Venato"; Filename: "{app}\Venato.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Venato.exe"; Description: "Open Venato"; Flags: nowait postinstall skipifsilent
