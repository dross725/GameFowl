#!/usr/bin/env python3
"""Create or compare a SHA-256 inventory of deployable project files."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator


INVENTORY_VERSION = 1
SKIP_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "staticfiles",
    "media",
    "logs",
    "htmlcov",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "__pycache__",
    "tests",
}
EXCLUDE_GLOBS = (
    ".env",
    ".env.*",
    ".gitignore",
    "db.sqlite3",
    "db.sqlite3-journal",
    "master_lock.state",
    "master_lock.state.lock",
    "**/master_lock.state",
    "**/*.master_lock.*.tmp",
    "**/*.pyc",
    "**/*.pyo",
    "**/*.log",
    "**/test_*.py",
    "deploy/sync_config.env",
    "deploy/.deploy-last-sync",
    "deploy/.last_sync_manifest",
    "deploy/.last_applied_usb_release.json",
    "deploy/python_path.txt",
)


class InventoryError(RuntimeError):
    pass


def normalize_rel_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_safe_inventory_path(value: str) -> bool:
    normalized = normalize_rel_path(value)
    path = PurePosixPath(normalized)
    return bool(
        normalized
        and not normalized.startswith("/")
        and ":" not in normalized
        and ".." not in path.parts
        and not any(part in SKIP_DIRECTORY_NAMES for part in path.parts[:-1])
        and not any(fnmatch.fnmatch(normalized, pattern) for pattern in EXCLUDE_GLOBS)
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_inventory_files(root: Path) -> Iterator[tuple[str, Path]]:
    root = root.resolve()
    for current, directory_names, file_names in os.walk(root):
        current_path = Path(current)
        relative_dir = current_path.relative_to(root)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in SKIP_DIRECTORY_NAMES
            and is_safe_inventory_path((relative_dir / name / "_").as_posix())
        )
        for name in sorted(file_names):
            full_path = current_path / name
            rel_path = full_path.relative_to(root).as_posix()
            if full_path.is_file() and not full_path.is_symlink() and is_safe_inventory_path(rel_path):
                yield rel_path, full_path


def collect_inventory(root: Path) -> dict[str, dict[str, int | str]]:
    if not root.is_dir():
        raise InventoryError(f"Project directory does not exist: {root}")
    files: dict[str, dict[str, int | str]] = {}
    for rel_path, full_path in iter_inventory_files(root):
        stat = full_path.stat()
        files[rel_path] = {
            "sha256": sha256_file(full_path),
            "size": stat.st_size,
        }
    return files


def write_inventory(root: Path, output: Path) -> dict[str, Any]:
    files = collect_inventory(root)
    inventory = {
        "inventory_version": INVENTORY_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(root.resolve()),
        "file_count": len(files),
        "files": files,
    }
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return inventory


def load_inventory(path: Path) -> dict[str, Any]:
    try:
        inventory = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"Cannot read inventory {path}: {exc}") from exc
    if inventory.get("inventory_version") != INVENTORY_VERSION:
        raise InventoryError(
            f"Unsupported inventory version: {inventory.get('inventory_version')!r}"
        )
    if not isinstance(inventory.get("files"), dict):
        raise InventoryError("Inventory has no valid files map.")
    for rel_path, details in inventory["files"].items():
        if not is_safe_inventory_path(str(rel_path)):
            raise InventoryError(f"Inventory contains an unsafe path: {rel_path!r}")
        if not isinstance(details, dict) or not isinstance(details.get("sha256"), str):
            raise InventoryError(f"Inventory contains invalid file details: {rel_path!r}")
    return inventory


def compare_inventory(root: Path, inventory_path: Path) -> tuple[list[str], list[str], list[str]]:
    server = load_inventory(inventory_path)["files"]
    local = collect_inventory(root)
    added = sorted(path for path in local if path not in server)
    changed = sorted(
        path
        for path in local.keys() & server.keys()
        if local[path]["sha256"].lower() != server[path]["sha256"].lower()
    )
    deleted = sorted(path for path in server if path not in local)
    return added, changed, deleted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot", help="Write an inventory JSON file.")
    snapshot.add_argument("--root", type=Path, required=True, help="Project directory to inventory.")
    snapshot.add_argument("--output", type=Path, required=True, help="Inventory JSON output path.")

    compare = subparsers.add_parser("compare", help="Compare an inventory with local files.")
    compare.add_argument("--root", type=Path, required=True, help="Local project directory.")
    compare.add_argument("--inventory", type=Path, required=True, help="Server inventory JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "snapshot":
            inventory = write_inventory(args.root, args.output)
            print(f"Wrote {inventory['file_count']} file hashes to {args.output.resolve()}")
            return 0

        added, changed, deleted = compare_inventory(args.root, args.inventory)
        for label, paths in (("ADD", added), ("UPDATE", changed), ("DELETE", deleted)):
            for path in paths:
                print(f"{label:6} {path}")
        print(f"\nSummary: {len(added)} add, {len(changed)} update, {len(deleted)} delete")
        return 0
    except InventoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
