from types import SimpleNamespace

import pytest

from app.native_connectors import (
    NativeConnectorError,
    coerce_module_arguments,
    current_capability_manifest,
    native_manifest,
    native_operations,
    normalize_module_arguments,
    planning_catalog,
    public_catalog,
    validate_module_arguments,
)
from app.orchestrator import refresh_native_connection_contract


def test_resolved_structured_result_is_coerced_to_connector_text() -> None:
    result = coerce_module_arguments(
        native_manifest("google"),
        "gmail.send",
        {
            "to": "me",
            "body": {"summary": "Sunny in Munich", "temperature_max_c": 24},
        },
    )

    assert result["body"] == "Sunny in Munich"


def test_planning_catalog_includes_unconnected_native_connectors() -> None:
    catalog = {item["slug"]: item for item in planning_catalog({"slack"})}

    assert catalog["slack"]["connected"] is True
    assert catalog["notion"]["connected"] is False
    assert "notion.page.create" in catalog["notion"]["allowed_operations"]
    assert catalog["hubspot"]["connected"] is False
    assert "hubspot.contacts.list" in catalog["hubspot"]["allowed_operations"]
    assert "hubspot.contact.update" in catalog["hubspot"]["allowed_operations"]
    assert catalog["jira"]["connected"] is False
    assert "jira.issues.search" in catalog["jira"]["allowed_operations"]
    assert "jira.issue.create" in catalog["jira"]["allowed_operations"]


def test_native_catalog_exposes_composable_module_types():
    slack = public_catalog("slack")
    assert {module["type"] for module in slack["modules"]} == {"search", "action"}
    assert native_operations("slack") == ["slack.channels.list", "slack.post", "slack.message.get"]


def test_aura_weather_is_connection_free_and_read_only():
    catalog = {item["slug"]: item for item in planning_catalog({"aura"})}
    manifest = native_manifest("aura")
    forecast = next(
        item for item in manifest["capabilities"]
        if item["name"] == "weather.forecast"
    )

    assert catalog["aura"]["connected"] is True
    assert forecast["permission_scope"] == "read"
    assert forecast["requires_approval"] is False
    validate_module_arguments(
        manifest, "weather.forecast", {"location": "Munich", "date": "tomorrow"}
    )

    capabilities = {item["name"]: item for item in manifest["capabilities"]}
    assert capabilities["web.search"]["permission_scope"] == "read"
    assert capabilities["web.page.read"]["permission_scope"] == "read"
    assert capabilities["creator.tiktok.screen"]["permission_scope"] == "read"
    assert capabilities["web.search"]["requires_approval"] is False
    assert capabilities["web.page.read"]["requires_approval"] is False
    assert capabilities["creator.tiktok.screen"]["requires_approval"] is False


def test_google_catalog_can_resolve_and_update_named_spreadsheets():
    manifest = native_manifest("google")
    capabilities = {item["name"]: item for item in manifest["capabilities"]}

    assert capabilities["drive.files.search"]["permission_scope"] == "read"
    assert capabilities["drive.files.search"]["requires_approval"] is False
    assert capabilities["sheets.append"]["permission_scope"] == "write"
    assert capabilities["sheets.append"]["requires_approval"] is True
    assert "sheets.read" in capabilities["sheets.append"]["reliability"][
        "readback_operations"
    ]


def test_planning_refreshes_stale_native_capabilities_without_touching_custom_tools():
    google = SimpleNamespace(slug="google", allowed_operations=["sheets.read"])
    custom = SimpleNamespace(slug="creator-approvals", allowed_operations=["submit"])

    refreshed = refresh_native_connection_contract(google)

    assert refreshed == native_operations("google")
    assert google.allowed_operations == native_operations("google")
    assert "drive.files.search" in google.allowed_operations
    assert "sheets.append" in google.allowed_operations
    assert refresh_native_connection_contract(custom) == ["submit"]
    assert custom.allowed_operations == ["submit"]


def test_module_arguments_normalize_common_model_variants_before_approval():
    normalized = normalize_module_arguments(
        native_manifest("aura"),
        "weather.forecast",
        {"city": "Munich", "forecastDate": "tomorrow"},
    )

    assert normalized == {"location": "Munich", "date": "tomorrow"}


def test_module_argument_normalization_still_rejects_unknown_inputs():
    with pytest.raises(NativeConnectorError, match="unknown inputs"):
        normalize_module_arguments(
            native_manifest("aura"),
            "weather.forecast",
            {"location": "Munich", "admin_override": True},
        )


def test_jira_catalog_requires_approval_for_issue_writes():
    manifest = native_manifest("jira")
    create = next(item for item in manifest["capabilities"] if item["name"] == "jira.issue.create")
    assert create["requires_approval"] is True
    validate_module_arguments(
        manifest,
        "jira.issue.create",
        {"project_key": "AURA", "summary": "Prepare launch brief"},
    )


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


def test_notion_search_accepts_explicit_recency_sorting():
    assert normalize_module_arguments(
        native_manifest("notion"),
        "notion.search",
        {"sort": "last_edited_time", "direction": "descending", "pageSize": 10},
    ) == {
        "sort": "last_edited_time",
        "direction": "descending",
        "page_size": 10,
    }

    with pytest.raises(NativeConnectorError, match="must be one of"):
        normalize_module_arguments(
            native_manifest("notion"),
            "notion.search",
            {"sort": "created_time", "direction": "newest"},
        )


def test_notion_search_accepts_provider_filter_objects():
    assert normalize_module_arguments(
        native_manifest("notion"),
        "notion.search",
        {"filter": {"property": "object", "value": "page"}},
    ) == {"filter": {"property": "object", "value": "page"}}


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


def test_canva_catalog_exposes_design_and_export_modules():
    manifest = native_manifest("canva")
    operations = native_operations("canva")
    assert "canva.designs.list" in operations
    assert "canva.design.create" in operations
    assert "canva.export.create" in operations
    create = next(item for item in manifest["capabilities"] if item["name"] == "canva.design.create")
    assert create["requires_approval"] is True

def test_notion_search_normalizes_common_limit_alias():
    assert normalize_module_arguments(
        native_manifest("notion"),
        "notion.search",
        {"query": "", "limit": 1},
    ) == {"query": "", "page_size": 1}


def test_schema_guided_aliases_normalize_unseen_pagination_variants():
    assert normalize_module_arguments(
        native_manifest("notion"),
        "notion.search",
        {"maxResults": 5, "cursor": "next-page"},
    ) == {"page_size": 5, "start_cursor": "next-page"}


def test_current_capability_manifest_replaces_stale_native_snapshots():
    stale = {"schema_version": "0.1", "capabilities": []}

    manifest = current_capability_manifest("notion", stale)

    assert manifest["schema_version"] != "0.1"
    assert any(
        module["name"] == "notion.page.get" for module in manifest["capabilities"]
    )


def test_current_capability_manifest_keeps_discovered_connector_schema():
    discovered = {
        "schema_version": "9.0",
        "capabilities": [{"name": "custom.read"}],
    }

    assert current_capability_manifest("custom", discovered) is discovered



@pytest.mark.parametrize("value", ["2026-02-30T00:00:00Z", "not a date"])
def test_calendar_rejects_invalid_date_bounds_before_provider(value):
    with pytest.raises(NativeConnectorError, match="RFC3339"):
        normalize_module_arguments(native_manifest("google"), "calendar.list", {"time_min": value})


@pytest.mark.parametrize("value", ["2026-09-11T00:00:00Z", "2026-09-11T00:00:00+02:00", "{{inputs.start}}"])
def test_calendar_accepts_offset_dates_and_declared_references(value):
    result = normalize_module_arguments(native_manifest("google"), "calendar.list", {"time_min": value, "query": "appointment"})
    assert result == {"time_min": value, "query": "appointment"}


@pytest.mark.parametrize("value", ["2026-09-11T00:00:00", "2026-09-11"])
def test_unzoned_calendar_bounds_normalize_to_explicit_utc(value):
    assert normalize_module_arguments(native_manifest("google"), "calendar.list", {"time_min": value})["time_min"] == "2026-09-11T00:00:00+00:00"
