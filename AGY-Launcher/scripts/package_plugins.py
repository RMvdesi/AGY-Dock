from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LAUNCHER_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REPOSITORY = "haoan33/AGY-Plugin-Manager"
DEFAULT_RELEASE_TAG = "v2.2.1"

VALID_PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-_]{1,63}$")
PLUGIN_DIR_REF_RE = re.compile(
    r"(?:^|[\\/])plugins[\\/]([a-z0-9][a-z0-9._-]{0,63})(?:[\\/]|$)",
    re.IGNORECASE,
)

SKIP_DIR_NAMES = {"logs", "__pycache__", ".git", ".pytest_cache", ".vscode", ".idea"}
SKIP_FILE_NAMES = {".ds_store", "thumbs.db", "agy-plugin.json"}
SKIP_FILE_SUFFIXES = {".pid", ".log", ".pyc", ".pyo"}
KNOWN_FALLBACK_VERSIONS = {
    "antigravity-hans": "0.4.10",
}


def _extract_author(value: Any) -> str:
    """Extracts an author name from either a string or an npm-style object."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("name") or "").strip()
    return ""


def _normalize_repo_url(raw: str) -> str:
    url = raw.strip()
    if not url:
        return ""
    if url.startswith("git+"):
        url = url[4:]
    if url.endswith(".git") and ("github.com/" in url or "gitlab.com/" in url):
        url = url[:-4]
    if url.startswith("github:"):
        url = "https://github.com/" + url[len("github:") :].lstrip("/")
    return url


def _extract_homepage(data: dict[str, Any]) -> str:
    """Extracts homepage or repository URL from a plugin metadata JSON object."""
    homepage = data.get("homepage")
    if isinstance(homepage, str) and homepage.strip():
        return homepage.strip()
    repo = data.get("repository")
    if isinstance(repo, str) and repo.strip():
        return _normalize_repo_url(repo)
    if isinstance(repo, dict):
        repo_url = repo.get("url")
        if isinstance(repo_url, str) and repo_url.strip():
            return _normalize_repo_url(repo_url)
    return ""


def read_plugin_dir_manifest(plugin_dir: Path | None) -> dict[str, str]:
    """Reads name, version, description, author, and homepage from a plugin directory."""
    meta = {
        "name": "",
        "version": "",
        "description": "",
        "author": "",
        "homepage": "",
    }
    if plugin_dir is None or not plugin_dir.is_dir():
        return meta

    for filename in ("package.json", "plugin.json", "manifest.json", "version.json"):
        candidate = plugin_dir / filename
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if not meta["version"] and isinstance(data.get("version"), str):
            meta["version"] = data["version"].strip()
        if not meta["name"] and isinstance(data.get("name"), str):
            meta["name"] = data["name"].strip()
        if not meta["description"] and isinstance(data.get("description"), str):
            meta["description"] = data["description"].strip()
        if not meta["author"]:
            meta["author"] = _extract_author(data.get("author"))
        if not meta["homepage"]:
            meta["homepage"] = _extract_homepage(data)

    if not meta["version"]:
        ver_file = plugin_dir / "VERSION"
        if ver_file.is_file():
            try:
                for line in ver_file.read_text(encoding="utf-8-sig").splitlines():
                    stripped = line.strip()
                    if stripped:
                        meta["version"] = stripped
                        break
            except Exception:
                pass

    return meta


def resolve_plugin_dir(launcher_dir: Path, entry: dict[str, Any] | None) -> Path | None:
    """Resolves the plugin directory under AGY-Launcher/plugins/ for a config entry."""
    if not entry:
        return None
    plugins_root = launcher_dir / "plugins"
    if not plugins_root.is_dir():
        return None

    pid = str(entry.get("id") or "").strip()
    if pid:
        direct = plugins_root / pid
        if direct.is_dir():
            return direct

    tokens: list[str] = [str(entry.get("command") or "")]
    for key in ("launchArgs", "attachArgs"):
        values = entry.get(key)
        if isinstance(values, list):
            tokens.extend(str(item) for item in values)
    process_match = entry.get("processMatch")
    if isinstance(process_match, str):
        tokens.append(process_match)

    for token in tokens:
        match = PLUGIN_DIR_REF_RE.search(token.strip())
        if match:
            candidate = plugins_root / match.group(1)
            if candidate.is_dir():
                return candidate
    return None


def _has_npm_dependencies(plugin_dir: Path) -> bool:
    pkg_json = plugin_dir / "package.json"
    if not pkg_json.is_file():
        return False
    try:
        data = json.loads(pkg_json.read_text(encoding="utf-8-sig"))
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


def _compute_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(entry: dict[str, Any], plugin_dir: Path) -> tuple[dict[str, Any], str]:
    """Builds a unified agy-plugin.json manifest and archive filename version suffix."""
    plugin_id = str(entry.get("id") or "").strip()
    if not VALID_PLUGIN_ID_RE.match(plugin_id):
        raise ValueError(f"Invalid plugin id: {plugin_id!r}")

    dir_meta = read_plugin_dir_manifest(plugin_dir)
    discovered_version = str(entry.get("version") or dir_meta.get("version") or "").strip()
    manifest_version = discovered_version or KNOWN_FALLBACK_VERSIONS.get(plugin_id, "")
    author = _extract_author(entry.get("author")) or dir_meta.get("author", "")
    homepage = str(entry.get("homepage") or dir_meta.get("homepage") or "").strip()

    launch_args = [str(x) for x in (entry.get("launchArgs") or [])]
    attach_args = [str(x) for x in (entry.get("attachArgs") or launch_args)]
    stop_args = [str(x) for x in (entry.get("stopArgs") or [])]

    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "id": plugin_id,
        "name": str(entry.get("name") or dir_meta.get("name") or plugin_id).strip(),
        "version": manifest_version,
    }
    if author:
        manifest["author"] = author
    manifest["description"] = str(entry.get("description") or dir_meta.get("description") or "").strip()
    if homepage:
        manifest["homepage"] = homepage
    manifest.update(
        {
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
    )
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
        return {
            "path": str(zip_path),
            "filename": zip_path.name,
            "files": len(names),
            "size": zip_path.stat().st_size,
            "sha256": _compute_sha256(zip_path),
            "manifest": manifest,
        }


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
    verified = verify_package_zip(zip_path)
    verified["changelog"] = str(entry.get("changelog") or "").strip()
    return verified


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


def build_catalog(
    results: list[dict[str, Any]],
    repository: str = DEFAULT_REPOSITORY,
    release_tag: str = DEFAULT_RELEASE_TAG,
    omit_sha256: bool = False,
) -> dict[str, Any]:
    """Builds a GitHub remote marketplace catalog payload (schemaVersion: 1)."""
    repo = repository.strip().strip("/") or DEFAULT_REPOSITORY
    tag = release_tag.strip() or DEFAULT_RELEASE_TAG
    plugins: list[dict[str, Any]] = []

    for item in results:
        manifest = item["manifest"]
        filename = item["filename"]
        plugins.append(
            {
                "id": manifest["id"],
                "name": manifest.get("name") or manifest["id"],
                "version": manifest.get("version") or "",
                "author": manifest.get("author") or "",
                "description": manifest.get("description") or "",
                "type": manifest.get("type") or "custom-cdp",
                "downloadUrl": f"https://github.com/{repo}/releases/download/{tag}/{filename}",
                "homepage": manifest.get("homepage") or f"https://github.com/{repo}",
                "changelog": item.get("changelog") or "",
                "sha256": "" if omit_sha256 else item["sha256"],
                "size": item["size"],
                "releaseTag": tag,
            }
        )

    return {
        "schemaVersion": 1,
        "repository": repo,
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plugins": plugins,
    }


def write_catalog_atomic(catalog_path: Path, catalog: dict[str, Any]) -> Path:
    """Writes plugins-catalog.json atomically via temporary file replacement."""
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = catalog_path.with_name(f".{catalog_path.name}.tmp")
    tmp_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(catalog_path)
    return catalog_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build unified AGY plugin .zip packages")
    parser.add_argument("--launcher-dir", type=Path, default=LAUNCHER_DIR, help="Path to AGY-Launcher directory")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory for .zip packages")
    parser.add_argument("--plugin", action="append", default=[], help="Optional plugin ID(s) to package")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Optional output path for GitHub marketplace catalog (e.g. ../plugins-catalog.json)",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPOSITORY,
        help=f"GitHub owner/repo for release download URLs (default: {DEFAULT_REPOSITORY})",
    )
    parser.add_argument(
        "--release-tag",
        default=DEFAULT_RELEASE_TAG,
        help=f"GitHub release tag hosting the .zip assets (default: {DEFAULT_RELEASE_TAG})",
    )
    parser.add_argument(
        "--omit-sha256",
        action="store_true",
        help="Leave sha256 empty in catalog entries (use when referencing historical release assets)",
    )
    args = parser.parse_args()

    only_ids = {p.strip() for p in args.plugin if p.strip()} or None
    results = package_all_plugins(
        launcher_dir=args.launcher_dir.resolve(),
        output_dir=args.output_dir.resolve() if args.output_dir else None,
        only_ids=only_ids,
    )
    for item in results:
        manifest = item["manifest"]
        size_kb = item["size"] / 1024.0
        author_label = manifest.get("author") or "unknown"
        print(
            f"[OK] {item['filename']} | id={manifest['id']} "
            f"v{manifest['version'] or 'unversioned'} | author={author_label} "
            f"| files={item['files']} | {size_kb:.1f} KB"
        )

    if args.catalog is not None:
        catalog = build_catalog(
            results,
            repository=args.repo,
            release_tag=args.release_tag,
            omit_sha256=args.omit_sha256,
        )
        out_path = write_catalog_atomic(args.catalog.resolve(), catalog)
        print(
            f"[OK] catalog -> {out_path} | repo={catalog['repository']} "
            f"| tag={args.release_tag} | plugins={len(catalog['plugins'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
