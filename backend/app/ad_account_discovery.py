"""Read-only account discovery before planning; never switch reviewed targets."""
import asyncio
import re

import httpx

from . import meta_ads, reddit_ads
from .config import get_settings
from .connection_families import is_synthetic_source, synthetic_source_families
from .providers import refresh_oauth_credentials
from .request_contracts import user_request_text
from .security import CredentialVault


async def refresh_planning_accounts(inventory, tools, prompt, requested_tools=()):
    prompt = user_request_text(prompt)
    requested = " ".join([prompt, *requested_tools]).casefold()
    simulated = synthetic_source_families(prompt)
    by_slug = {tool.slug: tool for tool in tools if tool.enabled}
    for item in inventory:
        tool = by_slug.get(item.get("slug"))
        if not tool or not item.get("connected") or is_synthetic_source(item, simulated):
            continue
        native_reddit = tool.slug == "reddit-ads" and (tool.config or {}).get("managed_by") == "native"
        direct_meta = tool.slug == meta_ads.SLUG and (tool.config or {}).get("managed_by") == "meta_direct"
        if not (native_reddit or direct_meta):
            continue
        pattern = (r"\breddit[ -]+(?:ads?|advertising)\b" if native_reddit
                   else r"\b(?:meta|facebook|instagram)[ -]+(?:ads?|advertising)\b")
        if not re.search(pattern, requested):
            continue
        try:
            async with asyncio.timeout(45):
                vault = CredentialVault()
                credentials = vault.decrypt(tool.encrypted_credentials)
                credentials, changed = await refresh_oauth_credentials(
                    get_settings(), tool.slug, credentials, tool.config or {})
                if changed:
                    tool.encrypted_credentials = vault.encrypt(credentials)
                if native_reddit:
                    discovery = await reddit_ads.account_options(credentials)
                else:
                    result = await meta_ads.execute(credentials, "meta-ads.accounts.list", {})
                    discovery = result["account_discovery"]
            item["ad_account_discovery"] = discovery
            if native_reddit:
                accounts = discovery["accounts"]
                selected = item.get("reddit_ads_account") or {}
                fresh = next((row for row in accounts if row["ad_account_id"] == selected.get("ad_account_id")), None)
                # A sole discovered account is an unambiguous planning default.
                # Persisted customer choices and reviewed runs are never edited.
                item["reddit_ads_account"] = fresh or (accounts[0] if len(accounts) == 1 else None)
        except (httpx.HTTPError, ValueError, RuntimeError, TimeoutError):
            item["ad_account_discovery"] = {"accounts": [], "coverage": {
                "status": "unavailable", "warnings": [
                    ("Automatic account discovery could not complete. Use the account-list read to retry; "
                     "do not interpret this as no accounts or ask for an account ID.")]}}
            if native_reddit:
                # Do not silently fall back to an unverified stale selection.
                item["reddit_ads_account"] = None
