!include "LogicLib.nsh"

; Match local hot-sync default install directory (%LOCALAPPDATA%\AGY-Plugin-Manager)
InstallDir "$LOCALAPPDATA\AGY-Plugin-Manager"

!macro NSIS_HOOK_PREINSTALL
  ; Normalize default install path if Tauri's template defaulted to productName ("AGY Plugin Manager")
  ${If} $INSTDIR == "$LOCALAPPDATA\AGY Plugin Manager"
    StrCpy $INSTDIR "$LOCALAPPDATA\AGY-Plugin-Manager"
  ${EndIf}

  ; Gracefully stop managed plugins and any running manager process before replacing binaries
  ${If} ${FileExists} "$INSTDIR\AGY Plugin Manager.exe"
    nsExec::ExecToStack '"$INSTDIR\AGY Plugin Manager.exe" --stop'
    Pop $0
    Pop $1
  ${EndIf}
  nsExec::ExecToStack 'taskkill /F /IM "AGY Plugin Manager.exe"'
  Pop $0
  Pop $1
  Sleep 400

  ; Clean up legacy Inno Setup / PyInstaller _internal leftovers when upgrading in-place
  ; Never touch user configuration (plugins.json) or installed plugins (plugins\)
  ${If} ${FileExists} "$INSTDIR\_internal\*.*"
    RMDir /r "$INSTDIR\_internal"
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\assets\*.*"
    RMDir /r "$INSTDIR\assets"
  ${EndIf}
  Delete "$INSTDIR\unins000.exe"
  Delete "$INSTDIR\unins000.dat"
  Delete "$INSTDIR\unins000.msg"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\{8E9B7D4A-4B3C-4C12-9F5E-1A2B3C4D5E6F}_is1"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Silently create Desktop shortcuts for both AGY Plugin Manager.lnk and Antigravity (AGY-Launcher).lnk
  ${If} ${FileExists} "$INSTDIR\AGY Plugin Manager.exe"
    nsExec::ExecToStack '"$INSTDIR\AGY Plugin Manager.exe" --shortcut'
    Pop $0
    Pop $1
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ${If} ${FileExists} "$INSTDIR\AGY Plugin Manager.exe"
    nsExec::ExecToStack '"$INSTDIR\AGY Plugin Manager.exe" --stop'
    Pop $0
    Pop $1
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$DESKTOP\Antigravity (AGY-Launcher).lnk"
!macroend
