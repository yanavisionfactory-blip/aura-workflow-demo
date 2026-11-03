"""Customer-facing social app names; stored account and vendor IDs stay intact."""

_APPS = {
    "tiktok": ("TikTok", ("TikTok",)),
    "tiktok-ads-manager": ("TikTok Ads", ("TikTok Ads", "TikTok Ads Manager")),
    "x": ("X (Twitter)", ("X", "Twitter", "X (Twitter)")),
}
_ALIASES = {
    "tiktok-zernio": "tiktok",
    "x-zernio": "x",
    "tiktok-ads": "tiktok-ads-manager",
    "twitter": "x",
    "twitter-v1": "x",
    "twitter-v2": "x",
    "twitter-oauth2": "x",
}


def social_catalog_entry(item: dict) -> dict:
    """Group equivalent catalog cards without rewriting authorization routes."""
    provider = str(item.get("provider") or "").lower().replace("_", "-")
    canonical = _ALIASES.get(provider, provider)
    if canonical not in _APPS:
        return item
    name, aliases = _APPS[canonical]
    return {
        **item,
        "display_name": name,
        "canonical_provider": canonical,
        "aliases": sorted({*aliases, *(item.get("aliases") or []),
                           str(item.get("display_name") or ""), provider} - {""}),
    }
