from app.approval_review import build_review_contract
from app.native_connectors import NATIVE_CONNECTORS, native_manifest


def _capability(provider: str, operation: str) -> dict:
    return next(
        item
        for item in native_manifest(provider)["capabilities"]
        if item["name"] == operation
    )


def test_email_review_contract_is_editable_and_schema_driven():
    contract = build_review_contract(
        "gmail.send",
        {"to": "person@example.com", "subject": "Forecast", "body": "Hello"},
        _capability("google", "gmail.send"),
        "Gmail",
    )

    assert contract["kind"] == "email"
    assert contract["title"] == "Review the email before sending"
    assert {field["key"] for field in contract["fields"]} >= {"to", "subject", "body"}
    assert ["to"] in contract["editable_paths"]
    body = next(field for field in contract["fields"] if field["key"] == "body")
    assert body["control"] == "textarea"
    assert body["required"] is True


def test_presentation_review_contract_keeps_structured_phases_editable():
    contract = build_review_contract(
        "canva.presentation.create",
        {"title": "Roadmap", "phases": [{"period": "Q1", "title": "Launch", "items": ["Ship"]}]},
        _capability("canva", "canva.presentation.create"),
        "Canva",
    )

    assert contract["kind"] == "presentation"
    phases = next(field for field in contract["fields"] if field["key"] == "phases")
    assert phases["control"] == "json"
    assert phases["item_schema"]["properties"]["items"]["type"] == "array"
    assert ["phases"] in contract["editable_paths"]


def test_unknown_consequential_action_still_gets_a_complete_generic_editor():
    capability = {
        "description": "Create an approved custom object.",
        "input_schema": {
            "type": "object",
            "required": ["name", "payload"],
            "properties": {
                "name": {"type": "string"},
                "payload": {"type": "object"},
                "enabled": {"type": "boolean"},
            },
        },
    }
    contract = build_review_contract(
        "custom.object.create",
        {"name": "Example", "payload": {"score": 9}, "enabled": True},
        capability,
        "Custom agent",
    )

    assert contract["kind"] == "action"
    assert contract["editable_paths"] == [["name"], ["payload"], ["enabled"]]
    assert [field["control"] for field in contract["fields"]] == ["text", "json", "checkbox"]


def test_every_native_consequential_action_has_a_reviewable_field_contract():
    for provider, definition in NATIVE_CONNECTORS.items():
        manifest = native_manifest(provider)
        for capability in manifest["capabilities"]:
            if not capability["requires_approval"]:
                continue
            properties = capability["input_schema"].get("properties", {})
            example_arguments = {
                key: (
                    []
                    if schema.get("type") == "array"
                    else {}
                    if schema.get("type") == "object"
                    else False
                    if schema.get("type") == "boolean"
                    else 1
                    if schema.get("type") in {"integer", "number"}
                    else "example"
                )
                for key, schema in properties.items()
            }
            contract = build_review_contract(
                capability["name"],
                example_arguments,
                capability,
                definition["name"],
            )

            assert [field["key"] for field in contract["fields"]] == list(properties)
            assert all(field["editable"] for field in contract["fields"])
