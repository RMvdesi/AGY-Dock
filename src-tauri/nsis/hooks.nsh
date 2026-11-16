!include "LogicLib.nsh"

Var AgyLauncherFinishCheckbox

; Tauri declares the finish page after this hook is included. Wrap only that MUI2
; page so its existing manager and run options retain their original handlers.
!macroundef MUI_PAGE_FINISH
!macro MUI_PAGE_FINISH
  !define MUI_PAGE_CUSTOMFUNCTION_SHOW AgyShowLauncherOption
  !define MUI_PAGE_CUSTOMFUNCTION_LEAVE AgyApplyFinishPage
  !insertmacro MUI_PAGE_INIT
  !insertmacro MUI_PAGEDECLARATION_FINISH

  Function AgyShowLauncherOption
    StrCpy $AgyLauncherFinishCheckbox 0
    ${If} ${RebootFlag}
    ${OrIf} $NoShortcutMode = 1
    ${OrIf} $UpdateMode = 1
      Return
    ${EndIf}

    StrCpy $0 "Create AGY Launcher desktop shortcut"
    ${If} $LANGUAGE = 2052
      StrCpy $0 "创建 AGY Launcher 桌面快捷方式"
    ${EndIf}
    ; MUI2 places Run at 90u and the manager desktop shortcut at 110u.
    ${NSD_CreateCheckbox} 120u 130u 195u 10u "$0"
    Pop $AgyLauncherFinishCheckbox
    ${NSD_Check} $AgyLauncherFinishCheckbox
    SetCtlColors $AgyLauncherFinishCheckbox "${MUI_TEXTCOLOR}" "${MUI_BGCOLOR}"
  FunctionEnd

  Function AgyApplyFinishPage
    StrCpy $0 ${BST_UNCHECKED}
    ${If} $AgyLauncherFinishCheckbox != 0
      ${NSD_GetState} $AgyLauncherFinishCheckbox $0
    ${EndIf}
    Call AgyApplyShortcutChoice
  FunctionEnd

  Function AgyApplyShortcutChoice
    StrCpy $1 ""
    ${If} $0 = ${BST_CHECKED}
    ${AndIf} $NoShortcutMode != 1
    ${AndIf} $UpdateMode != 1
      StrCpy $1 "--create-agy-launcher"
    ${EndIf}
    ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --finish-install $1' $0
    ${If} $0 != 0
      DetailPrint "Could not apply AGY Launcher shortcut choice (exit code $0)"
    ${EndIf}
  FunctionEnd
!macroend

; Match local hot-sync default install directory (%LOCALAPPDATA%\AGY-Plugin-Manager)
InstallDir "$LOCALAPPDATA\AGY-Plugin-Manager"

!macro NSIS_HOOK_PREINSTALL
  ; Normalize default install path if Tauri's template defaulted to productName ("AGY Plugin Manager")
  ${If} $INSTDIR == "$LOCALAPPDATA\AGY Plugin Manager"
    StrCpy $INSTDIR "$LOCALAPPDATA\AGY-Plugin-Manager"
  ${EndIf}

  ; Gracefully stop managed plugins and any running manager process before replacing binaries
  ${If} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
    nsExec::ExecToStack '"$INSTDIR\${MAINBINARYNAME}.exe" --stop'
    Pop $0
    Pop $1
  ${ElseIf} ${FileExists} "$INSTDIR\agy-plugin-manager.exe"
    nsExec::ExecToStack '"$INSTDIR\agy-plugin-manager.exe" --stop'
    Pop $0
    Pop $1
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\agy-plugin-manager.exe"
    !insertmacro CheckIfAppIsRunning "$INSTDIR\agy-plugin-manager.exe" "${PRODUCTNAME}"
  ${EndIf}

  ; Clean up legacy Inno Setup / PyInstaller _internal and removed bundled plugin-packages leftovers
  ; Never touch user configuration (plugins.json) or installed plugins (plugins\)
  ${If} ${FileExists} "$INSTDIR\_internal\*.*"
    RMDir /r "$INSTDIR\_internal"
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\assets\*.*"
    RMDir /r "$INSTDIR\assets"
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\plugin-packages\*.*"
    RMDir /r "$INSTDIR\plugin-packages"
  ${EndIf}
  Delete "$INSTDIR\unins000.exe"
  Delete "$INSTDIR\unins000.dat"
  Delete "$INSTDIR\unins000.msg"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\{8E9B7D4A-4B3C-4C12-9F5E-1A2B3C4D5E6F}_is1"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Repair an existing launcher link during a filename migration even when
  ; the user chooses to skip creating desktop shortcuts.
  ${If} $OldMainBinaryName == "agy-plugin-manager.exe"
    !insertmacro IsShortcutTarget "$DESKTOP\Antigravity (AGY-Launcher).lnk" "$INSTDIR\$OldMainBinaryName"
    Pop $0
    ${If} $0 = 1
      !insertmacro SetShortcutTarget "$DESKTOP\Antigravity (AGY-Launcher).lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    ${EndIf}
  ${EndIf}
  ${If} $PassiveMode = 1
  ${OrIf} ${Silent}
    StrCpy $0 ${BST_CHECKED}
    Call AgyApplyShortcutChoice
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ${If} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
    nsExec::ExecToStack '"$INSTDIR\${MAINBINARYNAME}.exe" --stop'
    Pop $0
    Pop $1
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$DESKTOP\Antigravity (AGY-Launcher).lnk"
!macroend
