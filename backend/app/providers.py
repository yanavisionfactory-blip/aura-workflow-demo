import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .config import Settings, get_settings
from .native_connectors import validate_module_arguments
from .universal_connectors import capability_for


@dataclass(frozen=True)
class OAuthProvider:
    slug: str
    display_name: str
    authorization_url: str
    token_url: str
    scopes: tuple[str, ...]
    client_id_attr: str
    client_secret_attr: str


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
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/spreadsheets.readonly",
        ),
        client_id_attr="google_client_id",
        client_secret_attr="google_client_secret",
    ),
    "airtable": OAuthProvider(
        slug="airtable",
        display_name="Airtable",
        authorization_url="https://airtable.com/oauth2/v1/authorize",
        token_url="https://airtable.com/oauth2/v1/token",
        scopes=("data.records:read", "data.records:write", "schema.bases:read"),
        client_id_attr="airtable_client_id",
        client_secret_attr="airtable_client_secret",
    ),
    "notion": OAuthProvider(
        slug="notion",
        display_name="Notion",
        authorization_url="https://api.notion.com/v1/oauth/authorize",
        token_url="https://api.notion.com/v1/oauth/token",
        scopes=(),
        client_id_attr="notion_client_id",
        client_secret_attr="notion_client_secret",
    ),
    "mailchimp": OAuthProvider(
        slug="mailchimp",
        display_name="Mailchimp",
        authorization_url="https://login.mailchimp.com/oauth2/authorize",
        token_url="https://login.mailchimp.com/oauth2/token",
        scopes=(),
        client_id_attr="mailchimp_client_id",
        client_secret_attr="mailchimp_client_secret",
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
    ),
    "tiktok": OAuthProvider(
        slug="tiktok",
        display_name="TikTok",
        authorization_url="https://www.tiktok.com/v2/auth/authorize/",
        token_url="https://open.tiktokapis.com/v2/oauth/token/",
        scopes=("user.info.basic", "video.list", "video.upload", "video.publish"),
        client_id_attr="tiktok_client_id",
        client_secret_attr="tiktok_client_secret",
    ),
    "slack": OAuthProvider(
        slug="slack",
        display_name="Slack",
        authorization_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scopes=("channels:read", "chat:write"),
        client_id_attr="slack_client_id",
        client_secret_attr="slack_client_secret",
    ),
}


def oauth_callback_url(settings: Settings, provider: OAuthProvider) -> str:
    # Providers registered against AURA's shared installation callback.
    callback_provider = "installation" if provider.slug in {"notion", "tiktok", "mailchimp", "canva"} else provider.slug
    return f"{settings.public_url}/v1/oauth/{callback_provider}/callback"


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
    settings: Settings, provider: OAuthProvider, code: str, state: str | None = None
) -> dict:
    client_id = getattr(settings, provider.client_id_attr)
    client_secret = getattr(settings, provider.client_secret_attr)
    payload = {
        ("client_key" if provider.slug == "tiktok" else "client_id"): client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": oauth_callback_url(settings, provider),
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
        response = await client.post(provider.token_url, data=payload, headers=headers)
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
    if provider.slug in {"airtable", "canva"}:
        basic = base64.b64encode(f"{payload['client_id']}:{payload['client_secret']}".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"
        payload.pop("client_secret")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(provider.token_url, data=payload, headers=headers)
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
    else:
        return {"ok": False, "reason": "unsupported_oauth_provider"}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.request(method, url, headers=headers, **kwargs)
        data = response.json() if "application/json" in response.headers.get("content-type", "") else {}
    ok = response.is_success and (provider_slug != "slack" or bool(data.get("ok")))
    identity_source = data.get("data", {}).get("user", {}) if provider_slug == "tiktok" else data
    identity = {
        key: identity_source.get(key)
        for key in (
            "sub", "email", "team", "team_id", "user", "user_id", "id",
            "open_id", "union_id", "display_name",
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
        header = self.credentials.get("header", "Authorization")
        prefix = self.credentials.get("prefix", "Bearer")
        return {header: f"{prefix} {token}".strip(), "Content-Type": "application/json"}

    async def execute(self, operation: str, arguments: dict[str, Any]) -> dict:
        if self.capability_manifest:
            validate_module_arguments(self.capability_manifest, operation, arguments)
        handlers = {
            "gmail.list": self._gmail_list,
            "gmail.send": self._gmail_send,
            "calendar.list": self._calendar_list,
            "calendar.create": self._calendar_create,
            "sheets.read": self._sheets_read,
            "sheets.append": self._sheets_append,
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
            "canva.folder.items.list": self._canva_folder_items_list,
            "canva.export.create": self._canva_export_create,
            "canva.export.get": self._canva_export_get,
            "http.request": self._http_request,
            "mcp.call": self._mcp_call,
        }
        if operation not in handlers:
            return await self._execute_capability(operation, arguments)
        return await handlers[operation](arguments)

    async def _execute_capability(self, operation: str, arguments: dict[str, Any]) -> dict:
        capability = capability_for(self.capability_manifest, operation)
        transport = capability.get("transport", {})
        if self.provider_kind == "mcp":
            return await self._mcp_call(
                {"tool_name": transport.get("tool_name", operation), "arguments": arguments}
            )
        if not self.base_url:
            raise ValueError("Capability provider has no endpoint")
        if self.provider_kind == "browser":
            worker = get_settings().browser_connector_url
            if not worker:
                raise ValueError("Browser connector worker is not configured")
            return await ProviderExecutor(
                self.credentials,
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

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.request(method, url, headers=self._headers(), **kwargs)
            response.raise_for_status()
            if response.status_code == 204:
                return {"status_code": 204}
            return response.json()

    async def _gmail_list(self, a: dict) -> dict:
        params = {"maxResults": min(int(a.get("limit", 10)), 50), "q": a.get("query", "")}
        return await self._request("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages", params=params)

    async def _gmail_send(self, a: dict) -> dict:
        if not a.get("to"):
            raise ValueError("gmail.send requires an approved recipient")
        message = "\r\n".join([
            f"To: {a['to']}", f"Subject: {a.get('subject', 'AURA workflow')}",
            "Content-Type: text/plain; charset=utf-8", "MIME-Version: 1.0", "", a.get("body", ""),
        ])
        raw = base64.urlsafe_b64encode(message.encode()).decode().rstrip("=")
        return await self._request("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", json={"raw": raw})

    async def _calendar_list(self, a: dict) -> dict:
        params = {"singleEvents": "true", "orderBy": "startTime", "maxResults": min(int(a.get("limit", 20)), 100)}
        if a.get("time_min"): params["timeMin"] = a["time_min"]
        if a.get("time_max"): params["timeMax"] = a["time_max"]
        return await self._request("GET", "https://www.googleapis.com/calendar/v3/calendars/primary/events", params=params)

    async def _calendar_create(self, a: dict) -> dict:
        if not a.get("start") or not a.get("end"):
            raise ValueError("calendar.create requires approved start and end")
        payload = {"summary": a.get("title", "AURA event"), "description": a.get("description", ""), "start": a["start"], "end": a["end"]}
        return await self._request("POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events", json=payload)

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
        payload = {
            key: value
            for key, value in {
                "query": a.get("query"),
                "page_size": min(int(a.get("page_size", 20)), 100),
                "start_cursor": a.get("start_cursor"),
            }.items()
            if value not in (None, "")
        }
        return await self._notion_request("POST", "search", json=payload)

    async def _notion_page_get(self, a: dict) -> dict:
        return await self._notion_request("GET", f"pages/{quote(a['page_id'], safe='')}")

    async def _notion_blocks_children_list(self, a: dict) -> dict:
        params = {"page_size": min(int(a.get("page_size", 100)), 100)}
        if a.get("start_cursor"):
            params["start_cursor"] = a["start_cursor"]
        return await self._notion_request(
            "GET", f"blocks/{quote(a['block_id'], safe='')}/children", params=params
        )

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

    async def _canva_folder_items_list(self, a: dict) -> dict:
        params = {"limit": min(int(a.get("limit", 50)), 100)}
        if a.get("continuation"): params["continuation"] = a["continuation"]
        return await self._canva_request("GET", f"folders/{quote(a['folder_id'], safe='')}/items", params=params)

    async def _canva_export_create(self, a: dict) -> dict:
        return await self._canva_request("POST", "exports", json={"design_id": a["design_id"], "format": {"type": a["format"]}})

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
        return await self._tiktok_request(
            "POST", "post/publish/status/fetch/", body={"publish_id": a["publish_id"]}
        )

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
        async with streamablehttp_client(self.base_url, headers=self._headers()) as (read, write, _):
            async with ClientSession(read, write) as session:
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
