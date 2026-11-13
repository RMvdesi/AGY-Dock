from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any, Callable

# Ensure stdout/stderr are never None in PyInstaller --windowed mode
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
LAUNCHER_DIR = SCRIPT_DIR.parent
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))

from desktop.core import CREATE_NO_WINDOW, _write_json_atomic, detect_antigravity_exe

APP_DISPLAY_NAME = "AGY Plugin Manager"
APP_VERSION = "2.0.0"
APP_EXE_NAME = "AGY Plugin Manager.exe"
SHORTCUT_NAME = "AGY Plugin Manager.lnk"

DEFAULT_CONFIG_TEMPLATE: dict[str, Any] = {
    "managerPort": 12400,
    "antigravityExe": "",
    "antigravityArgs": [],
    "cdpWaitTimeoutSec": 30,
    "proxy": {
        "enabled": False,
        "httpProxy": "",
        "httpsProxy": "",
        "allProxy": "",
        "noProxy": "127.0.0.1,localhost,::1",
        "electronProxyServer": "",
    },
    "lifecycle": {
        "autoCleanupOnExit": True,
        "stopPluginsOnExit": True,
    },
    "plugins": [],
    "ui": {
        "theme": "auto",
        "minimizeToTray": True,
    },
}


def get_bundle_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).resolve()
    return LAUNCHER_DIR


def get_default_install_dir() -> Path:
    local_app = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return (local_app / "AGY-Plugin-Manager").resolve()


def is_temp_path(target: Path) -> bool:
    temp_root = Path(tempfile.gettempdir()).resolve()
    resolved = target.resolve()
    return resolved == temp_root or temp_root in resolved.parents


def load_example_template() -> dict[str, Any]:
    bundle_root = get_bundle_root()
    example_path = bundle_root / "plugins.example.json"
    if example_path.is_file():
        try:
            data = json.loads(example_path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG_TEMPLATE))


def _validate_zip_member(name: str) -> str:
    norm = name.replace("\\", "/").lstrip("/")
    if not norm:
        return ""
    if name.startswith("/") or name.startswith("\\") or ":" in name.split("/", 1)[0]:
        raise ValueError(f"Unsafe archive entry path: {name!r}")
    parts = [p for p in norm.split("/") if p]
    if ".." in parts:
        raise ValueError(f"Zip-Slip path traversal detected: {name!r}")
    return "/".join(parts)


def _extract_payload(payload_zip: Path, dest_dir: Path, progress_cb: Callable[[int, str], None] | None = None) -> int:
    if not payload_zip.is_file():
        raise FileNotFoundError(f"Missing installer payload archive: {payload_zip}")

    with zipfile.ZipFile(payload_zip, "r") as zf:
        members = zf.infolist()
        total = max(len(members), 1)
        extracted_files = 0
        for idx, info in enumerate(members, start=1):
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"Refusing symlink inside payload: {info.filename}")
            rel = _validate_zip_member(info.filename)
            if not rel:
                continue
            target = (dest_dir / rel).resolve()
            if target != dest_dir and dest_dir not in target.parents:
                raise ValueError(f"Path traversal blocked: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, target.open("wb") as dst:
                    while True:
                        chunk = src.read(65536)
                        if not chunk:
                            break
                        dst.write(chunk)
                extracted_files += 1
            if progress_cb and (idx == total or idx % 8 == 0):
                pct = int(10 + (idx / total) * 75)
                progress_cb(pct, f"正在解压程序文件 ({idx}/{total})...")
    return extracted_files


def _initialize_or_preserve_config(dest_dir: Path, antigravity_exe: str) -> tuple[Path, bool]:
    """Creates a clean decoupled plugins.json or preserves existing user config on upgrade."""
    config_path = dest_dir / "plugins.json"
    cleaned_exe = str(antigravity_exe or "").strip()

    if config_path.is_file():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8-sig"))
            if isinstance(existing, dict):
                current_exe = str(existing.get("antigravityExe") or "").strip()
                if cleaned_exe and (not current_exe or not Path(current_exe).is_file()):
                    existing["antigravityExe"] = cleaned_exe
                    _write_json_atomic(config_path, existing)
                return config_path, True
        except Exception:
            backup = dest_dir / "plugins.json.bak"
            try:
                config_path.replace(backup)
            except OSError:
                pass

    cfg = load_example_template()
    cfg["antigravityExe"] = cleaned_exe
    cfg["plugins"] = []
    if not isinstance(cfg.get("proxy"), dict):
        cfg["proxy"] = {"enabled": False}
    else:
        cfg["proxy"]["enabled"] = False
    _write_json_atomic(config_path, cfg)
    return config_path, False


def _create_windows_shortcut(shortcut_path: Path, target_exe: Path, work_dir: Path, description: str) -> str:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)

    def ps_quote(val: str) -> str:
        return "'" + str(val).replace("'", "''") + "'"

    ps_script = f"""
$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut({ps_quote(str(shortcut_path))})
$sc.TargetPath = {ps_quote(str(target_exe))}
$sc.WorkingDirectory = {ps_quote(str(work_dir))}
$sc.IconLocation = {ps_quote(str(target_exe) + ',0')}
$sc.Description = {ps_quote(description)}
$sc.Save()
"""
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
        creationflags=CREATE_NO_WINDOW,
        timeout=10,
        check=True,
    )
    return str(shortcut_path)


def _create_shortcuts(dest_dir: Path, desktop: bool, start_menu: bool) -> dict[str, str]:
    created: dict[str, str] = {}
    exe_path = dest_dir / APP_EXE_NAME
    if desktop:
        desktop_dir = Path("D:/Desktop") if Path("D:/Desktop").exists() else (Path.home() / "Desktop")
        created["desktop"] = _create_windows_shortcut(
            desktop_dir / SHORTCUT_NAME,
            exe_path,
            dest_dir,
            "Open AGY Plugin Manager",
        )
    if start_menu:
        appdata = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        start_dir = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        created["startMenu"] = _create_windows_shortcut(
            start_dir / SHORTCUT_NAME,
            exe_path,
            dest_dir,
            "Open AGY Plugin Manager",
        )
    return created


def _write_uninstall_script(dest_dir: Path) -> Path:
    uninstall_path = dest_dir / "Uninstall.cmd"
    # Pure ASCII batch script: safe across all Windows codepages, no labels inside if (...) blocks.
    content = (
        "@echo off\r\n"
        "setlocal\r\n"
        'set "INSTALL_DIR=%~dp0"\r\n'
        'if "%INSTALL_DIR:~-1%"=="\\" set "INSTALL_DIR=%INSTALL_DIR:~0,-1%"\r\n'
        'echo Stopping AGY Plugin Manager...\r\n'
        f'taskkill /IM "{APP_EXE_NAME}" /F >nul 2>&1\r\n'
        'echo Removing shortcuts...\r\n'
        f'if exist "D:\\Desktop\\{SHORTCUT_NAME}" del /f /q "D:\\Desktop\\{SHORTCUT_NAME}" >nul 2>&1\r\n'
        f'if exist "%USERPROFILE%\\Desktop\\{SHORTCUT_NAME}" del /f /q "%USERPROFILE%\\Desktop\\{SHORTCUT_NAME}" >nul 2>&1\r\n'
        f'if exist "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{SHORTCUT_NAME}" del /f /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{SHORTCUT_NAME}" >nul 2>&1\r\n'
        'cd /d "%LOCALAPPDATA%"\r\n'
        'echo Removing application directory...\r\n'
        'start "" /b cmd /c "ping 127.0.0.1 -n 3 >nul & rmdir /s /q ""%INSTALL_DIR%"""\r\n'
        "exit /b 0\r\n"
    )
    uninstall_path.write_text(content, encoding="ascii")
    return uninstall_path


def launch_installed_app(dest_dir: Path) -> None:
    exe_path = dest_dir / APP_EXE_NAME
    if not exe_path.is_file():
        raise FileNotFoundError(f"Executable not found: {exe_path}")
    subprocess.Popen(
        [str(exe_path)],
        cwd=str(dest_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def perform_install(
    dest_dir: Path,
    antigravity_exe: str = "",
    *,
    create_desktop_shortcut: bool = True,
    create_start_menu_shortcut: bool = True,
    launch_after: bool = False,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    import shutil

    target_dir = Path(dest_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    bundle_root = get_bundle_root()
    payload_zip = bundle_root / "payload.zip"

    if progress_cb:
        progress_cb(5, "正在准备安装目录...")

    internal_dir = target_dir / "_internal"
    if internal_dir.exists():
        shutil.rmtree(internal_dir)

    extracted = _extract_payload(payload_zip, target_dir, progress_cb=progress_cb)
    (target_dir / "plugins").mkdir(parents=True, exist_ok=True)
    (target_dir / "logs").mkdir(parents=True, exist_ok=True)

    if progress_cb:
        progress_cb(88, "正在初始化配置文件...")
    config_path, preserved = _initialize_or_preserve_config(target_dir, antigravity_exe)

    if progress_cb:
        progress_cb(93, "正在生成卸载脚本与快捷方式...")
    uninstall_path = _write_uninstall_script(target_dir)
    shortcuts = _create_shortcuts(
        target_dir,
        desktop=create_desktop_shortcut,
        start_menu=create_start_menu_shortcut,
    )

    if progress_cb:
        progress_cb(100, "安装完成")

    if launch_after:
        launch_installed_app(target_dir)

    return {
        "installDir": str(target_dir),
        "exePath": str(target_dir / APP_EXE_NAME),
        "configPath": str(config_path),
        "preservedConfig": preserved,
        "extractedFiles": extracted,
        "uninstallScript": str(uninstall_path),
        "shortcuts": shortcuts,
        "antigravityExe": str(antigravity_exe or "").strip(),
    }


def run_gui_wizard(initial_dest: Path | None = None) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    root.title(f"{APP_DISPLAY_NAME} v{APP_VERSION} 安装向导")
    root.geometry("620x470")
    root.resizable(False, False)
    root.configure(bg="#F5F7FA")

    ico_path = get_bundle_root() / "assets" / "app.ico"
    if ico_path.is_file():
        try:
            root.iconbitmap(default=str(ico_path))
        except Exception:
            pass

    style = ttk.Style()
    try:
        style.theme_use("vista")
    except Exception:
        pass

    font_family = "Microsoft YaHei UI"
    dest_var = tk.StringVar(value=str(initial_dest or get_default_install_dir()))
    detected = detect_antigravity_exe()
    agy_var = tk.StringVar(value=detected.get("path") or "")
    if detected.get("found"):
        hint_initial = f"已自动检测到 Antigravity ({detected.get('source', 'local')})"
        hint_color = "#047857"
    else:
        hint_initial = "未检测到 Antigravity.exe，可手动浏览选择或稍后在设置中配置"
        hint_color = "#64748B"

    desktop_var = tk.BooleanVar(value=True)
    start_menu_var = tk.BooleanVar(value=True)
    launch_var = tk.BooleanVar(value=True)
    status_var = tk.StringVar(value="准备就绪，点击「立即安装」开始部署。")
    progress_var = tk.IntVar(value=0)

    header = tk.Frame(root, bg="#0F172A", height=84)
    header.pack(fill="x")
    header.pack_propagate(False)
    tk.Label(
        header,
        text=f"{APP_DISPLAY_NAME}  v{APP_VERSION}",
        font=(font_family, 15, "bold"),
        fg="#F8FAFC",
        bg="#0F172A",
    ).pack(anchor="w", padx=24, pady=(16, 2))
    tk.Label(
        header,
        text="Antigravity IDE 独立桌面插件控制中心 · 解耦架构 · 开箱即用",
        font=(font_family, 9),
        fg="#94A3B8",
        bg="#0F172A",
    ).pack(anchor="w", padx=24)

    body = tk.Frame(root, bg="#F5F7FA", padx=24, pady=18)
    body.pack(fill="both", expand=True)

    # Install Directory
    tk.Label(body, text="安装目录", font=(font_family, 9, "bold"), fg="#1E293B", bg="#F5F7FA").pack(anchor="w")
    dest_row = tk.Frame(body, bg="#F5F7FA")
    dest_row.pack(fill="x", pady=(4, 12))
    dest_entry = ttk.Entry(dest_row, textvariable=dest_var, font=(font_family, 9))
    dest_entry.pack(side="left", fill="x", expand=True, ipady=3)

    def browse_dest() -> None:
        chosen = filedialog.askdirectory(title="选择安装目录", initialdir=dest_var.get() or str(Path.home()))
        if chosen:
            dest_var.set(str(Path(chosen) / "AGY-Plugin-Manager") if Path(chosen).name != "AGY-Plugin-Manager" else chosen)

    ttk.Button(dest_row, text="浏览...", command=browse_dest).pack(side="left", padx=(8, 0))

    # Antigravity Exe
    tk.Label(body, text="Antigravity 客户端路径", font=(font_family, 9, "bold"), fg="#1E293B", bg="#F5F7FA").pack(anchor="w")
    agy_row = tk.Frame(body, bg="#F5F7FA")
    agy_row.pack(fill="x", pady=(4, 2))
    agy_entry = ttk.Entry(agy_row, textvariable=agy_var, font=(font_family, 9))
    agy_entry.pack(side="left", fill="x", expand=True, ipady=3)

    agy_hint_label = tk.Label(body, text=hint_initial, font=(font_family, 8), fg=hint_color, bg="#F5F7FA")
    agy_hint_label.pack(anchor="w", pady=(0, 12))

    def run_redetect() -> None:
        res = detect_antigravity_exe()
        if res.get("found"):
            agy_var.set(res["path"])
            agy_hint_label.config(text=f"已自动检测到 Antigravity ({res.get('source', 'local')})", fg="#047857")
        else:
            agy_hint_label.config(text="未检测到 Antigravity.exe，请手动浏览选择", fg="#B45309")

    def browse_agy() -> None:
        chosen = filedialog.askopenfilename(
            title="选择 Antigravity.exe",
            filetypes=[("Antigravity Executable", "Antigravity.exe"), ("Executables", "*.exe"), ("All Files", "*.*")],
        )
        if chosen:
            agy_var.set(chosen)
            agy_hint_label.config(text="已手动指定客户端路径", fg="#1D4ED8")

    ttk.Button(agy_row, text="自动检测", command=run_redetect).pack(side="left", padx=(8, 0))
    ttk.Button(agy_row, text="浏览...", command=browse_agy).pack(side="left", padx=(6, 0))

    # Options
    opts_frame = tk.LabelFrame(body, text=" 安装选项 ", font=(font_family, 9), fg="#334155", bg="#F5F7FA", padx=12, pady=8)
    opts_frame.pack(fill="x", pady=(0, 14))
    tk.Checkbutton(
        opts_frame, text="创建桌面快捷方式 (AGY Plugin Manager)", variable=desktop_var,
        bg="#F5F7FA", activebackground="#F5F7FA", font=(font_family, 9)
    ).pack(anchor="w")
    tk.Checkbutton(
        opts_frame, text="创建开始菜单快捷方式", variable=start_menu_var,
        bg="#F5F7FA", activebackground="#F5F7FA", font=(font_family, 9)
    ).pack(anchor="w")
    tk.Checkbutton(
        opts_frame, text="安装完成后立即启动 AGY Plugin Manager", variable=launch_var,
        bg="#F5F7FA", activebackground="#F5F7FA", font=(font_family, 9, "bold"), fg="#1D4ED8"
    ).pack(anchor="w")

    # Progress & status
    progress_bar = ttk.Progressbar(body, maximum=100, variable=progress_var)
    progress_bar.pack(fill="x", pady=(0, 6))
    status_label = tk.Label(body, textvariable=status_var, font=(font_family, 8), fg="#475569", bg="#F5F7FA")
    status_label.pack(anchor="w")

    # Footer buttons
    footer = tk.Frame(root, bg="#EEF2F6", height=58, padx=24)
    footer.pack(fill="x", side="bottom")
    footer.pack_propagate(False)

    install_btn = tk.Button(
        footer,
        text="立即安装",
        font=(font_family, 9, "bold"),
        bg="#2563EB",
        fg="#FFFFFF",
        activebackground="#1D4ED8",
        activeforeground="#FFFFFF",
        relief="flat",
        padx=18,
        pady=6,
        cursor="hand2",
    )
    cancel_btn = ttk.Button(footer, text="取消", command=root.destroy)
    cancel_btn.pack(side="right", pady=13)
    install_btn.pack(side="right", padx=(0, 10), pady=12)

    installing = {"active": False, "done": False}

    def on_close() -> None:
        if not installing["active"]:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    def start_install() -> None:
        if installing["done"]:
            root.destroy()
            return
        if installing["active"]:
            return
        dest_text = dest_var.get().strip()
        if not dest_text:
            messagebox.showwarning("提示", "请选择有效的安装目录。", parent=root)
            return

        installing["active"] = True
        install_btn.config(state="disabled", text="正在安装...")
        cancel_btn.config(state="disabled")
        dest_entry.config(state="disabled")
        agy_entry.config(state="disabled")

        def worker() -> None:
            try:
                def on_progress(pct: int, msg: str) -> None:
                    root.after(0, lambda p=pct, m=msg: (progress_var.set(p), status_var.set(m)))

                should_launch = bool(launch_var.get())
                perform_install(
                    Path(dest_text),
                    agy_var.get().strip(),
                    create_desktop_shortcut=bool(desktop_var.get()),
                    create_start_menu_shortcut=bool(start_menu_var.get()),
                    launch_after=should_launch,
                    progress_cb=on_progress,
                )

                def on_success() -> None:
                    installing["active"] = False
                    installing["done"] = True
                    progress_var.set(100)
                    if should_launch:
                        status_var.set("安装成功，正在启动 AGY Plugin Manager...")
                        root.after(350, root.destroy)
                    else:
                        status_var.set(f"安装完成！已部署至 {dest_text}")
                        install_btn.config(state="normal", text="完成", bg="#059669")

                root.after(0, on_success)
            except Exception as exc:
                def on_error() -> None:
                    installing["active"] = False
                    install_btn.config(state="normal", text="重试安装")
                    cancel_btn.config(state="normal")
                    dest_entry.config(state="normal")
                    agy_entry.config(state="normal")
                    status_var.set(f"安装失败: {exc}")
                    messagebox.showerror("安装失败", str(exc), parent=root)

                root.after(0, on_error)

        threading.Thread(target=worker, daemon=True).start()

    install_btn.config(command=start_install)
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AGY Plugin Manager Windows Setup Installer")
    parser.add_argument("--silent", action="store_true", help="Run non-interactive silent install")
    parser.add_argument("--dest", type=Path, default=None, help="Target installation directory")
    parser.add_argument("--antigravity-exe", default=None, help="Explicit path to Antigravity.exe")
    parser.add_argument("--shortcuts", action="store_true", help="Force creating Desktop/Start Menu shortcuts in silent mode")
    parser.add_argument("--no-shortcuts", action="store_true", help="Skip creating Desktop/Start Menu shortcuts")
    parser.add_argument("--launch", action="store_true", help="Launch AGY Plugin Manager after silent install")
    args = parser.parse_args()

    if args.silent:
        dest_dir = (args.dest or get_default_install_dir()).expanduser().resolve()
        agy_exe = args.antigravity_exe
        if agy_exe is None:
            agy_exe = detect_antigravity_exe().get("path") or ""

        if args.no_shortcuts:
            create_shortcuts = False
        elif args.shortcuts:
            create_shortcuts = True
        else:
            # Avoid overwriting real user desktop shortcuts during automated temp-dir CI checks
            create_shortcuts = not is_temp_path(dest_dir)

        result = perform_install(
            dest_dir,
            agy_exe,
            create_desktop_shortcut=create_shortcuts,
            create_start_menu_shortcut=create_shortcuts,
            launch_after=bool(args.launch),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    return run_gui_wizard(initial_dest=args.dest)


if __name__ == "__main__":
    raise SystemExit(main())
