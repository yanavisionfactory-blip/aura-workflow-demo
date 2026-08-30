import pytest

from app.native_connectors import (
    NativeConnectorError,
    native_manifest,
    native_operations,
    public_catalog,
    validate_module_arguments,
)


def test_native_catalog_exposes_composable_module_types():
    slack = public_catalog("slack")
    assert {module["type"] for module in slack["modules"]} == {"search", "action"}
    assert native_operations("slack") == ["slack.channels.list", "slack.post"]


def test_native_manifest_has_versioned_schema_and_transport():
    manifest = native_manifest("airtable")
    assert manifest["schema_version"] == "1.1"
    assert manifest["catalog_version"] == 1
    create = next(item for item in manifest["capabilities"] if item["name"] == "airtable.create")
    assert create["module_type"] == "action"
    assert create["transport"] == {"builtin": "airtable.create"}
    assert create["requires_approval"] is True


def test_module_arguments_require_declared_inputs():
    manifest = native_manifest("airtable")
    with pytest.raises(NativeConnectorError, match="missing required inputs"):
        validate_module_arguments(manifest, "airtable.create", {"base_id": "app123"})


def test_module_arguments_reject_undeclared_inputs():
    manifest = native_manifest("slack")
    with pytest.raises(NativeConnectorError, match="unknown inputs"):
        validate_module_arguments(
            manifest,
            "slack.post",
            {"channel": "C123", "text": "hello", "admin_override": True},
        )


def test_valid_module_arguments_pass():
    validate_module_arguments(
        native_manifest("slack"),
        "slack.post",
        {"channel": "C123", "text": "hello"},
    )
