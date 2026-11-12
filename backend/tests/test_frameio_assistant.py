from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app import frameio_assistant as native
from app.frameio_assistant_contract import validate_native_assistant_plan
from app.models import FrameioAssistantSession, ToolConnection, ToolKind, Workspace
from app.native_connectors import native_manifest
from app.operation_contracts import output_errors
from app.providers import ProviderExecutor

ACCOUNT, FILE, PROJECT = (str(uuid4()) for _ in range(3))
ARGS = {"account_id": ACCOUNT, "file_id": FILE, "instructions": "Review errors and audio with timestamps"}
RECEIPT = {"status": "completed", "message_id": "msg-native", "response": "00:22: Graphic label is inconsistent. Correct the font. " * 3 + "Audio could not be accessed and remains unassessed.", "source_url": f"https://app.frame.io/project/{PROJECT}/view/{FILE}"}


def test_native_receipt_preserves_provider_and_audio_limitations():
    result = native.report_from_receipt(RECEIPT, ARGS, str(uuid4()), "a" * 64)
    assert result["analysis_provider"] == "frameio_ai_assistant"
    assert result["body"] == RECEIPT["response"]
    assert "unassessed" in result["body"]
    assert "coverage" not in result and "models" not in result
    assert output_errors(native.OPERATION, result) == []
    for invalid in [{**RECEIPT, "status": "submitted"}, {**RECEIPT, "message_id": ""}]:
        with pytest.raises(ValueError):
            native.report_from_receipt(invalid, ARGS, str(uuid4()), "a" * 64)


def test_native_request_cannot_use_aura_analysis_or_backup():
    prompt = "Use Frame.io's own AI Assistant to review this video"
    for operation in ["frameio.video.review", "intelligence.video.review", "report.compose"]:
        with pytest.raises(ValueError, match="own AI Assistant"):
            validate_native_assistant_plan(prompt, SimpleNamespace(steps=[SimpleNamespace(operation=operation)]))
    validate_native_assistant_plan(prompt, SimpleNamespace(steps=[SimpleNamespace(operation=native.OPERATION, fallback_operation=None)]))
    with pytest.raises(ValueError, match="fall back"):
        validate_native_assistant_plan(prompt, SimpleNamespace(steps=[SimpleNamespace(operation=native.OPERATION, fallback_operation="intelligence.video.review")]))


async def seed(factory):
    async with factory() as session:
        session.add_all([Workspace(id="w", name="Workspace"), Workspace(id="other", name="Other")])
        session.add(ToolConnection(id="tool", workspace_id="w", slug="frameio", display_name="Frame.io", kind=ToolKind.oauth, enabled=True, encrypted_credentials="encrypted"))
        session.add(FrameioAssistantSession(id="profile", workspace_id="w", tool_id="tool", owner="owner", account_id=ACCOUNT, file_id=FILE, project_id=PROJECT, worker_id=str(uuid4()), ready=True))
        await session.commit()


async def test_uncertain_submission_recovers_without_duplicate_dispatch(database, monkeypatch):
    await seed(database)
    monkeypatch.setattr(native, "SessionLocal", database)
    posts = []
    completed = False
    async def fake_worker(method, path, **kwargs):
        if method == "POST":
            posts.append(kwargs["payload"])
            raise HTTPException(503, "Lost acknowledgement after submission")
        if "/sessions/" in path:
            return {"ready": True, "busy": False}
        assert completed
        return RECEIPT
    async def file_get(*args):
        return {"file": {"project_id": PROJECT}}
    monkeypatch.setattr(native, "worker", fake_worker)
    monkeypatch.setattr(native.frameio, "execute", file_get)
    context = {"workspace_id": "w", "tool_id": "tool", "invocation_id": str(uuid4())}
    with pytest.raises(HTTPException):
        await native.execute({}, ARGS, context)
    completed = True
    result = await native.execute({}, ARGS, context)
    assert result["body"] == RECEIPT["response"]
    assert len(posts) == 1
    assert await native.execute({}, ARGS, context) == result
    assert len(posts) == 1
    with pytest.raises(ValueError, match="original authorized"):
        await native.execute({}, {**ARGS, "instructions": "Different review"}, context)
    with pytest.raises(ValueError, match="original authorized"):
        await native.execute({}, ARGS, {**context, "workspace_id": "other"})


async def test_missing_session_never_substitutes_engine(database, monkeypatch):
    await seed(database)
    monkeypatch.setattr(native, "SessionLocal", database)
    async def file_get(*args):
        return {"file": {"project_id": PROJECT}}
    monkeypatch.setattr(native.frameio, "execute", file_get)
    with pytest.raises(ValueError, match="Connect the Frame.io AI Assistant"):
        await native.execute({}, {**ARGS, "file_id": str(uuid4())}, {"workspace_id": "w", "tool_id": "tool", "invocation_id": str(uuid4())})


async def test_provider_requires_workflow_context_and_verified_connection(monkeypatch):
    with pytest.raises(ValueError):
        await ProviderExecutor({}, capability_manifest=native_manifest("frameio")).execute(native.OPERATION, ARGS)
    calls = []
    async def fake_execute(credentials, arguments, context):
        calls.append(context)
        return {"body": "actual native response"}
    monkeypatch.setattr(native, "execute", fake_execute)
    context = {"workspace_id": "w", "tool_id": "tool", "invocation_id": str(uuid4())}
    result = await ProviderExecutor({}, capability_manifest=native_manifest("frameio"), execution_context=context).execute(native.OPERATION, ARGS)
    assert result["body"] == "actual native response" and calls == [context]


async def test_signin_screen_is_owner_and_tenant_isolated(database):
    await seed(database)
    app = FastAPI()
    context = SimpleNamespace(workspace_id="other", subject="intruder", role="owner")
    async def tenant_context():
        return context
    async def session_dependency():
        async with database() as session:
            yield session
    native.install_routes(app, tenant_context, session_dependency)
    # UUID route cannot use arbitrary strings; add a valid owned profile ID.
    identifier = str(uuid4())
    async with database() as session:
        profile = await session.get(FrameioAssistantSession, "profile")
        profile.id = identifier
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app), base_url="https://aura.test") as client:
        for method, suffix, body in [("GET", "", None), ("POST", "/input", {"action": "text", "text": "secret"}), ("DELETE", "", None)]:
            result = await client.request(method, native.PREFIX + "/sessions/" + identifier + suffix, json=body)
            assert result.status_code == 404
        context.workspace_id = "w"
        result = await client.get(native.PREFIX + "/sessions/" + identifier)
        assert result.status_code == 404


async def test_readiness_requires_native_session_for_exact_video(database, monkeypatch):
    from unittest.mock import AsyncMock

    from app import run_readiness
    from app.models import CapabilityManifest, WorkflowRun
    from app.native_connectors import native_operations
    from app.schemas import PlanStep, WorkflowPlan

    await seed(database)
    plan = WorkflowPlan(name="Native review", interpretation="Review selected video", steps=[PlanStep(
        key="review", agent="Frame.io AI Assistant", tool_slug="frameio", operation=native.OPERATION,
        arguments=ARGS, reason="Review video with Frame.io own assistant", expected_output="Native assistant report")])
    async with database() as session:
        tool = await session.get(ToolConnection, "tool")
        tool.allowed_operations = native_operations("frameio")
        tool.config = {"managed_by": "native_oauth"}
        session.add(CapabilityManifest(workspace_id="w", tool_id="tool", provider_type="oauth", status="verified", manifest=native_manifest("frameio")))
        session.add(WorkflowRun(id="run", workspace_id="w", prompt="Native video review", inputs={}))
        await session.commit()
    monkeypatch.setattr(run_readiness, "_connection_credentials", AsyncMock(return_value=({}, {"identity": {"id": "owner"}}, None)))
    probe = AsyncMock(return_value={"file": {"id": FILE}})
    monkeypatch.setattr(run_readiness.ProviderExecutor, "execute", probe)
    ready = AsyncMock(return_value=False)
    monkeypatch.setattr(native, "readiness", ready)
    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        result = await run_readiness.check_run_readiness(session, run, plan)
        assert not result["passed"]
        check = next(row for row in result["checks"] if row.get("type") == "assistant")
        assert check["code"] == "assistant_signin_required"
        assert ACCOUNT in check["connect_path"] and FILE in check["connect_path"]
        probe.assert_awaited_once_with("frameio.file.get", {"account_id": ACCOUNT, "file_id": FILE})
        ready.return_value = True
        assert (await run_readiness.check_run_readiness(session, run, plan))["passed"]


def test_native_session_cannot_use_parallel_stateless_provider_path():
    from app.operation_contracts import enrich_operation
    module = next(row for row in native_manifest("frameio")["capabilities"] if row["name"] == native.OPERATION)
    assert enrich_operation(module)["reliability"]["concurrent_read"] is False
