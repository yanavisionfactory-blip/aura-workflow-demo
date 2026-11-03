"""Server-owned social authorization. No broker login or keys for customers.

References: docs.zernio.com/multi-tenant and /guides/connecting-accounts.
Only verified account/profile references are saved; OAuth tokens stay at Zernio.
"""
import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import httpx
from sqlalchemy import select, update

from .config import get_settings
from .db import set_tenant_context
from .models import (
    CapabilityManifest,
    TenantMembership,
    ToolConnection,
    ToolKind,
    Workspace,
    ZernioAuthorization,
    ZernioProfile,
)
from .security import CredentialVault

BASE_URL = "https://zernio.com/api/v1"
PROVIDERS = {"tiktok-zernio": ("tiktok", "TikTok"), "x-zernio": ("twitter", "X (Twitter)")}
OPERATIONS = ("zernio.account.get", "zernio.posts.list")


class ZernioError(ValueError):
    def __init__(self, message, *, retryable=False, code="connection_unavailable"):
        super().__init__(message)
        self.retryable = retryable
        self.code = code


def _id(value):
    return str(value.get("_id") or value.get("id") or "") if isinstance(value, dict) else str(value or "")


def _valid_id(value):
    import re
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value):
        raise ZernioError("AURA could not verify this account reference.")
    return value


def account_view(account):
    # Deliberately omit broker metadata and any future credential fields.
    return {"id": _id(account), "platform": str(account.get("platform") or ""),
            "username": str(account.get("username") or ""),
            "display_name": str(account.get("displayName") or account.get("username") or ""),
            "profile_url": str(account.get("profileUrl") or "")}


class ZernioClient:
    def __init__(self, settings=None, timeout=30):
        self.settings = settings or get_settings()
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.settings.zernio_api_key.get_secret_value())

    async def request(self, method, path, **kwargs):
        if not self.configured:
            raise ZernioError("AURA's social connection service is awaiting activation.", code="setup_required")
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, headers={
                    "Authorization": "Bearer " + self.settings.zernio_api_key.get_secret_value(),
                }, **kwargs)
        except httpx.HTTPError:
            raise ZernioError("The connection service is temporarily unavailable. Try again shortly.", retryable=True) from None
        if response.status_code == 402:
            # Billing belongs to AURA. Never send customers to the broker's billing/login page.
            raise ZernioError("AURA needs to activate this social connection. Please contact AURA support.", code="billing_required")
        if response.status_code == 429 or response.status_code >= 500:
            raise ZernioError("The connection service is temporarily unavailable. Try again shortly.", retryable=True)
        if not 200 <= response.status_code < 300:
            raise ZernioError("The social connection could not be verified. Please try Connect again.")
        if response.status_code == 204:
            return {}
        try:
            data = response.json()
        except ValueError:
            raise ZernioError("The connection service returned an invalid response.") from None
        if not isinstance(data, dict) or data.get("error"):
            raise ZernioError("The social connection could not be verified.")
        return data

    async def account(self, profile_id, account_id, platform, *, require_active=True):
        _valid_id(profile_id)
        _valid_id(account_id)
        data = await self.request("GET", "/accounts", params={"profileId": profile_id})
        accounts = data.get("accounts")
        if not isinstance(accounts, list):
            raise ZernioError("The service did not return an account list.")
        matches = [a for a in accounts if isinstance(a, dict) and _id(a) == account_id
                   and _id(a.get("profileId")) == profile_id and a.get("platform") == platform]
        if len(matches) != 1:
            raise ZernioError("This account does not belong to the requested AURA connection.")
        account = matches[0]
        if require_active and (account.get("isActive") is not True or account.get("needsReconnection") is True):
            raise ZernioError("Please reconnect this social account to restore access.", code="authorization_required")
        return account

    async def verify(self, reference):
        account = await self.account(reference["profile_id"], reference["account_id"], reference["platform"])
        health = await self.request("GET", f"/accounts/{_valid_id(reference['account_id'])}/health")
        if (health.get("accountId") != reference["account_id"]
                or health.get("platform") != reference["platform"]
                or (health.get("tokenStatus") or {}).get("valid") is not True):
            raise ZernioError("Please reconnect this social account to restore access.", code="authorization_required")
        return {"ok": True, "source": "zernio", "identity": account_view(account)}


def catalog(settings=None):
    configured = ZernioClient(settings).configured
    return [{"provider": slug, "display_name": name,
             "canonical_provider": "x" if platform == "twitter" else platform,
             "auth_mode": "OAUTH2", "managed": True, "source": "native",
             "connection_backend": "zernio" if configured else None, "preferred_connection": configured,
             "connectable": configured, "availability": "available" if configured else "coming_soon",
             "capability_count": len(OPERATIONS), "capabilities": list(OPERATIONS),
             "setup_hint": "Sign in with " + name}
            for slug, (platform, name) in PROVIDERS.items()]


def state_workspace(state, settings):
    # X embeds this URL plus its exit notice and reconnect marker in a limited
    # OAuth state. The workspace prefix ONLY locates the tenant partition: it
    # is untrusted until the hash of the entire 128-bit random token matches a
    # live, unused grant there. Changing either part invalidates that lookup.
    try:
        workspace, nonce = state.split(".")
        import re
        if not re.fullmatch(r"[A-Za-z0-9_-]{22}", workspace) or not re.fullmatch(r"[A-Za-z0-9_-]{22}", nonce):
            raise ValueError()
        return str(UUID(bytes=base64.urlsafe_b64decode(workspace + "==")))
    except (ValueError, AttributeError):
        raise ZernioError("This connection link is invalid or expired. Start again from Connect.") from None


async def start(session, context, provider, settings):
    platform, _ = PROVIDERS[provider]
    client = ZernioClient(settings)
    if not client.configured:
        raise ZernioError("AURA's social connection service is awaiting activation.", code="setup_required")
    # Serializes profile provisioning and concurrent reconnect attempts in PostgreSQL.
    workspace = await session.scalar(select(Workspace).where(Workspace.id == context.workspace_id).with_for_update())
    if not workspace:
        raise ZernioError("Workspace not found.")
    profile = await session.get(ZernioProfile, context.workspace_id)
    if not profile:
        name = "aura-" + hashlib.sha256(context.workspace_id.encode()).hexdigest()[:32]
        # Recover an already-created profile after a network timeout or DB rollback.
        data = await client.request("GET", "/profiles")
        profiles = data.get("profiles")
        if not isinstance(profiles, list):
            raise ZernioError("AURA could not verify the customer profile.")
        matches = [p for p in profiles if isinstance(p, dict) and p.get("name") == name]
        if len(matches) > 1:
            raise ZernioError("AURA could not verify the customer profile.")
        remote = matches[0] if matches else (await client.request("POST", "/profiles", json={"name": name})).get("profile")
        profile_id = _valid_id(_id(remote))
        profile = ZernioProfile(workspace_id=context.workspace_id, profile_id=profile_id)
        session.add(profile)
        await session.flush()
    tool = await session.scalar(select(ToolConnection).where(
        ToolConnection.workspace_id == context.workspace_id, ToolConnection.slug == provider))
    if tool and (tool.config or {}).get("managed_by") != "zernio":
        raise ZernioError("This connection uses a different authorization service.")
    workspace_token = base64.urlsafe_b64encode(UUID(context.workspace_id).bytes).decode().rstrip("=")
    state = workspace_token + "." + secrets.token_urlsafe(16)
    callback = settings.public_url.rstrip("/") + "/v1/z/c?" + urlencode({"s": state})
    params = {"profileId": profile.profile_id, "redirect_url": callback}
    if tool and tool.external_account_id:
        # The broker enforces this before changing any existing provider grant.
        params["reconnectAccountId"] = tool.external_account_id
    result = await client.request("GET", "/connect/" + platform, params=params)
    url = result.get("authUrl") or ""
    parsed = urlsplit(url)
    allowed = {"twitter": {"twitter.com", "www.twitter.com", "x.com", "www.x.com"},
               "tiktok": {"www.tiktok.com", "tiktok.com", "business-api.tiktok.com"}}
    if parsed.scheme != "https" or parsed.hostname not in allowed[platform] or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ZernioError("The service did not return a direct social-account authorization link.")
    await session.execute(update(ZernioAuthorization).where(
        ZernioAuthorization.workspace_id == context.workspace_id,
        ZernioAuthorization.provider == provider, ZernioAuthorization.consumed.is_(False),
    ).values(consumed=True))
    session.add(ZernioAuthorization(
        id=hashlib.sha256(state.encode()).hexdigest(), workspace_id=context.workspace_id,
        subject=context.subject, provider=provider, profile_id=profile.profile_id,
        tool_id=tool.id if tool else None, account_id=tool.external_account_id if tool else None,
        expires_at=datetime.now(UTC) + timedelta(minutes=15), consumed=False,
    ))
    await session.commit()
    return {"backend": "zernio", "provider": provider, "authorization_url": url,
            "previous_updated_at": tool.updated_at.isoformat() if tool and tool.updated_at else None}


async def finish(session, state, account_id, profile_id, platform, error, settings):
    workspace_id = state_workspace(state, settings)
    await set_tenant_context(session, workspace_id)
    grant_id = hashlib.sha256(state.encode()).hexdigest()
    grant = await session.scalar(select(ZernioAuthorization).where(
        ZernioAuthorization.id == grant_id, ZernioAuthorization.workspace_id == workspace_id,
        ZernioAuthorization.consumed.is_(False), ZernioAuthorization.expires_at > datetime.now(UTC),
    ).with_for_update())
    if not grant:
        raise ZernioError("This connection link is invalid or expired. Start again from Connect.")
    member = await session.scalar(select(TenantMembership).where(
        TenantMembership.workspace_id == workspace_id, TenantMembership.subject == grant.subject,
        TenantMembership.active.is_(True),
    ))
    if not member:
        raise ZernioError("Your workspace access has changed. Sign in to AURA again.")
    if error:
        grant.consumed = True
        await session.commit()
        raise ZernioError("The app did not grant access. Start a fresh connection from Connect.")
    expected_platform = PROVIDERS[grant.provider][0]
    if (profile_id != grant.profile_id or platform != expected_platform
            or (grant.account_id and account_id != grant.account_id)):
        raise ZernioError("This authorization does not match the requested account.")
    reference = {"profile_id": grant.profile_id, "account_id": _valid_id(account_id), "platform": expected_platform}
    verification = await ZernioClient(settings).verify(reference)
    from .native_connectors import native_manifest, native_operations
    tool = await session.scalar(select(ToolConnection).where(
        ToolConnection.workspace_id == workspace_id, ToolConnection.slug == grant.provider))
    if (tool.id if tool else None) != grant.tool_id:
        raise ZernioError("This connection changed while you were authorizing. Start again from Connect.")
    claimed = await session.execute(update(ZernioAuthorization).where(
        ZernioAuthorization.id == grant_id, ZernioAuthorization.consumed.is_(False),
    ).values(consumed=True))
    if claimed.rowcount != 1:
        raise ZernioError("This connection link has already been used.")
    if not tool:
        tool = ToolConnection(workspace_id=workspace_id, slug=grant.provider,
                              display_name=PROVIDERS[grant.provider][1], kind=ToolKind.oauth)
        session.add(tool)
    tool.config = {"managed_by": "zernio", "canonical_provider": "x" if expected_platform == "twitter" else expected_platform,
                   **reference}
    tool.external_account_id = account_id
    tool.external_connection_id = "zernio:" + account_id
    tool.encrypted_credentials = CredentialVault().encrypt({"zernio": reference})
    tool.allowed_operations = native_operations(grant.provider)
    tool.enabled = True
    tool.updated_at = datetime.now(UTC)
    await session.flush()
    manifest = await session.scalar(select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id))
    if not manifest:
        manifest = CapabilityManifest(workspace_id=workspace_id, tool_id=tool.id, provider_type="zernio")
        session.add(manifest)
    manifest.manifest = native_manifest(grant.provider)
    manifest.verification = verification
    manifest.status = "verified"
    manifest.verified_at = datetime.now(UTC)
    return tool, grant.subject


async def verify_tool(tool, settings=None):
    reference = {key: (tool.config or {}).get(key, "") for key in ("profile_id", "account_id", "platform")}
    if tool.slug not in PROVIDERS or reference["platform"] != PROVIDERS[tool.slug][0]:
        raise ZernioError("The social connection reference is invalid.")
    return await ZernioClient(settings).verify(reference)


async def execute(credentials, operation, arguments, timeout):
    reference = credentials.get("zernio") or {}
    if operation not in OPERATIONS or reference.get("platform") not in {"twitter", "tiktok"}:
        raise ZernioError("This operation is not available on this connection.")
    client = ZernioClient(timeout=timeout)
    account = await client.account(reference.get("profile_id"), reference.get("account_id"), reference.get("platform"))
    if operation == "zernio.account.get":
        return {"account": account_view(account)}
    data = await client.request("GET", f"/accounts/{_valid_id(reference['account_id'])}/posts")
    if not isinstance(data.get("posts"), list) or data.get("status") in {"pending", "syncing", "error", "failed"}:
        raise ZernioError("The platform's posts are not available yet. Try again shortly.", retryable=True)
    fields = ("id", "platform", "message", "createdTime", "permalink", "mediaType", "commentCount", "likeCount")
    posts = []
    for post in data["posts"]:
        if not isinstance(post, dict) or not post.get("id") or post.get("platform") not in {None, reference["platform"]}:
            raise ZernioError("The service returned invalid post data.")
        posts.append({key: post[key] for key in fields if key in post})
    return {"account_id": reference["account_id"], "posts": posts, "last_updated": data.get("lastUpdated")}
