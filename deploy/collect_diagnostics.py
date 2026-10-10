"""Collect a sanitized diagnostics bundle for remote support.

Secret values are never copied. Environment output is limited to setting names,
and log lines that look like credentials are redacted.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


SECRET_LINE_RE = re.compile(
    r"(?i)(password|secret|token|signing_key|api_key|authorization)\s*[=:]\s*\S+"
)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def scrub_line(line: str) -> str:
    return SECRET_LINE_RE.sub(r"\1=<redacted>", line)


def environment_names(env_path: Path) -> list[str]:
    if not env_path.is_file():
        return []
    names = []
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        names.append(line.split("=", 1)[0].strip())
    return names


def tail_log(path: Path, limit: int = 80) -> list[str]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return [scrub_line(line) for line in lines[-limit:]]


def read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def build_diagnostics(project_root: Path, log_dir: Path | None = None) -> dict:
    deploy = project_root / "deploy"
    logs = log_dir or project_root.parent / "logs"
    if not logs.is_dir():
        logs = project_root / "logs"
    usage = shutil.disk_usage(project_root if project_root.exists() else project_root.parent)
    release = read_json(deploy / ".deployed_release.json")
    backup = read_json(project_root.parent / "backups" / "last_backup.json")
    safe_release = {
        key: release.get(key)
        for key in (
            "ok",
            "app_version",
            "commit_sha",
            "schema_level",
            "applied_at",
            "artifact_kind",
            "print_agent_version",
            "print_agent_min_version",
        )
        if key in release
    }
    history = []
    history_path = deploy / "fleet_history"
    if history_path.is_dir():
        for path in sorted(history_path.glob("*.jsonl")):
            history.append({"site": path.stem, "tail": tail_log(path, limit=20)})
    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "environment_names": environment_names(project_root / ".env"),
        "release": safe_release,
        "backup": {
            "path": backup.get("path", ""),
            "created_at": backup.get("created_at", ""),
            "validated": backup.get("validated"),
            "bytes": backup.get("bytes"),
        },
        "disk": {"total": usage.total, "used": usage.used, "free": usage.free},
        "logs": {
            "deploy_apply": tail_log(logs / "deploy_apply.log"),
            "usb_release": tail_log(logs / "usb_release.log"),
            "daphne_stderr": tail_log(logs / "daphne_stderr.log"),
        },
        "deployment_history": history,
        "failure": read_json(deploy / ".last_deploy_failure.json"),
    }


def write_diagnostics(project_root: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    document = build_diagnostics(project_root)
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(r"C:\SmartWagers\logs\diagnostics.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        path = write_diagnostics(args.project.resolve(), args.output)
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Diagnostics written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
