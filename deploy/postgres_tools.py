"""PostgreSQL backup and restore helper for the Windows deployment."""

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
DEFAULT_BACKUP_DIR = PROJECT_DIR.parent / "backups"


def load_env(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"Environment file not found: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def postgres_env() -> dict[str, str]:
    required = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing PostgreSQL settings: " + ", ".join(missing))
    env = os.environ.copy()
    env["PGPASSWORD"] = os.environ["POSTGRES_PASSWORD"]
    return env


def executable(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"{name} was not found on PATH. Add PostgreSQL's bin directory "
            "(for example C:\\Program Files\\PostgreSQL\\17\\bin) to PATH."
        )
    return path


def connection_args() -> list[str]:
    return [
        "--host", os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "--port", os.environ.get("POSTGRES_PORT", "5432"),
        "--username", os.environ["POSTGRES_USER"],
        "--dbname", os.environ["POSTGRES_DB"],
    ]


def run_backup(output: Path | None) -> Path:
    backup_dir = DEFAULT_BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    if output is None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = backup_dir / f"smartwagers-{timestamp}.dump"
    else:
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        executable("pg_dump"),
        *connection_args(),
        "--format=custom",
        "--no-owner",
        "--file", str(output),
    ]
    subprocess.run(command, env=postgres_env(), check=True)
    return output


def write_backup_status(backup: Path, *, validated: bool, status_path: Path | None = None) -> Path:
    status = status_path or (backup.parent / "last_backup.json")
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "path": str(backup),
        "bytes": backup.stat().st_size if backup.is_file() else 0,
        "validated": validated,
    }
    status.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return status


def prune_backups(directory: Path, keep: int = 14) -> list[Path]:
    dumps = sorted(path for path in directory.glob("smartwagers-*.dump") if path.is_file())
    obsolete = dumps[:-keep] if keep > 0 else dumps
    for path in obsolete:
        path.unlink()
    return obsolete


def validate_backup(backup: Path) -> None:
    if not backup.is_file():
        raise RuntimeError(f"Backup file not found: {backup}")
    command = [executable("pg_restore"), "--list", str(backup)]
    subprocess.run(command, check=True)


def backup_maintain(output: Path | None, keep: int = 14) -> Path:
    backup = run_backup(output)
    validated = False
    try:
        validate_backup(backup)
        validated = True
    except Exception:
        write_backup_status(backup, validated=False)
        raise
    prune_backups(backup.parent, keep=keep)
    write_backup_status(backup, validated=validated)
    return backup


def run_restore(backup: Path, confirmation: str) -> None:
    database = os.environ["POSTGRES_DB"]
    if confirmation != database:
        raise RuntimeError(
            f"Restore confirmation must exactly match database name {database!r}."
        )
    if not backup.is_file():
        raise RuntimeError(f"Backup file not found: {backup}")

    command = [
        executable("pg_restore"),
        *connection_args(),
        "--clean",
        "--if-exists",
        "--no-owner",
        "--exit-on-error",
        str(backup.resolve()),
    ]
    subprocess.run(command, env=postgres_env(), check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--output", type=Path)

    maintain_parser = subparsers.add_parser("backup-maintain")
    maintain_parser.add_argument("--output", type=Path)
    maintain_parser.add_argument("--keep", type=int, default=14)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("backup", type=Path)

    prune_parser = subparsers.add_parser("prune")
    prune_parser.add_argument("--keep", type=int, default=14)
    prune_parser.add_argument("--directory", type=Path, default=DEFAULT_BACKUP_DIR)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("backup", type=Path)
    restore_parser.add_argument(
        "--confirm-database",
        required=True,
        help="Must exactly match POSTGRES_DB; restore replaces existing data.",
    )

    args = parser.parse_args()
    load_env(args.env_file.resolve())

    if args.command == "backup":
        output = run_backup(args.output)
        print(f"PostgreSQL backup created: {output}")
    elif args.command == "backup-maintain":
        output = backup_maintain(args.output, keep=args.keep)
        print(f"PostgreSQL backup created and validated: {output}")
    elif args.command == "validate":
        validate_backup(args.backup)
        print(f"PostgreSQL backup is readable: {args.backup}")
    elif args.command == "prune":
        removed = prune_backups(args.directory, keep=args.keep)
        print(f"Removed {len(removed)} old backup(s).")
    else:
        run_restore(args.backup, args.confirm_database)
        print(f"PostgreSQL restore completed: {args.backup.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
