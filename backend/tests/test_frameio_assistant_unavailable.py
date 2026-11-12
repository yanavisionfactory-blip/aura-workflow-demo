from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app import orchestrator, run_readiness
from app.frameio_assistant_contract import (
    OPERATION,
    UNAVAILABLE_MESSAGE,
    FrameioAssistantUnavailable,
    validate_native_assistant_plan,
)
from app.models import WorkflowRun, Workspace
from app.native_connectors import native_manifest, native_operations
from app.providers import ProviderExecutor
from app.schemas import PlanStep, WorkflowPlan


def native_plan():
    return WorkflowPlan(name="Saved native review", interpretation="Review the video", steps=[
        PlanStep(key="review", agent="Frame.io", tool_slug="frameio", operation=OPERATION,
                 arguments={}, reason="Review video", expected_output="Native assistant review"),
    ])


@pytest.mark.parametrize("operation", [OPERATION, "frameio.video.review", "intelligence.video.review", "report.compose"])
def test_explicit_native_request_cannot_reach_another_engine(operation):
    plan = SimpleNamespace(steps=[SimpleNamespace(operation=operation)])
    with pytest.raises(FrameioAssistantUnavailable):
        validate_native_assistant_plan("Use Frame.io's own AI Assistant to review the video", plan)
    if operation != OPERATION:
        validate_native_assistant_plan("Review the video with AURA Intelligence", plan)


async def test_native_request_stops_before_model_planning(monkeypatch):
    model = AsyncMock(side_effect=AssertionError("Unsupported requests must not call a model"))
    monkeypatch.setattr(orchestrator, "create_plan", model)
    with pytest.raises(FrameioAssistantUnavailable) as error:
        await orchestrator._create_compiled_plan("Use Frame.io AI Assistant to review this video", [], set(), {})
    model.assert_not_awaited()
    assert orchestrator.planning_error_message(error.value) == UNAVAILABLE_MESSAGE


async def test_stale_provider_operation_cannot_execute_or_fall_back():
    with pytest.raises(FrameioAssistantUnavailable):
        await ProviderExecutor({}, capability_manifest=native_manifest("frameio")).execute(OPERATION, {})
    plan = SimpleNamespace(steps=[SimpleNamespace(operation="frameio.video.review", fallback_operation=OPERATION)])
    with pytest.raises(FrameioAssistantUnavailable):
        validate_native_assistant_plan("Review the video", plan)
    assert OPERATION not in native_operations("frameio")
    assert {"frameio.file.get", "frameio.comments.list", "frameio.video.review"} <= set(native_operations("frameio"))


async def test_saved_native_plan_is_blocked_without_login_or_provider_request(database, monkeypatch):
    credentials = AsyncMock(side_effect=AssertionError("No reconnect or provider request"))
    monkeypatch.setattr(run_readiness, "_connection_credentials", credentials)
    async with database() as session:
        session.add(Workspace(id="native-withdrawal", name="Workspace"))
        run = WorkflowRun(id="saved-native", workspace_id="native-withdrawal", prompt="Review video", inputs={})
        session.add(run)
        await session.commit()
        report = await run_readiness.check_run_readiness(session, run, native_plan())
    assert not report["passed"]
    assert report["checks"] == [{"type": "capability", "tool_slug": "frameio", "operation": OPERATION,
                                  "status": "blocked", "code": "capability_unavailable", "message": UNAVAILABLE_MESSAGE}]
    credentials.assert_not_awaited()


async def test_application_does_not_mount_remote_signin_endpoints():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/frameio-assistant/sessions", json={})
    assert response.status_code == 404
