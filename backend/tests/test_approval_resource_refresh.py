from types import SimpleNamespace

from app import main
from app.models import Approval, WorkflowRun, RunStep
from app.schemas import ApprovalDecision


async def test_stale_job_preview_refreshes_without_approval_or_dispatch(monkeypatch):
    approval = SimpleNamespace(id="approval", run_id="run", step_id="step", status="pending",
        preview={"arguments": {"design_id": "job", "format": "pdf"}})
    run = SimpleNamespace(id="run", workspace_id="tenant", execution_context={"steps": {
        "create": {"provider_result": {"job": {"id": "job", "status": "success",
            "result": {"designs": [{"id": "design"}]}}}}}})
    step = SimpleNamespace(operation="canva.export.create")
    class Session:
        committed = False
        async def get(self, model, identifier):
            return {Approval: approval, WorkflowRun: run, RunStep: step}[model]
        async def commit(self):
            self.committed = True
    async def no_dispatch(*args):
        raise AssertionError("A refreshed preview must not dispatch")
    monkeypatch.setattr(main, "dispatch_pending", no_dispatch)
    session = Session()
    result = await main.decide_approval("approval", ApprovalDecision(approved=True,
        edited_arguments={"design_id": "job", "format": "pdf"}),
        SimpleNamespace(workspace_id="tenant"), session)
    assert result["status"] == approval.status == "pending"
    assert approval.preview["arguments"] == {"design_id": "design", "format": "pdf"}
    assert session.committed
