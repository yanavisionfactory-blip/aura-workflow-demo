"""Reddit Ads read access. App credentials belong to AURA, never its customers."""
import re
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .config import get_settings

ORIGIN = "https://ads-api.reddit.com"
BASE = ORIGIN + "/api/v3"
OPERATIONS = frozenset({"reddit-ads.identity.get", "reddit-ads.businesses.list",
                        "reddit-ads.accounts.list", "reddit-ads.campaigns.list"})
ACCOUNT_ID = r"^(?:t2|a2)_[A-Za-z0-9]+$"


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


def apply_account_defaults(plan, inventory, manifests):
    selected = next((item.get("reddit_ads_account") for item in inventory if item["slug"] == "reddit-ads"), None)
    if not selected:
        return
    for step in plan.steps:
        if step.tool_slug != "reddit-ads":
            continue
        fields = {"reddit-ads.accounts.list": "business_id", "reddit-ads.campaigns.list": "ad_account_id"}
        field = fields.get(step.operation)
        if field and not step.arguments.get(field):
            step.arguments = {**step.arguments, field: selected[field]}
