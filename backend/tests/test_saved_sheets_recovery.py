from copy import deepcopy
from types import SimpleNamespace

import pytest

from app import main
from app.models import RunStatus, StepStatus, WorkflowRun
from app.run_supervisor import public_run_projection


def saved_creation():
    return SimpleNamespace(
        id="created-sheet", status=StepStatus.failed, tool_slug="google-sheets",
        operation="google-sheets.new-spreadsheet", arguments={"title": "Plantea KPI"},
        output={"provider_result": {"ret": {
            "spreadsheetId": "existing-workbook", "title": "Plantea KPI",
            "worksheetName": "Dashboard",
        }}},
    )


def paused_run(stored=None):
    context = {
        "__aura_autonomy__": {"handoff_reason_code": "no_safe_recovery", "rounds": 3},
        "__aura_supervisor__": {"status": "operator_attention", "phase": "execution",
            "last_transition": {"reason": "autonomous_recovery_exhausted"}},
    }
    if stored:
        context["__aura_blocker__"] = stored
    return WorkflowRun(status=RunStatus.waiting_for_action, plan_approved=True,
        prompt="Create a KPI dashboard", result={"failed_step": {"id": "created-sheet"}},
        execution_context=context)


@pytest.mark.parametrize("status", [StepStatus.failed, StepStatus.running])
@pytest.mark.parametrize("stored", [None, {
    "code": "no_safe_recovery", "action": "inspect_run", "retryable": False,
}])
def test_saved_sheet_can_be_rechecked_after_automatic_recovery_ends(status, stored):
    run, step = paused_run(stored), saved_creation()
    step.status = status
    before = deepcopy(step.output)

    blocker = main._run_blocker(run, [step], {}, [], {step.id})
    public = public_run_projection(run, blocker)

    assert public["public_status"] == "blocked"
    assert public["public_blocker"]["action"] == "recheck_saved_result"
    assert public["public_blocker"]["retryable"] is True
    assert public["public_blocker"]["step_id"] == step.id
    assert step.output == before
    assert run.execution_context["__aura_autonomy__"]["rounds"] == 3


@pytest.mark.parametrize("change", [
    "no_receipt", "bad_identity", "different_title", "other_write", "completed_step",
    "unapproved_plan", "completed_run", "authorization_required",
])
def test_saved_sheet_recheck_does_not_guess_results_or_override_access(change):
    run, step = paused_run(), saved_creation()
    if change == "no_receipt":
        step.output = {}
    elif change == "bad_identity":
        step.output["provider_result"]["ret"]["spreadsheetId"] = "../other"
    elif change == "different_title":
        step.output["provider_result"]["ret"]["title"] = "Other workbook"
    elif change == "other_write":
        step.operation = "google-sheets.add-multiple-rows"
    elif change == "completed_step":
        step.status = StepStatus.completed
    elif change == "unapproved_plan":
        run.plan_approved = False
    elif change == "completed_run":
        run.status = RunStatus.completed
    else:
        run.execution_context = {"__aura_blocker__": {
            "code": "permission_required", "action": "reconnect_account",
        }}

    blocker = main._run_blocker(run, [step], {}, [], {step.id})

    assert not blocker or blocker["action"] != "recheck_saved_result"
    if change == "authorization_required":
        assert blocker == run.execution_context["__aura_blocker__"]


@pytest.mark.parametrize("status", [StepStatus.failed, StepStatus.running])
def test_saved_cell_update_exposes_read_only_recovery_after_handoff(status):
    run = paused_run({"code": "no_safe_recovery", "action": "inspect_run", "retryable": False})
    step = SimpleNamespace(id="saved-update", status=status, tool_slug="google-sheets",
        operation="google-sheets.update-multiple-rows",
        arguments={"sheetId": "saved_workbook_12345", "worksheetId": 0, "range": "A4:B4", "rows": [["Source", "Google Ads"]]},
        output={"provider_result": {"ret": {"spreadsheetId": "saved_workbook_12345", "updatedRange": "Summary!A4:B4", "updatedCells": 2}}})
    before = deepcopy(step.output)
    blocker = main._run_blocker(run, [step], {}, [], {step.id})
    assert blocker["action"] == "recheck_saved_result" and blocker["retryable"] is True
    assert step.output == before
    step.output["provider_result"]["ret"]["updatedCells"] = 1
    assert main._run_blocker(run, [step], {}, [], {step.id})["action"] == "inspect_run"
    step.output = before
    run.execution_context["__aura_blocker__"] = {"action": "reconnect_account"}
    assert main._run_blocker(run, [step], {}, [], {step.id})["action"] == "reconnect_account"
