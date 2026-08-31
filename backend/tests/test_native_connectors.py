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


def test_notion_catalog_exposes_read_and_approved_write_modules():
    manifest = native_manifest("notion")
    operations = native_operations("notion")
    assert "notion.search" in operations
    assert "notion.page.create" in operations
    create = next(item for item in manifest["capabilities"] if item["name"] == "notion.page.create")
    assert create["requires_approval"] is True
    validate_module_arguments(
        manifest,
        "notion.page.create",
        {"parent": {"page_id": "page"}, "properties": {"title": {"title": []}}},
    )


def test_tiktok_catalog_separates_reads_from_approved_posts():
    manifest = native_manifest("tiktok")
    operations = native_operations("tiktok")
    assert "tiktok.profile.get" in operations
    assert "tiktok.videos.list" in operations
    assert "tiktok.video.upload.init" in operations
    upload = next(
        item for item in manifest["capabilities"]
        if item["name"] == "tiktok.video.upload.init"
    )
    assert upload["permission_scope"] == "write"
    assert upload["requires_approval"] is True
    validate_module_arguments(
        manifest,
        "tiktok.video.upload.init",
        {"source_info": {"source": "PULL_FROM_URL", "video_url": "https://example.com/video.mp4"}},
    )


def test_mailchimp_catalog_requires_approval_for_contact_and_campaign_writes():
    manifest = native_manifest("mailchimp")
    operations = native_operations("mailchimp")
    assert "mailchimp.audiences.list" in operations
    assert "mailchimp.member.upsert" in operations
    assert "mailchimp.campaign.send" in operations
    send = next(
        item for item in manifest["capabilities"]
        if item["name"] == "mailchimp.campaign.send"
    )
    assert send["permission_scope"] == "write"
    assert send["requires_approval"] is True
    validate_module_arguments(
        manifest,
        "mailchimp.member.upsert",
        {"list_id": "list", "email_address": "person@example.com"},
    )
