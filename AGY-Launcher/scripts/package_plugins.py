from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

LAUNCHER_DIR = Path(__file__).resolve().parent.parent
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))

from desktop.core import VALID_PLUGIN_ID_RE, read_plugin_dir_manifest, resolve_plugin_dir

SKIP_DIR_NAMES = {"logs", "__pycache__", ".git", ".pytest_cache", ".vscode", ".idea"}
SKIP_FILE_NAMES = {".ds_store", "thumbs.db", "agy-plugin.json"}
SKIP_FILE_SUFFIXES = {".pid", ".log", ".pyc", ".pyo"}
KNOWN_FALLBACK_VERSIONS = {
    "antigravity-hans": "0.4.10",
}


def _has_npm_dependencies(plugin_dir: Path) -> bool:
    pkg_json = plugin_dir / "package.json"
    if not pkg_json.is_file():
        return False
    try:
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
    except Exception:
        return False
    deps = data.get("dependencies")
    return isinstance(deps, dict) and len(deps) > 0


def _should_skip_relative(rel_path: Path, skip_node_modules: bool) -> bool:
    parts = rel_path.parts
    for part in parts[:-1]:
        lower = part.lower()
        if lower in SKIP_DIR_NAMES:
            return True
        if skip_node_modules and lower == "node_modules":
            return True
    name_lower = rel_path.name.lower()
    if name_lower in SKIP_FILE_NAMES:
        return True
    if rel_path.suffix.lower() in SKIP_FILE_SUFFIXES:
        return True
    return False


def build_manifest(entry: dict[str, Any], plugin_dir: Path) -> tuple[dict[str, Any], str]:
    """Builds a unified agy-plugin.json manifest and archive filename version suffix."""
    plugin_id = str(entry.get("id") or "").strip()
    if not VALID_PLUGIN_ID_RE.match(plugin_id):
        raise ValueError(f"Invalid plugin id: {plugin_id!r}")

    dir_meta = read_plugin_dir_manifest(plugin_dir)
    discovered_version = str(entry.get("version") or dir_meta.get("version") or "").strip()
    manifest_version = discovered_version or KNOWN_FALLBACK_VERSIONS.get(plugin_id, "")

    launch_args = [str(x) for x in (entry.get("launchArgs") or [])]
    attach_args = [str(x) for x in (entry.get("attachArgs") or launch_args)]
    stop_args = [str(x) for x in (entry.get("stopArgs") or [])]

    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "id": plugin_id,
        "name": str(entry.get("name") or dir_meta.get("name") or plugin_id).strip(),
        "version": manifest_version,
        "description": str(entry.get("description") or dir_meta.get("description") or "").strip(),
        "type": str(entry.get("type") or "custom-cdp").strip(),
        "command": str(entry.get("command") or "").strip(),
        "launchArgs": launch_args,
        "attachArgs": attach_args,
        "stopArgs": stop_args,
        "healthUrl": str(entry.get("healthUrl") or "").strip(),
        "processMatch": str(entry.get("processMatch") or "").strip(),
        "enabled": bool(entry.get("enabled", True)),
        "autoAttach": bool(entry.get("autoAttach", True)),
    }
    if not manifest["command"]:
        raise ValueError(f"Plugin {plugin_id!r} is missing required 'command' field.")
    return manifest, discovered_version


def verify_package_zip(zip_path: Path) -> dict[str, Any]:
    """Validates ZIP archive integrity, Zip-Slip safety, and agy-plugin.json schema."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        corrupted = zf.testzip()
        if corrupted is not None:
            raise ValueError(f"Corrupted ZIP entry {corrupted!r} in {zip_path}")
        names = zf.namelist()
        if "agy-plugin.json" not in names:
            raise ValueError(f"Missing agy-plugin.json at root of {zip_path}")
        for name in names:
            if name.startswith("/") or name.startswith("\\") or ":" in name:
                raise ValueError(f"Unsafe absolute/drive path {name!r} in {zip_path}")
            norm_parts = [p for p in name.replace("\\", "/").split("/") if p]
            if ".." in norm_parts:
                raise ValueError(f"Path traversal entry {name!r} in {zip_path}")
        manifest = json.loads(zf.read("agy-plugin.json").decode("utf-8"))
        if manifest.get("schemaVersion") != 1:
            raise ValueError(f"Unsupported schemaVersion in {zip_path}: {manifest.get('schemaVersion')!r}")
        if not VALID_PLUGIN_ID_RE.match(str(manifest.get("id") or "")):
            raise ValueError(f"Invalid manifest id in {zip_path}: {manifest.get('id')!r}")
        if not str(manifest.get("command") or "").strip():
            raise ValueError(f"Empty manifest command in {zip_path}")
        return {"path": str(zip_path), "files": len(names), "manifest": manifest}


def package_single_plugin(
    launcher_dir: Path,
    entry: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Packages a single configured plugin directory into a self-contained .zip archive."""
    plugin_id = str(entry.get("id") or "").strip()
    plugin_dir = resolve_plugin_dir(launcher_dir, entry) or (launcher_dir / "plugins" / plugin_id)
    if not plugin_dir.is_dir():
        raise FileNotFoundError(f"Plugin directory not found for {plugin_id!r}: {plugin_dir}")

    manifest, archive_version = build_manifest(entry, plugin_dir)
    filename = f"{plugin_id}-v{archive_version}.zip" if archive_version else f"{plugin_id}.zip"
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / filename
    tmp_path = output_dir / f".{filename}.tmp"

    for stale in output_dir.glob(f"{plugin_id}*.zip"):
        if stale != zip_path:
            stale.unlink(missing_ok=True)

    skip_node_modules = not _has_npm_dependencies(plugin_dir)
    files_to_pack = sorted(
        (p for p in plugin_dir.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(plugin_dir).as_posix().lower(),
    )

    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("agy-plugin.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for file_path in files_to_pack:
            rel_path = file_path.relative_to(plugin_dir)
            if _should_skip_relative(rel_path, skip_node_modules=skip_node_modules):
                continue
            zf.write(file_path, arcname=rel_path.as_posix())

    tmp_path.replace(zip_path)
    return verify_package_zip(zip_path)


def package_all_plugins(
    launcher_dir: Path = LAUNCHER_DIR,
    output_dir: Path | None = None,
    only_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Packages all matching plugins from plugins.json into plugin-packages/."""
    config_path = launcher_dir / "plugins.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing plugins.json at {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    target_dir = output_dir or (launcher_dir / "plugin-packages")

    results: list[dict[str, Any]] = []
    for entry in config.get("plugins") or []:
        plugin_id = str(entry.get("id") or "").strip()
        if not plugin_id:
            continue
        if only_ids and plugin_id not in only_ids:
            continue
        results.append(package_single_plugin(launcher_dir, entry, target_dir))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Build unified AGY plugin .zip packages")
    parser.add_argument("--launcher-dir", type=Path, default=LAUNCHER_DIR, help="Path to AGY-Launcher directory")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory for .zip packages")
    parser.add_argument("--plugin", action="append", default=[], help="Optional plugin ID(s) to package")
    args = parser.parse_args()

    only_ids = {p.strip() for p in args.plugin if p.strip()} or None
    results = package_all_plugins(
        launcher_dir=args.launcher_dir.resolve(),
        output_dir=args.output_dir.resolve() if args.output_dir else None,
        only_ids=only_ids,
    )
    for item in results:
        manifest = item["manifest"]
        size_kb = Path(item["path"]).stat().st_size / 1024.0
        print(
            f"[OK] {Path(item['path']).name} | id={manifest['id']} "
            f"v{manifest['version'] or 'unversioned'} | files={item['files']} | {size_kb:.1f} KB"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
