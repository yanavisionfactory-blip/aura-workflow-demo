"""Read Google Analytics account options through the existing managed grant.

The upstream options actions dereference omitted collections on empty Google
responses and do not exhaust pagination. These two fixed, read-only Admin API
routes retain real provider evidence, including a successful empty result.
"""
import base64
import re
from urllib.parse import quote, urlencode

ROUTES = {
    "google-analytics.list-account-options": ("accounts", "accounts"),
    "google-analytics.list-property-options": ("accountSummaries", "accountSummaries"),
}
MAX_PAGES = 20


def handles(provider, operation):
    return provider == "google-analytics" and operation in ROUTES


async def execute(broker, external_user_id, account_id, operation, arguments):
    from .pipedream_connect import PipedreamConnectError

    def invalid():
        return PipedreamConnectError(
            "Google Analytics discovery returned an invalid or incomplete collection",
            retryable=False, upstream_code="analytics_discovery_invalid",
        )

    if operation not in ROUTES or arguments:
        raise PipedreamConnectError("Invalid Analytics discovery operation or inputs", retryable=False)
    verification = await broker.verify_account(external_user_id, "google_analytics", account_id)
    if not verification.get("ok"):
        raise PipedreamConnectError("Google Analytics authorization is required",
                                    retryable=False, status_code=403)

    route, collection = ROUTES[operation]
    pages, options, seen_tokens, seen_resources = [], [], set(), set()
    token = None
    for _ in range(MAX_PAGES):
        query = {"pageSize": 200}
        if token:
            query["pageToken"] = token
        target = f"https://analyticsadmin.googleapis.com/v1beta/{route}?{urlencode(query)}"
        encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        # No model-provided target, headers, body or provider credential. The
        # broker inserts the selected owner's existing Google Analytics grant.
        result = await broker._request(
            "GET", f"/v1/connect/{quote(broker.settings.pipedream_project_id, safe='')}/proxy/{encoded}",
            params={"external_user_id": external_user_id, "account_id": account_id},
        )
        if not isinstance(result, dict):
            raise invalid()
        if "error" in result:
            error = result["error"]
            status = error.get("code") if isinstance(error, dict) else None
            status = status if type(status) is int and 400 <= status <= 599 else None
            raise PipedreamConnectError("Google Analytics rejected the discovery request",
                retryable=status in {408, 429, 500, 502, 503, 504}, status_code=status,
                upstream_code="analytics_discovery_rejected")
        # Google omits empty repeated fields. Unexpected envelopes, explicit
        # null and malformed collections are not evidence of an empty account.
        if set(result) - {collection, "nextPageToken"}:
            raise invalid()
        rows = result.get(collection, [])
        if not isinstance(rows, list):
            raise invalid()
        pages.append(result)
        for row in rows:
            if not isinstance(row, dict):
                raise invalid()
            if route == "accounts":
                candidates = [(row.get("name"), row.get("displayName"), "accounts")]
            else:
                properties = row.get("propertySummaries", [])
                if not isinstance(properties, list):
                    raise invalid()
                candidates = []
                for prop in properties:
                    if not isinstance(prop, dict):
                        raise invalid()
                    candidates.append((prop.get("property"), prop.get("displayName"), "properties"))
            for resource, label, kind in candidates:
                if (not isinstance(resource, str) or not re.fullmatch(rf"{kind}/[0-9]+", resource)
                        or not isinstance(label, str) or not label.strip()):
                    raise invalid()
                if resource in seen_resources:
                    raise invalid()
                seen_resources.add(resource)
                options.append({"label": label, "value": resource})
        token = result.get("nextPageToken", "")
        if not isinstance(token, str) or len(token) > 8192 or token in seen_tokens:
            raise invalid()
        if not token:
            return {
                "ret": options,
                "aura_transport": "google_analytics_admin_via_pipedream_proxy",
                "provider_pages": pages,
                "pagination": {"complete": True, "pages": len(pages)},
                "empty": not options,
                "summary": (f"Retrieved {len(options)} accessible Analytics options."
                            if options else "Google Analytics returned no accessible options for this account."),
            }
        seen_tokens.add(token)
    raise invalid()
