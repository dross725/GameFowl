import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_diagnostics_redact_secrets_and_keep_names(tmp_path):
    module = load_module("diagnostics_for_test", PROJECT_ROOT / "deploy" / "collect_diagnostics.py")
    project = tmp_path / "GameFowl"
    (project / "deploy").mkdir(parents=True)
    (project / ".env").write_text(
        "DJANGO_SECRET_KEY=super-secret\nPOSTGRES_PASSWORD=db-secret\nLOCATION=North\n",
        encoding="utf-8",
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "usb_release.log").write_text("password=hunter2\nready\n", encoding="utf-8")
    (project / "deploy" / ".deployed_release.json").write_text(
        json.dumps({"ok": True, "app_version": "1.14.0", "commit_sha": "abc", "backup_path": "hidden"}) + "\n",
        encoding="utf-8",
    )
    document = module.build_diagnostics(project, log_dir=logs)
    assert document["environment_names"] == ["DJANGO_SECRET_KEY", "POSTGRES_PASSWORD", "LOCATION"]
    assert "super-secret" not in json.dumps(document)
    assert "db-secret" not in json.dumps(document)
    assert "hunter2" not in json.dumps(document)
    assert document["release"]["commit_sha"] == "abc"
    assert "backup_path" not in document["release"]


def test_backup_prune_and_status(tmp_path):
    module = load_module("postgres_tools_for_test", PROJECT_ROOT / "deploy" / "postgres_tools.py")
    for index in range(3):
        (tmp_path / f"smartwagers-2026010{index}.dump").write_bytes(b"dump")
    removed = module.prune_backups(tmp_path, keep=2)
    assert len(removed) == 1
    assert len(list(tmp_path.glob("smartwagers-*.dump"))) == 2
    status = module.write_backup_status(next(tmp_path.glob("smartwagers-*.dump")), validated=True)
    payload = json.loads(status.read_text(encoding="utf-8"))
    assert payload["validated"] is True
    assert "bytes" in payload


def test_field_kit_contains_checklist_and_release(tmp_path):
    module = load_module("build_release_for_test", PROJECT_ROOT / "deploy" / "build_release.py")
    package = tmp_path / "SmartWagers-release"
    (package / "payload").mkdir(parents=True)
    (package / "release.json").write_text("{}\n", encoding="utf-8")
    kit = module.assemble_field_kit(package, tmp_path / "kit")
    assert (kit / "release" / package.name / "release.json").is_file()
    checklist = (kit / "CHECKLIST.txt").read_text(encoding="utf-8")
    assert "Checksum mismatch" in checklist
    assert "Power loss" in checklist
    assert (kit / "tools" / "apply_engine.py").is_file()


def test_pre_release_stops_on_first_failure():
    import sys

    module = load_module("pre_release_for_test", PROJECT_ROOT / "deploy" / "pre_release.py")
    status = module.run_checks([[sys.executable, "-c", "raise SystemExit(3)"]])
    assert status == 3


def test_site_config_fails_closed_without_historical_hosts():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "site_config_for_test", PROJECT_ROOT / "GameFowl" / "site_config.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.resolve_csv(True, "", "DJANGO_ALLOWED_HOSTS", module.DEV_HOSTS) == [
        "localhost",
        "127.0.0.1",
    ]
    try:
        module.resolve_csv(False, "", "DJANGO_ALLOWED_HOSTS", module.DEV_HOSTS)
    except module.SiteConfigError as exc:
        assert "192.168" not in str(exc)
    else:
        raise AssertionError("production hosts must be required")
    errors, warnings = module.evaluate_site_config({}, debug=False)
    assert any("DJANGO_ALLOWED_HOSTS" in error for error in errors)
    assert all("replace-me" not in message for message in errors + warnings)
    assert warnings
