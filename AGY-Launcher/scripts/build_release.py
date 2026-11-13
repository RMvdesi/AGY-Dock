from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

LAUNCHER_DIR = Path(__file__).resolve().parent.parent


def read_manager_version(launcher_dir: Path = LAUNCHER_DIR) -> str:
    server_mjs = launcher_dir / "server.mjs"
    if server_mjs.is_file():
        text = server_mjs.read_text(encoding="utf-8")
        match = re.search(r"const\s+VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
        if match:
            return match.group(1).strip()
    return "2.0.0"


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"[RUN] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), check=True)


def build_desktop_onedir(launcher_dir: Path, dist_dir: Path, build_dir: Path) -> Path:
    icon_path = launcher_dir / "assets" / "app.ico"
    assets_dir = launcher_dir / "assets"
    example_cfg = launcher_dir / "plugins.example.json"
    if not icon_path.is_file():
        raise FileNotFoundError(f"Missing icon file: {icon_path}")
    if not example_cfg.is_file():
        raise FileNotFoundError(f"Missing template config: {example_cfg}")

    raw_app_dir = dist_dir / "AGY Plugin Manager"
    target_app_dir = dist_dir / "AGY-Plugin-Manager"
    for path in (raw_app_dir, target_app_dir):
        if path.exists():
            shutil.rmtree(path)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        "AGY Plugin Manager",
        "--icon",
        str(icon_path),
        "--paths",
        str(launcher_dir),
        "--add-data",
        f"{assets_dir};assets",
        "--add-data",
        f"{example_cfg};.",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir / "app"),
        "--specpath",
        str(build_dir),
        str(launcher_dir / "desktop_app.py"),
    ]
    _run(cmd, cwd=launcher_dir)

    if not raw_app_dir.is_dir():
        raise RuntimeError(f"Expected PyInstaller output missing: {raw_app_dir}")
    raw_app_dir.replace(target_app_dir)

    exe_path = target_app_dir / "AGY Plugin Manager.exe"
    if not exe_path.is_file():
        raise RuntimeError(f"Missing built desktop executable: {exe_path}")

    # Enforce strict decoupling: never ship user plugins/ or personal plugins.json inside app bundle
    for forbidden in (
        target_app_dir / "plugins",
        target_app_dir / "plugins.json",
        target_app_dir / "_internal" / "plugins",
        target_app_dir / "_internal" / "plugins.json",
    ):
        if forbidden.exists():
            raise RuntimeError(f"Decoupling violation: found {forbidden} inside frozen app bundle")

    return target_app_dir


def create_payload_archive(app_dir: Path, payload_zip: Path) -> Path:
    payload_zip.parent.mkdir(parents=True, exist_ok=True)
    tmp_zip = payload_zip.with_suffix(".zip.tmp")
    files = sorted((p for p in app_dir.rglob("*") if p.is_file()), key=lambda p: p.as_posix().lower())
    with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file_path in files:
            rel = file_path.relative_to(app_dir).as_posix()
            zf.write(file_path, arcname=rel)
    tmp_zip.replace(payload_zip)
    return payload_zip


def build_setup_installer(
    launcher_dir: Path,
    dist_dir: Path,
    build_dir: Path,
    payload_zip: Path,
    version: str,
) -> Path:
    icon_path = launcher_dir / "assets" / "app.ico"
    example_cfg = launcher_dir / "plugins.example.json"
    setup_name = f"AGY-Plugin-Manager-Setup-v{version}"
    setup_exe = dist_dir / f"{setup_name}.exe"
    if setup_exe.exists():
        setup_exe.unlink()

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        setup_name,
        "--icon",
        str(icon_path),
        "--paths",
        str(launcher_dir),
        "--exclude-module",
        "PySide6",
        "--exclude-module",
        "shiboken6",
        "--add-data",
        f"{payload_zip};.",
        "--add-data",
        f"{icon_path};assets",
        "--add-data",
        f"{example_cfg};.",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir / "setup"),
        "--specpath",
        str(build_dir),
        str(launcher_dir / "scripts" / "installer_ui.py"),
    ]
    _run(cmd, cwd=launcher_dir)

    if not setup_exe.is_file():
        raise RuntimeError(f"Missing built setup installer: {setup_exe}")
    return setup_exe


def main() -> int:
    parser = argparse.ArgumentParser(description="Build AGY Plugin Manager app bundle and Windows Setup Installer")
    parser.add_argument("--launcher-dir", type=Path, default=LAUNCHER_DIR)
    parser.add_argument("--version", default="", help="Override release version (defaults to server.mjs VERSION)")
    parser.add_argument("--clean", action="store_true", help="Clean build/ and dist/ before building")
    args = parser.parse_args()

    launcher_dir = args.launcher_dir.resolve()
    version = args.version.strip() or read_manager_version(launcher_dir)
    dist_dir = launcher_dir / "dist"
    build_dir = launcher_dir / "build"

    if args.clean:
        for path in (dist_dir, build_dir):
            if path.exists():
                shutil.rmtree(path)

    dist_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)

    app_dir = build_desktop_onedir(launcher_dir, dist_dir, build_dir)
    payload_zip = create_payload_archive(app_dir, build_dir / "payload.zip")
    setup_exe = build_setup_installer(launcher_dir, dist_dir, build_dir, payload_zip, version)

    app_mb = sum(p.stat().st_size for p in app_dir.rglob("*") if p.is_file()) / (1024 * 1024)
    setup_mb = setup_exe.stat().st_size / (1024 * 1024)
    print(f"[OK] Desktop bundle : {app_dir} ({app_mb:.1f} MB)")
    print(f"[OK] Setup installer: {setup_exe} ({setup_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
