"""Resolve a saved Sheets result to its native app tab without executing a run."""
import re
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy import select

from .execution_preflight import _connection_credentials
from .models import CapabilityManifest, RunStep, StepStatus, ToolConnection, ToolKind, WorkflowRun
from .providers import ProviderExecutor
from .run_readiness import account_fingerprint

SHEET_OPERATIONS = {"sheets.read", "sheets.append", "sheets.workbook.get", "sheets.kpi.create",
                    "sheets.campaign_report.get", "sheets.campaign_report.create"}


async def saved_sheet_screen(session, context, run_id, step_key):
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != context.workspace_id:
        raise HTTPException(404, "Run not found")
    step = await session.scalar(select(RunStep).where(RunStep.run_id == run.id, RunStep.step_key == step_key))
    if not step or step.status != StepStatus.completed or step.tool_slug != "google" or step.operation not in SHEET_OPERATIONS:
        raise HTTPException(404, "Saved Google Sheets result not found")
    output = step.output or {}
    receipt = output.get("provider_result") or {}
    arguments = output.get("resolved_arguments") or step.arguments or {}
    sid = receipt.get("spreadsheetId") or arguments.get("spreadsheet_id")
    cell_range = (receipt.get("updates") or {}).get("updatedRange") or receipt.get("range")
    if receipt.get("error") or receipt.get("isError") or not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        raise HTTPException(404, "Saved spreadsheet identity is unavailable")
    tool = await session.scalar(select(ToolConnection).where(
        ToolConnection.workspace_id == context.workspace_id, ToolConnection.slug == step.tool_slug))
    if not tool or not tool.enabled or tool.kind != ToolKind.oauth or (tool.config or {}).get("managed_by"):
        raise HTTPException(409, "The original Google connection is unavailable")
    if not {"sheets.read", "sheets.workbook.get", "sheets.campaign_report.get"}.intersection(tool.allowed_operations or []):
        raise HTTPException(403, "Google Sheets read access is required")
    manifest = await session.scalar(select(CapabilityManifest).where(
        CapabilityManifest.workspace_id == context.workspace_id, CapabilityManifest.tool_id == tool.id))
    if not manifest or manifest.status != "verified":
        raise HTTPException(409, "The Google connection needs verification")
    try:
        credentials, verification, blocker = await _connection_credentials(session, tool, manifest)
        if blocker:
            raise HTTPException(409, "The Google connection needs attention")
        binding = (run.execution_context or {}).get("__aura_review_readiness__", {}).get("bindings", {}).get(step.tool_slug)
        if binding and (binding.get("connection_id") != tool.id or binding.get("account_fingerprint") != account_fingerprint(tool, verification)):
            raise HTTPException(409, "The connected Google account differs from this run")
        # Fixed provider host, saved workbook ID and metadata-only field mask.
        # No append, write, dispatch, resume, or arbitrary provider URL is accepted.
        params = {"fields": "spreadsheetId,properties(title),sheets(properties(sheetId,title))"}
        if cell_range:
            params["ranges"] = cell_range
        metadata = await ProviderExecutor(credentials or {}, tool.base_url, timeout_seconds=15)._request(
            "GET", f"https://sheets.googleapis.com/v4/spreadsheets/{sid}", params=params)
        await session.commit()  # Retain an ordinary OAuth refresh, if needed.
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Google Sheets could not open its app preview. The saved cells remain available.") from exc
    properties = [sheet.get("properties") or {} for sheet in metadata.get("sheets", [])]
    tab_name = cell_range.rsplit("!", 1)[0] if cell_range and "!" in cell_range else None
    if tab_name and tab_name.startswith("'") and tab_name.endswith("'"):
        tab_name = tab_name[1:-1].replace("''", "'")
    tab = next((item for item in properties if item.get("title") == tab_name), {}) if tab_name else properties[0] if properties else {}
    gid = tab.get("sheetId")
    if not isinstance(gid, int) or isinstance(gid, bool) or gid < 0 or metadata.get("spreadsheetId") != sid:
        raise HTTPException(502, "Google Sheets did not return a matching tab")
    fragment = {"gid": gid}
    if cell_range:
        fragment["range"] = cell_range.rsplit("!", 1)[-1]
    suffix = urlencode(fragment)
    base = f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    return {"spreadsheetId": sid, "sheetId": gid, "range": cell_range,
            "title": (metadata.get("properties") or {}).get("title"), "tab": tab.get("title"),
            "link": f"{base}#{suffix}", "embedUrl": f"{base}?rm=minimal#{suffix}"}
