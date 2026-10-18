from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from jsonschema import ValidationError
from sqlalchemy import select

from app import main
from app import wordpress_plugins as wp
from app.config import Settings
from app.models import CapabilityManifest, ToolConnection, ToolKind, Workspace
from app.pipedream_connect import PipedreamClient, PipedreamConnectError


@pytest.fixture
async def wordpress(database):
    async with database() as session:
        session.add_all([Workspace(id="w", name="Demo"), Workspace(id="other", name="Other")])
        parent = ToolConnection(
            id="wp",
            workspace_id="w",
            slug="wordpress-org",
            display_name="WordPress",
            kind=ToolKind.oauth,
            enabled=True,
            config={
                "managed_by": "pipedream",
                "vendor_app": "wordpress_org",
                "account_id": "apn_demo",
                "external_user_id": "aura_demo",
            },
        )
        session.add(parent)
        await session.flush()
        session.add(
            CapabilityManifest(
                workspace_id="w",
                tool_id="wp",
                provider_type="pipedream",
                status="verified",
                manifest={},
            )
        )
        await session.commit()
    return database


def bridge_status():
    return {
        "bridge_version": "1.0.0",
        "wordpress_version": "6.8.1",
        "plugins": {
            provider: {
                "version": "1.0.280" if provider == "rankmath" else "2.3.4",
                "api_key_configured": True,
                "api_key_valid": True,
                "operations": [x["name"] for x in wp.manifest(provider)["capabilities"]],
            }
            for provider in wp.PROVIDERS
        },
    }


@pytest.mark.parametrize("provider", ["rankmath", "imagify"])
async def test_connect_reuses_existing_account_and_runs_real_adapter_boundary(
    wordpress, monkeypatch, provider
):
    request = AsyncMock(return_value=bridge_status())
    monkeypatch.setattr(wp, "_wordpress_request", request)
    async with wordpress() as session:
        tool = await wp.connect(session, "w", provider)
        await session.commit()
        first_id = tool.id
        assert tool.kind == ToolKind.plugin
        assert tool.config["parent_connection_id"] == "wp"
        assert tool.encrypted_credentials is None
        assert tool.external_connection_id is None
        assert (await wp.connect(session, "w", provider)).id == first_id
        record = await session.scalar(
            select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
        )
        assert record.status == "verified"
        assert record.verification["wordpress_version"] == "6.8.1"
        assert "password" not in str(record.manifest)
        result = (
            {"wp": {"count_optimized": 1}}
            if provider == "imagify"
            else {"post_id": 107, "title": "Actual stored title"}
        )
        request.return_value = result
        operation = "imagify.stats.get" if provider == "imagify" else "rankmath.post_seo.get"
        arguments = {} if provider == "imagify" else {"post_id": 107}
        assert await wp.execute(session, tool, operation, arguments) == result
        assert request.call_args.args[1:] == ("POST", f"/{provider}/{operation}", arguments)


async def test_unavailable_bridge_never_creates_a_verified_connection(wordpress, monkeypatch):
    monkeypatch.setattr(wp, "_wordpress_request", AsyncMock(return_value={"plugins": {}}))
    async with wordpress() as session:
        with pytest.raises(wp.WordPressPluginError, match="not ready"):
            await wp.connect(session, "w", "rankmath")
        assert (
            await session.scalar(select(ToolConnection).where(ToolConnection.slug == "rankmath"))
            is None
        )


async def test_imagify_requires_verified_key_and_not_just_installed_plugin(wordpress, monkeypatch):
    status = bridge_status()
    status["plugins"]["imagify"]["api_key_valid"] = False
    monkeypatch.setattr(wp, "_wordpress_request", AsyncMock(return_value=status))
    async with wordpress() as session:
        with pytest.raises(wp.WordPressPluginError, match="API key"):
            await wp.connect(session, "w", "imagify")


async def test_parent_is_workspace_bound_and_revocation_blocks_execution(wordpress, monkeypatch):
    request = AsyncMock(return_value=bridge_status())
    monkeypatch.setattr(wp, "_wordpress_request", request)
    async with wordpress() as session:
        with pytest.raises(wp.WordPressPluginError):
            await wp.wordpress_parent(session, "other", "wp")
        tool = await wp.connect(session, "w", "rankmath")
        parent = await session.get(ToolConnection, "wp")
        parent.enabled = False
        request.reset_mock()
        with pytest.raises(wp.WordPressPluginError):
            await wp.execute(session, tool, "rankmath.post_seo.get", {"post_id": 107})
        request.assert_not_called()


async def test_no_arbitrary_operations_arguments_or_destinations(wordpress, monkeypatch):
    request = AsyncMock(return_value=bridge_status())
    monkeypatch.setattr(wp, "_wordpress_request", request)
    async with wordpress() as session:
        tool = await wp.connect(session, "w", "rankmath")
        request.reset_mock()
        with pytest.raises(wp.WordPressPluginError):
            await wp.execute(session, tool, "wordpress.users.delete", {"post_id": 107})
        with pytest.raises(ValidationError):
            await wp.execute(
                session,
                tool,
                "rankmath.post_seo.get",
                {"post_id": 107, "url": "https://other.example"},
            )
        request.assert_not_called()
        capability = next(
            x for x in wp.manifest("rankmath")["capabilities"] if x["name"].endswith(".update")
        )
        assert capability["requires_approval"] is True
        assert capability["permission_scope"] == "write"


async def test_broker_connection_and_test_use_existing_account_without_sign_in(
    wordpress, monkeypatch
):
    monkeypatch.setattr(wp, "_wordpress_request", AsyncMock(return_value=bridge_status()))
    monkeypatch.setattr(
        main, "_satisfy_matching_connection_requirements", AsyncMock(return_value=[])
    )
    async with wordpress() as session:
        result = await main.create_connector_broker_session(
            "RankMath", None, main.TenantContext("w", "owner", "owner"), session
        )
        assert result["already_connected"] is True
        assert "token" not in result
        verified = await main.test_connection(
            result["connection_id"], main.TenantContext("w", "owner", "owner"), session
        )
        assert verified["status"] == "verified"
        assert verified["verification"]["ok"] is True


@pytest.mark.parametrize("code", [302, 401, 404, 500])
async def test_request_never_follows_redirects_or_exposes_credentials(monkeypatch, code):
    broker = SimpleNamespace(
        wordpress_account_credentials=AsyncMock(
            return_value={
                "url": "https://demo.example/site/test",
                "username": "demo",
                "application_password": "private-test-secret",
            }
        )
    )
    monkeypatch.setattr(wp, "pipedream_client", lambda: broker)
    monkeypatch.setattr(wp, "validate_public_endpoint", lambda url: None)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            code, headers={"Location": "https://untrusted.example"}, text="private-test-secret"
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        wp.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    parent = SimpleNamespace(
        config={"external_user_id": "aura_demo", "account_id": "apn_demo"},
        external_connection_id=None,
    )
    with pytest.raises(wp.WordPressPluginError) as failure:
        await wp._wordpress_request(parent, "GET", "/status")
    assert "private-test-secret" not in str(failure.value)
    assert len(calls) == 1
    assert str(calls[0].url) == "https://demo.example/site/test/wp-json/aura-seo/v1/status"


@pytest.mark.parametrize(
    "url",
    [
        "http://demo.example",
        "https://demo.example/?key=x",
        "https://u:p@demo.example",
        "https://demo.example:8443",
        "https://demo.example/a/../b",
    ],
)
async def test_bad_credential_destinations_rejected_before_network(monkeypatch, url):
    broker = SimpleNamespace(
        wordpress_account_credentials=AsyncMock(
            return_value={
                "url": url,
                "username": "demo",
                "application_password": "private-test-secret",
            }
        )
    )
    monkeypatch.setattr(wp, "pipedream_client", lambda: broker)
    parent = SimpleNamespace(
        config={"external_user_id": "aura_demo", "account_id": "apn_demo"},
        external_connection_id=None,
    )
    with pytest.raises(wp.WordPressPluginError, match="HTTPS"):
        await wp._wordpress_request(parent, "GET", "/status")


async def test_credential_retrieval_requires_ownership_before_project_account_read(monkeypatch):
    client = PipedreamClient(Settings(pipedream_project_id="proj_demo"))
    request = AsyncMock()
    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr(client, "verify_account", AsyncMock(return_value={"ok": False}))
    with pytest.raises(PipedreamConnectError, match="not authorized"):
        await client.wordpress_account_credentials("aura_other", "apn_demo")
    request.assert_not_called()
    monkeypatch.setattr(client, "verify_account", AsyncMock(return_value={"ok": True}))
    request.return_value = {
        "id": "apn_demo",
        "app": {"name_slug": "wordpress_org"},
        "credentials": {
            "url": "https://demo.example",
            "username": "demo",
            "application_password": "private-test-secret",
            "other_secret": "never-return",
        },
    }
    credentials = await client.wordpress_account_credentials("aura_demo", "apn_demo")
    assert set(credentials) == {"url", "username", "application_password"}
    assert request.call_args.kwargs["params"] == {"include_credentials": "true"}


async def test_plugin_runs_through_governed_preflight_and_orchestrator(wordpress, monkeypatch):
    from app import execution_preflight, orchestrator
    from app.models import (
        ApprovalSnapshot,
        PlanVersion,
        RunStatus,
        RunStep,
        StepStatus,
        WorkflowRun,
    )
    from app.policy import DEFAULT_POLICY, canonical_plan_hash
    from app.schemas import (
        CriticDecision,
        OutcomeVerification,
        PlanStep,
        UnifiedDeliverable,
        WorkflowPlan,
    )

    async def boundary(parent, method, path, body=None):
        if method == "GET":
            return bridge_status()
        assert path == "/rankmath/rankmath.post_seo.get"
        assert body == {"post_id": 107}
        return {"post_id": 107, "title": "Actual title"}

    request = AsyncMock(side_effect=boundary)
    monkeypatch.setattr(wp, "_wordpress_request", request)
    operation = "rankmath.post_seo.get"
    plan = WorkflowPlan(
        name="Read RankMath",
        interpretation="Read the draft's SEO metadata",
        steps=[
            PlanStep(
                key="read",
                agent="seo",
                tool_slug="rankmath",
                operation=operation,
                arguments={"post_id": 107},
                reason="Verify the draft",
                expected_output="Saved metadata",
            )
        ],
    ).model_dump(mode="json")
    digest = canonical_plan_hash(plan)
    async with wordpress() as session:
        tool = await wp.connect(session, "w", "rankmath")
        record = await session.scalar(
            select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
        )
        credentials, verification, blocker = await execution_preflight._connection_credentials(
            session, tool, record
        )
        assert credentials == {} and verification["ok"] and blocker is None
        session.add(
            WorkflowRun(
                id="plugin-run",
                workspace_id="w",
                prompt="Read RankMath metadata for post 107",
                plan=plan,
                plan_approved=True,
                status=RunStatus.running,
                execution_context={
                    "__aura_preflight__": {
                        "version": 2,
                        "plan_hash": digest,
                        "status": "passed",
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                },
            )
        )
        session.add(
            PlanVersion(
                id="plugin-plan",
                workspace_id="w",
                run_id="plugin-run",
                version=1,
                status="approved",
                plan=plan,
                plan_hash=digest,
            )
        )
        session.add(
            ApprovalSnapshot(
                id="plugin-snapshot",
                workspace_id="w",
                run_id="plugin-run",
                plan_version_id="plugin-plan",
                plan_hash=digest,
                approver_subject="owner",
                approver_role="owner",
                policy_snapshot=DEFAULT_POLICY,
                permission_snapshot={"rankmath": tool.allowed_operations},
                risk_snapshot={},
                cost_snapshot={"estimated_cost_usd": 0},
            )
        )
        session.add(
            RunStep(
                id="plugin-step",
                run_id="plugin-run",
                position=0,
                step_key="read",
                agent="seo",
                tool_slug="rankmath",
                operation=operation,
                arguments={"post_id": 107},
                status=StepStatus.pending,
                consequential=False,
                idempotency_key="read-plugin-once",
            )
        )
        await session.commit()
    monkeypatch.setattr(orchestrator, "SessionLocal", wordpress)
    monkeypatch.setattr(
        orchestrator, "critique_step", AsyncMock(return_value=CriticDecision(action="accept"))
    )
    monkeypatch.setattr(
        orchestrator,
        "verify_outcome",
        AsyncMock(
            return_value=OutcomeVerification(status="verified", evidence_step_ids=["plugin-step"])
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "synthesize_result",
        AsyncMock(
            return_value=UnifiedDeliverable(
                summary="Read saved metadata", deliverable="Actual title"
            )
        ),
    )
    await orchestrator._execute_run("plugin-run", "w")
    async with wordpress() as session:
        run = await session.get(WorkflowRun, "plugin-run")
        step = await session.get(RunStep, "plugin-step")
        assert run.status == RunStatus.completed, run.error
        assert step.status == StepStatus.completed
    assert sum(call.args[1] == "POST" for call in request.await_args_list) == 1
