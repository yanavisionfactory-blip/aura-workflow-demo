from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.google_ads_errors import diagnose, message
from app.google_ads_reporting import REPORT_RESOURCES, normalize_report_arguments
from app.native_connectors import NativeConnectorError, normalize_planned_module_arguments
from app.pipedream_connect import PipedreamClient, PipedreamConnectError, _prop_schema
from app.policy import operation_scope
from app.schemas import CriticDecision

OPERATION = "google-ads.create-customer-report"


@pytest.mark.parametrize("operation", REPORT_RESOURCES)
async def test_accepted_google_report_is_a_verified_read_receipt(monkeypatch, operation):
    from app import orchestrator

    monkeypatch.setattr(orchestrator, "check_provider_outcome", AsyncMock(return_value={"status": "unsupported"}))
    critic = AsyncMock(return_value=CriticDecision(action="accept", reasons=["Report matches the requested scope"]))
    monkeypatch.setattr(orchestrator, "critique_step", critic)
    step = SimpleNamespace(operation=operation, output={})
    receipt = {"ret": [{"campaign": {"id": "1"}, "metrics": {"clicks": "12"}}]}
    decision = await orchestrator.review_recorded_result(None, None, step, None, {}, receipt)

    assert operation_scope(operation) == "read"
    assert decision.action == "accept"
    critic.assert_awaited_once()
    assert step.output["outcome_check"] == {
        "status": "verified", "mode": "accepted_read_receipt", "operation": operation,
    }


@pytest.mark.parametrize("case", ["incomplete", "policy"])
async def test_report_read_classification_does_not_accept_missing_or_unsafe_evidence(monkeypatch, case):
    from app import orchestrator

    monkeypatch.setattr(orchestrator, "check_provider_outcome", AsyncMock(return_value={"status": "unsupported"}))
    monkeypatch.setattr(orchestrator, "critique_step", AsyncMock(return_value=CriticDecision(
        action="escalate", policy_violations=["Response exceeds approved scope"],
    )))
    step = SimpleNamespace(operation=OPERATION, output={})
    receipt = {"ret": []}
    if case == "incomplete":
        receipt["nextPageToken"] = "remaining-page"
    decision = await orchestrator.review_recorded_result(
        None, None, step, None, {"required_evidence": ["complete_collection"]}, receipt,
    )
    assert decision.action == "escalate"
    assert step.output.get("outcome_check", {}).get("status") != "verified"


@pytest.mark.parametrize("operation,scope", [
    ("google-ads.create-campaign", "write"),
    ("google-ads.update-campaign", "write"),
    ("google-ads.delete-campaign", "destructive"),
    ("google-ads.create-custom-report", "write"),
    ("other.create-campaign-report", "write"),
])
def test_report_read_exceptions_are_exact_and_leave_writes_governed(operation, scope):
    assert operation_scope(operation) == scope


@pytest.mark.parametrize("options", [["clicks", "cost_micros"], [
    {"label": "Clicks", "value": "clicks"}, {"label": "Cost", "value": "cost_micros"},
]])
def test_action_choices_constrain_items_and_retain_values(options):
    schema = _prop_schema({"type": "string[]", "options": options})
    assert "enum" not in schema
    assert schema["items"]["enum"] == ["clicks", "cost_micros"]
    assert _prop_schema({"type": "string", "options": options})["enum"] == ["clicks", "cost_micros"]


def test_action_choices_do_not_truncate_valid_options():
    values = [str(i) for i in range(600)]
    assert _prop_schema({"options": values})["enum"] == values
    assert "enum" not in _prop_schema({"options": [{"label": "No value"}]})


@pytest.mark.parametrize("operation,resource", REPORT_RESOURCES.items())
def test_report_normalization_preserves_scope_and_fixes_empty_filter(operation, resource):
    original = {"accountId": "manager", "customerClientId": "client", "objectFilter": [],
                "fields": ["id"], "metrics": ["clicks", "metrics.cost_micros"],
                "segments": ["date"], "dateRange": "LAST_7_DAYS"}
    before = deepcopy(original)
    result = normalize_report_arguments(operation, original)
    assert original == before
    assert "objectFilter" not in result
    assert result == {"accountId": "manager", "customerClientId": "client",
                      "fields": [f"{resource}.id"], "metrics": ["metrics.clicks", "metrics.cost_micros"],
                      "segments": ["segments.date"], "dateRange": "LAST_7_DAYS"}
    assert normalize_report_arguments(operation, result) == result
    assert normalize_report_arguments(operation, {"objectFilter": ["123"]}) == {"objectFilter": ["123"]}


@pytest.mark.parametrize("args,error", [
    ({"dateRange": "ALL_TIME"}, "ALL_TIME is not supported"),
    ({"dateRange": []}, "supported GAQL"),
    ({"dateRange": "CUSTOM"}, "requires valid"),
    ({"dateRange": "CUSTOM", "startDate": "2026-02-30", "endDate": "2026-03-01"}, "requires valid"),
    ({"dateRange": "CUSTOM", "startDate": "2026-02-01", "endDate": "2025-03-01"}, "on or before"),
    ({"startDate": "2026-01-01", "endDate": "2026-02-01"}, "require dateRange: CUSTOM"),
    ({"segments": ["date"]}, "date segments require"),
    ({"segments": ["segments.month"]}, "date segments require"),
    ({"orderBy": "segments.date"}, "date segments require"),
    ({"fields": ["campaign.name"]}, "customer namespace"),
    ({"fields": ["metrics.clicks"]}, "customer namespace"),
    ({"metrics": ["customer.id"]}, "metrics namespace"),
    ({"metrics": "clicks"}, "must be an array"),
    ({"metrics": ["clicks FROM campaign"]}, "invalid field name"),
])
def test_bad_report_settings_fail_before_dispatch(args, error):
    with pytest.raises(ValueError, match=error):
        normalize_report_arguments(OPERATION, args)


def test_lifetime_and_custom_ranges_preserve_requested_coverage():
    lifetime = {"fields": ["customer.id"], "metrics": ["metrics.clicks"], "segments": []}
    assert normalize_report_arguments(OPERATION, lifetime) == lifetime
    custom = {**lifetime, "dateRange": "CUSTOM", "startDate": "2024-02-29", "endDate": "2026-11-06"}
    assert normalize_report_arguments(OPERATION, custom) == custom
    nondate = {**lifetime, "segments": ["segments.device"]}
    assert normalize_report_arguments(OPERATION, nondate) == nondate


@pytest.mark.parametrize("value", ["conversion_value", "metrics.conversion_value"])
@pytest.mark.parametrize("operation", REPORT_RESOURCES)
def test_live_rejected_conversion_value_alias_uses_google_plural_field(value, operation):
    args = {"metrics": ["clicks", value, "metrics.all_conversions_value"], "segments": []}
    assert normalize_report_arguments(operation, args) == {
        "metrics": ["metrics.clicks", "metrics.conversions_value", "metrics.all_conversions_value"],
        "segments": [],
    }


def test_typed_references_defer_until_resolved_but_never_reach_the_broker():
    args = {"metrics": "{{steps.fields.metrics}}", "dateRange": "{{inputs.period}}"}
    assert normalize_report_arguments(OPERATION, args, allow_references=True) == args
    with pytest.raises(ValueError):
        normalize_report_arguments(OPERATION, args)


@pytest.mark.parametrize("prefix", ["", "campaign."])
def test_removed_campaign_date_fields_use_v23_replacements(prefix):
    operation = "google-ads.create-campaign-report"
    args = {"fields": ["campaign.id", f"{prefix}start_date", f"{prefix}end_date"],
            "metrics": ["metrics.clicks"], "segments": [], "orderBy": "campaign.start_date"}
    original = deepcopy(args)
    result = normalize_report_arguments(operation, args)
    assert args == original
    assert result == {"fields": ["campaign.id", "campaign.start_date_time", "campaign.end_date_time"],
                      "metrics": ["metrics.clicks"], "segments": [], "orderBy": "campaign.start_date_time"}
    assert normalize_report_arguments(operation, result) == result


async def test_broker_repairs_removed_campaign_dates_in_saved_plans():
    client = PipedreamClient(Settings(pipedream_project_id="project"))
    client._request = AsyncMock(return_value={"results": []})
    cap = {"name": "google-ads.create-campaign-report",
           "metadata": {"connector_broker": {"provider": "google-ads"}},
           "transport": {"type": "pipedream_action", "action_id": "google_ads-create-campaign-report", "auth_prop": "google_ads"}}
    await client.run_action("owner", "grant", cap, {
        "accountId": "manager", "customerClientId": "client",
        "fields": ["campaign.start_date", "campaign.end_date"], "segments": [],
    })
    props = client._request.call_args.kwargs["json"]["configured_props"]
    assert props["fields"] == ["campaign.start_date_time", "campaign.end_date_time"]
    assert props["accountId"] == "manager" and props["customerClientId"] == "client"
    assert "dateRange" not in props


def test_old_and_new_manifest_inputs_receive_checks_before_schema_validation():
    for enums in (False, True):
        properties = {"dateRange": {"type": "string"}, "metrics": {"type": "array", "items": {"type": "string"}}}
        if enums:
            properties["metrics"]["items"]["enum"] = ["metrics.clicks", "metrics.conversions_value"]
        manifest = {"capabilities": [{"name": OPERATION, "input_schema": {"type": "object", "properties": properties}}]}
        assert normalize_planned_module_arguments(manifest, OPERATION, {"metrics": ["clicks"]}) == {"metrics": ["metrics.clicks"]}
        assert normalize_planned_module_arguments(manifest, OPERATION, {"metrics": ["conversion_value"]}) == {"metrics": ["metrics.conversions_value"]}
        with pytest.raises(NativeConnectorError, match="ALL_TIME"):
            normalize_planned_module_arguments(manifest, OPERATION, {"date_range": "ALL_TIME"})


async def test_broker_checks_resolved_arguments_and_preserves_account_binding():
    client = PipedreamClient(Settings(pipedream_project_id="project"))
    client._request = AsyncMock(return_value={"results": []})
    cap = {"name": OPERATION, "metadata": {"connector_broker": {"provider": "google-ads"}},
           "transport": {"type": "pipedream_action", "action_id": "google_ads-create-customer-report", "auth_prop": "google_ads"}}
    args = {"accountId": "manager", "customerClientId": "client", "objectFilter": [],
            "metrics": ["clicks", "metrics.conversion_value"], "segments": [], "dateRange": "LAST_7_DAYS"}
    await client.run_action("owner", "grant", cap, args)
    payload = client._request.call_args.kwargs["json"]
    assert payload["external_user_id"] == "owner"
    assert payload["configured_props"] == {"accountId": "manager", "customerClientId": "client",
        "metrics": ["metrics.clicks", "metrics.conversions_value"], "segments": [], "dateRange": "LAST_7_DAYS",
        "google_ads": {"authProvisionId": "grant"}}
    client._request.reset_mock()
    with pytest.raises(PipedreamConnectError, match="ALL_TIME") as error:
        await client.run_action("owner", "grant", cap, {**args, "dateRange": "ALL_TIME"})
    assert not error.value.retryable
    client._request.assert_not_called()


@pytest.mark.parametrize("key,code", [
    ("queryError", "UNRECOGNIZED_FIELD"),
    ("queryError", "REQUESTED_METRICS_FOR_MANAGER"),
    ("queryError", "INVALID_VALUE_WITH_DURING_OPERATOR"),
    ("queryError", "EXPECTED_FILTERS_ON_DATE_RANGE"),
    ("dateRangeError", "START_DATE_AFTER_END_DATE"),
    ("dateError", "INVALID_DATE"),
])
def test_specific_query_reason_wins_over_invalid_argument_without_leaking_payload(key, code):
    error = {"code": 400, "status": "INVALID_ARGUMENT", "details": [{"errors": [
        {"errorCode": {key: code}, "trigger": {"stringValue": "SECRET"}, "message": "PRIVATE"}]}]}
    assert diagnose(error) == (code, 400)
    assert "PRIVATE" not in message(code) and "SECRET" not in message(code)


def test_unrelated_operations_are_unchanged():
    args = {"dateRange": "ALL_TIME", "fields": ["campaign.name"]}
    assert normalize_report_arguments("other.create-report", args) == args
