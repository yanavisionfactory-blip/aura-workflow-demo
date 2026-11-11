"""Exercise the real MCP transport, JWT verification and workspace database boundary."""

import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from sqlalchemy import func, select

from app import chatgpt_mcp as bridge
from app.models import (
    AuditEvent,
    TenantMembership,
    ToolConnection,
    ToolKind,
    Workflow,
    WorkflowRun,
    Workspace,
)


@pytest.fixture
def config():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = SimpleNamespace(
        clerk_issuer="https://clerk.example.com",
        clerk_jwks_url="",
        clerk_jwt_key=key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
        public_url="https://aura.example.com",
        frontend_url="https://aura.example.com/app",
        chatgpt_mcp_allowed_client_ids="https://chatgpt.com/oauth/client.json",
        chatgpt_mcp_enabled=True,
        canary_mode=False,
        run_rate_limit_per_minute=60,
    )
    return settings, key


def bearer(config, *, typ="at+jwt", **overrides):
    settings, key = config
    claims = {
        "iss": settings.clerk_issuer,
        "sub": "user_alice",
        "iat": int(time.time()) - 1,
        "exp": int(time.time()) + 300,
        "aud": settings.public_url + "/mcp",
        "client_id": settings.chatgpt_mcp_allowed_client_ids,
        "scope": bridge.READ_SCOPE,
    }
    claims.update(overrides)
    return jwt.encode(
        {k: v for k, v in claims.items() if v is not None},
        key,
        algorithm="RS256",
        headers={"typ": typ},
    )


@asynccontextmanager
async def client(config):
    server = bridge.build_mcp_server(config[0])
    app = server.streamable_http_app()
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=config[0].public_url
        ) as http,
    ):
        yield http


async def rpc(http, token, method="tools/list", params=None):
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return await http.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        },
    )


async def call(http, token, tool_name, **arguments):
    response = await rpc(http, token, "tools/call", {"name": tool_name, "arguments": arguments})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def payload(result):
    return json.loads(result["content"][0]["text"])


@pytest.fixture
async def seeded(database, monkeypatch):
    monkeypatch.setattr(bridge, "SessionLocal", database)
    async with database() as session:
        session.add_all(
            [
                Workspace(id="a", name="Alice", external_organization_id="personal:user_alice"),
                Workspace(id="b", name="Bob", external_organization_id="personal:user_bob"),
                Workspace(id="old", name="Revoked", external_organization_id="personal:user_alice"),
                Workspace(id="org", name="Team", external_organization_id="org_team"),
            ]
        )
        await session.flush()
        session.add_all(
            [
                TenantMembership(workspace_id="a", subject="user_alice", role="owner"),
                TenantMembership(workspace_id="b", subject="user_bob", role="owner"),
                TenantMembership(workspace_id="old", subject="user_alice", active=False),
                TenantMembership(workspace_id="org", subject="user_alice", role="member"),
                Workflow(id="wa", workspace_id="a", name="Alice workflow", prompt="Alice task"),
                Workflow(id="wb", workspace_id="b", name="Bob workflow", prompt="Bob private task"),
                ToolConnection(
                    workspace_id="a",
                    slug="gmail",
                    display_name="Gmail",
                    kind=ToolKind.oauth,
                    encrypted_credentials="never-return-this",
                    external_account_id="private-account",
                    config={"token": "private-token"},
                ),
            ]
        )
        await session.commit()
    return database


async def test_metadata_and_unauthenticated_challenge(config):
    async with client(config) as http:
        response = await http.get("/.well-known/oauth-protected-resource/mcp")
        assert response.status_code == 200
        assert response.json()["resource"] == "https://aura.example.com/mcp"
        assert response.json()["authorization_servers"] == [config[0].clerk_issuer]
        response = await rpc(http, None)
        assert response.status_code == 401
        assert "/.well-known/oauth-protected-resource/mcp" in response.headers["www-authenticate"]


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "https://another.example.com/mcp"},
        {"aud": None},
        {"iss": "https://attacker.example.com"},
        {"iss": None},
        {"exp": 1},
        {"exp": None},
        {"nbf": 9999999999},
        {"client_id": "https://attacker.example.com/client"},
        {"client_id": None},
        {"typ": "JWT"},
        {"scope": None},
        {"scope": ["aura:read"]},
        {"sub": "machine_123"},
        {"org_id": "org_team"},
    ],
)
async def test_invalid_bearer_never_reaches_tools(config, changes):
    async with client(config) as http:
        response = await rpc(http, bearer(config, **changes))
        assert response.status_code == 401


async def test_invalid_signature_and_missing_scope(config):
    async with client(config) as http:
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        assert (await rpc(http, bearer((config[0], other_key)))).status_code == 401
        assert (await rpc(http, bearer(config, scope="profile"))).status_code == 403


async def test_clerk_scope_formats(config):
    async with client(config) as http:
        assert (await rpc(http, bearer(config, scope=None, scp=["aura:read"]))).status_code == 200
        assert (await rpc(http, bearer(config, scp=["unrelated"]))).status_code == 401


async def test_discovery_exposes_only_pilot_tools(config):
    async with client(config) as http:
        initialized = await rpc(http, bearer(config), "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "aura-pilot-test", "version": "1.0"},
        })
        assert initialized.status_code == 200
        assert initialized.json()["result"]["serverInfo"]["name"] == "AURA"
        assert "mcp-session-id" not in initialized.headers
        result = (await rpc(http, bearer(config))).json()["result"]
    tools = {tool["name"]: tool for tool in result["tools"]}
    assert set(tools) == {
        "list_workspaces",
        "list_connections",
        "list_workflows",
        "get_workflow",
        "save_workflow_draft",
    }
    assert tools["list_connections"]["annotations"]["readOnlyHint"] is True
    draft = tools["save_workflow_draft"]
    assert draft["annotations"]["readOnlyHint"] is False
    assert bridge.DRAFT_SCOPE in draft["securitySchemes"][0]["scopes"]


async def test_list_respects_identity_organization_and_revocation(config, seeded):
    async with client(config) as http:
        personal = payload(await call(http, bearer(config), "list_workspaces"))
        assert [row["id"] for row in personal["workspaces"]] == ["a"]
        org_token = bearer(config, org_id="org_team", scope="aura:read user:org:read")
        team = payload(await call(http, org_token, "list_workspaces"))
        assert [row["id"] for row in team["workspaces"]] == ["org"]
        for workspace_id in ["b", "old", "org", "nonexistent"]:
            result = await call(http, bearer(config), "list_workflows", workspace_id=workspace_id)
            assert result["isError"] is True
            assert "Bob private" not in str(result)
        # Revocation takes effect even while the OAuth bearer is unexpired.
        async with seeded() as session:
            membership = await session.scalar(
                select(TenantMembership).where(TenantMembership.workspace_id == "a")
            )
            membership.active = False
            await session.commit()
        result = await call(http, bearer(config), "list_connections", workspace_id="a")
        assert result["isError"] is True


async def test_reads_filter_secrets_and_foreign_workflow(config, seeded):
    async with client(config) as http:
        result = payload(await call(http, bearer(config), "list_connections", workspace_id="a"))
        assert result == {"connections": [{"slug": "gmail", "name": "Gmail", "enabled": True}]}
        result = await call(
            http, bearer(config), "get_workflow", workspace_id="a", workflow_id="wb"
        )
        assert result["isError"] is True
        assert "Bob" not in str(result)
        result = payload(
            await call(http, bearer(config), "get_workflow", workspace_id="a", workflow_id="wa")
        )
        assert result["prompt"] == "Alice task"
        assert "variables" not in result


async def test_draft_requires_scope_and_never_executes(config, seeded):
    args = {
        "workspace_id": "a",
        "name": "Review test",
        "prompt": "Draft a weekly report",
        "request_key": "pilot-draft-0001",
    }
    async with client(config) as http:
        result = await call(http, bearer(config), "save_workflow_draft", **args)
        assert result["isError"] is True
        assert bridge.DRAFT_SCOPE in result["_meta"]["mcp/www_authenticate"][0]
        token = bearer(config, scope="aura:read aura:drafts:write")
        first = payload(await call(http, token, "save_workflow_draft", **args))
        second = payload(await call(http, token, "save_workflow_draft", **args))
        assert first["executed"] is False and first["replayed"] is False
        assert second["id"] == first["id"] and second["replayed"] is True
        conflict = await call(http, token, "save_workflow_draft", **{**args, "prompt": "Different"})
        assert conflict["isError"] is True
        foreign = await call(http, token, "save_workflow_draft", **{**args, "workspace_id": "b"})
        assert foreign["isError"] is True
    async with seeded() as session:
        draft = await session.get(Workflow, first["id"])
        assert draft.enabled is False and draft.plan == {} and draft.variables == {}
        assert await session.scalar(select(func.count()).select_from(WorkflowRun)) == 0
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 1


async def test_body_validation_and_host_protection(config, seeded):
    async with client(config) as http:
        result = await call(http, bearer(config), "list_workflows", workspace_id="a", limit=1000)
        assert result["isError"] is True
        response = await http.post(
            "/mcp",
            headers={
                "Host": "evil.example.com",
                "Authorization": f"Bearer {bearer(config)}",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 421


@pytest.mark.parametrize("enabled,canary", [(False, False), (True, True)])
async def test_disabled_and_canary_do_not_mount_mcp(config, enabled, canary):
    config[0].chatgpt_mcp_enabled = enabled
    config[0].canary_mode = canary
    app = FastAPI()
    bridge.install_chatgpt_mcp(app, config[0])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://aura.example.com"
    ) as http:
        assert (await http.get("/mcp")).status_code == 404


async def test_main_style_mount_and_lifecycle_preserve_existing_routes(config):
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"ok": True}

    bridge.install_chatgpt_mcp(app, config[0])
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=config[0].public_url
        ) as http,
    ):
        assert (await http.get("/health")).json() == {"ok": True}
        assert (await rpc(http, bearer(config))).status_code == 200
