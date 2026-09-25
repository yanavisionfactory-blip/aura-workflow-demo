from app.approval_review import (
    build_review_contract,
    public_review_preview,
    public_step_arguments,
)
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


def test_google_doc_review_displays_full_editable_content():
    contract = build_review_contract(
        "docs.create",
        {"title": "Brief", "body": "Complete approved document body."},
        _capability("google", "docs.create"),
        "Google Docs",
    )

    assert contract["kind"] == "document"
    assert ["title"] in contract["editable_paths"]
    assert ["body"] in contract["editable_paths"]
    body = next(field for field in contract["fields"] if field["key"] == "body")
    assert body["control"] == "textarea"
    assert body["required"] is True


def test_notion_to_jira_batch_review_has_task_title_and_source_block_contract():
    contract = build_review_contract(
        "jira.issues.create_from_blocks",
        {"source_blocks": [{"type": "to_do", "to_do": {"rich_text": [{"plain_text": "Ship"}]}}]},
        _capability("jira", "jira.issues.create_from_blocks"),
        "Jira",
    )

    assert contract["title"] == "Review Jira tasks before creating them"
    assert next(field for field in contract["fields"] if field["key"] == "source_blocks")["required"]


def test_email_review_contract_replaces_attachment_transport_with_receipt():
    contract = build_review_contract(
        "gmail.send",
        {
            "to": "me",
            "body": "Attached",
            "attachments": [{
                "filename": "Munich weather.pdf",
                "url": "https://export-download.canva.com/private?signature=secret",
                "sha256": "a" * 64,
            }],
        },
        _capability("google", "gmail.send"),
        "Gmail",
    )

    assert "attachments" not in {field["key"] for field in contract["fields"]}
    assert contract["artifacts"] == [{
        "kind": "attachment",
        "name": "Munich weather.pdf",
        "source": "Prepared from the approved Canva presentation",
    }]

    public = public_review_preview({
        "status": "ready",
        "operation": "gmail.send",
        "arguments": {
            "to": "me",
            "body": "Attached",
            "attachments": [{
                "filename": "Munich weather.pdf",
                "url": "https://export-download.canva.com/private?signature=secret",
            }],
        },
        "review_contract": contract,
    })
    assert public["arguments"] == {"to": "me", "body": "Attached"}
    assert "signature=secret" not in str(public)
    assert public_step_arguments(
        "gmail.send",
        {
            "to": "me",
            "body": "Attached",
            "attachments": [{"url": "https://secret.example/signed"}],
        },
    ) == {"to": "me", "body": "Attached"}


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

            expected = [
                key for key in properties
                if not (capability["name"] == "gmail.send" and key == "attachments")
            ]
            assert [field["key"] for field in contract["fields"]] == expected
            assert all(field["editable"] for field in contract["fields"])
