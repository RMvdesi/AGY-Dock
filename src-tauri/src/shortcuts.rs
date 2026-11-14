use crate::config::{load_config, save_config};
use crate::models::ShortcutResult;
use crate::paths::{resolve_desktop_dir, ManagerPaths};
use std::path::{Path, PathBuf};

#[cfg(windows)]
use windows::core::{Interface, HSTRING, PCWSTR};
#[cfg(windows)]
use windows::Win32::Foundation::RPC_E_CHANGED_MODE;
#[cfg(windows)]
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CoUninitialize, IPersistFile, CLSCTX_INPROC_SERVER,
    COINIT_APARTMENTTHREADED,
};
#[cfg(windows)]
use windows::Win32::UI::Shell::{IShellLinkW, ShellLink};

#[cfg(windows)]
fn create_shortcut_com(
    shortcut_path: &Path,
    target_path: &str,
    arguments: &str,
    working_dir: &str,
    icon_path: &str,
    description: &str,
) -> Result<(), String> {
    if let Some(parent) = shortcut_path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("创建快捷方式目录失败: {e}"))?;
    }

    unsafe {
        let hr = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
        let should_uninit = hr.is_ok();
        if hr.is_err() && hr != RPC_E_CHANGED_MODE {
            return Err(format!("初始化 COM 失败: {hr:?}"));
        }

        let res = (|| -> Result<(), String> {
            let shell_link: IShellLinkW = CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER)
                .map_err(|e| format!("创建 ShellLink COM 对象失败: {e}"))?;

            let w_target = HSTRING::from(target_path);
            shell_link
                .SetPath(PCWSTR(w_target.as_ptr()))
                .map_err(|e| format!("设置快捷方式 TargetPath 失败: {e}"))?;

            if !arguments.is_empty() {
                let w_args = HSTRING::from(arguments);
                shell_link
                    .SetArguments(PCWSTR(w_args.as_ptr()))
                    .map_err(|e| format!("设置快捷方式 Arguments 失败: {e}"))?;
            }

            if !working_dir.is_empty() {
                let w_cwd = HSTRING::from(working_dir);
                shell_link
                    .SetWorkingDirectory(PCWSTR(w_cwd.as_ptr()))
                    .map_err(|e| format!("设置快捷方式 WorkingDirectory 失败: {e}"))?;
            }

            if !icon_path.is_empty() && Path::new(icon_path).exists() {
                let w_icon = HSTRING::from(icon_path);
                shell_link
                    .SetIconLocation(PCWSTR(w_icon.as_ptr()), 0)
                    .map_err(|e| format!("设置快捷方式图标失败: {e}"))?;
            }

            if !description.is_empty() {
                let w_desc = HSTRING::from(description);
                shell_link
                    .SetDescription(PCWSTR(w_desc.as_ptr()))
                    .map_err(|e| format!("设置快捷方式描述失败: {e}"))?;
            }

            let persist: IPersistFile = shell_link
                .cast()
                .map_err(|e| format!("获取 IPersistFile 接口失败: {e}"))?;
            let w_lnk = HSTRING::from(shortcut_path.as_os_str());
            persist
                .Save(PCWSTR(w_lnk.as_ptr()), true)
                .map_err(|e| format!("保存快捷方式文件失败: {e}"))?;
            Ok(())
        })();

        if should_uninit {
            CoUninitialize();
        }
        res
    }
}

#[cfg(not(windows))]
fn create_shortcut_com(
    _shortcut_path: &Path,
    _target_path: &str,
    _arguments: &str,
    _working_dir: &str,
    _icon_path: &str,
    _description: &str,
) -> Result<(), String> {
    Err("仅支持 Windows 平台创建 .lnk 快捷方式".to_string())
}

fn find_manager_icon(paths: &ManagerPaths, launcher_exe: &str) -> String {
    let candidates = [
        paths.assets_dir.join("assets").join("app.ico"),
        paths.assets_dir.join("icons").join("icon.ico"),
        PathBuf::from(launcher_exe)
            .parent()
            .map(|p| p.join("icons").join("icon.ico"))
            .unwrap_or_default(),
        PathBuf::from(launcher_exe),
    ];
    for cand in candidates {
        if !cand.as_os_str().is_empty() && cand.is_file() {
            return cand.to_string_lossy().into_owned();
        }
    }
    String::new()
}

pub fn create_all_shortcuts(paths: &ManagerPaths) -> Result<ShortcutResult, String> {
    let config = load_config(paths)?;
    let launcher_exe = std::env::current_exe()
        .map_err(|e| format!("无法获取当前程序路径: {e}"))?
        .to_string_lossy()
        .into_owned();

    let desktop_dir = resolve_desktop_dir();
    let working_dir = paths.data_dir.to_string_lossy().into_owned();
    let app_icon = find_manager_icon(paths, &launcher_exe);
    let agy_icon = config.antigravity_exe.trim().to_string();

    let manager_lnk = desktop_dir.join("AGY Plugin Manager.lnk");
    create_shortcut_com(
        &manager_lnk,
        &launcher_exe,
        "",
        &working_dir,
        &app_icon,
        "打开 AGY Plugin Manager 原生桌面控制中心",
    )?;
    paths.log_info(&format!("已生成桌面快捷方式: {}", manager_lnk.display()));

    let agy_lnk = desktop_dir.join("Antigravity (AGY-Launcher).lnk");
    create_shortcut_com(
        &agy_lnk,
        &launcher_exe,
        "--quick-launch",
        &working_dir,
        if !agy_icon.is_empty() && Path::new(&agy_icon).exists() {
            &agy_icon
        } else {
            &app_icon
        },
        "无黑框启动 Antigravity 并静默加载托管插件",
    )?;
    paths.log_info(&format!("已生成桌面快捷方式: {}", agy_lnk.display()));

    Ok(ShortcutResult {
        manager_shortcut: manager_lnk.to_string_lossy().into_owned(),
        agy_shortcut: agy_lnk.to_string_lossy().into_owned(),
    })
}

pub fn ensure_default_shortcuts_once(paths: &ManagerPaths) -> Result<bool, String> {
    let mut cfg = load_config(paths)?;
    if cfg.ui.shortcuts_initialized == Some(true) {
        return Ok(false);
    }

    let desktop_dir = resolve_desktop_dir();
    let agy_lnk = desktop_dir.join("Antigravity (AGY-Launcher).lnk");
    let mgr_lnk = desktop_dir.join("AGY Plugin Manager.lnk");
    if agy_lnk.exists() && mgr_lnk.exists() {
        cfg.ui.shortcuts_initialized = Some(true);
        save_config(paths, &cfg)?;
        return Ok(false);
    }

    let exe = cfg.antigravity_exe.trim();
    if exe.is_empty() || !Path::new(exe).exists() {
        return Ok(false);
    }

    let _ = create_all_shortcuts(paths)?;
    cfg.ui.shortcuts_initialized = Some(true);
    save_config(paths, &cfg)?;
    paths.log_info("已首次自动补充生成 Antigravity (AGY-Launcher) 与控制中心桌面快捷方式");
    Ok(true)
}
