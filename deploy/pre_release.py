"""Run the local gate that must pass before a field release is built."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def default_commands(python: str | None = None) -> list[list[str]]:
    executable = python or sys.executable
    return [
        [executable, "-m", "pytest", "deploy/tests", "SmartWagers/tests", "-q", "--tb=line"],
        [executable, "manage.py", "check"],
        [executable, "manage.py", "makemigrations", "--check", "--dry-run"],
    ]


def run_checks(commands: list[list[str]] | None = None, cwd: Path = PROJECT_ROOT) -> int:
    for command in commands or default_commands():
        print("RUN " + " ".join(command))
        result = subprocess.run(command, cwd=cwd, check=False)
        if result.returncode != 0:
            print(f"ERROR: pre-release check failed: {' '.join(command)}", file=sys.stderr)
            return result.returncode
    print("Pre-release checks passed.")
    return 0


def main() -> int:
    return run_checks()


if __name__ == "__main__":
    raise SystemExit(main())
