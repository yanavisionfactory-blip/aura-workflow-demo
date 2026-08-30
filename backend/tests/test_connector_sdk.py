import pytest

from app.connector_sdk import ConnectorSDKError, validate_connector_definition
from app.security import verify_webhook_signature, webhook_signature


def connector_definition():
    return {
        "schema_version": "1.0",
        "slug": "example",
        "name": "Example",
        "base_url": "https://api.example.com",
        "authentication": {"type": "oauth2"},
        "modules": [
            {
                "name": "records.list",
                "module_type": "search",
                "permission_scope": "read",
                "transport": {"method": "GET", "path": "/records"},
            },
            {
                "name": "records.created",
                "module_type": "trigger",
                "permission_scope": "read",
                "transport": {"type": "webhook", "event": "record.created"},
            },
        ],
    }


def test_connector_sdk_accepts_search_action_and_trigger_modules():
    result = validate_connector_definition(connector_definition())
    assert result["module_count"] == 2
    assert result["manifest"]["capabilities"][1]["module_type"] == "trigger"


def test_connector_sdk_rejects_trigger_without_delivery_transport():
    definition = connector_definition()
    definition["modules"][1]["transport"] = {"method": "GET", "path": "/events"}
    with pytest.raises(ConnectorSDKError, match="webhook or polling"):
        validate_connector_definition(definition)


def test_connector_sdk_rejects_duplicate_names():
    definition = connector_definition()
    definition["modules"][1]["name"] = "records.list"
    with pytest.raises(ConnectorSDKError, match="unique"):
        validate_connector_definition(definition)


def test_webhook_signature_covers_timestamp_and_raw_body():
    secret = "test-secret"
    body = b'{"record":"rec123"}'
    signature = webhook_signature(secret, "1730000000", body)
    assert verify_webhook_signature(secret, "1730000000", body, signature)
    assert not verify_webhook_signature(secret, "1730000001", body, signature)
    assert not verify_webhook_signature(secret, "1730000000", b"{}", signature)
