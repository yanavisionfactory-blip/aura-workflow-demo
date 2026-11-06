"""Direct, read-only Meta Marketing API. No broker or caller-supplied transport.

The operator owns the Meta app. Consent is verified against /me/permissions and
/me/adaccounts; an OAuth redirect alone never certifies reporting access.
"""
import asyncio
import hashlib
import hmac
import json
import re
import time
from datetime import UTC, date, datetime

import httpx

from .config import get_settings
from .logging_privacy import protect_access_logs

SLUG = "meta-ads-direct"
ORIGIN = "https://graph.facebook.com"
OPERATIONS = frozenset({
    "meta-ads.identity.get", "meta-ads.accounts.list", "meta-ads.campaigns.list",
    "meta-ads.adsets.list", "meta-ads.ads.list", "meta-ads.insights.get",
})
ACCOUNT_FIELDS = ("id", "account_id", "name", "account_status", "currency", "timezone_name")
FIELDS = {
    "campaigns": ("id", "name", "account_id", "status", "effective_status", "objective"),
    "adsets": ("id", "name", "account_id", "campaign_id", "status", "effective_status"),
    "ads": ("id", "name", "account_id", "campaign_id", "adset_id", "status", "effective_status"),
}
MAX_PAGES = 50
MAX_ROWS = 5000


class MetaAdsError(ValueError):
    def __init__(self, message, *, reason="invalid_response", status_code=400, retryable=False):
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code
        self.retryable = retryable


def api_version(settings=None):
    version = (settings or get_settings()).meta_graph_api_version
    if not re.fullmatch(r"v[0-9]{1,3}\.0", version):
        raise MetaAdsError("AURA's Meta API version needs configuration.", reason="setup_required")
    return version


def app_credentials(settings=None):
    settings = settings or get_settings()
    secret = settings.meta_client_secret.get_secret_value()
    if not settings.meta_client_id or not secret:
        raise MetaAdsError("AURA's direct Meta connection is awaiting app configuration.",
                           reason="setup_required")
    return settings.meta_client_id, secret


def account_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:act_)?[0-9]{1,40}", value):
        raise MetaAdsError("Select an exact Meta ad account ID returned by the account list.",
                           reason="invalid_account")
    return "act_" + value.removeprefix("act_")


def _token(credentials, settings=None):
    app_id, _ = app_credentials(settings)
    if credentials.get("meta_app_id") != app_id or credentials.get("provider") != SLUG:
        raise MetaAdsError("Reconnect Meta directly using AURA's current Meta app.",
                           reason="authorization_required", status_code=401)
    token = credentials.get("access_token")
    expiry = credentials.get("expires_at")
    if (not isinstance(token, str) or not token or not isinstance(expiry, (int, float))
            or isinstance(expiry, bool) or expiry <= time.time() + 30):
        raise MetaAdsError("Meta access has expired. Reconnect Meta directly in AURA.",
                           reason="authorization_required", status_code=401)
    return token


async def _request(client, method, path, *, settings=None, credentials=None, data=None, params=None):
    settings = settings or get_settings()
    protect_access_logs()
    headers = {"Accept": "application/json"}
    params = dict(params or {})
    if credentials is not None:
        token = _token(credentials, settings)
        _, secret = app_credentials(settings)
        headers["Authorization"] = "Bearer " + token
        params["appsecret_proof"] = hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
    # Paths are code-owned or validated numeric IDs. Never follow provider URLs.
    url = f"{ORIGIN}/{api_version(settings)}/{path}"
    try:
        response = await client.request(method, url, headers=headers, params=params, data=data)
    except httpx.HTTPError:
        raise MetaAdsError("Meta is temporarily unreachable. Retry this read shortly.",
                           reason="provider_unavailable", status_code=503, retryable=True) from None
    try:
        payload = response.json()
    except ValueError:
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if error or not response.is_success:
        if code in {102, 190} or response.status_code == 401:
            raise MetaAdsError("Meta authorization expired or was revoked. Reconnect Meta directly.",
                               reason="authorization_required", status_code=401)
        if code in {10, 200, 294} or response.status_code == 403:
            raise MetaAdsError("Meta denied reporting access. Check the app's ads_read permission and ad-account access.",
                               reason="permission_denied", status_code=403)
        if (code in {4, 17, 32, 613, 80000} or response.status_code == 429):
            raise MetaAdsError("Meta's reporting limit was reached. Retry later.",
                               reason="rate_limited", status_code=429, retryable=True)
        if response.status_code >= 500 or (isinstance(error, dict) and error.get("is_transient")):
            raise MetaAdsError("Meta reporting is temporarily unavailable. Retry shortly.",
                               reason="provider_unavailable", status_code=503, retryable=True)
        raise MetaAdsError("Meta rejected this request. Check the app configuration and selected reporting inputs.",
                           reason="request_rejected")
    if not isinstance(payload, dict):
        raise MetaAdsError("Meta returned an invalid response.")
    return payload


async def _collection(client, path, credentials, params=None, settings=None):
    params = {**(params or {}), "limit": 100}
    rows, seen = [], set()
    for _ in range(MAX_PAGES):
        payload = await _request(client, "GET", path, credentials=credentials, params=params, settings=settings)
        page = payload.get("data")
        if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
            raise MetaAdsError("Meta returned an invalid reporting collection.")
        rows.extend(page)
        if len(rows) > MAX_ROWS:
            break
        paging = payload.get("paging") or {}
        if not isinstance(paging, dict):
            raise MetaAdsError("Meta returned invalid pagination.")
        if not paging.get("next"):
            return rows
        cursors = paging.get("cursors")
        after = cursors.get("after") if isinstance(cursors, dict) else None
        if not isinstance(after, str) or not after or len(after) > 8192 or after in seen:
            raise MetaAdsError("Meta pagination is incomplete. Repeat the read.")
        seen.add(after)
        params["after"] = after
    raise MetaAdsError("This Meta read exceeds 5,000 rows. Narrow the date range or use a complete export.",
                       reason="report_too_large")


def _project(row, fields):
    return {key: row[key] for key in fields if key in row}


async def _accounts(client, credentials, settings=None):
    rows = await _collection(client, "me/adaccounts", credentials,
                             {"fields": ",".join(ACCOUNT_FIELDS)}, settings)
    seen = set()
    for row in rows:
        identifier = account_id(row.get("id"))
        if identifier in seen or identifier != account_id(row.get("account_id")):
            raise MetaAdsError("Meta returned an inconsistent ad-account list.")
        seen.add(identifier)
    return [_project(row, ACCOUNT_FIELDS) for row in rows]


async def verify(credentials, settings=None):
    async with asyncio.timeout(30), httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        identity = await _request(client, "GET", "me", credentials=credentials,
                                  params={"fields": "id,name"}, settings=settings)
        if not isinstance(identity.get("id"), str) or not re.fullmatch(r"[0-9]+", identity["id"]):
            raise MetaAdsError("Meta did not return a verified user identity.")
        permissions = await _collection(client, "me/permissions", credentials, settings=settings)
        if not any(p.get("permission") == "ads_read" and p.get("status") == "granted" for p in permissions):
            raise MetaAdsError("Allow ads_read reporting access when connecting Meta.",
                               reason="permission_denied", status_code=403)
        accounts = await _accounts(client, credentials, settings)
    if not accounts:
        raise MetaAdsError("This Meta user has no accessible ad accounts. Ask an ad-account administrator to grant reporting access.",
                           reason="no_ad_accounts", status_code=403)
    return {"ok": True, "identity": _project(identity, ("id", "name")),
            "account_ids": [a["id"] for a in accounts], "accounts_verified": len(accounts),
            "expires_at": credentials["expires_at"], "source": "meta_marketing_api"}


async def exchange(settings, code, callback_url):
    app_id, secret = app_credentials(settings)
    async with asyncio.timeout(60), httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        short = await _request(client, "POST", "oauth/access_token", settings=settings, data={
            "client_id": app_id, "client_secret": secret, "code": code, "redirect_uri": callback_url,
        })
        if not isinstance(short.get("access_token"), str) or not short["access_token"]:
            raise MetaAdsError("Meta did not issue an access token.")
        long = await _request(client, "POST", "oauth/access_token", settings=settings, data={
            "client_id": app_id, "client_secret": secret, "grant_type": "fb_exchange_token",
            "fb_exchange_token": short["access_token"],
        })
        token, expires = long.get("access_token"), long.get("expires_in")
        if (not isinstance(token, str) or not token or not isinstance(expires, int)
                or isinstance(expires, bool) or expires <= 60):
            raise MetaAdsError("Meta did not return a valid token expiry. Try connecting again.")
        # Facebook Login does not issue a refresh_token. Expiry requires fresh consent.
        credentials = {"provider": SLUG, "meta_app_id": app_id, "access_token": token,
                       "expires_at": int(time.time()) + expires}
        credentials["meta_verification"] = await verify(credentials, settings)
        return credentials


async def execute(credentials, operation, arguments, timeout=45):
    if operation not in OPERATIONS:
        raise MetaAdsError("Direct Meta supports reviewed reporting reads only.")
    if operation == "meta-ads.identity.get":
        return await verify(credentials)
    evidence = {"source_provider": "meta-ads", "connection_route": "direct",
                "input_mode": "vendor_api", "vendor_api_called": True,
                "api_version": api_version(), "retrieved_at": datetime.now(UTC).isoformat()}
    async with asyncio.timeout(timeout), httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        if operation == "meta-ads.accounts.list":
            return {**evidence, "data": await _accounts(client, credentials), "complete": True}
        selected = account_id(arguments.get("account_id"))
        # Verify the exact selected account on every read; never pick the first.
        account = await _request(client, "GET", selected, credentials=credentials,
                                 params={"fields": ",".join(ACCOUNT_FIELDS)})
        if account.get("id") != selected or account_id(account.get("account_id")) != selected:
            raise MetaAdsError("Meta did not verify the selected ad account.")
        evidence.update(account_id=selected, account=_project(account, ACCOUNT_FIELDS))
        edge = operation.split(".")[1]
        if edge == "insights":
            try:
                since, until = (date.fromisoformat(arguments[key]) for key in ("since", "until"))
                if (since > until or (until - since).days > 366
                        or any(arguments[k] != d.isoformat() for k, d in (("since", since), ("until", until)))):
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise MetaAdsError("Use explicit YYYY-MM-DD dates, in order, spanning at most 367 days.",
                                   reason="invalid_dates") from None
            level = arguments.get("level", "campaign")
            if level not in {"account", "campaign", "adset", "ad"}:
                raise MetaAdsError("Select account, campaign, adset or ad reporting level.")
            fields = ["account_id", "account_name", "account_currency", "date_start", "date_stop",
                      "impressions", "clicks", "inline_link_clicks", "spend", "reach", "frequency",
                      "cpc", "cpm", "ctr", "actions", "action_values", "purchase_roas"]
            for dimension in ("campaign", "adset", "ad"):
                if level == "account":
                    break
                fields.extend((dimension + "_id", dimension + "_name"))
                if dimension == level:
                    break
            params = {"fields": ",".join(fields), "level": level,
                      "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
                      "time_increment": "all_days", "action_report_time": "impression",
                      "use_unified_attribution_setting": "true"}
            evidence.update(date_range={"since": since.isoformat(), "until": until.isoformat(),
                                        "inclusive": True}, level=level,
                            attribution={"action_report_time": "impression", "setting": "adset_unified"},
                            limitations=["Account timezone and currency apply. Attribution follows each ad set's settings.",
                                         "Reach is not additive. Action types must not be summed as interchangeable conversions."])
        else:
            fields = FIELDS[edge]
            params = {"fields": ",".join(fields)}
        rows = await _collection(client, f"{selected}/{edge}", credentials, params)
        seen = set()
        for row in rows:
            if account_id(row.get("account_id")) != selected:
                raise MetaAdsError("Meta returned a row for an unexpected ad account.")
            if edge == "insights":
                try:
                    start, stop = (date.fromisoformat(row[k]) for k in ("date_start", "date_stop"))
                    if not since <= start <= stop <= until:
                        raise ValueError()
                except (KeyError, TypeError, ValueError):
                    raise MetaAdsError("Meta returned a row outside the requested reporting period.") from None
                identifier = row.get(level + "_id")
                key = (identifier, row["date_start"], row["date_stop"])
            else:
                identifier = row.get("id")
                key = identifier
            if not isinstance(identifier, str) or not re.fullmatch(r"[0-9]{1,40}", identifier) or key in seen:
                raise MetaAdsError("Meta returned missing or duplicate row identifiers. Repeat the read.")
            seen.add(key)
        return {**evidence, "data": [_project(row, fields) for row in rows],
                "row_count": len(rows), "complete": True}
