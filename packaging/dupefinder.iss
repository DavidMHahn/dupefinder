; Inno Setup script for the dupefinder Windows installer.
; Built by .github/workflows/installer.yml:
;   ISCC.exe /DAppVersion=0.2.0 packaging\dupefinder.iss
; It packages the PyInstaller folder dist\dupefinder.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B930CAAC-C2A5-4993-B5BC-876235BA5301}
AppName=dupefinder
AppVersion={#AppVersion}
AppVerName=dupefinder {#AppVersion}
AppPublisher=dupefinder
; Installs for the current user only: no administrator prompt.
PrivilegesRequired=lowest
DefaultDirName={autopf}\dupefinder
DefaultGroupName=dupefinder
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=dupefinder-setup-{#AppVersion}
SetupIconFile=dupefinder.ico
UninstallDisplayIcon={app}\dupefinder.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Close a running copy before updating it.
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\dupefinder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\dupefinder"; Filename: "{app}\dupefinder.exe"
Name: "{autodesktop}\dupefinder"; Filename: "{app}\dupefinder.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\dupefinder.exe"; Description: "Start dupefinder"; Flags: nowait postinstall skipifsilent

; Uninstalling removes the program only. Your scans, moves logs and the
; quarantine folders are kept (%LOCALAPPDATA%\dupefinder and each drive's
; _dupes_quarantine), so anything in quarantine can still be put back or
; checked with the command-line tools.
