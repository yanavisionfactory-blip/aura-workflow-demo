"""Reddit Ads read access. App credentials belong to AURA, never its customers."""
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .config import get_settings

ORIGIN = "https://ads-api.reddit.com"
BASE = ORIGIN + "/api/v3"
OPERATIONS = frozenset({"reddit-ads.identity.get", "reddit-ads.businesses.list",
                        "reddit-ads.accounts.list", "reddit-ads.campaigns.list", "reddit-ads.report.get"})
ACCOUNT_ID = r"^(?:t2|a2)_[A-Za-z0-9]+$"
REPORT_FIELDS = ["CAMPAIGN_ID", "CURRENCY", "SPEND", "IMPRESSIONS", "CLICKS",
                 "CONVERSION_PURCHASE_CLICKS", "CONVERSION_PURCHASE_VIEWS",
                 "CONVERSION_PURCHASE_TOTAL_VALUE"]


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ad_account_id: str = Field(pattern=ACCOUNT_ID, max_length=120)
    since: date | None = None
    until: date | None = None


def _report_window(request, now):
    # Reddit retains 24 months of delivery data. Never label that full lifetime.
    try:
        earliest = now.date().replace(year=now.year - 2)
    except ValueError:  # Leap day, with a non-leap retention boundary.
        earliest = date(now.year - 2, 2, 28)
    requested_since = request.since or earliest
    requested_until = request.until or now.date()
    if requested_since > requested_until or requested_until > now.date():
        raise ValueError("Choose ordered Reddit reporting dates ending no later than today (UTC).")
    since = max(requested_since, earliest)
    start = datetime.combine(since, datetime.min.time(), UTC)
    end = min(datetime.combine(requested_until + timedelta(days=1), datetime.min.time(), UTC),
              now.replace(minute=0, second=0, microsecond=0))
    if start >= end:
        raise ValueError("The requested dates contain no completed hours within Reddit's 24-month reporting window.")
    return start, end, requested_since < earliest


def _metric(row, key, divisor=1):
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Reddit Ads returned an invalid numeric metric.")  # noqa: TRY004
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError("Reddit Ads returned an invalid numeric metric.")
    return float(number / divisor) if divisor != 1 else value


async def performance_report(credentials, arguments):
    request = ReportRequest.model_validate(arguments)
    now = datetime.now(UTC)
    start, end, limited = _report_window(request, now)
    path = f"/ad_accounts/{request.ad_account_id}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        account = (await _get(client, BASE + path, credentials)).get("data")
        if not isinstance(account, dict) or account.get("id") != request.ad_account_id:
            raise ValueError("Reddit Ads returned a different advertising account.")
        account = {key: account[key] for key in (
            "id", "name", "currency", "time_zone_id", "created_at", "attribution_type",
            "click_attribution_window", "view_attribution_window",
        ) if key in account}
        body = {"data": {"starts_at": start.strftime("%Y-%m-%dT%H:00:00Z"),
                         "ends_at": end.strftime("%Y-%m-%dT%H:00:00Z"),
                         "breakdowns": ["CAMPAIGN_ID"], "fields": REPORT_FIELDS,
                         "time_zone_id": "UTC"}}
        url, visited, raw_rows, updated = BASE + path + "/reports", set(), [], []
        while url:
            target = urlsplit(url)
            if (target.scheme != "https" or target.netloc != "ads-api.reddit.com"
                    or target.path != "/api/v3" + path + "/reports" or target.fragment
                    or url in visited or len(visited) >= 25):
                raise ValueError("Reddit Ads reporting pagination could not be completed.")
            visited.add(url)
            response = await client.post(url, headers=headers(credentials), json=body)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("error") or payload.get("errors"):
                raise ValueError("Reddit Ads returned an invalid report.")
            data = payload.get("data")
            metrics = data.get("metrics") if isinstance(data, dict) else None
            pagination = payload.get("pagination")
            if (not isinstance(metrics, list) or any(not isinstance(row, dict) for row in metrics)
                    or not isinstance(pagination, dict)):
                raise ValueError("Reddit Ads returned an incomplete report.")
            raw_rows.extend(metrics)
            if len(raw_rows) > 5000:
                raise ValueError("Reddit Ads report exceeds the supported size. Use a shorter period.")
            if data.get("metrics_updated_at"):
                updated.append(data["metrics_updated_at"])
            url = pagination.get("next_url")
            if url is not None and not isinstance(url, str):
                raise ValueError("Reddit Ads returned invalid report pagination.")
    campaigns = (await collection(credentials, path + "/campaigns"))["data"]
    metadata = {row["id"]: row for row in campaigns}
    rows, seen = [], set()
    for source in raw_rows:
        campaign_id = source.get("campaign_id")
        if not isinstance(campaign_id, str) or not campaign_id or campaign_id in seen:
            raise ValueError("Reddit Ads returned missing or duplicate campaign report IDs.")
        seen.add(campaign_id)
        currency = source.get("currency") or account.get("currency")
        if source.get("currency") and account.get("currency") and currency != account["currency"]:
            raise ValueError("Reddit Ads report currency does not match the advertising account.")
        spend = _metric(source, "spend", 1_000_000)
        impressions, clicks = _metric(source, "impressions"), _metric(source, "clicks")
        click_purchases = _metric(source, "conversion_purchase_clicks")
        view_purchases = _metric(source, "conversion_purchase_views")
        purchases = (click_purchases + view_purchases
                     if click_purchases is not None and view_purchases is not None else None)
        value = _metric(source, "conversion_purchase_total_value", 100)
        rows.append({"campaign_id": campaign_id, "campaign_name": metadata.get(campaign_id, {}).get("name"),
                     "currency": currency, "spend": spend, "impressions": impressions, "clicks": clicks,
                     "ctr": clicks / impressions if impressions and clicks is not None else None,
                     "cpc": spend / clicks if clicks and spend is not None else None,
                     "purchase_click_conversions": click_purchases, "purchase_view_conversions": view_purchases,
                     "purchase_conversions": purchases, "purchase_conversion_value": value,
                     "purchase_cpa": spend / purchases if purchases and spend is not None else None,
                     "purchase_roas": value / spend if spend and value is not None else None})
    return {"source_provider": "reddit-ads", "vendor_api_called": True, "complete": True,
            "account_id": request.ad_account_id, "account": account, "data": rows, "raw_data": raw_rows,
            "campaigns": campaigns, "campaigns_without_report_rows": sorted(set(metadata) - seen),
            "row_count": len(rows), "date_range": {**{key: body["data"][key] for key in ("starts_at", "ends_at")},
                "timezone": "UTC", "requested_since": request.since.isoformat() if request.since else None,
                "requested_until": request.until.isoformat() if request.until else None,
                "retention_months": 24, "retention_limit_applied": limited, "completed_hours_only": True},
            "conversion_definition": "Reddit-attributed purchases; click-through and view-through counts are also returned separately. Other conversion events are not included.",
            "notes": ["Delivery history is limited to the last 24 months; this is not necessarily full campaign lifetime.",
                      "Missing metrics and campaigns without report rows are unavailable, not zero.",
                      "Spend is converted from microcurrency and purchase value from cents; CTR is a fraction.",
                      "Recent metrics and historical conversion attribution can change after provider refreshes."],
            "metrics_updated_at": updated, "retrieved_at": now.isoformat()}


class AccountSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_id: UUID
    ad_account_id: str = Field(pattern=ACCOUNT_ID, max_length=120)


def headers(credentials):
    if not isinstance(credentials.get("access_token"), str) or not credentials["access_token"]:
        raise ValueError("Reconnect Reddit Ads to restore access.")
    return {"Authorization": f"Bearer {credentials['access_token']}",
            "Accept": "application/json", "User-Agent": get_settings().reddit_ads_user_agent}


async def _get(client, url, credentials):
    response = await client.get(url, headers=headers(credentials))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("error") or payload.get("errors"):
        raise ValueError("Reddit Ads returned an invalid response. Try again.")
    return payload


async def verify(credentials):
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        payload = await _get(client, BASE + "/me", credentials)
    actor = payload.get("data")
    if not isinstance(actor, dict) or not isinstance(actor.get("id"), str) or not actor["id"]:
        raise ValueError("Reddit Ads did not verify this account.")
    if credentials.get("reddit_ads_identity") and actor["id"] != credentials["reddit_ads_identity"]:
        raise ValueError("Reddit Ads returned a different account. Reconnect to confirm access.")
    return {"ok": True, "status_code": 200,
            "identity": {key: actor[key] for key in ("id", "type", "reddit_username") if key in actor}}


async def collection(credentials, path):
    """Follow only same-origin, same-resource pages; never return a partial list."""
    url, rows, visited = BASE + path, [], set()
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        while url:
            target = urlsplit(url)
            if (target.scheme != "https" or target.netloc != "ads-api.reddit.com"
                    or target.path != "/api/v3" + path or target.fragment
                    or url in visited or len(visited) >= 25):
                raise ValueError("Reddit Ads account list could not be completed. Try again.")
            visited.add(url)
            payload = await _get(client, url, credentials)
            page = payload.get("data")
            if not isinstance(page, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] for row in page
            ):
                raise ValueError("Reddit Ads returned an invalid account list.")
            rows.extend(page)
            if len(rows) > 5000:
                raise ValueError("Reddit Ads returned too many results. Contact AURA support.")
            pagination = payload.get("pagination")
            if not isinstance(pagination, dict):
                raise ValueError("Reddit Ads returned invalid pagination.")  # noqa: TRY004
            url = pagination.get("next_url")
            if url is not None and not isinstance(url, str):
                raise ValueError("Reddit Ads returned invalid pagination.")
    return {"data": rows, "complete": True}


async def execute(credentials, operation, arguments):
    if operation == "reddit-ads.report.get":
        return await performance_report(credentials, arguments)
    if operation == "reddit-ads.identity.get":
        return await verify(credentials)
    if operation == "reddit-ads.businesses.list":
        return await collection(credentials, "/me/businesses")
    if operation == "reddit-ads.accounts.list":
        business = str(UUID(str(arguments.get("business_id", ""))))
        return await collection(credentials, f"/businesses/{business}/ad_accounts")
    if operation == "reddit-ads.campaigns.list":
        account = str(arguments.get("ad_account_id", ""))
        if not re.fullmatch(ACCOUNT_ID, account):
            raise ValueError("Choose a valid Reddit advertising account.")
        return await collection(credentials, f"/ad_accounts/{account}/campaigns")
    raise ValueError("Unsupported Reddit Ads operation")


async def account_options(credentials, business_id=None, search=""):
    businesses = (await collection(credentials, "/me/businesses"))["data"]
    roots = [{"id": str(UUID(row["id"])), "name": str(row.get("name") or row["id"])[:200]} for row in businesses]
    business_id = business_id or (roots[0]["id"] if len(roots) == 1 else None)
    if business_id and business_id not in {row["id"] for row in roots}:
        raise ValueError("That Reddit business is no longer accessible. Refresh the account list.")
    accounts = []
    if business_id:
        result = await collection(credentials, f"/businesses/{business_id}/ad_accounts")
        for row in result["data"]:
            if not re.fullmatch(ACCOUNT_ID, str(row["id"])) or row.get("business_id") != business_id:
                raise ValueError("Reddit Ads returned an unexpected advertising account.")
            name = str(row.get("name") or row["id"])[:200]
            if search.casefold() in name.casefold():
                accounts.append({"business_id": business_id, "ad_account_id": row["id"], "name": name})
    return {"businesses": roots, "business_id": business_id, "accounts": accounts}


def selected_account(tool):
    config = tool.config or {}
    saved = config.get("reddit_ads_account")
    if tool.slug != "reddit-ads" or config.get("managed_by") != "native" or not isinstance(saved, dict):
        return None
    if not tool.external_account_id or saved.get("identity_id") != tool.external_account_id:
        return None
    try:
        AccountSelection.model_validate({key: saved[key] for key in ("business_id", "ad_account_id")})
        return {key: saved[key] for key in ("business_id", "ad_account_id", "name")}
    except (ValueError, KeyError):
        return None


def apply_account_defaults(plan, inventory, manifests, *, prompt=""):
    """Bind missing/model-malformed account IDs to the verified saved choice.

    This runs before plan approval, never during dispatch. Explicit user targets
    and workflow references must still be validated instead of being redirected.
    """
    selected = next((item.get("reddit_ads_account") for item in inventory if item["slug"] == "reddit-ads"), None)
    if not selected:
        return
    for step in plan.steps:
        if step.tool_slug != "reddit-ads":
            continue
        fields = {"reddit-ads.accounts.list": "business_id", "reddit-ads.campaigns.list": "ad_account_id",
                  "reddit-ads.report.get": "ad_account_id"}
        field = fields.get(step.operation)
        if not field or field not in selected:
            continue
        value = step.arguments.get(field)
        saved = selected[field]
        if field == "ad_account_id" and (
            not isinstance(saved, str) or len(saved) > 120 or not re.fullmatch(ACCOUNT_ID, saved)
        ):
            continue
        malformed_generated_id = (
            field == "ad_account_id" and isinstance(value, str) and value
            and "{{" not in value and not re.fullmatch(ACCOUNT_ID, value)
            and value.casefold() not in prompt.casefold()
        )
        if not value or malformed_generated_id:
            step.arguments = {**step.arguments, field: selected[field]}
