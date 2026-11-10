"""Meta-to-Sheets through the durable worker; external HTTP is simulated.

These tests verify tenant routing and data delivery, not Meta App Review or a
customer's real consent. No real ad account or spreadsheet is accessed.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app import meta_ads_oauth, orchestrator
from app.config import get_settings
from app.models import (
    Approval,
    ApprovalSnapshot,
    CapabilityManifest,
    PlanVersion,
    RunStatus,
    RunStep,
    StepStatus,
    TenantMembership,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)
from app.native_connectors import native_manifest, native_operations
from app.policy import canonical_plan_hash
from app.schemas import CriticDecision, ExecutionDirective, WorkflowPlan
from app.security import CredentialVault

META = "meta-ads-direct"
ACCOUNT = {
    "id": "act_987654321",
    "account_id": "987654321",
    "name": "External advertiser",
    "account_status": 1,
    "currency": "EUR",
    "timezone_name": "Europe/Berlin",
}
BOOK = "external_customer_workbook"
PERIOD = {"since": "2026-10-01", "until": "2026-10-31"}
ROWS = [
    {
        "account_id": "987654321",
        "campaign_id": "120000000000001",
        "campaign_name": "Prospecting",
        "date_start": "2026-10-01",
        "date_stop": "2026-10-31",
        "spend": "123.45",
        "impressions": "2000",
        "clicks": "42",
        "reach": "1500",
        "frequency": "1.333333",
    },
    {
        "account_id": "987654321",
        "campaign_id": "120000000000002",
        "campaign_name": "Retargeting",
        "date_start": "2026-10-01",
        "date_stop": "2026-10-31",
        "spend": "56.78",
        "impressions": "1200",
        "clicks": "15",
        "reach": "800",
        "frequency": "1.5",
    },
]
FIELDS = ["campaign_name", "date_start", "date_stop", "spend", "impressions", "clicks"]
EXPECTED = [[r[k] for k in FIELDS] + ["EUR"] for r in ROWS]


async def seed_external_run(runtime, settings):
    plan = WorkflowPlan.model_validate(
        {
            "name": "Meta campaign export",
            "interpretation": "Export the selected external account to its customer's sheet.",
            "steps": [
                {
                    "key": "meta",
                    "agent": "Reader",
                    "tool_slug": META,
                    "operation": "meta-ads.insights.get",
                    "arguments": {"account_id": ACCOUNT["id"], **PERIOD, "level": "campaign"},
                    "reason": "Read approved campaign results",
                    "expected_output": "Complete campaign rows",
                },
                {
                    "key": "write",
                    "agent": "Writer",
                    "tool_slug": "google",
                    "operation": "sheets.append",
                    "depends_on": ["meta"],
                    "arguments": {
                        "spreadsheet_id": BOOK,
                        "range": "'Meta Ads'!A2:G3",
                        "values": [
                            ["{{steps.meta.data[" + str(i) + "]." + k + "}}" for k in FIELDS]
                            + ["{{steps.meta.account.currency}}"]
                            for i in range(2)
                        ],
                    },
                    "reason": "Save source results in the customer's sheet",
                    "expected_output": "Saved campaign rows",
                    "consequential": True,
                },
            ],
        }
    ).model_dump(mode="json")
    digest = canonical_plan_hash(plan)
    scopes = {META: native_operations(META), "google": ["sheets.append", "sheets.read"]}
    async with runtime() as session:
        session.add(
            TenantMembership(
                workspace_id="w", subject="external-customer", role="owner", active=True
            )
        )
        session.add(Workspace(id="operator", name="Unrelated app owner"))
        for slug in (META, "google"):
            session.add(
                ToolConnection(
                    workspace_id="operator",
                    slug=slug,
                    display_name=slug,
                    kind=ToolKind.oauth,
                    allowed_operations=scopes[slug],
                    encrypted_credentials=CredentialVault().encrypt(
                        {"access_token": "operator-token-must-not-be-used"}
                    ),
                )
            )
        await session.commit()
        context = SimpleNamespace(workspace_id="w", subject="external-customer")
        started = await meta_ads_oauth.start(session, context, settings)
        state = parse_qs(urlsplit(started["authorization_url"]).query)["state"][0]
        connection, subject = await meta_ads_oauth.complete(
            session,
            settings,
            {"workspace_id": "w"},
            state,
            "test-consent-code",
            "https://api.example.com/v1/oauth/meta-ads-direct/callback",
        )
        assert subject == "external-customer" and connection.workspace_id == "w"
        run = await session.get(WorkflowRun, "run")
        run.prompt, run.plan = (
            "Read Meta Ads campaign metrics and save them to my Google Sheet",
            plan,
        )
        run.execution_context = {
            "__aura_preflight__": {
                "version": 2,
                "plan_hash": digest,
                "status": "passed",
                "completed_at": datetime.now(UTC).isoformat(),
            }
        }
        version = await session.get(PlanVersion, "version")
        version.plan, version.plan_hash = plan, digest
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        snapshot.plan_hash, snapshot.permission_snapshot = digest, scopes
        snapshot.approver_subject = "external-customer"
        old = await session.get(RunStep, "step")
        for index, spec in enumerate(plan["steps"]):
            step = (
                old
                if index == 0
                else RunStep(
                    id="write-step",
                    run_id="run",
                    position=index,
                    status=StepStatus.pending,
                    idempotency_key="external-sheet-write",
                )
            )
            for key in (
                "agent",
                "tool_slug",
                "operation",
                "arguments",
                "depends_on",
                "dependency_mode",
                "condition",
                "output_variables",
                "consequential",
            ):
                setattr(step, key, spec[key])
            step.step_key = spec["key"]
            step.approval_id = "approval" if index else None
            if index:
                session.add(step)
        approval = await session.get(Approval, "approval")
        approval.step_id = "write-step"
        approval.preview = {
            "status": "ready",
            "tool_slug": "google",
            "operation": "sheets.append",
            "arguments": {**plan["steps"][1]["arguments"], "values": EXPECTED},
        }
        google = await session.get(ToolConnection, "tool")
        google.slug, google.kind, google.allowed_operations = (
            "google",
            ToolKind.oauth,
            scopes["google"],
        )
        google.encrypted_credentials = CredentialVault().encrypt(
            {
                "access_token": "external-google-token",
                "scope": "https://www.googleapis.com/auth/spreadsheets",
            }
        )
        manifest = await session.get(CapabilityManifest, "manifest")
        manifest.provider_type, manifest.manifest = "oauth", native_manifest("google")
        await session.commit()


@pytest.mark.parametrize(
    "scenario", ["success", "meta_denied", "meta_empty", "sheets_denied", "wrong_saved_cells"]
)
async def test_external_meta_to_sheets_delivery_and_failure_boundaries(
    runtime, monkeypatch, scenario
):
    settings = get_settings()
    monkeypatch.setattr(settings, "meta_client_id", "test-app")
    monkeypatch.setattr(settings, "meta_client_secret", SecretStr("test-app-secret"))
    monkeypatch.setattr(settings, "public_url", "https://api.example.com")
    calls, written = [], []

    def respond(request):
        calls.append(request)
        path = unquote(request.url.path)
        if request.url.host == "graph.facebook.com":
            if path.endswith("/oauth/access_token"):
                form = parse_qs(request.content.decode())
                assert form["client_id"] == ["test-app"]
                return httpx.Response(
                    200, json={"access_token": "external-meta-token", "expires_in": 5184000}
                )
            assert request.headers["authorization"] == "Bearer external-meta-token"
            if path.endswith("/me"):
                return httpx.Response(200, json={"id": "87654321", "name": "External customer"})
            if path.endswith("/me/permissions"):
                return httpx.Response(
                    200, json={"data": [{"permission": "ads_read", "status": "granted"}]}
                )
            if path.endswith("/me/adaccounts"):
                return httpx.Response(200, json={"data": [ACCOUNT]})
            if path.endswith("/" + ACCOUNT["id"]):
                return httpx.Response(200, json=ACCOUNT)
            assert path.endswith("/" + ACCOUNT["id"] + "/insights")
            assert json.loads(request.url.params["time_range"]) == PERIOD
            assert request.url.params["level"] == "campaign"
            if scenario == "meta_denied":
                return httpx.Response(
                    403, json={"error": {"code": 200, "message": "Access denied"}}
                )
            if scenario == "meta_empty":
                return httpx.Response(200, json={"data": []})
            if request.url.params.get("after") == "page-two":
                return httpx.Response(200, json={"data": [ROWS[1]]})
            return httpx.Response(
                200,
                json={
                    "data": [ROWS[0]],
                    "paging": {
                        "next": "https://graph.facebook.com/unused",
                        "cursors": {"after": "page-two"},
                    },
                },
            )
        assert request.url.host == "sheets.googleapis.com"
        assert request.headers["authorization"] == "Bearer external-google-token"
        assert "/" + BOOK + "/values/" in path
        if request.method == "POST":
            assert path.endswith(":append")
            values = json.loads(request.content)["values"]
            assert values == EXPECTED
            if scenario == "sheets_denied":
                return httpx.Response(
                    403, json={"error": {"code": 403, "message": "Access denied"}}
                )
            written.extend(values)
            return httpx.Response(
                200,
                json={
                    "spreadsheetId": BOOK,
                    "updates": {
                        "updatedRange": "'Meta Ads'!A2:G3",
                        "updatedRows": 2,
                        "updatedColumns": 7,
                        "updatedCells": 14,
                    },
                },
            )
        assert request.method == "GET" and path.endswith("'Meta Ads'!A2:G3")
        saved = [list(row) for row in written]
        if scenario == "wrong_saved_cells":
            saved[0][3] = "0"
        return httpx.Response(
            200, json={"range": "'Meta Ads'!A2:G3", "majorDimension": "ROWS", "values": saved}
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    await seed_external_run(runtime, settings)

    async def directive(_prompt, step, arguments, _agent):
        return ExecutionDirective(
            action="execute",
            step_key=step["key"],
            tool_slug=step["tool_slug"],
            operation=step["operation"],
            arguments=arguments,
            reason="Execute the approved dataflow",
        ), "deterministic"

    monkeypatch.setattr(orchestrator, "prepare_execution_directive", directive)
    monkeypatch.setattr(
        orchestrator,
        "critique_step",
        AsyncMock(
            return_value=CriticDecision(action="accept", reasons=["Read contract satisfied"])
        ),
    )
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        steps = (
            await session.scalars(
                select(RunStep).where(RunStep.run_id == "run").order_by(RunStep.position)
            )
        ).all()
        if scenario in {"meta_denied", "meta_empty"}:
            assert run.status != RunStatus.completed
            assert not written
            assert not any(r.url.host == "sheets.googleapis.com" for r in calls)
        elif scenario == "sheets_denied":
            assert run.status != RunStatus.completed
            assert not written
            assert (
                sum(r.method == "POST" and r.url.host == "sheets.googleapis.com" for r in calls)
                == 1
            )
        elif scenario == "wrong_saved_cells":
            assert run.status != RunStatus.completed
            assert steps[1].output["outcome_check"]["status"] != "verified"
            assert (
                sum(r.method == "POST" and r.url.host == "sheets.googleapis.com" for r in calls)
                == 1
            )
        else:
            assert run.status == RunStatus.completed, (
                run.status,
                run.error,
                run.execution_context,
                [(s.status, s.error, s.output) for s in steps],
            )
            assert written == EXPECTED
            assert steps[0].output["provider_result"]["row_count"] == 2
            assert steps[1].output["outcome_check"]["status"] == "verified"
            assert (
                sum(r.method == "POST" and r.url.host == "sheets.googleapis.com" for r in calls)
                == 1
            )
            assert any(r.method == "GET" and r.url.host == "sheets.googleapis.com" for r in calls)
