"""Operator commands for Tailscale/OpenSSH site fleets.

The registry is local and gitignored. This module uploads a canonical release
package and runs the same apply engine used by USB recovery. A failed site stops
promotion to the remaining sites.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


FORBIDDEN_SITE_FIELDS = {"password", "secret", "token", "api_key", "private_key"}


class FleetError(RuntimeError):
    pass


@dataclass(frozen=True)
class Site:
    name: str
    host: str
    user: str = "Administrator"
    port: int = 22
    remote_root: str = "C:/SmartWagers/GameFowl"
    group: str = "fleet"
    ssh_key: str = ""

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host


@dataclass
class SiteResult:
    ok: bool
    site: str
    stage: str
    message: str
    warnings: list[str]

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "site": self.site,
            "stage": self.stage,
            "message": self.message,
            "warnings": self.warnings,
        }


def load_sites(path: Path) -> list[Site]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FleetError(f"Cannot read site registry {path}: {exc}") from exc
    raw_sites = document.get("sites") if isinstance(document, dict) else None
    if not isinstance(raw_sites, list) or not raw_sites:
        raise FleetError("Site registry must contain a non-empty sites list.")
    sites: list[Site] = []
    for raw in raw_sites:
        if not isinstance(raw, dict):
            raise FleetError("Each site entry must be an object.")
        secret_fields = FORBIDDEN_SITE_FIELDS.intersection(raw)
        if secret_fields:
            raise FleetError(
                f"Site {raw.get('name', '?')!r} contains forbidden secret fields: "
                + ", ".join(sorted(secret_fields))
            )
        name = str(raw.get("name") or "").strip()
        host = str(raw.get("host") or "").strip()
        if not name or not host:
            raise FleetError("Every site needs a name and a Tailscale or VPN host.")
        sites.append(
            Site(
                name=name,
                host=host,
                user=str(raw.get("user") or "Administrator"),
                port=int(raw.get("port") or 22),
                remote_root=str(raw.get("remote_root") or "C:/SmartWagers/GameFowl"),
                group=str(raw.get("group") or "fleet"),
                ssh_key=str(raw.get("ssh_key") or ""),
            )
        )
    return sites


def select_sites(sites: list[Site], *, name: str | None = None, group: str | None = None) -> list[Site]:
    chosen = sites
    if name:
        chosen = [site for site in chosen if site.name == name]
    if group:
        chosen = [site for site in chosen if site.group == group]
    if not chosen:
        raise FleetError("No sites matched the requested name or group.")
    return order_sites(chosen)


def order_sites(sites: list[Site]) -> list[Site]:
    """Canary sites run before the rest. Original order is preserved within each group."""
    canaries = [site for site in sites if site.group == "canary"]
    others = [site for site in sites if site.group != "canary"]
    return canaries + others


def ssh_command(site: Site, remote_command: str) -> list[str]:
    command = [
        "ssh",
        "-p",
        str(site.port),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
    ]
    if site.ssh_key:
        command.extend(["-i", site.ssh_key])
    command.extend([site.target, remote_command])
    return command


def scp_command(site: Site, source: Path, remote_path: str) -> list[str]:
    command = [
        "scp",
        "-r",
        "-P",
        str(site.port),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
    ]
    if site.ssh_key:
        command.extend(["-i", site.ssh_key])
    command.extend([str(source), f"{site.target}:{remote_path}"])
    return command


def _windows_path(posix_path: str) -> str:
    return posix_path.replace("/", "\\")


def remote_python_command(python_file: str, script: str, arguments: str) -> str:
    """Run a script with the interpreter path stored on the venue.

    cmd expands %PY% before set /p assigns it. Keeping both operations on one
    line therefore exits successfully without launching Python. Delayed
    expansion reads the path after set /p.
    """
    return (
        f'cmd /v:on /c "set /p PY=<{python_file} & '
        f'\"!PY!\" \"{script}\" {arguments}"'
    )


def deploy_commands(site: Site, package_dir: Path) -> list[list[str]]:
    incoming = f"C:/SmartWagers/incoming/{package_dir.name}"
    incoming_windows = _windows_path(incoming)
    apply_script = f"{incoming_windows}\\apply_usb_release.py"
    python_file = _windows_path(site.remote_root.rstrip("/")) + "\\deploy\\python_path.txt"
    remote = remote_python_command(
        python_file,
        apply_script,
        f"--yes --target {_windows_path(site.remote_root)}",
    )
    return [
        ssh_command(site, 'cmd /c "if not exist C:\\SmartWagers\\incoming mkdir C:\\SmartWagers\\incoming"'),
        scp_command(site, package_dir, incoming),
        ssh_command(site, remote),
    ]


def status_command(site: Site) -> list[str]:
    root = _windows_path(site.remote_root.rstrip("/"))
    script = (
        f'cmd /c "type {root}\\deploy\\.deployed_release.json & '
        f'echo. & type {root}\\..\\backups\\last_backup.json & '
        f'echo. & type {root}\\deploy\\teller_agent_reports.json"'
    )
    return ssh_command(site, script)


def verify_command(site: Site) -> list[str]:
    root = _windows_path(site.remote_root.rstrip("/"))
    return ssh_command(site, f'cmd /c "type {root}\\deploy\\.deployed_release.json"')


def rollback_command(site: Site) -> list[str]:
    root = _windows_path(site.remote_root.rstrip("/"))
    python_file = f"{root}\\deploy\\python_path.txt"
    remote = remote_python_command(
        python_file,
        f"{root}\\deploy\\apply_engine.py",
        f"--rollback --yes --target {root}",
    )
    return ssh_command(site, remote)


def diagnostics_command(site: Site) -> list[str]:
    root = _windows_path(site.remote_root.rstrip("/"))
    python_file = f"{root}\\deploy\\python_path.txt"
    output = r"C:\SmartWagers\logs\diagnostics.json"
    remote = remote_python_command(
        python_file,
        f"{root}\\deploy\\collect_diagnostics.py",
        f"--output {output}",
    )
    return ssh_command(site, remote)


def preflight_command(site: Site) -> list[str]:
    root = _windows_path(site.remote_root.rstrip("/"))
    remote = (
        f'cmd /c "if not exist {root}\\manage.py exit /b 2 & '
        f'{root}\\deploy\\python_path.txt >nul & python -c \\"import sys; print(sys.version)\\""'
    )
    return ssh_command(site, remote)


def run_rollout(sites: list[Site], action) -> list[SiteResult]:
    """Run sites in canary order and stop when one fails. Earlier sites stay as they are."""
    results: list[SiteResult] = []
    for site in order_sites(sites):
        result = action(site)
        results.append(result)
        if not result.ok:
            break
    return results


def release_identity_matches(stdout: str, commit_sha: str) -> bool:
    try:
        start = stdout.find("{")
        end = stdout.rfind("}")
        if start < 0 or end < start:
            return False
        document = json.loads(stdout[start : end + 1])
    except json.JSONDecodeError:
        return False
    return str(document.get("commit_sha") or "") == commit_sha and bool(document.get("ok", True))


def append_history(history_dir: Path, site_name: str, record: dict) -> Path:
    history_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in site_name)
    path = history_dir / f"{safe_name}.jsonl"
    payload = dict(record)
    payload.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
    payload.setdefault("operator", os.environ.get("USER") or os.environ.get("USERNAME") or "")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return path


def execute_commands(commands: list[list[str]], runner=subprocess.run) -> subprocess.CompletedProcess:
    last = None
    for command in commands:
        last = runner(command, check=False, capture_output=True, text=True)
        if last.returncode != 0:
            return last
    if last is None:
        raise FleetError("No commands to execute.")
    return last


def default_runner(command, check=False, capture_output=True, text=True):
    return subprocess.run(command, check=check, capture_output=capture_output, text=text)


def _result_from_process(site: Site, stage: str, process, *, warnings: list[str] | None = None) -> SiteResult:
    detail = ((process.stderr or "") + "\n" + (process.stdout or "")).strip()
    if process.returncode != 0:
        return SiteResult(False, site.name, stage, detail or f"{stage} failed", warnings or [])
    return SiteResult(True, site.name, stage, detail, warnings or [])


def command_for(action: str, site: Site, package: Path | None) -> list[list[str]]:
    if action == "status":
        return [status_command(site)]
    if action == "preflight":
        return [preflight_command(site)]
    if action == "verify":
        return [verify_command(site)]
    if action == "rollback":
        return [rollback_command(site)]
    if action == "collect-diagnostics":
        return [diagnostics_command(site)]
    if action == "deploy":
        if package is None:
            raise FleetError("deploy requires a release package directory.")
        return deploy_commands(site, package)
    raise FleetError(f"Unknown fleet action: {action}")


def run_action(
    action: str,
    sites: list[Site],
    *,
    package: Path | None = None,
    expected_sha: str = "",
    history_dir: Path | None = None,
    runner=default_runner,
) -> list[SiteResult]:
    def act(site: Site) -> SiteResult:
        commands = command_for(action, site, package)
        process = execute_commands(commands, runner=runner)
        warnings: list[str] = []
        result = _result_from_process(site, action, process, warnings=warnings)
        if action == "verify" and result.ok and expected_sha:
            if not release_identity_matches(process.stdout or "", expected_sha):
                result = SiteResult(
                    False,
                    site.name,
                    action,
                    f"Deployed commit does not match {expected_sha}.",
                    [],
                )
        if history_dir is not None:
            append_history(
                history_dir,
                site.name,
                {
                    "action": action,
                    "ok": result.ok,
                    "stage": result.stage,
                    "message": result.message[-2000:],
                    "expected_sha": expected_sha,
                    "previous_version": "",
                    "attempted_version": expected_sha,
                },
            )
        return result

    return run_rollout(sites, act)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("status", "preflight", "deploy", "verify", "rollback", "collect-diagnostics"),
    )
    parser.add_argument("--sites", type=Path, default=Path("deploy/sites.json"))
    parser.add_argument("--site", help="Operate on one site name.")
    parser.add_argument("--group", help="Operate on one site group, such as canary.")
    parser.add_argument("--package", type=Path, help="Canonical release package directory.")
    parser.add_argument("--expect-sha", default="", help="Commit SHA that verify must find.")
    parser.add_argument("--history", type=Path, default=Path("deploy/fleet_history"))
    parser.add_argument("--dry-run", action="store_true", help="Print commands without connecting.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        sites = select_sites(load_sites(args.sites), name=args.site, group=args.group)
    except (FleetError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        for site in order_sites(sites):
            try:
                commands = command_for(args.action, site, args.package)
            except FleetError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            print(f"# {site.name} ({site.group})")
            for command in commands:
                print(" ".join(command))
        return 0
    try:
        results = run_action(
            args.action,
            sites,
            package=args.package,
            expected_sha=args.expect_sha,
            history_dir=args.history,
        )
    except FleetError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for result in results:
        state = "OK" if result.ok else "FAILED"
        print(f"{state} {result.site} {result.stage}: {result.message.splitlines()[0] if result.message else ''}")
        for warning in result.warnings:
            print(f"WARNING {result.site}: {warning}")
    print(json.dumps([result.as_dict() for result in results], indent=2))
    return 0 if results and all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
