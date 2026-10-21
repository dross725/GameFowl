"""Build an immutable release package from a Git commit.

USB packages, inventory repair packages, and VPN fleet deploys all consume the
package written here. Uncommitted worktree files are not included.
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


DEPLOY_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DEPLOY_DIR.parent
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

import sync_release  # noqa: E402


class BuildError(RuntimeError):
    pass


FIELD_KIT_TOOLS = (
    "APPLY_RELEASE.bat",
    "apply_usb_release.py",
    "apply_engine.py",
    "release_metadata.py",
    "release_inventory.py",
    "EXPORT_SERVER_INVENTORY.bat",
    "13_export_server_inventory.bat",
    "collect_diagnostics.py",
    "postgres_tools.py",
    "8_restore_postgres.bat",
    "7_backup_postgres.bat",
)


def export_git_ref(ref: str, destination: Path, runner=subprocess.run) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    result = runner(
        ["git", "archive", "--format=tar", ref],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise BuildError(detail or f"git archive {ref} failed")
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        extract_kwargs = {"filter": "data"} if sys.version_info >= (3, 11, 4) else {}
        archive.extractall(destination, **extract_kwargs)


def deployable_files(source_root: Path) -> list[str]:
    files = []
    for path in source_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source_root).as_posix()
        if sync_release.is_safe_relative_path(relative, include_tests=False):
            files.append(relative)
    return sorted(files)


def git_head(ref: str, runner=subprocess.run) -> str | None:
    result = runner(
        ["git", "rev-parse", ref],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def build_canonical_release(
    output_root: Path,
    ref: str = "HEAD",
    *,
    skip_wheels: bool = False,
    runner=subprocess.run,
) -> Path:
    head = git_head(ref, runner=runner)
    export_root = output_root / ".export"
    if export_root.exists():
        shutil.rmtree(export_root)
    export_git_ref(ref, export_root, runner=runner)
    files = deployable_files(export_root)
    if "requirements.txt" not in files:
        raise BuildError("Canonical release is missing requirements.txt.")
    files = sorted(set(files) | set(sync_release.REQUIRED_PAYLOAD_FILES))
    package = sync_release.build_usb_package(
        output_root,
        files,
        [],
        base_ref=None,
        dry_run=False,
        source_root=export_root,
        artifact_kind="full",
        head_ref=head,
        skip_wheels=skip_wheels,
    )
    shutil.rmtree(export_root, ignore_errors=True)
    if package is None:
        raise BuildError("Canonical release package was not created.")
    return package


def checklist_text(package_name: str) -> str:
    return f"""SmartWagers field kit — {package_name}

Remote update is preferred. Use this USB kit only when the VPN path is unavailable
or a site must be recovered on location.

Before applying
1. Confirm the venue name and that betting is stopped.
2. Run EXPORT_SERVER_INVENTORY.bat if the installed version is uncertain.
3. Confirm PostgreSQL and Memurai are running.

Apply
1. Open the release folder and run APPLY_RELEASE.bat as Administrator.
2. Wait for the success message. Do not remove the USB drive early.
3. Open http://localhost:8080/health/ready/ and confirm ok is true.
4. Log in as admin, place no bets, and confirm the display page connects.

If apply fails
1. Read C:\\SmartWagers\\logs\\usb_release.log and deploy\\.last_deploy_failure.json.
2. The apply engine restores the previous code and pre-migration database backup.
3. If the service is still down, run the rollback package in the rollback folder
   or: python deploy\\apply_engine.py --rollback --target C:\\SmartWagers\\GameFowl
4. Restore a named backup with deploy\\8_restore_postgres.bat only when the
   automatic rollback did not restore the database.

Failure drills to rehearse before a wide rollout
- VPN disconnects during upload: the package is applied only after upload completes.
- Checksum mismatch: apply stops before copying files.
- Not enough disk space: apply stops before stopping Daphne.
- PostgreSQL or Redis unavailable: readiness fails and the previous release returns.
- Migration or service restart failure: code snapshot and database backup are restored.
- Power loss: rerun the same package. A completed release is not applied twice.
- USB rollback: apply the previous package or the recorded snapshot.

Teller print agents are not rolled back with the server. Update outdated teller
PCs from Admin -> Print Agent after the server is healthy.
"""


def assemble_field_kit(
    package_dir: Path,
    destination: Path,
    previous_package: Path | None = None,
) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    release_dir = destination / "release" / package_dir.name
    shutil.copytree(package_dir, release_dir)
    if previous_package and previous_package.is_dir():
        shutil.copytree(previous_package, destination / "rollback" / previous_package.name)
    tools = destination / "tools"
    tools.mkdir(parents=True)
    for name in FIELD_KIT_TOOLS:
        source = DEPLOY_DIR / name
        if source.is_file():
            shutil.copy2(source, tools / name)
    (destination / "CHECKLIST.txt").write_text(checklist_text(package_dir.name), encoding="utf-8")
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Git tag or commit to package.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, help="Build a repair package from a server inventory.")
    parser.add_argument("--field-kit", action="store_true")
    parser.add_argument("--previous-package", type=Path, help="Previous package included for USB rollback.")
    parser.add_argument("--skip-checks", action="store_true")
    parser.add_argument("--skip-wheels", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.skip_checks and not args.dry_run:
        from pre_release import run_checks

        status = run_checks()
        if status != 0:
            return status
    output = args.output.expanduser().resolve()
    if args.inventory:
        from release_inventory import InventoryError, compare_inventory

        try:
            added, changed, deleted = compare_inventory(PROJECT_ROOT, args.inventory.expanduser().resolve())
        except InventoryError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        package = sync_release.build_usb_package(
            output,
            added + changed,
            deleted,
            base_ref=None,
            dry_run=args.dry_run,
            artifact_kind="inventory-repair",
            skip_wheels=args.skip_wheels,
        )
    else:
        if args.dry_run:
            print(f"Would build canonical release {args.ref} under {output}")
            return 0
        try:
            package = build_canonical_release(output, args.ref, skip_wheels=args.skip_wheels)
        except BuildError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    if package and args.field_kit:
        kit = assemble_field_kit(
            package,
            output / f"{package.name}-field-kit",
            previous_package=args.previous_package,
        )
        print(f"Field kit created: {kit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
