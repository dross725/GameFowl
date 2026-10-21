"""Record a teller print-agent version without affecting the server release."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


DEPLOY_DIR = Path(__file__).resolve().parent
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

from release_metadata import PRINT_AGENT_MIN_VERSION, is_agent_compatible, outdated_agents  # noqa: E402


def load_reports(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    reports = document.get("agents") if isinstance(document, dict) else None
    if not isinstance(reports, list):
        return []
    return [item for item in reports if isinstance(item, dict)]


def record_agent(path: Path, host: str, version: str) -> dict:
    reports = [item for item in load_reports(path) if item.get("host") != host]
    reports.append(
        {
            "host": host,
            "version": version,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "compatible": is_agent_compatible(version),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "minimum_version": PRINT_AGENT_MIN_VERSION,
        "agents": reports,
        "outdated": outdated_agents(reports),
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEPLOY_DIR / "teller_agent_reports.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    document = record_agent(args.output, args.host.strip(), args.version.strip())
    outdated = document["outdated"]
    if outdated:
        print(f"Outdated teller agents: {len(outdated)}. Server release was not changed.")
        return 0
    print("Teller agent version is compatible. Server release was not changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
