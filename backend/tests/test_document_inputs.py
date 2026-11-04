import base64
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from app import llm_planner, orchestrator
from app.native_connectors import native_manifest, native_operations
from app.orchestrator import _create_compiled_plan, _planning_prompt_with_documents
from app.schemas import RunCreate, WorkflowPlan
from app.workflow_context import resolve_value


def data_url(value: str, media_type: str = "text/plain") -> str:
    encoded = base64.b64encode(value.encode()).decode()
    return f"data:{media_type};base64,{encoded}"


def test_attached_text_is_available_to_planning_without_data_url_leakage():
    url = data_url("Revenue target: 42")
    prompt = _planning_prompt_with_documents(
        "Build the report",
        {"attached_documents": [{"name": "target.txt", "file_url": url, "size": 18}]},
    )

    assert "Revenue target: 42" in prompt
    assert "target.txt" in prompt
    assert url not in prompt
    assert "not fields on the upload metadata" in prompt


def test_run_create_rejects_non_aura_document_references():
    try:
        RunCreate(
            prompt="Build the report",
            inputs={"attached_documents": [{"name": "secret.txt", "file_url": "https://evil.test"}]},
        )
    except ValueError as error:
        assert "AURA upload reference" in str(error)
    else:
        raise AssertionError("external attachment URL should be rejected")


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_planning_repairs_missing_attachment_field_before_execution(monkeypatch, repair_succeeds):
    context = '{"campaign_context":{"client":"Fictional coffee shop","synthetic":true}}'
    inputs = {"attached_documents": [{"name": "campaign.json",
                                      "file_url": data_url(context, "application/json")}]}
    bad_path = "inputs.attached_documents.0.campaign_context"
    candidate = WorkflowPlan.model_validate({
        "name": "Synthetic campaign review", "interpretation": "Review supplied evidence",
        "steps": [{"key": "report", "agent": "AURA", "tool_slug": "aura",
                   "operation": "report.compose", "consequential": False,
                   "reason": "Compose the supplied evidence", "expected_output": "Review draft",
                   "arguments": {"title": "Campaign review", "instructions": "Review source",
                                 "synthetic": True, "sources": [{"id": "ClientContext",
                                 "title": "Client context", "content": "{{" + bad_path + "}}"}]}}],
    })
    corrected = candidate.model_copy(deep=True)
    corrected.steps[0].arguments["sources"][0]["content"] = context
    calls = []

    async def propose(*args, **_kwargs):
        calls.append(deepcopy(args))
        return (corrected if repair_succeeds and len(calls) == 2 else candidate).model_copy(deep=True)

    monkeypatch.setattr(orchestrator.get_settings(), "planner_mode", "llm")
    monkeypatch.setattr(llm_planner, "create_llm_plan", propose)
    execute = AsyncMock()
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    inventory = [{"slug": "aura", "name": "AURA Intelligence", "connected": True,
                  "allowed_operations": native_operations("aura")}]
    args = (_planning_prompt_with_documents("Prepare a review from the supplied evidence", inputs),
            inventory, set(inputs), {"aura": native_manifest("aura")})
    if repair_succeeds:
        plan = await _create_compiled_plan(*args, input_values=inputs)
        assert resolve_value(plan.steps[0].arguments, {"inputs": inputs})["sources"][0]["content"] == context
        assert plan.planning_artifacts["contract_repair_attempts"] == 1
    else:
        with pytest.raises(ValueError, match="unavailable input reference"):
            await _create_compiled_plan(*args, input_values=inputs)
    assert len(calls) == 2
    assert any(bad_path in requirement for requirement in calls[1][4])
    execute.assert_not_awaited()
