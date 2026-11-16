import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from app.internal_diagnostics import failure_category


def test_stop_category_never_exposes_raw_provider_or_customer_content():
    assert failure_category({'internal_error':'[authorization_required] private information'}) == 'authorization_required'
    assert failure_category({'internal_error':'provider response containing personal data'}) is None
    assert failure_category({'internal_error':'[private-token] secret'}) is None


async def test_managed_diagnostics_read_only_failed_tenant_bound_sessions(database, monkeypatch, caplog):
    import openai

    from app import internal_diagnostics as diagnostics
    from app import scheduler_runtime
    from app.config import get_settings
    from app.models import AuditEvent, RunStatus, WorkflowRun, Workspace

    monkeypatch.setattr(diagnostics, "SessionLocal", database)
    monkeypatch.setattr(scheduler_runtime, "_workspace_ids", AsyncMock(return_value=["w", "other"]))
    monkeypatch.setattr(get_settings(), "managed_agents_enabled", True)
    turns = AsyncMock(return_value=NS(data=[NS(id="turn-1", subagent_id=None, status="failed",
        error=NS(code="invalid_request", message="private project text, sk-secret, unsupported anyOf schema"))]))

    class Client:
        async def __aenter__(self):
            # No create/events/items API is available: diagnosis must only read status.
            return NS(beta=NS(agents=NS(sessions=NS(turns=NS(list=turns)))))
        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_: Client())
    async with database() as session:
        session.add_all([Workspace(id="w", name="One"), Workspace(id="other", name="Two")])
        session.add_all([WorkflowRun(id="r", workspace_id="w", prompt="private", status=RunStatus.failed),
            WorkflowRun(id="other-r", workspace_id="other", prompt="private", status=RunStatus.failed),
            WorkflowRun(id="active", workspace_id="w", prompt="private", status=RunStatus.running)])
        for run_id, sid, actor in [("r", "sess_good", "openai-agents-api"),
            ("r", "sess_good", "openai-agents-api"), ("other-r", "sess_wrong_tenant", "openai-agents-api"),
            ("active", "sess_active", "openai-agents-api"), ("r", "sess_forged", "other")]:
            session.add(AuditEvent(workspace_id="w", run_id=run_id, actor=actor,
                event_type="run.managed_agent_session", payload={"session_id": sid}))
        await session.commit()
    await diagnostics.log_recent_managed_failures_safely()
    turns.assert_awaited_once_with("sess_good", limit=10, order="desc")
    logs = [record.message for record in caplog.records if record.message.startswith("MANAGED_AGENT_STOP ")]
    assert len(logs) == 1
    payload = json.loads(logs[0].split(" ", 1)[1])
    assert payload["run_id"] == "r" and payload["code"] == "invalid_request"
    assert payload["markers"] == ["schema", "anyOf", "unsupported"]
    assert "private" not in caplog.text and "sk-secret" not in caplog.text
