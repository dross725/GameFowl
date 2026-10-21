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
def engine(monkeypatch):
    module = load_module("apply_engine_for_test", PROJECT_ROOT / "deploy" / "apply_engine.py")
    monkeypatch.setattr(module, "NSSM", Path("/nonexistent/nssm.exe"))
    return module


def make_site(tmp_path: Path):
    target = tmp_path / "GameFowl"
    (target / "deploy").mkdir(parents=True)
    (target / "manage.py").write_text("# manage\n", encoding="utf-8")
    app = target / "SmartWagers" / "views.py"
    app.parent.mkdir()
    app.write_text("old\n", encoding="utf-8")
    package = tmp_path / "package"
    payload = package / "payload" / "SmartWagers"
    payload.mkdir(parents=True)
    (payload / "views.py").write_text("new\n", encoding="utf-8")
    (package / "release.json").write_text("{}\n", encoding="utf-8")
    return target, package


def metadata():
    return {
        "app_version": "1.14.0",
        "commit_sha": "abc123",
        "head_ref": "abc123",
        "schema_level": "0051_eventreportemail",
        "required_python": "3.12",
        "requires_migrate": True,
        "requires_dependencies": False,
        "requires_collectstatic": False,
        "allow_from_any_older": True,
    }


def hooks(engine, **overrides):
    calls = []

    def record(name, fn=None):
        def wrapped(*args):
            calls.append((name, args))
            if fn:
                return fn(*args)
            return None

        return wrapped

    values = {
        "stop_service": record("stop"),
        "start_service": record("start"),
        "backup_database": record("backup", lambda: Path("backup.dump")),
        "restore_database": record("restore"),
        "install_dependencies": record("deps"),
        "migrate": record("migrate"),
        "collectstatic": record("static"),
        "readiness": record("ready"),
        "python_version": (3, 12),
    }
    values.update(overrides)
    return engine.ApplyHooks(**values), calls


def test_successful_apply_writes_marker_only_after_readiness(engine, tmp_path):
    target, package = make_site(tmp_path)
    apply_hooks, calls = hooks(engine)
    result = engine.apply_package(
        target=target,
        package_root=package,
        metadata=metadata(),
        files=["SmartWagers/views.py"],
        deleted=[],
        hooks=apply_hooks,
        minimum_free_bytes=0,
        log=lambda message: None,
    )
    assert result.ok is True
    assert (target / "SmartWagers" / "views.py").read_text(encoding="utf-8") == "new\n"
    marker = json.loads((target / "deploy" / ".deployed_release.json").read_text(encoding="utf-8"))
    assert marker["commit_sha"] == "abc123"
    assert [name for name, _args in calls] == ["stop", "backup", "migrate", "ready", "start"]
    assert not (target / "deploy" / ".last_deploy_failure.json").exists()


def test_duplicate_apply_does_not_stop_service(engine, tmp_path):
    target, package = make_site(tmp_path)
    apply_hooks, _calls = hooks(engine)
    engine.apply_package(
        target=target,
        package_root=package,
        metadata=metadata(),
        files=["SmartWagers/views.py"],
        deleted=[],
        hooks=apply_hooks,
        minimum_free_bytes=0,
        log=lambda message: None,
    )
    again, calls = hooks(engine)
    result = engine.apply_package(
        target=target,
        package_root=package,
        metadata=metadata(),
        files=["SmartWagers/views.py"],
        deleted=[],
        hooks=again,
        minimum_free_bytes=0,
        log=lambda message: None,
    )
    assert result.stage == "already-applied"
    assert calls == []


@pytest.mark.parametrize(
    ("stage_name", "override"),
    [
        ("dependencies", {"install_dependencies": "fail", "requires_dependencies": True}),
        ("migrate", {"migrate": "fail"}),
        ("collectstatic", {"collectstatic": "fail", "requires_collectstatic": True}),
        ("readiness", {"readiness": "fail"}),
        ("start-service", {"start_service": "fail"}),
    ],
)
def test_failure_restores_code_and_database(engine, tmp_path, stage_name, override):
    target, package = make_site(tmp_path)
    package_metadata = metadata()
    options = dict(override)
    if options.pop("requires_dependencies", False):
        package_metadata["requires_dependencies"] = True
        package_metadata["requires_migrate"] = False
    if options.pop("requires_collectstatic", False):
        package_metadata["requires_collectstatic"] = True

    def fail():
        raise RuntimeError("password=secret boom")

    apply_hooks, calls = hooks(engine)
    for name, action in options.items():
        if action == "fail":
            setattr(apply_hooks, name, fail)
    result = engine.apply_package(
        target=target,
        package_root=package,
        metadata=package_metadata,
        files=["SmartWagers/views.py"],
        deleted=[],
        hooks=apply_hooks,
        minimum_free_bytes=0,
        log=lambda message: None,
    )
    assert result.ok is False
    assert result.stage == stage_name
    assert "password=<redacted>" in result.message
    assert (target / "SmartWagers" / "views.py").read_text(encoding="utf-8") == "old\n"
    assert not (target / "deploy" / ".deployed_release.json").exists()
    report = json.loads((target / "deploy" / ".last_deploy_failure.json").read_text(encoding="utf-8"))
    assert report["rolled_back"] is True
    if package_metadata["requires_migrate"]:
        assert any(name == "restore" for name, _args in calls)


def test_disk_and_python_failures_do_not_stop_service(engine, tmp_path):
    target, package = make_site(tmp_path)
    apply_hooks, calls = hooks(engine, python_version=(3, 11))
    result = engine.apply_package(
        target=target,
        package_root=package,
        metadata=metadata(),
        files=["SmartWagers/views.py"],
        deleted=[],
        hooks=apply_hooks,
        minimum_free_bytes=0,
        log=lambda message: None,
    )
    assert result.ok is False
    assert result.stage == "verify"
    assert "Python" in result.message
    assert calls == []

    apply_hooks, calls = hooks(engine)
    result = engine.apply_package(
        target=target,
        package_root=package,
        metadata=metadata(),
        files=["SmartWagers/views.py"],
        deleted=[],
        hooks=apply_hooks,
        minimum_free_bytes=10**18,
        log=lambda message: None,
    )
    assert "disk space" in result.message
    assert calls == []


def test_schema_downgrade_is_rejected(engine, tmp_path):
    target, package = make_site(tmp_path)
    (target / "deploy" / ".deployed_release.json").write_text(
        json.dumps({"commit_sha": "old", "schema_level": "0051_eventreportemail"}) + "\n",
        encoding="utf-8",
    )
    package_metadata = metadata()
    package_metadata["schema_level"] = "0050_mark_and_backfill_opening_funds"
    package_metadata["allow_from_any_older"] = False
    apply_hooks, calls = hooks(engine)
    result = engine.apply_package(
        target=target,
        package_root=package,
        metadata=package_metadata,
        files=["SmartWagers/views.py"],
        deleted=[],
        hooks=apply_hooks,
        minimum_free_bytes=0,
        log=lambda message: None,
    )
    assert result.ok is False
    assert "downgrade" in result.message
    assert calls == []


def test_operator_rollback_restores_previous_snapshot(engine, tmp_path):
    target, package = make_site(tmp_path)
    backup = tmp_path / "db.dump"
    backup.write_bytes(b"dump")
    apply_hooks, _calls = hooks(engine, backup_database=lambda: backup)
    engine.apply_package(
        target=target,
        package_root=package,
        metadata=metadata(),
        files=["SmartWagers/views.py"],
        deleted=[],
        hooks=apply_hooks,
        minimum_free_bytes=0,
        log=lambda message: None,
    )
    assert (target / "SmartWagers" / "views.py").read_text(encoding="utf-8") == "new\n"
    rollback_hooks, calls = hooks(engine)
    result = engine.rollback_release(target, hooks=rollback_hooks, log=lambda message: None)
    assert result.ok is True
    assert (target / "SmartWagers" / "views.py").read_text(encoding="utf-8") == "old\n"
    assert any(name == "restore" for name, _args in calls)
