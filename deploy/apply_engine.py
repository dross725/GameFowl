"""Staged release apply and rollback shared by USB and VPN deployments.

Files are snapshotted and the database is backed up before changes. The deployed
version marker is written only after readiness succeeds. Any later failure restores
the previous code and database backup.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


DEPLOY_DIR = Path(__file__).resolve().parent
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

from release_metadata import assert_schema_compatible  # noqa: E402


LOCK_STALE_SECONDS = 2 * 60 * 60
HISTORY_KEEP = 2
MIN_FREE_BYTES = 512 * 1024 * 1024
NSSM = Path(r"C:\SmartWagers\nssm\nssm.exe")
SERVICE_NAME = "SmartWagers-Daphne"
DENY_PARTS = {
    ".env",
    ".email_password",
    "db.sqlite3",
    "master_lock.state",
}


class ApplyError(RuntimeError):
    pass


@dataclass
class ApplyResult:
    ok: bool
    stage: str
    message: str
    backup_path: str | None = None
    snapshot_path: str | None = None
    rolled_back: bool = False
    report_path: str | None = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "stage": self.stage,
            "message": self.message,
            "backup_path": self.backup_path,
            "snapshot_path": self.snapshot_path,
            "rolled_back": self.rolled_back,
            "report_path": self.report_path,
        }


@dataclass
class ApplyHooks:
    stop_service: callable = field(default=lambda: None)
    start_service: callable = field(default=lambda: None)
    backup_database: callable = field(default=lambda: None)
    restore_database: callable = field(default=lambda path: None)
    install_dependencies: callable = field(default=lambda: None)
    migrate: callable = field(default=lambda: None)
    collectstatic: callable = field(default=lambda: None)
    readiness: callable = field(default=lambda: None)
    python_version: tuple = field(default_factory=lambda: sys.version_info[:2])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def scrub(text: str) -> str:
    return re.sub(
        r"(?i)(password|secret|token|signing_key|hash)\s*[=:]\s*\S+",
        r"\1=<redacted>",
        text or "",
    )


def validate_rel_path(value: str) -> str:
    raw = str(value).strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if (
        not raw
        or raw.startswith("/")
        or ":" in raw
        or ".." in path.parts
        or path.name in DENY_PARTS
        or raw.startswith(".env")
        or "master_lock.state" in raw
        or raw.startswith("staticfiles/")
        or raw.startswith("logs/")
        or raw.startswith("media/")
    ):
        raise ApplyError(f"Unsafe or protected release path: {value!r}")
    return raw


def _lock_path(target: Path) -> Path:
    return target / "deploy" / ".deploy.lock"


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


@contextmanager
def deployment_lock(target: Path):
    path = _lock_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = _read_json(path)
        started = existing.get("started_at") or ""
        age = LOCK_STALE_SECONDS + 1
        try:
            started_at = datetime.fromisoformat(started)
            age = (datetime.now(timezone.utc) - started_at).total_seconds()
        except ValueError:
            age = LOCK_STALE_SECONDS + 1
        if age < LOCK_STALE_SECONDS:
            raise ApplyError(
                f"Another deployment is in progress (lock {path}). "
                "Wait for it to finish or remove the lock only after confirming it is stale."
            )
    path.write_text(
        json.dumps({"pid": os.getpid(), "started_at": _now()}) + "\n",
        encoding="utf-8",
    )
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def assert_disk_space(path: Path, minimum_bytes: int) -> None:
    anchor = path if path.exists() else path.parent
    free = shutil.disk_usage(anchor).free
    if free < minimum_bytes:
        raise ApplyError(
            f"Insufficient disk space: {free} bytes free, {minimum_bytes} bytes required."
        )


def assert_python_version(actual: tuple, required: str) -> None:
    parts = str(required).split(".")
    if len(parts) < 2 or not all(part.isdigit() for part in parts[:2]):
        raise ApplyError(f"Release required_python is invalid: {required!r}")
    expected = (int(parts[0]), int(parts[1]))
    actual_pair = (int(actual[0]), int(actual[1]))
    if actual_pair != expected:
        raise ApplyError(
            f"Python {actual_pair[0]}.{actual_pair[1]} does not match required {expected[0]}.{expected[1]}."
        )


def current_schema(target: Path) -> str | None:
    document = _read_json(target / "deploy" / ".deployed_release.json")
    schema = str(document.get("schema_level") or "").strip()
    return schema or None


def _history_root(target: Path) -> Path:
    return target.parent / "release_history"


def snapshot_code(target: Path, files: list[str], deleted: list[str], snapshot_dir: Path) -> dict:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"files": [], "created": [], "deleted_existed": []}
    for rel_path in files:
        destination = target / Path(*PurePosixPath(rel_path).parts)
        if destination.is_file():
            stored = snapshot_dir / "files" / Path(*PurePosixPath(rel_path).parts)
            stored.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, stored)
            manifest["files"].append(rel_path)
        else:
            manifest["created"].append(rel_path)
    for rel_path in deleted:
        destination = target / Path(*PurePosixPath(rel_path).parts)
        if destination.is_file():
            stored = snapshot_dir / "deleted" / Path(*PurePosixPath(rel_path).parts)
            stored.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, stored)
            manifest["deleted_existed"].append(rel_path)
    (snapshot_dir / "snapshot.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def restore_snapshot(target: Path, snapshot_dir: Path) -> None:
    manifest = _read_json(snapshot_dir / "snapshot.json")
    for rel_path in manifest.get("files", []):
        source = snapshot_dir / "files" / Path(*PurePosixPath(rel_path).parts)
        destination = target / Path(*PurePosixPath(rel_path).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for rel_path in manifest.get("created", []):
        destination = target / Path(*PurePosixPath(rel_path).parts)
        if destination.is_file() or destination.is_symlink():
            destination.unlink()
    for rel_path in manifest.get("deleted_existed", []):
        source = snapshot_dir / "deleted" / Path(*PurePosixPath(rel_path).parts)
        destination = target / Path(*PurePosixPath(rel_path).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def copy_payload(package_root: Path, target: Path, files: list[str], deleted: list[str]) -> None:
    for rel_path in files:
        source = package_root / "payload" / Path(*PurePosixPath(rel_path).parts)
        if not source.is_file():
            raise ApplyError(f"Payload file is missing: {rel_path}")
        destination = target / Path(*PurePosixPath(rel_path).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for rel_path in deleted:
        destination = target / Path(*PurePosixPath(rel_path).parts)
        if destination.is_file() or destination.is_symlink():
            destination.unlink()


def prune_history(target: Path, keep: int = HISTORY_KEEP) -> None:
    root = _history_root(target)
    if not root.is_dir():
        return
    snapshots = sorted(path for path in root.iterdir() if path.is_dir())
    for obsolete in snapshots[:-keep]:
        shutil.rmtree(obsolete, ignore_errors=True)


def required_free_bytes(package_root: Path, minimum_free_bytes: int | None) -> int:
    if minimum_free_bytes is not None:
        return minimum_free_bytes
    payload = package_root / "payload"
    size = 0
    if payload.is_dir():
        for path in payload.rglob("*"):
            if path.is_file():
                size += path.stat().st_size
    return max(MIN_FREE_BYTES, size * 3)


def _write_report(target: Path, result: ApplyResult) -> Path:
    path = target / "deploy" / ".last_deploy_failure.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.as_dict(), indent=2) + "\n", encoding="utf-8")
    result.report_path = str(path)
    return path


def _same_release(target: Path, metadata: dict) -> bool:
    current = _read_json(target / "deploy" / ".deployed_release.json")
    incoming = str(metadata.get("commit_sha") or metadata.get("head_ref") or "")
    schema = str(metadata.get("schema_level") or "")
    if not incoming or not current:
        return False
    return current.get("commit_sha") == incoming and str(current.get("schema_level") or "") == schema


def _write_success_marker(
    target: Path,
    metadata: dict,
    *,
    backup_path: Path | None,
    snapshot_path: Path,
    previous: dict,
) -> None:
    deploy = target / "deploy"
    deploy.mkdir(parents=True, exist_ok=True)
    marker = {
        "ok": True,
        "app_version": metadata.get("app_version"),
        "commit_sha": metadata.get("commit_sha") or metadata.get("head_ref"),
        "head_ref": metadata.get("head_ref"),
        "schema_level": metadata.get("schema_level"),
        "min_schema": metadata.get("min_schema"),
        "max_schema": metadata.get("max_schema"),
        "artifact_kind": metadata.get("artifact_kind"),
        "print_agent_version": metadata.get("print_agent_version"),
        "print_agent_min_version": metadata.get("print_agent_min_version"),
        "applied_at": _now(),
        "backup_path": str(backup_path) if backup_path else "",
        "snapshot_path": str(snapshot_path),
        "previous": previous,
    }
    (deploy / ".deployed_release.json").write_text(
        json.dumps(marker, indent=2) + "\n",
        encoding="utf-8",
    )
    head_ref = metadata.get("head_ref")
    if head_ref:
        (deploy / ".deploy-last-sync").write_text(str(head_ref) + "\n", encoding="utf-8")
    package_root = Path(str(metadata.get("_package_root") or ""))
    release_json = package_root / "release.json"
    if release_json.is_file():
        shutil.copy2(release_json, deploy / ".last_applied_usb_release.json")
    failure = deploy / ".last_deploy_failure.json"
    if failure.exists():
        failure.unlink()


def apply_package(
    *,
    target: Path,
    package_root: Path,
    metadata: dict,
    files: list[str],
    deleted: list[str],
    hooks: ApplyHooks | None = None,
    log=print,
    force: bool = False,
    minimum_free_bytes: int | None = None,
) -> ApplyResult:
    hooks = hooks or production_hooks(target, package_root, metadata)
    target = target.resolve()
    package_root = package_root.resolve()
    metadata = dict(metadata)
    metadata["_package_root"] = str(package_root)
    stage = "verify"
    backup_path: Path | None = None
    snapshot_dir: Path | None = None
    changed = False
    backup_created = False
    stopped = False

    def fail(exc: Exception, *, rolled_back: bool) -> ApplyResult:
        result = ApplyResult(
            ok=False,
            stage=stage,
            message=scrub(str(exc)),
            backup_path=str(backup_path) if backup_path else None,
            snapshot_path=str(snapshot_dir) if snapshot_dir else None,
            rolled_back=rolled_back,
        )
        try:
            _write_report(target, result)
        except OSError:
            pass
        log(f"ERROR stage={stage} {result.message}")
        return result

    try:
        files = [validate_rel_path(path) for path in files]
        deleted = [validate_rel_path(path) for path in deleted]
        if not (target / "manage.py").is_file():
            raise ApplyError(f"Target is not a SmartWagers project directory: {target}")
        with deployment_lock(target):
            if not force and _same_release(target, metadata):
                log("Release already applied; leaving the site unchanged.")
                return ApplyResult(ok=True, stage="already-applied", message="Release already applied.")
            required = str(metadata.get("required_python") or "")
            if required:
                assert_python_version(hooks.python_version, required)
            try:
                assert_schema_compatible(current_schema(target), metadata)
            except ValueError as exc:
                raise ApplyError(str(exc)) from exc
            assert_disk_space(target, required_free_bytes(package_root, minimum_free_bytes))

            stage = "stop-service"
            hooks.stop_service()
            stopped = True

            stage = "snapshot"
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            sha = str(metadata.get("commit_sha") or "unknown")[:12]
            snapshot_dir = _history_root(target) / f"{stamp}-{sha}"
            previous_marker = _read_json(target / "deploy" / ".deployed_release.json")
            snapshot_code(target, files, deleted, snapshot_dir)

            if metadata.get("requires_migrate"):
                stage = "backup-database"
                backup_path = hooks.backup_database()
                backup_created = backup_path is not None

            stage = "copy"
            copy_payload(package_root, target, files, deleted)
            changed = True
            manifest_lines = sorted(set(files) | set(deleted))
            (target / "deploy" / ".last_sync_manifest").write_text(
                "\n".join(manifest_lines) + ("\n" if manifest_lines else ""),
                encoding="utf-8",
            )

            if metadata.get("requires_dependencies"):
                stage = "dependencies"
                hooks.install_dependencies()
            if metadata.get("requires_migrate"):
                stage = "migrate"
                hooks.migrate()
            if metadata.get("requires_collectstatic"):
                stage = "collectstatic"
                hooks.collectstatic()

            stage = "readiness"
            hooks.readiness()

            stage = "start-service"
            hooks.start_service()

            stage = "marker"
            _write_success_marker(
                target,
                metadata,
                backup_path=backup_path,
                snapshot_path=snapshot_dir,
                previous={
                    "commit_sha": previous_marker.get("commit_sha", ""),
                    "schema_level": previous_marker.get("schema_level", ""),
                    "snapshot_path": str(snapshot_dir),
                    "backup_path": str(backup_path) if backup_path else previous_marker.get("backup_path", ""),
                },
            )
            prune_history(target)
            log(f"APPLIED {metadata.get('commit_sha') or metadata.get('app_version') or 'release'}")
            return ApplyResult(
                ok=True,
                stage="applied",
                message="Release applied.",
                backup_path=str(backup_path) if backup_path else None,
                snapshot_path=str(snapshot_dir),
            )
    except Exception as exc:  # noqa: BLE001 — convert every stage failure into a rollback result
        rolled_back = False
        if changed and snapshot_dir is not None:
            try:
                restore_snapshot(target, snapshot_dir)
                rolled_back = True
            except Exception as restore_exc:  # noqa: BLE001
                log(f"ERROR code rollback failed: {scrub(str(restore_exc))}")
        if backup_created and backup_path is not None and stage in {
            "migrate",
            "collectstatic",
            "readiness",
            "start-service",
            "marker",
        }:
            try:
                hooks.restore_database(backup_path)
                rolled_back = True
            except Exception as restore_exc:  # noqa: BLE001
                log(f"ERROR database rollback failed: {scrub(str(restore_exc))}")
        if stopped:
            try:
                hooks.start_service()
            except Exception as restart_exc:  # noqa: BLE001
                log(f"ERROR service restart after rollback failed: {scrub(str(restart_exc))}")
        return fail(exc, rolled_back=rolled_back)


def rollback_release(target: Path, hooks: ApplyHooks | None = None, log=print) -> ApplyResult:
    """Restore the previous code snapshot and database backup recorded by the last apply."""
    hooks = hooks or production_hooks(target, target, {})
    marker = _read_json(target / "deploy" / ".deployed_release.json")
    previous = marker.get("previous") if isinstance(marker.get("previous"), dict) else {}
    snapshot_path = Path(str(previous.get("snapshot_path") or ""))
    backup_value = str(previous.get("backup_path") or "")
    backup_path = Path(backup_value) if backup_value else None
    if not snapshot_path.is_dir():
        return ApplyResult(
            ok=False,
            stage="rollback",
            message="No previous code snapshot is available for rollback.",
        )
    try:
        with deployment_lock(target):
            hooks.stop_service()
            restore_snapshot(target, snapshot_path)
            if backup_path and backup_path.is_file():
                hooks.restore_database(backup_path)
            hooks.readiness()
            hooks.start_service()
            restored = {
                "ok": True,
                "app_version": marker.get("app_version"),
                "commit_sha": previous.get("commit_sha") or "",
                "schema_level": previous.get("schema_level") or "",
                "rolled_back_from": marker.get("commit_sha") or "",
                "applied_at": _now(),
                "snapshot_path": str(snapshot_path),
                "backup_path": str(backup_path) if backup_path else "",
                "previous": {},
            }
            (target / "deploy" / ".deployed_release.json").write_text(
                json.dumps(restored, indent=2) + "\n",
                encoding="utf-8",
            )
            log(f"ROLLED BACK to {restored['commit_sha'] or 'previous snapshot'}")
            return ApplyResult(
                ok=True,
                stage="rolled-back",
                message="Previous release restored.",
                backup_path=str(backup_path) if backup_path else None,
                snapshot_path=str(snapshot_path),
                rolled_back=True,
            )
    except Exception as exc:  # noqa: BLE001
        result = ApplyResult(ok=False, stage="rollback", message=scrub(str(exc)))
        _write_report(target, result)
        try:
            hooks.start_service()
        except Exception:
            pass
        return result


def production_python(target: Path) -> Path:
    path_file = target / "deploy" / "python_path.txt"
    if path_file.is_file():
        python_path = Path(path_file.read_text(encoding="utf-8").strip())
        if python_path.is_file():
            return python_path
        raise ApplyError(f"Production Python recorded in {path_file} does not exist.")
    executable = shutil.which("python")
    if not executable:
        raise ApplyError("Python was not found and deploy/python_path.txt is missing.")
    return Path(executable)


def _run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        detail = scrub((result.stderr or result.stdout or "").strip())
        raise ApplyError(f"Command failed ({result.returncode}): {Path(command[0]).name} {detail}")


def production_hooks(target: Path, package_root: Path, metadata: dict) -> ApplyHooks:
    python_exe = production_python(target)

    def stop_service() -> None:
        if NSSM.is_file():
            subprocess.run([str(NSSM), "stop", SERVICE_NAME], check=False)

    def start_service() -> None:
        if not NSSM.is_file():
            return
        result = subprocess.run([str(NSSM), "start", SERVICE_NAME], check=False)
        if result.returncode != 0:
            raise ApplyError("Daphne service failed to start.")

    def backup_database() -> Path:
        tool = target / "deploy" / "postgres_tools.py"
        if not tool.is_file():
            raise ApplyError(f"Cannot back up before migration; missing {tool}")
        backup_dir = target.parent / "backups"
        before = set(backup_dir.glob("smartwagers-*.dump")) if backup_dir.is_dir() else set()
        _run([str(python_exe), str(tool), "backup"], target)
        after = set(backup_dir.glob("smartwagers-*.dump"))
        created = sorted(after - before, key=lambda path: path.stat().st_mtime)
        if not created:
            created = sorted(after, key=lambda path: path.stat().st_mtime)
        if not created:
            raise ApplyError("Database backup command finished without creating a dump.")
        return created[-1]

    def restore_database(path: Path) -> None:
        tool = target / "deploy" / "postgres_tools.py"
        database = ""
        env_file = target / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("POSTGRES_DB="):
                    database = line.split("=", 1)[1].strip()
                    break
        if not database:
            raise ApplyError("POSTGRES_DB is required to restore the pre-migration backup.")
        _run(
            [str(python_exe), str(tool), "restore", str(path), "--confirm-database", database],
            target,
        )

    def install_dependencies() -> None:
        wheels = package_root / "wheels"
        if not wheels.is_dir() or not any(path.is_file() for path in wheels.iterdir()):
            raise ApplyError("requirements.txt changed, but the package contains no offline wheels.")
        _run(
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
            target,
        )

    def migrate() -> None:
        _run([str(python_exe), "manage.py", "migrate", "--noinput"], target)

    def collectstatic() -> None:
        _run([str(python_exe), "manage.py", "collectstatic", "--noinput"], target)

    def readiness() -> None:
        _run([str(python_exe), "manage.py", "check_database"], target)
        _run([str(python_exe), "manage.py", "check_release_readiness"], target)

    return ApplyHooks(
        stop_service=stop_service,
        start_service=start_service,
        backup_database=backup_database,
        restore_database=restore_database,
        install_dependencies=install_dependencies,
        migrate=migrate,
        collectstatic=collectstatic,
        readiness=readiness,
        python_version=sys.version_info[:2],
    )


def legacy_manifest_apply(target: Path) -> ApplyResult:
    """Apply an already-copied manifest. Database changes roll back; copied code stays in place."""
    manifest_path = target / "deploy" / ".last_sync_manifest"
    lines = []
    if manifest_path.is_file():
        lines = [line.strip() for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    needs_migrate = any(path.replace("\\", "/").startswith("SmartWagers/migrations/") for path in lines) or not lines
    needs_static = any(
        "/static/" in f"/{path}" or "/templates/" in f"/{path}" or path.endswith((".js", ".css", ".html"))
        for path in lines
    ) or not lines
    hooks = production_hooks(target, target, {})
    backup_path = None
    try:
        with deployment_lock(target):
            hooks.stop_service()
            if needs_migrate:
                backup_path = hooks.backup_database()
            try:
                if needs_migrate:
                    hooks.migrate()
                if needs_static:
                    hooks.collectstatic()
                hooks.readiness()
                hooks.start_service()
            except Exception:
                if needs_migrate and backup_path is not None:
                    hooks.restore_database(backup_path)
                try:
                    hooks.start_service()
                except Exception:
                    pass
                raise
            return ApplyResult(
                ok=True,
                stage="legacy-applied",
                message="Manifest release applied.",
                backup_path=str(backup_path) if backup_path else None,
            )
    except Exception as exc:  # noqa: BLE001
        result = ApplyResult(ok=False, stage="legacy", message=scrub(str(exc)))
        _write_report(target, result)
        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=Path(r"C:\SmartWagers\GameFowl"))
    parser.add_argument("--package", type=Path, help="Release package directory containing release.json.")
    parser.add_argument("--legacy-manifest", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Accepted for non-interactive callers.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = args.target.expanduser().resolve()
    if args.rollback:
        result = rollback_release(target)
    elif args.legacy_manifest:
        result = legacy_manifest_apply(target)
    elif args.package:
        package = args.package.expanduser().resolve()
        metadata = json.loads((package / "release.json").read_text(encoding="utf-8"))
        result = apply_package(
            target=target,
            package_root=package,
            metadata=metadata,
            files=list(metadata.get("files") or []),
            deleted=list(metadata.get("deleted_files") or []),
            force=args.force,
        )
    else:
        print("ERROR: specify --package, --rollback, or --legacy-manifest.", file=sys.stderr)
        return 2
    print(json.dumps(result.as_dict(), indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
