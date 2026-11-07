from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.google_ads_errors import diagnose, message
from app.google_ads_reporting import REPORT_RESOURCES, normalize_report_arguments
from app.native_connectors import NativeConnectorError, normalize_planned_module_arguments
from app.pipedream_connect import PipedreamClient, PipedreamConnectError, _prop_schema

OPERATION = "google-ads.create-customer-report"


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


def test_typed_references_defer_until_resolved_but_never_reach_the_broker():
    args = {"metrics": "{{steps.fields.metrics}}", "dateRange": "{{inputs.period}}"}
    assert normalize_report_arguments(OPERATION, args, allow_references=True) == args
    with pytest.raises(ValueError):
        normalize_report_arguments(OPERATION, args)


def test_old_and_new_manifest_inputs_receive_checks_before_schema_validation():
    for enums in (False, True):
        properties = {"dateRange": {"type": "string"}, "metrics": {"type": "array", "items": {"type": "string"}}}
        if enums:
            properties["metrics"]["items"]["enum"] = ["metrics.clicks"]
        manifest = {"capabilities": [{"name": OPERATION, "input_schema": {"type": "object", "properties": properties}}]}
        assert normalize_planned_module_arguments(manifest, OPERATION, {"metrics": ["clicks"]}) == {"metrics": ["metrics.clicks"]}
        with pytest.raises(NativeConnectorError, match="ALL_TIME"):
            normalize_planned_module_arguments(manifest, OPERATION, {"date_range": "ALL_TIME"})


async def test_broker_checks_resolved_arguments_and_preserves_account_binding():
    client = PipedreamClient(Settings(pipedream_project_id="project"))
    client._request = AsyncMock(return_value={"results": []})
    cap = {"name": OPERATION, "metadata": {"connector_broker": {"provider": "google-ads"}},
           "transport": {"type": "pipedream_action", "action_id": "google_ads-create-customer-report", "auth_prop": "google_ads"}}
    args = {"accountId": "manager", "customerClientId": "client", "objectFilter": [],
            "metrics": ["clicks"], "segments": [], "dateRange": "LAST_7_DAYS"}
    await client.run_action("owner", "grant", cap, args)
    payload = client._request.call_args.kwargs["json"]
    assert payload["external_user_id"] == "owner"
    assert payload["configured_props"] == {"accountId": "manager", "customerClientId": "client",
        "metrics": ["metrics.clicks"], "segments": [], "dateRange": "LAST_7_DAYS",
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
