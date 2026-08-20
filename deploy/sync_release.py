#!/usr/bin/env python3
"""Sync changed SmartWagers files or build an offline USB release.

Compares the working tree against the last deployed commit (deploy/.deploy-last-sync)
or an explicit git ref, then copies just those files to the server.

Usage (from project root):
    python deploy/sync_release.py --dry-run
    python deploy/sync_release.py
    python deploy/sync_release.py --base origin/main
    python deploy/sync_release.py --files SmartWagers/views.py SmartWagers/services.py
    python deploy/sync_release.py --usb E:\\SmartWagersReleases
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_DIR = PROJECT_ROOT / "deploy"
CONFIG_PATH = DEPLOY_DIR / "sync_config.env"
LAST_SYNC_PATH = DEPLOY_DIR / ".deploy-last-sync"
MANIFEST_PATH = DEPLOY_DIR / ".last_sync_manifest"
PACKAGE_APPLY_FILES = (
    DEPLOY_DIR / "APPLY_RELEASE.bat",
    DEPLOY_DIR / "apply_usb_release.py",
    DEPLOY_DIR / "EXPORT_SERVER_INVENTORY.bat",
    DEPLOY_DIR / "release_inventory.py",
)
REQUIRED_PAYLOAD_FILES = (
    "deploy/11_apply_release.bat",
    "deploy/13_export_server_inventory.bat",
    "deploy/release_inventory.py",
)

# Never push these paths to production.
EXCLUDE_GLOBS = (
    ".git/*",
    ".venv/*",
    "venv/*",
    "env/*",
    "staticfiles/*",
    "media/*",
    "logs/*",
    "htmlcov/*",
    ".pytest_cache/*",
    ".mypy_cache/*",
    ".ruff_cache/*",
    "node_modules/*",
    "deploy/sync_config.env",
    "deploy/.deploy-last-sync",
    "deploy/.last_sync_manifest",
    "deploy/python_path.txt",
    "**/__pycache__/*",
    "**/*.pyc",
    "**/*.pyo",
    "**/*.log",
    ".env",
    ".env.*",
    ".gitignore",
    "db.sqlite3",
    "db.sqlite3-journal",
    "master_lock.state",
    "master_lock.state.lock",
    "**/master_lock.state",
    "**/*.master_lock.*.tmp",
)

# Skip tests on production unless --include-tests is passed.
TEST_GLOBS = (
    "SmartWagers/tests/**",
    "**/test_*.py",
    "**/tests/**",
)


def load_config() -> dict[str, str]:
    if not CONFIG_PATH.exists():
        print(
            f"ERROR: {CONFIG_PATH} not found.\n"
            f"Copy deploy/sync_config.example.env to deploy/sync_config.env and edit it.",
            file=sys.stderr,
        )
        sys.exit(1)

    config: dict[str, str] = {}
    for raw_line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip()
    return config


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def normalize_rel_path(path: str) -> str:
    cleaned = path.strip().strip('"').strip("'")
    cleaned = cleaned.replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = normalize_rel_path(path)
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def is_deployable(path: str, include_tests: bool) -> bool:
    normalized = normalize_rel_path(path)
    if not is_safe_relative_path(normalized, include_tests=include_tests) or normalized.endswith("/"):
        return False
    full_path = PROJECT_ROOT / normalized
    if not full_path.is_file():
        return False
    return True


def is_safe_relative_path(path: str, include_tests: bool = False) -> bool:
    normalized = normalize_rel_path(path)
    pure_path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or ":" in normalized
        or ".." in pure_path.parts
        or matches_any(normalized, EXCLUDE_GLOBS)
    ):
        return False
    if not include_tests and matches_any(normalized, TEST_GLOBS):
        return False
    return True


def read_last_sync_ref() -> str | None:
    if not LAST_SYNC_PATH.exists():
        return None
    ref = LAST_SYNC_PATH.read_text(encoding="utf-8").strip()
    return ref or None


def write_last_sync_ref(ref: str) -> None:
    LAST_SYNC_PATH.write_text(ref + "\n", encoding="utf-8")


def current_head() -> str:
    result = run_git(["rev-parse", "HEAD"])
    if result.returncode != 0:
        print(result.stderr.strip() or "ERROR: git rev-parse HEAD failed", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def collect_changed_files(base: str | None, include_uncommitted: bool) -> list[str]:
    files: set[str] = set()

    if base:
        diff = run_git(["diff", "--name-only", "--diff-filter=ACMRTUXB", base, "HEAD"])
        if diff.returncode != 0:
            print(diff.stderr.strip() or f"ERROR: git diff against {base} failed", file=sys.stderr)
            sys.exit(1)
        files.update(normalize_rel_path(line) for line in diff.stdout.splitlines() if line.strip())

    if include_uncommitted:
        unstaged = run_git(["diff", "--name-only", "--diff-filter=ACMRTUXB"])
        if unstaged.returncode == 0:
            files.update(
                normalize_rel_path(line) for line in unstaged.stdout.splitlines() if line.strip()
            )

        staged = run_git(["diff", "--name-only", "--cached", "--diff-filter=ACMRTUXB"])
        if staged.returncode == 0:
            files.update(
                normalize_rel_path(line) for line in staged.stdout.splitlines() if line.strip()
            )

        untracked = run_git(["ls-files", "--others", "--exclude-standard"])
        if untracked.returncode == 0:
            files.update(
                normalize_rel_path(line) for line in untracked.stdout.splitlines() if line.strip()
            )

    return sorted(files)


def collect_deleted_files(
    base: str | None, include_tests: bool, include_uncommitted: bool = True
) -> list[str]:
    commands: list[list[str]] = []
    if base:
        commands.append(["diff", "--name-status", "--diff-filter=DR", base, "HEAD"])
    if include_uncommitted:
        commands.extend(
            (
                ["diff", "--name-status", "--diff-filter=DR"],
                ["diff", "--name-status", "--cached", "--diff-filter=DR"],
            )
        )

    deleted: set[str] = set()
    for command in commands:
        diff = run_git(command)
        if diff.returncode != 0:
            print(diff.stderr.strip() or "ERROR: git deletion diff failed", file=sys.stderr)
            sys.exit(1)
        for line in diff.stdout.splitlines():
            fields = line.split("\t")
            if not fields:
                continue
            status = fields[0]
            old_path = fields[1] if len(fields) >= 2 and status.startswith(("D", "R")) else ""
            if old_path and is_safe_relative_path(old_path, include_tests=include_tests):
                deleted.add(normalize_rel_path(old_path))
    return sorted(deleted)


def filter_deployable(files: list[str], include_tests: bool) -> list[str]:
    deployable = [path for path in files if is_deployable(path, include_tests=include_tests)]
    skipped = sorted(set(files) - set(deployable))
    if skipped:
        print("Skipped (not deployed):")
        for path in skipped:
            print(f"  - {path}")
        print()
    return deployable


def write_manifest(files: list[str]) -> None:
    MANIFEST_PATH.write_text("\n".join(files) + ("\n" if files else ""), encoding="utf-8")


def git_ref_or_none(ref: str) -> str | None:
    result = run_git(["rev-parse", ref])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_package_dir(output_root: Path, head_ref: str | None) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    suffix = (head_ref or "working-tree")[:8]
    candidate = output_root / f"SmartWagers-{stamp}-{suffix}"
    counter = 2
    while candidate.exists():
        candidate = output_root / f"SmartWagers-{stamp}-{suffix}-{counter}"
        counter += 1
    return candidate


def download_offline_dependencies(package_dir: Path) -> None:
    wheels_dir = package_dir / "wheels"
    wheels_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--dest",
        str(wheels_dir),
        "--only-binary=:all:",
        "--requirement",
        str(PROJECT_ROOT / "requirements.txt"),
    ]
    print("Downloading offline dependencies:")
    print(" ".join(f'"{part}"' if " " in part else part for part in cmd))
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)
    if result.returncode != 0:
        shutil.rmtree(package_dir, ignore_errors=True)
        print("ERROR: failed to build the offline dependency wheelhouse.", file=sys.stderr)
        sys.exit(1)


def build_usb_package(
    output_root: Path,
    files: list[str],
    deleted_files: list[str],
    base_ref: str | None,
    dry_run: bool,
) -> Path | None:
    head_ref = git_ref_or_none("HEAD")
    package_dir = unique_package_dir(output_root, head_ref)
    for rel_path in REQUIRED_PAYLOAD_FILES:
        if not (PROJECT_ROOT / rel_path).is_file():
            print(f"ERROR: required payload file not found: {rel_path}", file=sys.stderr)
            sys.exit(1)
    payload_files = sorted(set(files) | set(REQUIRED_PAYLOAD_FILES))
    payload_files = [path for path in payload_files if is_deployable(path, include_tests=True)]
    needs_dependencies = "requirements.txt" in payload_files

    print(f"USB release folder: {package_dir}")
    for rel_path in payload_files:
        print(f"  COPY payload/{rel_path}")
    for rel_path in deleted_files:
        print(f"  DELETE on server: {rel_path}")
    if needs_dependencies:
        print("  DOWNLOAD offline dependencies into wheels/")
    if dry_run:
        print("\nDry run complete. No release package created.")
        return None

    output_root.mkdir(parents=True, exist_ok=True)
    payload_root = package_dir / "payload"
    payload_root.mkdir(parents=True)

    checksums: dict[str, str] = {}
    for rel_path in payload_files:
        source = PROJECT_ROOT / rel_path
        destination = payload_root / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        checksums[rel_path] = sha256_file(destination)

    apply_manifest = sorted(set(payload_files) | set(deleted_files))
    (package_dir / "manifest.txt").write_text(
        "\n".join(apply_manifest) + ("\n" if apply_manifest else ""),
        encoding="utf-8",
    )
    (package_dir / "deleted.txt").write_text(
        "\n".join(deleted_files) + ("\n" if deleted_files else ""),
        encoding="utf-8",
    )

    for apply_file in PACKAGE_APPLY_FILES:
        if not apply_file.is_file():
            shutil.rmtree(package_dir, ignore_errors=True)
            print(f"ERROR: required package utility not found: {apply_file}", file=sys.stderr)
            sys.exit(1)
        destination = package_dir / apply_file.name
        shutil.copy2(apply_file, destination)
        checksums[apply_file.name] = sha256_file(destination)

    if needs_dependencies:
        download_offline_dependencies(package_dir)
        for wheel in sorted((package_dir / "wheels").iterdir()):
            if wheel.is_file():
                checksums[f"wheels/{wheel.name}"] = sha256_file(wheel)

    metadata = {
        "package_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_ref": base_ref,
        "head_ref": head_ref,
        "files": payload_files,
        "deleted_files": deleted_files,
        "requires_dependencies": needs_dependencies,
        "checksums": checksums,
    }
    (package_dir / "release.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nUSB release package created: {package_dir}")
    print(f'On the server, run "{package_dir.name}\\APPLY_RELEASE.bat" from the USB drive.')
    return package_dir


def remote_root_posix(config: dict[str, str]) -> str:
    root = config.get("DEPLOY_REMOTE_ROOT", "C:/SmartWagers/GameFowl")
    return PureWindowsPath(root).as_posix().rstrip("/")


def local_root_path(config: dict[str, str], required: bool = True) -> Path:
    root = config.get("DEPLOY_LOCAL_ROOT")
    if not root:
        if required:
            print("ERROR: DEPLOY_LOCAL_ROOT is required for copy method.", file=sys.stderr)
            sys.exit(1)
        return Path("C:/SmartWagers/GameFowl")
    return Path(root).expanduser().resolve()


def ssh_base(config: dict[str, str]) -> list[str]:
    host = config.get("DEPLOY_HOST", "").strip()
    user = config.get("DEPLOY_USER", "").strip()
    port = config.get("DEPLOY_PORT", "22").strip()
    if not host:
        print("ERROR: DEPLOY_HOST is required for scp/rsync methods.", file=sys.stderr)
        sys.exit(1)

    target = f"{user}@{host}" if user else host
    cmd = ["ssh", "-p", port]
    extra = config.get("DEPLOY_SSH_OPTIONS", "").strip()
    if extra:
        cmd.extend(extra.split())
    cmd.append(target)
    return cmd


def scp_base(config: dict[str, str]) -> list[str]:
    host = config.get("DEPLOY_HOST", "").strip()
    user = config.get("DEPLOY_USER", "").strip()
    port = config.get("DEPLOY_PORT", "22").strip()
    if not host:
        print("ERROR: DEPLOY_HOST is required for scp/rsync methods.", file=sys.stderr)
        sys.exit(1)

    target = f"{user}@{host}" if user else host
    cmd = ["scp", "-P", port]
    extra = config.get("DEPLOY_SSH_OPTIONS", "").strip()
    if extra:
        cmd.extend(extra.split())
    return cmd, target


def ensure_remote_dirs(config: dict[str, str], files: list[str]) -> None:
    remote_root = remote_root_posix(config)
    dirs = sorted({str(PurePosixPath(remote_root, PurePosixPath(path).parent)) for path in files})
    if not dirs:
        return

    mkdir_script = " && ".join(f'if not exist "{PureWindowsPath(d)}" mkdir "{PureWindowsPath(d)}"' for d in dirs)
    cmd = ssh_base(config) + [f'cmd /c "{mkdir_script}"']
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print("ERROR: failed to create remote directories.", file=sys.stderr)
        sys.exit(1)


def sync_via_scp(config: dict[str, str], files: list[str], dry_run: bool) -> None:
    scp_cmd, target = scp_base(config)
    remote_root = remote_root_posix(config)

    if not dry_run:
        ensure_remote_dirs(config, files)

    for rel_path in files:
        src = PROJECT_ROOT / rel_path
        remote_file = f"{target}:{PurePosixPath(remote_root, rel_path).as_posix()}"
        cmd = [*scp_cmd, str(src), remote_file]
        print(" ".join(cmd))
        if dry_run:
            continue
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            print(f"ERROR: scp failed for {rel_path}", file=sys.stderr)
            sys.exit(1)


def sync_via_rsync(config: dict[str, str], files: list[str], dry_run: bool) -> None:
    remote_root = remote_root_posix(config)
    host = config.get("DEPLOY_HOST", "").strip()
    user = config.get("DEPLOY_USER", "").strip()
    port = config.get("DEPLOY_PORT", "22").strip()
    target = f"{user}@{host}" if user else host

    ssh_parts = ["ssh", "-p", port]
    extra = config.get("DEPLOY_SSH_OPTIONS", "").strip()
    if extra:
        ssh_parts.extend(extra.split())

    with MANIFEST_PATH.open("w", encoding="utf-8") as manifest:
        for rel_path in files:
            manifest.write(rel_path + "\n")

    cmd = [
        "rsync",
        "-avz",
        "--files-from",
        str(MANIFEST_PATH),
        "--relative",
        "-e",
        " ".join(ssh_parts),
    ]
    if dry_run:
        cmd.insert(1, "--dry-run")
    cmd.extend([f"{PROJECT_ROOT}/", f"{target}:{remote_root}/"])
    print(" ".join(cmd))
    if dry_run:
        return
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)
    if result.returncode != 0:
        print("ERROR: rsync failed.", file=sys.stderr)
        sys.exit(1)


def sync_via_copy(config: dict[str, str], files: list[str], dry_run: bool) -> None:
    dest_root = local_root_path(config, required=not dry_run)
    for rel_path in files:
        src = PROJECT_ROOT / rel_path
        dest = dest_root / rel_path
        print(f"COPY {src} -> {dest}")
        if dry_run:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def remote_apply(config: dict[str, str], dry_run: bool) -> None:
    if config.get("DEPLOY_REMOTE_APPLY", "true").lower() not in {"1", "true", "yes", "on"}:
        print("Skipping remote apply (DEPLOY_REMOTE_APPLY=false).")
        return

    remote_root = remote_root_posix(config)
    apply_script = PureWindowsPath(remote_root, "deploy", "11_apply_release.bat").as_posix()
    remote_cmd = f'cmd /c "{apply_script}"'
    cmd = ssh_base(config) + [remote_cmd]
    print(" ".join(cmd))
    if dry_run:
        return
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print("ERROR: remote apply script failed.", file=sys.stderr)
        sys.exit(1)


def local_apply(config: dict[str, str], dry_run: bool) -> None:
    apply_script = DEPLOY_DIR / "11_apply_release.bat"
    if not apply_script.exists():
        print(f"WARNING: {apply_script} not found; skipping apply.", file=sys.stderr)
        return
    cmd = ["cmd.exe", "/c", str(apply_script)]
    print(" ".join(cmd))
    if dry_run:
        return
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)
    if result.returncode != 0:
        print("ERROR: local apply script failed.", file=sys.stderr)
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync only changed files to production.")
    parser.add_argument(
        "--base",
        help="Git ref to compare against (default: last successful deploy, else HEAD~1).",
    )
    parser.add_argument(
        "--since-last",
        action="store_true",
        help="Compare against deploy/.deploy-last-sync (default when present).",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        help="Deploy explicit file paths instead of using git diffs.",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        help="Compare against a production inventory instead of a Git baseline.",
    )
    parser.add_argument(
        "--include-uncommitted",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include unstaged, staged, and untracked files (default: true).",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include test files in the deploy set.",
    )
    parser.add_argument(
        "--method",
        choices=("auto", "scp", "rsync", "copy", "package"),
        default="auto",
        help="Transport method (default: auto = use DEPLOY_METHOD from config).",
    )
    parser.add_argument(
        "--usb",
        metavar="DIRECTORY",
        help="Build a timestamped offline package under this USB directory.",
    )
    parser.add_argument(
        "--output",
        metavar="DIRECTORY",
        help="Output root for --method package (equivalent to --usb).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show actions without copying files or restarting services.",
    )
    parser.add_argument(
        "--no-apply",
        action="store_true",
        help="Skip migrate/collectstatic/restart after sync.",
    )
    parser.add_argument(
        "--mark-deployed",
        action="store_true",
        help="Update deploy/.deploy-last-sync to current HEAD after success.",
    )
    parser.add_argument(
        "--mark-only",
        action="store_true",
        help="Record the current HEAD as deployed without copying or packaging files.",
    )
    return parser.parse_args()


def resolve_base(args: argparse.Namespace) -> str | None:
    if args.files:
        return None

    last_ref = read_last_sync_ref()
    if args.since_last and last_ref:
        return last_ref
    if args.base:
        return args.base
    if last_ref:
        return last_ref

    fallback = run_git(["rev-parse", "HEAD~1"])
    if fallback.returncode == 0:
        return fallback.stdout.strip()
    return None


def choose_method(config: dict[str, str], requested: str) -> str:
    if requested != "auto":
        return requested
    method = config.get("DEPLOY_METHOD", "scp").strip().lower()
    if method not in {"scp", "rsync", "copy", "package"}:
        print(f"ERROR: unknown DEPLOY_METHOD {method!r}.", file=sys.stderr)
        sys.exit(1)
    return method


def main() -> int:
    args = parse_args()
    if args.mark_only:
        head_ref = current_head()
        write_last_sync_ref(head_ref)
        print(f"Recorded deploy baseline {head_ref} at {LAST_SYNC_PATH.name}.")
        return 0
    if args.usb and args.output:
        print("ERROR: use either --usb or --output, not both.", file=sys.stderr)
        return 2
    if args.inventory and (args.files or args.base or args.since_last):
        print(
            "ERROR: --inventory cannot be combined with --files, --base, or --since-last.",
            file=sys.stderr,
        )
        return 2
    package_output = args.usb or args.output
    requested_method = "package" if package_output else args.method
    config = {} if requested_method == "package" else load_config()
    method = choose_method(config, requested_method)
    if method == "package" and not package_output:
        package_output = config.get("PACKAGE_OUTPUT_ROOT")
    if method == "package" and not package_output:
        print("ERROR: --usb DIRECTORY or --output DIRECTORY is required for package mode.", file=sys.stderr)
        return 2

    base: str | None = None
    if args.inventory:
        try:
            from release_inventory import InventoryError, compare_inventory
        except ImportError as exc:
            print(f"ERROR: inventory helper could not be loaded: {exc}", file=sys.stderr)
            return 1
        try:
            added_files, changed_files, deleted_files = compare_inventory(
                PROJECT_ROOT, args.inventory.expanduser().resolve()
            )
        except InventoryError as exc:
            print(f"ERROR: production inventory comparison failed: {exc}", file=sys.stderr)
            return 1
        candidates = added_files + changed_files
        print(f"Production inventory: {args.inventory}")
        print(
            f"Difference: {len(added_files)} add, "
            f"{len(changed_files)} update, {len(deleted_files)} delete"
        )
    elif args.files:
        candidates = [normalize_rel_path(path) for path in args.files]
        deleted_files: list[str] = []
    else:
        base = resolve_base(args)
        if base:
            print(f"Changes since: {base}")
        else:
            print("Changes since: explicit file list only")
        candidates = collect_changed_files(base, include_uncommitted=args.include_uncommitted)
        deleted_files = collect_deleted_files(
            base,
            include_tests=args.include_tests,
            include_uncommitted=args.include_uncommitted,
        )

    files = filter_deployable(candidates, include_tests=args.include_tests)
    if not files and not deleted_files:
        print("Nothing to deploy.")
        return 0

    if method == "package":
        build_usb_package(
            Path(str(package_output)).expanduser().resolve(),
            files,
            deleted_files,
            base_ref=base,
            dry_run=args.dry_run,
        )
        if args.mark_deployed:
            print(
                "WARNING: package creation does not mark the release deployed. "
                "Run --mark-deployed --no-apply after confirming the server apply.",
                file=sys.stderr,
            )
        return 0

    print(f"Deploying {len(files)} file(s) via {method}:")
    for path in files:
        print(f"  + {path}")
    print()

    write_manifest(files)
    manifest_rel = normalize_rel_path(str(MANIFEST_PATH.relative_to(PROJECT_ROOT)))
    if manifest_rel not in files:
        files.append(manifest_rel)

    if method == "scp":
        sync_via_scp(config, files, dry_run=args.dry_run)
    elif method == "rsync":
        sync_via_rsync(config, files, dry_run=args.dry_run)
    else:
        sync_via_copy(config, files, dry_run=args.dry_run)

    if args.dry_run:
        print("\nDry run complete. No files copied.")
        return 0

    if not args.no_apply:
        if method == "copy":
            local_apply(config, dry_run=False)
        else:
            remote_apply(config, dry_run=False)

    if args.mark_deployed:
        write_last_sync_ref(current_head())
        print(f"Recorded deploy baseline at {LAST_SYNC_PATH.name}.")

    print("Deploy complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
