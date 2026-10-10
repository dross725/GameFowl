"""Record the installed print-agent version next to this script."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "print_agent.py"
TARGET = ROOT / "installed_agent_version.txt"


def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")
    match = re.search(r'^AGENT_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    version = match.group(1) if match else "unknown"
    TARGET.write_text(version + "\n", encoding="utf-8")
    print(f"Installed print agent version: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
