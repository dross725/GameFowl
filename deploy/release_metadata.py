"""Canonical release metadata shared by USB, VPN, and inventory packages."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


PACKAGE_VERSION = 2
REQUIRED_PYTHON = "3.12"
PRINT_AGENT_MIN_VERSION = "1.13.10-receipt-center"
SUPPORTED_PACKAGE_VERSIONS = {1, 2}

_AGENT_VERSION_RE = re.compile(r"^AGENT_VERSION\s*=\s*\"([^\"]+)\"", re.MULTILINE)
_VERSION_PREFIX_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def migration_sort_key(name: str) -> tuple:
    head = (name or "").split("_", 1)[0]
    if head.isdigit():
        return (int(head), name)
    return (10**9, name or "")


def version_key(value: str) -> tuple[int, int, int]:
    match = _VERSION_PREFIX_RE.search(value or "")
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_agent_compatible(reported: str, minimum: str = PRINT_AGENT_MIN_VERSION) -> bool:
    if not reported:
        return False
    return version_key(reported) >= version_key(minimum)


def outdated_agents(reports: list[dict], minimum: str = PRINT_AGENT_MIN_VERSION) -> list[dict]:
    outdated = []
    for report in reports:
        version = str(report.get("version") or "")
        if not is_agent_compatible(version, minimum):
            outdated.append(
                {
                    "host": str(report.get("host") or ""),
                    "version": version,
                    "minimum": minimum,
                }
            )
    return outdated


def read_app_version(project_root: Path) -> str:
    path = project_root / "VERSION"
    if not path.is_file():
        return "unknown"
    version = path.read_text(encoding="utf-8").strip()
    return version or "unknown"


def migration_names(project_root: Path) -> list[str]:
    folder = project_root / "SmartWagers" / "migrations"
    if not folder.is_dir():
        return []
    names = [
        path.stem
        for path in folder.glob("*.py")
        if path.name != "__init__.py" and path.stem.split("_", 1)[0].isdigit()
    ]
    return sorted(names, key=migration_sort_key)


def read_print_agent_version(project_root: Path) -> str:
    path = project_root / "local_print_agent" / "print_agent.py"
    if not path.is_file():
        return ""
    match = _AGENT_VERSION_RE.search(path.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def compose_package_metadata(
    *,
    files: list[str],
    deleted_files: list[str],
    checksums: dict[str, str],
    base_ref: str | None,
    head_ref: str | None,
    requires_dependencies: bool,
    artifact_kind: str,
    project_root: Path,
    collectstatic: bool | None = None,
    migrate: bool | None = None,
) -> dict:
    """Build release.json contents. Checksums are stored but this dict is not hashed."""
    migrations = migration_names(project_root)
    schema_level = migrations[-1] if migrations else ""
    full_snapshot = artifact_kind == "full"
    needs_migrate = bool(migrations) if migrate is None and full_snapshot else bool(migrate)
    if migrate is None and not full_snapshot:
        needs_migrate = any(path.startswith("SmartWagers/migrations/") for path in files)
    needs_static = True if collectstatic is None and full_snapshot else bool(collectstatic)
    if collectstatic is None and not full_snapshot:
        needs_static = any(
            "/static/" in f"/{path}" or "/templates/" in f"/{path}" or path.endswith((".js", ".css", ".html"))
            for path in files
        )
    commit_sha = head_ref or ""
    return {
        "package_version": PACKAGE_VERSION,
        "artifact_kind": artifact_kind,
        "app_version": read_app_version(project_root),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_ref": base_ref,
        "head_ref": head_ref,
        "commit_sha": commit_sha,
        "required_python": REQUIRED_PYTHON,
        "schema_level": schema_level,
        "min_schema": migrations[0] if full_snapshot and migrations else "",
        "max_schema": schema_level,
        "allow_from_any_older": full_snapshot,
        "migrations": migrations if full_snapshot else [
            Path(path).stem
            for path in files
            if path.startswith("SmartWagers/migrations/") and path.endswith(".py")
        ],
        "files": files,
        "deleted_files": deleted_files,
        "requires_dependencies": requires_dependencies,
        "requires_migrate": needs_migrate,
        "requires_collectstatic": needs_static,
        "requires_restart": True,
        "print_agent_version": read_print_agent_version(project_root),
        "print_agent_min_version": PRINT_AGENT_MIN_VERSION,
        "checksums": checksums,
    }


def assert_supported_package(metadata: dict) -> None:
    version = metadata.get("package_version")
    if version not in SUPPORTED_PACKAGE_VERSIONS:
        raise ValueError(f"Unsupported package version: {version!r}")


def assert_schema_compatible(current_schema: str | None, metadata: dict) -> None:
    """Reject downgrades and releases that skip below their declared minimum."""
    schema_level = str(metadata.get("schema_level") or "")
    min_schema = str(metadata.get("min_schema") or "")
    if not current_schema or not schema_level:
        return
    if migration_sort_key(current_schema) > migration_sort_key(schema_level):
        raise ValueError(
            f"Refusing schema downgrade from {current_schema} to {schema_level}."
        )
    allow_any_older = bool(metadata.get("allow_from_any_older"))
    if min_schema and not allow_any_older and migration_sort_key(current_schema) < migration_sort_key(min_schema):
        raise ValueError(
            f"Refusing unsafe migration skip from {current_schema}; "
            f"this release requires at least {min_schema}."
        )
