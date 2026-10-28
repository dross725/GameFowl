import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fleet(monkeypatch):
    return load_module("fleet_for_test", PROJECT_ROOT / "deploy" / "fleet.py")


def write_sites(path: Path, sites: list[dict]) -> None:
    path.write_text(json.dumps({"sites": sites}) + "\n", encoding="utf-8")


def test_registry_rejects_secrets_and_orders_canary_first(fleet, tmp_path):
    path = tmp_path / "sites.json"
    write_sites(
        path,
        [
            {"name": "venue", "host": "venue.tailnet.ts.net", "group": "fleet", "password": "nope"},
        ],
    )
    with pytest.raises(fleet.FleetError, match="forbidden secret"):
        fleet.load_sites(path)

    write_sites(
        path,
        [
            {"name": "venue", "host": "venue.tailnet.ts.net", "group": "fleet"},
            {"name": "canary", "host": "canary.tailnet.ts.net", "group": "canary"},
        ],
    )
    ordered = fleet.select_sites(fleet.load_sites(path))
    assert [site.name for site in ordered] == ["canary", "venue"]


def test_failed_canary_halts_promotion(fleet):
    sites = [
        fleet.Site("canary", "canary.example", group="canary"),
        fleet.Site("venue", "venue.example", group="fleet"),
    ]
    seen = []

    def action(site):
        seen.append(site.name)
        return fleet.SiteResult(site.name != "canary", site.name, "deploy", "stopped", [])

    results = fleet.run_rollout(sites, action)
    assert seen == ["canary"]
    assert results[0].ok is False


def test_deploy_commands_upload_before_apply_and_history_is_appended(fleet, tmp_path):
    site = fleet.Site("canary", "canary.tailnet.ts.net", ssh_key="C:/keys/canary")
    package = tmp_path / "SmartWagers-release"
    package.mkdir()
    commands = fleet.deploy_commands(site, package)
    assert commands[0][0] == "ssh"
    assert commands[1][0] == "scp"
    assert commands[2][0] == "ssh"
    remote = commands[2][-1]
    assert "apply_usb_release.py" in remote
    assert "--yes" in remote
    assert "cmd /v:on /c" in remote
    assert "!PY!" in remote
    assert "%PY%" not in remote

    def runner(command, check=False, capture_output=True, text=True):
        class Process:
            returncode = 0
            stdout = json.dumps({"ok": True, "commit_sha": "abc123"})
            stderr = ""

        return Process()

    results = fleet.run_action(
        "verify",
        [site],
        expected_sha="abc123",
        history_dir=tmp_path / "history",
        runner=runner,
    )
    assert results[0].ok is True
    history = (tmp_path / "history" / "canary.jsonl").read_text(encoding="utf-8")
    assert "abc123" in history
    assert "verify" in history


def test_verify_rejects_wrong_commit(fleet, tmp_path):
    site = fleet.Site("canary", "canary.tailnet.ts.net")

    def runner(command, check=False, capture_output=True, text=True):
        class Process:
            returncode = 0
            stdout = json.dumps({"ok": True, "commit_sha": "other"})
            stderr = ""

        return Process()

    results = fleet.run_action("verify", [site], expected_sha="abc123", runner=runner)
    assert results[0].ok is False
