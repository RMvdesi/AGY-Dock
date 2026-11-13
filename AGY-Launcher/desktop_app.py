from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Use FreeType font engine on Windows to avoid jagged GDI over-sharpening while keeping static UI fonts
os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from desktop.core import CREATE_NO_WINDOW, AgyProcessManager, _is_pid_alive
from desktop.main_window import MainWindow

IPC_SERVER_NAME = "agy-plugin-manager-desktop-ipc"


def notify_existing_instance(command: str = "SHOW") -> bool:
    """Connects to an already-running instance via local IPC socket if present."""
    socket = QLocalSocket()
    socket.connectToServer(IPC_SERVER_NAME)
    if not socket.waitForConnected(250):
        return False
    socket.write(command.encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(250)
    socket.disconnectFromServer()
    return True


def run_gui(manager: AgyProcessManager) -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("AGY Plugin Manager")
    app.setQuitOnLastWindowClosed(False)

    base_font = QFont("Microsoft YaHei UI", 9)
    base_font.setFamilies(["Microsoft YaHei UI", "Segoe UI"])
    base_font.setPointSize(9)
    base_font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    base_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality)
    app.setFont(base_font)

    if notify_existing_instance("SHOW"):
        return 0

    QLocalServer.removeServer(IPC_SERVER_NAME)
    ipc_server = QLocalServer(app)
    ipc_server.listen(IPC_SERVER_NAME)

    icon_path = manager.paths.assets_dir / "assets" / "app.ico"
    png_path = manager.paths.assets_dir / "assets" / "app.png"
    icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
    if png_path.exists():
        icon.addFile(str(png_path))
    app.setWindowIcon(icon)

    window = MainWindow(manager, icon)

    def handle_ipc() -> None:
        conn = ipc_server.nextPendingConnection()
        if not conn:
            return
        if conn.waitForReadyRead(200):
            cmd = bytes(conn.readAll()).decode("utf-8", errors="ignore").strip()
            if cmd == "SHOW":
                window.show_and_raise()
        conn.disconnectFromServer()

    ipc_server.newConnection.connect(handle_ipc)
    window.show()
    return app.exec()


def _spawn_detached_exit_watcher(manager: AgyProcessManager) -> None:
    """Spawns a single lightweight headless exit watcher if the GUI isn't already supervising."""
    if getattr(sys, "frozen", False):
        cmd = [str(Path(sys.executable).resolve()), "--watch-exit"]
    else:
        python_dir = Path(sys.executable).parent
        pythonw = python_dir / "pythonw.exe"
        exe = str(pythonw if pythonw.exists() else Path(sys.executable))
        script = str(Path(__file__).resolve())
        cmd = [exe, script, "--watch-exit"]
    subprocess.Popen(
        cmd,
        cwd=str(manager.paths.plugins_dir.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def run_watch_exit(manager: AgyProcessManager) -> int:
    """Waits in the background until Antigravity main exits, then cleans residual processes & plugins."""
    pid_file = manager.paths.logs_dir / ".watch_exit.pid"
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text(encoding="utf-8").strip())
            if old_pid != os.getpid() and _is_pid_alive(old_pid):
                return 0
        except Exception:
            pass
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    try:
        # Wait up to 30s for Antigravity main window to appear
        saw_main = False
        appear_deadline = time.monotonic() + 30.0
        while time.monotonic() < appear_deadline:
            if notify_existing_instance("PING"):
                return 0
            info = manager.get_active_cdp_info()
            if int(info.get("mainProcessCount") or 0) > 0:
                saw_main = True
                break
            time.sleep(1.5)

        if not saw_main:
            return 0

        while True:
            time.sleep(3.0)
            if notify_existing_instance("PING"):
                # Desktop GUI/tray took over lifecycle monitoring.
                return 0
            info = manager.get_active_cdp_info()
            if int(info.get("mainProcessCount") or 0) == 0:
                time.sleep(2.5)
                confirm = manager.get_active_cdp_info()
                if int(confirm.get("mainProcessCount") or 0) == 0:
                    cfg = manager.load_config()
                    if cfg.get("lifecycle", {}).get("autoCleanupOnExit", True) is not False:
                        manager.cleanup_antigravity_residuals()
                    return 0
    finally:
        try:
            if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
                pid_file.unlink(missing_ok=True)
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="AGY Plugin Manager Native Desktop App")
    parser.add_argument("--quick-launch", action="store_true", help="Headless launch Antigravity and attach plugins")
    parser.add_argument("--attach", action="store_true", help="Headless attach enabled plugins")
    parser.add_argument("--stop", action="store_true", help="Headless stop all managed plugins")
    parser.add_argument("--cleanup", action="store_true", help="Clean up residual Antigravity processes & plugins")
    parser.add_argument("--watch-exit", action="store_true", help="Wait for Antigravity exit and clean up residuals")
    parser.add_argument("--shortcut", action="store_true", help="Create desktop shortcuts and exit")
    args = parser.parse_args()

    base_dir = None if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    manager = AgyProcessManager(base_dir=base_dir)

    if args.quick_launch:
        try:
            manager.launch_antigravity_and_attach(focus_if_running=True)
            cfg = manager.load_config()
            if cfg.get("lifecycle", {}).get("autoCleanupOnExit", True) is not False and not notify_existing_instance("PING"):
                _spawn_detached_exit_watcher(manager)
            return 0
        except Exception as exc:
            manager.log(f"快速启动失败: {exc}", "ERROR")
            if getattr(sys, "frozen", False):
                try:
                    import ctypes
                    ctypes.windll.user32.MessageBoxW(0, str(exc), "AGY Plugin Manager - 启动失败", 0x10)
                except Exception:
                    pass
            else:
                print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    if args.attach:
        try:
            manager.attach_enabled_plugins()
            return 0
        except Exception as exc:
            manager.log(f"热附着失败: {exc}", "ERROR")
            if not getattr(sys, "frozen", False):
                print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    if args.stop:
        manager.stop_all_plugins()
        return 0
    if args.cleanup:
        print(manager.cleanup_antigravity_residuals())
        return 0
    if args.watch_exit:
        return run_watch_exit(manager)
    if args.shortcut:
        res = manager.create_all_shortcuts()
        print(res)
        return 0

    return run_gui(manager)


if __name__ == "__main__":
    raise SystemExit(main())
