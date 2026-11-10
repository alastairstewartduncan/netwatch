; ---------------------------------------------------------------------------------------------
;  NetWatch installer (NSIS 3, Modern UI 2)
;
;  Built by build.bat:   makensis installer\netwatch.nsi
;  Expects:  build\version.nsh            (from tools\make_version_info.py)
;            dist\NetWatch\               (PyInstaller one-folder build)
;  Produces: dist\NetWatch-Setup-<version>.exe
;
;  Command line:  /S          silent install (uses defaults: Start menu shortcut, start with Windows, firewall)
;                 /UPDATE     used by NetWatch's updater: relaunch NetWatch after a silent upgrade
;                 /D=path     install folder (must be last)
; ---------------------------------------------------------------------------------------------

Unicode true
ManifestDPIAware true
SetCompressor /SOLID lzma
SetCompressorDictSize 64

!include "..\build\version.nsh"
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "Sections.nsh"

!define EXE          "NetWatch.exe"
!define UNINST_EXE   "Uninstall NetWatch.exe"
!define UNINST_KEY   "Software\Microsoft\Windows\CurrentVersion\Uninstall\NetWatch"
!define RUN_KEY      "Software\Microsoft\Windows\CurrentVersion\Run"
!define FW_RULE      "NetWatch phone dashboard"
!define MUTEX        "Global\NetWatchSingleInstance"
!define WV2_GUID     "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
!define WV2_URL      "https://go.microsoft.com/fwlink/p/?LinkId=2124703"

Name "${APP_NAME}"
Caption "${APP_NAME} ${APP_VERSION} Setup"
BrandingText "${APP_NAME} ${APP_VERSION}  ·  ${APP_PUBLISHER}"
OutFile "..\dist\NetWatch-Setup-${APP_VERSION}.exe"
InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "${UNINST_KEY}" "InstallLocation"
RequestExecutionLevel admin
ShowInstDetails hide
ShowUninstDetails hide

VIProductVersion "${APP_VERSION4}"
VIAddVersionKey /LANG=1033 "ProductName"     "${APP_NAME}"
VIAddVersionKey /LANG=1033 "ProductVersion"  "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "FileVersion"     "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "FileDescription" "${APP_NAME} Setup"
VIAddVersionKey /LANG=1033 "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey /LANG=1033 "LegalCopyright"  "${APP_COPYRIGHT}"

Var IsUpdate
Var PrevVersion

; ------------------------------------------------------------------ look & feel
!define MUI_ICON   "..\assets\netwatch.ico"
!define MUI_UNICON "..\assets\netwatch.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP   "..\assets\installer-sidebar.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "..\assets\installer-sidebar.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP   "..\assets\installer-header.bmp"
!define MUI_HEADERIMAGE_UNBITMAP "..\assets\installer-header.bmp"
!define MUI_ABORTWARNING
!define MUI_ABORTWARNING_TEXT "Are you sure you want to stop installing ${APP_NAME}?"
!define MUI_COMPONENTSPAGE_SMALLDESC

; ------------------------------------------------------------------ pages
!define MUI_WELCOMEPAGE_TITLE "Welcome to ${APP_NAME} ${APP_VERSION}"
!define MUI_WELCOMEPAGE_TEXT "${APP_NAME} keeps an eye on your internet connection, Wi-Fi and the devices on your network, and tells you when something goes wrong.$\r$\n$\r$\nSetup will install ${APP_NAME} on this PC. If an earlier version is installed, it will be upgraded and your settings and history kept.$\r$\n$\r$\nClick Next to continue."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE.txt"
!define MUI_PAGE_HEADER_TEXT "Choose options"
!define MUI_PAGE_HEADER_SUBTEXT "Pick how ${APP_NAME} fits into Windows. You can change all of these later in Settings."
!define MUI_COMPONENTSPAGE_TEXT_TOP "Tick the extras you'd like."
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "${APP_NAME} is ready"
!define MUI_FINISHPAGE_TEXT "${APP_NAME} ${APP_VERSION} has been installed.$\r$\n$\r$\nIt lives in the system tray next to the clock and keeps monitoring when you close its window. Find it any time in the Start menu."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APP_NAME} now"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\THIRD-PARTY-NOTICES.txt"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Show third-party notices"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!insertmacro MUI_PAGE_FINISH

!define MUI_WELCOMEPAGE_TITLE "Uninstall ${APP_NAME}"
!define MUI_WELCOMEPAGE_TEXT "This will remove ${APP_NAME} ${APP_VERSION} from your PC.$\r$\n$\r$\nOn the next page you can choose whether to keep your settings and monitoring history, in case you reinstall later."
!insertmacro MUI_UNPAGE_WELCOME
!define MUI_PAGE_HEADER_TEXT "Your data"
!define MUI_PAGE_HEADER_SUBTEXT "Choose what to remove."
!define MUI_COMPONENTSPAGE_TEXT_TOP "${APP_NAME} itself is always removed. Tick the box below to delete your settings, history, device list and captures too."
!insertmacro MUI_UNPAGE_COMPONENTS
!insertmacro MUI_UNPAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "${APP_NAME} has been removed"
!define MUI_FINISHPAGE_TEXT "Thanks for using ${APP_NAME}."
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

; ------------------------------------------------------------------ helpers
!macro CloseNetWatch UN
Function ${UN}CloseNetWatch
  ; NetWatch holds a named mutex while running - if it exists, the app is open.
  System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "${MUTEX}") p .r0'
  ${If} $0 P<> 0
    System::Call 'kernel32::CloseHandle(p r0)'
    ${IfNot} ${Silent}
      MessageBox MB_OKCANCEL|MB_ICONINFORMATION "${APP_NAME} is running.$\r$\n$\r$\nClick OK to close it and continue." IDOK +2
      Abort
    ${EndIf}
    nsExec::Exec 'taskkill /IM "${EXE}" /F'
    Pop $1
    Sleep 1500
  ${EndIf}
FunctionEnd
!macroend
!insertmacro CloseNetWatch ""
!insertmacro CloseNetWatch "un."

Function LaunchApp
  ; Launch through Explorer so NetWatch runs as the signed-in user, not elevated like Setup
  Exec '"$WINDIR\explorer.exe" "$INSTDIR\${EXE}"'
FunctionEnd

Function EnsureWebView2
  ReadRegStr $0 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\${WV2_GUID}" "pv"
  ${If} $0 == ""
  ${OrIf} $0 == "0.0.0.0"
    ReadRegStr $0 HKCU "Software\Microsoft\EdgeUpdate\Clients\${WV2_GUID}" "pv"
  ${EndIf}
  ${If} $0 == ""
  ${OrIf} $0 == "0.0.0.0"
    DetailPrint "Installing Microsoft Edge WebView2 Runtime (needed for NetWatch's window)..."
    nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -Command "$$ProgressPreference=''SilentlyContinue''; Invoke-WebRequest -UseBasicParsing ''${WV2_URL}'' -OutFile ''$TEMP\MicrosoftEdgeWebview2Setup.exe''"'
    Pop $1
    ${If} ${FileExists} "$TEMP\MicrosoftEdgeWebview2Setup.exe"
      ExecWait '"$TEMP\MicrosoftEdgeWebview2Setup.exe" /silent /install' $1
      Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
    ${Else}
      DetailPrint "Couldn't download WebView2 - NetWatch can still run with:  NetWatch.exe --browser"
    ${EndIf}
  ${Else}
    DetailPrint "WebView2 Runtime $0 found"
  ${EndIf}
FunctionEnd

; ------------------------------------------------------------------ install
Section "-${APP_NAME} (required)" SecCore
  SectionIn RO
  Call CloseNetWatch
  SetOutPath "$INSTDIR"
  SetOverwrite on
  ; remove the previous version's program files (never user data) so stale files don't linger
  ${If} ${FileExists} "$INSTDIR\${EXE}"
    RMDir /r "$INSTDIR\_internal"
  ${EndIf}
  File /r "..\dist\NetWatch\*.*"
  File "..\LICENSE.txt"
  File "..\THIRD-PARTY-NOTICES.txt"
  WriteUninstaller "$INSTDIR\${UNINST_EXE}"

  ; Start menu (top level, like modern Windows apps)
  CreateShortcut "$SMPROGRAMS\${APP_NAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0 SW_SHOWNORMAL "" "${APP_DESCRIPTION}"

  ; Settings -> Apps entry
  WriteRegStr   HKLM "${UNINST_KEY}" "DisplayName"          "${APP_NAME}"
  WriteRegStr   HKLM "${UNINST_KEY}" "DisplayVersion"       "${APP_VERSION}"
  WriteRegStr   HKLM "${UNINST_KEY}" "Publisher"            "${APP_PUBLISHER}"
  WriteRegStr   HKLM "${UNINST_KEY}" "DisplayIcon"          "$INSTDIR\${EXE},0"
  WriteRegStr   HKLM "${UNINST_KEY}" "InstallLocation"      "$INSTDIR"
  WriteRegStr   HKLM "${UNINST_KEY}" "UninstallString"      '"$INSTDIR\${UNINST_EXE}"'
  WriteRegStr   HKLM "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\${UNINST_EXE}" /S'
  WriteRegStr   HKLM "${UNINST_KEY}" "Comments"             "${APP_DESCRIPTION}"
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${UNINST_KEY}" "EstimatedSize" "$0"

  Call EnsureWebView2
SectionEnd

Section "Desktop shortcut" SecDesktop
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0 SW_SHOWNORMAL "" "${APP_DESCRIPTION}"
SectionEnd

Section "Start NetWatch when I sign in" SecStartup
  WriteRegStr HKCU "${RUN_KEY}" "${APP_NAME}" '"$INSTDIR\${EXE}" --minimized'
SectionEnd

Section "Allow the phone dashboard on my home network" SecFirewall
  nsExec::Exec 'netsh advfirewall firewall delete rule name="${FW_RULE}"'
  Pop $0
  nsExec::Exec 'netsh advfirewall firewall add rule name="${FW_RULE}" dir=in action=allow program="$INSTDIR\${EXE}" profile=private enable=yes description="Lets phones on your home network open the NetWatch dashboard (only when you switch it on in NetWatch)."'
  Pop $0
SectionEnd

Section "-Finish"
  ${If} $IsUpdate == 1
    Call LaunchApp
  ${EndIf}
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop}  "Put a ${APP_NAME} icon on your desktop."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartup}  "Start quietly in the system tray when you sign in to Windows, so monitoring never stops. Recommended."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecFirewall} "Add a Windows Firewall rule for private networks only, so your phone can open the dashboard once you switch it on."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "${APP_NAME} needs 64-bit Windows 10 or 11."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_ICONSTOP "${APP_NAME} needs Windows 10 or later."
    Abort
  ${EndIf}
  SetRegView 64
  SetShellVarContext all   ; Start menu & desktop shortcuts for everyone on this PC
  ; one installer at a time
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "NetWatchSetupRunning") p .r0 ?e'
  Pop $1
  ${If} $1 == 183
    MessageBox MB_ICONINFORMATION "${APP_NAME} Setup is already running."
    Abort
  ${EndIf}
  StrCpy $IsUpdate 0
  ${GetParameters} $R0
  ClearErrors
  ${GetOptions} $R0 "/UPDATE" $R1
  ${IfNot} ${Errors}
    StrCpy $IsUpdate 1
  ${EndIf}
  ; upgrading? keep the previous folder and the user's earlier choices
  ReadRegStr $PrevVersion HKLM "${UNINST_KEY}" "DisplayVersion"
  ${If} $PrevVersion != ""
    ${IfNot} ${FileExists} "$DESKTOP\${APP_NAME}.lnk"
      !insertmacro UnselectSection ${SecDesktop}
    ${EndIf}
    ReadRegStr $0 HKCU "${RUN_KEY}" "${APP_NAME}"
    ${If} $0 == ""
      !insertmacro UnselectSection ${SecStartup}
    ${EndIf}
  ${EndIf}
FunctionEnd

; ------------------------------------------------------------------ uninstall
Section "un.${APP_NAME}" SecUnCore
  SectionIn RO
  Call un.CloseNetWatch
  Delete "$SMPROGRAMS\${APP_NAME}.lnk"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  DeleteRegValue HKCU "${RUN_KEY}" "${APP_NAME}"
  nsExec::Exec 'netsh advfirewall firewall delete rule name="${FW_RULE}"'
  Pop $0
  ; firewall rules NetWatch created when you blocked apps
  nsExec::Exec 'powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetFirewallRule -DisplayName ''NetWatch block - *'' -ErrorAction SilentlyContinue | Remove-NetFirewallRule"'
  Pop $0
  ; program files only - by name, never a blanket delete of the folder
  Delete "$INSTDIR\${EXE}"
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\LICENSE.txt"
  Delete "$INSTDIR\THIRD-PARTY-NOTICES.txt"
  Delete "$INSTDIR\${UNINST_EXE}"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "${UNINST_KEY}"
SectionEnd

Section /o "un.Also delete my settings and history" SecUnData
  SetShellVarContext current
  RMDir /r "$APPDATA\${APP_NAME}"
  SetShellVarContext all
SectionEnd

!insertmacro MUI_UNFUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecUnCore} "Removes the program, shortcuts, start-up entry and firewall rules."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecUnData} "Deletes %APPDATA%\NetWatch: settings, monitoring history, device list, speed tests and captures. Can't be undone."
!insertmacro MUI_UNFUNCTION_DESCRIPTION_END

Function un.onInit
  SetRegView 64
  SetShellVarContext all
FunctionEnd
