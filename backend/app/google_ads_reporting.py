"""Checks for the released Pipedream Google Ads report components.

Apply to stored packs too: fixing discovery schemas alone does not repair
connections which already have an immutable, signed capability manifest.
"""
import re
from datetime import date
from typing import Any

REPORT_RESOURCES = {
    "google-ads.create-customer-report": "customer",
    "google-ads.create-campaign-report": "campaign",
    "google-ads.create-ad-group-report": "ad_group",
    "google-ads.create-ad-report": "ad_group_ad",
}
DATE_RANGES = {
    "CUSTOM", "TODAY", "YESTERDAY", "LAST_7_DAYS", "LAST_BUSINESS_WEEK",
    "THIS_MONTH", "LAST_MONTH", "LAST_14_DAYS", "LAST_30_DAYS",
    "THIS_WEEK_SUN_TODAY", "THIS_WEEK_MON_TODAY", "LAST_WEEK_SUN_SAT",
    "LAST_WEEK_MON_SUN",
}
DATE_SEGMENTS = {f"segments.{part}" for part in ("date", "week", "month", "quarter", "year")}
_ROOTS = set(REPORT_RESOURCES.values()) | {"metrics", "segments", "campaign_budget"}
# The planner used the natural-language singular in a live campaign report.
# Google exposes the conversion-value metric under this plural field name.
_FIELD_ALIASES = {"metrics.conversion_value": "metrics.conversions_value"}
_FIELD = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")
_REFERENCE = re.compile(r"\{\{\s*(?:inputs|vars|steps)\.[a-zA-Z0-9_.\-\[\]'\" ]+\s*\}\}")


def normalize_report_arguments(
    operation: str, arguments: dict[str, Any], *, allow_references: bool = False,
) -> dict[str, Any]:
    resource = REPORT_RESOURCES.get(operation)
    if not resource:
        return arguments
    result = dict(arguments)

    def reference(value):
        return allow_references and isinstance(value, str) and bool(_REFERENCE.fullmatch(value))

    # Pipedream tests length when adding WHERE, but truthiness when adding AND.
    # [] means all resources, just like omission; leaving it set generates an
    # invalid "FROM customer AND segments.date ..." query in the component.
    if result.get("objectFilter") == []:
        result.pop("objectFilter")

    for key, prefix in (("fields", resource), ("segments", "segments"), ("metrics", "metrics")):
        values = result.get(key)
        if values is None or reference(values):
            continue
        if not isinstance(values, list):
            raise ValueError(f"Google Ads {key} must be an array of field names.")  # noqa: TRY004 - plan validation contract
        qualified = []
        for value in values:
            if reference(value):
                qualified.append(value)
                continue
            if not isinstance(value, str) or not _FIELD.fullmatch(value):
                raise ValueError(f"Google Ads {key} contains an invalid field name.")
            root = value.split(".", 1)[0]
            if "." in value and root in _ROOTS and root != prefix:
                raise ValueError(f"Google Ads {key} must use the {prefix} namespace for this report; choose the matching report resource.")
            field = value if value.startswith(f"{prefix}.") else f"{prefix}.{value}"
            qualified.append(_FIELD_ALIASES.get(field, field))
        result[key] = qualified

    date_range = result.get("dateRange")
    if reference(date_range):
        return result  # Check again after typed references are resolved.
    if date_range is not None and (not isinstance(date_range, str) or date_range not in DATE_RANGES):
        raise ValueError("Google Ads dateRange must be a supported GAQL date range or CUSTOM. For full-period totals, omit dateRange and use segments: []; ALL_TIME is not supported.")
    dates = [result.get(key) for key in ("startDate", "endDate")]
    if date_range == "CUSTOM":
        parsed = []
        for value in dates:
            if reference(value):
                parsed.append(None)
                continue
            try:
                if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError
                parsed.append(date.fromisoformat(value))
            except ValueError as exc:
                raise ValueError("Google Ads CUSTOM requires valid startDate and endDate in YYYY-MM-DD format.") from exc
        if all(parsed) and parsed[0] > parsed[1]:
            raise ValueError("Google Ads startDate must be on or before endDate.")
    elif any(value is not None for value in dates):
        raise ValueError("Google Ads startDate/endDate require dateRange: CUSTOM; otherwise the provider ignores those dates.")

    segments = result.get("segments")
    if not date_range and (
        isinstance(segments, list) and any(value in DATE_SEGMENTS for value in segments)
        or isinstance(result.get("orderBy"), str) and result["orderBy"] in DATE_SEGMENTS
    ):
        raise ValueError("Google Ads date segments require a date range. Use explicit dates for a time breakdown, or segments: [] for full-period totals; do not silently drop a requested breakdown.")
    return result
