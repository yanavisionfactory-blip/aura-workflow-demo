import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .config import Settings, get_settings
from .native_connectors import coerce_module_arguments
from .reliability import AuthorizationRequired
from .universal_connectors import capability_for

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OAuthProvider:
    slug: str
    display_name: str
    authorization_url: str
    token_url: str
    scopes: tuple[str, ...]
    client_id_attr: str
    client_secret_attr: str
    callback_provider: str
    legacy_callback_providers: tuple[str, ...] = ()


PROVIDERS = {
    "google": OAuthProvider(
        slug="google",
        display_name="Google Workspace",
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=(
            "openid", "email",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/spreadsheets",
        ),
        client_id_attr="google_client_id",
        client_secret_attr="google_client_secret",
        callback_provider="google",
    ),
    "airtable": OAuthProvider(
        slug="airtable",
        display_name="Airtable",
        authorization_url="https://airtable.com/oauth2/v1/authorize",
        token_url="https://airtable.com/oauth2/v1/token",
        scopes=("data.records:read", "data.records:write", "schema.bases:read"),
        client_id_attr="airtable_client_id",
        client_secret_attr="airtable_client_secret",
        callback_provider="airtable",
    ),
    "notion": OAuthProvider(
        slug="notion",
        display_name="Notion",
        authorization_url="https://api.notion.com/v1/oauth/authorize",
        token_url="https://api.notion.com/v1/oauth/token",
        scopes=(),
        client_id_attr="notion_client_id",
        client_secret_attr="notion_client_secret",
        callback_provider="installation",
    ),
    "mailchimp": OAuthProvider(
        slug="mailchimp",
        display_name="Mailchimp",
        authorization_url="https://login.mailchimp.com/oauth2/authorize",
        token_url="https://login.mailchimp.com/oauth2/token",
        scopes=(),
        client_id_attr="mailchimp_client_id",
        client_secret_attr="mailchimp_client_secret",
        callback_provider="installation",
    ),
    "canva": OAuthProvider(
        slug="canva",
        display_name="Canva",
        authorization_url="https://www.canva.com/api/oauth/authorize",
        token_url="https://api.canva.com/rest/v1/oauth/token",
        scopes=(
            "profile:read", "design:meta:read", "design:content:read",
            "design:content:write", "asset:read", "asset:write",
            "folder:read", "folder:write",
        ),
        client_id_attr="canva_client_id",
        client_secret_attr="canva_client_secret",
        callback_provider="installation",
    ),
    "tiktok": OAuthProvider(
        slug="tiktok",
        display_name="TikTok",
        authorization_url="https://www.tiktok.com/v2/auth/authorize/",
        token_url="https://open.tiktokapis.com/v2/oauth/token/",
        scopes=("user.info.basic", "video.list", "video.upload", "video.publish"),
        client_id_attr="tiktok_client_id",
        client_secret_attr="tiktok_client_secret",
        callback_provider="installation",
    ),
    "slack": OAuthProvider(
        slug="slack",
        display_name="Slack",
        authorization_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scopes=("channels:read", "chat:write"),
        client_id_attr="slack_client_id",
        client_secret_attr="slack_client_secret",
        callback_provider="slack",
    ),
    "hubspot": OAuthProvider(
        slug="hubspot",
        display_name="HubSpot",
        authorization_url="https://app.hubspot.com/oauth/authorize",
        token_url="https://api.hubapi.com/oauth/v1/token",
        scopes=(
            "crm.objects.contacts.read",
            "crm.objects.contacts.write",
            "crm.objects.companies.read",
            "crm.objects.companies.write",
        ),
        client_id_attr="hubspot_client_id",
        client_secret_attr="hubspot_client_secret",
        callback_provider="hubspot",
    ),
    "jira": OAuthProvider(
        slug="jira",
        display_name="Jira",
        authorization_url="https://auth.atlassian.com/authorize",
        token_url="https://auth.atlassian.com/oauth/token",
        scopes=("read:jira-work", "write:jira-work", "read:jira-user", "offline_access"),
        client_id_attr="atlassian_client_id",
        client_secret_attr="atlassian_client_secret",
        callback_provider="jira",
        legacy_callback_providers=("atlassian",),
    ),
}


def _oauth_callback_overrides(settings: Settings) -> dict[str, str]:
    if not settings.oauth_callback_overrides.strip():
        return {}
    try:
        overrides = json.loads(settings.oauth_callback_overrides)
    except json.JSONDecodeError as exc:
        raise ValueError("OAUTH_CALLBACK_OVERRIDES must be a JSON object") from exc
    if not isinstance(overrides, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in overrides.items()
    ):
        raise ValueError("OAUTH_CALLBACK_OVERRIDES must map provider slugs to URLs")
    return overrides


def _validated_callback_url(callback: str, label: str) -> str:
    parts = urlsplit(callback)
    path = parts.path.strip("/").split("/")
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.query
        or parts.fragment
        or len(path) != 4
        or path[:2] != ["v1", "oauth"]
        or path[3] != "callback"
        or not path[2]
    ):
        raise ValueError(
            f"Invalid OAuth callback contract for {label}; expected "
            "https://host/v1/oauth/{provider}/callback"
        )
    return callback


def oauth_route_callback_url(settings: Settings, route_provider: str) -> str:
    """Resolve managed, installed, and custom OAuth routes through one contract."""
    override = _oauth_callback_overrides(settings).get(route_provider)
    callback = override or (
        f"{settings.public_url.rstrip('/')}/v1/oauth/{route_provider}/callback"
    )
    return _validated_callback_url(callback, route_provider)


def oauth_callback_url(settings: Settings, provider: OAuthProvider) -> str:
    """Return the callback used for both authorization and token exchange."""
    override = _oauth_callback_overrides(settings).get(provider.slug)
    if override:
        return _validated_callback_url(override, provider.slug)
    return oauth_route_callback_url(settings, provider.callback_provider)


def oauth_callback_route_provider(settings: Settings, provider: OAuthProvider) -> str:
    return urlsplit(oauth_callback_url(settings, provider)).path.strip("/").split("/")[2]


def oauth_callback_matches(
    settings: Settings, state_provider: str, route_provider: str
) -> bool:
    definition = PROVIDERS.get(state_provider)
    if not definition:
        return False
    accepted = {
        oauth_callback_route_provider(settings, definition),
        *definition.legacy_callback_providers,
    }
    return route_provider in accepted


def oauth_exchange_callback_url(
    settings: Settings, provider: OAuthProvider, route_provider: str
) -> str:
    """Preserve the exact redirect URI used by current or accepted legacy flows."""
    if route_provider == oauth_callback_route_provider(settings, provider):
        return oauth_callback_url(settings, provider)
    if route_provider in provider.legacy_callback_providers:
        return oauth_route_callback_url(settings, route_provider)
    raise ValueError(f"OAuth callback route does not match {provider.slug}")


def oauth_registry_errors(settings: Settings) -> list[str]:
    """Validate all managed callback contracts before users encounter OAuth."""
    errors: list[str] = []
    try:
        oauth_route_callback_url(settings, "custom")
        oauth_route_callback_url(settings, "installation")
    except ValueError as exc:
        errors.append(str(exc))
    for key, provider in PROVIDERS.items():
        if key != provider.slug:
            errors.append(f"Provider key {key!r} does not match slug {provider.slug!r}")
        for endpoint_name, endpoint in (
            ("authorization", provider.authorization_url),
            ("token", provider.token_url),
        ):
            if urlsplit(endpoint).scheme != "https":
                errors.append(f"{provider.slug} {endpoint_name} URL must use HTTPS")
        try:
            callback = oauth_callback_url(settings, provider)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if settings.environment == "production" and urlsplit(callback).scheme != "https":
            errors.append(f"{provider.slug} callback URL must use HTTPS in production")
    return errors


def _canva_code_verifier(settings: Settings, state: str) -> str:
    """Derive a short-lived PKCE verifier without persisting OAuth secrets."""
    digest = hmac.new(
        settings.session_signing_key.encode(), state.encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _canva_code_challenge(settings: Settings, state: str) -> str:
    verifier = _canva_code_verifier(settings, state)
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def oauth_authorization_url(settings: Settings, provider: OAuthProvider, state: str) -> str:
    client_id = getattr(settings, provider.client_id_attr)
    if not client_id:
        raise ValueError(f"{provider.display_name} OAuth client is not configured")
    params = {
        ("client_key" if provider.slug == "tiktok" else "client_id"): client_id,
        "redirect_uri": oauth_callback_url(settings, provider),
        "response_type": "code",
        "state": state,
    }
    if provider.slug == "notion":
        params["owner"] = "user"
    elif provider.slug == "jira":
        params.update({
            "audience": "api.atlassian.com",
            "prompt": "consent",
            "scope": " ".join(provider.scopes),
        })
    elif provider.slug == "mailchimp":
        pass
    elif provider.slug in {"slack", "tiktok"}:
        params["scope"] = ",".join(provider.scopes)
    else:
        params["scope"] = " ".join(provider.scopes)
    if provider.slug == "canva":
        params.update({
            "code_challenge": _canva_code_challenge(settings, state),
            "code_challenge_method": "S256",
        })
    if provider.slug == "google":
        params.update({"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"})
    return f"{provider.authorization_url}?{urlencode(params)}"


async def exchange_oauth_code(
    settings: Settings,
    provider: OAuthProvider,
    code: str,
    state: str | None = None,
    callback_url: str | None = None,
) -> dict:
    client_id = getattr(settings, provider.client_id_attr)
    client_secret = getattr(settings, provider.client_secret_attr)
    payload = {
        ("client_key" if provider.slug == "tiktok" else "client_id"): client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": callback_url or oauth_callback_url(settings, provider),
    }
    headers = {"Accept": "application/json"}
    if provider.slug == "canva":
        if not state:
            raise ValueError("Canva OAuth callback is missing PKCE state")
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"
        payload.pop("client_secret")
        payload["code_verifier"] = _canva_code_verifier(settings, state)
    elif provider.slug in {"airtable", "notion"}:
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"
        payload.pop("client_secret")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            provider.token_url,
            json=payload if provider.slug == "jira" else None,
            data=None if provider.slug == "jira" else payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
    if provider.slug == "slack" and not data.get("ok", False):
        raise RuntimeError(data.get("error", "Slack OAuth failed"))
    if provider.slug == "mailchimp":
        async with httpx.AsyncClient(timeout=30) as client:
            metadata_response = await client.get(
                "https://login.mailchimp.com/oauth2/metadata",
                headers={"Authorization": f"OAuth {data['access_token']}"},
            )
            metadata_response.raise_for_status()
            data.update(metadata_response.json())
    if provider.slug == "jira":
        async with httpx.AsyncClient(timeout=30) as client:
            resources_response = await client.get(
                "https://api.atlassian.com/oauth/token/accessible-resources",
                headers={"Authorization": f"Bearer {data['access_token']}", "Accept": "application/json"},
            )
            resources_response.raise_for_status()
            resources = resources_response.json()
        jira_sites = [
            item for item in resources
            if any("jira" in scope for scope in item.get("scopes", []))
        ]
        if not jira_sites:
            raise RuntimeError("Atlassian authorization did not grant access to a Jira site")
        site = jira_sites[0]
        data.update({"cloud_id": site["id"], "site_name": site.get("name"), "site_url": site.get("url")})
    if data.get("expires_in"):
        data["expires_at"] = int(time.time()) + int(data["expires_in"])
    return data


async def refresh_oauth_credentials(
    settings: Settings,
    provider_slug: str,
    credentials: dict,
    config: dict | None = None,
) -> tuple[dict, bool]:
    """Refresh shortly before expiry; returns credentials and whether they changed."""
    if not credentials.get("refresh_token") or int(credentials.get("expires_at", 0)) > int(time.time()) + 90:
        return credentials, False
    provider = PROVIDERS.get(provider_slug)
    if not provider:
        config = config or {}
        token_url = config.get("token_url")
        if not config.get("oauth_custom") or not token_url:
            return credentials, False
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": credentials["refresh_token"],
            **config.get("token_params", {}),
        }
        auth = None
        method = config.get("token_auth_method", "client_secret_post")
        if method == "client_secret_basic":
            auth = (credentials["client_id"], credentials.get("client_secret", ""))
        elif method == "client_secret_post":
            payload.update(
                {"client_id": credentials["client_id"], "client_secret": credentials.get("client_secret", "")}
            )
        else:
            payload["client_id"] = credentials["client_id"]
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.post(token_url, data=payload, auth=auth, headers={"Accept": "application/json"})
            response.raise_for_status()
            updated = response.json()
        if updated.get("expires_in"):
            updated["expires_at"] = int(time.time()) + int(updated["expires_in"])
        return {**credentials, **updated}, True
    payload = {
        ("client_key" if provider.slug == "tiktok" else "client_id"): getattr(
            settings, provider.client_id_attr
        ),
        "client_secret": getattr(settings, provider.client_secret_attr),
        "refresh_token": credentials["refresh_token"],
        "grant_type": "refresh_token",
    }
    headers = {"Accept": "application/json"}
    if provider.slug in {"airtable", "canva", "notion"}:
        basic = base64.b64encode(f"{payload['client_id']}:{payload['client_secret']}".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"
        payload.pop("client_secret")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            provider.token_url,
            json=payload if provider.slug == "jira" else None,
            data=None if provider.slug == "jira" else payload,
            headers=headers,
        )
        response.raise_for_status()
        refreshed = response.json()
    merged = {**credentials, **refreshed}
    if refreshed.get("expires_in"):
        merged["expires_at"] = int(time.time()) + int(refreshed["expires_in"])
    return merged, True


async def verify_oauth_credentials(provider_slug: str, credentials: dict) -> dict:
    token = credentials.get("access_token")
    if not token:
        return {"ok": False, "reason": "missing_access_token"}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if provider_slug == "google":
        method, url, kwargs = "GET", "https://openidconnect.googleapis.com/v1/userinfo", {}
    elif provider_slug == "slack":
        method, url, kwargs = "POST", "https://slack.com/api/auth.test", {}
    elif provider_slug == "airtable":
        method, url, kwargs = "GET", "https://api.airtable.com/v0/meta/whoami", {}
    elif provider_slug == "notion":
        method, url, kwargs = "GET", "https://api.notion.com/v1/users/me", {}
        headers["Notion-Version"] = "2025-09-03"
    elif provider_slug == "mailchimp":
        method, url, kwargs = "GET", "https://login.mailchimp.com/oauth2/metadata", {}
        headers["Authorization"] = f"OAuth {token}"
    elif provider_slug == "tiktok":
        method, url, kwargs = (
            "GET",
            "https://open.tiktokapis.com/v2/user/info/",
            {"params": {"fields": "open_id,union_id,avatar_url,display_name"}},
        )
    elif provider_slug == "canva":
        method, url, kwargs = "GET", "https://api.canva.com/rest/v1/users/me/profile", {}
    elif provider_slug == "hubspot":
        method, url, kwargs = "GET", "https://api.hubapi.com/crm/v3/objects/contacts", {"params": {"limit": 1}}
    elif provider_slug == "jira":
        method, url, kwargs = "GET", "https://api.atlassian.com/oauth/token/accessible-resources", {}
    else:
        return {"ok": False, "reason": "unsupported_oauth_provider"}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.request(method, url, headers=headers, **kwargs)
        data = response.json() if "application/json" in response.headers.get("content-type", "") else {}
    ok = response.is_success and (provider_slug != "slack" or bool(data.get("ok")))
    if provider_slug == "tiktok":
        identity_source = data.get("data", {}).get("user", {})
    elif provider_slug == "jira":
        site = next((item for item in data if any("jira" in scope for scope in item.get("scopes", []))), {})
        identity_source = {
            "id": site.get("id"),
            "display_name": site.get("name"),
            "site_url": site.get("url"),
        }
    else:
        identity_source = data
    identity = {
        key: identity_source.get(key)
        for key in (
            "sub", "email", "team", "team_id", "user", "user_id", "id",
            "open_id", "union_id", "display_name", "site_url",
        )
        if identity_source.get(key) is not None
    }
    return {"ok": ok, "status_code": response.status_code, "identity": identity}


class ProviderExecutor:
    """Executes only allow-listed operations; credentials never enter model context."""

    def __init__(
        self,
        credentials: dict[str, Any],
        base_url: str | None = None,
        timeout_seconds: float = 45,
        provider_kind: str | None = None,
        capability_manifest: dict | None = None,
    ):
        self.credentials = credentials
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.provider_kind = provider_kind
        self.capability_manifest = capability_manifest or {}

    def _headers(self) -> dict[str, str]:
        token = self.credentials.get("access_token") or self.credentials.get("api_key")
        if not token:
            return {"Content-Type": "application/json"}
        header = self.credentials.get("header", "Authorization")
        prefix = self.credentials.get("prefix", "Bearer")
        return {header: f"{prefix} {token}".strip(), "Content-Type": "application/json"}

    async def execute(self, operation: str, arguments: dict[str, Any]) -> dict:
        if self.capability_manifest:
            arguments = coerce_module_arguments(
                self.capability_manifest, operation, arguments
            )
        handlers = {
            "gmail.list": self._gmail_list,
            "gmail.send": self._gmail_send,
            "gmail.get": self._gmail_get,
            "google.identity.get": self._google_identity_get,
            "calendar.list": self._calendar_list,
            "calendar.create": self._calendar_create,
            "calendar.get": self._calendar_get,
            "docs.create": self._docs_create,
            "docs.get": self._docs_get,
            "drive.files.search": self._drive_files_search,
            "drive.spreadsheet.resolve": self._drive_spreadsheet_resolve,
            "sheets.read": self._sheets_read,
            "sheets.append": self._sheets_append,
            "airtable.record.get": self._airtable_record_get,
            "slack.message.get": self._slack_message_get,
            "hubspot.contact.get": self._hubspot_contact_get,
            "hubspot.company.get": self._hubspot_company_get,
            "mailchimp.member.get": self._mailchimp_member_get,
            "mailchimp.campaign.get": self._mailchimp_campaign_get,
            "airtable.list": self._airtable_list,
            "airtable.create": self._airtable_create,
            "notion.search": self._notion_search,
            "notion.page.get": self._notion_page_get,
            "notion.blocks.children.list": self._notion_blocks_children_list,
            "notion.page.create": self._notion_page_create,
            "notion.page.update": self._notion_page_update,
            "notion.blocks.children.append": self._notion_blocks_children_append,
            "slack.channels.list": self._slack_channels_list,
            "slack.post": self._slack_post,
            "tiktok.profile.get": self._tiktok_profile_get,
            "tiktok.videos.list": self._tiktok_videos_list,
            "tiktok.post.creator_info": self._tiktok_post_creator_info,
            "tiktok.video.upload.init": self._tiktok_video_upload_init,
            "tiktok.video.publish.init": self._tiktok_video_publish_init,
            "tiktok.post.status.get": self._tiktok_post_status_get,
            "mailchimp.audiences.list": self._mailchimp_audiences_list,
            "mailchimp.members.list": self._mailchimp_members_list,
            "mailchimp.member.upsert": self._mailchimp_member_upsert,
            "mailchimp.campaigns.list": self._mailchimp_campaigns_list,
            "mailchimp.campaign.create": self._mailchimp_campaign_create,
            "mailchimp.campaign.send": self._mailchimp_campaign_send,
            "mailchimp.reports.list": self._mailchimp_reports_list,
            "canva.designs.list": self._canva_designs_list,
            "canva.design.get": self._canva_design_get,
            "canva.design.create": self._canva_design_create,
            "canva.presentation.create": self._canva_presentation_create,
            "canva.import.get": self._canva_import_get,
            "canva.folder.items.list": self._canva_folder_items_list,
            "canva.export.create": self._canva_export_create,
            "canva.export.get": self._canva_export_get,
            "hubspot.contacts.list": self._hubspot_contacts_list,
            "hubspot.companies.list": self._hubspot_companies_list,
            "hubspot.contact.update": self._hubspot_contact_update,
            "hubspot.company.update": self._hubspot_company_update,
            "jira.projects.list": self._jira_projects_list,
            "jira.issues.search": self._jira_issues_search,
            "jira.issue.get": self._jira_issue_get,
            "jira.issue.create": self._jira_issue_create,
            "jira.issues.create_from_blocks": self._jira_issues_create_from_blocks,
            "jira.issue.update": self._jira_issue_update,
            "weather.forecast": self._weather_forecast,
            "web.search": self._web_search,
            "web.page.read": self._web_page_read,
            "creator.tiktok.screen": self._creator_tiktok_screen,
            "creator.candidates.exclude_existing": (
                self._creator_candidates_exclude_existing
            ),
            "http.request": self._http_request,
            "mcp.call": self._mcp_call,
        }
        if operation not in handlers:
            result = await self._execute_capability(operation, arguments)
        else:
            result = await handlers[operation](arguments)
        return self._attach_result_url(operation, arguments, result)

    def _attach_result_url(
        self, operation: str, arguments: dict[str, Any], result: dict
    ) -> dict:
        """Add a user-facing deep link without exposing transport endpoints."""
        if not isinstance(result, dict) or result.get("result_url"):
            return result

        url: str | None = None
        for key in (
            "web_url",
            "html_url",
            "htmlLink",
            "webViewLink",
            "permalink",
            "browser_url",
            "edit_url",
        ):
            if isinstance(result.get(key), str):
                url = result[key]
                break

        if not url and operation.startswith("notion."):
            if isinstance(result.get("url"), str):
                url = result["url"]
            elif isinstance(result.get("results"), list):
                url = next(
                    (
                        item.get("url")
                        for item in result["results"]
                        if isinstance(item, dict) and isinstance(item.get("url"), str)
                    ),
                    None,
                )
        elif not url and operation == "gmail.send" and result.get("message_id"):
            message_id = quote(str(result["message_id"]), safe="")
            url = f"https://mail.google.com/mail/u/0/#all/{message_id}"
        elif not url and operation.startswith("jira."):
            issue_key = result.get("key") or result.get("issue_id_or_key")
            if not issue_key and isinstance(result.get("issues"), list):
                issue_key = next(
                    (
                        issue.get("key")
                        for issue in result["issues"]
                        if isinstance(issue, dict) and issue.get("key")
                    ),
                    None,
                )
            site_url = self.credentials.get("site_url")
            if issue_key and isinstance(site_url, str):
                url = f"{site_url.rstrip('/')}/browse/{quote(str(issue_key), safe='')}"
        elif not url and operation.startswith("sheets."):
            spreadsheet_id = result.get("spreadsheetId") or arguments.get("spreadsheet_id")
            if spreadsheet_id:
                url = (
                    "https://docs.google.com/spreadsheets/d/"
                    f"{quote(str(spreadsheet_id), safe='')}/edit"
                )
        elif not url and operation.startswith("docs."):
            document_id = result.get("id") or arguments.get("document_id")
            if document_id:
                url = (
                    "https://docs.google.com/document/d/"
                    f"{quote(str(document_id), safe='')}/edit"
                )
        elif not url and operation == "slack.post":
            channel = result.get("channel") or arguments.get("channel")
            timestamp = result.get("ts")
            team = self.credentials.get("team")
            team_id = team.get("id") if isinstance(team, dict) else None
            if team_id and channel and timestamp:
                team_id = quote(str(team_id), safe="")
                channel = quote(str(channel), safe="")
                thread = str(timestamp).replace(".", "")
                url = (
                    f"https://app.slack.com/client/{team_id}/{channel}"
                    f"/thread/{channel}-{thread}"
                )

        if isinstance(url, str) and url.startswith("https://"):
            return {**result, "result_url": url}
        return result

    async def _execute_capability(self, operation: str, arguments: dict[str, Any]) -> dict:
        capability = capability_for(self.capability_manifest, operation)
        transport = capability.get("transport", {})
        agent_protocol = self.capability_manifest.get("agent_protocol")
        if self.provider_kind == "agent" and operation == "agent.task.run":
            return await self._agent_task_run(arguments, transport, str(agent_protocol or "aura"))
        if self.provider_kind == "mcp":
            return await self._mcp_call(
                {"tool_name": transport.get("tool_name", operation), "arguments": arguments}
            )
        if not self.base_url:
            raise ValueError("Capability provider has no endpoint")
        if self.provider_kind == "browser":
            settings = get_settings()
            worker = settings.browser_connector_url
            if not worker or not settings.browser_connector_token:
                raise ValueError("Browser connector worker is not configured")
            return await ProviderExecutor(
                {"api_key": settings.browser_connector_token},
                worker,
                self.timeout_seconds,
            )._request(
                "POST",
                f"{worker.rstrip('/')}/v1/execute",
                json={
                    "target_url": self.base_url,
                    "capability": operation,
                    "input": arguments,
                },
            )
        method = str(transport.get("method", "POST")).upper()
        path = transport.get("path")
        if self.provider_kind == "agent":
            path = path or "/invoke"
            payload = {
                "capability": operation,
                "input": arguments,
                "delegation": {"depth": 0, "may_delegate": False},
            }
        elif self.provider_kind == "plugin":
            path = path or "/invoke"
            payload = {"capability": operation, "input": arguments}
        elif self.provider_kind == "webhook":
            path = path or ""
            payload = arguments
        else:
            payload = arguments.get("body", arguments)
        for key, value in arguments.get("path", {}).items():
            encoded = quote(str(value), safe="")
            path = str(path or "").replace("{" + key + "}", encoded)
        if "{" in str(path or "") or "}" in str(path or ""):
            raise ValueError("Required path parameters are missing")
        url = f"{self.base_url.rstrip('/')}/{str(path or '').lstrip('/')}"
        kwargs: dict[str, Any] = {}
        if method in {"GET", "HEAD"}:
            kwargs["params"] = arguments.get("query", arguments)
        else:
            kwargs["json"] = payload
        return await self._request(method, url, **kwargs)

    @staticmethod
    def _agent_state(task: dict) -> str:
        status = task.get("status") or {}
        if isinstance(status, dict):
            state = status.get("state") or status.get("status")
        else:
            state = status
        return str(state or task.get("state") or "completed").lower()

    @staticmethod
    def _agent_artifacts(task: dict) -> list[dict]:
        artifacts = task.get("artifacts") or task.get("outputs") or []
        if isinstance(artifacts, dict):
            artifacts = [artifacts]
        return [item for item in artifacts if isinstance(item, dict)]

    @staticmethod
    def _reject_agent_tool_requests(payload: dict) -> None:
        pending: list[Any] = [payload]
        prohibited = {"tool_requests", "requested_actions", "aura_tool_requests"}
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                if any(value.get(key) for key in prohibited):
                    raise ValueError(
                        "External agents cannot invoke AURA tools in this release"
                    )
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)

    async def _cancel_agent_task(
        self,
        task_id: str,
        path_template: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        if not self.base_url or not task_id or not path_template:
            return
        path = path_template.replace("{task_id}", quote(task_id, safe=""))
        try:
            await self._request(
                "POST",
                f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
                json={},
                headers=headers or {},
            )
        except Exception:  # noqa: BLE001 - cancellation remains best effort
            return

    async def _agent_task_run(
        self,
        arguments: dict[str, Any],
        transport: dict[str, Any],
        protocol: str,
    ) -> dict:
        if not self.base_url:
            raise ValueError("Agent connection has no endpoint")
        goal = str(arguments.get("goal") or "").strip()
        if not goal:
            raise ValueError("agent.task.run requires a bounded goal")
        send_path = str(
            transport.get("send_path")
            or ("/message:send" if protocol == "a2a" else "/invoke")
        )
        status_path = str(transport.get("status_path") or "/tasks/{task_id}")
        cancel_path = str(
            transport.get("cancel_path")
            or ("/tasks/{task_id}:cancel" if protocol == "a2a" else "/tasks/{task_id}/cancel")
        )
        declared_limits = self.capability_manifest.get("limits") or {}
        budget = {
            "max_runtime_seconds": min(
                self.timeout_seconds,
                float(declared_limits.get("max_runtime_seconds") or self.timeout_seconds),
            ),
            "max_cost_usd": float(declared_limits.get("max_cost_usd") or 0),
        }
        if protocol == "a2a":
            protocol_version = str(transport.get("protocol_version") or "").strip()
            if not protocol_version:
                raise ValueError("A2A connection has no negotiated protocol version")
            request_headers = {
                "A2A-Version": protocol_version,
                "Accept": "application/a2a+json",
                "Content-Type": "application/a2a+json",
            }
            parts: list[dict[str, Any]] = [{"text": goal}]
            if arguments.get("context"):
                parts.append({"data": arguments["context"]})
            payload = {
                "message": {
                    "messageId": hashlib.sha256(
                        json.dumps(arguments, sort_keys=True).encode()
                    ).hexdigest()[:32],
                    "role": "ROLE_USER",
                    "parts": parts,
                    "metadata": {
                        "skill_id": arguments.get("skill_id"),
                        "delegation": {"depth": 0, "may_delegate": False},
                        "aura_budget": budget,
                    },
                },
                "configuration": {
                    "acceptedOutputModes": arguments.get("accepted_output_modes") or []
                },
            }
        else:
            request_headers = {}
            payload = {
                "capability": "agent.task.run",
                "input": {
                    "goal": goal,
                    "context": arguments.get("context") or {},
                    "skill_id": arguments.get("skill_id"),
                    "accepted_output_modes": arguments.get("accepted_output_modes") or [],
                },
                "delegation": {"depth": 0, "may_delegate": False},
                "budget": budget,
            }
        send_url = f"{self.base_url.rstrip('/')}/{send_path.lstrip('/')}"
        response = await self._request(
            "POST", send_url, json=payload, headers=request_headers
        )
        if not isinstance(response, dict):
            raise TypeError("Agent returned an invalid task response")
        self._reject_agent_tool_requests(response)
        message = response.get("message")
        if message is not None and not isinstance(message, dict):
            raise TypeError("Agent returned an invalid message")
        if message and not response.get("task") and not response.get("task_id"):
            return {
                "task_id": None,
                "status": "completed",
                "artifacts": [{"name": "Agent response", "parts": message.get("parts", [])}],
                "message": message,
            }
        task = response.get("task") if isinstance(response.get("task"), dict) else response
        task_id = str(task.get("id") or task.get("task_id") or response.get("task_id") or "")
        terminal = {"completed", "failed", "canceled", "cancelled", "rejected"}
        terminal.update({f"task_state_{state}" for state in terminal})
        deadline = time.monotonic() + self.timeout_seconds
        try:
            while self._agent_state(task) not in terminal:
                if not task_id:
                    raise ValueError("Agent returned a non-terminal task without an identifier")
                if time.monotonic() >= deadline:
                    await self._cancel_agent_task(task_id, cancel_path, request_headers)
                    raise TimeoutError("Agent task exceeded its execution budget")
                await asyncio.sleep(0.5)
                path = status_path.replace("{task_id}", quote(task_id, safe=""))
                polled = await self._request(
                    "GET",
                    f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
                    headers=request_headers,
                )
                if not isinstance(polled, dict):
                    raise TypeError("Agent returned an invalid task status")
                self._reject_agent_tool_requests(polled)
                task = polled.get("task") if isinstance(polled.get("task"), dict) else polled
        except asyncio.CancelledError:
            await asyncio.shield(
                self._cancel_agent_task(task_id, cancel_path, request_headers)
            )
            raise
        state = self._agent_state(task)
        if state not in {"completed", "task_state_completed"}:
            raise ValueError(f"Agent task ended with status {state}")
        artifacts = self._agent_artifacts(task)
        if not artifacts and not task.get("message"):
            raise ValueError("Agent completed without returning an artifact")
        return {
            "task_id": task_id or None,
            "status": "completed",
            "artifacts": artifacts,
            "message": task.get("message"),
        }

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict:
        headers = self._headers()
        headers.update(kwargs.pop("headers", {}) or {})
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            if response.status_code == 204:
                return {"status_code": 204}
            return response.json()

    async def _gmail_list(self, a: dict) -> dict:
        params = {"maxResults": min(int(a.get("limit", 10)), 50), "q": a.get("query", "")}
        return await self._request("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages", params=params)

    async def _gmail_send(self, a: dict) -> dict:
        recipient = str(a.get("to") or "").strip()
        if not recipient or recipient.lower() in {"me", "myself", "self"}:
            profile = await self._request(
                "GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile"
            )
            recipient = str(profile.get("emailAddress") or "").strip()
        if not recipient:
            raise ValueError("gmail.send could not resolve the approved recipient")
        message = EmailMessage()
        message["To"] = recipient
        message["Subject"] = str(a.get("subject") or "AURA workflow")
        message.set_content(str(a.get("body") or ""), charset="utf-8")
        from jsonschema import validate

        from .file_delivery import ATTACHMENTS_SCHEMA, MAX_FILE_BYTES, download_pdf, fingerprint
        attachments = a.get('attachments', [])
        validate(attachments, ATTACHMENTS_SCHEMA)
        total = 0
        for attachment in attachments:
            if not attachment.get('sha256') or not attachment.get('size'):
                raise ValueError('Attachment must be prepared and fingerprinted before sending')
            data = await download_pdf(attachment['url'])
            total += len(data)
            if total > MAX_FILE_BYTES or fingerprint(data) != {k: attachment[k] for k in ('sha256', 'size')}:
                raise ValueError('Attachment differs from the reviewed PDF or exceeds its budget')
            message.add_attachment(data, maintype='application', subtype='pdf', filename=attachment['filename'])
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
        result = await self._request("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", json={"raw": raw})
        return {
            **result,
            "message_id": result.get("id"),
            "thread_id": result.get("threadId"),
            "recipient": recipient,
            "subject": a.get("subject", "AURA workflow"),
            "body": a.get("body", ""),
            "attachments": [{k: item[k] for k in ('filename', 'sha256', 'size')} for item in attachments],
        }

    async def _gmail_get(self, a: dict) -> dict:
        base = "https://gmail.googleapis.com/gmail/v1/users/me/messages/" + quote(a["message_id"], safe="")
        result = await self._request("GET", base, params={"format": "full"})
        if not a.get('verify_attachments'):
            return result
        # Read bytes only for attachments on this exact receipt's message, bounded
        # independently of the mailbox. No account token reaches a download URL.
        from .file_delivery import MAX_FILE_BYTES
        pending, count, total = [result.get('payload', {})], 0, 0
        while pending:
            part = pending.pop()
            pending.extend(part.get('parts', []))
            if part.get('filename'):
                count += 1
                total += int(part.get('body', {}).get('size', 0))
                if count > 3 or total > MAX_FILE_BYTES:
                    raise ValueError('Message attachments exceed verification budget')
                attachment_id = part.get('body', {}).get('attachmentId')
                if attachment_id:
                    part['body'] = await self._request('GET', base + '/attachments/' + quote(attachment_id, safe=''))
        return result

    async def _calendar_get(self, a: dict) -> dict:
        return await self._request("GET", "https://www.googleapis.com/calendar/v3/calendars/primary/events/"
                                   + quote(a["event_id"], safe=""))

    async def _docs_create(self, a: dict) -> dict:
        """Import the approved text in one write, avoiding a blank intermediate Doc."""
        import secrets

        title = str(a["title"]).strip()
        body = str(a["body"])
        if not title or not body.strip():
            raise ValueError("docs.create requires a title and nonempty body")
        boundary = f"aura-{secrets.token_hex(16)}"
        metadata = json.dumps(
            {"name": title, "mimeType": "application/vnd.google-apps.document"},
            ensure_ascii=False,
        ).encode("utf-8")
        content = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
            + metadata
            + f"\r\n--{boundary}\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n".encode()
            + body.encode("utf-8")
            + f"\r\n--{boundary}--\r\n".encode()
        )
        try:
            return await self._request(
                "POST",
                "https://www.googleapis.com/upload/drive/v3/files",
                params={"uploadType": "multipart", "fields": "id,name,mimeType,webViewLink"},
                headers={"Content-Type": f"multipart/related; boundary={boundary}"},
                content=content,
            )
        except httpx.HTTPStatusError as exc:
            # Only the provider's fixed error category is logged. The response
            # body can contain customer content and must never enter logs.
            try:
                error = exc.response.json().get("error") or {}
                category = (error.get("errors") or [{}])[0].get("reason") or error.get("status")
            except (ValueError, AttributeError, IndexError, TypeError):
                category = None
            safe_category = category if isinstance(category, str) and re.fullmatch(
                r"[A-Za-z_]{3,64}", category
            ) else "unknown"
            logger.warning(
                "google_docs_create_rejected status=%s reason=%s",
                exc.response.status_code, safe_category,
            )
            raise

    async def _docs_get(self, a: dict) -> dict:
        result = await self._request(
            "GET",
            "https://docs.googleapis.com/v1/documents/"
            + quote(a["document_id"], safe=""),
            params={"includeTabsContent": "true"},
        )

        def text_from_body(body: dict) -> str:
            return "".join(
                element.get("textRun", {}).get("content", "")
                for item in body.get("content", [])
                for element in item.get("paragraph", {}).get("elements", [])
            )

        def tab_bodies(tabs: list[dict]) -> list[str]:
            return [
                text_from_body(tab.get("documentTab", {}).get("body", {}))
                for tab in tabs
                if tab.get("documentTab")
            ] + [
                content
                for tab in tabs
                for content in tab_bodies(tab.get("childTabs") or [])
            ]

        contents = tab_bodies(result.get("tabs") or [])
        if not contents:
            contents = [text_from_body(result.get("body", {}))]
        return {
            "id": result.get("documentId"),
            "title": result.get("title"),
            "body": "\n".join(contents).rstrip("\n"),
        }

    async def _weather_forecast(self, a: dict) -> dict:
        location = str(a.get("location") or "").strip()
        if not location:
            raise ValueError("weather.forecast requires a location")
        geocoded = await self._request(
            "GET",
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "en", "format": "json"},
        )
        places = geocoded.get("results") or []
        if not places:
            raise ValueError("AURA could not find that weather location")
        place = places[0]
        units = str(a.get("units") or "metric").lower()
        params = {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "timezone": "auto",
            "forecast_days": 7,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
        }
        if units == "imperial":
            params.update({"temperature_unit": "fahrenheit", "wind_speed_unit": "mph"})
        forecast = await self._request(
            "GET", "https://api.open-meteo.com/v1/forecast", params=params
        )
        daily = forecast.get("daily") or {}
        dates = daily.get("time") or []
        requested = str(a.get("date") or "tomorrow").strip().lower()
        # Provider dates use the requested location's timezone. Never silently
        # substitute another day when the requested date is outside the forecast.
        if requested in {"today", "tomorrow"}:
            index = 0 if requested == "today" else 1
            if len(dates) <= index:
                raise ValueError("Provider forecast does not cover the requested day")
            target = dates[index]
        else:
            target = requested
            if target not in dates:
                raise ValueError("Requested date is outside the provider forecast range")
            index = dates.index(target)
        day_count = int(a.get("days") or 1)
        if index + day_count > len(dates):
            raise ValueError("Provider forecast does not cover every requested day")
        fields = ("temperature_2m_max", "temperature_2m_min", "precipitation_probability_max", "wind_speed_10m_max", "weather_code")
        if any(len(daily.get(field) or []) < index + day_count for field in fields):
            raise ValueError("Provider forecast metrics do not cover the requested day")
        symbol = "°F" if units == "imperial" else "°C"
        wind_unit = "mph" if units == "imperial" else "km/h"
        location_name = ", ".join(
            filter(None, [place.get("name"), place.get("admin1"), place.get("country")])
        )

        def day_result(day_index: int) -> dict:
            item = {
                "location": location_name,
                "date": dates[day_index],
                "temperature_high": daily["temperature_2m_max"][day_index],
                "temperature_low": daily["temperature_2m_min"][day_index],
                "precipitation_probability": daily["precipitation_probability_max"][day_index],
                "wind_speed": daily["wind_speed_10m_max"][day_index],
                "weather_code": daily["weather_code"][day_index],
            }
            item["summary"] = (
                f"{item['date']}: {item['temperature_low']}{symbol} to "
                f"{item['temperature_high']}{symbol}, {item['precipitation_probability']}% chance "
                f"of precipitation, wind up to {item['wind_speed']} {wind_unit}."
            )
            return item

        forecasts = [day_result(day_index) for day_index in range(index, index + day_count)]
        result = {
            **forecasts[0],
            "forecasts": forecasts,
            "forecast_days": day_count,
            "max_precipitation_probability": max(
                item["precipitation_probability"] for item in forecasts
            ),
            "max_wind_speed": max(item["wind_speed"] for item in forecasts),
            "updated_at": datetime.now(UTC).isoformat(),
            "source": "Open-Meteo",
            "source_url": "https://open-meteo.com/",
        }
        return result

    async def _browser_worker_request(self, path: str, payload: dict) -> dict:
        settings = get_settings()
        if not settings.browser_connector_url or not settings.browser_connector_token:
            raise ValueError("Public web execution is not configured")
        executor = ProviderExecutor(
            {"api_key": settings.browser_connector_token},
            settings.browser_connector_url,
            self.timeout_seconds,
        )
        return await executor._request(
            "POST",
            f"{settings.browser_connector_url.rstrip('/')}/{path.lstrip('/')}",
            json=payload,
        )

    async def _web_search(self, a: dict) -> dict:
        return await self._browser_worker_request(
            "/v1/search",
            {"query": a["query"], "limit": min(int(a.get("limit", 10)), 20)},
        )

    async def _web_page_read(self, a: dict) -> dict:
        return await self._browser_worker_request("/v1/read", {"url": a["url"]})

    async def _creator_tiktok_screen(self, a: dict) -> dict:
        payload = {
            key: a[key]
            for key in (
                "query",
                "max_candidates",
                "videos_per_creator",
                "min_followers",
                "min_videos",
                "min_trimmed_mean_views",
                "min_original_audio_ratio",
                "recency_days",
            )
            if key in a
        }
        return await self._browser_worker_request("/v1/tiktok/screen", payload)

    async def _creator_candidates_exclude_existing(self, a: dict) -> dict:
        candidates = a.get("candidates") or []
        outreach_rows = a.get("creator_outreach_rows") or []
        my_creator_rows = a.get("my_creator_rows") or []

        def cells(rows: list) -> list[str]:
            return [
                str(cell).strip()
                for row in rows
                if isinstance(row, list)
                for cell in row
                if cell not in (None, "")
            ]

        def handle(value: object) -> str | None:
            text = str(value or "").strip().casefold()
            url_match = re.search(r"tiktok\.com/@([^/?#]+)", text)
            if url_match:
                return url_match.group(1).strip().casefold()
            direct = text.removeprefix("@").strip()
            return direct if re.fullmatch(r"[a-z0-9._-]+", direct) else None

        def email(value: object) -> str | None:
            text = str(value or "").strip().casefold()
            return text if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text) else None

        indexed_sources = {
            "creator_outreach": cells(outreach_rows),
            "my_creators": cells(my_creator_rows),
        }
        source_handles = {
            name: {found for value in values if (found := handle(value))}
            for name, values in indexed_sources.items()
        }
        source_emails = {
            name: {found for value in values if (found := email(value))}
            for name, values in indexed_sources.items()
        }
        eligible: list[dict] = []
        excluded: list[dict] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_handle = handle(
                candidate.get("handle") or candidate.get("profile_url")
            )
            candidate_email = email(candidate.get("public_email"))
            matches = [
                source
                for source in indexed_sources
                if (
                    candidate_handle
                    and candidate_handle in source_handles[source]
                )
                or (
                    candidate_email
                    and candidate_email in source_emails[source]
                )
            ]
            if matches:
                excluded.append({**candidate, "duplicate_sources": matches})
            else:
                eligible.append(candidate)
        return {
            "eligible_candidates": eligible,
            "excluded_candidates": excluded,
            "input_count": len(candidates),
            "eligible_count": len(eligible),
        }

    async def _calendar_list(self, a: dict) -> dict:
        params = {"singleEvents": "true", "orderBy": "startTime", "maxResults": min(int(a.get("limit", 20)), 100)}
        if a.get("query"): params["q"] = a["query"]
        if a.get("time_min"): params["timeMin"] = a["time_min"]
        if a.get("time_max"): params["timeMax"] = a["time_max"]
        from .calendar_time import annotate_calendar_times
        return annotate_calendar_times(await self._request("GET", "https://www.googleapis.com/calendar/v3/calendars/primary/events", params=params))

    async def _calendar_create(self, a: dict) -> dict:
        if not a.get("start") or not a.get("end"):
            raise ValueError("calendar.create requires approved start and end")
        payload = {"summary": a.get("title", "AURA event"), "description": a.get("description", ""), "start": a["start"], "end": a["end"]}
        return await self._request("POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events", json=payload)

    async def _google_identity_get(self, a: dict) -> dict:
        return await self._request(
            "GET", "https://openidconnect.googleapis.com/v1/userinfo"
        )

    async def _drive_files_search(self, a: dict) -> dict:
        query = str(a.get("query", "")).strip()
        if not query:
            raise ValueError("drive.files.search requires query")
        escaped = query.replace("\\", "\\\\").replace("'", "\\'")
        return await self._request(
            "GET",
            "https://www.googleapis.com/drive/v3/files",
            params={
                "q": f"name = '{escaped}' and trashed = false",
                "pageSize": min(int(a.get("page_size", 20)), 100),
                "fields": (
                    "nextPageToken,files(id,name,mimeType,createdTime,modifiedTime,"
                    "parents,driveId,owners(displayName,emailAddress,me),webViewLink)"
                ),
            },
        )

    async def _drive_spreadsheet_resolve(self, a: dict) -> dict:
        name = str(a.get("name", "")).strip()
        if not name:
            raise ValueError("drive.spreadsheet.resolve requires name")
        canonical_name = " ".join(name.split()).casefold()
        result = await self._drive_files_search({"query": name, "page_size": 10})
        matches = [
            item
            for item in result.get("files", [])
            if " ".join(str(item.get("name", "")).split()).casefold()
            == canonical_name
            and item.get("mimeType") == "application/vnd.google-apps.spreadsheet"
        ]
        resolution_source = "exact_name_search"
        alias_id = get_settings().resource_aliases.get(name.casefold())
        if len(matches) != 1 and alias_id:
            try:
                verified = await self._request(
                    "GET",
                    "https://www.googleapis.com/drive/v3/files/"
                    + quote(alias_id, safe=""),
                    params={
                        "fields": (
                            "id,name,mimeType,createdTime,modifiedTime,parents,driveId,"
                            "owners(displayName,emailAddress,me),webViewLink"
                        )
                    },
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {403, 404}:
                    raise AuthorizationRequired(
                        "authorization_required: the connected Google account cannot access "
                        f"the configured original named {name!r}"
                    ) from exc
                raise
            if (
                verified.get("id") == alias_id
                and " ".join(str(verified.get("name", "")).split()).casefold()
                == canonical_name
                and verified.get("mimeType")
                == "application/vnd.google-apps.spreadsheet"
            ):
                matches = [verified]
                resolution_source = "verified_resource_alias"
        resolved = len(matches) == 1
        return {
            "query": name,
            "status": "resolved" if resolved else "not_found" if not matches else "ambiguous",
            "match_count": len(matches),
            "matches": matches,
            "spreadsheet": matches[0] if resolved else None,
            "resolution_source": resolution_source,
        }

    async def _sheets_read(self, a: dict) -> dict:
        sid, cell_range = a.get("spreadsheet_id"), a.get("range", "A1:Z100")
        if not sid: raise ValueError("sheets.read requires spreadsheet_id")
        return await self._request("GET", f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{cell_range}")

    async def _sheets_append(self, a: dict) -> dict:
        sid, cell_range, values = a.get("spreadsheet_id"), a.get("range", "Sheet1!A1"), a.get("values")
        if not sid or not values: raise ValueError("sheets.append requires spreadsheet_id and approved values")
        return await self._request("POST", f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{cell_range}:append", params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"}, json={"values": values})

    async def _airtable_list(self, a: dict) -> dict:
        if not a.get("base_id") or not a.get("table_id"): raise ValueError("airtable.list requires base_id and table_id")
        return await self._request("GET", f"https://api.airtable.com/v0/{a['base_id']}/{a['table_id']}", params={"maxRecords": min(int(a.get("limit", 20)), 100)})

    async def _airtable_create(self, a: dict) -> dict:
        if not a.get("base_id") or not a.get("table_id") or not a.get("records"): raise ValueError("airtable.create requires base_id, table_id and approved records")
        return await self._request("POST", f"https://api.airtable.com/v0/{a['base_id']}/{a['table_id']}", json={"records": a["records"], "typecast": True})

    async def _notion_request(self, method: str, path: str, **kwargs: Any) -> dict:
        headers = self._headers()
        headers["Notion-Version"] = "2025-09-03"
        headers["Accept"] = "application/json"
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.request(
                method, f"https://api.notion.com/v1/{path.lstrip('/')}", headers=headers, **kwargs
            )
            response.raise_for_status()
            return response.json()

    async def _notion_search(self, a: dict) -> dict:
        sort = a.get("sort")
        direction = a.get("direction")
        sort_payload = None
        if sort or direction:
            sort_payload = {
                "timestamp": sort or "last_edited_time",
                "direction": direction or "descending",
            }
        payload = {
            key: value
            for key, value in {
                "query": a.get("query"),
                "page_size": min(int(a.get("page_size", 20)), 100),
                "start_cursor": a.get("start_cursor"),
                "filter": a.get("filter"),
                "sort": sort_payload,
            }.items()
            if value not in (None, "")
        }
        return await self._notion_request("POST", "search", json=payload)

    async def _notion_page_get(self, a: dict) -> dict:
        return await self._notion_request("GET", f"pages/{quote(a['page_id'], safe='')}")

    async def _notion_blocks_children_list(self, a: dict) -> dict:
        from .completeness import read_notion_tree
        if a.get("start_cursor"):
            return await self._notion_request("GET", f"blocks/{quote(a['block_id'], safe='')}/children",
                params={"page_size": min(int(a.get("page_size", 100)), 100), "start_cursor": a["start_cursor"]})
        return await read_notion_tree(self._notion_request, a["block_id"], page_size=min(int(a.get("page_size", 100)), 100))

    async def _notion_page_create(self, a: dict) -> dict:
        payload = {"parent": a["parent"], "properties": a["properties"]}
        if a.get("children") is not None:
            payload["children"] = a["children"]
        return await self._notion_request("POST", "pages", json=payload)

    async def _notion_page_update(self, a: dict) -> dict:
        payload = {"properties": a["properties"]}
        if "archived" in a:
            payload["archived"] = a["archived"]
        return await self._notion_request(
            "PATCH", f"pages/{quote(a['page_id'], safe='')}", json=payload
        )

    async def _notion_blocks_children_append(self, a: dict) -> dict:
        return await self._notion_request(
            "PATCH",
            f"blocks/{quote(a['block_id'], safe='')}/children",
            json={"children": a["children"]},
        )

    async def _canva_request(self, method: str, path: str, **kwargs: Any) -> dict:
        return await self._request(method, f"https://api.canva.com/rest/v1/{path.lstrip('/')}", **kwargs)

    async def _canva_designs_list(self, a: dict) -> dict:
        params = {key: a[key] for key in ("query", "continuation", "ownership") if a.get(key)}
        return await self._canva_request("GET", "designs", params=params)

    async def _canva_design_get(self, a: dict) -> dict:
        return await self._canva_request("GET", f"designs/{quote(a['design_id'], safe='')}")

    async def _canva_design_create(self, a: dict) -> dict:
        payload = {"design_type": a["design_type"]}
        if a.get("title"): payload["title"] = a["title"]
        if a.get("asset_id"): payload["asset_id"] = a["asset_id"]
        return await self._canva_request("POST", "designs", json=payload)

    async def _canva_presentation_create(self, a: dict) -> dict:
        import hashlib

        from .presentation_content import render_timeline
        data = render_timeline(a)
        headers = {**self._headers(), 'Content-Type': 'application/octet-stream',
            'Import-Metadata': json.dumps({'title_base64': base64.b64encode(a['title'].encode()).decode(),
                'mime_type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'})}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post('https://api.canva.com/rest/v1/imports', headers=headers, content=data)
            response.raise_for_status()
        page_count = len(a['phases']) if a.get('layout') == 'slides' else 1
        return {**response.json(), 'source_sha256': hashlib.sha256(data).hexdigest(), 'page_count': page_count}

    async def _canva_import_get(self, a: dict) -> dict:
        return await self._canva_request('GET', 'imports/' + quote(a['import_id'], safe=''))

    async def _canva_folder_items_list(self, a: dict) -> dict:
        params = {"limit": min(int(a.get("limit", 50)), 100)}
        if a.get("continuation"): params["continuation"] = a["continuation"]
        return await self._canva_request("GET", f"folders/{quote(a['folder_id'], safe='')}/items", params=params)

    async def _canva_export_create(self, a: dict) -> dict:
        payload = {"design_id": a["design_id"], "format": {"type": a["format"]}}
        # A successful import job already returns Canva's canonical design id.
        # Do not probe the design-metadata endpoint before exporting: that read
        # requires a separate permission and can reject an otherwise authorized
        # export. Dispatch exactly once. A definitive design_not_found rejection
        # is handled by the durable recovery supervisor; timeouts and lost
        # responses remain non-replayable.
        return await self._canva_request("POST", "exports", json=payload)

    async def _canva_export_get(self, a: dict) -> dict:
        return await self._canva_request("GET", f"exports/{quote(a['export_id'], safe='')}")

    async def _mailchimp_request(self, method: str, path: str, **kwargs: Any) -> dict:
        api_endpoint = self.credentials.get("api_endpoint")
        if not api_endpoint:
            raise ValueError("Mailchimp connection is missing its data center metadata")
        return await self._request(
            method, f"{api_endpoint.rstrip('/')}/3.0/{path.lstrip('/')}", **kwargs
        )

    async def _mailchimp_audiences_list(self, a: dict) -> dict:
        return await self._mailchimp_request(
            "GET", "lists", params={"count": min(int(a.get("count", 20)), 1000)}
        )

    async def _mailchimp_members_list(self, a: dict) -> dict:
        return await self._mailchimp_request(
            "GET",
            f"lists/{quote(a['list_id'], safe='')}/members",
            params={"count": min(int(a.get("count", 20)), 1000)},
        )

    async def _mailchimp_member_upsert(self, a: dict) -> dict:
        email = a["email_address"].strip().lower()
        subscriber_hash = hashlib.md5(email.encode(), usedforsecurity=False).hexdigest()
        payload = {
            "email_address": email,
            "status_if_new": a.get("status_if_new", "subscribed"),
        }
        if a.get("merge_fields") is not None:
            payload["merge_fields"] = a["merge_fields"]
        return await self._mailchimp_request(
            "PUT",
            f"lists/{quote(a['list_id'], safe='')}/members/{subscriber_hash}",
            json=payload,
        )

    async def _mailchimp_campaigns_list(self, a: dict) -> dict:
        return await self._mailchimp_request(
            "GET", "campaigns", params={"count": min(int(a.get("count", 20)), 1000)}
        )

    async def _mailchimp_campaign_create(self, a: dict) -> dict:
        return await self._mailchimp_request(
            "POST",
            "campaigns",
            json={"type": a["type"], "recipients": a["recipients"], "settings": a["settings"]},
        )

    async def _mailchimp_campaign_send(self, a: dict) -> dict:
        return await self._mailchimp_request(
            "POST", f"campaigns/{quote(a['campaign_id'], safe='')}/actions/send", json={}
        )

    async def _mailchimp_reports_list(self, a: dict) -> dict:
        return await self._mailchimp_request(
            "GET", "reports", params={"count": min(int(a.get("count", 20)), 1000)}
        )

    async def _tiktok_request(
        self, method: str, path: str, *, fields: str | None = None, body: dict | None = None
    ) -> dict:
        params = {"fields": fields} if fields else None
        data = await self._request(
            method,
            f"https://open.tiktokapis.com/v2/{path.lstrip('/')}",
            params=params,
            json=body,
        )
        error = data.get("error", {})
        if error.get("code") not in (None, "", "ok", 0):
            raise RuntimeError(error.get("message") or error.get("code"))
        return data

    async def _tiktok_profile_get(self, a: dict) -> dict:
        fields = (
            "open_id,union_id,avatar_url,display_name,profile_deep_link,"
            "is_verified,follower_count,following_count,likes_count,video_count"
        )
        return await self._tiktok_request("GET", "user/info/", fields=fields)

    async def _tiktok_videos_list(self, a: dict) -> dict:
        fields = (
            "id,title,video_description,duration,cover_image_url,embed_link,"
            "share_url,create_time,like_count,comment_count,share_count,view_count"
        )
        body = {"max_count": min(int(a.get("max_count", 20)), 20)}
        if a.get("cursor") is not None:
            body["cursor"] = int(a["cursor"])
        return await self._tiktok_request("POST", "video/list/", fields=fields, body=body)

    async def _tiktok_post_creator_info(self, a: dict) -> dict:
        return await self._tiktok_request("POST", "post/publish/creator_info/query/", body={})

    async def _tiktok_video_upload_init(self, a: dict) -> dict:
        return await self._tiktok_request(
            "POST", "post/publish/inbox/video/init/", body={"source_info": a["source_info"]}
        )

    async def _tiktok_video_publish_init(self, a: dict) -> dict:
        return await self._tiktok_request(
            "POST",
            "post/publish/video/init/",
            body={"post_info": a["post_info"], "source_info": a["source_info"]},
        )

    async def _tiktok_post_status_get(self, a: dict) -> dict:
        result = await self._tiktok_request(
            "POST", "post/publish/status/fetch/", body={"publish_id": a["publish_id"]}
        )
        return {**result, "_aura_requested_publish_id": a["publish_id"]}

    async def _airtable_record_get(self, a):
        return await self._request("GET", "https://api.airtable.com/v0/" + "/".join(quote(a[key], safe="") for key in ("base_id", "table_id", "record_id")))

    async def _slack_message_get(self, a):
        result = await self._request("GET", "https://slack.com/api/conversations.history", params={
            "channel": a["channel"], "oldest": a["ts"], "latest": a["ts"], "inclusive": "true", "limit": 1})
        if result.get("ok") is not True:
            raise RuntimeError("Slack read-back was not authorized or available")
        return {**result, "channel": a["channel"]}

    async def _hubspot_contact_get(self, a):
        return await self._request("GET", f"https://api.hubapi.com/crm/v3/objects/contacts/{quote(a['contact_id'], safe='')}",
            params={"properties": ",".join(a.get("properties", []))})

    async def _hubspot_company_get(self, a):
        return await self._request("GET", f"https://api.hubapi.com/crm/v3/objects/companies/{quote(a['company_id'], safe='')}",
            params={"properties": ",".join(a.get("properties", []))})

    async def _mailchimp_member_get(self, a):
        return await self._mailchimp_request("GET", f"lists/{quote(a['list_id'], safe='')}/members/{quote(a['subscriber_hash'], safe='')}")

    async def _mailchimp_campaign_get(self, a):
        return await self._mailchimp_request("GET", f"campaigns/{quote(a['campaign_id'], safe='')}")

    async def _slack_channels_list(self, a: dict) -> dict:
        params = {
            "limit": min(int(a.get("limit", 100)), 200),
            "exclude_archived": "true",
            "types": "public_channel",
        }
        if a.get("cursor"):
            params["cursor"] = a["cursor"]
        data = await self._request("GET", "https://slack.com/api/conversations.list", params=params)
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "Slack channel discovery failed"))
        return data

    async def _slack_post(self, a: dict) -> dict:
        if not a.get("channel") or not a.get("text"): raise ValueError("slack.post requires channel and approved text")
        data = await self._request("POST", "https://slack.com/api/chat.postMessage", json={"channel": a["channel"], "text": a["text"]})
        if not data.get("ok"): raise RuntimeError(data.get("error", "Slack post failed"))
        return data

    async def _hubspot_contacts_list(self, a: dict) -> dict:
        params = {
            "limit": min(int(a.get("limit", 20)), 100),
            "properties": ",".join(a.get("properties") or ["firstname", "lastname", "email", "lastmodifieddate"]),
        }
        if a.get("after"):
            params["after"] = a["after"]
        return await self._request("GET", "https://api.hubapi.com/crm/v3/objects/contacts", params=params)

    async def _hubspot_companies_list(self, a: dict) -> dict:
        params = {
            "limit": min(int(a.get("limit", 20)), 100),
            "properties": ",".join(a.get("properties") or ["name", "domain", "lastmodifieddate"]),
        }
        if a.get("after"):
            params["after"] = a["after"]
        return await self._request("GET", "https://api.hubapi.com/crm/v3/objects/companies", params=params)

    async def _hubspot_contact_update(self, a: dict) -> dict:
        return await self._request(
            "PATCH",
            f"https://api.hubapi.com/crm/v3/objects/contacts/{quote(a['contact_id'], safe='')}",
            json={"properties": a["properties"]},
        )

    async def _hubspot_company_update(self, a: dict) -> dict:
        return await self._request(
            "PATCH",
            f"https://api.hubapi.com/crm/v3/objects/companies/{quote(a['company_id'], safe='')}",
            json={"properties": a["properties"]},
        )

    async def _jira_request(self, method: str, path: str, **kwargs: Any) -> dict:
        cloud_id = self.credentials.get("cloud_id")
        if not cloud_id:
            raise ValueError("Jira connection is missing its authorized site")
        return await self._request(
            method,
            f"https://api.atlassian.com/ex/jira/{quote(str(cloud_id), safe='')}/rest/api/3/{path.lstrip('/')}",
            **kwargs,
        )

    async def _jira_projects_list(self, a: dict) -> dict:
        params = {"maxResults": min(int(a.get("limit", 50)), 100)}
        if "start_at" in a:
            params["startAt"] = a["start_at"]
        if a.get("query"):
            params["query"] = a["query"]
        return await self._jira_request("GET", "project/search", params=params)

    async def _jira_issues_search(self, a: dict) -> dict:
        payload = {
            "jql": a.get("jql", "order by updated DESC"),
            "maxResults": min(int(a.get("limit", 50)), 100),
            "fields": a.get("fields") or ["summary", "status", "assignee", "project", "issuetype", "updated"],
        }
        if a.get("next_page_token"):
            payload["nextPageToken"] = a["next_page_token"]
        return await self._jira_request("POST", "search/jql", json=payload)

    async def _jira_issue_get(self, a: dict) -> dict:
        fields = a.get("fields") or ["summary", "description", "status", "assignee", "project", "issuetype", "labels", "updated"]
        return await self._jira_request(
            "GET",
            f"issue/{quote(a['issue_id_or_key'], safe='')}",
            params={"fields": ",".join(fields)},
        )

    @staticmethod
    def _jira_description(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": value}]}],
        }

    async def _jira_issue_create(self, a: dict) -> dict:
        fields: dict[str, Any] = {
            "project": {"key": a["project_key"]},
            "summary": a["summary"],
            "issuetype": {"name": a.get("issue_type", "Task")},
        }
        for name in ("description", "labels", "priority"):
            if a.get(name) is not None:
                fields[name] = self._jira_description(a[name]) if name == "description" else a[name]
        if a.get("assignee_id"):
            fields["assignee"] = {"accountId": a["assignee_id"]}
        return await self._jira_request("POST", "issue", json={"fields": fields})

    @staticmethod
    def _notion_block_text(block: dict[str, Any]) -> str:
        block_type = str(block.get("type") or "")
        body = block.get(block_type)
        if not isinstance(body, dict):
            return ""
        rich_text = body.get("rich_text")
        if not isinstance(rich_text, list):
            return ""
        parts: list[str] = []
        for item in rich_text:
            if not isinstance(item, dict):
                continue
            value = item.get("plain_text")
            if not isinstance(value, str):
                text = item.get("text")
                value = text.get("content") if isinstance(text, dict) else None
            if isinstance(value, str):
                parts.append(value)
        return "".join(parts).strip()

    async def _jira_issues_create_from_blocks(self, a: dict) -> dict:
        blocks = a.get("source_blocks")
        if not isinstance(blocks, list):
            raise TypeError("Jira task batch requires retrieved Notion blocks")

        max_issues = min(max(int(a.get("max_issues", 20)), 1), 20)
        task_types = {"to_do", "bulleted_list_item", "numbered_list_item"}
        candidates = [
            self._notion_block_text(block)
            for block in blocks[:100]
            if isinstance(block, dict) and str(block.get("type") or "") in task_types
        ]
        summaries = []
        for value in candidates:
            summary = " ".join(value.split())[:255]
            if summary and summary not in summaries:
                summaries.append(summary)
            if len(summaries) >= max_issues:
                break
        if not summaries:
            raise ValueError("No actionable list or to-do blocks were found in the Notion page")

        project_key = str(a.get("project_key") or "").strip()
        if not project_key:
            project_response = await self._jira_projects_list(
                {"query": a.get("project_query"), "limit": 2}
            )
            projects = project_response.get("values")
            if not isinstance(projects, list) or len(projects) != 1:
                raise ValueError(
                    "AURA needs one unambiguous Jira project before creating the approved task batch"
                )
            project_key = str(projects[0].get("key") or "").strip()
        if not project_key:
            raise ValueError("The resolved Jira project has no project key")

        issue_type = str(a.get("issue_type") or "Task")
        issue_updates = [
            {
                "fields": {
                    "project": {"key": project_key},
                    "summary": summary,
                    "issuetype": {"name": issue_type},
                }
            }
            for summary in summaries
        ]
        result = await self._jira_request(
            "POST",
            "issue/bulk",
            json={"issueUpdates": issue_updates},
        )
        return {
            **result,
            "project_key": project_key,
            "requested_summaries": summaries,
            "issue_type": issue_type,
        }

    async def _jira_issue_update(self, a: dict) -> dict:
        fields = dict(a["fields"])
        if "description" in fields:
            fields["description"] = self._jira_description(fields["description"])
        result = await self._jira_request(
            "PUT", f"issue/{quote(a['issue_id_or_key'], safe='')}", json={"fields": fields}
        )
        return result or {"updated": True, "issue_id_or_key": a["issue_id_or_key"]}

    async def _http_request(self, a: dict) -> dict:
        if not self.base_url: raise ValueError("Custom HTTP tool has no base URL")
        path = str(a.get("path", "")).lstrip("/")
        url = f"{self.base_url.rstrip('/')}/{path}"
        if not url.startswith(self.base_url.rstrip("/")): raise ValueError("Request escaped the configured base URL")
        return await self._request(str(a.get("method", "GET")).upper(), url, params=a.get("query"), json=a.get("body"))

    async def _mcp_call(self, a: dict) -> dict:
        if not self.base_url:
            raise ValueError("MCP tool has no Streamable HTTP URL")
        if not a.get("tool_name"):
            raise ValueError("mcp.call requires an allow-listed tool_name")
        async with streamablehttp_client(self.base_url, headers=self._headers()) as (
            read,
            write,
            _,
        ), ClientSession(read, write) as session:
                await session.initialize()
                available = await session.list_tools()
                names = {tool.name for tool in available.tools}
                if a["tool_name"] not in names:
                    raise ValueError(f"MCP server does not expose {a['tool_name']!r}")
                result = await session.call_tool(a["tool_name"], arguments=a.get("arguments", {}))
                return {
                    "is_error": bool(result.isError),
                    "content": [item.model_dump(mode="json") for item in result.content],
                }


def idempotency_key(run_id: str, position: int, operation: str, arguments: dict) -> str:
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{run_id}:{position}:{operation}:{canonical}".encode()).hexdigest()
