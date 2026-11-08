"""Refresh temporary Canva preview URLs for an existing, tenant-scoped result."""
import asyncio
import re
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import select

from .broker_readback import readback_executor
from .execution_preflight import _connection_credentials
from .models import BrokerCapabilityPack, CapabilityManifest, RunStep, StepStatus, ToolConnection, WorkflowRun
from .providers import ProviderExecutor
from .run_readiness import account_fingerprint

OPERATIONS = {"canva.presentation.create", "canva.design.get", "canva.get-design", "canva.list-designs",
              "canva.create-design-import-job", "canva.get-design-import-job"}


def _body(receipt):
    if not isinstance(receipt, dict) or receipt.get("error") or receipt.get("isError"):
        return {}
    body = receipt.get("ret", receipt)
    return body if isinstance(body, dict) and not body.get("error") else {}


def _saved_design(step):
    output = step.output or {}
    body = _body(output.get("provider_result"))
    if step.operation == "canva.list-designs":
        query = (output.get("resolved_arguments") or step.arguments or {}).get("query")
        candidates = [item for item in body.get("items", []) if isinstance(item, dict)
                      and isinstance(query, str) and query.strip() and item.get("title") == query.strip()]
    elif "import-job" in step.operation:
        job = body.get("job") or {}
        candidates = (job.get("result") or {}).get("designs", []) if job.get("status") == "success" else []
    else:
        candidates = [body["design"]] if isinstance(body.get("design"), dict) else body.get("designs", [])
    if len(candidates) != 1 or not isinstance(candidates[0], dict):
        raise HTTPException(404, "A unique saved Canva design is unavailable")
    design = candidates[0]
    if not isinstance(design.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]+", design["id"]):
        raise HTTPException(404, "Saved Canva design identity is unavailable")
    return design


def _canva_url(value):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        if (url.scheme == "https" and not url.username and not url.password and url.port in (None, 443)
                and (url.hostname == "canva.com" or (url.hostname or "").endswith(".canva.com"))):
            return value
    except ValueError:
        pass
    return None


async def _read_design(session, tool, credentials, saved):
    allowed = set(tool.allowed_operations or [])
    if (tool.config or {}).get("managed_by") == "pipedream":
        pack = await session.get(BrokerCapabilityPack, tool.config.get("capability_pack_id"))
        capabilities = (pack.definition or {}).get("capabilities", []) if pack else []
        # The executor verifies the signature and read-only scope before any call.
        for operation in ("canva.get-design", "canva.list-designs"):
            capability = next((item for item in capabilities if item.get("name") == operation), None)
            if operation not in allowed or not capability:
                continue
            properties = (capability.get("input_schema") or {}).get("properties", {})
            if operation == "canva.get-design":
                key = next((key for key in ("designId", "design_id") if key in properties), None)
                if not key:
                    continue
                arguments = {key: saved["id"]}
            else:
                if not saved.get("title") or "query" not in properties:
                    continue
                arguments = {"query": saved["title"]}
            executor = await readback_executor(session, tool, {operation})
            return _body(await executor.execute(operation, arguments))
    elif not (tool.config or {}).get("managed_by") and "canva.design.get" in allowed:
        return _body(await ProviderExecutor(credentials or {}, tool.base_url, timeout_seconds=15).execute(
            "canva.design.get", {"design_id": saved["id"]}))
    raise HTTPException(403, "Canva design read access is required")


async def saved_canva_screen(session, context, run_id, step_key):
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != context.workspace_id:
        raise HTTPException(404, "Run not found")
    step = await session.scalar(select(RunStep).where(RunStep.run_id == run.id, RunStep.step_key == step_key))
    if not step or step.status != StepStatus.completed or step.tool_slug != "canva" or step.operation not in OPERATIONS:
        raise HTTPException(404, "Saved Canva result not found")
    saved = _saved_design(step)
    tool = await session.scalar(select(ToolConnection).where(
        ToolConnection.workspace_id == context.workspace_id, ToolConnection.slug == step.tool_slug))
    if not tool or not tool.enabled:
        raise HTTPException(409, "The original Canva connection is unavailable")
    manifest = await session.scalar(select(CapabilityManifest).where(
        CapabilityManifest.workspace_id == context.workspace_id, CapabilityManifest.tool_id == tool.id))
    if not manifest or manifest.status != "verified":
        raise HTTPException(409, "The Canva connection needs verification")
    try:
        async with asyncio.timeout(20):
            credentials, verification, blocker = await _connection_credentials(session, tool, manifest)
            if blocker:
                raise HTTPException(409, "The Canva connection needs attention")
            binding = (run.execution_context or {}).get("__aura_review_readiness__", {}).get("bindings", {}).get(step.tool_slug)
            if binding and (binding.get("connection_id") != tool.id or binding.get("account_fingerprint") != account_fingerprint(tool, verification)):
                raise HTTPException(409, "The connected Canva account differs from this run")
            body = await _read_design(session, tool, credentials, saved)
            candidates = [body["design"]] if isinstance(body.get("design"), dict) else body.get("items", [])
            matches = [item for item in candidates if isinstance(item, dict) and item.get("id") == saved["id"]]
            if len(matches) != 1:
                raise ValueError("No unique matching design")
            design = matches[0]
            thumbnail = _canva_url((design.get("thumbnail") or {}).get("url"))
            if not thumbnail:
                raise ValueError("No safe preview URL")
            urls = design.get("urls") or {}
            screen = {"designId": saved["id"], "thumbnailUrl": thumbnail,
                      "link": _canva_url(urls.get("edit_url")), "viewLink": _canva_url(urls.get("view_url"))}
            await session.commit()  # Keep ordinary credential refresh; never rewrite saved receipts.
            return screen
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Canva preview could not be refreshed. The saved design is unchanged.") from exc
