"""Read-only Reddit Ads v3 operations; ordinary Reddit access is not Ads access."""

import re
from datetime import UTC, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

API_ROOT = "https://ads-api.reddit.com/api/v3"
USER_AGENT = "web:aura-workflow:1.0 (Reddit Ads reporting)"
OPERATIONS = frozenset({
    "reddit-ads.identity.get", "reddit-ads.businesses.list", "reddit-ads.accounts.list",
    "reddit-ads.account.get", "reddit-ads.campaigns.list", "reddit-ads.ad-groups.list",
    "reddit-ads.ads.list", "reddit-ads.report.get",
})
REPORT_FIELDS = (
    "IMPRESSIONS", "CLICKS", "SPEND", "CTR", "CPC", "ECPM",
    "CONVERSION_PURCHASE_CLICKS", "CONVERSION_PURCHASE_VIEWS",
    "CONVERSION_PURCHASE_TOTAL_VALUE", "CONVERSION_ROAS",
)
REPORT_BREAKDOWNS = ("DATE", "CAMPAIGN_ID", "AD_GROUP_ID", "AD_ID")
MAX_PAGES = 20


class RedditAdsError(ValueError):
    pass


def _id(value: object) -> str:
    value = str(value or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise RedditAdsError("Choose an exact Reddit Ads business or ad account ID.")
    return value


def _headers(credentials: dict) -> dict:
    token = credentials.get("access_token")
    if not isinstance(token, str) or not token:
        raise RedditAdsError("Connect Reddit Ads before reading advertising data.")
    return {"Authorization": f"Bearer {token}", "Accept": "application/json",
            "User-Agent": USER_AGENT}


async def _request(client, method, url, headers, body=None) -> dict:
    response = await client.request(method, url, headers=headers,
                                    **({"json": body} if body is not None else {}))
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict) or result.get("error") or result.get("errors"):
        raise RedditAdsError("Reddit Ads returned an invalid response.")
    return result


def _next_url(result: dict, original_url: str) -> str | None:
    pagination = result.get("pagination") or {}
    if not isinstance(pagination, dict):
        raise RedditAdsError("Reddit Ads returned invalid pagination.")
    value = pagination.get("next_url")
    if not value:
        return None
    if not isinstance(value, str):
        raise RedditAdsError("Reddit Ads returned invalid pagination.")
    target, original = urlsplit(value), urlsplit(original_url)
    if (target.scheme != "https" or target.netloc != "ads-api.reddit.com"
            or target.path != original.path or target.fragment):
        raise RedditAdsError("Reddit Ads pagination changed the requested resource.")
    return value


async def _collection(client, path, headers, *, body=None) -> dict:
    """Follow provider URLs on the same resource; never return a partial total."""
    original_url = API_ROOT + path
    url = original_url
    rows, pages, visited = [], [], set()
    for _ in range(MAX_PAGES):
        if url in visited:
            raise RedditAdsError("Reddit Ads pagination repeated; the result is incomplete.")
        visited.add(url)
        result = await _request(client, "POST" if body is not None else "GET", url, headers, body)
        data = result.get("data")
        batch = data.get("metrics") if isinstance(data, dict) and body is not None else data
        if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
            raise RedditAdsError("Reddit Ads returned an invalid collection.")
        rows.extend(batch)
        pages.append(result)
        url = _next_url(result, original_url)
        if not url:
            return {"data": rows, "raw_pages": pages, "page_count": len(pages),
                    "coverage_complete": True, "source_url": original_url}
    raise RedditAdsError("Reddit Ads result exceeds the page limit; narrow the report before retrying.")


def report_body(arguments: dict) -> dict:
    dates = []
    for key in ("starts_at", "ends_at"):
        value = arguments.get(key, "")
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:00:00Z", value):
            raise RedditAdsError("Use hourly UTC report boundaries: YYYY-MM-DDTHH:00:00Z.")
        try:
            dates.append(datetime.fromisoformat(value))
        except ValueError as exc:
            raise RedditAdsError("Choose valid report dates.") from exc
    if dates[1] <= dates[0]:
        raise RedditAdsError("The report end must be after its start.")
    fields = arguments.get("fields", list(REPORT_FIELDS))
    breakdowns = arguments.get("breakdowns", ["DATE", "CAMPAIGN_ID"])
    for values, allowed, maximum in ((fields, REPORT_FIELDS, len(REPORT_FIELDS)),
                                    (breakdowns, REPORT_BREAKDOWNS, 3)):
        if (not isinstance(values, list) or not 1 <= len(values) <= maximum
                or any(not isinstance(value, str) or value not in allowed for value in values)
                or len(set(values)) != len(values)):
            raise RedditAdsError("Choose supported, distinct Reddit Ads report fields and breakdowns.")
    timezone = arguments.get("time_zone_id", "UTC")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise RedditAdsError("Choose a valid reporting time zone.") from exc
    return {"data": {"starts_at": arguments["starts_at"], "ends_at": arguments["ends_at"],
                     "fields": fields, "breakdowns": breakdowns, "time_zone_id": timezone}}


async def verify(credentials: dict) -> dict:
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        result = await _request(client, "GET", API_ROOT + "/me", _headers(credentials))
    identity = result.get("data")
    if not isinstance(identity, dict) or not identity.get("id"):
        raise RedditAdsError("Reddit Ads account access could not be verified.")
    return {"ok": True, "read_only": True, "identity": {
        "id": identity["id"], "username": identity.get("reddit_username"),
    }}


async def execute(credentials: dict, operation: str, arguments: dict, timeout: float = 45) -> dict:
    if operation not in OPERATIONS:
        raise RedditAdsError("This Reddit Ads operation is not supported.")
    headers = _headers(credentials)
    report = report_body(arguments) if operation == "reddit-ads.report.get" else None
    if operation == "reddit-ads.identity.get":
        return await verify(credentials)
    business_id = _id(arguments.get("business_id")) if operation == "reddit-ads.accounts.list" else None
    account_id = _id(arguments.get("ad_account_id")) if operation not in {
        "reddit-ads.businesses.list", "reddit-ads.accounts.list",
    } else None
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        if operation == "reddit-ads.businesses.list":
            result = await _collection(client, "/me/businesses", headers)
        elif operation == "reddit-ads.accounts.list":
            result = await _collection(client, f"/businesses/{business_id}/ad_accounts", headers)
            result["account_scope_note"] = "Accounts shared with the business may be absent; verify an explicit account ID with account.get."
        else:
            path = f"/ad_accounts/{account_id}"
            account = (await _request(client, "GET", API_ROOT + path, headers)).get("data")
            if not isinstance(account, dict) or str(account.get("id")) != account_id:
                raise RedditAdsError("Reddit Ads did not verify the requested ad account.")
            if operation == "reddit-ads.account.get":
                result = {"data": account, "source_url": API_ROOT + path}
            else:
                resource = {"reddit-ads.campaigns.list": "campaigns", "reddit-ads.ad-groups.list": "ad_groups",
                            "reddit-ads.ads.list": "ads", "reddit-ads.report.get": "reports"}[operation]
                result = await _collection(client, path + "/" + resource, headers, body=report)
                result["ad_account"] = account
            if report is not None:
                result["report_request"] = report["data"]
                result["metric_units"] = {
                    "spend_cpc_ecpm": "Raw microcurrency units; divide by 1,000,000 in the account currency.",
                    "conversion_purchase_total_value": "Raw minor currency units; divide by 100.",
                    "purchase_clicks_and_views": "Reddit-attributed conversions, not deduplicated sales orders or company revenue.",
                    "missing_values": "Missing or null metrics remain unavailable; never replace with zero.",
                }
                result["reporting_note"] = "Raw Reddit metrics and attribution settings are retained in raw_pages. Metrics may change as conversions arrive."
        return {**result, "provider": "Reddit Ads", "api_version": "v3",
                "retrieved_at": datetime.now(UTC).isoformat(), "result_url": "https://ads.reddit.com/"}
