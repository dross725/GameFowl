"""Offline, repeatable SQLite-to-PostgreSQL migration for SmartWagers."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV = PROJECT_DIR / ".env"
DEFAULT_SQLITE = PROJECT_DIR / "db.sqlite3"


def parse_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f"Environment file not found: {path}")
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def run_manage(arguments: list[str], env: dict[str, str]) -> None:
    command = [sys.executable, str(PROJECT_DIR / "manage.py"), *arguments]
    print("+", " ".join(str(part) for part in command))
    subprocess.run(command, cwd=PROJECT_DIR, env=env, check=True)


def ensure_daphne_stopped() -> None:
    if os.name != "nt":
        return
    result = subprocess.run(
        ["sc", "query", "SmartWagers-Daphne"],
        capture_output=True,
        text=True,
        check=False,
    )
    if "RUNNING" in result.stdout:
        raise RuntimeError(
            "SmartWagers-Daphne is still running. Stop it before migrating."
        )


def ensure_empty_target(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    populated = []
    for label, snapshot in manifest["models"].items():
        if label == "SmartWagers.TransactionSequence":
            continue
        if label.startswith("SmartWagers.") or label in ("auth.User", "auth.Group"):
            if snapshot["count"]:
                populated.append(f"{label}={snapshot['count']}")
    if populated:
        raise RuntimeError(
            "PostgreSQL import target is not empty: " + ", ".join(populated)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument(
        "--confirm-downtime",
        action="store_true",
        help="Acknowledge that Daphne is stopped and no teller can write.",
    )
    args = parser.parse_args()

    if not args.confirm_downtime:
        raise RuntimeError("Pass --confirm-downtime after stopping Daphne.")
    ensure_daphne_stopped()

    env_file = args.env_file.resolve()
    sqlite_path = args.sqlite.resolve()
    if not sqlite_path.is_file():
        raise RuntimeError(f"SQLite source not found: {sqlite_path}")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    work_dir = (
        args.work_dir.resolve()
        if args.work_dir
        else (PROJECT_DIR.parent / "backups" / f"sqlite-to-postgres-{timestamp}")
    )
    work_dir.mkdir(parents=True, exist_ok=False)

    sqlite_backup = work_dir / "db.sqlite3"
    env_backup = work_dir / ".env.backup"
    fixture_path = work_dir / "smartwagers-data.json"
    source_manifest = work_dir / "source-manifest.json"
    empty_manifest = work_dir / "target-before-import.json"
    target_manifest = work_dir / "target-manifest.json"
    postgres_backup = work_dir / "postgres-after-import.dump"

    shutil.copy2(sqlite_path, sqlite_backup)
    shutil.copy2(env_file, env_backup)
    master_lock_path = Path(
        parse_env(env_file).get(
            "MASTER_LOCK_STATE_PATH",
            str(PROJECT_DIR / "master_lock.state"),
        )
    )
    if master_lock_path.is_file():
        shutil.copy2(master_lock_path, work_dir / "master_lock.state.backup")

    configured = parse_env(env_file)
    base_env = os.environ.copy()
    base_env.update(configured)

    sqlite_env = base_env.copy()
    sqlite_env.update({
        "DJANGO_DEBUG": "True",
        "DJANGO_DB_ENGINE": "sqlite",
        "SQLITE_PATH": str(sqlite_backup),
    })

    postgres_env = base_env.copy()
    postgres_env.update({
        "DJANGO_DEBUG": "False",
        "DJANGO_DB_ENGINE": "postgresql",
    })
    postgres_env.pop("SQLITE_PATH", None)

    print(f"Migration workspace: {work_dir}")
    print("1/9 Upgrade the frozen SQLite copy to the current schema")
    run_manage(["migrate", "--noinput"], sqlite_env)

    print("2/9 Verify frozen SQLite source")
    run_manage(
        ["verify_database", "--output", str(source_manifest), "--strict"],
        sqlite_env,
    )

    print("3/9 Export application and authentication data")
    run_manage(
        [
            "dumpdata",
            "auth.group",
            "auth.user",
            "SmartWagers",
            "--natural-foreign",
            "--natural-primary",
            "--indent", "2",
            "--output", str(fixture_path),
        ],
        sqlite_env,
    )

    print("4/9 Verify PostgreSQL connectivity")
    run_manage(["check_database"], postgres_env)

    print("5/9 Create/update PostgreSQL schema")
    run_manage(["migrate", "--noinput"], postgres_env)

    print("6/9 Require an empty PostgreSQL import target")
    run_manage(
        ["verify_database", "--output", str(empty_manifest)],
        postgres_env,
    )
    ensure_empty_target(empty_manifest)

    print("7/9 Import records and reset sequences")
    run_manage(["loaddata", str(fixture_path)], postgres_env)
    run_manage(["reset_sequences"], postgres_env)

    print("8/9 Compare PostgreSQL with SQLite source")
    run_manage(
        [
            "verify_database",
            "--output", str(target_manifest),
            "--compare", str(source_manifest),
            "--strict",
        ],
        postgres_env,
    )

    print("9/9 Create a post-import PostgreSQL backup")
    subprocess.run(
        [
            sys.executable,
            str(PROJECT_DIR / "deploy" / "postgres_tools.py"),
            "--env-file", str(env_file),
            "backup",
            "--output", str(postgres_backup),
        ],
        cwd=PROJECT_DIR,
        env=postgres_env,
        check=True,
    )

    print()
    print("Migration completed and verified.")
    print(f"Artifacts: {work_dir}")
    print("Keep Daphne stopped until the operational smoke test is complete.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
