#!/usr/bin/env python3
"""Verify and apply a SmartWagers offline USB release package."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_TARGET = Path(r"C:\SmartWagers\GameFowl")
DEFAULT_LOG = Path(r"C:\SmartWagers\logs\usb_release.log")
PACKAGE_TOOL_FILES = {
    "APPLY_RELEASE.bat",
    "apply_usb_release.py",
    "EXPORT_SERVER_INVENTORY.bat",
    "release_inventory.py",
}
DENY_GLOBS = (
    ".env",
    ".env.*",
    "db.sqlite3",
    "db.sqlite3-journal",
    "master_lock.state",
    "master_lock.state.lock",
    "**/master_lock.state",
    "**/*.master_lock.*.tmp",
    "deploy/sync_config.env",
    "deploy/python_path.txt",
    "deploy/.deploy-last-sync",
    "staticfiles/*",
    "media/*",
    "logs/*",
)


class ReleaseError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help=r"Production project directory (default: C:\SmartWagers\GameFowl).",
    )
    parser.add_argument("--yes", action="store_true", help="Apply without an interactive confirmation.")
    return parser.parse_args()


def append_log(log_path: Path, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    line = f"[{timestamp}] {message}"
    print(message)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(line + "\n")


def normalize_rel_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def validate_rel_path(value: str) -> str:
    raw = value.strip().replace("\\", "/")
    path = PurePosixPath(raw)
    normalized = normalize_rel_path(raw)
    if (
        not raw
        or raw.startswith("/")
        or ":" in raw
        or raw.startswith("./")
        or ".." in path.parts
        or normalized != raw
        or any(fnmatch.fnmatch(normalized, pattern) for pattern in DENY_GLOBS)
    ):
        raise ReleaseError(f"Unsafe or protected release path: {value!r}")
    return normalized


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_metadata() -> dict[str, Any]:
    metadata_path = PACKAGE_ROOT / "release.json"
    if not metadata_path.is_file():
        raise ReleaseError(f"Release metadata is missing: {metadata_path}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"Cannot read release metadata: {exc}") from exc
    if metadata.get("package_version") != 1:
        raise ReleaseError(f"Unsupported package version: {metadata.get('package_version')!r}")
    return metadata


def verify_package(metadata: dict[str, Any]) -> tuple[list[str], list[str]]:
    files = [validate_rel_path(str(path)) for path in metadata.get("files", [])]
    deleted = [validate_rel_path(str(path)) for path in metadata.get("deleted_files", [])]
    checksums = metadata.get("checksums")
    if not isinstance(checksums, dict) or not checksums:
        raise ReleaseError("Release has no checksum manifest.")

    for rel_path, expected in checksums.items():
        check_path = normalize_rel_path(str(rel_path))
        if check_path.startswith("wheels/"):
            wheel_path = PurePosixPath(check_path)
            if ":" in check_path or ".." in wheel_path.parts or wheel_path.parts[0] != "wheels":
                raise ReleaseError(f"Unsafe wheel path in checksum manifest: {rel_path!r}")
            source = PACKAGE_ROOT / check_path
        elif "/" not in check_path and check_path in PACKAGE_TOOL_FILES:
            source = PACKAGE_ROOT / check_path
        else:
            validate_rel_path(check_path)
            source = PACKAGE_ROOT / "payload" / check_path
        if not source.is_file():
            raise ReleaseError(f"Release file is missing: {source}")
        actual = sha256_file(source)
        if actual.lower() != str(expected).lower():
            raise ReleaseError(f"Checksum mismatch: {source}")

    for rel_path in files:
        if not (PACKAGE_ROOT / "payload" / rel_path).is_file():
            raise ReleaseError(f"Payload file is missing: {rel_path}")
    return files, deleted


def production_python(target: Path) -> Path:
    path_file = target / "deploy" / "python_path.txt"
    if path_file.is_file():
        python_path = Path(path_file.read_text(encoding="utf-8").strip())
        if python_path.is_file():
            return python_path
        raise ReleaseError(f"Production Python recorded in {path_file} does not exist: {python_path}")
    executable = shutil.which("python")
    if not executable:
        raise ReleaseError("Python was not found and deploy/python_path.txt is missing.")
    return Path(executable)


def run_checked(command: list[str], log_path: Path, cwd: Path) -> None:
    append_log(log_path, "RUN " + subprocess.list2cmdline(command))
    result = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)
    if result.stdout:
        for line in result.stdout.rstrip().splitlines():
            append_log(log_path, f"  {line}")
    if result.stderr:
        for line in result.stderr.rstrip().splitlines():
            append_log(log_path, f"  {line}")
    if result.returncode != 0:
        raise ReleaseError(
            f"Command failed with exit code {result.returncode}: {subprocess.list2cmdline(command)}"
        )


def backup_before_migration(target: Path, python_exe: Path, files: list[str], log_path: Path) -> None:
    if not any(path.startswith("SmartWagers/migrations/") for path in files):
        return
    backup_tool = target / "deploy" / "postgres_tools.py"
    if not backup_tool.is_file():
        raise ReleaseError(f"Cannot back up before migration; missing {backup_tool}")
    append_log(log_path, "Migration detected; creating a PostgreSQL backup before copying files.")
    run_checked([str(python_exe), str(backup_tool), "backup"], log_path, target)


def install_dependencies(
    target: Path, python_exe: Path, metadata: dict[str, Any], log_path: Path
) -> None:
    if not metadata.get("requires_dependencies"):
        return
    wheels = PACKAGE_ROOT / "wheels"
    if not wheels.is_dir() or not any(wheels.iterdir()):
        raise ReleaseError("requirements.txt changed, but the package contains no offline wheels.")
    append_log(log_path, "Installing dependencies from the offline wheelhouse.")
    run_checked(
        [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(wheels),
            "--requirement",
            str(target / "requirements.txt"),
        ],
        log_path,
        target,
    )


def apply_release(
    target: Path,
    metadata: dict[str, Any],
    files: list[str],
    deleted: list[str],
    log_path: Path,
) -> None:
    target = target.resolve()
    if not (target / "manage.py").is_file():
        raise ReleaseError(f"Target is not a SmartWagers project directory: {target}")

    python_exe = production_python(target)
    backup_before_migration(target, python_exe, files, log_path)

    for rel_path in files:
        source = PACKAGE_ROOT / "payload" / rel_path
        destination = target / Path(*PurePosixPath(rel_path).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        append_log(log_path, f"COPIED {rel_path}")

    for rel_path in deleted:
        destination = target / Path(*PurePosixPath(rel_path).parts)
        if destination.is_file() or destination.is_symlink():
            destination.unlink()
            append_log(log_path, f"DELETED {rel_path}")

    apply_manifest = sorted(set(files) | set(deleted))
    manifest = target / "deploy" / ".last_sync_manifest"
    manifest.write_text(
        "\n".join(apply_manifest) + ("\n" if apply_manifest else ""),
        encoding="utf-8",
    )

    install_dependencies(target, python_exe, metadata, log_path)

    apply_script = target / "deploy" / "11_apply_release.bat"
    if not apply_script.is_file():
        raise ReleaseError(f"Server apply script is missing: {apply_script}")
    run_checked(["cmd.exe", "/c", str(apply_script)], log_path, target)

    head_ref = metadata.get("head_ref")
    if head_ref:
        (target / "deploy" / ".deploy-last-sync").write_text(str(head_ref) + "\n", encoding="utf-8")
    shutil.copy2(PACKAGE_ROOT / "release.json", target / "deploy" / ".last_applied_usb_release.json")
    append_log(log_path, f"APPLIED release {head_ref or 'working-tree'}")


def main() -> int:
    args = parse_args()
    target = args.target.expanduser()
    log_path = DEFAULT_LOG
    try:
        metadata = load_metadata()
        files, deleted = verify_package(metadata)
        append_log(log_path, f"Verified USB release at {PACKAGE_ROOT}")
        print(f"\nTarget: {target}")
        print(f"Files to copy: {len(files)}")
        print(f"Files to delete: {len(deleted)}")
        print(f"Source commit: {metadata.get('head_ref') or 'unavailable'}")
        if not args.yes:
            confirmation = input("\nType APPLY to continue: ").strip()
            if confirmation != "APPLY":
                print("Release cancelled; no files were changed.")
                return 1
        apply_release(target, metadata, files, deleted, log_path)
        return 0
    except (OSError, ReleaseError) as exc:
        append_log(log_path, f"ERROR {exc}")
        print("The database backup (if created) and the USB package can be used for recovery.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
