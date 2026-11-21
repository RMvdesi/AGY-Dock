!include "LogicLib.nsh"

Var AgyLauncherFinishCheckbox
Var AgyLegacyDetected
Var AgyLegacyInstallDir
Var AgyLegacyBinaryName

; Detect legacy AGY Plugin Manager installs before the Welcome and Directory pages render.
!macroundef MUI_PAGE_WELCOME
!macro MUI_PAGE_WELCOME
  !ifdef MUI_PAGE_CUSTOMFUNCTION_PRE
    !undef MUI_PAGE_CUSTOMFUNCTION_PRE
  !endif
  !define MUI_PAGE_CUSTOMFUNCTION_PRE AgyPreWelcome
  !insertmacro MUI_PAGE_INIT
  !insertmacro MUI_PAGEDECLARATION_WELCOME

  Function AgyDetectLegacyInstall
    ${If} $AgyLegacyDetected = 1
      Return
    ${EndIf}
    StrCpy $AgyLegacyDetected 1
    StrCpy $AgyLegacyInstallDir ""
    StrCpy $AgyLegacyBinaryName ""

    ReadRegStr $AgyLegacyInstallDir SHCTX "Software\${MANUFACTURER}\AGY Plugin Manager" ""
    ${If} $AgyLegacyInstallDir == ""
      ReadRegStr $AgyLegacyInstallDir SHCTX "Software\Microsoft\Windows\CurrentVersion\Uninstall\AGY Plugin Manager" "InstallLocation"
    ${EndIf}
    ${If} $AgyLegacyInstallDir == ""
      ReadRegStr $AgyLegacyInstallDir HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\{8E9B7D4A-4B3C-4C12-9F5E-1A2B3C4D5E6F}_is1" "InstallLocation"
    ${EndIf}

    ; Normalize quotes and trailing slashes from Uninstall\InstallLocation strings.
    ${If} $AgyLegacyInstallDir != ""
      StrCpy $0 $AgyLegacyInstallDir 1
      ${If} $0 == '"'
        StrCpy $AgyLegacyInstallDir $AgyLegacyInstallDir "" 1
      ${EndIf}
      StrCpy $0 $AgyLegacyInstallDir 1 -1
      ${If} $0 == '"'
        StrCpy $AgyLegacyInstallDir $AgyLegacyInstallDir -1
      ${EndIf}
      StrLen $1 $AgyLegacyInstallDir
      ${If} $1 > 3
        StrCpy $0 $AgyLegacyInstallDir 1 -1
        ${If} $0 == "\"
          StrCpy $AgyLegacyInstallDir $AgyLegacyInstallDir -1
        ${EndIf}
      ${EndIf}
    ${EndIf}

    ${If} $AgyLegacyInstallDir == ""
      ${If} ${FileExists} "$LOCALAPPDATA\AGY-Plugin-Manager\AGY Plugin Manager.exe"
      ${OrIf} ${FileExists} "$LOCALAPPDATA\AGY-Plugin-Manager\agy-plugin-manager.exe"
        StrCpy $AgyLegacyInstallDir "$LOCALAPPDATA\AGY-Plugin-Manager"
      ${EndIf}
    ${EndIf}

    ReadRegStr $AgyLegacyBinaryName SHCTX "Software\Microsoft\Windows\CurrentVersion\Uninstall\AGY Plugin Manager" "MainBinaryName"
    ${If} $AgyLegacyBinaryName == ""
      StrCpy $AgyLegacyBinaryName "AGY Plugin Manager.exe"
    ${EndIf}

    ReadRegStr $0 SHCTX "${MANUPRODUCTKEY}" ""
    ${If} $0 == ""
    ${AndIf} $INSTDIR == "$LOCALAPPDATA\${PRODUCTNAME}"
    ${AndIf} $AgyLegacyInstallDir != ""
      StrCpy $INSTDIR $AgyLegacyInstallDir
    ${EndIf}
  FunctionEnd

  Function AgyCollapseNestedLegacyInstallDir
    StrCpy $1 $INSTDIR "" -9
    ${If} $1 == "\AGY Dock"
      StrCpy $0 $INSTDIR -9
      ${IfNot} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
        ${If} ${FileExists} "$0\AGY Plugin Manager.exe"
        ${OrIf} ${FileExists} "$0\agy-plugin-manager.exe"
          StrCpy $INSTDIR $0
        ${EndIf}
      ${EndIf}
    ${EndIf}
  FunctionEnd

  Function AgyPreWelcome
    Call AgyDetectLegacyInstall
    Call SkipIfPassive
  FunctionEnd
!macroend

; Prevent NSIS directory browsing from appending "\AGY Dock" inside an existing AGY Plugin Manager folder.
!macroundef MUI_PAGE_DIRECTORY
!macro MUI_PAGE_DIRECTORY
  !ifdef MUI_PAGE_CUSTOMFUNCTION_LEAVE
    !undef MUI_PAGE_CUSTOMFUNCTION_LEAVE
  !endif
  !define MUI_PAGE_CUSTOMFUNCTION_LEAVE AgyLeaveDirectory
  !insertmacro MUI_PAGE_INIT
  !insertmacro MUI_PAGEDECLARATION_DIRECTORY

  Function AgyLeaveDirectory
    Call AgyCollapseNestedLegacyInstallDir
  FunctionEnd
!macroend

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

!macro NSIS_HOOK_PREINSTALL
  Call AgyDetectLegacyInstall
  Call AgyCollapseNestedLegacyInstallDir
  SetOutPath $INSTDIR

  ; Gracefully stop managed plugins and any running manager process before replacing binaries
  ${If} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
    nsExec::ExecToStack '"$INSTDIR\${MAINBINARYNAME}.exe" --stop'
    Pop $0
    Pop $1
  ${ElseIf} ${FileExists} "$INSTDIR\AGY Plugin Manager.exe"
    nsExec::ExecToStack '"$INSTDIR\AGY Plugin Manager.exe" --stop'
    Pop $0
    Pop $1
  ${ElseIf} ${FileExists} "$INSTDIR\agy-plugin-manager.exe"
    nsExec::ExecToStack '"$INSTDIR\agy-plugin-manager.exe" --stop'
    Pop $0
    Pop $1
  ${ElseIf} $AgyLegacyBinaryName != ""
  ${AndIf} ${FileExists} "$INSTDIR\$AgyLegacyBinaryName"
    nsExec::ExecToStack '"$INSTDIR\$AgyLegacyBinaryName" --stop'
    Pop $0
    Pop $1
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\AGY Plugin Manager.exe"
    !insertmacro CheckIfAppIsRunning "$INSTDIR\AGY Plugin Manager.exe" "AGY Plugin Manager"
    Delete "$INSTDIR\AGY Plugin Manager.exe"
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\agy-plugin-manager.exe"
    !insertmacro CheckIfAppIsRunning "$INSTDIR\agy-plugin-manager.exe" "AGY Plugin Manager"
    Delete "$INSTDIR\agy-plugin-manager.exe"
  ${EndIf}
  ${If} $AgyLegacyBinaryName != ""
  ${AndIf} $AgyLegacyBinaryName != "${MAINBINARYNAME}.exe"
  ${AndIf} $AgyLegacyBinaryName != "AGY Plugin Manager.exe"
  ${AndIf} $AgyLegacyBinaryName != "agy-plugin-manager.exe"
  ${AndIf} ${FileExists} "$INSTDIR\$AgyLegacyBinaryName"
    !insertmacro CheckIfAppIsRunning "$INSTDIR\$AgyLegacyBinaryName" "AGY Plugin Manager"
    Delete "$INSTDIR\$AgyLegacyBinaryName"
  ${EndIf}

  ; If upgrading into a different folder, clean up only legacy binaries from the previous install folder
  ; and never remove user configuration (plugins.json) or installed plugins (plugins\)
  ${If} $AgyLegacyInstallDir != ""
  ${AndIf} $AgyLegacyInstallDir != $INSTDIR
    ${If} ${FileExists} "$AgyLegacyInstallDir\AGY Plugin Manager.exe"
      nsExec::ExecToStack '"$AgyLegacyInstallDir\AGY Plugin Manager.exe" --stop'
      Pop $0
      Pop $1
      !insertmacro CheckIfAppIsRunning "$AgyLegacyInstallDir\AGY Plugin Manager.exe" "AGY Plugin Manager"
      Delete "$AgyLegacyInstallDir\AGY Plugin Manager.exe"
    ${EndIf}
    ${If} ${FileExists} "$AgyLegacyInstallDir\agy-plugin-manager.exe"
      nsExec::ExecToStack '"$AgyLegacyInstallDir\agy-plugin-manager.exe" --stop'
      Pop $0
      Pop $1
      !insertmacro CheckIfAppIsRunning "$AgyLegacyInstallDir\agy-plugin-manager.exe" "AGY Plugin Manager"
      Delete "$AgyLegacyInstallDir\agy-plugin-manager.exe"
    ${EndIf}
    ${If} $AgyLegacyBinaryName != ""
    ${AndIf} $AgyLegacyBinaryName != "AGY Plugin Manager.exe"
    ${AndIf} $AgyLegacyBinaryName != "agy-plugin-manager.exe"
    ${AndIf} ${FileExists} "$AgyLegacyInstallDir\$AgyLegacyBinaryName"
      !insertmacro CheckIfAppIsRunning "$AgyLegacyInstallDir\$AgyLegacyBinaryName" "AGY Plugin Manager"
      Delete "$AgyLegacyInstallDir\$AgyLegacyBinaryName"
    ${EndIf}
    Delete "$AgyLegacyInstallDir\uninstall.exe"
    Delete "$AgyLegacyInstallDir\plugins.example.json"
    RMDir "$AgyLegacyInstallDir"
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

  ; Remove legacy AGY Plugin Manager registry entries so Installed Apps shows only AGY Dock
  DeleteRegKey SHCTX "Software\Microsoft\Windows\CurrentVersion\Uninstall\AGY Plugin Manager"
  DeleteRegKey SHCTX "Software\${MANUFACTURER}\AGY Plugin Manager"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "AGY Plugin Manager"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Clean up legacy Start Menu shortcuts from AGY Plugin Manager
  ${If} ${FileExists} "$SMPROGRAMS\AGY Plugin Manager.lnk"
    !insertmacro UnpinShortcut "$SMPROGRAMS\AGY Plugin Manager.lnk"
    Delete "$SMPROGRAMS\AGY Plugin Manager.lnk"
  ${EndIf}
  ${If} ${FileExists} "$SMPROGRAMS\AGY Plugin Manager\AGY Plugin Manager.lnk"
    !insertmacro UnpinShortcut "$SMPROGRAMS\AGY Plugin Manager\AGY Plugin Manager.lnk"
    Delete "$SMPROGRAMS\AGY Plugin Manager\AGY Plugin Manager.lnk"
    RMDir "$SMPROGRAMS\AGY Plugin Manager"
  ${EndIf}

  ; Migrate or remove legacy Desktop shortcut
  ${If} ${FileExists} "$DESKTOP\AGY Plugin Manager.lnk"
    ${If} ${FileExists} "$DESKTOP\${PRODUCTNAME}.lnk"
      !insertmacro UnpinShortcut "$DESKTOP\AGY Plugin Manager.lnk"
      Delete "$DESKTOP\AGY Plugin Manager.lnk"
    ${Else}
      !insertmacro SetShortcutTarget "$DESKTOP\AGY Plugin Manager.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
      Rename "$DESKTOP\AGY Plugin Manager.lnk" "$DESKTOP\${PRODUCTNAME}.lnk"
    ${EndIf}
  ${EndIf}

  ; Unconditionally repair Antigravity (AGY-Launcher).lnk when migrating from legacy binary names
  ${If} ${FileExists} "$DESKTOP\Antigravity (AGY-Launcher).lnk"
    StrCpy $4 0
    !insertmacro IsShortcutTarget "$DESKTOP\Antigravity (AGY-Launcher).lnk" "$INSTDIR\AGY Plugin Manager.exe"
    Pop $0
    ${If} $0 = 1
      StrCpy $4 1
    ${EndIf}
    ${If} $4 = 0
      !insertmacro IsShortcutTarget "$DESKTOP\Antigravity (AGY-Launcher).lnk" "$INSTDIR\agy-plugin-manager.exe"
      Pop $0
      ${If} $0 = 1
        StrCpy $4 1
      ${EndIf}
    ${EndIf}
    ${If} $4 = 0
    ${AndIf} $AgyLegacyInstallDir != ""
      !insertmacro IsShortcutTarget "$DESKTOP\Antigravity (AGY-Launcher).lnk" "$AgyLegacyInstallDir\AGY Plugin Manager.exe"
      Pop $0
      ${If} $0 = 1
        StrCpy $4 1
      ${EndIf}
      ${If} $4 = 0
        !insertmacro IsShortcutTarget "$DESKTOP\Antigravity (AGY-Launcher).lnk" "$AgyLegacyInstallDir\agy-plugin-manager.exe"
        Pop $0
        ${If} $0 = 1
          StrCpy $4 1
        ${EndIf}
      ${EndIf}
    ${EndIf}
    ${If} $4 = 0
    ${AndIf} $OldMainBinaryName != ""
    ${AndIf} $OldMainBinaryName != "${MAINBINARYNAME}.exe"
      !insertmacro IsShortcutTarget "$DESKTOP\Antigravity (AGY-Launcher).lnk" "$INSTDIR\$OldMainBinaryName"
      Pop $0
      ${If} $0 = 1
        StrCpy $4 1
      ${EndIf}
    ${EndIf}
    ${If} $4 = 1
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
