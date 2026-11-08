from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app import broker_readback, canva_screen
from app.models import (
    BrokerCapabilityPack,
    CapabilityManifest,
    RunStep,
    StepStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)

READ = "canva.list-designs"
DESIGN = {"id": "saved-design", "title": "Campaign comparison", "thumbnail": {"url": "https://media.canva.com/fresh.jpg"},
          "urls": {"edit_url": "https://www.canva.com/design/saved-design/edit"}}


async def seed(database, monkeypatch):
    call = AsyncMock(return_value={"ret": {"items": [{**DESIGN, "id": "unrelated"}, deepcopy(DESIGN)]}})
    monkeypatch.setattr(canva_screen, "_connection_credentials", AsyncMock(return_value=({}, {"identity": {"sub": "owner"}}, None)))
    monkeypatch.setattr(broker_readback, "pack_signature_valid", lambda pack: pack.signature == "valid")
    monkeypatch.setattr(broker_readback, "pipedream_client_for_tool", lambda tool: SimpleNamespace(run_action=call))
    capability = {"name": READ, "permission_scope": "read", "requires_approval": False,
                  "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                  "output_schema": {"type": "object"}}
    async with database() as session:
        session.add(Workspace(id="w", name="Workspace"))
        session.add(WorkflowRun(id="run", workspace_id="w", prompt="Report", status="completed"))
        session.add(RunStep(id="step", run_id="run", position=0, step_key="verify", agent="reader", tool_slug="canva",
                           operation=READ, status=StepStatus.completed, idempotency_key="saved", arguments={"query": DESIGN["title"]},
                           output={"provider_result": {"ret": {"items": [deepcopy(DESIGN)]}}}))
        session.add(ToolConnection(id="canva", workspace_id="w", slug="canva", display_name="Canva", kind=ToolKind.oauth,
                                   enabled=True, allowed_operations=[READ], config={"managed_by": "pipedream", "account_id": "account",
                                   "external_user_id": "user", "capability_pack_id": "pack", "capability_pack_hash": "hash"}))
        session.add(CapabilityManifest(tool_id="canva", workspace_id="w", provider_type="oauth", status="verified", manifest={}))
        session.add(BrokerCapabilityPack(id="pack", backend="pipedream", provider_slug="canva", display_name="Canva", version=1,
                                        status="released", definition_hash="hash", signature="valid", definition={"capabilities": [capability]}))
        await session.commit()
    return call


async def test_refreshes_exact_saved_design_through_signed_read_without_rerunning(database, monkeypatch):
    call = await seed(database, monkeypatch)
    async with database() as session:
        original = deepcopy((await session.get(RunStep, "step")).output)
        screen = await canva_screen.saved_canva_screen(session, SimpleNamespace(workspace_id="w"), "run", "verify")
        assert screen["designId"] == DESIGN["id"] and screen["thumbnailUrl"] == DESIGN["thumbnail"]["url"]
        args = call.call_args.args
        assert args[:2] == ("user", "account") and args[2]["name"] == READ and args[3] == {"query": DESIGN["title"]}
        assert call.await_count == 1
        assert (await session.get(RunStep, "step")).output == original
        assert (await session.get(WorkflowRun, "run")).status == "completed"


@pytest.mark.parametrize("case", ["tenant", "step", "failed", "operation", "disabled", "permissions", "account", "signature", "write_scope", "ambiguous", "receipt_error"])
async def test_denies_untrusted_or_unrelated_reads_before_provider_call(database, monkeypatch, case):
    call = await seed(database, monkeypatch)
    async with database() as session:
        step = await session.get(RunStep, "step")
        tool = await session.get(ToolConnection, "canva")
        pack = await session.get(BrokerCapabilityPack, "pack")
        run = await session.get(WorkflowRun, "run")
        if case == "failed": step.status = StepStatus.failed
        if case == "operation": step.operation = "canva.delete-design"
        if case == "disabled": tool.enabled = False
        if case == "permissions": tool.allowed_operations = ["canva.create-design"]
        if case == "account": run.execution_context = {"__aura_review_readiness__": {"bindings": {"canva": {"connection_id": "different"}}}}
        if case == "signature": pack.signature = "invalid"
        if case == "write_scope": pack.definition = {"capabilities": [{**pack.definition["capabilities"][0], "permission_scope": "write"}]}
        if case == "ambiguous": step.output = {"provider_result": {"ret": {"items": [DESIGN, DESIGN]}}}
        if case == "receipt_error": step.output = {"provider_result": {"error": "failed"}}
        await session.commit()
        with pytest.raises(HTTPException):
            await canva_screen.saved_canva_screen(session, SimpleNamespace(workspace_id="other" if case == "tenant" else "w"), "run", "other" if case == "step" else "verify")
        call.assert_not_awaited()


@pytest.mark.parametrize("response", [{"items": [{**DESIGN, "id": "wrong"}]}, {"items": [DESIGN, DESIGN]},
    {"items": [{**DESIGN, "thumbnail": {"url": "https://canva.com.attacker.example/image"}}]}, {"error": "SECRET"}])
async def test_bad_provider_responses_never_replace_saved_result(database, monkeypatch, response):
    call = await seed(database, monkeypatch)
    call.return_value = {"ret": response}
    async with database() as session:
        with pytest.raises(HTTPException) as exc:
            await canva_screen.saved_canva_screen(session, SimpleNamespace(workspace_id="w"), "run", "verify")
        assert exc.value.status_code == 502 and "SECRET" not in exc.value.detail
        assert (await session.get(RunStep, "step")).status == StepStatus.completed


async def test_import_receipt_and_get_design_capability(database, monkeypatch):
    call = await seed(database, monkeypatch)
    call.return_value = {"ret": {"design": DESIGN}}
    async with database() as session:
        step = await session.get(RunStep, "step")
        step.operation = "canva.get-design-import-job"
        step.output = {"provider_result": {"ret": {"job": {"status": "success", "result": {"designs": [DESIGN]}}}}}
        tool = await session.get(ToolConnection, "canva")
        tool.allowed_operations = ["canva.get-design"]
        pack = await session.get(BrokerCapabilityPack, "pack")
        pack.definition = {"capabilities": [{"name": "canva.get-design", "permission_scope": "read", "requires_approval": False,
                            "input_schema": {"type": "object", "properties": {"designId": {"type": "string"}}, "required": ["designId"]}}]}
        await session.commit()
        assert (await canva_screen.saved_canva_screen(session, SimpleNamespace(workspace_id="w"), "run", "verify"))["designId"] == DESIGN["id"]
        assert call.call_args.args[3] == {"designId": DESIGN["id"]}
