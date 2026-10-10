import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def metadata_module():
    return load_module("release_metadata_for_test", PROJECT_ROOT / "deploy" / "release_metadata.py")


def test_schema_policy_rejects_downgrade_and_unsafe_skip(metadata_module):
    metadata = {
        "schema_level": "0050_mark_and_backfill_opening_funds",
        "min_schema": "0048_example",
        "allow_from_any_older": False,
    }
    with pytest.raises(ValueError, match="downgrade"):
        metadata_module.assert_schema_compatible("0051_eventreportemail", metadata)
    with pytest.raises(ValueError, match="unsafe migration skip"):
        metadata_module.assert_schema_compatible("0040_backfill_transaction_generations", metadata)
    metadata_module.assert_schema_compatible("0049_example", metadata)


def test_full_release_allows_older_schema(metadata_module):
    metadata = {
        "schema_level": "0051_eventreportemail",
        "min_schema": "0001_initial",
        "allow_from_any_older": True,
    }
    metadata_module.assert_schema_compatible("0001_initial", metadata)


def test_print_agent_contract(metadata_module):
    assert metadata_module.is_agent_compatible("1.13.2-shared-printer")
    assert not metadata_module.is_agent_compatible("1.13.1-shared-printer")
    outdated = metadata_module.outdated_agents(
        [{"host": "teller-1", "version": "1.13.0"}, {"host": "teller-2", "version": "1.13.2-shared-printer"}]
    )
    assert outdated == [{"host": "teller-1", "version": "1.13.0", "minimum": "1.13.2-shared-printer"}]


def test_compose_metadata_includes_release_identity(metadata_module):
    metadata = metadata_module.compose_package_metadata(
        files=["SmartWagers/views.py"],
        deleted_files=[],
        checksums={"SmartWagers/views.py": "abc"},
        base_ref=None,
        head_ref="abc123",
        requires_dependencies=False,
        artifact_kind="full",
        project_root=PROJECT_ROOT,
    )
    assert metadata["package_version"] == 2
    assert metadata["app_version"] == "1.14.0"
    assert metadata["commit_sha"] == "abc123"
    assert metadata["required_python"] == "3.12"
    assert metadata["schema_level"] == "0051_eventreportemail"
    assert metadata["allow_from_any_older"] is True
    assert metadata["print_agent_min_version"] == "1.13.2-shared-printer"
    assert metadata["print_agent_version"] == "1.13.2-shared-printer"
