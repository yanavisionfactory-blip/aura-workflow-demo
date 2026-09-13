from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import execution_preflight, main, orchestrator, pipedream_connect
from app.config import Settings
from app.db import Base
from app.models import (
    ApprovalSnapshot,
    BrokerCapabilityPack,
    ConnectionRequirement,
    PlanVersion,
    RunStatus,
    RunStep,
    StepStatus,
    ToolConnection,
    WorkflowRun,
    Workspace,
)
from app.pipedream_connect import certify_app, pack_signature_valid, released_pack
from app.policy import DEFAULT_POLICY, canonical_plan_hash
from app.schemas import (
    CriticDecision,
    OutcomeVerification,
    PlanStep,
    UnifiedDeliverable,
    WorkflowPlan,
)
from app.security import CredentialVault


def broker_settings() -> Settings:
    return Settings(
        credential_encryption_key=(
            "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
        ),
        session_signing_key="test-session-signing-key-000000000",
        connector_engineer_signing_key="connector-pack-signing-key-000000000000000",
        pipedream_client_id="server-client-id",
        pipedream_client_secret="server-client-secret",
        pipedream_project_id="proj_abc123",
        pipedream_environment="development",
        frontend_url="https://aura.example/app",
    )


def action_definition(provider: str, auth_type: str) -> dict:
    return {
        "name_slug": provider,
        "name": provider.replace("-", " ").title(),
        "auth_type": auth_type,
        "has_actions": True,
        "categories": ["Test"],
    }


def actions(provider: str) -> list[dict]:
    return [
        {
            "key": f"{provider}-list-items",
            "version": "1.0.0",
            "name": "List items",
            "description": "List items",
            "annotations": {"readOnlyHint": True},
            "configurable_props": [
                {"name": provider.replace("-", "_"), "type": "app", "app": provider},
                {"name": "limit", "type": "integer", "optional": True},
            ],
        }
    ]


class PipedreamBoundary:
    """Deterministic substitute for Pipedream; AURA's HTTP and DB layers stay real."""

    configured = True

    def __init__(
        self,
        app_definition: dict,
        *,
        action_definitions: list[dict] | None = None,
        mcp_tools: list[dict] | None = None,
    ) -> None:
        self.app_definition = app_definition
        self.action_definitions = action_definitions or []
        self.mcp_tools = mcp_tools or []
        self.execution = AsyncMock(return_value={"content": [{"type": "text", "text": "ok"}]})

    async def list_apps(self, query: str, limit: int = 30) -> list[dict]:
        return [self.app_definition] if query.casefold() in self.app_definition["name"].casefold() else []

    async def get_app(self, provider: str) -> dict:
        assert provider == self.app_definition["name_slug"]
        return self.app_definition

    async def list_actions(self, provider: str) -> list[dict]:
        assert provider == self.app_definition["name_slug"]
        return self.action_definitions

    async def list_mcp_tools(self, provider: str) -> list[dict]:
        assert provider == self.app_definition["name_slug"]
        return self.mcp_tools

    async def create_connect_token(self, external_user_id: str) -> dict:
        assert external_user_id.startswith("aura_")
        return {"token": "short-lived-browser-token", "expires_at": "2099-01-01T00:00:00Z"}

    async def verify_account(
        self, external_user_id: str, provider: str, account_id: str
    ) -> dict:
        assert external_user_id.startswith("aura_")
        assert provider == self.app_definition["name_slug"]
        assert account_id.startswith("apn_")
        return {
            "ok": True,
            "identity": {"id": f"identity-{provider}", "display_name": "Pilot account"},
            "authorized_scopes": ["read"],
            "account_id": account_id,
        }

    async def run_action(self, *args, **kwargs) -> dict:
        return await self.execution(*args, **kwargs)


class MultiPipedreamBoundary:
    """Two-provider boundary for a complete connection barrier and workflow run."""

    configured = True

    def __init__(self, apps: list[dict], action_definitions: dict[str, list[dict]]) -> None:
        self.apps = {app["name_slug"]: app for app in apps}
        self.action_definitions = action_definitions
        self.execution = AsyncMock(side_effect=self._result)

    async def list_apps(self, query: str, limit: int = 30) -> list[dict]:
        return [
            app for app in self.apps.values() if query.casefold() in app["name"].casefold()
        ][:limit]

    async def get_app(self, provider: str) -> dict:
        return self.apps[provider]

    async def list_actions(self, provider: str) -> list[dict]:
        return self.action_definitions[provider]

    async def list_mcp_tools(self, provider: str) -> list[dict]:
        return []

    async def create_connect_token(self, external_user_id: str) -> dict:
        assert external_user_id.startswith("aura_")
        return {"token": "short-lived-browser-token", "expires_at": "2099-01-01T00:00:00Z"}

    async def verify_account(
        self, external_user_id: str, provider: str, account_id: str
    ) -> dict:
        assert external_user_id.startswith("aura_")
        assert provider in self.apps
        return {
            "ok": True,
            "identity": {"id": f"identity-{provider}", "display_name": "Pilot account"},
            "authorized_scopes": ["read", "write"],
            "account_id": account_id,
        }

    async def run_action(self, *args, **kwargs) -> dict:
        return await self.execution(*args, **kwargs)

    @staticmethod
    def _result(_user: str, _account: str, capability: dict, arguments: dict) -> dict:
        if capability["permission_scope"] == "read":
            return {"exports": {"issues": [{"id": "LIN-1", "title": "Pilot issue"}]}}
        return {
            "exports": {
                "message": {
                    "id": "slack-message-1",
                    "channel": arguments["channel"],
                    "text": arguments["text"],
                }
            }
        }


@pytest.fixture
async def broker_api(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    context = main.TenantContext("workspace-1", "pilot-user", "owner")
    config = broker_settings()

    async with factory() as session:
        session.add(Workspace(id=context.workspace_id, name="Connector E2E"))
        await session.commit()

    async def context_override() -> main.TenantContext:
        return context

    async def session_override():
        async with factory() as session:
            yield session

    main.app.dependency_overrides[main.tenant_context] = context_override
    main.app.dependency_overrides[main.tenant_session] = session_override
    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr(
        main, "managed_connector_client", lambda: SimpleNamespace(configured=False)
    )
    dispatch = AsyncMock(return_value=1)
    monkeypatch.setattr(main, "dispatch_pending", dispatch)

    async def released(session, provider):
        return await released_pack(session, provider, config)

    monkeypatch.setattr(main, "released_pipedream_pack", released)
    monkeypatch.setattr(
        main,
        "pipedream_pack_signature_valid",
        lambda pack: pack_signature_valid(pack, config),
    )

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://aura.test") as client:
        yield SimpleNamespace(
            client=client,
            factory=factory,
            context=context,
            settings=config,
            dispatch=dispatch,
        )

    main.app.dependency_overrides.clear()
    await engine.dispose()


def use_pipedream(monkeypatch, boundary: PipedreamBoundary) -> None:
    monkeypatch.setattr(main, "pipedream_client", lambda: boundary)


async def connect_account(api, provider: str, account_id: str) -> tuple[dict, dict]:
    boundary = main.pipedream_client()
    async with api.factory() as database:
        if await released_pack(database, provider, api.settings) is None:
            await certify_app(
                database,
                boundary,
                await boundary.get_app(provider),
                api.settings,
            )
            await database.commit()
    session_response = await api.client.post(f"/v1/connector-broker/{provider}/session")
    assert session_response.status_code == 201, session_response.text
    completion_response = await api.client.post(
        f"/v1/connector-broker/{provider}/complete",
        json={"account_id": account_id},
    )
    assert completion_response.status_code == 200, completion_response.text
    return session_response.json(), completion_response.json()


async def test_oauth_connection_e2e_uses_only_short_lived_and_opaque_references(
    broker_api, monkeypatch
):
    provider = "linear-e2e"
    boundary = PipedreamBoundary(
        action_definition(provider, "oauth"),
        action_definitions=actions(provider),
    )
    use_pipedream(monkeypatch, boundary)

    async with broker_api.factory() as session:
        await certify_app(session, boundary, boundary.app_definition, broker_api.settings)
        await session.commit()

    search = await broker_api.client.get("/v1/connector-broker/apps", params={"q": "linear"})
    assert search.status_code == 200
    assert search.json()["apps"][0]["connection_strategy"] == "oauth"

    connection, completed = await connect_account(broker_api, provider, "apn_oauth123")

    assert connection["token"] == "short-lived-browser-token"
    assert connection["setup_hint"] == "Provider consent"
    assert completed["connected"] is True
    assert "secret" not in str(connection).casefold()
    async with broker_api.factory() as session:
        tool = await session.scalar(select(ToolConnection))
        assert tool.external_connection_id == "apn_oauth123"
        assert CredentialVault().decrypt(tool.encrypted_credentials) == {}


async def test_connect_click_never_discovers_uncached_action_schemas(broker_api, monkeypatch):
    provider = "uncached-e2e"
    boundary = PipedreamBoundary(
        action_definition(provider, "oauth"),
        action_definitions=actions(provider),
    )
    boundary.list_actions = AsyncMock(return_value=actions(provider))
    boundary.list_mcp_tools = AsyncMock(return_value=[])
    use_pipedream(monkeypatch, boundary)

    response = await broker_api.client.post(f"/v1/connector-broker/{provider}/session")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "connector_certification_in_progress"
    boundary.list_actions.assert_not_awaited()
    boundary.list_mcp_tools.assert_not_awaited()


async def test_api_key_connection_e2e_keeps_the_key_inside_managed_auth(
    broker_api, monkeypatch
):
    provider = "api-key-e2e"
    boundary = PipedreamBoundary(
        action_definition(provider, "keys"),
        action_definitions=actions(provider),
    )
    use_pipedream(monkeypatch, boundary)

    connection, completed = await connect_account(broker_api, provider, "apn_key123")

    assert connection["connection_strategy"] == "secure_credentials"
    assert connection["setup_hint"] == "Secure credentials required"
    assert completed["connection_id"]
    async with broker_api.factory() as session:
        tool = await session.scalar(select(ToolConnection))
        assert tool.config["managed_by"] == "pipedream"
        assert tool.external_connection_id == "apn_key123"
        assert CredentialVault().decrypt(tool.encrypted_credentials) == {}


async def test_mcp_connection_and_tool_execution_e2e(broker_api, monkeypatch):
    provider = "lovable-mcp-e2e"
    app_definition = {
        **action_definition(provider, "oauth"),
        "name": "Lovable (MCP) E2E",
        "has_actions": False,
    }
    boundary = PipedreamBoundary(
        app_definition,
        mcp_tools=[
            {
                "name": "list_projects",
                "description": "List projects",
                "annotations": {"readOnlyHint": True},
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"limit": {"type": "integer"}},
                },
            }
        ],
    )
    use_pipedream(monkeypatch, boundary)

    connection, completed = await connect_account(broker_api, provider, "apn_mcp123")
    assert connection["connection_strategy"] == "mcp"

    async with broker_api.factory() as session:
        tool = await session.get(ToolConnection, completed["connection_id"])
        pack = await session.get(BrokerCapabilityPack, tool.config["capability_pack_id"])
        operation = pack.definition["capabilities"][0]["name"]
        plan = WorkflowPlan(
            name="MCP read",
            interpretation="List connected projects",
            steps=[
                PlanStep(
                    key="read",
                    agent="data",
                    tool_slug=provider,
                    operation=operation,
                    arguments={"limit": 5},
                    reason="Read projects",
                    expected_output="Projects",
                )
            ],
        ).model_dump(mode="json")
        digest = canonical_plan_hash(plan)
        session.add(
            WorkflowRun(
                id="mcp-run",
                workspace_id=broker_api.context.workspace_id,
                prompt="List projects",
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
                id="mcp-version",
                workspace_id=broker_api.context.workspace_id,
                run_id="mcp-run",
                version=1,
                status="approved",
                plan=plan,
                plan_hash=digest,
            )
        )
        session.add(
            ApprovalSnapshot(
                id="mcp-snapshot",
                workspace_id=broker_api.context.workspace_id,
                run_id="mcp-run",
                plan_version_id="mcp-version",
                plan_hash=digest,
                approver_subject="pilot-user",
                approver_role="owner",
                policy_snapshot=DEFAULT_POLICY,
                permission_snapshot={provider: [operation]},
                risk_snapshot={},
                cost_snapshot={"estimated_cost_usd": 0},
            )
        )
        session.add(
            RunStep(
                id="mcp-step",
                run_id="mcp-run",
                position=0,
                step_key="read",
                agent="data",
                tool_slug=provider,
                operation=operation,
                arguments={"limit": 5},
                status=StepStatus.pending,
                consequential=False,
                idempotency_key="mcp-read-once",
            )
        )
        await session.commit()

    monkeypatch.setattr(orchestrator, "SessionLocal", broker_api.factory)
    monkeypatch.setattr(pipedream_connect, "pipedream_client", lambda: boundary)
    monkeypatch.setattr(pipedream_connect, "get_settings", lambda: broker_api.settings)
    monkeypatch.setattr(
        orchestrator,
        "critique_step",
        AsyncMock(return_value=CriticDecision(action="accept")),
    )
    monkeypatch.setattr(
        orchestrator,
        "verify_outcome",
        AsyncMock(return_value=OutcomeVerification(status="verified", evidence_step_ids=["mcp-step"])),
    )
    monkeypatch.setattr(
        orchestrator,
        "synthesize_result",
        AsyncMock(return_value=UnifiedDeliverable(summary="Found projects", deliverable="Projects")),
    )

    await orchestrator._execute_run("mcp-run", broker_api.context.workspace_id)

    boundary.execution.assert_awaited_once()
    execution_args = boundary.execution.await_args.args
    assert execution_args[1] == "apn_mcp123"
    assert "secret" not in str(execution_args).casefold()
    async with broker_api.factory() as session:
        run = await session.get(WorkflowRun, "mcp-run")
        assert run.status == RunStatus.completed


async def test_paused_workflow_connect_and_automatic_continuation_e2e(
    broker_api, monkeypatch
):
    provider = "resume-e2e"
    boundary = PipedreamBoundary(
        action_definition(provider, "oauth"),
        action_definitions=actions(provider),
    )
    use_pipedream(monkeypatch, boundary)
    operation = f"{provider}.list-items"

    async with broker_api.factory() as session:
        session.add(
            WorkflowRun(
                id="paused-run",
                workspace_id=broker_api.context.workspace_id,
                prompt="List connected items",
                status=RunStatus.waiting_for_action,
            )
        )
        session.add(
            ConnectionRequirement(
                id="paused-requirement",
                workspace_id=broker_api.context.workspace_id,
                run_id="paused-run",
                capability=operation,
                provider_hint=provider,
                reason="Connection required",
            )
        )
        await session.commit()

    _, completed = await connect_account(broker_api, provider, "apn_resume123")

    assert completed["resumed_run_ids"] == ["paused-run"]
    broker_api.dispatch.assert_awaited_once_with(broker_api.context.workspace_id)
    async with broker_api.factory() as session:
        run = await session.get(WorkflowRun, "paused-run")
        requirement = await session.get(ConnectionRequirement, "paused-requirement")
        assert run.status == RunStatus.queued
        assert requirement.status == "satisfied"
        assert requirement.satisfied_by_tool_id == completed["connection_id"]


async def test_linear_and_slack_barrier_plans_and_executes_complete_workflow(
    broker_api, monkeypatch
):
    linear = "linear"
    slack = "slack"
    linear_action = actions(linear)
    slack_action = [
        {
            "key": f"{slack}-send-message",
            "version": "1.0.0",
            "name": "Send message",
            "description": "Send a Slack message",
            "configurable_props": [
                {"name": slack.replace("-", "_"), "type": "app", "app": slack},
                {"name": "channel", "type": "string"},
                {"name": "text", "type": "string"},
            ],
        }
    ]
    boundary = MultiPipedreamBoundary(
        [action_definition(linear, "oauth"), action_definition(slack, "oauth")],
        {linear: linear_action, slack: slack_action},
    )
    use_pipedream(monkeypatch, boundary)
    monkeypatch.setattr(pipedream_connect, "pipedream_client", lambda: boundary)
    monkeypatch.setattr(pipedream_connect, "get_settings", lambda: broker_api.settings)
    monkeypatch.setattr(execution_preflight, "pipedream_client", lambda: boundary)

    async with broker_api.factory() as session:
        session.add(
            WorkflowRun(
                id="linear-slack-run",
                workspace_id=broker_api.context.workspace_id,
                prompt="Read my open Linear issues, summarize them, and post the summary to Slack.",
                status=RunStatus.waiting_for_action,
            )
        )
        for provider in (linear, slack):
            session.add(
                ConnectionRequirement(
                    id=f"require-{provider}",
                    workspace_id=broker_api.context.workspace_id,
                    run_id="linear-slack-run",
                    capability=provider,
                    provider_hint=provider,
                    reason=f"Connect {provider}",
                )
            )
        await session.commit()

    _, first = await connect_account(broker_api, linear, "apn_linear123")
    assert first["resumed_run_ids"] == []
    async with broker_api.factory() as session:
        assert (await session.get(WorkflowRun, "linear-slack-run")).status == (
            RunStatus.waiting_for_action
        )

    _, second = await connect_account(broker_api, slack, "apn_slack123")
    assert second["resumed_run_ids"] == ["linear-slack-run"]

    async with broker_api.factory() as session:
        linear_pack = await released_pack(session, linear, broker_api.settings)
        slack_pack = await released_pack(session, slack, broker_api.settings)
        linear_operation = linear_pack.definition["capabilities"][0]["name"]
        slack_operation = slack_pack.definition["capabilities"][0]["name"]
    plan = WorkflowPlan(
        name="Linear summary to Slack",
        interpretation="Read every open issue and post one grounded summary",
        steps=[
            PlanStep(
                key="read_linear",
                agent="Linear specialist",
                tool_slug=linear,
                operation=linear_operation,
                arguments={"limit": 20},
                reason="Read open Linear issues",
                expected_output="Open issues",
            ),
            PlanStep(
                key="post_slack",
                agent="Slack specialist",
                tool_slug=slack,
                operation=slack_operation,
                arguments={
                    "channel": "pilot-updates",
                    "text": "Open issue: {{steps.read_linear.exports.issues.0.title}}",
                },
                reason="Post the grounded summary to Slack",
                expected_output="Slack message receipt",
                consequential=True,
                depends_on=["read_linear"],
            ),
        ],
    )
    monkeypatch.setattr(orchestrator, "SessionLocal", broker_api.factory)
    monkeypatch.setattr(
        orchestrator, "_create_compiled_plan", AsyncMock(return_value=plan)
    )
    await orchestrator._plan_run("linear-slack-run", broker_api.context.workspace_id)

    async with broker_api.factory() as session:
        run = await session.get(WorkflowRun, "linear-slack-run")
        assert run.status == RunStatus.awaiting_approval
        assert [item["tool_slug"] for item in run.plan["steps"]] == [linear, slack]
        await main.approve_plan(
            run.id,
            main.PlanApproval(approved=True, approve_consequential=True),
            broker_api.context,
            session,
        )
        step_ids = list(
            await session.scalars(
                select(RunStep.id)
                .where(RunStep.run_id == run.id)
                .order_by(RunStep.position)
            )
        )

    async def outcome(_session, _run, step, _snapshot):
        if step.consequential:
            return {"status": "verified", "observed": step.output["provider_result"]}
        return {"status": "unsupported"}

    monkeypatch.setattr(orchestrator, "check_provider_outcome", outcome)
    monkeypatch.setattr(
        orchestrator,
        "critique_step",
        AsyncMock(return_value=CriticDecision(action="accept")),
    )
    monkeypatch.setattr(
        orchestrator,
        "verify_outcome",
        AsyncMock(
            return_value=OutcomeVerification(
                status="verified", evidence_step_ids=step_ids
            )
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "synthesize_result",
        AsyncMock(
            return_value=UnifiedDeliverable(
                summary="Posted one issue", deliverable="Open issue: Pilot issue"
            )
        ),
    )
    await orchestrator._execute_run("linear-slack-run", broker_api.context.workspace_id)

    assert boundary.execution.await_count == 2
    async with broker_api.factory() as session:
        run = await session.get(WorkflowRun, "linear-slack-run")
        steps = (
            await session.scalars(
                select(RunStep)
                .where(RunStep.run_id == run.id)
                .order_by(RunStep.position)
            )
        ).all()
        assert run.status == RunStatus.completed
        assert [step.status for step in steps] == [StepStatus.completed, StepStatus.completed]
        assert steps[1].output["resolved_arguments"]["text"] == "Open issue: Pilot issue"


def test_public_api_has_no_direct_provider_secret_submission_routes():
    paths = main.app.openapi()["paths"]
    assert "post" not in paths.get("/v1/tools", {})
    assert "/v1/connectors/discover" not in paths
    assert "/v1/oauth/custom/start" not in paths
    assert "post" not in paths.get("/v1/connector-installations", {})
