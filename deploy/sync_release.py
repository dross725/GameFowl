#!/usr/bin/env python3
"""Sync only changed SmartWagers files to production.

Compares the working tree against the last deployed commit (deploy/.deploy-last-sync)
or an explicit git ref, then copies just those files to the server.

Usage (from project root):
    python deploy/sync_release.py --dry-run
    python deploy/sync_release.py
    python deploy/sync_release.py --base origin/main
    python deploy/sync_release.py --files SmartWagers/views.py SmartWagers/services.py
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_DIR = PROJECT_ROOT / "deploy"
CONFIG_PATH = DEPLOY_DIR / "sync_config.env"
LAST_SYNC_PATH = DEPLOY_DIR / ".deploy-last-sync"
MANIFEST_PATH = DEPLOY_DIR / ".last_sync_manifest"

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
    return cleaned.replace("\\", "/").lstrip("./")


def matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = normalize_rel_path(path)
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def is_deployable(path: str, include_tests: bool) -> bool:
    normalized = normalize_rel_path(path)
    if not normalized or normalized.endswith("/"):
        return False
    if matches_any(normalized, EXCLUDE_GLOBS):
        return False
    if not include_tests and matches_any(normalized, TEST_GLOBS):
        return False
    full_path = PROJECT_ROOT / normalized
    if not full_path.is_file():
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
        choices=("auto", "scp", "rsync", "copy"),
        default="auto",
        help="Transport method (default: auto = use DEPLOY_METHOD from config).",
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
    if method not in {"scp", "rsync", "copy"}:
        print(f"ERROR: unknown DEPLOY_METHOD {method!r}.", file=sys.stderr)
        sys.exit(1)
    return method


def main() -> int:
    args = parse_args()
    config = load_config()
    method = choose_method(config, args.method)

    if args.files:
        candidates = [normalize_rel_path(path) for path in args.files]
    else:
        base = resolve_base(args)
        if base:
            print(f"Changes since: {base}")
        else:
            print("Changes since: explicit file list only")
        candidates = collect_changed_files(base, include_uncommitted=args.include_uncommitted)

    files = filter_deployable(candidates, include_tests=args.include_tests)
    if not files:
        print("Nothing to deploy.")
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
