"""Migrate only Django users and groups from SQLite to PostgreSQL.

SmartWagers financial data is NOT copied. Use this for a clean PostgreSQL
start when only login accounts and roles need to be preserved.
"""

from __future__ import annotations

import argparse
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


def count_users(env: dict[str, str]) -> tuple[int, int]:
    command = [
        sys.executable,
        str(PROJECT_DIR / "manage.py"),
        "shell",
        "-c",
        (
            "from django.contrib.auth.models import Group, User; "
            "print(f'{User.objects.count()} {Group.objects.count()}')"
        ),
    ]
    result = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    # Django may print version banners; take the last non-empty line.
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Could not read user count.")
    parts = lines[-1].split()
    return int(parts[0]), int(parts[1])


def list_usernames(env: dict[str, str]) -> list[str]:
    command = [
        sys.executable,
        str(PROJECT_DIR / "manage.py"),
        "shell",
        "-c",
        (
            "from django.contrib.auth.models import User; "
            "print(','.join(User.objects.order_by('username').values_list('username', flat=True)))"
        ),
    ]
    result = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines or not lines[-1]:
        return []
    return [name for name in lines[-1].split(",") if name]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=DEFAULT_SQLITE,
        help="Path to the OLD SQLite database that contains the users to import.",
    )
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument(
        "--confirm-downtime",
        action="store_true",
        help="Acknowledge that Daphne is stopped and no teller can write.",
    )
    parser.add_argument(
        "--allow-existing-users",
        action="store_true",
        help="Load users even if PostgreSQL already has auth.User rows.",
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
        else (PROJECT_DIR.parent / "backups" / f"users-to-postgres-{timestamp}")
    )
    work_dir.mkdir(parents=True, exist_ok=False)

    sqlite_backup = work_dir / "db.sqlite3"
    env_backup = work_dir / ".env.backup"
    fixture_path = work_dir / "auth-users-groups.json"

    shutil.copy2(sqlite_path, sqlite_backup)
    shutil.copy2(env_file, env_backup)

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

    print(f"Users-only migration workspace: {work_dir}")
    print(f"Source SQLite: {sqlite_path}")

    source_users, source_groups = count_users(sqlite_env)
    source_names = list_usernames(sqlite_env)
    print(f"Source contains {source_users} user(s) and {source_groups} group(s).")
    if source_names:
        print("Source usernames: " + ", ".join(source_names))
    if source_users == 0:
        raise RuntimeError(
            "Source SQLite has zero users. Point --sqlite at the OLD "
            "db.sqlite3 that contains your login accounts."
        )

    print("1/5 Export auth.User and auth.Group from SQLite")
    run_manage(
        [
            "dumpdata",
            "auth.group",
            "auth.user",
            "--natural-foreign",
            "--natural-primary",
            "--indent", "2",
            "--output", str(fixture_path),
        ],
        sqlite_env,
    )
    if fixture_path.stat().st_size < 10:
        raise RuntimeError(f"Export fixture is empty: {fixture_path}")

    print("2/5 Verify PostgreSQL connectivity")
    run_manage(["check_database"], postgres_env)

    print("3/5 Create/update PostgreSQL schema")
    run_manage(["migrate", "--noinput"], postgres_env)

    if not args.allow_existing_users:
        print("4/5 Require empty PostgreSQL user table")
        existing, _ = count_users(postgres_env)
        if existing:
            raise RuntimeError(
                f"PostgreSQL already has {existing} user(s). "
                "Use a fresh database, or pass --allow-existing-users."
            )
    else:
        print("4/5 Skipping empty-user check (--allow-existing-users)")

    print("5/5 Import users/groups and reset sequences")
    run_manage(["loaddata", str(fixture_path)], postgres_env)
    run_manage(["reset_sequences"], postgres_env)

    imported, imported_groups = count_users(postgres_env)
    imported_names = list_usernames(postgres_env)
    print()
    print(
        f"Users-only migration completed. "
        f"PostgreSQL users={imported} groups={imported_groups}"
    )
    if imported_names:
        print("Imported usernames: " + ", ".join(imported_names))
    if imported < source_users:
        raise RuntimeError(
            f"Expected at least {source_users} users after import, found {imported}."
        )
    print(f"Artifacts: {work_dir}")
    print("SmartWagers wager/payout/event data was NOT imported.")
    print("Create a fresh event and settings after starting Daphne.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
