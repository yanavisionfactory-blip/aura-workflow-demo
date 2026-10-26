import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException

from app import sheet_screen
from app.models import (
    CapabilityManifest,
    RunStep,
    StepStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)


async def seed(database, monkeypatch):
    calls = []
    async def credentials(*_):
        return {"access_token": "NEVER_RETURN_THIS"}, {"identity": {"sub": "account"}}, None
    async def request(self, method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {"spreadsheetId": "workbook", "properties": {"title": "Pilot"}, "sheets": [
            {"properties": {"title": "Source", "sheetId": 1}},
            {"properties": {"title": "Pilot Record", "sheetId": 77}}]}
    monkeypatch.setattr(sheet_screen, "_connection_credentials", credentials)
    monkeypatch.setattr(sheet_screen.ProviderExecutor, "_request", request)
    async with database() as session:
        session.add(Workspace(id="w", name="Workspace"))
        session.add(WorkflowRun(id="run", workspace_id="w", prompt="Pilot", status="completed"))
        session.add(RunStep(id="step", run_id="run", position=0, step_key="verify", agent="reader",
                            tool_slug="google", operation="sheets.read", status=StepStatus.completed,
                            idempotency_key="read", arguments={"spreadsheet_id": "workbook"},
                            output={"provider_result": {"range": "'Pilot Record'!A49:B52", "values": [["Saved"]]}}))
        session.add(ToolConnection(id="google", workspace_id="w", slug="google", display_name="Google",
                                   kind=ToolKind.oauth, enabled=True, allowed_operations=["sheets.read"]))
        session.add(CapabilityManifest(tool_id="google", workspace_id="w", provider_type="oauth", status="verified", manifest={}))
        await session.commit()
    return calls


async def test_screen_uses_saved_target_and_exact_tab_without_execution(database, monkeypatch):
    calls = await seed(database, monkeypatch)
    async with database() as session:
        result = await sheet_screen.saved_sheet_screen(session, SimpleNamespace(workspace_id="w"), "run", "verify")
        assert result["sheetId"] == 77
        assert parse_qs(urlsplit(result["embedUrl"]).fragment) == {"gid": ["77"], "range": ["A49:B52"]}
        assert "NEVER_RETURN_THIS" not in json.dumps(result)
        assert calls == [("GET", "https://sheets.googleapis.com/v4/spreadsheets/workbook", {"params": {
            "fields": "spreadsheetId,properties(title),sheets(properties(sheetId,title))", "ranges": "'Pilot Record'!A49:B52"}})]
        assert (await session.get(WorkflowRun, "run")).status == "completed"
        assert (await session.get(RunStep, "step")).output["provider_result"]["values"] == [["Saved"]]


@pytest.mark.parametrize("case", ["tenant", "step", "failed", "operation", "disabled", "permissions", "account", "untrusted_id", "receipt_error"])
async def test_screen_rejects_unrelated_or_unauthorized_reads(database, monkeypatch, case):
    calls = await seed(database, monkeypatch)
    async with database() as session:
        step = await session.get(RunStep, "step")
        tool = await session.get(ToolConnection, "google")
        run = await session.get(WorkflowRun, "run")
        if case == "failed": step.status = StepStatus.failed
        if case == "operation": step.operation = "mail.send"
        if case == "disabled": tool.enabled = False
        if case == "permissions": tool.allowed_operations = ["sheets.append"]
        if case == "account": run.execution_context = {"__aura_review_readiness__": {"bindings": {"google": {"connection_id": "another"}}}}
        if case == "untrusted_id": step.arguments = {"spreadsheet_id": "../other?token=secret"}
        if case == "receipt_error": step.output = {"provider_result": {"error": "Failed"}}
        await session.commit()
        with pytest.raises(HTTPException):
            await sheet_screen.saved_sheet_screen(session, SimpleNamespace(workspace_id="other" if case == "tenant" else "w"), "run", "other" if case == "step" else "verify")
        assert calls == []


async def test_screen_failure_is_sanitized_and_preserves_saved_result(database, monkeypatch):
    await seed(database, monkeypatch)
    async def broken(*args, **kwargs):
        raise ValueError("SECRET provider response")
    monkeypatch.setattr(sheet_screen.ProviderExecutor, "_request", broken)
    async with database() as session:
        with pytest.raises(HTTPException) as exc:
            await sheet_screen.saved_sheet_screen(session, SimpleNamespace(workspace_id="w"), "run", "verify")
        assert exc.value.status_code == 502 and "SECRET" not in exc.value.detail
        assert (await session.get(RunStep, "step")).status == StepStatus.completed
