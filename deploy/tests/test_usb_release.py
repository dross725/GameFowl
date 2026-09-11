import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sync_module():
    return load_module("sync_release_for_test", PROJECT_ROOT / "deploy" / "sync_release.py")


@pytest.fixture
def apply_module():
    return load_module("apply_usb_release_for_test", PROJECT_ROOT / "deploy" / "apply_usb_release.py")


@pytest.fixture
def inventory_module():
    return load_module("release_inventory_for_test", PROJECT_ROOT / "deploy" / "release_inventory.py")


def configure_temp_project(monkeypatch, sync_module, tmp_path):
    project = tmp_path / "project"
    deploy = project / "deploy"
    deploy.mkdir(parents=True)
    (deploy / "APPLY_RELEASE.bat").write_text("@echo off\n", encoding="utf-8")
    (deploy / "apply_usb_release.py").write_text("# installer\n", encoding="utf-8")
    (deploy / "11_apply_release.bat").write_text("@echo off\n", encoding="utf-8")
    (deploy / "13_export_server_inventory.bat").write_text("@echo off\n", encoding="utf-8")
    (deploy / "release_inventory.py").write_text("# inventory\n", encoding="utf-8")
    (project / "requirements.txt").write_text("Django==5.1\n", encoding="utf-8")
    app_file = project / "SmartWagers" / "views.py"
    app_file.parent.mkdir()
    app_file.write_text("answer = 42\n", encoding="utf-8")

    monkeypatch.setattr(sync_module, "PROJECT_ROOT", project)
    monkeypatch.setattr(sync_module, "DEPLOY_DIR", deploy)
    monkeypatch.setattr(sync_module, "MANIFEST_PATH", deploy / ".last_sync_manifest")
    monkeypatch.setattr(
        sync_module,
        "PACKAGE_APPLY_FILES",
        (deploy / "APPLY_RELEASE.bat", deploy / "apply_usb_release.py"),
    )
    return project


def test_safe_paths_reject_runtime_state_and_traversal(sync_module):
    assert sync_module.is_safe_relative_path("SmartWagers/views.py")
    assert not sync_module.is_safe_relative_path("../.env")
    assert not sync_module.is_safe_relative_path(".env")
    assert not sync_module.is_safe_relative_path("deploy/python_path.txt")
    assert not sync_module.is_safe_relative_path("SmartWagers/tests/test_views.py")
    # Expo/RN build trees blow past Windows MAX_PATH — never deploy them.
    assert not sync_module.is_safe_relative_path(
        "mobile_print_agent/android/app/build/outputs/apk/release/app-release.apk"
    )
    assert not sync_module.is_safe_relative_path(
        "mobile_print_agent/node_modules/expo/package.json"
    )
    assert sync_module.is_safe_relative_path(
        "mobile_print_agent/dist/SmartWagers-PrintCompanion.apk"
    )
    assert sync_module.is_safe_relative_path("mobile_print_agent/App.tsx")
    # Windows Mark-of-the-Web ADS saved as a real file (invalid ":" name).
    assert not sync_module.is_safe_relative_path(
        "SmartWagers/static/SmartWagers/images/login smartwagers.jpg:Zone.Identifier"
    )


def test_windows_max_path_guard_rejects_oversized_payload(sync_module):
    short = "SmartWagers/views.py"
    # Force a path that exceeds 259 under C:\SmartWagers\GameFowl\
    long_name = "SmartWagers/" + ("a" * 240) + ".py"
    assert sync_module.windows_absolute_path_length(
        sync_module.DEFAULT_WINDOWS_PROD_ROOT, short
    ) <= sync_module.WINDOWS_MAX_PATH
    assert sync_module.windows_absolute_path_length(
        sync_module.DEFAULT_WINDOWS_PROD_ROOT, long_name
    ) > sync_module.WINDOWS_MAX_PATH
    with pytest.raises(SystemExit):
        sync_module.assert_windows_safe_payload_paths([long_name])
    sync_module.assert_windows_safe_payload_paths([short])



def test_collect_deleted_files_keeps_only_safe_paths(monkeypatch, sync_module):
    result = subprocess.CompletedProcess(
        ["git"],
        0,
        "D\tSmartWagers/old.py\nD\t.env\nD\tdeploy/python_path.txt\nD\t../outside.py\n"
        "R100\tSmartWagers/renamed.py\tSmartWagers/new_name.py\n",
        "",
    )
    monkeypatch.setattr(sync_module, "run_git", lambda args: result)

    assert sync_module.collect_deleted_files("abc123", include_tests=False) == [
        "SmartWagers/old.py",
        "SmartWagers/renamed.py",
    ]


def test_build_usb_package_with_checksums_and_wheels(
    monkeypatch, sync_module, apply_module, tmp_path
):
    configure_temp_project(monkeypatch, sync_module, tmp_path)
    monkeypatch.setattr(sync_module, "git_ref_or_none", lambda ref: "1234567890abcdef")

    def fake_download(package_dir):
        wheels = package_dir / "wheels"
        wheels.mkdir()
        (wheels / "Django-5.1-py3-none-any.whl").write_bytes(b"offline wheel")

    monkeypatch.setattr(sync_module, "download_offline_dependencies", fake_download)
    output = tmp_path / "usb"
    package = sync_module.build_usb_package(
        output,
        ["SmartWagers/views.py", "requirements.txt"],
        ["SmartWagers/old.py"],
        base_ref="base123",
        dry_run=False,
    )

    assert package is not None
    assert (package / "payload" / "SmartWagers" / "views.py").is_file()
    assert (package / "payload" / "deploy" / "11_apply_release.bat").is_file()
    assert (package / "wheels" / "Django-5.1-py3-none-any.whl").is_file()
    metadata = json.loads((package / "release.json").read_text(encoding="utf-8"))
    assert metadata["requires_dependencies"] is True
    assert metadata["deleted_files"] == ["SmartWagers/old.py"]
    assert "SmartWagers/views.py" in metadata["checksums"]

    monkeypatch.setattr(apply_module, "PACKAGE_ROOT", package)
    loaded = apply_module.load_metadata()
    files, deleted = apply_module.verify_package(loaded)
    assert "requirements.txt" in files
    assert deleted == ["SmartWagers/old.py"]


def test_dry_run_does_not_create_package(monkeypatch, sync_module, tmp_path):
    configure_temp_project(monkeypatch, sync_module, tmp_path)
    monkeypatch.setattr(sync_module, "git_ref_or_none", lambda ref: None)
    output = tmp_path / "usb"

    result = sync_module.build_usb_package(
        output,
        ["SmartWagers/views.py"],
        [],
        base_ref=None,
        dry_run=True,
    )

    assert result is None
    assert not output.exists()


def test_server_validator_rejects_protected_paths(apply_module):
    for path in (".env", "../outside.py", "deploy/python_path.txt", "staticfiles/app.js"):
        with pytest.raises(apply_module.ReleaseError):
            apply_module.validate_rel_path(path)


def test_inventory_finds_actual_server_differences(inventory_module, tmp_path):
    server = tmp_path / "server"
    local = tmp_path / "local"
    for root in (server, local):
        (root / "SmartWagers").mkdir(parents=True)
        (root / ".env").write_text("SECRET=ignored\n", encoding="utf-8")
        (root / "staticfiles").mkdir()
        (root / "staticfiles" / "app.js").write_text("ignored\n", encoding="utf-8")

    (server / "SmartWagers" / "same.py").write_text("same\n", encoding="utf-8")
    (local / "SmartWagers" / "same.py").write_text("same\n", encoding="utf-8")
    (server / "SmartWagers" / "changed.py").write_text("old\n", encoding="utf-8")
    (local / "SmartWagers" / "changed.py").write_text("new\n", encoding="utf-8")
    (server / "SmartWagers" / "removed.py").write_text("removed\n", encoding="utf-8")
    (local / "SmartWagers" / "added.py").write_text("added\n", encoding="utf-8")

    inventory_path = tmp_path / "server_inventory.json"
    inventory_module.write_inventory(server, inventory_path)
    added, changed, deleted = inventory_module.compare_inventory(local, inventory_path)

    assert added == ["SmartWagers/added.py"]
    assert changed == ["SmartWagers/changed.py"]
    assert deleted == ["SmartWagers/removed.py"]


def test_inventory_skips_unsafe_zone_identifier_entries(inventory_module, tmp_path):
    root = tmp_path / "project"
    (root / "SmartWagers").mkdir(parents=True)
    (root / "SmartWagers" / "views.py").write_text("ok\n", encoding="utf-8")

    inventory_path = tmp_path / "server_inventory.json"
    junk_key = "SmartWagers/static/SmartWagers/images/login smartwagers.jpg\uf03aZone.Identifier"
    inventory_path.write_text(
        json.dumps(
            {
                "inventory_version": 1,
                "files": {
                    "SmartWagers/views.py": {"sha256": "abc", "size": 3},
                    junk_key: {"sha256": "deadbeef", "size": 1},
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = inventory_module.load_inventory(inventory_path)
    assert junk_key not in loaded["files"]
    assert "SmartWagers/static/SmartWagers/images/login smartwagers.jpg:Zone.Identifier" not in loaded["files"]
    assert "SmartWagers/views.py" in loaded["files"]

    added, changed, deleted = inventory_module.compare_inventory(root, inventory_path)
    assert junk_key not in deleted
    assert "SmartWagers/static/SmartWagers/images/login smartwagers.jpg:Zone.Identifier" not in deleted
    # views.py hash differs → changed; no crash on unsafe inventory entry
    assert "SmartWagers/views.py" in changed
    assert added == []


def test_inventory_skips_mobile_print_agent_build_trees(inventory_module, tmp_path):
    root = tmp_path / "project"
    apk = root / "mobile_print_agent" / "dist" / "SmartWagers-PrintCompanion.apk"
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    long_build = (
        root
        / "mobile_print_agent"
        / "android"
        / ".gradle"
        / "8.10.2"
        / "dependencies-accessors"
        / "hash"
        / "classes"
        / "LibrariesForReactAndroidLibsInPluginsBlock$FrescoImagepipelineLibraryAccessors.class"
    )
    long_build.parent.mkdir(parents=True)
    long_build.write_bytes(b"build-cache")
    (root / "mobile_print_agent" / "node_modules" / "expo" / "package.json").parent.mkdir(
        parents=True
    )
    (root / "mobile_print_agent" / "node_modules" / "expo" / "package.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (root / "mobile_print_agent" / "App.tsx").write_text("export {}\n", encoding="utf-8")

    inventory_path = tmp_path / "inventory.json"
    inventory_module.write_inventory(root, inventory_path)
    files = set(json.loads(inventory_path.read_text(encoding="utf-8"))["files"])

    assert "mobile_print_agent/dist/SmartWagers-PrintCompanion.apk" in files
    assert "mobile_print_agent/App.tsx" in files
    assert not any(path.startswith("mobile_print_agent/android/") for path in files)
    assert not any(path.startswith("mobile_print_agent/node_modules/") for path in files)

