import base64
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .config import Settings


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
    "slack": OAuthProvider(
        slug="slack",
        display_name="Slack",
        authorization_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scopes=("channels:read", "chat:write", "users:read"),
        client_id_attr="slack_client_id",
        client_secret_attr="slack_client_secret",
    ),
}


def oauth_authorization_url(settings: Settings, provider: OAuthProvider, state: str) -> str:
    client_id = getattr(settings, provider.client_id_attr)
    if not client_id:
        raise ValueError(f"{provider.display_name} OAuth client is not configured")
    params = {
        "client_id": client_id,
        "redirect_uri": f"{settings.public_url}/v1/oauth/{provider.slug}/callback",
        "response_type": "code",
        "state": state,
    }
    if provider.slug == "slack":
        params["scope"] = ",".join(provider.scopes)
    else:
        params["scope"] = " ".join(provider.scopes)
    if provider.slug == "google":
        params.update({"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"})
    return f"{provider.authorization_url}?{urlencode(params)}"


async def exchange_oauth_code(settings: Settings, provider: OAuthProvider, code: str) -> dict:
    client_id = getattr(settings, provider.client_id_attr)
    client_secret = getattr(settings, provider.client_secret_attr)
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": f"{settings.public_url}/v1/oauth/{provider.slug}/callback",
    }
    headers = {"Accept": "application/json"}
    if provider.slug == "airtable":
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"
        payload.pop("client_secret")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(provider.token_url, data=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    if provider.slug == "slack" and not data.get("ok", False):
        raise RuntimeError(data.get("error", "Slack OAuth failed"))
    if data.get("expires_in"):
        data["expires_at"] = int(time.time()) + int(data["expires_in"])
    return data


async def refresh_oauth_credentials(settings: Settings, provider_slug: str, credentials: dict) -> tuple[dict, bool]:
    """Refresh shortly before expiry; returns credentials and whether they changed."""
    if not credentials.get("refresh_token") or int(credentials.get("expires_at", 0)) > int(time.time()) + 90:
        return credentials, False
    provider = PROVIDERS.get(provider_slug)
    if not provider:
        return credentials, False
    payload = {
        "client_id": getattr(settings, provider.client_id_attr),
        "client_secret": getattr(settings, provider.client_secret_attr),
        "refresh_token": credentials["refresh_token"],
        "grant_type": "refresh_token",
    }
    headers = {"Accept": "application/json"}
    if provider.slug == "airtable":
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


class ProviderExecutor:
    """Executes only allow-listed operations; credentials never enter model context."""

    def __init__(self, credentials: dict[str, Any], base_url: str | None = None):
        self.credentials = credentials
        self.base_url = base_url

    def _headers(self) -> dict[str, str]:
        token = self.credentials.get("access_token") or self.credentials.get("api_key")
        header = self.credentials.get("header", "Authorization")
        prefix = self.credentials.get("prefix", "Bearer")
        return {header: f"{prefix} {token}".strip(), "Content-Type": "application/json"}

    async def execute(self, operation: str, arguments: dict[str, Any]) -> dict:
        handlers = {
            "gmail.list": self._gmail_list,
            "gmail.send": self._gmail_send,
            "calendar.list": self._calendar_list,
            "calendar.create": self._calendar_create,
            "sheets.read": self._sheets_read,
            "sheets.append": self._sheets_append,
            "airtable.list": self._airtable_list,
            "airtable.create": self._airtable_create,
            "slack.post": self._slack_post,
            "http.request": self._http_request,
            "mcp.call": self._mcp_call,
        }
        if operation not in handlers:
            raise ValueError(f"Operation {operation!r} is not executable")
        return await handlers[operation](arguments)

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict:
        async with httpx.AsyncClient(timeout=45) as client:
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
